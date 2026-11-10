"""
Weather Source Registry for KrishiVaani — Phase 6.1.
Maintains institutional catalog, access status, and planning horizon capabilities
for all official and supplementary meteorological data sources.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Any

from app.weather.enums import (
    ProviderStatus,
    WeatherInformationType,
    GeographicalResolution,
    WeatherForecastHorizon,
)


@dataclass(frozen=True)
class WeatherSourceDescriptor:
    """Institutional metadata descriptor for a weather data provider."""
    source_id: str
    source_name: str
    organization: str
    portal_url: str
    status: ProviderStatus
    supported_information_types: List[WeatherInformationType]
    spatial_resolution: GeographicalResolution
    supported_horizons: List[WeatherForecastHorizon]
    attribution_text: str
    access_requirements: str
    status_notes: str


WEATHER_SOURCES: Dict[str, WeatherSourceDescriptor] = {
    "weatherapi_free": WeatherSourceDescriptor(
        source_id="weatherapi_free",
        source_name="WeatherAPI.com Free",
        organization="WeatherAPI.com",
        portal_url="https://www.weatherapi.com/",
        status=ProviderStatus.CONFIGURED,  # Evaluated dynamically based on key
        supported_information_types=[
            WeatherInformationType.CURRENT_CONDITIONS,
            WeatherInformationType.WEATHER_FORECAST,
        ],
        spatial_resolution=GeographicalResolution.POINT_GRID,
        supported_horizons=[
            WeatherForecastHorizon.HOURLY_24H,
            WeatherForecastHorizon.SHORT_RANGE_1_3D,
        ],
        attribution_text="Powered by WeatherAPI.com (https://www.weatherapi.com/)",
        access_requirements="Free tier API key via WEATHERAPI_API_KEY environment variable.",
        status_notes="Provides current conditions and up to 3 days of short-range forecast. 100k calls/month limit.",
    ),
    "imd_official": WeatherSourceDescriptor(
        source_id="imd_official",
        source_name="India Meteorological Department (IMD)",
        organization="Ministry of Earth Sciences, Government of India",
        portal_url="https://api.imd.gov.in/public/",
        status=ProviderStatus.PENDING_CREDENTIALS,
        supported_information_types=[
            WeatherInformationType.CURRENT_CONDITIONS,
            WeatherInformationType.WEATHER_FORECAST,
            WeatherInformationType.WEATHER_WARNING,
            WeatherInformationType.RAINFALL_OBSERVATION,
            WeatherInformationType.AGROMET_ADVISORY,
            WeatherInformationType.EXTENDED_RANGE_OUTLOOK,
            WeatherInformationType.MONTHLY_OUTLOOK,
            WeatherInformationType.SEASONAL_OUTLOOK,
        ],
        spatial_resolution=GeographicalResolution.DISTRICT,
        supported_horizons=[
            WeatherForecastHorizon.SHORT_RANGE_1_3D,
            WeatherForecastHorizon.MEDIUM_RANGE_4_7D,
            WeatherForecastHorizon.EXTENDED_RANGE_8_15D,
            WeatherForecastHorizon.MONTHLY_OUTLOOK_16_30D,
            WeatherForecastHorizon.SEASONAL_OUTLOOK_31_60D,
        ],
        attribution_text="Data provided by India Meteorological Department (IMD), Government of India",
        access_requirements="Dual-layer authentication: Registered API Key + JWT Bearer Token, static public IP binding.",
        status_notes="Official government API. Unauthenticated requests return HTTP 401. Integration pending approved credentials.",
    ),
    "tsdps_telemetry": WeatherSourceDescriptor(
        source_id="tsdps_telemetry",
        source_name="Telangana State Development Planning Society (TSDPS)",
        organization="Planning Department, Government of Telangana",
        portal_url="https://tsdps.telangana.gov.in/",
        status=ProviderStatus.PENDING_MACHINE_READABLE_FEED,
        supported_information_types=[
            WeatherInformationType.RAINFALL_OBSERVATION,
        ],
        spatial_resolution=GeographicalResolution.MANDAL,
        supported_horizons=[],  # Observations only, no forecast models
        attribution_text="Rainfall data from Telangana State Development Planning Society (TSDPS)",
        access_requirements="Public REST contract not currently published. Requires data-sharing agreement.",
        status_notes="Network of Automatic Weather Stations (AWS) at mandal level. Portal publishes HTML dashboards; public machine-readable REST API pending.",
    ),
    "des_telangana": WeatherSourceDescriptor(
        source_id="des_telangana",
        source_name="Directorate of Economics and Statistics (DES), Telangana",
        organization="Planning Department, Government of Telangana",
        portal_url="https://des.telangana.gov.in/",
        status=ProviderStatus.PENDING_MACHINE_READABLE_FEED,
        supported_information_types=[
            WeatherInformationType.RAINFALL_OBSERVATION,
        ],
        spatial_resolution=GeographicalResolution.DISTRICT,
        supported_horizons=[],
        attribution_text="Rainfall statistics from Directorate of Economics and Statistics (DES), Telangana",
        access_requirements="Statistical publications released periodically. Machine-readable API pending.",
        status_notes="Publishes seasonal and annual agricultural rainfall statistics.",
    ),
}


class WeatherSourceRegistry:
    """Registry providing access to cataloged weather sources and their integration status."""

    @classmethod
    def get_source(cls, source_id: str) -> Optional[WeatherSourceDescriptor]:
        return WEATHER_SOURCES.get(source_id)

    @classmethod
    def list_sources(cls) -> List[WeatherSourceDescriptor]:
        return list(WEATHER_SOURCES.values())

    @classmethod
    def get_active_providers_status(
        cls,
        weatherapi_status: ProviderStatus,
        imd_status: Optional[ProviderStatus] = None,
    ) -> Dict[str, str]:
        """Summarize current provider statuses for diagnostic reporting."""
        return {
            "weatherapi_free": weatherapi_status.value,
            "imd_official": (imd_status or ProviderStatus.PENDING_CREDENTIALS).value,
            "tsdps_telemetry": ProviderStatus.PENDING_MACHINE_READABLE_FEED.value,
            "des_telangana": ProviderStatus.PENDING_MACHINE_READABLE_FEED.value,
        }

