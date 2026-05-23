from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException

from app.auth.dependencies import require_auth
from app.auth.service import AuthService
from app.db.models import User

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=255)
    password: str = Field(..., min_length=1)


@router.post("/login")
async def login(request: LoginRequest):
    result = AuthService.login(request.email, request.password)
    if result is None:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    return result


@router.post("/logout")
async def logout(current_user: User = Depends(require_auth)):
    return {"message": "Logged out successfully"}


@router.get("/me")
async def get_me(current_user: User = Depends(require_auth)):
    return AuthService.get_me(current_user)
