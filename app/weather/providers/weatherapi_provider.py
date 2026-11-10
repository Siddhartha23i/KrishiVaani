"""
WeatherAPI.com Free plan provider integration for KrishiVaani — Phase 6.1.
Adheres strictly to WeatherAPI.com terms:
- 100,000 API calls/month Free plan.
- Maximum 3 days forecast on Free plan.
- Caching: current conditions max 60 minutes, forecast max 24 hours.
- Required attribution: 'Powered by WeatherAPI.com'.
- Never exposes the API key in exception messages, URLs, or logs.
"""

from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
from zoneinfo import ZoneInfo
import httpx

from app.core.config import settings
from app.weather.enums import (
    ProviderStatus,
    WeatherInformationType,
    GeographicalResolution,
    FreshnessStatus,
    WeatherForecastHorizon,
)
from app.weather.schemas import (
    WeatherLocationInfo,
    CurrentWeatherConditions,
    HourlyWeatherForecast,
    DailyWeatherForecast,
    WeatherForecastResponse,
)
from app.weather.disclaimers import get_weather_disclaimer
from app.weather.exceptions import (
    ProviderNotConfiguredError,
    ProviderAuthenticationError,
    ProviderRateLimitError,
    ProviderUnavailableError,
    LocationNotFoundError,
    LocationCountryMismatchError,
    ForecastDaysLimitExceededError,
    InvalidProviderResponseError,
)
from app.weather.cache import weather_cache
from app.weather.providers.base import BaseWeatherProvider

KOLKATA_TZ = ZoneInfo("Asia/Kolkata")


