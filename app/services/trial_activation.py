"""Confirm a trial's actual-use deadline without resetting its VPN identity."""

import logging

from sqlalchemy import select

from app.db.models import PaidLink, TrialLink
from app.integrations.xui.trial_keys import TrialKeyClient
from app.services.commerce import utc
from app.services.trial_pool import confirm_activation


async def reconcile_activations(sessions, settings, config):
    async with sessions() as db:
        identities = list(
            await db.scalars(
                select(TrialLink.id).where(
                    TrialLink.status == "ACTIVATING",
                    TrialLink.activation_deadline_ms.is_not(None),
                    TrialLink.pending_uuid.is_(None),
                    TrialLink.user_id.is_not(None),
                )
            )
        )
    if not identities:
        return
    client = TrialKeyClient(config["base_url"], config["api_token"], config["inbound_id"])
    try:
        for identity in identities:
            async with sessions() as db:
                record = await db.get(TrialLink, identity)
                if await db.scalar(
                    select(PaidLink.id).where(PaidLink.client_uuid == record.client_uuid)
                ):
                    continue
                key, email, deadline, issued, baseline = (
                    record.client_uuid,
                    record.panel_email,
                    record.activation_deadline_ms,
                    utc(record.issued_at),
                    record.baseline_bytes,
                )
            try:
                await client.confirm_trial_deadline(key, email, deadline, issued, baseline)
            except Exception as error:
                logging.getLogger("aera").error(
                    "trial_activation_failed type=%s", type(error).__name__
                )
                continue
            async with sessions.begin() as db:
                record = await db.get(TrialLink, identity)
                if (
                    record.user_id
                    and record.client_uuid == key
                    and record.activation_deadline_ms == deadline
                    and not record.pending_uuid
                ):
                    await confirm_activation(db, record, settings)
    finally:
        await client.close()
