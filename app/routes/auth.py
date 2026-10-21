"""Cookie-session auth endpoints for the website (register/login/logout/me)."""

from __future__ import annotations

from datetime import timedelta
import re
import secrets

from fastapi import APIRouter, Depends, File, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, select

from ..auth import (
    COOKIE_NAME,
    SESSION_TTL_DAYS,
    hash_password,
    new_session_token,
    token_sha256,
    verify_password,
)
from ..email import send_email
from ..errors import ApiError
from ..models import (
    Asset,
    AuthToken,
    CreditEntry,
    GuestSession,
    Job,
    User,
    UserSession,
    new_uuid,
    utcnow,
)
from ..orchestration import as_utc
from ..policies import current_policy_payload, record_policy_acceptance

router = APIRouter(tags=["auth"])


EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class RegisterRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    username: str = Field(min_length=2, max_length=80, pattern=r"^[a-zA-Z0-9_.-]+$")
    password: str = Field(min_length=8, max_length=200)
    confirm_password: str | None = Field(default=None, max_length=200)
    policy_accepted: bool = True
    policy_version: str | None = Field(default=None, max_length=80)
    marketing_consent: bool = False

    @field_validator("email")
    @classmethod
    def _validate_email(cls, value: str) -> str:
        if not EMAIL_RE.match(value.strip()):
            raise ValueError("Email is not valid.")
        return value


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=200)


class EmailRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)

    @field_validator("email")
    @classmethod
    def _validate_email(cls, value: str) -> str:
        if not EMAIL_RE.match(value.strip()):
            raise ValueError("Email is not valid.")
        return value


class PasswordResetConfirm(BaseModel):
    token: str = Field(min_length=10, max_length=200)
    new_password: str = Field(min_length=8, max_length=200)


class TokenConfirm(BaseModel):
    token: str = Field(min_length=10, max_length=200)


def user_payload(user: User) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "username": user.username,
        "role": user.role,
        "state": user.state,
        "plan": user.plan,
        "credits_balance": user.credits_balance,
        "stripe_customer_id": user.stripe_customer_id,
        "stripe_subscription_id": user.stripe_subscription_id,
        "subscription_status": user.subscription_status,
        "cancel_at_period_end": user.cancel_at_period_end,
        "current_period_end": user.current_period_end.isoformat() if user.current_period_end else None,
        "email_verified_at": user.email_verified_at.isoformat() if user.email_verified_at else None,
        "avatar_key": user.avatar_key,
        "bio": user.bio,
        "active_workspace_id": user.active_workspace_id,
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
    if token:
        with request.app.state.db.session() as session:
            record = session.execute(
                select(UserSession).where(UserSession.token_sha256 == token_sha256(token))
            ).scalar_one_or_none()
            if record is not None and as_utc(record.expires_at) > utcnow():
                user = session.get(User, record.user_id)
                if user is not None and user.state == "active":
                    session.expunge(user)
                    return user
                raise ApiError(403, "USER_DISABLED", "Account is missing or disabled.")
            raise ApiError(401, "SESSION_EXPIRED", "Session is missing or expired.")

    header = request.headers.get("Authorization")
    if header and header.lower().startswith("bearer "):
        from ..deps import owner_from_request

        owner_id = owner_from_request(request)
        if not owner_id.startswith("usr_"):
            raise ApiError(403, "ACCOUNT_REQUIRED", "An account session or account API key is required.")
        with request.app.state.db.session() as session:
            user = session.get(User, owner_id[4:])
            if user is None or user.state != "active":
                raise ApiError(403, "USER_DISABLED", "Account is missing or disabled.")
            session.expunge(user)
            return user

    raise ApiError(401, "UNAUTHENTICATED", "A session cookie or account API key is required.")


def require_admin(request: Request, user: User = Depends(current_user)) -> User:
    if user.role != "admin":
        raise ApiError(403, "ADMIN_REQUIRED", "Administrator role required.")
    return user


def _current_policy_version(request: Request) -> str:
    with request.app.state.db.session() as session:
        return current_policy_payload(session, request.app.state.settings)["version"]


def _issue_auth_token(session, user_id: str, purpose: str, request: Request) -> tuple[AuthToken, str]:
    token = secrets.token_urlsafe(32)
    record = AuthToken(
        user_id=user_id,
        purpose=purpose,
        token_sha256=token_sha256(token),
        expires_at=utcnow() + timedelta(minutes=request.app.state.settings.auth_token_ttl_minutes),
    )
    session.add(record)
    return record, token


