"""Import owner-supplied keys without embedding plaintext secrets in the source ZIP."""

import json
from pathlib import Path

from sqlalchemy import select

from app.core.security import TokenVault
from app.db.models import AppSetting, Plan
from app.services.catalog import catalog
from app.services.portal import backfill_access
from app.services.trial_pool import import_links


async def bootstrap(db, settings):
    # Apply this catalog revision once; later owner edits remain intact.
    if not await db.get(AppSetting, "portal_catalog_v2"):
        for values in catalog():
            plan = await db.scalar(select(Plan).where(Plan.slug == values["slug"]))
            if plan:
                for key in ("device_limit", "unlimited_devices", "description", "sort_order"):
                    setattr(plan, key, values[key])
            else:
                db.add(Plan(**values))
        db.add(AppSetting(key="portal_catalog_v2", value="true"))
        await db.flush()
    await backfill_access(db)
    path = Path(__file__).resolve().parents[1] / "private-bootstrap.enc"
    if path.exists():
        payload = json.loads(TokenVault(settings.bot_token).reveal(path.read_text().strip()))
        vault = TokenVault(settings.app_secret)
        await import_links(db, payload["trial_links"], vault)
        from app.services.paid_pool import import_paid_links

        await import_paid_links(db, payload.get("paid_links", {}), vault)
        if "observer" in payload:
            stored = await db.get(AppSetting, "trial_observer")
            encrypted = vault.cipher.encrypt(json.dumps(payload["observer"]).encode()).decode()
            if stored:
                stored.value = encrypted
            else:
                db.add(AppSetting(key="trial_observer", value=encrypted))
        # The ciphertext may be re-imported safely; no assigned key is overwritten.
    if not await db.get(AppSetting, "portal_stars_v2"):
        # Owner delegated pricing. Fixed catalogue, based on official Telegram reward
        # $0.013/star and CBR USD rate at the release date; adjustable in owner panel.
        for values in catalog():
            plan = await db.scalar(select(Plan).where(Plan.slug == values["slug"]))
            from decimal import ROUND_CEILING, Decimal

            plan.stars_price = int(
                (Decimal(plan.price_minor) / 100 / Decimal("1.0852907")).to_integral_value(
                    rounding=ROUND_CEILING
                )
            )
        db.add(AppSetting(key="portal_stars_v2", value="true"))
        enabled = await db.get(AppSetting, "manual_stars_enabled")
        if enabled is None:
            db.add(AppSetting(key="manual_stars_enabled", value="true"))
    # Old queued selections should not announce manual checkout after this update.
    from sqlalchemy import update

    from app.db.models import Notification

    await db.execute(
        update(Notification)
        .where(
            Notification.notification_type == "TARIFF_REQUEST",
            Notification.status == "PENDING",
        )
        .values(status="CANCELLED")
    )
    await db.execute(
        update(Notification)
        .where(
            Notification.notification_type == "TRIAL_ACTIVE",
            Notification.status == "PENDING",
            ~Notification.dedupe_key.contains(":verified:"),
        )
        .values(status="CANCELLED")
    )
