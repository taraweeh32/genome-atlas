"""FastAPI application factory: startup, shutdown, middleware, routing.

Startup order is deliberate:
1. validate all configuration (fail fast, no unsafe defaults),
2. configure structured logging,
3. build the composition root and connect infrastructure,
4. install middleware, error handlers and the versioned router.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from app import __version__
from app.api.errors import register_exception_handlers
from app.api.openapi import API_DESCRIPTION, API_TITLE, OPENAPI_TAGS
from app.api.v1.router import api_v1_router
from app.application.container import Container
from app.core.app_config import get_application_settings
from app.core.environment import get_environment_settings
from app.core.logging import configure_logging, get_logger
from app.core.scientific_config import get_scientific_settings
from app.infrastructure.observability.middleware import (
    AccessLogMiddleware,
    CorrelationIdMiddleware,
    RequestSizeLimitMiddleware,
    SecurityHeadersMiddleware,
)

logger = get_logger(__name__)


def create_app() -> FastAPI:
    # Configuration validation happens before anything else can run.
    environment = get_environment_settings()
    application = get_application_settings()
    get_scientific_settings()

    configure_logging(environment.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        logger.info(
            "application starting",
            extra={"environment": environment.environment.value, "version": __version__},
        )
        container = Container.build()
        await container.startup()
        app.state.container = container
        logger.info("application started")
        try:
            yield
        finally:
            logger.info("application stopping")
            await container.shutdown()
            app.state.container = None
            logger.info("application stopped")

    docs_enabled = (
        application.feature_openapi_docs and not environment.environment.is_production_like
    )
    app = FastAPI(
        title=API_TITLE,
        description=API_DESCRIPTION,
        version=__version__,
        openapi_tags=OPENAPI_TAGS,
        lifespan=lifespan,
        docs_url=f"{application.api_prefix}/docs" if docs_enabled else None,
        redoc_url=None,
        openapi_url=f"{application.api_prefix}/openapi.json" if docs_enabled else None,
    )

    # Middleware executes bottom-up: correlation ID is outermost so every log
    # line and every error response carries it.
    app.add_middleware(
        RequestSizeLimitMiddleware, max_bytes=environment.transport.max_request_body_bytes
    )
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(AccessLogMiddleware)
    app.add_middleware(CorrelationIdMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=environment.transport.cors_origin_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Correlation-ID"],
    )

    register_exception_handlers(app, environment.environment)
    app.include_router(api_v1_router, prefix=application.api_prefix)
    return app


app = create_app()
