import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.logging import setup_logging
from app.db.base import Base
from app.db.session import engine
from app.setup.service import SetupService

setup_logging()
logger = logging.getLogger("openaudiolab")

app = FastAPI(
    title="OpenAudiolab",
    version="0.1.0-foundation",
    docs_url="/api/docs" if not settings.is_production else None,
    redoc_url="/api/redoc" if not settings.is_production else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from app.api.health import router as health_router
from app.api.setup import router as setup_router
from app.api.auth import router as auth_router
from app.api.system import router as system_router
from app.api.jobs import router as jobs_router
from app.api.agents import router as agents_router
from app.api.models import router as models_router
from app.api.storage import router as storage_router
from app.api.settings import router as settings_router

app.include_router(health_router)
app.include_router(setup_router)
app.include_router(auth_router)
app.include_router(system_router)
app.include_router(jobs_router)
app.include_router(agents_router)
app.include_router(models_router)
app.include_router(storage_router)
app.include_router(settings_router)


@app.on_event("startup")
async def startup():
    # Create tables after DB is ready (fixes race condition with postgres healthcheck)
    Base.metadata.create_all(bind=engine)

    warnings = settings.validate_production_secrets()
    for warning in warnings:
        logger.warning(warning)

    setup_status = SetupService.get_setup_status()
    if not setup_status.get("setup_completed"):
        logger.info("System is in first-run setup mode. Visit /setup to configure.")

    logger.info(f"OpenAudiolab backend started (env={settings.APP_ENV})")
