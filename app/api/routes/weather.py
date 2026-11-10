"""
Weather API endpoints for KrishiVaani — Phase 6.1.
Exposes:
- GET /api/v1/weather/current
- GET /api/v1/weather/forecast
- GET /api/v1/weather/status

Security note:
During local development, farmer identity is resolved using internal farmer UUID.
Verified WhatsApp identity and authenticated backend context will be enforced before public deployment.
"""

from fastapi import APIRouter, Query, HTTPException, status
from typing import Optional, List, Dict, Any

from app.weather.schemas import (
    CurrentWeatherConditions,
    WeatherForecastResponse,
    WeatherServiceStatusResponse,
    WeatherErrorResponse,
    IMDDistrictWarning,
    IMDDistrictNowcast,
    IMDDistrictRainfallObservation,
    IMDDistrictRainfallForecast,
    IMDStationObservation,
    IMDCityForecast,
)
from app.weather.exceptions import (
    WeatherError,
    ProviderNotConfiguredError,
    ProviderAuthenticationError,
    ProviderRateLimitError,
    ProviderUnavailableError,
    LocationNotFoundError,
    LocationAmbiguityError,
    LocationCountryMismatchError,
    LocationDistrictMismatchError,
    ForecastDaysLimitExceededError,
    InvalidProviderResponseError,
    WeatherLocationSharingConsentRequiredError,
)
from app.weather.services.weather_service import WeatherService

router = APIRouter()
_weather_service: Optional[WeatherService] = None


def get_weather_service() -> WeatherService:
    """Dependency provider returning singleton weather service instance."""
    global _weather_service
    if _weather_service is None:
        _weather_service = WeatherService()
    return _weather_service


@router.get(
    "/status",
    response_model=WeatherServiceStatusResponse,
    summary="Weather Service Operational Status",
    description="Inspect operational health, configured meteorological providers, and planning horizons.",
)
async def get_weather_status():
    """Return status of all weather providers and integration pipelines."""
    service = get_weather_service()
    return service.get_service_status()


@router.get(
    "/current",
    response_model=CurrentWeatherConditions,
    responses={
        400: {"model": WeatherErrorResponse, "description": "Invalid query parameters"},
        404: {"model": WeatherErrorResponse, "description": "Farmer or location not found"},
        422: {"model": WeatherErrorResponse, "description": "Geographical ambiguity or mismatch"},
        429: {"model": WeatherErrorResponse, "description": "Provider rate limit exceeded"},
        502: {"model": WeatherErrorResponse, "description": "Provider authentication failure or invalid response"},
        503: {"model": WeatherErrorResponse, "description": "Provider unconfigured or service unavailable"},
    },
    summary="Get Current Weather for Farmer",
    description="Retrieve normalized real-time weather conditions using confirmed farmer profile location.",
)
async def get_current_weather(
    farmer_id: str = Query(..., description="Internal UUID of the confirmed farmer profile"),
):
    service = get_weather_service()
    try:
        return service.get_current_weather(farmer_id=farmer_id)
    except WeatherLocationSharingConsentRequiredError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error_code": "LOCATION_SHARING_CONSENT_REQUIRED", "message": exc.message, "details": exc.details},
        )
    except ProviderNotConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error_code": "PROVIDER_NOT_CONFIGURED", "message": exc.message, "provider": exc.provider},
        )
    except LocationNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_code": "LOCATION_NOT_FOUND", "message": exc.message, "provider": exc.provider},
        )
    except (LocationCountryMismatchError, LocationDistrictMismatchError, LocationAmbiguityError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error_code": "LOCATION_AMBIGUITY", "message": exc.message, "details": exc.details},
        )
    except ProviderRateLimitError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"error_code": "RATE_LIMIT_EXCEEDED", "message": exc.message, "provider": exc.provider},
        )
    except ProviderAuthenticationError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"error_code": "PROVIDER_AUTH_ERROR", "message": exc.message, "provider": exc.provider},
        )
    except ProviderUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error_code": "PROVIDER_UNAVAILABLE", "message": exc.message, "provider": exc.provider},
        )
    except InvalidProviderResponseError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"error_code": "INVALID_PROVIDER_RESPONSE", "message": exc.message, "provider": exc.provider},
        )
    except WeatherError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error_code": "WEATHER_ERROR", "message": exc.message, "provider": exc.provider},
        )


