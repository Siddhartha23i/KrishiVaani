"""
Base weather provider interface for KrishiVaani — Phase 6.1.
Abstracts underlying meteorological data services (WeatherAPI, IMD, TSDPS)
to allow interchangeable provider routing without altering client services.
"""

from abc import ABC, abstractmethod
from typing import Optional

from app.weather.enums import ProviderStatus
from app.weather.schemas import CurrentWeatherConditions, WeatherForecastResponse


class BaseWeatherProvider(ABC):
    """
    Abstract interface for meteorological data providers.
    All providers must implement current weather and multi-day forecast retrieval,
    returning standardized Pydantic models.
    """

    @property
    @abstractmethod
    def provider_id(self) -> str:
        """Unique programmatic identifier for the provider."""
        pass

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Human-readable provider name."""
        pass

    @property
    @abstractmethod
    def provider_url(self) -> str:
        """Official website or API documentation portal."""
        pass

    @property
    @abstractmethod
    def attribution(self) -> str:
        """Required legal/terms attribution notice."""
        pass

    @abstractmethod
    def get_status(self) -> ProviderStatus:
        """Return the current operational status of this provider."""
        pass

    @abstractmethod
    def get_current_weather(
        self,
        query: str,
        lat: Optional[float] = None,
        lon: Optional[float] = None,
        language: str = "te-IN",
    ) -> CurrentWeatherConditions:
        """
        Retrieve and normalize real-time weather conditions for the specified location.
        May query by coordinates (lat/lon) or text location query.
        Includes localized disclaimer in requested language.
        """
        pass

    @abstractmethod
    def get_forecast(
        self,
        query: str,
        days: int = 3,
        lat: Optional[float] = None,
        lon: Optional[float] = None,
        language: str = "te-IN",
    ) -> WeatherForecastResponse:
        """
        Retrieve and normalize short-range multi-day weather forecast.
        Free plan limit: 3 days.
        Includes localized disclaimer in requested language.
        """
        pass

