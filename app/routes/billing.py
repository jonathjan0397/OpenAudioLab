"""Billing plans: Suno-style tiers with mock payment (milestone 13)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from ..errors import ApiError
from ..models import CreditEntry, User
from ..routes.auth import current_user

router = APIRouter(tags=["billing"])

PLANS: dict[str, dict] = {
    "free": {"id": "free", "name": "Free", "price_usd": 0, "monthly_credits": 0},
    "pro": {"id": "pro", "name": "Pro", "price_usd": 8, "monthly_credits": 2500},
    "premier": {"id": "premier", "name": "Premier", "price_usd": 24, "monthly_credits": 10000},
}
TOPUP_CREDITS = 500


class SubscribeRequest(BaseModel):
    plan: str = Field(pattern=r"^(pro|premier)$")


def _grant(session, user: User, delta: int, reason: str) -> None:
    user.credits_balance += delta
    session.add(CreditEntry(owner_id="usr_" + user.id, delta=delta, reason=reason))


def _require_mock_billing(request: Request) -> None:
    mode = getattr(request.app.state.settings, "billing_mode", "production")
    if mode != "mock":
        raise ApiError(409, "MOCK_BILLING_DISABLED", "Use Stripe checkout for billing in production.")


def load_pricing(session) -> dict[str, list[dict]]:
    """Read pricing rows; seed defaults from PLANS/PACKS when empty."""
    from sqlalchemy import select

    from ..models import Pricing

    rows = list(session.execute(select(Pricing).order_by(Pricing.position)).scalars())
    if not rows:
        defaults = [
            Pricing(id=k, kind="plan", name=v["name"], price_usd=v["price_usd"], credits=v["monthly_credits"], position=i)
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
            {"id": p.id, "kind": p.kind, "name": p.name, "price_usd": p.price_usd, "credits": p.credits, "position": p.position}
        )
    return out


def _plan_map(session) -> dict[str, dict]:
    data = load_pricing(session)
    return {
        p["id"]: {"id": p["id"], "name": p["name"], "price_usd": p["price_usd"], "monthly_credits": p["credits"]}
        for p in data["plan"]
    }


@router.get("/billing/plans")
def billing_plans(request: Request, user: User = Depends(current_user)) -> JSONResponse:
    with request.app.state.db.session() as session:
        plans = list(_plan_map(session).values())
    return JSONResponse(
        {
            "plans": plans,
            "current": user.plan,
            "credits_balance": user.credits_balance,
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
        session.commit()
        balance = fresh.credits_balance
        current = fresh.plan
    return JSONResponse({"plan": current, "credits_balance": balance, "charged_usd": plan["price_usd"]})


@router.post("/billing/unsubscribe")
def billing_unsubscribe(request: Request, user: User = Depends(current_user)) -> JSONResponse:
    with request.app.state.db.session() as session:
        fresh = session.get(User, user.id)
        fresh.plan = "free"
        session.commit()
    return JSONResponse({"plan": "free", "credits_balance": user.credits_balance})


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
    plan: str | None = Field(default=None, pattern=r"^(pro|premier)$")
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
        line = {
            "price_data": {
                "currency": "usd",
                "product_data": {"name": f"OpenAudioLab {item['name']}"},
                "unit_amount": unit,
                "recurring": {"interval": "month"},
            },
            "quantity": 1,
        }
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
    obj = raw["data"]["object"]
    from ..models import User as _User

    if event_type == "checkout.session.completed":
        meta = obj.get("metadata") or {}
        owner = obj.get("client_reference_id")
        with request.app.state.db.session() as session:
            fresh = session.get(_User, owner) if owner else None
            if fresh is not None:
                if meta.get("kind") == "plan" and meta.get("plan"):
                    fresh.plan = meta["plan"]
                    if obj.get("subscription"):
                        fresh.stripe_subscription_id = str(obj["subscription"])
                    _grant(session, fresh, int(meta.get("credits") or 0), "subscription")
                elif meta.get("kind") == "pack":
                    _grant(session, fresh, int(meta.get("credits") or 0), "topup")
                session.commit()
    elif event_type == "customer.subscription.deleted":
        with request.app.state.db.session() as session:
            rows = list(
                session.execute(
                    select(_User).where(_User.stripe_subscription_id == obj.get("id"))
                ).scalars()
            )
            for fresh in rows:
                fresh.plan = "free"
                fresh.stripe_subscription_id = None
            session.commit()
    return JSONResponse({"received": True})
