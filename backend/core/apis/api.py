"""FastAPI application aggregator.

Owns application creation, lifespan wiring, middleware, global exception handling, and router
registration. Endpoint logic lives in ``core/apis/routes``.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from commons.redis_client import close_redis_connection
from core import logger
from core.apis.routes.account_router import account_router
from core.apis.routes.admin_question_router import admin_question_router
from core.apis.routes.attempt_router import attempt_router
from core.apis.routes.auth_router import auth_router
from core.apis.routes.billing_router import billing_router
from core.apis.routes.email_router import email_router
from core.apis.routes.health_router import health_router
from core.apis.routes.question_router import question_router
from core.apis.routes.review_router import review_router
from core.apis.routes.session_router import session_router
from core.config.settings import settings
from core.database.database import close_database_connection

logging = logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """
    Manage application startup and shutdown.

    Connections are created lazily by their own modules; this hook exists to close them
    deterministically so a redeploy does not leak database or Redis connections.

    Args:
        app: The FastAPI application instance.

    Returns:
        AsyncIterator[None]: Lifespan context.
    """
    logging.info(f"Starting {settings.APP_NAME} in {settings.ENVIRONMENT} environment")
    yield
    logging.info(f"Shutting down {settings.APP_NAME}")
    await close_database_connection()
    await close_redis_connection()


def create_app() -> FastAPI:
    """
    Build and configure the FastAPI application.

    Interactive documentation is disabled in production so the full API surface and schemas are
    not published to unauthenticated clients.

    Returns:
        FastAPI: The configured application instance.
    """
    app = FastAPI(
        title=settings.APP_NAME,
        version="0.1.0",
        lifespan=lifespan,
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None,
        openapi_url=None if settings.is_production else "/openapi.json",
    )

    if settings.CORS_ORIGINS:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.CORS_ORIGINS,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        """
        Convert any unhandled exception into a generic 500 response.

        The exception detail is logged but never returned, so internal paths, queries, and
        library internals are not disclosed to clients.

        Args:
            request: The incoming request that failed.
            exc: The unhandled exception.

        Returns:
            JSONResponse: Generic 500 error payload.
        """
        logging.error(f"Unhandled error on {request.method} {request.url.path}: {exc}")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "Internal Server Error"},
        )

    # Health is infrastructure, not product API: registered unversioned so probe URLs are
    # stable across future API versions.
    app.include_router(health_router, tags=["health"])
    app.include_router(auth_router, tags=["auth"])
    app.include_router(account_router, tags=["account"])
    app.include_router(question_router, tags=["questions"])
    app.include_router(session_router, tags=["sessions"])
    app.include_router(attempt_router, tags=["attempts"])
    app.include_router(review_router, tags=["review"])
    app.include_router(billing_router, tags=["billing"])
    app.include_router(email_router, tags=["email"])
    app.include_router(admin_question_router, tags=["admin"])

    return app


app = create_app()
