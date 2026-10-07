"""Localized manual customer journey. Runs before legacy automated checkout."""

import logging
import math
from datetime import UTC, datetime, timedelta
from html import escape

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message, WebAppInfo
from sqlalchemy import func, select

from app.bot.keyboards import keyboard
from app.bot.presentation import edit_screen, send_screen
from app.bot.texts.portal import LANGUAGES, devices, period
from app.bot.texts.portal import text as tr
from app.bot.texts.privacy import privacy_page
from app.config import get_settings
from app.core.security import TokenVault
from app.db.models import (
    ManualAccess,
    Payment,
    Plan,
    Referral,
    ReferralCoupon,
    SaleOrder,
    SupportMessage,
    SupportTicket,
    TrialLink,
)
from app.db.session import sessions
from app.services.catalog import FAMILIES, family_of
from app.services.commerce import CommerceService, utc
from app.services.notifications import enqueue
from app.services.portal import ensure_order
from app.services.requests import paid_requests, select_tariff

router = Router(name="manual_portal")
router.message.filter(lambda event: get_settings().manual_sales)
router.callback_query.filter(lambda event: get_settings().manual_sales)


class HelpFlow(StatesGroup):
    message = State()


def home_menu(lang):
    items = [
        ("plans", "plans"),
        ("menu_trial", "trial"),
        ("profile", "profile"),
        ("connect", "connect"),
        ("menu_referral", "referral"),
        ("menu_how", "how"),
        ("requests", "subscription"),
        ("support", "support"),
        ("lang", "language"),
        ("menu_privacy", "privacy:0"),
    ]
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=tr(k, lang), callback_data=d) for k, d in items[i : i + 2]]
            for i in range(0, len(items), 2)
        ] + [
            [InlineKeyboardButton(text={"ru":"Соглашение","en":"User agreement","zh":"用户协议","fa":"توافق‌نامه"}.get(lang,"User agreement"), url="https://aera-reserve.duckdns.org/terms?lang=" + ("en" if lang != "ru" else "ru")),
             InlineKeyboardButton(text={"ru":"Политика данных","en":"Privacy policy","zh":"隐私政策","fa":"سیاست حریم خصوصی"}.get(lang,"Privacy policy"), url="https://aera-reserve.duckdns.org/privacy?lang=" + ("en" if lang != "ru" else "ru"))],
            [InlineKeyboardButton(text="Поддержка / Support", url="https://aera-reserve.duckdns.org/support"), InlineKeyboardButton(text="AERA VPN", url="https://aera-reserve.duckdns.org")],
        ]
    )


def languages(lang="ru"):
    entries = list(LANGUAGES.items())
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=("✅ " if code == lang else "") + label, callback_data="language:" + code
                )
                for code, label in entries[i : i + 2]
            ]
            for i in (0, 2)
        ]
    )


def actions(lang, *items):
    return keyboard(*[(tr(k, lang), d) for k, d in items], (tr("home", lang), "menu"))


async def get_user(db, sender):
    return await CommerceService(db, TokenVault(get_settings().app_secret)).user(
        sender.id, username=sender.username, first_name=sender.first_name
    )


@router.message(Command("start", "help"))
async def start(message: Message, state: FSMContext):
    await state.clear()
    async with sessions.begin() as db:
        user = await get_user(db, message.from_user)
        parts = (message.text or "").split(maxsplit=1)
        if len(parts) == 2 and parts[1].startswith("ref_"):
            from app.services.referrals import register_referral

            await register_referral(db, user, parts[1][4:])
        lang = user.language_code
    await send_screen(message, tr("language", lang), reply_markup=languages(lang))


@router.message(Command("privacy", "terms", "support", "paysupport"))
async def commands(message: Message, state: FSMContext):
    async with sessions.begin() as db:
        user = await get_user(db, message.from_user)
        lang = user.language_code
    cmd = (message.text or "").split()[0].split("@")[0]
    if cmd in {"/support", "/paysupport"}:
        await state.set_state(HelpFlow.message)
        await message.answer(
            tr("support_info", lang), parse_mode="HTML", reply_markup=actions(lang)
        )
    else:
        await message.answer(
            privacy_page(lang, 0) if cmd == "/privacy" else tr("terms", lang),
            parse_mode="HTML",
            reply_markup=actions(lang, ("privacy", "privacy:0")),
        )


