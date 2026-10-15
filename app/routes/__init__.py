from .health import router as health_router
from .jobs import router as jobs_router
from .models import router as models_router
from .projects import router as projects_router
from .uploads import router as uploads_router
from .exports import router as exports_router

__all__ = [
    "health_router",
    "jobs_router",
    "models_router",
    "projects_router",
    "uploads_router",
    "exports_router",
]
