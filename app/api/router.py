"""
Centralized API router for KrishiVaani backend.
Combines sub-routers across distinct domain modules.
"""

from fastapi import APIRouter
from app.api.routes import health, farmers, knowledge, weather, voice, whatsapp, twilio

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

# Register WhatsApp Cloud API routes (accessible at /api/v1/whatsapp/webhook and /webhook)
api_router.include_router(whatsapp.router, prefix="/api/v1/whatsapp", tags=["WhatsApp Cloud API"])
api_router.include_router(whatsapp.router, tags=["WhatsApp Cloud API Root"])

# Register Twilio WhatsApp Sandbox routes (Phase 8.2 Integration)
api_router.include_router(twilio.router, prefix="/api/v1/twilio", tags=["Twilio WhatsApp"])