class WeatherAPIProvider(BaseWeatherProvider):
    """
    Supplementary short-range weather provider utilizing WeatherAPI.com Free tier.
    Provides current conditions and up to 3 days of short-range forecasts.
    """

    PROVIDER_ID = "weatherapi_free"
    PROVIDER_NAME = "WeatherAPI.com Free"
    PROVIDER_URL = "https://www.weatherapi.com/"
    ATTRIBUTION = "Powered by WeatherAPI.com (https://www.weatherapi.com/)"
    MAX_FREE_FORECAST_DAYS = 3

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout_seconds: Optional[float] = None,
        http_client: Optional[httpx.Client] = None,
    ):
        self._api_key = api_key or settings.WEATHERAPI_API_KEY
        self._base_url = (base_url or settings.WEATHERAPI_BASE_URL).rstrip("/")
        self._timeout = timeout_seconds or settings.WEATHER_REQUEST_TIMEOUT_SECONDS
        self._client = http_client

    @property
    def provider_id(self) -> str:
        return self.PROVIDER_ID

    @property
    def provider_name(self) -> str:
        return self.PROVIDER_NAME

    @property
    def provider_url(self) -> str:
        return self.PROVIDER_URL

    @property
    def attribution(self) -> str:
        return self.ATTRIBUTION

    def get_status(self) -> ProviderStatus:
        """Return configuration status without revealing secrets."""
        if not self._api_key or not self._api_key.strip():
            return ProviderStatus.NOT_CONFIGURED
        return ProviderStatus.CONFIGURED

    def _ensure_configured(self) -> None:
        """Validate that API credentials exist before making external requests."""
        if self.get_status() == ProviderStatus.NOT_CONFIGURED:
            raise ProviderNotConfiguredError(
                "WeatherAPI.com is not configured. Please set WEATHERAPI_API_KEY in the environment.",
                provider=self.PROVIDER_NAME,
            )

    def _get_http_client(self) -> httpx.Client:
        """Return reusable or transient HTTP client with configured timeout."""
        if self._client is not None:
            return self._client
        return httpx.Client(timeout=self._timeout)

    def _parse_epoch_to_kolkata_iso(self, epoch_seconds: int) -> str:
        """Convert a Unix epoch timestamp to an ISO-8601 string in Asia/Kolkata timezone."""
        dt = datetime.fromtimestamp(epoch_seconds, tz=timezone.utc).astimezone(KOLKATA_TZ)
        return dt.isoformat()

    def _extract_location_info(
        self,
        loc_data: Dict[str, Any],
        requested_lat: Optional[float] = None,
        requested_lon: Optional[float] = None,
    ) -> WeatherLocationInfo:
        """
        Extract and validate location metadata from provider payload.
        Enforces India country check, spatial resolution clarity (~1-11 km),
        and distinguishes between requested coordinates and provider grid center.
        """
        country = loc_data.get("country", "").strip()
        if country.lower() != "india":
            raise LocationCountryMismatchError(
                f"Resolved location country '{country}' does not match expected country 'India'.",
                provider=self.PROVIDER_NAME,
                details={"country": country, "location_name": loc_data.get("name")},
            )

        match_status = "coordinates_matched" if (requested_lat is not None and requested_lon is not None) else "not_independently_verified"

        return WeatherLocationInfo(
            location_name=loc_data.get("name", "Unknown"),
            region=loc_data.get("region"),
            country=country,
            requested_latitude=requested_lat,
            requested_longitude=requested_lon,
            provider_location_latitude=loc_data.get("lat"),
            provider_location_longitude=loc_data.get("lon"),
            provider_grid_resolution_km="1-11 km",
            location_match_status=match_status,
            geographical_resolution=GeographicalResolution.POINT_GRID,
            resolution=GeographicalResolution.POINT_GRID,
            station_identifier=None,
            station_observation_confirmed=False,
            is_nearby_grid_estimate=True,
            timezone=loc_data.get("tz_id", "Asia/Kolkata"),
        )

    def _handle_http_error_response(self, response: httpx.Response) -> None:
        """
        Inspect error status codes and provider error payloads.
        Guarantees that the secret API key is never included in the exception message.
        """
        status_code = response.status_code
        error_code = None
        error_msg = None

        try:
            body = response.json()
            if isinstance(body, dict) and "error" in body:
                err_dict = body["error"]
                error_code = err_dict.get("code")
                error_msg = err_dict.get("message")
        except Exception:
            body = None

        # Sanitize error message to prevent key leak if provider includes it
        safe_msg = f"Provider error (HTTP {status_code})"
        if error_msg:
            safe_msg += f": {error_msg}"

        if status_code in (401, 403) or error_code in (1002, 2006, 2008):
            raise ProviderAuthenticationError(
                f"WeatherAPI authentication failed: {error_msg or 'Invalid or unauthorized API key.'}",
                provider=self.PROVIDER_NAME,
                details={"http_status": status_code, "provider_error_code": error_code},
            )
        elif status_code == 429 or error_code == 2007:
            raise ProviderRateLimitError(
                f"WeatherAPI rate limit or monthly call quota exceeded: {error_msg or 'Quota exceeded.'}",
                provider=self.PROVIDER_NAME,
                details={"http_status": status_code, "provider_error_code": error_code},
            )
        elif status_code == 400 and error_code == 1006:
            raise LocationNotFoundError(
                f"No matching location found by WeatherAPI: {error_msg or 'Location not found.'}",
                provider=self.PROVIDER_NAME,
                details={"http_status": status_code, "provider_error_code": error_code},
            )
        elif status_code >= 500:
            raise ProviderUnavailableError(
                f"WeatherAPI server is currently unavailable (HTTP {status_code}).",
                provider=self.PROVIDER_NAME,
                details={"http_status": status_code},
            )
        else:
            raise InvalidProviderResponseError(
                f"WeatherAPI request failed with HTTP {status_code}: {safe_msg}",
                provider=self.PROVIDER_NAME,
                details={"http_status": status_code, "provider_error_code": error_code},
            )

    def get_current_weather(
        self,
        query: str,
        lat: Optional[float] = None,
        lon: Optional[float] = None,
        language: str = "te-IN",
    ) -> CurrentWeatherConditions:
        """
        Retrieve and normalize current weather conditions.
        Results are cached for up to 30 minutes (well within the 60-minute limit).
        Includes localized intelligible end-user legal disclaimer and explicit data source nature.
        """
        self._ensure_configured()

        # Build clean query parameter (coordinates preferred if supplied)
        q = f"{lat},{lon}" if (lat is not None and lon is not None) else query
        if not q or not q.strip():
            raise LocationNotFoundError("Location query parameter is empty.", provider=self.PROVIDER_NAME)

        cache_key = f"weatherapi:current:{q.strip().lower()}:{language}"
        cached = weather_cache.get(cache_key)
        if cached is not None and isinstance(cached, CurrentWeatherConditions):
            return cached

        url = f"{self._base_url}/current.json"
        params = {"key": self._api_key, "q": q.strip(), "aqi": "no"}

        client = self._get_http_client()
        should_close = (self._client is None)

        try:
            resp = client.get(url, params=params)
        except httpx.TimeoutException as exc:
            raise ProviderUnavailableError(
                f"WeatherAPI connection timed out after {self._timeout}s.",
                provider=self.PROVIDER_NAME,
            ) from exc
        except httpx.RequestError as exc:
            # Note: Do not include exc representation directly in case URL contains key
            raise ProviderUnavailableError(
                "Failed to connect to WeatherAPI service. Network connection error.",
                provider=self.PROVIDER_NAME,
            ) from exc
        finally:
            if should_close:
                client.close()

        if resp.status_code != 200:
            self._handle_http_error_response(resp)

        try:
            data = resp.json()
        except Exception as exc:
            raise InvalidProviderResponseError(
                "WeatherAPI returned invalid JSON response.",
                provider=self.PROVIDER_NAME,
            ) from exc

        loc_data = data.get("location", {})
        curr_data = data.get("current", {})

        location_info = self._extract_location_info(loc_data, requested_lat=lat, requested_lon=lon)

        # Timestamps
        retrieved_at = datetime.now(timezone.utc).astimezone(KOLKATA_TZ).isoformat()
        last_updated_epoch = curr_data.get("last_updated_epoch")
        if last_updated_epoch:
            issued_at = self._parse_epoch_to_kolkata_iso(last_updated_epoch)
        else:
            issued_at = retrieved_at

        valid_from = issued_at
        # Current conditions valid for 60 minutes from issue
        try:
            valid_until_dt = datetime.fromisoformat(valid_from)
            valid_until = valid_until_dt.replace(
                minute=(valid_until_dt.minute + 60) % 60,
                hour=(valid_until_dt.hour + (valid_until_dt.minute + 60) // 60) % 24
            ).isoformat()
        except Exception:
            valid_until = retrieved_at

        condition = curr_data.get("condition", {})
        precip_mm = curr_data.get("precip_mm", 0.0)

        result = CurrentWeatherConditions(
            source_name=self.PROVIDER_NAME,
            source_url=self.PROVIDER_URL,
            retrieved_at=retrieved_at,
            issued_at=issued_at,
            valid_from=valid_from,
            valid_until=valid_until,
            information_type=WeatherInformationType.CURRENT_CONDITIONS,
            geographical_resolution=GeographicalResolution.POINT_GRID,
            location=location_info,
            timezone=location_info.timezone,
            attribution=self.ATTRIBUTION,
            freshness_status=FreshnessStatus.CURRENT,
            disclaimer=get_weather_disclaimer(language),
            disclaimer_language=language,
            temperature_c=float(curr_data.get("temp_c", 0.0)),
            feels_like_c=float(curr_data.get("feelslike_c", curr_data.get("temp_c", 0.0))),
            humidity_percent=float(curr_data.get("humidity", 0)),
            wind_kph=float(curr_data.get("wind_kph", 0.0)),
            wind_dir=curr_data.get("wind_dir"),
            condition_text=condition.get("text"),
            condition_code=condition.get("code"),
            uv_index=float(curr_data.get("uv", 0.0)),
            precipitation_mm=float(precip_mm),
            is_day=bool(curr_data.get("is_day", 1)),
            is_station_observation=False,  # WeatherAPI is numerical grid estimate
            station_observation_confirmed=False,
            data_source_nature="provider_reported_current_conditions",
            observed_rainfall_mm=None,     # Ground observations must never be fabricated
            forecast_rainfall_mm=float(precip_mm),
        )

        # Cache valid for 30 minutes (within 60 min terms)
        weather_cache.set(cache_key, result, ttl_seconds=weather_cache.DEFAULT_CURRENT_TTL_SECONDS)
        return result

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
        Rejects requests above Free plan limit (max 3 days).
        Results are cached for up to 6 hours (within the 24-hour limit).
        Includes localized intelligible end-user legal disclaimer.
        """
        self._ensure_configured()

        if days < 1:
            days = 1
        if days > self.MAX_FREE_FORECAST_DAYS:
            raise ForecastDaysLimitExceededError(
                f"WeatherAPI.com Free plan supports a maximum of {self.MAX_FREE_FORECAST_DAYS} forecast days. "
                f"Requested {days} days exceeds authorized tier.",
                provider=self.PROVIDER_NAME,
                details={"requested_days": days, "max_allowed_days": self.MAX_FREE_FORECAST_DAYS},
            )

        q = f"{lat},{lon}" if (lat is not None and lon is not None) else query
        if not q or not q.strip():
            raise LocationNotFoundError("Location query parameter is empty.", provider=self.PROVIDER_NAME)

        cache_key = f"weatherapi:forecast:{q.strip().lower()}:{days}:{language}"
        cached = weather_cache.get(cache_key)
        if cached is not None and isinstance(cached, WeatherForecastResponse):
            return cached

        url = f"{self._base_url}/forecast.json"
        params = {"key": self._api_key, "q": q.strip(), "days": days, "aqi": "no", "alerts": "no"}

        client = self._get_http_client()
        should_close = (self._client is None)

        try:
            resp = client.get(url, params=params)
        except httpx.TimeoutException as exc:
            raise ProviderUnavailableError(
                f"WeatherAPI connection timed out after {self._timeout}s.",
                provider=self.PROVIDER_NAME,
            ) from exc
        except httpx.RequestError as exc:
            raise ProviderUnavailableError(
                "Failed to connect to WeatherAPI service. Network connection error.",
                provider=self.PROVIDER_NAME,
            ) from exc
        finally:
            if should_close:
                client.close()

        if resp.status_code != 200:
            self._handle_http_error_response(resp)

        try:
            data = resp.json()
        except Exception as exc:
            raise InvalidProviderResponseError(
                "WeatherAPI returned invalid JSON response.",
                provider=self.PROVIDER_NAME,
            ) from exc

        loc_data = data.get("location", {})
        forecast_obj = data.get("forecast", {})
        forecast_days_raw = forecast_obj.get("forecastday", [])

        location_info = self._extract_location_info(loc_data, requested_lat=lat, requested_lon=lon)
        retrieved_at = datetime.now(timezone.utc).astimezone(KOLKATA_TZ).isoformat()

        daily_forecasts: List[DailyWeatherForecast] = []
        for day_entry in forecast_days_raw:
            date_str = day_entry.get("date", "")
            day_metrics = day_entry.get("day", {})
            condition = day_metrics.get("condition", {})
            total_precip = float(day_metrics.get("totalprecip_mm", 0.0))

            hourly_list: List[HourlyWeatherForecast] = []
            for h in day_entry.get("hour", []):
                h_cond = h.get("condition", {})
                hourly_list.append(
                    HourlyWeatherForecast(
                        time=h.get("time", ""),
                        temp_c=float(h.get("temp_c", 0.0)),
                        condition_text=h_cond.get("text"),
                        condition_code=h_cond.get("code"),
                        precip_mm=float(h.get("precip_mm", 0.0)),
                        humidity_percent=float(h.get("humidity", 0)),
                        wind_kph=float(h.get("wind_kph", 0.0)),
                        chance_of_rain_percent=int(h.get("chance_of_rain", 0)),
                    )
                )

            daily_forecasts.append(
                DailyWeatherForecast(
                    date=date_str,
                    max_temp_c=float(day_metrics.get("maxtemp_c", 0.0)),
                    min_temp_c=float(day_metrics.get("mintemp_c", 0.0)),
                    avg_temp_c=float(day_metrics.get("avgtemp_c", 0.0)),
                    max_wind_kph=float(day_metrics.get("maxwind_kph", 0.0)),
                    total_precipitation_mm=total_precip,
                    avg_humidity_percent=float(day_metrics.get("avghumidity", 0.0)),
                    condition_text=condition.get("text"),
                    condition_code=condition.get("code"),
                    uv_index=float(day_metrics.get("uv", 0.0)),
                    chance_of_rain_percent=int(day_metrics.get("daily_chance_of_rain", 0)),
                    is_model_estimate=True,
                    forecast_rainfall_mm=total_precip,
                    observed_rainfall_mm=None,  # Forecast never generates observed rainfall
                    hourly=hourly_list if hourly_list else None,
                )
            )

        valid_from = daily_forecasts[0].date if daily_forecasts else retrieved_at
        valid_until = daily_forecasts[-1].date if daily_forecasts else retrieved_at

        result = WeatherForecastResponse(
            source_name=self.PROVIDER_NAME,
            source_url=self.PROVIDER_URL,
            retrieved_at=retrieved_at,
            issued_at=retrieved_at,
            valid_from=valid_from,
            valid_until=valid_until,
            information_type=WeatherInformationType.WEATHER_FORECAST,
            geographical_resolution=GeographicalResolution.POINT_GRID,
            forecast_horizon=WeatherForecastHorizon.SHORT_RANGE_1_3D,
            days_count=len(daily_forecasts),
            location=location_info,
            timezone=location_info.timezone,
            attribution=self.ATTRIBUTION,
            freshness_status=FreshnessStatus.CURRENT,
            disclaimer=get_weather_disclaimer(language),
            disclaimer_language=language,
            forecast_days=daily_forecasts,
        )

        # Cache forecast for 6 hours (within 24 hours terms)
        weather_cache.set(cache_key, result, ttl_seconds=weather_cache.DEFAULT_FORECAST_TTL_SECONDS)
        return result

