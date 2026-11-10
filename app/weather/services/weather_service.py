"""
Weather intelligence service for KrishiVaani — Phase 6.1.
Orchestrates meteorological data retrieval across providers, validates farmer
locations, enforces provider limits, and maintains standing safety rules.
"""

from typing import Optional, Dict, Any, List, Tuple
from pathlib import Path

from app.models.farmer import FarmerModel
from app.services.farmer_service import FarmerService
from app.weather.enums import (
    ProviderStatus,
    WeatherForecastHorizon,
)
from app.weather.schemas import (
    CurrentWeatherConditions,
    WeatherForecastResponse,
    WeatherServiceStatusResponse,
    IMDDistrictWarning,
    IMDDistrictNowcast,
    IMDDistrictRainfallObservation,
    IMDDistrictRainfallForecast,
    IMDStationObservation,
    IMDCityForecast,
)
from app.weather.exceptions import (
    LocationNotFoundError,
    LocationDistrictMismatchError,
    ForecastDaysLimitExceededError,
    WeatherLocationSharingConsentRequiredError,
)
from app.weather.cache import weather_cache
from app.weather.providers.base import BaseWeatherProvider
from app.weather.providers.weatherapi_provider import WeatherAPIProvider
from app.weather.providers.imd_provider import IMDWeatherProvider
from app.weather.providers.imd_public_warning_adapter import (
    IMDPublicWarningAdapter,
    IMDDistrictDayWarningRecord,
    IMDDistrict5DayWarningBulletin,
)
from app.weather.services.location_weather_service import LocationWeatherService
from app.weather.source_registry import WeatherSourceRegistry


