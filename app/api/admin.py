import hmac
from typing import Literal

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.config import get_settings
from app.db.models import Plan, PromoCode, Server, Subscription, SupportTicket, User
from app.db.session import sessions
from app.services.admin import AdminService
from app.services.settings import set_setting

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


def authorize(token: str, admin_id: int) -> None:
    settings = get_settings()
    if (
        not settings.admin_api_token
        or not hmac.compare_digest(token, settings.admin_api_token)
        or admin_id not in settings.admin_ids
    ):
        raise HTTPException(403, "Administrator required")


class PlanInput(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    slug: str = Field(pattern=r"^[a-z0-9-]{1,64}$")
    description: str = ""
    price_minor: int = Field(gt=0)
    currency: Literal["RUB", "XTR"] = "RUB"
    stars_price: int | None = Field(default=None, gt=0)
    crypto_asset: Literal["USDT", "TON", "BTC", "ETH", "LTC", "BNB", "TRX", "USDC"] | None = None
    crypto_amount: str | None = Field(default=None, pattern=r"^[0-9]+(\.[0-9]+)?$")
    duration_days: int = Field(gt=0, le=3650)
    duration_months: int | None = Field(default=None, gt=0, le=120)
    traffic_limit_bytes: int = Field(ge=0)
    device_limit: int = Field(gt=0, le=100)
    unlimited_devices: bool = False
    is_active: bool = True
    is_featured: bool = False
    sort_order: int = 0


class AccessInput(BaseModel):
    action: Literal["extend", "disable", "enable", "rotate", "revoke"]
    confirmed: bool = False
    days: int = Field(default=30, gt=0, le=3650)


class PromoInput(BaseModel):
    code: str = Field(pattern=r"^[A-Z0-9_-]{3,64}$")
    discount_type: Literal["PERCENT", "FIXED_AMOUNT", "EXTRA_DAYS"]
    discount_value: int = Field(gt=0)
    max_uses: int = Field(gt=0)
    plan_id: str | None = None


class ReplyInput(BaseModel):
    text: str = Field(min_length=1, max_length=3500)
    close: bool = False


class BroadcastInput(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    confirmed: bool = False
    image_file_id: str | None = None
    button_text: str | None = None
    button_url: str | None = None


class SettingInput(BaseModel):
    value: str = Field(max_length=4000)


@router.get("/analytics")
async def analytics(
    x_admin_token: str = Header(default=""), x_admin_telegram_id: int = Header(default=0)
) -> dict:
    authorize(x_admin_token, x_admin_telegram_id)
    async with sessions() as db:
        return await AdminService(db, get_settings(), x_admin_telegram_id).analytics()


@router.get("/{resource}")
async def list_resource(
    resource: str,
    offset: int = 0,
    limit: int = 25,
    x_admin_token: str = Header(default=""),
    x_admin_telegram_id: int = Header(default=0),
) -> list[dict]:
    authorize(x_admin_token, x_admin_telegram_id)
    models = {
        "users": User,
        "plans": Plan,
        "subscriptions": Subscription,
        "servers": Server,
        "support": SupportTicket,
    }
    if resource not in models:
        raise HTTPException(404)
    async with sessions() as db:
        records = await db.scalars(
            select(models[resource]).offset(max(offset, 0)).limit(max(1, min(limit, 100)))
        )
        return [
            {c.name: getattr(record, c.key) for c in record.__table__.columns} for record in records
        ]


@router.post("/plans")
@router.put("/plans/{plan_id}")
async def save_plan(
    payload: PlanInput,
    plan_id: str | None = None,
    x_admin_token: str = Header(default=""),
    x_admin_telegram_id: int = Header(default=0),
) -> dict:
    authorize(x_admin_token, x_admin_telegram_id)
    async with sessions.begin() as db:
        record = await db.get(Plan, plan_id) if plan_id else Plan()
        if record is None:
            raise HTTPException(404)
        for key, value in payload.model_dump().items():
            setattr(record, key, value)
        db.add(record)
        await db.flush()
        AdminService(db, get_settings(), x_admin_telegram_id).audit("plan_save", "Plan", record.id)
    return {"id": record.id}


@router.post("/users/{user_id}/access")
async def change_access(
    user_id: str,
    payload: AccessInput,
    x_admin_token: str = Header(default=""),
    x_admin_telegram_id: int = Header(default=0),
) -> dict:
    authorize(x_admin_token, x_admin_telegram_id)
    async with sessions.begin() as db:
        await AdminService(db, get_settings(), x_admin_telegram_id).change_access(
            user_id, payload.action, payload.confirmed, payload.days
        )
    return {"status": "queued"}


@router.post("/promos")
async def create_promo(
    payload: PromoInput,
    x_admin_token: str = Header(default=""),
    x_admin_telegram_id: int = Header(default=0),
) -> dict:
    authorize(x_admin_token, x_admin_telegram_id)
    if payload.discount_type == "PERCENT" and payload.discount_value >= 100:
        raise HTTPException(422, "Discount must be below 100 percent")
    async with sessions.begin() as db:
        record = PromoCode(**payload.model_dump())
        db.add(record)
        await db.flush()
        AdminService(db, get_settings(), x_admin_telegram_id).audit(
            "promo_create", "PromoCode", record.id
        )
    return {"id": record.id}


@router.post("/support/{ticket_id}/reply")
async def reply(
    ticket_id: str,
    payload: ReplyInput,
    x_admin_token: str = Header(default=""),
    x_admin_telegram_id: int = Header(default=0),
) -> dict:
    authorize(x_admin_token, x_admin_telegram_id)
    async with sessions.begin() as db:
        await AdminService(db, get_settings(), x_admin_telegram_id).reply_ticket(
            ticket_id, payload.text, payload.close
        )
    return {"status": "queued"}


@router.post("/broadcasts")
async def broadcast(
    payload: BroadcastInput,
    x_admin_token: str = Header(default=""),
    x_admin_telegram_id: int = Header(default=0),
) -> dict:
    authorize(x_admin_token, x_admin_telegram_id)
    async with sessions.begin() as db:
        record = await AdminService(db, get_settings(), x_admin_telegram_id).broadcast(
            **payload.model_dump()
        )
    return {"id": record.id, "total": record.total}


@router.put("/settings/{key}")
async def update_setting(
    key: str,
    payload: SettingInput,
    x_admin_token: str = Header(default=""),
    x_admin_telegram_id: int = Header(default=0),
) -> dict:
    authorize(x_admin_token, x_admin_telegram_id)
    allowed = {
        "maintenance_mode",
        "trial_enabled",
        "trial_days",
        "referral_reward_days",
        "support_username",
        "ios_client_url",
        "android_client_url",
        "windows_client_url",
        "macos_client_url",
        "privacy_text",
        "terms_text",
        "terms_version",
    }
    if key not in allowed:
        raise HTTPException(422, "Unsupported setting")
    async with sessions.begin() as db:
        await set_setting(db, key, payload.value)
        AdminService(db, get_settings(), x_admin_telegram_id).audit(
            "setting_update", "AppSetting", key
        )
    return {"ok": True}