@router.get(
    "/forecast",
    response_model=WeatherForecastResponse,
    responses={
        400: {"model": WeatherErrorResponse, "description": "Invalid forecast days or parameter"},
        404: {"model": WeatherErrorResponse, "description": "Farmer or location not found"},
        422: {"model": WeatherErrorResponse, "description": "Geographical ambiguity or mismatch"},
        429: {"model": WeatherErrorResponse, "description": "Provider rate limit exceeded"},
        502: {"model": WeatherErrorResponse, "description": "Provider authentication failure or invalid response"},
        503: {"model": WeatherErrorResponse, "description": "Provider unconfigured or service unavailable"},
    },
    summary="Get Short-Range Weather Forecast for Farmer",
    description="Retrieve normalized multi-day weather forecast (up to 3 days on Free plan).",
)
async def get_weather_forecast(
    farmer_id: str = Query(..., description="Internal UUID of the confirmed farmer profile"),
    days: int = Query(3, ge=1, le=14, description="Forecast horizon in days (Free plan maximum: 3)"),
):
    service = get_weather_service()
    try:
        return service.get_forecast(farmer_id=farmer_id, days=days)
    except ForecastDaysLimitExceededError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error_code": "FORECAST_DAYS_LIMIT_EXCEEDED", "message": exc.message, "details": exc.details},
        )
    except WeatherLocationSharingConsentRequiredError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error_code": "LOCATION_SHARING_CONSENT_REQUIRED", "message": exc.message, "details": exc.details},
        )
    except ProviderNotConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error_code": "PROVIDER_NOT_CONFIGURED", "message": exc.message, "provider": exc.provider},
        )
    except LocationNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_code": "LOCATION_NOT_FOUND", "message": exc.message, "provider": exc.provider},
        )
    except (LocationCountryMismatchError, LocationDistrictMismatchError, LocationAmbiguityError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error_code": "LOCATION_AMBIGUITY", "message": exc.message, "details": exc.details},
        )
    except ProviderRateLimitError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"error_code": "RATE_LIMIT_EXCEEDED", "message": exc.message, "provider": exc.provider},
        )
    except ProviderAuthenticationError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"error_code": "PROVIDER_AUTH_ERROR", "message": exc.message, "provider": exc.provider},
        )
    except ProviderUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error_code": "PROVIDER_UNAVAILABLE", "message": exc.message, "provider": exc.provider},
        )
    except InvalidProviderResponseError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"error_code": "INVALID_PROVIDER_RESPONSE", "message": exc.message, "provider": exc.provider},
        )
    except WeatherError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error_code": "WEATHER_ERROR", "message": exc.message, "provider": exc.provider},
        )


# =============================================================================
# Phase 6.2: Official IMD Weather Intelligence Endpoints
# =============================================================================

@router.get(
    "/imd/status",
    summary="IMD Integration Status",
    description="Inspect official India Meteorological Department API integration readiness and authentication evidence.",
)
async def get_imd_status():
    """Return operational status and classified authentication requirements for IMD API."""
    service = get_weather_service()
    return service.get_imd_status()


@router.get(
    "/imd/district-warnings",
    response_model=List[IMDDistrictWarning],
    summary="Official IMD 5-Day District Weather Warnings",
    description="Retrieve official IMD 5-day weather warnings (heavy rain, thunderstorm, lightning, etc.) for a Telangana district.",
)
async def get_imd_district_warnings(
    district: Optional[str] = Query(None, description="Telangana district name (e.g. Jagtial, Hanamkonda)"),
    farmer_id: Optional[str] = Query(None, description="Optional confirmed farmer profile UUID"),
    language: Optional[str] = Query("te-IN", description="Preferred language for disclaimer (te-IN, hi-IN, en-IN)"),
):
    service = get_weather_service()
    try:
        return service.get_imd_district_warnings(district_name=district, farmer_id=farmer_id, language=language)
    except WeatherLocationSharingConsentRequiredError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error_code": "LOCATION_SHARING_CONSENT_REQUIRED", "message": exc.message, "details": exc.details},
        )
    except LocationDistrictMismatchError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error_code": "DISTRICT_MISMATCH", "message": exc.message, "details": exc.details},
        )
    except LocationNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_code": "LOCATION_NOT_FOUND", "message": exc.message},
        )
    except ProviderNotConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error_code": "PROVIDER_NOT_CONFIGURED", "message": exc.message, "provider": exc.provider, "details": exc.details},
        )
    except ProviderAuthenticationError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"error_code": "PROVIDER_AUTH_ERROR", "message": exc.message, "provider": exc.provider},
        )
    except ProviderRateLimitError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"error_code": "RATE_LIMIT_EXCEEDED", "message": exc.message, "provider": exc.provider},
        )
    except ProviderUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error_code": "PROVIDER_UNAVAILABLE", "message": exc.message, "provider": exc.provider},
        )
    except InvalidProviderResponseError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"error_code": "INVALID_PROVIDER_RESPONSE", "message": exc.message, "provider": exc.provider},
        )