@router.message(HelpFlow.message, F.text, ~F.text.startswith("/"))
async def support_message(message: Message, state: FSMContext):
    settings = get_settings()
    async with sessions.begin() as db:
        user = await get_user(db, message.from_user)
        lang = user.language_code
        if len(message.text) > 4000:
            await message.answer(tr("error", lang))
            return
        ticket = SupportTicket(user_id=user.id, category="Поддержка", subject="💬 Вопрос из бота")
        db.add(ticket)
        await db.flush()
        db.add(
            SupportMessage(
                ticket_id=ticket.id, sender_type="USER", sender_id=user.id, text=message.text
            )
        )
        for identity in settings.admin_ids:
            admin = await CommerceService(db, TokenVault(settings.app_secret)).user(identity)
            await enqueue(
                db,
                f"ticket:{ticket.id}:{identity}",
                admin.id,
                "SUPPORT_ADMIN",
                f"💊 Новое обращение № {ticket.id[:8]}. Открой поддержку в /admin.",
            )
    await state.clear()
    await message.answer(
        tr("ticket_sent", lang, number=ticket.id[:8]), reply_markup=home_menu(lang)
    )


def expiry_copy(deadline, lang):
    hours = max(0, math.ceil((utc(deadline) - datetime.now(UTC)).total_seconds() / 3600))
    return tr(
        "expiry",
        lang,
        date=utc(deadline).strftime("%d.%m.%Y %H:%M"),
        days=hours // 24,
        hours=hours % 24,
    )


async def profile_copy(db, user, lang):
    from app.services.paid_pool import current, latest

    paid = await current(db, user.id) or await latest(db, user.id)
    access = await db.scalar(select(ManualAccess).where(ManualAccess.user_id == user.id))
    trial = await db.scalar(select(TrialLink).where(TrialLink.user_id == user.id))
    status, plan, expiry = tr("none", lang), "AERA", ""
    if paid:
        p = await db.get(Plan, paid.plan_id)
        plan = p.name + " · " + devices(p, lang)
        recent = paid.checked_at and utc(paid.checked_at) > datetime.now(UTC) - timedelta(minutes=2)
        status = tr(
            "EXPIRED"
            if paid.expires_at and utc(paid.expires_at) <= datetime.now(UTC)
            else paid.status
            if recent and paid.status in {"ACTIVE", "WAITING", "EXPIRED"}
            else "UNKNOWN",
            lang,
        )
        expiry = (
            expiry_copy(paid.expires_at, lang)
            if paid.expires_at
            else tr(
                "paid_waiting",
                lang,
                days=(paid.duration_ms or p.duration_days * 86400000) // 86400000,
            )
        )
    elif access:
        plan = (await db.get(Plan, access.plan_id)).name
        status = tr("ACTIVE" if utc(access.expires_at) > datetime.now(UTC) else "EXPIRED", lang)
        expiry = expiry_copy(access.expires_at, lang)
    elif trial:
        plan = tr("trial", lang)
        recent = trial.checked_at and utc(trial.checked_at) > datetime.now(UTC) - timedelta(
            minutes=2
        )
        status = tr(
            trial.status
            if recent and trial.status in {"ACTIVE", "WAITING", "EXPIRED", "ACTIVATING", "BLOCKED"}
            else "UNKNOWN",
            lang,
        )
        expiry = (
            tr("trial_confirming", lang)
            if trial.status == "ACTIVATING"
            else expiry_copy(trial.expires_at, lang)
            if trial.expires_at
            else tr("waiting_time", lang)
        )
    return tr(
        "profile_info",
        lang,
        name=escape(user.first_name or user.username or "AERA"),
        status=status,
        plan=escape(plan),
        expiry=expiry,
    )


