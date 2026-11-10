"""
Weather domain exceptions for KrishiVaani — Phase 6.1.
Enforces unambiguous error classification without masking failures as missing data.
"""

from typing import Optional, Dict, Any


class WeatherError(Exception):
    """Base class for all weather domain exceptions in KrishiVaani."""

    def __init__(self, message: str, provider: Optional[str] = None, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.provider = provider
        self.details = details or {}


class ProviderNotConfiguredError(WeatherError):
    """Raised when an operation is requested on an unconfigured weather provider."""
    pass


class ProviderAuthenticationError(WeatherError):
    """Raised when provider credentials fail authentication (HTTP 401/403)."""
    pass


class ProviderRateLimitError(WeatherError):
    """Raised when provider API rate limit or quota is exceeded (HTTP 429)."""
    pass


class ProviderUnavailableError(WeatherError):
    """Raised when provider service is unreachable, timed out, or returned HTTP 5xx."""
    pass


class LocationNotFoundError(WeatherError):
    """Raised when a location query cannot be resolved by the weather provider."""
    pass


class LocationAmbiguityError(WeatherError):
    """Raised when a location query is ambiguous or returned coordinates are contradictory."""
    pass


class LocationCountryMismatchError(LocationAmbiguityError):
    """Raised when provider returns a location outside India for an Indian farmer query."""
    pass


class LocationDistrictMismatchError(LocationAmbiguityError):
    """Raised when provider resolves a location in a different district from farmer's confirmed profile."""
    pass


class WeatherLocationSharingConsentRequiredError(WeatherError):
    """Raised when weather retrieval is requested for a farmer without explicit third-party location sharing consent."""
    pass


class ForecastDaysLimitExceededError(WeatherError):
    """Raised when forecast days exceed the authorized provider tier (e.g. >3 days on Free plan)."""
    pass


class InvalidProviderResponseError(WeatherError):
    """Raised when provider returns malformed, incomplete, or unparseable JSON payload."""
    pass


class NoCurrentDataError(WeatherError):
    """Raised when no active weather data is available for the resolved location."""
    pass

