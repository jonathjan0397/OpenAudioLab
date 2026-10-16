"""Cookie-session auth endpoints for the website (register/login/logout/me)."""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from ..auth import (
    COOKIE_NAME,
    SESSION_TTL_DAYS,
    hash_password,
    new_session_token,
    token_sha256,
    verify_password,
)
from ..errors import ApiError
from ..models import User, UserSession, utcnow
from ..orchestration import as_utc

router = APIRouter(tags=["auth"])


class RegisterRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    username: str = Field(min_length=2, max_length=80, pattern=r"^[a-zA-Z0-9_.-]+$")
    password: str = Field(min_length=8, max_length=200)


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=200)


def user_payload(user: User) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "username": user.username,
        "role": user.role,
        "state": user.state,
        "credits_balance": user.credits_balance,
    }


def create_session(request: Request, user: User) -> str:
    token = new_session_token()
    with request.app.state.db.session() as session:
        session.add(
            UserSession(
                user_id=user.id,
                token_sha256=token_sha256(token),
                expires_at=utcnow() + timedelta(days=SESSION_TTL_DAYS),
            )
        )
        session.commit()
    return token


def set_session_cookie(response: JSONResponse, request: Request, token: str) -> JSONResponse:
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        max_age=SESSION_TTL_DAYS * 86400,
        httponly=True,
        samesite="lax",
        secure=request.app.state.settings.cookie_secure,
        path="/",
    )
    return response


def current_user(request: Request) -> User:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise ApiError(401, "UNAUTHENTICATED", "A session cookie is required.")
    with request.app.state.db.session() as session:
        record = session.execute(
            select(UserSession).where(UserSession.token_sha256 == token_sha256(token))
        ).scalar_one_or_none()
        if record is None or as_utc(record.expires_at) <= utcnow():
            raise ApiError(401, "SESSION_EXPIRED", "Session is missing or expired.")
        user = session.get(User, record.user_id)
        if user is None or user.state != "active":
            raise ApiError(403, "USER_DISABLED", "Account is missing or disabled.")
        session.expunge(user)
        return user


def require_admin(request: Request, user: User = Depends(current_user)) -> User:
    if user.role != "admin":
        raise ApiError(403, "ADMIN_REQUIRED", "Administrator role required.")
    return user


@router.post("/auth/register", status_code=201)
def auth_register(payload: RegisterRequest, request: Request) -> JSONResponse:
    email = payload.email.strip().lower()
    with request.app.state.db.session() as session:
        if session.execute(select(User).where(User.email == email)).scalar_one_or_none():
            raise ApiError(409, "EMAIL_TAKEN", "Email already registered.")
        if session.execute(
            select(User).where(User.username == payload.username)
        ).scalar_one_or_none():
            raise ApiError(409, "USERNAME_TAKEN", "Username already taken.")
        user = User(
            email=email,
            username=payload.username,
            password_hash=hash_password(payload.password),
        )
        session.add(user)
        session.commit()
        session.refresh(user)
    token = create_session(request, user)
    return set_session_cookie(JSONResponse(status_code=201, content={"user": user_payload(user)}), request, token)


@router.post("/auth/login")
def auth_login(payload: LoginRequest, request: Request) -> JSONResponse:
    email = payload.email.strip().lower()
    with request.app.state.db.session() as session:
        user = session.execute(select(User).where(User.email == email)).scalar_one_or_none()
        if user is None or not verify_password(payload.password, user.password_hash):
            raise ApiError(401, "INVALID_CREDENTIALS", "Email or password is incorrect.")
        if user.state != "active":
            raise ApiError(403, "USER_DISABLED", "Account is disabled.")
        session.expunge(user)
    token = create_session(request, user)
    return set_session_cookie(JSONResponse(content={"user": user_payload(user)}), request, token)


@router.post("/auth/logout")
def auth_logout(request: Request) -> JSONResponse:
    token = request.cookies.get(COOKIE_NAME)
    if token:
        with request.app.state.db.session() as session:
            record = session.execute(
                select(UserSession).where(UserSession.token_sha256 == token_sha256(token))
            ).scalar_one_or_none()
            if record is not None:
                session.delete(record)
                session.commit()
    response = JSONResponse(content={"ok": True})
    response.delete_cookie(COOKIE_NAME, path="/")
    return response


@router.get("/auth/me")
def auth_me(request: Request, user: User = Depends(current_user)) -> JSONResponse:
    return JSONResponse(content={"user": user_payload(user)})