@router.get(
    "/imd/district-nowcast",
    response_model=List[IMDDistrictNowcast],
    summary="Official IMD District Nowcast",
    description="Retrieve short-lived official nowcast bulletins from IMD (valid for 3 hours).",
)
async def get_imd_district_nowcast(
    district: Optional[str] = Query(None, description="Telangana district name (e.g. Jagtial, Hanamkonda)"),
    farmer_id: Optional[str] = Query(None, description="Optional confirmed farmer profile UUID"),
    language: Optional[str] = Query("te-IN", description="Preferred language for disclaimer"),
):
    service = get_weather_service()
    try:
        return service.get_imd_district_nowcast(district_name=district, farmer_id=farmer_id, language=language)
    except WeatherLocationSharingConsentRequiredError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error_code": "LOCATION_SHARING_CONSENT_REQUIRED", "message": exc.message, "details": exc.details},
        )
    except LocationDistrictMismatchError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error_code": "DISTRICT_MISMATCH", "message": exc.message, "details": exc.details},
        )
    except LocationNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_code": "LOCATION_NOT_FOUND", "message": exc.message},
        )
    except ProviderNotConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error_code": "PROVIDER_NOT_CONFIGURED", "message": exc.message, "provider": exc.provider, "details": exc.details},
        )
    except ProviderAuthenticationError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"error_code": "PROVIDER_AUTH_ERROR", "message": exc.message, "provider": exc.provider},
        )
    except ProviderRateLimitError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"error_code": "RATE_LIMIT_EXCEEDED", "message": exc.message, "provider": exc.provider},
        )
    except ProviderUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error_code": "PROVIDER_UNAVAILABLE", "message": exc.message, "provider": exc.provider},
        )
    except InvalidProviderResponseError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"error_code": "INVALID_PROVIDER_RESPONSE", "message": exc.message, "provider": exc.provider},
        )


@router.get(
    "/imd/district-rainfall",
    response_model=List[IMDDistrictRainfallObservation],
    summary="Official IMD District Rainfall Observations",
    description="Retrieve district-level rainfall actuals, departures, and normal statistics (daily, weekly, cumulative).",
)
async def get_imd_district_rainfall(
    district: Optional[str] = Query(None, description="Telangana district name (e.g. Jagtial, Hanamkonda)"),
    farmer_id: Optional[str] = Query(None, description="Optional confirmed farmer profile UUID"),
):
    service = get_weather_service()
    try:
        return service.get_imd_district_rainfall(district_name=district, farmer_id=farmer_id)
    except WeatherLocationSharingConsentRequiredError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error_code": "LOCATION_SHARING_CONSENT_REQUIRED", "message": exc.message, "details": exc.details},
        )
    except LocationDistrictMismatchError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error_code": "DISTRICT_MISMATCH", "message": exc.message, "details": exc.details},
        )
    except LocationNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_code": "LOCATION_NOT_FOUND", "message": exc.message},
        )
    except ProviderNotConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error_code": "PROVIDER_NOT_CONFIGURED", "message": exc.message, "provider": exc.provider, "details": exc.details},
        )
    except ProviderAuthenticationError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"error_code": "PROVIDER_AUTH_ERROR", "message": exc.message, "provider": exc.provider},
        )
    except ProviderRateLimitError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"error_code": "RATE_LIMIT_EXCEEDED", "message": exc.message, "provider": exc.provider},
        )
    except ProviderUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error_code": "PROVIDER_UNAVAILABLE", "message": exc.message, "provider": exc.provider},
        )
    except InvalidProviderResponseError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"error_code": "INVALID_PROVIDER_RESPONSE", "message": exc.message, "provider": exc.provider},
        )


