from fastapi import APIRouter

router = APIRouter(prefix="/api/health", tags=["health"])


@router.get("")
@router.get("/")
async def health_check():
    return {
        "status": "healthy",
        "service": "openaudiolab-backend",
        "version": "0.1.0-foundation",
    }