@router.callback_query(lambda call: not (call.data or "").startswith("ad:"))
async def navigate(call: CallbackQuery, state: FSMContext):
    await call.answer()
    await state.clear()
    settings = get_settings()
    vault = TokenVault(settings.app_secret)
    data = call.data or "menu"
    lang = "ru"
    art = "welcome"
    invoice = None
    send_file = False
    try:
        async with sessions.begin() as db:
            user = await get_user(db, call.from_user)
            lang = user.language_code
            if user.is_blocked or not user.is_active:
                raise ValueError("Account unavailable")
            markup = actions(lang)
            body = tr("welcome", lang)
            if data.startswith("language:"):
                lang = data.split(":")[1]
                if lang not in LANGUAGES:
                    raise ValueError("Language unavailable")
                user.language_code = lang
                markup = home_menu(lang)
                body = tr("welcome", lang)
            elif data == "language":
                body, markup = tr("language", lang), languages(lang)
            elif data == "menu":
                markup = home_menu(lang)
            elif data.startswith("privacy"):
                page = int(data.split(":")[1]) if ":" in data else 0
                if page not in range(3):
                    raise ValueError("Page unavailable")
                body = privacy_page(lang, page)
                art = "profile"
                markup = keyboard(
                    *[(f"📄 {i + 1}/3", f"privacy:{i}") for i in range(3) if i != page],
                    (tr("home", lang), "menu"),
                )
            elif data in {"plans", "hiddify:plans"} or data.startswith("family:"):
                plans = await CommerceService(db, vault).plans()
                family = data.split(":")[1] if data.startswith("family:") else None
                if family and family not in FAMILIES:
                    raise ValueError("Family unavailable")
                body = f"<b>{tr('plans', lang)}</b>\n\n"
                rows = []
                art = "plans"
                for code in [family] if family else FAMILIES:
                    group = sorted(
                        (p for p in plans if family_of(p) == code), key=lambda p: p.duration_months
                    )
                    if not group:
                        continue
                    p = group[0]
                    body += (
                        f"<b>AERA {code.upper()}</b> · {devices(p, lang)}\n"
                        + " · ".join(
                            f"{p.price_minor / 100:g} ₽ / {period(p, lang)}" for p in group
                        )
                        + "\n\n"
                    )
                    if family:
                        rows.extend(
                            (f"📅 {period(p, lang)} · {p.price_minor / 100:g} ₽", f"plan:{p.id}")
                            for p in group
                        )
                    else:
                        rows.append((f"💎 {code.upper()} · {devices(p, lang)}", f"family:{code}"))
                    if code == "business":
                        body += tr("business", lang) + "\n\n"
                body += tr("choose_term" if family else "traffic", lang)
                markup = keyboard(
                    *rows, (tr("plans" if family else "home", lang), "plans" if family else "menu")
                )
            elif data.startswith("plan:"):
                ticket, plan = await select_tariff(
                    db,
                    CommerceService(db, vault),
                    user,
                    data.split(":")[1],
                    settings.admin_ids,
                    notify_owner=False,
                )
                order = await ensure_order(db, ticket, plan)
                data = "order:" + order.id
            if data.startswith("order:"):
                order = await owned_order(db, data.split(":")[1], user)
                plan = await db.get(Plan, order.plan_id)
                art = "payments"
                if order.paid_at:
                    from app.db.models import PaidLink

                    issued = await db.scalar(
                        select(PaidLink.id).where(
                            PaidLink.order_id == order.id, PaidLink.issued_at.is_not(None)
                        )
                    )
                    body = tr("paid_ready" if issued else "paid", lang)
                    markup = actions(lang, ("profile", "profile"))
                else:
                    body = tr(
                        "pay",
                        lang,
                        plan=escape(plan.name),
                        period=period(plan, lang),
                        price=f"{order.amount_rub_minor / 100:g}",
                        discount=order.discount_percent,
                        number=order.ticket_id[:8],
                    )
                    stars = (
                        max(1, (plan.stars_price * (100 - order.discount_percent) + 99) // 100)
                        if plan.stars_price
                        else None
                    )
                    markup = keyboard(
                        (
                            f"⭐ Telegram Stars · {stars}" if stars else "⭐ Telegram Stars",
                            f"terms:{order.id}",
                        ),
                        ("СБП · FreeKassa" if settings.freekassa_enabled else tr("sbp_soon", lang), f"termsfk:42:{order.id}" if settings.freekassa_enabled else f"sbp:{order.id}"),
                        *([("Карта · FreeKassa", f"termsfk:4:{order.id}")] if settings.freekassa_enabled else []),
                        (tr("crypto", lang), f"cryptosoon:{order.id}"),
                        ("Cancel" if lang == "en" else "Отменить", f"cancelorder:{order.id}"),
                        (tr("home", lang), "menu"),
                    )
            elif data.startswith("terms:"):
                order = await owned_order(db, data.split(":")[1], user)
                from app.services.paid_pool import enabled

                body = tr("terms_auto" if await enabled(db) else "terms", lang)
                art = "payments"
                markup = actions(lang, ("accept", f"stars:{order.id}"), ("privacy", "privacy:0"))
            elif data.startswith("termsfk:"):
                _, method, identity = data.split(":")
                order = await owned_order(db, identity, user)
                from app.services.paid_pool import enabled
                body = tr("terms_auto" if await enabled(db) else "terms", lang)
                markup = keyboard((tr("accept", lang), f"fkpay:{method}:{order.id}"), ("Cancel" if lang == "en" else "Отменить", f"cancelorder:{order.id}"))
                art = "payments"
            elif data.startswith("fkpay:"):
                _, method, identity = data.split(":")
                order = await owned_order(db, identity, user)
                user.terms_accepted_at = datetime.now(UTC)
                user.terms_version = "portal-2"
                from app.api.checkout_api import intent
                url = "https://aera-reserve.duckdns.org/checkout?intent=" + intent(order.id, user.id) + "&method=" + ("36" if method == "4" else "42")
                plan = await db.get(Plan, order.plan_id)
                body = f"<b>{escape(plan.name)}</b> · {period(plan, lang)}\n\nК оплате: {order.amount_rub_minor / 100:g} ₽.\nОплата картой или СБП без регистрации кошелька." if url else tr("paid_stock_empty", lang)
                markup = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=("Pay" if lang == "en" else "Оплатить"), web_app=WebAppInfo(url=url))], [InlineKeyboardButton(text=tr("home", lang), callback_data="menu")]]) if url else actions(lang, ("plans", "plans"))
                art = "payments"
            elif data.startswith("cancelorder:"):
                order = await owned_order(db, data.split(":")[1], user)
                cancelled = await cancel_unpaid_order(db, order, user)
                body = ("Purchase cancelled." if lang == "en" else "Покупка отменена.") if cancelled else ("Payment is already being processed. Check your profile." if lang == "en" else "Оплата уже обрабатывается. Проверьте профиль.")
                markup = actions(lang, ("plans", "plans"), ("profile", "profile"))
            elif data.startswith("stars:"):
                order = await owned_order(db, data.split(":")[1], user)
                user.terms_accepted_at = datetime.now(UTC)
                user.terms_version = "portal-2"
                from app.services.manual_checkout import stars_payment

                payment = await stars_payment(db, data.split(":")[1], user)
                if payment is None:
                    from app.services.paid_pool import enabled

                    body = tr("paid_stock_empty" if await enabled(db) else "soon", lang)
                else:
                    invoice = (payment.id, payment.amount_minor)
                    plan = await db.get(Plan, payment.plan_id)
                    body = f"<b>{escape(plan.name)}</b> · {period(plan, lang)}\n\n" + tr("invoice", lang, n=payment.amount_minor)
                art = "payments"
            elif data.startswith(("sbp:", "bank:", "bankpay:", "cryptosoon:")):
                order = await owned_order(db, data.split(":")[-1], user)
                body = tr("payments_soon", lang)
                art = "payments"
                markup = actions(lang, ("pay_button", f"terms:{order.id}"))
            elif data in {"connect", "devices"}:
                body = tr("connect_info", lang)
                markup = keyboard(
                    *[
                        (label, f"guide:{code}")
                        for label, code in [
                            ("iPhone / iPad", "ios"),
                            ("Android", "android"),
                            ("Windows", "windows"),
                            ("macOS", "macos"),
                        ]
                    ],
                    (tr("my_link", lang), "link"),
                    (tr("home", lang), "menu"),
                )
            elif data.startswith("guide:"):
                platform = data.split(":")[1]
                if platform not in {"ios", "android", "windows", "macos"}:
                    raise ValueError("Platform unavailable")
                body = tr(platform, lang)
                markup = actions(
                    lang,
                    *([("download", "download:windows")] if platform == "windows" else []),
                    ("pick", "plans"),
                    ("back", "connect"),
                )
            elif data == "download:windows":
                send_file = True
            elif data == "how":
                body = tr("how_info", lang)
                markup = actions(lang, ("connect", "connect"), ("pick", "plans"))
            elif data in {"profile", "subscription"} or data.startswith("subscription:"):
                art = "profile"
                if data == "profile":
                    body = await profile_copy(db, user, lang)
                    markup = actions(
                        lang, ("my_link", "link"), ("pick", "plans"), ("refresh", "profile")
                    )
                else:
                    page = max(0, int(data.split(":")[1])) if ":" in data else 0
                    tickets = list(
                        await db.scalars(
                            paid_requests()
                            .where(SupportTicket.user_id == user.id)
                            .order_by(SaleOrder.paid_at.desc(), SupportTicket.id.desc())
                            .offset(page * 5)
                            .limit(6)
                        )
                    )
                    body = f"<b>{tr('requests', lang)}</b>\n\n"
                    for ticket in tickets[:5]:
                        order = await db.scalar(
                            select(SaleOrder).where(SaleOrder.ticket_id == ticket.id)
                        )
                        plan = await db.get(Plan, order.plan_id) if order else None
                        payment = (
                            await db.get(Payment, order.payment_id) if order.payment_id else None
                        )
                        amount = (
                            f"{payment.amount_minor} ⭐"
                            if payment and payment.currency == "XTR"
                            else f"{order.amount_rub_minor / 100:g} ₽"
                        )
                        body += (
                            tr(
                                "purchase_record",
                                lang,
                                number=ticket.id[:8],
                                plan=escape(plan.name) if plan else "AERA",
                                period=period(plan, lang) if plan else "",
                                amount=amount,
                                date=utc(order.paid_at).strftime("%d.%m.%Y %H:%M UTC"),
                            )
                            + "\n\n"
                        )
                    if not tickets:
                        body += tr("empty_requests", lang)
                    markup = keyboard(
                        *([(tr("previous", lang), f"subscription:{page - 1}")] if page else []),
                        *(
                            [(tr("next", lang), f"subscription:{page + 1}")]
                            if len(tickets) > 5
                            else []
                        ),
                        (tr("home", lang), "menu"),
                    )
            elif data == "referral":
                refs = list(
                    await db.scalars(select(Referral).where(Referral.referrer_user_id == user.id))
                )
                coupons = await db.scalar(
                    select(func.count())
                    .select_from(ReferralCoupon)
                    .where(ReferralCoupon.user_id == user.id, ReferralCoupon.status == "AVAILABLE")
                )
                body = tr(
                    "ref_info",
                    lang,
                    invited=len(refs),
                    qualified=sum(r.status == "COUPON" for r in refs),
                    coupons=coupons,
                    url=f"https://t.me/{settings.bot_username}?start=ref_{user.referral_code}",
                )
                art = "referral"
                markup = actions(lang, ("pick", "plans"))
            elif data == "trial":
                body = tr("trial_info", lang)
                art = "trial"
                markup = actions(lang, ("get_trial", "trial:get"), ("profile", "profile"))
            elif data == "trial:get":
                from app.services.trial_pool import claim_link

                trial, result = await claim_link(db, user, settings.app_secret)
                art = "trial"
                if result == "empty":
                    body = tr("trial_empty", lang)
                    for aid in settings.admin_ids:
                        admin = await CommerceService(db, vault).user(aid)
                        await enqueue(
                            db,
                            f"trial-empty:{user.id}:{aid}:{datetime.now(UTC):%Y%m%d}",
                            admin.id,
                            "PORTAL",
                            f"🎁 Не хватило пробной ссылки для @{user.username or '-'} "
                            f"(ID {user.telegram_id}). Пополни запас в панели.",
                        )
                elif result == "used" or trial.status in {"EXPIRED", "RETIRED"}:
                    body = tr("trial_used", lang)
                else:
                    body = tr("trial_key", lang, link=escape(vault.reveal(trial.link_encrypted)))
                markup = actions(
                    lang, ("connect", "connect"), ("profile", "profile"), ("pick", "plans")
                )
            elif data in {"link", "qr"}:
                from app.services.paid_pool import current, latest

                paid = await current(db, user.id) or await latest(db, user.id)
                access = await db.scalar(
                    select(ManualAccess).where(ManualAccess.user_id == user.id)
                )
                trial = await db.scalar(select(TrialLink).where(TrialLink.user_id == user.id))
                encrypted = (
                    paid.link_encrypted
                    if paid
                    and paid.status in {"WAITING", "ACTIVE"}
                    and (paid.expires_at is None or utc(paid.expires_at) > datetime.now(UTC))
                    else access.link_encrypted
                    if access and utc(access.expires_at) > datetime.now(UTC)
                    else trial.link_encrypted
                    if trial and trial.status in {"WAITING", "ACTIVE", "ACTIVATING"}
                    else None
                )
                body = (
                    f"🔗 <code>{escape(vault.reveal(encrypted))}</code>"
                    if encrypted
                    else tr("no_link", lang)
                )
                markup = actions(lang, ("connect", "connect"), ("support", "support"))
            elif data == "support":
                body = tr("support_info", lang)
                await state.set_state(HelpFlow.message)
        if send_file:
            from app.bot.installers import send_windows_installer

            await send_windows_installer(
                call.message, caption=tr("installer", lang), unavailable=tr("error", lang)
            )
            return
        if invoice:
            from app.integrations.payments.telegram_stars import TelegramStarsProvider

            url = await TelegramStarsProvider(call.bot).create_payment(
                invoice[0], invoice[1], "XTR", lang=lang
            )
            markup = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text=tr("pay_button", lang), url=url)],
                    [InlineKeyboardButton(text="Cancel" if lang == "en" else "Отменить", callback_data=f"cancelorder:{order.id}")],
                    [InlineKeyboardButton(text=tr("home", lang), callback_data="menu")],
                ]
            )
        if markup:
            for row in markup.inline_keyboard:
                for button in row:
                    if button.callback_data and button.callback_data.startswith("termsfk:"):
                        from app.api.checkout_api import intent
                        _, method, order_id = button.callback_data.split(":")
                        button.url = "https://aera-reserve.duckdns.org/checkout?intent=" + intent(order_id, user.id) + "&method=" + ("36" if method == "4" else "42")
                        button.web_app = WebAppInfo(url=button.url)
                        button.url = None
                        button.callback_data = None
        await edit_screen(call.message, body, reply_markup=markup, art=art)
    except Exception as error:
        logging.getLogger("aera").error("portal_action_failed type=%s", type(error).__name__)
        await edit_screen(
            call.message, tr("error", lang), reply_markup=actions(lang, ("support", "support"))
        )


