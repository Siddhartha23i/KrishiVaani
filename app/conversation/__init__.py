"""
KrishiVaani Conversation Package — Phase 7.5.

Orchestrates text-based dialogues between farmers and KrishiVaani,
integrating farmer context, weather services, approved evidence retrieval,
Groq reasoning inference, and deterministic safety validation.
"""

from app.conversation.schemas import (
    ConversationRequest,
    ConversationResponse,
    LocationInput,
    WeatherMetadata,
    GuestWeatherConsentEvent,
)
from app.conversation.service import (
    ConversationOrchestrator,
    normalize_language,
)
from app.conversation.intent import (
    classify_intent,
    is_weather_query,
    INTENT_WEATHER_INQUIRY,
    INTENT_CROP_RECOMMENDATION,
    INTENT_PEST_DISEASE_INQUIRY,
    INTENT_FERTILIZER_GUIDANCE,
    INTENT_GOVERNMENT_SCHEME,
    INTENT_AGRICULTURAL_ADVICE,
    INTENT_GENERAL_CONVERSATION,
)

__all__ = [
    "ConversationOrchestrator",
    "ConversationRequest",
    "ConversationResponse",
    "LocationInput",
    "WeatherMetadata",
    "GuestWeatherConsentEvent",
    "normalize_language",
    "classify_intent",
    "is_weather_query",
    "INTENT_WEATHER_INQUIRY",
    "INTENT_CROP_RECOMMENDATION",
    "INTENT_PEST_DISEASE_INQUIRY",
    "INTENT_FERTILIZER_GUIDANCE",
    "INTENT_GOVERNMENT_SCHEME",
    "INTENT_AGRICULTURAL_ADVICE",
    "INTENT_GENERAL_CONVERSATION",
]

