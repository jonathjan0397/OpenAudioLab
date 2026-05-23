from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from jwt import PyJWTError

from app.core.config import settings
from app.core.security import hash_password, verify_password
from app.db.models import User
from app.db.session import SessionLocal


ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.JWT_SECRET, algorithm=ALGORITHM)


def decode_access_token(token: str) -> Optional[dict]:
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[ALGORITHM])
        return payload
    except PyJWTError:
        return None


def authenticate_user(email: str, password: str) -> Optional[User]:
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
        if user and verify_password(password, user.password_hash):
            return user
        return None
    finally:
        db.close()


def create_admin_user(email: str, password: str) -> User:
    db = SessionLocal()
    try:
        user = User(
            email=email,
            password_hash=hash_password(password),
            is_admin=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user
    finally:
        db.close()


def get_user_by_id(user_id: str) -> Optional[User]:
    db = SessionLocal()
    try:
        return db.query(User).filter(User.id == user_id).first()
    finally:
        db.close()
