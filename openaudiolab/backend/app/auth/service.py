from typing import Optional

from app.auth.jwt import create_access_token
from app.core.security import validate_password
from app.db.models import User
from app.db.session import SessionLocal


class AuthService:
    @staticmethod
    def login(email: str, password: str) -> Optional[dict]:
        from app.auth.jwt import authenticate_user

        user = authenticate_user(email, password)
        if user is None:
            return None

        token = create_access_token(data={"sub": user.id})
        return {
            "access_token": token,
            "token_type": "bearer",
            "user": {
                "id": user.id,
                "email": user.email,
                "is_admin": user.is_admin,
            },
        }

    @staticmethod
    def get_me(user: User) -> dict:
        return {
            "id": user.id,
            "email": user.email,
            "is_admin": user.is_admin,
            "created_at": user.created_at.isoformat() if user.created_at else None,
        }

    @staticmethod
    def create_user(email: str, password: str, is_admin: bool = False) -> tuple[Optional[User], list[str]]:
        errors = validate_password(password)
        if errors:
            return None, errors

        db = SessionLocal()
        try:
            existing = db.query(User).filter(User.email == email).first()
            if existing:
                return None, ["Email already registered"]

            from app.core.security import hash_password

            user = User(
                email=email,
                password_hash=hash_password(password),
                is_admin=is_admin,
            )
            db.add(user)
            db.commit()
            db.refresh(user)
            return user, []
        finally:
            db.close()