async def owned_order(db, identity, user):
    order = await db.get(SaleOrder, identity)
    ticket = await db.get(SupportTicket, order.ticket_id) if order else None
    if not ticket or ticket.user_id != user.id:
        raise ValueError("Order ownership mismatch")
    return order


async def cancel_unpaid_order(db, order, user):
    """Cancel only before Telegram has accepted a pre-checkout; keep receipts recoverable."""
    from sqlalchemy import update
    from app.db.models import Payment, User
    await db.execute(update(User).where(User.id == user.id).values(is_active=User.is_active))
    await db.refresh(order)
    ticket = await db.get(SupportTicket, order.ticket_id, populate_existing=True)
    if ticket.user_id != user.id:
        raise ValueError("Order ownership mismatch")
    payment = await db.get(Payment, order.payment_id, populate_existing=True) if order.payment_id else None
    if order.paid_at or (payment and (payment.status == "PAID" or (payment.details.get("precheckout_accepted") or payment.details.get("external_started")))):
        return False
    if payment and payment.status == "PENDING":
        payment.status = "CANCELLED"
    ticket.status, ticket.closed_at = "CLOSED", datetime.now(UTC)
    if order.coupon_id:
        coupon = await db.get(ReferralCoupon, order.coupon_id)
        if coupon and coupon.status == "RESERVED" and coupon.reserved_ticket_id == ticket.id:
            coupon.status, coupon.reserved_ticket_id = "AVAILABLE", None
    return True


