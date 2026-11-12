"""
Centralized API router for KrishiVaani backend.
Combines sub-routers across distinct domain modules.
"""

from fastapi import APIRouter
from app.api.routes import health, farmers, knowledge, weather, voice

api_router = APIRouter()

# Register health check route
api_router.include_router(health.router)

# Register farmers onboarding and profile management routes
api_router.include_router(farmers.router, prefix="/api/v1/farmers", tags=["Farmers"])

# Register agricultural knowledge base search routes
api_router.include_router(knowledge.router, prefix="/api/v1/knowledge", tags=["Knowledge Base"])

# Register weather intelligence service routes
api_router.include_router(weather.router, prefix="/api/v1/weather", tags=["Weather Intelligence"])

# Register voice pipeline routes
api_router.include_router(voice.router, prefix="/api/v1/voice", tags=["Voice Pipeline"])

