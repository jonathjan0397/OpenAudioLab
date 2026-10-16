from .health import router as health_router
from .jobs import router as jobs_router
from .models import router as models_router
from .projects import router as projects_router
from .uploads import router as uploads_router
from .exports import router as exports_router
from .artist import router as artist_router
from .internal import router as internal_router
from .lab import router as lab_router
from .auth import router as auth_router
from .admin import router as admin_router
from .seo import router as seo_router

__all__ = [
    "health_router",
    "jobs_router",
    "models_router",
    "projects_router",
    "uploads_router",
    "exports_router",
    "artist_router",
    "internal_router",
    "lab_router",
    "auth_router",
    "admin_router",
    "seo_router",
]
