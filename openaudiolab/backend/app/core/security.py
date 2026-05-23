import secrets
import string
from datetime import datetime, timedelta, timezone

import bcrypt

from app.core.config import settings


FORBIDDEN_PASSWORDS = {
    "admin123", "password", "changeme", "test123", "password123",
    "admin", "root", "12345678", "1234567890", "qwerty123",
    "letmein", "welcome1", "monkey", "dragon", "master",
    "abc123", "password1", "iloveyou", "trustno1", "openaudiolab",
}

MIN_PASSWORD_LENGTH = 12


def hash_password(password: str) -> str:
    salt = bcrypt.gensalt(rounds=12)
    hashed = bcrypt.hashpw(password.encode("utf-8"), salt)
    return hashed.decode("utf-8")


def verify_password(password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed_password.encode("utf-8"))
    except Exception:
        return False


def validate_password(password: str) -> list[str]:
    errors = []

    if len(password) < MIN_PASSWORD_LENGTH:
        errors.append(f"Password must be at least {MIN_PASSWORD_LENGTH} characters")

    if password.lower() in FORBIDDEN_PASSWORDS:
        errors.append("Password is too common or uses a forbidden placeholder")

    if not any(c.isupper() for c in password):
        errors.append("Password must contain at least one uppercase letter")

    if not any(c.islower() for c in password):
        errors.append("Password must contain at least one lowercase letter")

    if not any(c.isdigit() for c in password):
        errors.append("Password must contain at least one digit")

    return errors


def generate_secure_token(length: int = 32) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def generate_worker_api_token() -> str:
    return f"worker_{generate_secure_token(48)}"