def _send_auth_email(request: Request, user: User, purpose: str, token: str) -> str:
    base = request.app.state.settings.site_url.rstrip("/")
    if purpose == "verify_email":
        link = f"{base}/verify?token={token}"
        subject = "Verify your OpenAudioLab email"
        body = f"Confirm your email: {link}\n"
    else:
        link = f"{base}/recover?token={token}"
        subject = "Reset your OpenAudioLab password"
        body = f"Reset your password: {link}\n"
    return send_email(request.app.state.settings, user.email, subject, body)


@router.post("/auth/register", status_code=201)
def auth_register(payload: RegisterRequest, request: Request) -> JSONResponse:
    email = payload.email.strip().lower()
    if payload.confirm_password is not None and payload.confirm_password != payload.password:
        raise ApiError(422, "PASSWORD_CONFIRMATION", "Password confirmation does not match.")
    if not payload.policy_accepted:
        raise ApiError(422, "POLICY_ACCEPTANCE_REQUIRED", "Accept the Terms, Abuse Policy, and Privacy Notice.")
    current_version = _current_policy_version(request)
    if payload.policy_version and payload.policy_version != current_version:
        raise ApiError(422, "POLICY_VERSION_STALE", "Policy terms changed; reload and accept the current terms.")

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
        session.flush()
        signup_credits = request.app.state.settings.signup_credits
        user.credits_balance = signup_credits
        session.add(CreditEntry(owner_id=f"usr_{user.id}", delta=signup_credits, reason="signup"))
        record_policy_acceptance(
            session,
            "user",
            user.id,
            current_version,
            marketing_consent=payload.marketing_consent,
            user_agent=request.headers.get("user-agent", "")[:300] or None,
        )
        _, token = _issue_auth_token(session, user.id, "verify_email", request)
        session.commit()
        email_status = _send_auth_email(request, user, "verify_email", token)
    session_token = create_session(request, user)
    return set_session_cookie(
        JSONResponse(status_code=201, content={"user": user_payload(user), "email_status": email_status}),
        request,
        session_token,
    )


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


class ProfileUpdateRequest(BaseModel):
    username: str | None = Field(default=None, min_length=2, max_length=80, pattern=r"^[a-zA-Z0-9_.-]+$")
    email: str | None = Field(default=None, min_length=3, max_length=320)
    bio: str | None = Field(default=None, max_length=500)


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=8, max_length=200)


@router.patch("/auth/me")
def auth_update_me(
    payload: ProfileUpdateRequest, request: Request, user: User = Depends(current_user)
) -> JSONResponse:
    email = payload.email.strip().lower() if payload.email else None
    with request.app.state.db.session() as session:
        if email and session.execute(
            select(User).where(User.email == email, User.id != user.id)
        ).scalar_one_or_none():
            raise ApiError(409, "EMAIL_TAKEN", "Email already registered.")
        if payload.username and session.execute(
            select(User).where(User.username == payload.username, User.id != user.id)
        ).scalar_one_or_none():
            raise ApiError(409, "USERNAME_TAKEN", "Username already taken.")
        record = session.get(User, user.id)
        if payload.username:
            record.username = payload.username
        if email:
            record.email = email
        if payload.bio is not None:
            record.bio = payload.bio
        session.commit()
        session.refresh(record)
        session.expunge(record)
    return JSONResponse(content={"user": user_payload(record)})


@router.post("/auth/password")
def auth_change_password(
    payload: PasswordChangeRequest, request: Request, user: User = Depends(current_user)
) -> JSONResponse:
    with request.app.state.db.session() as session:
        record = session.get(User, user.id)
        if not verify_password(payload.current_password, record.password_hash):
            raise ApiError(401, "INVALID_CREDENTIALS", "Current password is incorrect.")
        record.password_hash = hash_password(payload.new_password)
        session.execute(delete(UserSession).where(UserSession.user_id == user.id))
        session.commit()
    token = create_session(request, user)
    return set_session_cookie(JSONResponse(content={"ok": True}), request, token)


AVATAR_MAX_BYTES = 2 * 1024 * 1024
AVATAR_MEDIA = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".gif": "image/gif"}


@router.post("/auth/avatar")
async def auth_upload_avatar(
    request: Request,
    user: User = Depends(current_user),
    file: UploadFile = File(...),
) -> JSONResponse:
    content_type = (file.content_type or "").lower()
    if not content_type.startswith("image/"):
        raise ApiError(422, "INVALID_FILE", "Avatar must be an image.")
    body = await file.read()
    if not body:
        raise ApiError(422, "EMPTY_FILE", "Avatar file is empty.")
    if len(body) > AVATAR_MAX_BYTES:
        raise ApiError(413, "FILE_TOO_LARGE", "Avatar must be 2 MB or smaller.")
    suffix = ""
    for ext in AVATAR_MEDIA:
        if (file.filename or "").lower().endswith(ext):
            suffix = ext
            break
    if not suffix:
        suffix = ".png" if content_type == "image/png" else ".jpg"
    key = f"owners/usr_{user.id}/avatar-{new_uuid()}{suffix}"
    request.app.state.storage.put(key, body)
    with request.app.state.db.session() as session:
        record = session.get(User, user.id)
        record.avatar_key = key
        session.commit()
        session.refresh(record)
        session.expunge(record)
    return JSONResponse(content={"user": user_payload(record)})


