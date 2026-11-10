"""
LLM domain exceptions for KrishiVaani — Phase 7.2.
Provides unambiguous error classification for provider operations,
authentication, timeouts, malformed responses, and deterministic safety checks.
"""

from typing import Optional, Dict, Any


class LLMError(Exception):
    """Base class for all LLM domain exceptions in KrishiVaani."""

    def __init__(self, message: str, provider: Optional[str] = None, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.provider = provider
        self.details = details or {}


class LLMProviderNotConfiguredError(LLMError):
    """Raised when an operation is requested on an unconfigured LLM provider (e.g. missing API key)."""
    pass


class LLMAuthenticationError(LLMError):
    """Raised when LLM provider credentials fail authentication (HTTP 401/403)."""
    pass


class LLMRateLimitError(LLMError):
    """Raised when LLM provider rate limit or quota is exceeded (HTTP 429)."""
    pass


class LLMProviderUnavailableError(LLMError):
    """Raised when LLM provider service is unreachable or returned HTTP 5xx."""
    pass


class LLMTimeoutError(LLMError):
    """Raised when an LLM API request times out."""
    pass


class LLMMalformedResponseError(LLMError):
    """Raised when LLM provider returns invalid JSON or schema-violating payload."""
    pass


class LLMSafetyViolationError(LLMError):
    """Raised when model response violates deterministic factual safety policies."""
    pass


class LLMAbstentionError(LLMError):
    """Raised when the LLM service must abstain due to missing or invalid evidence."""
    pass

