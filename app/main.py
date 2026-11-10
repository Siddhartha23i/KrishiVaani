"""
KrishiVaani - Main FastAPI Application Factory.
Provides application instance, global routes, and centralized router registration.
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.core.config import settings
from app.api.router import api_router
from app.db.database import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan context manager.
    Initializes database schema and handles startup/shutdown hooks.
    """
    init_db()
    yield


def create_application() -> FastAPI:
    """
    Application factory initializing FastAPI with configured metadata and routes.
    """
    application = FastAPI(
        title=settings.PROJECT_NAME,
        description=settings.DESCRIPTION,
        version=settings.VERSION,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    # Register centralized API router (includes /health, and future feature routers)
    application.include_router(api_router, prefix=settings.API_PREFIX)

    @application.get("/", summary="Root Status", tags=["Monitoring"])
    async def home():
        """
        Root endpoint confirming that the KrishiVaani backend is accessible.
        Preserves backward compatibility with earlier health inspections.
        """
        return {
            "application": settings.PROJECT_NAME,
            "message": "Backend is running!",
            "version": settings.VERSION,
        }

    return application


app = create_application()