class WeatherService:
    """
    Central business service for weather intelligence.
    Routes queries to authorized weather providers, validates geographic consistency,
    and returns normalized meteorological observations and forecasts.
    """

    def __init__(
        self,
        farmer_service: Optional[FarmerService] = None,
        weatherapi_provider: Optional[BaseWeatherProvider] = None,
        imd_provider: Optional[BaseWeatherProvider] = None,
        imd_warning_adapter: Optional[IMDPublicWarningAdapter] = None,
        db_path: Optional[Path] = None,
    ):
        self.farmer_service = farmer_service or FarmerService(db_path=db_path)
        self.weatherapi_provider = weatherapi_provider or WeatherAPIProvider()
        self.imd_provider = imd_provider or IMDWeatherProvider()
        self.imd_warning_adapter = imd_warning_adapter or IMDPublicWarningAdapter()

    def get_service_status(self) -> WeatherServiceStatusResponse:
        """
        Report current operational health and provider readiness.
        """
        wapi_status = self.weatherapi_provider.get_status()
        imd_status = self.imd_provider.get_status()

        configured = WeatherSourceRegistry.get_active_providers_status(wapi_status, imd_status)

        overall_status = "operational" if (wapi_status == ProviderStatus.CONFIGURED or imd_status == ProviderStatus.CONFIGURED) else "unconfigured"

        supported_horizons = [
            WeatherForecastHorizon.SHORT_RANGE_1_3D.value,
            WeatherForecastHorizon.MEDIUM_RANGE_4_7D.value,
        ]

        notes = [
            "WeatherAPI.com Free plan provides current conditions and up to 3 days forecast (100k calls/month).",
            "Third-party location sharing requires explicit farmer consent separate from local profile storage consent.",
            "Deployment requirement: Formal Data Processing Agreement (DPA) review required for commercial weather providers.",
            "IMD official API integration is pending approved credentials (API Key + JWT Token, static IP mapping).",
            "TSDPS mandal-level rainfall AWS telemetry is pending official machine-readable REST API access.",
            "Weather forecasts alone must NEVER trigger automatic agricultural recommendations (Phase 5.4.1 safety policy).",
        ]

        return WeatherServiceStatusResponse(
            status=overall_status,
            configured_providers=configured,
            default_provider=self.weatherapi_provider.provider_id if wapi_status == ProviderStatus.CONFIGURED else None,
            supported_horizons=supported_horizons,
            cache_entries_count=weather_cache.count(),
            notes=notes,
        )

    def get_current_weather(self, farmer_id: str) -> CurrentWeatherConditions:
        """
        Retrieve normalized real-time weather conditions for a confirmed farmer profile.
        Prioritizes verified coordinates, validates against district mismatch, and caches result.
        Enforces third-party location sharing consent.
        """
        farmer = self.farmer_service.get_farmer_by_id(farmer_id)
        if not farmer:
            raise LocationNotFoundError(
                f"Farmer profile with ID '{farmer_id}' does not exist.",
            )

        # Build location query (enforces weather_provider_sharing_consent)
        query_str, lat, lon = LocationWeatherService.build_location_query(farmer)
        preferred_lang = farmer.preferred_language or "te-IN"

        # Execute query against active short-range provider
        result = self.weatherapi_provider.get_current_weather(
            query=query_str,
            lat=lat,
            lon=lon,
            language=preferred_lang,
        )

        # Post-retrieval validation: country check, district consistency check
        LocationWeatherService.validate_resolved_location(result.location, farmer)

        return result

    def _resolve_context_and_consent(
        self,
        district_name: Optional[str] = None,
        farmer_id: Optional[str] = None,
        language: Optional[str] = None,
    ) -> Tuple[Optional[str], str]:
        """
        Resolve target Telangana district and user language, enforcing third-party location sharing consent
        if a farmer profile is referenced.
        """
        resolved_district = district_name
        resolved_lang = language or "te-IN"

        if farmer_id:
            farmer = self.farmer_service.get_farmer_by_id(farmer_id)
            if not farmer:
                raise LocationNotFoundError(f"Farmer profile with ID '{farmer_id}' does not exist.")
            if not getattr(farmer, "weather_provider_sharing_consent", False):
                raise WeatherLocationSharingConsentRequiredError(
                    "Farmer profile has not consented to sharing location data with external weather providers.",
                    details={
                        "farmer_id": farmer.farmer_id,
                        "consent_required": "weather_provider_sharing_consent",
                    },
                )
            if not resolved_district:
                resolved_district = farmer.district_name
            if not language and farmer.preferred_language:
                resolved_lang = farmer.preferred_language

        if resolved_district and resolved_district.strip():
            matched = LocationWeatherService.resolve_telangana_district(resolved_district)
            if not matched:
                raise LocationDistrictMismatchError(
                    f"District '{resolved_district}' is not a recognized Telangana revenue district.",
                    details={"requested_district": resolved_district},
                )
            resolved_district = matched.district_name

        return resolved_district, resolved_lang

    def get_imd_district_warnings(
        self,
        district_name: Optional[str] = None,
        farmer_id: Optional[str] = None,
        language: Optional[str] = None,
    ) -> List[IMDDistrictWarning]:
        """
        Retrieve official IMD 5-day district warnings for a verified Telangana district or farmer profile.
        """
        target_dist, lang = self._resolve_context_and_consent(district_name, farmer_id, language)
        if isinstance(self.imd_provider, IMDWeatherProvider):
            return self.imd_provider.get_district_warnings(district_name=target_dist, language=lang)
        raise NotImplementedError("Current IMD provider does not support district warnings.")

    def get_imd_district_nowcast(
        self,
        district_name: Optional[str] = None,
        farmer_id: Optional[str] = None,
        language: Optional[str] = None,
    ) -> List[IMDDistrictNowcast]:
        """
        Retrieve official short-lived IMD district nowcasts.
        """
        target_dist, lang = self._resolve_context_and_consent(district_name, farmer_id, language)
        if isinstance(self.imd_provider, IMDWeatherProvider):
            return self.imd_provider.get_district_nowcast(district_name=target_dist, language=lang)
        raise NotImplementedError("Current IMD provider does not support district nowcasts.")

    def get_imd_district_rainfall(
        self,
        district_name: Optional[str] = None,
        farmer_id: Optional[str] = None,
    ) -> List[IMDDistrictRainfallObservation]:
        """
        Retrieve official IMD district rainfall telemetry observations.
        """
        target_dist, _ = self._resolve_context_and_consent(district_name, farmer_id)
        if isinstance(self.imd_provider, IMDWeatherProvider):
            return self.imd_provider.get_district_rainfall(district_name=target_dist)
        raise NotImplementedError("Current IMD provider does not support district rainfall observations.")

    def get_imd_district_rainfall_forecast(
        self,
        district_name: Optional[str] = None,
        farmer_id: Optional[str] = None,
        language: Optional[str] = None,
    ) -> List[IMDDistrictRainfallForecast]:
        """
        Retrieve official IMD 5-day district rainfall distribution forecast.
        """
        target_dist, lang = self._resolve_context_and_consent(district_name, farmer_id, language)
        if isinstance(self.imd_provider, IMDWeatherProvider):
            return self.imd_provider.get_district_rainfall_forecast(district_name=target_dist, language=lang)
        raise NotImplementedError("Current IMD provider does not support district rainfall forecast.")

    def get_imd_station_weather(self, station_id: str) -> IMDStationObservation:
        """
        Retrieve ground observations from a verified named IMD station.
        """
        if isinstance(self.imd_provider, IMDWeatherProvider):
            return self.imd_provider.get_station_weather(station_id=station_id)
        raise NotImplementedError("Current IMD provider does not support station weather.")

    def get_imd_city_forecast(self, city_id: str, language: Optional[str] = None) -> IMDCityForecast:
        """
        Retrieve official 7-day city weather forecast for a verified Telangana city/station.
        """
        lang = language or "te-IN"
        if isinstance(self.imd_provider, IMDWeatherProvider):
            return self.imd_provider.get_city_forecast(city_id=city_id, language=lang)
        raise NotImplementedError("Current IMD provider does not support city forecast.")

    def get_forecast(self, farmer_id: str, days: int = 3) -> WeatherForecastResponse:
        """
        Retrieve normalized short-range weather forecast for a confirmed farmer profile.
        Enforces Free plan limit of 3 days. Enforces third-party location sharing consent.
        """
        if days < 1:
            days = 1
        if days > 3:
            raise ForecastDaysLimitExceededError(
                f"WeatherAPI.com Free plan supports a maximum of 3 forecast days. Requested: {days}.",
                provider=self.weatherapi_provider.provider_name,
                details={"requested_days": days, "max_allowed_days": 3},
            )

        farmer = self.farmer_service.get_farmer_by_id(farmer_id)
        if not farmer:
            raise LocationNotFoundError(
                f"Farmer profile with ID '{farmer_id}' does not exist.",
            )

        query_str, lat, lon = LocationWeatherService.build_location_query(farmer)
        preferred_lang = farmer.preferred_language or "te-IN"

        result = self.weatherapi_provider.get_forecast(
            query=query_str,
            days=days,
            lat=lat,
            lon=lon,
            language=preferred_lang,
        )

        LocationWeatherService.validate_resolved_location(result.location, farmer)

        return result

    def _resolve_context_and_consent(
        self,
        district_name: Optional[str] = None,
        farmer_id: Optional[str] = None,
        language: Optional[str] = None,
    ) -> Tuple[Optional[str], str]:
        """
        Resolve target Telangana district and user language, enforcing third-party location sharing consent
        if a farmer profile is referenced.
        """
        resolved_district = district_name
        resolved_lang = language or "te-IN"

        if farmer_id:
            farmer = self.farmer_service.get_farmer_by_id(farmer_id)
            if not farmer:
                raise LocationNotFoundError(f"Farmer profile with ID '{farmer_id}' does not exist.")
            if not getattr(farmer, "weather_provider_sharing_consent", False):
                raise WeatherLocationSharingConsentRequiredError(
                    "Farmer profile has not consented to sharing location data with external weather providers.",
                    details={
                        "farmer_id": farmer.farmer_id,
                        "consent_required": "weather_provider_sharing_consent",
                    },
                )
            if not resolved_district:
                resolved_district = farmer.district_name
            if not language and farmer.preferred_language:
                resolved_lang = farmer.preferred_language

        if resolved_district and resolved_district.strip():
            matched = LocationWeatherService.resolve_telangana_district(resolved_district)
            if not matched:
                raise LocationDistrictMismatchError(
                    f"District '{resolved_district}' is not a recognized Telangana revenue district.",
                    details={"requested_district": resolved_district},
                )
            resolved_district = matched.district_name

        return resolved_district, resolved_lang

    def get_imd_district_warnings(
        self,
        district_name: Optional[str] = None,
        farmer_id: Optional[str] = None,
        language: Optional[str] = None,
    ) -> List[IMDDistrictWarning]:
        """
        Retrieve official IMD 5-day district warnings for a verified Telangana district or farmer profile.
        """
        target_dist, lang = self._resolve_context_and_consent(district_name, farmer_id, language)
        if isinstance(self.imd_provider, IMDWeatherProvider):
            return self.imd_provider.get_district_warnings(district_name=target_dist, language=lang)
        raise NotImplementedError("Current IMD provider does not support district warnings.")

    def get_imd_district_nowcast(
        self,
        district_name: Optional[str] = None,
        farmer_id: Optional[str] = None,
        language: Optional[str] = None,
    ) -> List[IMDDistrictNowcast]:
        """
        Retrieve official short-lived IMD district nowcasts.
        """
        target_dist, lang = self._resolve_context_and_consent(district_name, farmer_id, language)
        if isinstance(self.imd_provider, IMDWeatherProvider):
            return self.imd_provider.get_district_nowcast(district_name=target_dist, language=lang)
        raise NotImplementedError("Current IMD provider does not support district nowcasts.")

    def get_imd_district_rainfall(
        self,
        district_name: Optional[str] = None,
        farmer_id: Optional[str] = None,
    ) -> List[IMDDistrictRainfallObservation]:
        """
        Retrieve official IMD district rainfall telemetry observations.
        """
        target_dist, _ = self._resolve_context_and_consent(district_name, farmer_id)
        if isinstance(self.imd_provider, IMDWeatherProvider):
            return self.imd_provider.get_district_rainfall(district_name=target_dist)
        raise NotImplementedError("Current IMD provider does not support district rainfall observations.")

    def get_imd_district_rainfall_forecast(
        self,
        district_name: Optional[str] = None,
        farmer_id: Optional[str] = None,
        language: Optional[str] = None,
    ) -> List[IMDDistrictRainfallForecast]:
        """
        Retrieve official IMD 5-day district rainfall distribution forecast.
        """
        target_dist, lang = self._resolve_context_and_consent(district_name, farmer_id, language)
        if isinstance(self.imd_provider, IMDWeatherProvider):
            return self.imd_provider.get_district_rainfall_forecast(district_name=target_dist, language=lang)
        raise NotImplementedError("Current IMD provider does not support district rainfall forecast.")

    def get_imd_station_weather(self, station_id: str) -> IMDStationObservation:
        """
        Retrieve ground observations from a verified named IMD station.
        """
        if isinstance(self.imd_provider, IMDWeatherProvider):
            return self.imd_provider.get_station_weather(station_id=station_id)
        raise NotImplementedError("Current IMD provider does not support station weather.")

    def get_imd_city_forecast(self, city_id: str, language: Optional[str] = None) -> IMDCityForecast:
        """
        Retrieve official 7-day city weather forecast for a verified Telangana city/station.
        """
        lang = language or "te-IN"
        if isinstance(self.imd_provider, IMDWeatherProvider):
            return self.imd_provider.get_city_forecast(city_id=city_id, language=lang)
        raise NotImplementedError("Current IMD provider does not support city forecast.")

    def get_imd_status(self) -> Dict[str, Any]:
        """
        Report IMD integration operational status and authentication evidence classification.
        """
        if isinstance(self.imd_provider, IMDWeatherProvider):
            return self.imd_provider.get_authentication_requirements()
        return {"status": "unsupported"}

    # -------------------------------------------------------------------------
    # Public IMD Telangana District Warnings (Phase 7.8)
    # -------------------------------------------------------------------------
    def get_imd_district_warning(
        self, district_name: str, day: str = "Day_1"
    ) -> IMDDistrictDayWarningRecord:
        """
        Retrieve official public IMD district-warning record for a Telangana district.
        Guarantees that missing data returns 'data_unavailable' and NEVER 'Green'.
        """
        return self.imd_warning_adapter.get_district_warning(district_name, day=day)

    def get_imd_district_5day_forecast(
        self, district_name: str
    ) -> IMDDistrict5DayWarningBulletin:
        """
        Retrieve consolidated 5-day public IMD warning bulletin for a Telangana district.
        """
        return self.imd_warning_adapter.get_district_5day_forecast(district_name)

    def format_imd_warning_for_farmer(
        self, district_name: str, day: str = "Day_1", language: str = "Telugu"
    ) -> str:
        """
        Format voice-ready farmer response for official IMD weather warnings.
        """
        return self.imd_warning_adapter.format_warning_for_farmer(
            district_name=district_name, day=day, language=language
        )