async def send_selected_checkout(message, plan_id, method="stars"):
    """Website-selected plan: prices and ownership are resolved exclusively in the bot."""
    if method == "rub":
        return await send_selected_rub(message, plan_id)
    settings = get_settings()
    vault = TokenVault(settings.app_secret)
    try:
        async with sessions.begin() as db:
            user = await get_user(db, message.from_user)
            lang = user.language_code
            if user.is_blocked or not user.is_active:
                raise ValueError("Account unavailable")
            ticket, plan = await select_tariff(db, CommerceService(db, vault), user, plan_id, settings.admin_ids, notify_owner=False)
            order = await ensure_order(db, ticket, plan)
            order_id = order.id
            label = f"<b>{escape(plan.name)}</b> · {period(plan, lang)}\n\n"
            payment = None
            if user.terms_accepted_at:
                from app.services.manual_checkout import stars_payment
                payment = await stars_payment(db, order.id, user)
                if payment is None:
                    raise ValueError("Stars checkout unavailable")
            if payment:
                invoice = (payment.id, payment.amount_minor)
                body = label + tr("invoice", lang, n=payment.amount_minor)
            else:
                from app.services.paid_pool import enabled
                stars = max(1, (plan.stars_price*(100-order.discount_percent)+99)//100) if plan.stars_price else 0
                body = label + f"⭐ {stars} Stars\n\n" + tr("terms_auto" if await enabled(db) else "terms", lang)
                invoice = None
        if invoice:
            from app.integrations.payments.telegram_stars import TelegramStarsProvider
            url = await TelegramStarsProvider(message.bot).create_payment(invoice[0], invoice[1], "XTR", lang=lang)
            markup = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=tr("pay_button", lang), url=url)],
                [InlineKeyboardButton(text="Cancel" if lang == "en" else "Отменить", callback_data=f"cancelorder:{order_id}")],
                [InlineKeyboardButton(text=tr("home", lang), callback_data="menu")],
            ])
        else:
            markup = keyboard((tr("accept", lang), f"stars:{order_id}"), ("Cancel" if lang == "en" else "Отменить", f"cancelorder:{order_id}"))
        from app.api.checkout_api import intent
        for row in markup.inline_keyboard:
            for button in row:
                if button.callback_data and button.callback_data.startswith("termsfk:"):
                    _, method, order_id = button.callback_data.split(":")
                    button.url = "https://aera-reserve.duckdns.org/checkout?intent=" + intent(order_id, user.id) + "&method=" + ("36" if method == "4" else "42")
                    button.web_app = WebAppInfo(url=button.url)
                    button.url = None
                    button.callback_data = None
        await send_screen(message, body, reply_markup=markup, art="payments")
    except Exception as error:
        logging.getLogger("aera").error("website_checkout_failed type=%s", type(error).__name__)
        await message.answer("Не удалось открыть оплату выбранного тарифа. Попробуйте снова или обратитесь в поддержку.")


