"""Billing plans: Suno-style tiers with mock payment (milestone 13)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

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


@router.get("/billing/plans")
def billing_plans(user: User = Depends(current_user)) -> JSONResponse:
    return JSONResponse(
        {
            "plans": list(PLANS.values()),
            "current": user.plan,
            "credits_balance": user.credits_balance,
            "topup_credits": TOPUP_CREDITS,
        }
    )


@router.post("/billing/subscribe")
def billing_subscribe(payload: SubscribeRequest, request: Request, user: User = Depends(current_user)) -> JSONResponse:
    plan = PLANS[payload.plan]
    with request.app.state.db.session() as session:
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
