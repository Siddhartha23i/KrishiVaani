"""
Health check route module for KrishiVaani.
"""

from fastapi import APIRouter
from app.core.config import settings

router = APIRouter()


@router.get("/health", summary="Health Check", tags=["Monitoring"])
async def health_check():
    """
    Health check endpoint.
    Confirms that the FastAPI application is alive and responding.
    Preserves backward-compatible response fields while reflecting KrishiVaani metadata.
    """
    return {
        "status": "healthy",
        "application": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "stage": "backend-foundation",
    }

