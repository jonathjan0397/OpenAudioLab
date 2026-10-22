"""Billing plans: Suno-style tiers with mock payment (milestone 13)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from ..errors import ApiError
from ..models import BillingEvent, CreditEntry, SubscriptionPeriod, User, utcnow
from ..routes.auth import current_user

router = APIRouter(tags=["billing"])

PLANS: dict[str, dict] = {
    "free": {"id": "free", "name": "Free account", "price_usd": 0, "monthly_credits": 0, "visible": True},
    "beginner": {"id": "beginner", "name": "Beginner", "price_usd": 5, "monthly_credits": 1000, "visible": True},
    "pro": {"id": "pro", "name": "Pro", "price_usd": 8, "monthly_credits": 2500, "visible": True},
    "premier": {"id": "premier", "name": "Premier", "price_usd": 24, "monthly_credits": 10000, "visible": True},
}
TOPUP_CREDITS = 500


class SubscribeRequest(BaseModel):
    plan: str = Field(pattern=r"^(beginner|pro|premier)$")


def _grant(session, user: User, delta: int, reason: str, external_id: str | None = None) -> None:
    if external_id:
        existing = session.execute(
            select(CreditEntry).where(CreditEntry.external_id == external_id)
        ).scalar_one_or_none()
        if existing is not None:
            return
    user.credits_balance += delta
    session.add(CreditEntry(owner_id="usr_" + user.id, delta=delta, reason=reason, external_id=external_id))


def _require_mock_billing(request: Request) -> None:
    mode = getattr(request.app.state.settings, "billing_mode", "production")
    if mode != "mock":
        raise ApiError(409, "MOCK_BILLING_DISABLED", "Use Stripe checkout for billing in production.")


def _owner_id(user_id: str | None) -> str | None:
    return f"usr_{user_id}" if user_id else None


def _user_for_customer(session, customer_id: str | None) -> User | None:
    if not customer_id:
        return None
    return session.execute(select(User).where(User.stripe_customer_id == customer_id)).scalars().first()


def _event_amount(obj: dict) -> int:
    for key in ("amount_total", "amount", "amount_captured", "amount_refunded"):
        value = obj.get(key)
        if isinstance(value, (int, float)) and value:
            return int(value)
    return 0


def load_pricing(session) -> dict[str, list[dict]]:
    """Read pricing rows; seed defaults from PLANS/PACKS when empty."""
    from sqlalchemy import select

    from ..models import Pricing

    rows = list(session.execute(select(Pricing).order_by(Pricing.position)).scalars())
    if not rows:
        defaults = [
            Pricing(
                id=k,
                kind="plan",
                name=v["name"],
                price_usd=v["price_usd"],
                credits=v["monthly_credits"],
                position=i,
                visible=v.get("visible", True),
            )
            for i, (k, v) in enumerate(PLANS.items())
        ] + [
            Pricing(id=k, kind="pack", name=v["name"], price_usd=v["price_usd"], credits=v["credits"], position=10 + i)
            for i, (k, v) in enumerate(PACKS.items())
        ]
        session.add_all(defaults)
        session.commit()
        rows = defaults
    out: dict[str, list[dict]] = {"plan": [], "pack": []}
    for p in rows:
        out.setdefault(p.kind, []).append(
            {
                "id": p.id,
                "kind": p.kind,
                "name": p.name,
                "price_usd": p.price_usd,
                "credits": p.credits,
                "position": p.position,
                "visible": bool(getattr(p, "visible", True)),
                "popular": bool(getattr(p, "popular", False)),
            }
        )
    return out


def _plan_map(session) -> dict[str, dict]:
    data = load_pricing(session)
    return {
        p["id"]: {
            "id": p["id"],
            "name": p["name"],
            "price_usd": p["price_usd"],
            "monthly_credits": p["credits"],
            "visible": p.get("visible", True),
        }
        for p in data["plan"]
    }


@router.get("/billing/pricing")
def billing_pricing(request: Request) -> JSONResponse:
    settings = request.app.state.settings
    with request.app.state.db.session() as session:
        data = load_pricing(session)
    return JSONResponse(
        {
            "plans": [p for p in data["plan"] if p.get("visible", True)],
            "packs": [p for p in data["pack"] if p.get("visible", True)],
            "guest": {
                "daily_song_limit": settings.guest_daily_song_limit,
                "max_duration_seconds": settings.guest_max_duration_seconds,
                "session_ttl_days": settings.guest_session_ttl_days,
            },
            "policy_version": settings.policy_version,
        }
    )


@router.get("/billing/plans")
def billing_plans(request: Request, user: User = Depends(current_user)) -> JSONResponse:
    with request.app.state.db.session() as session:
        plans = [p for p in _plan_map(session).values() if p.get("visible", True)]
    return JSONResponse(
        {
            "plans": plans,
            "current": user.plan,
            "credits_balance": user.credits_balance,
            "subscription_status": user.subscription_status,
            "cancel_at_period_end": user.cancel_at_period_end,
            "current_period_end": user.current_period_end.isoformat() if user.current_period_end else None,
            "topup_credits": TOPUP_CREDITS,
        }
    )


@router.post("/billing/subscribe")
def billing_subscribe(payload: SubscribeRequest, request: Request, user: User = Depends(current_user)) -> JSONResponse:
    _require_mock_billing(request)
    with request.app.state.db.session() as session:
        plan = _plan_map(session).get(payload.plan) or PLANS[payload.plan]
        fresh = session.get(User, user.id)
        _grant(session, fresh, plan["monthly_credits"], "subscription")
        fresh.plan = payload.plan
        fresh.subscription_status = "active"
        fresh.cancel_at_period_end = False
        fresh.current_period_end = utcnow() + timedelta(days=30)
        session.commit()
        balance = fresh.credits_balance
        current = fresh.plan
    return JSONResponse({"plan": current, "credits_balance": balance, "charged_usd": plan["price_usd"]})


@router.post("/billing/unsubscribe")
def billing_unsubscribe(request: Request, user: User = Depends(current_user)) -> JSONResponse:
    with request.app.state.db.session() as session:
        fresh = session.get(User, user.id)
        fresh.plan = "free"
        fresh.subscription_status = None
        fresh.cancel_at_period_end = False
        fresh.current_period_end = None
        session.commit()
    return JSONResponse({"plan": "free", "credits_balance": user.credits_balance})


@router.post("/billing/cancel")
def billing_cancel(request: Request, user: User = Depends(current_user)) -> JSONResponse:
    with request.app.state.db.session() as session:
        fresh = session.get(User, user.id)
        if fresh.plan == "free" or not fresh.stripe_subscription_id:
            raise ApiError(409, "NO_ACTIVE_SUBSCRIPTION", "There is no active subscription to cancel.")
        fresh.cancel_at_period_end = True
        fresh.subscription_status = "canceling"
        session.commit()
    return JSONResponse(
        {
            "plan": user.plan,
            "cancel_at_period_end": True,
            "subscription_status": "canceling",
            "current_period_end": user.current_period_end.isoformat() if user.current_period_end else None,
        }
    )


@router.post("/billing/topup")
def billing_topup(request: Request, user: User = Depends(current_user)) -> JSONResponse:
    _require_mock_billing(request)
    with request.app.state.db.session() as session:
        fresh = session.get(User, user.id)
        _grant(session, fresh, TOPUP_CREDITS, "topup")
        session.commit()
        balance = fresh.credits_balance
    return JSONResponse({"credits_balance": balance, "added": TOPUP_CREDITS})


def subscription_revenue(session) -> float:
    from sqlalchemy import func, select

    total = 0.0
    for plan, count in session.execute(select(User.plan, func.count()).group_by(User.plan)).all():
        total += PLANS.get(plan, PLANS["free"])["price_usd"] * int(count)
    return total


# --- M14d: Stripe Checkout + webhooks ----------------------------------------

PACKS: dict[str, dict] = {
    "small": {"id": "small", "name": "Starter pack", "price_usd": 5, "credits": 1000},
    "medium": {"id": "medium", "name": "Creator pack", "price_usd": 20, "credits": 5000},
    "large": {"id": "large", "name": "Studio pack", "price_usd": 45, "credits": 12000},
}


class CheckoutRequest(BaseModel):
    kind: str = Field(pattern=r"^(plan|pack)$")
    plan: str | None = Field(default=None, pattern=r"^(beginner|pro|premier)$")
    pack: str | None = Field(default=None, pattern=r"^(small|medium|large)$")


@router.get("/billing/packs")
def billing_packs(request: Request, user: User = Depends(current_user)) -> JSONResponse:
    with request.app.state.db.session() as session:
        packs = load_pricing(session)["pack"]
    return JSONResponse({"packs": packs})


@router.post("/billing/checkout", status_code=201)
def billing_checkout(
    payload: CheckoutRequest, request: Request, user: User = Depends(current_user)
) -> JSONResponse:
    settings = request.app.state.settings
    if payload.kind == "plan" and not payload.plan:
        raise ApiError(422, "PLAN_REQUIRED", "Choose a plan.")
    if payload.kind == "pack" and not payload.pack:
        raise ApiError(422, "PACK_REQUIRED", "Choose a credit pack.")
    if not settings.stripe_secret_key:
        raise ApiError(503, "STRIPE_DISABLED", "Card payments are not configured yet.")
    import stripe

    stripe.api_key = settings.stripe_secret_key
    with request.app.state.db.session() as db:
        pricing = load_pricing(db)
    if payload.kind == "plan":
        item = next((p for p in pricing["plan"] if p["id"] == payload.plan), None) or PLANS[payload.plan]
        name, unit, credits = item["name"], item["price_usd"] * 100, item.get("monthly_credits", item.get("credits", 0))
        price_id = getattr(settings, f"stripe_price_{payload.plan}", "")
        line = (
            {"price": price_id, "quantity": 1}
            if price_id
            else {
                "price_data": {
                    "currency": "usd",
                    "product_data": {"name": f"OpenAudioLab {item['name']}"},
                    "unit_amount": unit,
                    "recurring": {"interval": "month"},
                },
                "quantity": 1,
            }
        )
        mode = "subscription"
    else:
        item = next((p for p in pricing["pack"] if p["id"] == payload.pack), None) or PACKS[payload.pack]
        name, unit, credits = item["name"], item["price_usd"] * 100, item["credits"]
        line = {
            "price_data": {
                "currency": "usd",
                "product_data": {"name": f"OpenAudioLab {item['name']}"},
                "unit_amount": unit,
            },
            "quantity": 1,
        }
        mode = "payment"
    session = stripe.checkout.Session.create(
        mode=mode,
        line_items=[line],
        client_reference_id=user.id,
        customer_email=user.email,
        metadata={"kind": payload.kind, "plan": payload.plan or "", "pack": payload.pack or "", "credits": str(credits)},
        success_url=settings.site_url + "/pricing?checkout=success",
        cancel_url=settings.site_url + "/pricing?checkout=cancel",
    )
    with request.app.state.db.session() as db:
        fresh = db.get(User, user.id)
        if getattr(session, "customer", None):
            fresh.stripe_customer_id = str(session.customer)
        db.commit()
    return JSONResponse(
        status_code=201,
        content={"url": session.url, "session_id": session.id},
    )


def _ts_to_datetime(value) -> datetime | None:
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc)
    return None


def _subscription_period_end(subscription: dict | None) -> datetime | None:
    if not subscription:
        return None
    items = subscription.get("items", {}).get("data") or []
    if items:
        return _ts_to_datetime(items[0].get("current_period_end"))
    return _ts_to_datetime(subscription.get("current_period_end"))


def _user_for_subscription(session, subscription_id: str | None) -> User | None:
    if not subscription_id:
        return None
    return session.execute(select(User).where(User.stripe_subscription_id == subscription_id)).scalars().first()


def _invoice_period(obj: dict) -> tuple[datetime | None, datetime | None]:
    lines = (obj.get("lines") or {}).get("data") or []
    if lines:
        return _ts_to_datetime(lines[0].get("period", {}).get("start")), _ts_to_datetime(
            lines[0].get("period", {}).get("end")
        )
    return _ts_to_datetime(obj.get("period_start")), _ts_to_datetime(obj.get("period_end"))


def _plan_credits(session, plan: str | None) -> int:
    if not plan:
        return 0
    return int(_plan_map(session).get(plan, {}).get("monthly_credits") or PLANS.get(plan, {}).get("monthly_credits") or 0)


@router.post("/billing/webhook")
async def billing_webhook(request: Request) -> JSONResponse:
    settings = request.app.state.settings
    if not settings.stripe_webhook_secret:
        raise ApiError(503, "STRIPE_DISABLED", "Webhook secret is not configured.")
    import stripe

    stripe.api_key = settings.stripe_secret_key
    body = await request.body()
    try:
        event = stripe.Webhook.construct_event(
            body, request.headers.get("stripe-signature", ""), settings.stripe_webhook_secret
        )
    except Exception as exc:
        raise ApiError(400, "WEBHOOK_SIGNATURE", f"Signature verification failed: {exc}")
    import json

    raw = json.loads(body)
    event_type = raw["type"]
    event_id = raw.get("id")
    obj = raw["data"]["object"]
    meta = obj.get("metadata") or {}
    credits = int(meta.get("credits") or 0)
    owner_user_id = obj.get("client_reference_id")
    status = "recorded"

    with request.app.state.db.session() as session:
        if event_id and session.execute(
            select(BillingEvent).where(BillingEvent.stripe_event_id == event_id)
        ).scalar_one_or_none():
            return JSONResponse({"received": True, "duplicate": True})

        period_start = _ts_to_datetime(obj.get("period_start"))
        period_end = _ts_to_datetime(obj.get("period_end"))

        if event_type == "checkout.session.completed":
            fresh = session.get(User, owner_user_id) if owner_user_id else None
            if fresh is None:
                fresh = _user_for_customer(session, obj.get("customer"))
            if fresh is not None:
                owner_user_id = fresh.id
                if meta.get("kind") == "plan" and meta.get("plan"):
                    fresh.plan = meta["plan"]
                    fresh.subscription_status = "active"
                    fresh.cancel_at_period_end = False
                    if obj.get("subscription"):
                        fresh.stripe_subscription_id = str(obj["subscription"])
                    period_end = _ts_to_datetime((obj.get("subscription_details") or {}).get("current_period_end")) or period_end
                    fresh.current_period_end = period_end
                    _grant(session, fresh, credits, "subscription", external_id=obj.get("id") or event_id)
                    if obj.get("id"):
                        session.add(
                            SubscriptionPeriod(
                                user_id=fresh.id,
                                plan=fresh.plan,
                                stripe_subscription_id=obj.get("subscription"),
                                stripe_invoice_id=obj.get("invoice"),
                                period_start=utcnow(),
                                period_end=period_end,
                                status="active",
                                credits=credits,
                                amount_usd=_event_amount(obj),
                            )
                        )
                elif meta.get("kind") == "pack":
                    _grant(session, fresh, credits, "topup", external_id=obj.get("id") or event_id)
                status = "credited"
        elif event_type == "customer.subscription.updated":
            fresh = _user_for_subscription(session, obj.get("id"))
            if fresh is not None:
                owner_user_id = fresh.id
                fresh.subscription_status = obj.get("status") or fresh.subscription_status
                fresh.cancel_at_period_end = bool(obj.get("cancel_at_period_end"))
                fresh.current_period_end = _subscription_period_end(obj) or fresh.current_period_end
                if fresh.subscription_status in ("canceled", "unpaid", "incomplete_expired"):
                    fresh.plan = "free"
                    fresh.stripe_subscription_id = None
                    fresh.cancel_at_period_end = False
            status = "updated"
        elif event_type == "customer.subscription.deleted":
            rows = list(
                session.execute(
                    select(User).where(User.stripe_subscription_id == obj.get("id"))
                ).scalars()
            )
            for fresh in rows:
                fresh.plan = "free"
                fresh.stripe_subscription_id = None
                fresh.subscription_status = "canceled"
                fresh.cancel_at_period_end = False
                fresh.current_period_end = _subscription_period_end(obj)
            if rows:
                owner_user_id = rows[0].id
            status = "cancelled"
        elif event_type == "charge.refunded":
            fresh = _user_for_customer(session, obj.get("customer"))
            if fresh is not None:
                owner_user_id = fresh.id
            status = "refunded"
        elif event_type == "invoice.paid":
            fresh = _user_for_customer(session, obj.get("customer")) or _user_for_subscription(session, obj.get("subscription"))
            if fresh is not None:
                owner_user_id = fresh.id
                period_start, period_end = _invoice_period(obj)
                fresh.current_period_end = period_end or fresh.current_period_end
                fresh.subscription_status = "active"
                fresh.cancel_at_period_end = False
                billing_reason = obj.get("billing_reason")
                invoice_id = obj.get("id")
                if billing_reason == "subscription_cycle":
                    renewal_credits = credits or _plan_credits(session, fresh.plan)
                    _grant(session, fresh, renewal_credits, "subscription", external_id=invoice_id)
                    credits = renewal_credits
                if invoice_id:
                    session.add(
                        SubscriptionPeriod(
                            user_id=fresh.id,
                            plan=fresh.plan,
                            stripe_subscription_id=obj.get("subscription"),
                            stripe_invoice_id=invoice_id,
                            period_start=period_start or utcnow(),
                            period_end=period_end,
                            status="active",
                            credits=credits,
                            amount_usd=_event_amount(obj),
                        )
                    )
            status = "invoice"
        elif event_type.startswith("invoice."):
            fresh = _user_for_customer(session, obj.get("customer"))
            if fresh is not None:
                owner_user_id = fresh.id
            status = "invoice"

        session.add(
            BillingEvent(
                owner_id=_owner_id(owner_user_id),
                event_type=event_type,
                stripe_event_id=event_id,
                checkout_session_id=obj.get("id") if event_type == "checkout.session.completed" else None,
                payment_intent_id=obj.get("payment_intent") or obj.get("payment_intent_id"),
                invoice_id=obj.get("invoice") or obj.get("id") if event_type.startswith("invoice.") else None,
                subscription_id=obj.get("subscription") or (obj.get("id") if event_type.startswith("customer.subscription.") else None),
                kind=meta.get("kind"),
                item_id=meta.get("plan") or meta.get("pack"),
                amount_usd=_event_amount(obj),
                credits=credits,
                status=status,
                period_start=period_start,
                period_end=period_end,
            )
        )
        session.commit()
    return JSONResponse({"received": True, "duplicate": False})
