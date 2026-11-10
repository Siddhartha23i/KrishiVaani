"""
KrishiVaani LLM Modular Reasoning Package — Phase 7.2.
Provides Groq openai/gpt-oss-120b integration, Pydantic schemas,
deterministic safety validation, and reasoning services.
"""

from app.llm.config import LLMConfig, get_llm_config, mask_api_key
from app.llm.schemas import (
    LLMResponseSchema,
    LLMReasoningRequest,
    FarmerContextSchema,
    ApprovedEvidenceItem,
    WeatherFactItem,
)
from app.llm.providers.groq_provider import GroqProvider
from app.llm.safety import LLMSafetyValidator
from app.llm.service import LLMReasoningService
from app.llm.knowledge_adapter import (
    ApprovedKnowledgeAdapter,
    KnowledgeRetrievalFilter,
    EvidenceRetrievalResult,
)
from app.llm.exceptions import (
    LLMError,
    LLMProviderNotConfiguredError,
    LLMAuthenticationError,
    LLMRateLimitError,
    LLMProviderUnavailableError,
    LLMTimeoutError,
    LLMMalformedResponseError,
    LLMSafetyViolationError,
    LLMAbstentionError,
)

__all__ = [
    "LLMConfig",
    "get_llm_config",
    "mask_api_key",
    "LLMResponseSchema",
    "LLMReasoningRequest",
    "FarmerContextSchema",
    "ApprovedEvidenceItem",
    "WeatherFactItem",
    "GroqProvider",
    "LLMSafetyValidator",
    "LLMReasoningService",
    "ApprovedKnowledgeAdapter",
    "KnowledgeRetrievalFilter",
    "EvidenceRetrievalResult",
    "LLMError",
    "LLMProviderNotConfiguredError",
    "LLMAuthenticationError",
    "LLMRateLimitError",
    "LLMProviderUnavailableError",
    "LLMTimeoutError",
    "LLMMalformedResponseError",
    "LLMSafetyViolationError",
    "LLMAbstentionError",
]