@router.get("/auth/avatar/{user_id}")
def auth_get_avatar(user_id: str, request: Request) -> Response:
    with request.app.state.db.session() as session:
        record = session.get(User, user_id)
    if record is None or not record.avatar_key:
        raise ApiError(404, "AVATAR_NOT_FOUND", "User has no avatar.")
    stored = request.app.state.storage.get(record.avatar_key)
    media = AVATAR_MEDIA.get(record.avatar_key[record.avatar_key.rfind(".") :].lower(), "application/octet-stream")
    return Response(content=stored.body, media_type=media, headers={"Cache-Control": "public, max-age=300"})


class GuestPolicyRequest(BaseModel):
    policy_accepted: bool = False
    policy_version: str | None = Field(default=None, max_length=80)
    marketing_consent: bool = False


def _guest_ip_hash(request: Request) -> str | None:
    import hashlib

    host = request.client.host if request.client else None
    if not host:
        return None
    return hashlib.sha256(host.encode("utf-8")).hexdigest()[:16]


def set_guest_cookie(response: JSONResponse, request: Request, token: str) -> JSONResponse:
    settings = request.app.state.settings
    response.set_cookie(
        key=settings.guest_cookie_name,
        value=token,
        max_age=settings.guest_session_ttl_days * 86400,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        path="/",
    )
    return response


@router.get("/policies")
def policies(request: Request) -> JSONResponse:
    with request.app.state.db.session() as session:
        return JSONResponse(current_policy_payload(session, request.app.state.settings))


@router.post("/auth/guest")
def auth_guest(request: Request) -> JSONResponse:
    from ..deps import guest_session_from_request
    from ..quota import guest_allowance

    settings = request.app.state.settings
    guest = guest_session_from_request(request)
    token = request.cookies.get(settings.guest_cookie_name)
    if guest is None:
        token = new_session_token()
        guest = GuestSession(
            token_sha256=token_sha256(token),
            expires_at=utcnow() + timedelta(days=settings.guest_session_ttl_days),
            ip_hash=_guest_ip_hash(request),
            user_agent=request.headers.get("user-agent", "")[:300] or None,
        )
        with request.app.state.db.session() as session:
            session.add(guest)
            session.commit()
            session.refresh(guest)
    with request.app.state.db.session() as session:
        fresh = session.get(GuestSession, guest.id)
        allowance = guest_allowance(session, fresh, settings)
    return set_guest_cookie(JSONResponse(content=allowance), request, token)


@router.get("/auth/guest")
def auth_guest_status(request: Request) -> JSONResponse:
    from ..deps import guest_session_from_request
    from ..quota import guest_allowance

    guest = guest_session_from_request(request)
    if guest is None:
        raise ApiError(404, "GUEST_NOT_FOUND", "No active guest session.")
    with request.app.state.db.session() as session:
        fresh = session.get(GuestSession, guest.id)
        return JSONResponse(guest_allowance(session, fresh, request.app.state.settings))


@router.post("/auth/guest/policies")
def auth_guest_policies(payload: GuestPolicyRequest, request: Request) -> JSONResponse:
    from ..deps import guest_session_from_request
    from ..quota import guest_allowance

    guest = guest_session_from_request(request)
    if guest is None:
        raise ApiError(401, "GUEST_NOT_FOUND", "No active guest session.")
    if not payload.policy_accepted:
        raise ApiError(422, "POLICY_ACCEPTANCE_REQUIRED", "Accept the Terms, Abuse Policy, and Privacy Notice.")
    current_version = _current_policy_version(request)
    if payload.policy_version and payload.policy_version != current_version:
        raise ApiError(422, "POLICY_VERSION_STALE", "Policy terms changed; reload and accept the current terms.")
    with request.app.state.db.session() as session:
        fresh = session.get(GuestSession, guest.id)
        fresh.policy_version = current_version
        fresh.policy_accepted_at = utcnow()
        fresh.marketing_consent = payload.marketing_consent
        record_policy_acceptance(
            session,
            "guest",
            fresh.id,
            current_version,
            marketing_consent=payload.marketing_consent,
            ip_hash=fresh.ip_hash,
            user_agent=fresh.user_agent,
        )
        session.commit()
        session.refresh(fresh)
        allowance = guest_allowance(session, fresh, request.app.state.settings)
    return JSONResponse(allowance)


