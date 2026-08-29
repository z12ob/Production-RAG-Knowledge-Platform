import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import RedirectResponse

from app.api.auth import router as auth_router
from app.api.documents import router as documents_router
from app.api.health import router as health_router
from app.api.knowledge_bases import router as knowledge_bases_router
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import engine

settings = get_settings()
configure_logging(settings.log_level)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    logger.info("Application started in %s mode", settings.environment.value)
    try:
        yield
    finally:
        engine.dispose()
        logger.info("Application stopped")


def redirect_to_docs() -> RedirectResponse:
    return RedirectResponse(url="/docs")


def create_app() -> FastAPI:
    application = FastAPI(
        title=settings.app_name,
        summary="API foundation for a production-style knowledge platform.",
        version=settings.app_version,
        lifespan=lifespan,
    )
    application.add_api_route(
        "/",
        redirect_to_docs,
        methods=["GET"],
        include_in_schema=False,
    )
    application.include_router(health_router)
    application.include_router(auth_router)
    application.include_router(knowledge_bases_router)
    application.include_router(documents_router)
    return application


app = create_app()