async def send_selected_rub(message, plan_id):
    settings = get_settings()
    try:
        async with sessions.begin() as db:
            user = await get_user(db, message.from_user)
            if not settings.freekassa_enabled or user.is_blocked or not user.is_active:
                raise ValueError("Checkout unavailable")
            ticket, plan = await select_tariff(db, CommerceService(db, TokenVault(settings.app_secret)), user, plan_id, settings.admin_ids, notify_owner=False)
            order = await ensure_order(db, ticket, plan)
            body = f"<b>{escape(plan.name)}</b> · {period(plan, user.language_code)}\n\nК оплате: {order.amount_rub_minor / 100:g} ₽.\nВыберите способ оплаты."
            markup = keyboard(("СБП · FreeKassa", f"termsfk:42:{order.id}"), ("Карта · FreeKassa", f"termsfk:4:{order.id}"), ("Отменить", f"cancelorder:{order.id}"))
        from app.api.checkout_api import intent
        for row in markup.inline_keyboard:
            for button in row:
                if button.callback_data and button.callback_data.startswith("termsfk:"):
                    _, method, order_id = button.callback_data.split(":")
                    button.url = "https://aera-reserve.duckdns.org/checkout?intent=" + intent(order_id, user.id) + "&method=" + ("36" if method == "4" else "42")
                    button.web_app = WebAppInfo(url=button.url)
                    button.url = None
                    button.callback_data = None
        await send_screen(message, body, reply_markup=markup, art="payments")
    except Exception as error:
        logging.getLogger("aera").error("rub_checkout_failed type=%s", type(error).__name__)
        await message.answer("Не удалось открыть оплату. Попробуйте снова или обратитесь в поддержку.")