@router.post("/auth/claim-guest-songs")
def auth_claim_guest_songs(request: Request, user: User = Depends(current_user)) -> JSONResponse:
    from ..deps import guest_session_from_request

    guest = guest_session_from_request(request)
    if guest is None:
        return JSONResponse({"claimed": False, "jobs": 0, "assets": 0, "reason": "no_guest"})
    if guest.claimed_user_id and guest.claimed_user_id != user.id:
        raise ApiError(409, "GUEST_ALREADY_CLAIMED", "This guest session was already claimed by another account.")
    guest_owner = f"g_{guest.id}"
    user_owner = f"usr_{user.id}"
    with request.app.state.db.session() as session:
        fresh = session.get(GuestSession, guest.id)
        jobs = list(session.execute(select(Job).where(Job.owner_id == guest_owner)).scalars())
        assets = list(session.execute(select(Asset).where(Asset.owner_id == guest_owner)).scalars())
        for job in jobs:
            job.owner_id = user_owner
        for asset in assets:
            asset.owner_id = user_owner
        fresh.claimed_user_id = user.id
        fresh.claimed_at = utcnow()
        session.commit()
    return JSONResponse({"claimed": True, "jobs": len(jobs), "assets": len(assets)})


@router.post("/auth/verify/request")
def auth_verify_request(payload: EmailRequest, request: Request) -> JSONResponse:
    email = payload.email.strip().lower()
    with request.app.state.db.session() as session:
        user = session.execute(select(User).where(User.email == email)).scalar_one_or_none()
        if user is None or user.email_verified_at is not None:
            return JSONResponse({"status": "pending"})
        _, token = _issue_auth_token(session, user.id, "verify_email", request)
        session.commit()
        session.expunge(user)
        status = _send_auth_email(request, user, "verify_email", token)
    return JSONResponse({"status": status})


@router.post("/auth/verify/confirm")
def auth_verify_confirm(payload: TokenConfirm, request: Request) -> JSONResponse:
    with request.app.state.db.session() as session:
        token = session.execute(
            select(AuthToken).where(
                AuthToken.token_sha256 == token_sha256(payload.token),
                AuthToken.purpose == "verify_email",
                AuthToken.used_at.is_(None),
                AuthToken.expires_at > utcnow(),
            )
        ).scalar_one_or_none()
        if token is None:
            raise ApiError(401, "TOKEN_INVALID", "Verification token is invalid or expired.")
        user = session.get(User, token.user_id)
        if user is None:
            raise ApiError(404, "USER_NOT_FOUND", "Account not found.")
        user.email_verified_at = utcnow()
        token.used_at = utcnow()
        session.commit()
        session.expunge(user)
    session_token = create_session(request, user)
    return set_session_cookie(JSONResponse(content={"user": user_payload(user)}), request, session_token)


@router.post("/auth/password/reset/request")
def auth_password_reset_request(payload: EmailRequest, request: Request) -> JSONResponse:
    email = payload.email.strip().lower()
    with request.app.state.db.session() as session:
        user = session.execute(select(User).where(User.email == email)).scalar_one_or_none()
        if user is None:
            return JSONResponse({"status": "pending"})
        _, token = _issue_auth_token(session, user.id, "password_reset", request)
        session.commit()
        session.expunge(user)
        status = _send_auth_email(request, user, "password_reset", token)
    return JSONResponse({"status": status})


@router.post("/auth/password/reset/confirm")
def auth_password_reset_confirm(payload: PasswordResetConfirm, request: Request) -> JSONResponse:
    with request.app.state.db.session() as session:
        token = session.execute(
            select(AuthToken).where(
                AuthToken.token_sha256 == token_sha256(payload.token),
                AuthToken.purpose == "password_reset",
                AuthToken.used_at.is_(None),
                AuthToken.expires_at > utcnow(),
            )
        ).scalar_one_or_none()
        if token is None:
            raise ApiError(401, "TOKEN_INVALID", "Reset token is invalid or expired.")
        user = session.get(User, token.user_id)
        if user is None:
            raise ApiError(404, "USER_NOT_FOUND", "Account not found.")
        user.password_hash = hash_password(payload.new_password)
        token.used_at = utcnow()
        session.execute(delete(UserSession).where(UserSession.user_id == user.id))
        session.commit()
        session.expunge(user)
    session_token = create_session(request, user)
    return set_session_cookie(JSONResponse(content={"user": user_payload(user)}), request, session_token)