@router.get(
    "/imd/district-rainfall-forecast",
    response_model=List[IMDDistrictRainfallForecast],
    summary="Official IMD 5-Day District Rainfall Distribution Forecast",
    description="Retrieve 5-day spatial rainfall distribution categories (WS, FWS, SCT, ISOL, DRY) and station percentage.",
)
async def get_imd_district_rainfall_forecast(
    district: Optional[str] = Query(None, description="Telangana district name (e.g. Jagtial, Hanamkonda)"),
    farmer_id: Optional[str] = Query(None, description="Optional confirmed farmer profile UUID"),
    language: Optional[str] = Query("te-IN", description="Preferred language for disclaimer"),
):
    service = get_weather_service()
    try:
        return service.get_imd_district_rainfall_forecast(district_name=district, farmer_id=farmer_id, language=language)
    except WeatherLocationSharingConsentRequiredError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error_code": "LOCATION_SHARING_CONSENT_REQUIRED", "message": exc.message, "details": exc.details},
        )
    except LocationDistrictMismatchError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error_code": "DISTRICT_MISMATCH", "message": exc.message, "details": exc.details},
        )
    except LocationNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_code": "LOCATION_NOT_FOUND", "message": exc.message},
        )
    except ProviderNotConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error_code": "PROVIDER_NOT_CONFIGURED", "message": exc.message, "provider": exc.provider, "details": exc.details},
        )
    except ProviderAuthenticationError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"error_code": "PROVIDER_AUTH_ERROR", "message": exc.message, "provider": exc.provider},
        )
    except ProviderRateLimitError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"error_code": "RATE_LIMIT_EXCEEDED", "message": exc.message, "provider": exc.provider},
        )
    except ProviderUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error_code": "PROVIDER_UNAVAILABLE", "message": exc.message, "provider": exc.provider},
        )
    except InvalidProviderResponseError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"error_code": "INVALID_PROVIDER_RESPONSE", "message": exc.message, "provider": exc.provider},
        )


@router.get(
    "/imd/station-weather",
    response_model=IMDStationObservation,
    summary="Official IMD Ground Station Surface Observations",
    description="Retrieve surface meteorological observations for a verified physical IMD station.",
)
async def get_imd_station_weather(
    station_id: str = Query(..., description="Official IMD station identifier (e.g. 43093 for Begumpet)"),
):
    service = get_weather_service()
    try:
        return service.get_imd_station_weather(station_id=station_id)
    except ProviderNotConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error_code": "PROVIDER_NOT_CONFIGURED", "message": exc.message, "provider": exc.provider, "details": exc.details},
        )
    except LocationNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_code": "LOCATION_NOT_FOUND", "message": exc.message},
        )
    except ProviderUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error_code": "PROVIDER_UNAVAILABLE", "message": exc.message, "provider": exc.provider},
        )
    except InvalidProviderResponseError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"error_code": "INVALID_PROVIDER_RESPONSE", "message": exc.message, "provider": exc.provider},
        )


@router.get(
    "/imd/city-forecast",
    response_model=IMDCityForecast,
    summary="Official IMD 7-Day City Forecast",
    description="Retrieve 7-day city weather forecast for a verified Telangana city/station.",
)
async def get_imd_city_forecast(
    city_id: str = Query(..., description="Verified Telangana city code (e.g. HYD, HNK, NZB, KMM)"),
    language: Optional[str] = Query("te-IN", description="Preferred language for disclaimer"),
):
    service = get_weather_service()
    try:
        return service.get_imd_city_forecast(city_id=city_id, language=language)
    except ProviderNotConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error_code": "PROVIDER_NOT_CONFIGURED", "message": exc.message, "provider": exc.provider, "details": exc.details},
        )
    except LocationNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_code": "LOCATION_NOT_FOUND", "message": exc.message, "details": exc.details},
        )
    except ProviderUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error_code": "PROVIDER_UNAVAILABLE", "message": exc.message, "provider": exc.provider},
        )
    except InvalidProviderResponseError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"error_code": "INVALID_PROVIDER_RESPONSE", "message": exc.message, "provider": exc.provider},
        )

