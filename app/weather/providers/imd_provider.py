"""
India Meteorological Department (IMD) API adapter foundation for KrishiVaani — Phase 6.1.
Implements the interface for official government meteorological data access.
Grounded in official IMD API management portal architecture (https://api.imd.gov.in/public/).

Research & Authentication Findings:
1. Dual-Layer Security: Requires an API key (DEV or PROD) from the IMD Developer Portal
   coupled with a JWT (JSON Web Token) Bearer Token generated via portal authentication.
2. Server Binding: IMD requires calling application servers to be bound to registered static public IP addresses.
3. Unauthenticated requests strictly return HTTP 401 Unauthorized.
4. Status: PENDING_CREDENTIALS until official organizational registration is completed.
   Credentials can be configured via environment variables: IMD_API_KEY, IMD_JWT_TOKEN.
"""

import re
from datetime import datetime, timezone, timedelta
from enum import Enum
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
    IMDDistrictWarningColor,
    IMDNowcastColor,
    IMDRainfallCategory,
    IMDRainfallDistribution,
    map_district_warning_color,
    map_district_nowcast_color,
)
from app.weather.schemas import (
    WeatherLocationInfo,
    CurrentWeatherConditions,
    WeatherForecastResponse,
    IMDDistrictDailyWarning,
    IMDDistrictWarning,
    IMDDistrictNowcast,
    IMDDistrictRainfallObservation,
    IMDDistrictRainfallForecastDay,
    IMDDistrictRainfallForecast,
    IMDStationObservation,
    IMDCityForecast,
)
from app.weather.exceptions import (
    ProviderNotConfiguredError,
    ProviderAuthenticationError,
    ProviderRateLimitError,
    ProviderUnavailableError,
    LocationNotFoundError,
    LocationDistrictMismatchError,
    InvalidProviderResponseError,
)
from app.weather.disclaimers import get_weather_disclaimer
from app.weather.providers.base import BaseWeatherProvider
from app.knowledge.season_calendar import resolve_telangana_district

KOLKATA_TZ = ZoneInfo("Asia/Kolkata")

# Verified IMD Surface Meteorological Stations and City Forecast Identifiers for Telangana
TELANGANA_VERIFIED_CITY_STATIONS: Dict[str, Dict[str, str]] = {
    "HYD": {"station_id": "43093", "city_name": "Hyderabad (Begumpet)", "district": "Hyderabad"},
    "HYD_HIAL": {"station_id": "43094", "city_name": "Hyderabad (Shamshabad)", "district": "Rangareddy"},
    "RGM": {"station_id": "43048", "city_name": "Ramagundam", "district": "Peddapalli"},
    "HNK": {"station_id": "43054", "city_name": "Hanamkonda", "district": "Hanamkonda"},
    "KMM": {"station_id": "43087", "city_name": "Khammam", "district": "Khammam"},
    "NZB": {"station_id": "43037", "city_name": "Nizamabad", "district": "Nizamabad"},
    "MBN": {"station_id": "43097", "city_name": "Mahabubnagar", "district": "Mahabubnagar"},
    "ADL": {"station_id": "43041", "city_name": "Adilabad", "district": "Adilabad"},
    "MDK": {"station_id": "43076", "city_name": "Medak", "district": "Medak"},
}


class IMDAuthenticationEvidence(str, Enum):
    """
    Evidence classification for IMD API authentication statements.
    Phase 6.1.1 policy: distinguish officially documented portal facts from
    unverified developer assumptions and unknown runtime behaviors.
    """
    OFFICIALLY_DOCUMENTED = "officially_documented"
    PORTAL_REPORTED_UNVERIFIED = "portal_reported_unverified"
    AUTHENTICATED_DOCS_CONFIRMED = "authenticated_docs_confirmed"
    UNKNOWN = "unknown"


class IMDWeatherProvider(BaseWeatherProvider):
    """
    Official primary meteorological provider interface for India Meteorological Department.
    Encapsulates the documented IMD API endpoints:
    - Seven-day city weather forecast (/api/v1/cityforecast)
    - Five-day district rainfall forecast
    - District-wise warnings and nowcasts
    - AWS/ARG station telemetry
    - Agromet advisories (GKMS)
    """

    PROVIDER_ID = "imd_official"
    PROVIDER_NAME = "India Meteorological Department (IMD)"
    PROVIDER_URL = "https://api.imd.gov.in/public/"
    ATTRIBUTION = "Data provided by India Meteorological Department (IMD), Ministry of Earth Sciences, Government of India"

    DOCUMENTED_ENDPOINTS = {
        "district_warnings": "/api/v1/districtwarning",
        "district_nowcast": "/api/v1/districtnowcast",
        "district_rainfall": "/api/v1/districtrainfall",
        "rainfall_forecast_district": "/api/v1/state_district_rainfall_forecast",
        "current_station_weather": "/api/v1/current_wx",
        "city_forecast": "/api/v1/cityforecast",
        "aws_telemetry": "/api/v1/station/aws",
        "agromet_advisory": "/api/v1/agromet/advisory",
    }

    def __init__(
        self,
        api_key: Optional[str] = None,
        jwt_token: Optional[str] = None,
        base_url: str = "https://api.imd.gov.in",
        timeout_seconds: Optional[float] = None,
        http_client: Optional[httpx.Client] = None,
    ):
        self._api_key = api_key or settings.IMD_API_KEY
        self._jwt_token = jwt_token or settings.IMD_JWT_TOKEN
        self._base_url = base_url.rstrip("/")
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
        """
        Check operational readiness.
        IMD requires both API Key and JWT Bearer token from the official portal.
        """
        if not self._api_key or not self._jwt_token:
            return ProviderStatus.PENDING_CREDENTIALS
        return ProviderStatus.CONFIGURED

    def _ensure_configured(self) -> None:
        """Validate that IMD credentials exist before attempting external requests."""
        if self.get_status() == ProviderStatus.PENDING_CREDENTIALS:
            reqs = self.get_authentication_requirements()
            raise ProviderNotConfiguredError(
                f"IMD API integration is pending official credentials. "
                f"Requires registered API Key and JWT Bearer Token from {reqs['portal_url']}.",
                provider=self.PROVIDER_NAME,
                details=reqs,
            )

    def _get_http_client(self) -> httpx.Client:
        """Return reusable or transient HTTP client with configured timeout."""
        if self._client is not None:
            return self._client
        return httpx.Client(timeout=self._timeout)

    def _build_auth_headers(self) -> Dict[str, str]:
        """Build HTTP headers using documented IMD credentials without secret leakage."""
        headers = {"Accept": "application/json"}
        if self._api_key:
            headers["X-Api-Key"] = self._api_key
        if self._jwt_token:
            headers["Authorization"] = f"Bearer {self._jwt_token}"
        return headers

    def _handle_http_error_response(self, response: httpx.Response, endpoint_name: str) -> None:
        """
        Inspect error status codes and provider error payloads.
        Guarantees that credentials are never leaked in error messages.
        """
        status_code = response.status_code
        safe_msg = f"IMD {endpoint_name} request failed (HTTP {status_code})"

        if status_code in (401, 403):
            raise ProviderAuthenticationError(
                f"IMD authentication failed for {endpoint_name}. Invalid or expired credentials.",
                provider=self.PROVIDER_NAME,
                details={"http_status": status_code, "endpoint": endpoint_name},
            )
        elif status_code == 429:
            raise ProviderRateLimitError(
                f"IMD rate limit exceeded for {endpoint_name}.",
                provider=self.PROVIDER_NAME,
                details={"http_status": status_code, "endpoint": endpoint_name},
            )
        elif status_code >= 500:
            raise ProviderUnavailableError(
                f"IMD server is currently unavailable (HTTP {status_code}).",
                provider=self.PROVIDER_NAME,
                details={"http_status": status_code, "endpoint": endpoint_name},
            )
        else:
            raise InvalidProviderResponseError(
                f"{safe_msg}.",
                provider=self.PROVIDER_NAME,
                details={"http_status": status_code, "endpoint": endpoint_name},
            )

    def _utc_to_kolkata_iso(self, time_val: Optional[str], date_val: Optional[str] = None) -> Optional[str]:
        """Convert UTC timestamp string to Asia/Kolkata ISO-8601 string (+05:30)."""
        if not time_val or not str(time_val).strip():
            return None
        raw = str(time_val).strip()

        # Try full datetime formats
        for fmt in (
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M",
            "%d-%m-%Y %H:%M:%S",
            "%d-%m-%Y %H:%M",
        ):
            try:
                dt = datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc)
                return dt.astimezone(KOLKATA_TZ).isoformat()
            except ValueError:
                pass

        # Try time-only with supplied date
        if date_val and str(date_val).strip():
            combined = f"{str(date_val).strip()} {raw}"
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
                try:
                    dt = datetime.strptime(combined, fmt).replace(tzinfo=timezone.utc)
                    return dt.astimezone(KOLKATA_TZ).isoformat()
                except ValueError:
                    pass

        # If already contains timezone offset, parse with fromisoformat
        try:
            dt = datetime.fromisoformat(raw)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(KOLKATA_TZ).isoformat()
        except Exception:
            return raw

    def get_authentication_requirements(self) -> Dict[str, Any]:
        """
        Return documented technical requirements for activating live IMD data access,
        with each requirement explicitly classified by evidence status.
        """
        return {
            "portal_url": "https://api.imd.gov.in/public/index.php",
            "portal_reference": {
                "description": "Official public landing page of IMD API Management Portal",
                "evidence": IMDAuthenticationEvidence.OFFICIALLY_DOCUMENTED.value,
            },
            "registration_requirement": {
                "description": "Formal registration on IMD API portal required to generate client credentials",
                "evidence": IMDAuthenticationEvidence.OFFICIALLY_DOCUMENTED.value,
            },
            "security_architecture": {
                "description": "Dual-layer: API Key (DEV/PROD) + JWT Bearer Token generated on portal",
                "evidence": IMDAuthenticationEvidence.PORTAL_REPORTED_UNVERIFIED.value,
            },
            "server_binding": {
                "description": "Static public IP address mapping reported by community developers",
                "evidence": IMDAuthenticationEvidence.PORTAL_REPORTED_UNVERIFIED.value,
            },
            "government_domain_restriction": {
                "description": "Government email domain (@nic.in / @gov.in) reportedly required for PROD tier",
                "evidence": IMDAuthenticationEvidence.PORTAL_REPORTED_UNVERIFIED.value,
            },
            "token_refresh_lifecycle": {
                "description": "Exact JWT refresh header names and token expiry interval",
                "evidence": IMDAuthenticationEvidence.UNKNOWN.value,
            },
            "status": self.get_status().value,
            "configured_credentials": {
                "has_api_key": bool(self._api_key),
                "has_jwt_token": bool(self._jwt_token),
            },
            "documented_endpoints": list(self.DOCUMENTED_ENDPOINTS.keys()),
            "environment_variables": ["IMD_API_KEY", "IMD_JWT_TOKEN"],
        }

    def _execute_get_request(self, endpoint_key: str, params: Optional[Dict[str, Any]] = None) -> Any:
        """Execute validated HTTP GET request against documented IMD endpoint."""
        self._ensure_configured()
        path = self.DOCUMENTED_ENDPOINTS[endpoint_key]
        url = f"{self._base_url}{path}"
        headers = self._build_auth_headers()

        client = self._get_http_client()
        should_close = (self._client is None)

        try:
            resp = client.get(url, params=params, headers=headers)
        except httpx.TimeoutException as exc:
            raise ProviderUnavailableError(
                f"IMD connection timed out after {self._timeout}s.",
                provider=self.PROVIDER_NAME,
            ) from exc
        except httpx.RequestError as exc:
            raise ProviderUnavailableError(
                f"Failed to connect to IMD service at {path}. Network error.",
                provider=self.PROVIDER_NAME,
            ) from exc
        finally:
            if should_close:
                client.close()

        if resp.status_code != 200:
            self._handle_http_error_response(resp, endpoint_key)

        try:
            return resp.json()
        except Exception as exc:
            raise InvalidProviderResponseError(
                f"IMD {endpoint_key} returned invalid JSON payload.",
                provider=self.PROVIDER_NAME,
            ) from exc

    # -------------------------------------------------------------------------
    # A. District Warnings (/api/v1/districtwarning)
    # -------------------------------------------------------------------------
    def get_district_warnings(
        self,
        district_name: Optional[str] = None,
        language: str = "te-IN",
    ) -> List[IMDDistrictWarning]:
        """
        Retrieve official 5-day district weather warnings from IMD.
        Preserves multiple warning codes per day and enforces district warning color mapping
        (1=Red, 2=Orange, 3=Yellow, 4=Green).
        Validates against Telangana 33 districts registry.
        """
        target_mapping = None
        if district_name and district_name.strip():
            target_mapping = resolve_telangana_district(district_name)
            if not target_mapping:
                raise LocationDistrictMismatchError(
                    f"District '{district_name}' is not a recognized Telangana revenue district.",
                    details={"requested_district": district_name},
                )

        raw_payload = self._execute_get_request("district_warnings")
        retrieved_at = datetime.now(timezone.utc).astimezone(KOLKATA_TZ).isoformat()

        # Handle list or wrapped dict
        entries: List[Dict[str, Any]] = []
        if isinstance(raw_payload, list):
            entries = raw_payload
        elif isinstance(raw_payload, dict):
            for k in ("data", "district_warnings", "warnings", "records"):
                if isinstance(raw_payload.get(k), list):
                    entries = raw_payload[k]
                    break
            if not entries and "District" in raw_payload:
                entries = [raw_payload]

        results: List[IMDDistrictWarning] = []
        for entry in entries:
            d_name = entry.get("District") or entry.get("district") or "Unknown"
            matched_reg = resolve_telangana_district(str(d_name))

            # Filter if district_name requested
            if target_mapping:
                if not matched_reg or matched_reg.normalized_name != target_mapping.normalized_name:
                    continue
            elif not matched_reg:
                # If no specific district requested, only keep Telangana districts
                continue

            issue_date = str(entry.get("Date") or entry.get("date") or datetime.now(KOLKATA_TZ).strftime("%Y-%m-%d"))
            raw_time = entry.get("time") or entry.get("issue_time") or entry.get("Time")
            issue_kolkata = self._utc_to_kolkata_iso(raw_time, issue_date) if raw_time else None

            # Parse 5 daily warnings
            daily_list: List[IMDDistrictDailyWarning] = []
            for day_idx in range(1, 6):
                day_key = f"Day_{day_idx}"
                alt_day_key = f"Day{day_idx}"
                color_key = f"Day{day_idx}_Color"
                alt_color_key = f"Day_{day_idx}_Color"

                warn_text = entry.get(day_key) or entry.get(alt_day_key) or "No Warning"
                raw_color = entry.get(color_key) or entry.get(alt_color_key) or 4

                # Split multiple warning codes if comma-separated
                codes = [c.strip() for c in str(warn_text).split(",") if c.strip()]
                color_name = map_district_warning_color(raw_color)

                severity_map = {
                    "Red": ("take_action", "Take Action: Severe or extremely heavy weather conditions expected."),
                    "Orange": ("be_prepared", "Be Prepared: Severe weather warning in force; stay alert."),
                    "Yellow": ("be_updated", "Be Updated: Moderate weather warning; monitor forecasts."),
                    "Green": ("no_warning", "No Warning: Normal conditions expected."),
                }
                sev_level, guidance = severity_map.get(color_name, ("no_warning", "No Warning"))

                # Estimate date for day index
                try:
                    base_d = datetime.strptime(issue_date, "%Y-%m-%d").date()
                    day_d = (base_d + timedelta(days=day_idx - 1)).isoformat()
                except Exception:
                    day_d = issue_date

                try:
                    raw_int_color = int(raw_color)
                except (TypeError, ValueError):
                    raw_int_color = None

                daily_list.append(
                    IMDDistrictDailyWarning(
                        day_number=day_idx,
                        date=day_d,
                        warning_codes=codes,
                        raw_color_code=raw_int_color,
                        color_name=color_name,
                        severity_level=sev_level,
                        action_guidance=guidance,
                    )
                )

            results.append(
                IMDDistrictWarning(
                    district_name=d_name,
                    matched_telangana_district=matched_reg.district_name if matched_reg else None,
                    retrieved_at=retrieved_at,
                    issue_date=issue_date,
                    issue_time_utc=str(raw_time) if raw_time else None,
                    issue_time_kolkata=issue_kolkata,
                    daily_warnings=daily_list,
                    freshness_status=FreshnessStatus.CURRENT,
                    disclaimer=get_weather_disclaimer(language),
                )
            )

        return results

    # -------------------------------------------------------------------------
    # B. District Nowcast (/api/v1/districtnowcast)
    # -------------------------------------------------------------------------
    def get_district_nowcast(
        self,
        district_name: Optional[str] = None,
        language: str = "te-IN",
    ) -> List[IMDDistrictNowcast]:
        """
        Retrieve official short-lived district nowcast from IMD.
        Enforces nowcast color mapping (1=Green, 2=Yellow, 3=Orange, 4=Red).
        Marks nowcasts as expired when valid_until (Vupto) has passed.
        """
        target_mapping = None
        if district_name and district_name.strip():
            target_mapping = resolve_telangana_district(district_name)
            if not target_mapping:
                raise LocationDistrictMismatchError(
                    f"District '{district_name}' is not a recognized Telangana revenue district.",
                    details={"requested_district": district_name},
                )

        raw_payload = self._execute_get_request("district_nowcast")
        now_dt = datetime.now(timezone.utc).astimezone(KOLKATA_TZ)
        retrieved_at = now_dt.isoformat()

        entries: List[Dict[str, Any]] = []
        if isinstance(raw_payload, list):
            entries = raw_payload
        elif isinstance(raw_payload, dict):
            for k in ("data", "nowcasts", "district_nowcast", "records"):
                if isinstance(raw_payload.get(k), list):
                    entries = raw_payload[k]
                    break
            if not entries and ("Station" in raw_payload or "msg" in raw_payload):
                entries = [raw_payload]

        results: List[IMDDistrictNowcast] = []
        for entry in entries:
            stn = entry.get("Station") or entry.get("station") or entry.get("District") or "Unknown"
            matched_reg = resolve_telangana_district(str(stn))

            if target_mapping:
                if not matched_reg or matched_reg.normalized_name != target_mapping.normalized_name:
                    continue
            elif not matched_reg:
                continue

            n_date = str(entry.get("Date") or entry.get("date") or now_dt.strftime("%Y-%m-%d"))
            raw_toi = entry.get("toi") or entry.get("TOI") or entry.get("time_of_issue")
            raw_vupto = entry.get("Vupto") or entry.get("vupto") or entry.get("valid_until")

            toi_kolkata = self._utc_to_kolkata_iso(raw_toi, n_date)
            vupto_kolkata = self._utc_to_kolkata_iso(raw_vupto, n_date)

            # Determine expiration against Asia/Kolkata current time
            is_expired = False
            if vupto_kolkata:
                try:
                    v_dt = datetime.fromisoformat(vupto_kolkata)
                    is_expired = (now_dt > v_dt)
                except Exception:
                    pass

            raw_color = entry.get("Color") or entry.get("color") or 1
            color_name = map_district_nowcast_color(raw_color)

            sev_map = {
                "Green": "no_warning",
                "Yellow": "be_updated",
                "Orange": "be_prepared",
                "Red": "take_action",
            }
            sev_level = sev_map.get(color_name, "no_warning")

            raw_warn = entry.get("Warning") or entry.get("warning") or entry.get("categories") or ""
            categories = [c.strip() for c in str(raw_warn).split(",") if c.strip()]
            msg = entry.get("msg") or entry.get("message") or f"Nowcast for {stn}: {raw_warn or color_name}"

            try:
                raw_int_color = int(raw_color)
            except (TypeError, ValueError):
                raw_int_color = None

            freshness = FreshnessStatus.EXPIRED if is_expired else FreshnessStatus.CURRENT

            results.append(
                IMDDistrictNowcast(
                    station_or_district=stn,
                    matched_telangana_district=matched_reg.district_name if matched_reg else None,
                    retrieved_at=retrieved_at,
                    nowcast_date=n_date,
                    time_of_issue_utc=str(raw_toi) if raw_toi else None,
                    time_of_issue_kolkata=toi_kolkata,
                    valid_until_utc=str(raw_vupto) if raw_vupto else None,
                    valid_until_kolkata=vupto_kolkata,
                    is_expired=is_expired,
                    raw_color_code=raw_int_color,
                    color_name=color_name,
                    severity_level=sev_level,
                    warning_categories=categories,
                    consolidated_message=msg,
                    freshness_status=freshness,
                    disclaimer=get_weather_disclaimer(language),
                )
            )

        return results

    # -------------------------------------------------------------------------
    # C. District Rainfall Observations (/api/v1/districtrainfall)
    # -------------------------------------------------------------------------
    def get_district_rainfall(
        self,
        district_name: Optional[str] = None,
    ) -> List[IMDDistrictRainfallObservation]:
        """
        Retrieve official district rainfall telemetry from IMD.
        Strictly distinguishes ND (No Data / missing observation) from NR (No Rain / 0.0 mm).
        ND values are never converted to 0.0 mm.
        """
        target_mapping = None
        if district_name and district_name.strip():
            target_mapping = resolve_telangana_district(district_name)
            if not target_mapping:
                raise LocationDistrictMismatchError(
                    f"District '{district_name}' is not a recognized Telangana revenue district.",
                    details={"requested_district": district_name},
                )

        raw_payload = self._execute_get_request("district_rainfall")
        retrieved_at = datetime.now(timezone.utc).astimezone(KOLKATA_TZ).isoformat()

        entries: List[Dict[str, Any]] = []
        if isinstance(raw_payload, list):
            entries = raw_payload
        elif isinstance(raw_payload, dict):
            for k in ("data", "rainfall", "district_rainfall", "records"):
                if isinstance(raw_payload.get(k), list):
                    entries = raw_payload[k]
                    break
            if not entries and "District" in raw_payload:
                entries = [raw_payload]

        category_desc_map = {
            "LE": "Large Excess (+60% or more)",
            "E": "Excess (+20% to +59%)",
            "N": "Normal (-19% to +19%)",
            "D": "Deficient (-59% to -20%)",
            "LD": "Large Deficient (-99% to -60%)",
            "NR": "No Rain (0.0 mm)",
            "ND": "No Data (observation missing)",
        }

        results: List[IMDDistrictRainfallObservation] = []
        for entry in entries:
            d_name = entry.get("District") or entry.get("district") or "Unknown"
            matched_reg = resolve_telangana_district(str(d_name))

            if target_mapping:
                if not matched_reg or matched_reg.normalized_name != target_mapping.normalized_name:
                    continue
            elif not matched_reg:
                continue

            obs_date = str(entry.get("Date") or entry.get("date") or datetime.now(KOLKATA_TZ).strftime("%Y-%m-%d"))
            cat = str(entry.get("Category") or entry.get("category") or "ND").strip().upper()

            # Handle ND vs NR distinction
            raw_actual = entry.get("Daily_Actual") if "Daily_Actual" in entry else entry.get("daily_actual")
            is_nd = (cat == "ND" or raw_actual == "ND" or raw_actual is None)
            is_nr = (cat == "NR" or raw_actual == "NR")

            if is_nd:
                daily_actual_val = None
                cat = "ND"
            elif is_nr:
                daily_actual_val = 0.0
                cat = "NR"
            else:
                try:
                    daily_actual_val = float(raw_actual)
                except (TypeError, ValueError):
                    daily_actual_val = None
                    is_nd = True
                    cat = "ND"

            def _parse_float(v: Any) -> Optional[float]:
                if v is None or str(v).strip().upper() in ("ND", "NA", "-", ""):
                    return None
                try:
                    return float(v)
                except (TypeError, ValueError):
                    return None

            results.append(
                IMDDistrictRainfallObservation(
                    district_name=d_name,
                    matched_telangana_district=matched_reg.district_name if matched_reg else None,
                    retrieved_at=retrieved_at,
                    observation_date=obs_date,
                    daily_actual_mm=daily_actual_val,
                    daily_normal_mm=_parse_float(entry.get("Daily_Normal") or entry.get("daily_normal")),
                    daily_departure_percent=_parse_float(entry.get("Daily_Departure") or entry.get("daily_departure")),
                    weekly_actual_mm=_parse_float(entry.get("Weekly_Actual") or entry.get("weekly_actual")),
                    weekly_normal_mm=_parse_float(entry.get("Weekly_Normal") or entry.get("weekly_normal")),
                    cumulative_actual_mm=_parse_float(entry.get("Cumulative_Actual") or entry.get("cumulative_actual")),
                    cumulative_normal_mm=_parse_float(entry.get("Cumulative_Normal") or entry.get("cumulative_normal")),
                    monthly_actual_mm=_parse_float(entry.get("Monthly_Actual") or entry.get("monthly_actual")),
                    monthly_normal_mm=_parse_float(entry.get("Monthly_Normal") or entry.get("monthly_normal")),
                    rainfall_category=cat,
                    category_description=category_desc_map.get(cat, f"Category {cat}"),
                    is_no_data=is_nd,
                    is_no_rain=is_nr,
                    freshness_status=FreshnessStatus.CURRENT,
                )
            )

        return results

    # -------------------------------------------------------------------------
    # D. Five-Day District Rainfall Forecast (/api/v1/state_district_rainfall_forecast)
    # -------------------------------------------------------------------------
    def get_district_rainfall_forecast(
        self,
        district_name: Optional[str] = None,
        language: str = "te-IN",
    ) -> List[IMDDistrictRainfallForecast]:
        """
        Retrieve official 5-day district rainfall forecast from IMD.
        Preserves rainfall distribution categories (WS, FWS, SCT, ISOL, DRY) and station percentage
        without inventing false millimetre estimates.
        """
        target_mapping = None
        if district_name and district_name.strip():
            target_mapping = resolve_telangana_district(district_name)
            if not target_mapping:
                raise LocationDistrictMismatchError(
                    f"District '{district_name}' is not a recognized Telangana revenue district.",
                    details={"requested_district": district_name},
                )

        raw_payload = self._execute_get_request("rainfall_forecast_district")
        retrieved_at = datetime.now(timezone.utc).astimezone(KOLKATA_TZ).isoformat()

        entries: List[Dict[str, Any]] = []
        if isinstance(raw_payload, list):
            entries = raw_payload
        elif isinstance(raw_payload, dict):
            for k in ("data", "forecasts", "rainfall_forecast", "records"):
                if isinstance(raw_payload.get(k), list):
                    entries = raw_payload[k]
                    break
            if not entries and "District" in raw_payload:
                entries = [raw_payload]

        dist_names = {
            "WS": "Widespread (76-100% of stations reporting rain)",
            "FWS": "Fairly Widespread (51-75% of stations reporting rain)",
            "SCT": "Scattered (26-50% of stations reporting rain)",
            "ISOL": "Isolated (1-25% of stations reporting rain)",
            "DRY": "Dry (0% of stations reporting rain)",
        }
        station_pcts = {
            "WS": "76-100%",
            "FWS": "51-75%",
            "SCT": "26-50%",
            "ISOL": "1-25%",
            "DRY": "0%",
        }

        results: List[IMDDistrictRainfallForecast] = []
        for entry in entries:
            d_name = entry.get("District") or entry.get("district") or "Unknown"
            matched_reg = resolve_telangana_district(str(d_name))

            if target_mapping:
                if not matched_reg or matched_reg.normalized_name != target_mapping.normalized_name:
                    continue
            elif not matched_reg:
                continue

            issue_date = str(entry.get("Issue_Date") or entry.get("issue_date") or entry.get("Date") or datetime.now(KOLKATA_TZ).strftime("%Y-%m-%d"))

            day_entries: List[IMDDistrictRainfallForecastDay] = []
            for day_idx in range(1, 6):
                raw_code = str(entry.get(f"Day_{day_idx}") or entry.get(f"Day{day_idx}") or "DRY").strip().upper()
                raw_pct = entry.get(f"Day_{day_idx}_Stations") or entry.get(f"Day{day_idx}_Stations") or station_pcts.get(raw_code, "Unknown")
                raw_color = entry.get(f"Day_{day_idx}_Color") or entry.get(f"Day{day_idx}_Color")

                try:
                    base_d = datetime.strptime(issue_date, "%Y-%m-%d").date()
                    day_d = (base_d + timedelta(days=day_idx - 1)).isoformat()
                except Exception:
                    day_d = issue_date

                day_entries.append(
                    IMDDistrictRainfallForecastDay(
                        day_number=day_idx,
                        date=day_d,
                        distribution_code=raw_code,
                        distribution_name=dist_names.get(raw_code, f"Distribution: {raw_code}"),
                        station_percentage_range=str(raw_pct),
                        warning_color=str(raw_color) if raw_color else None,
                    )
                )

            results.append(
                IMDDistrictRainfallForecast(
                    district_name=d_name,
                    state_name=entry.get("State", "Telangana"),
                    matched_telangana_district=matched_reg.district_name if matched_reg else None,
                    retrieved_at=retrieved_at,
                    issue_date=issue_date,
                    forecast_days=day_entries,
                    freshness_status=FreshnessStatus.CURRENT,
                    disclaimer=get_weather_disclaimer(language),
                )
            )

        return results

    # -------------------------------------------------------------------------
    # E. Current Station Weather (/api/v1/current_wx)
    # -------------------------------------------------------------------------
    def get_station_weather(self, station_id: str) -> IMDStationObservation:
        """
        Retrieve surface meteorological observations for a verified IMD physical station.
        Measurements represent ground telemetry at the named station; not village-level field conditions.
        """
        raw_payload = self._execute_get_request("current_station_weather", params={"station_id": station_id})
        retrieved_at = datetime.now(timezone.utc).astimezone(KOLKATA_TZ).isoformat()

        entry: Dict[str, Any] = {}
        if isinstance(raw_payload, list) and raw_payload:
            entry = raw_payload[0]
        elif isinstance(raw_payload, dict):
            entry = raw_payload.get("data", raw_payload)

        stn_id = str(entry.get("station_id") or station_id)
        stn_name = entry.get("station_name") or entry.get("Station") or f"IMD Station {stn_id}"

        # Check matched district if in verified Telangana stations
        matched_dist = None
        for k, info in TELANGANA_VERIFIED_CITY_STATIONS.items():
            if info["station_id"] == stn_id or k.lower() == stn_id.lower():
                stn_name = info["city_name"]
                matched_dist = info["district"]
                break

        obs_date = str(entry.get("Date") or entry.get("date") or datetime.now(KOLKATA_TZ).strftime("%Y-%m-%d"))
        obs_utc = str(entry.get("time_utc") or entry.get("time") or "00:00:00")
        obs_kolkata = self._utc_to_kolkata_iso(obs_utc, obs_date) or retrieved_at

        def _get_float(key: str) -> Optional[float]:
            val = entry.get(key)
            if val is None or str(val).strip().upper() in ("ND", "NA", "-", ""):
                return None
            try:
                return float(val)
            except (TypeError, ValueError):
                return None

        return IMDStationObservation(
            station_id=stn_id,
            station_name=stn_name,
            matched_telangana_district=matched_dist,
            retrieved_at=retrieved_at,
            observation_date=obs_date,
            observation_time_utc=obs_utc,
            observation_time_kolkata=obs_kolkata,
            temperature_c=_get_float("temp_c") or _get_float("temp"),
            humidity_percent=_get_float("humidity") or _get_float("rh"),
            wind_speed_kph=_get_float("wind_kph") or _get_float("wind_speed"),
            wind_direction_deg=_get_float("wind_dir_deg") or _get_float("wind_direction"),
            wind_direction_compass=entry.get("wind_dir"),
            rainfall_last_24h_mm=_get_float("rain_24h_mm") or _get_float("rainfall_last_24h"),
            freshness_status=FreshnessStatus.CURRENT,
        )

    # -------------------------------------------------------------------------
    # F. Seven-Day City Forecast (/api/v1/cityforecast)
    # -------------------------------------------------------------------------
    def get_city_forecast(self, city_id: str, language: str = "te-IN") -> IMDCityForecast:
        """
        Retrieve 7-day city weather forecast from IMD.
        Enforces verified Telangana city/station mapping before querying.
        """
        city_key = city_id.strip().upper()
        if city_key not in TELANGANA_VERIFIED_CITY_STATIONS:
            raise LocationNotFoundError(
                f"City identifier '{city_id}' is not in verified IMD station mapping for Telangana.",
                provider=self.PROVIDER_NAME,
                details={"verified_cities": list(TELANGANA_VERIFIED_CITY_STATIONS.keys())},
            )

        info = TELANGANA_VERIFIED_CITY_STATIONS[city_key]
        raw_payload = self._execute_get_request("city_forecast", params={"city_id": info["station_id"]})
        retrieved_at = datetime.now(timezone.utc).astimezone(KOLKATA_TZ).isoformat()

        days_raw: List[Dict[str, Any]] = []
        if isinstance(raw_payload, list):
            days_raw = raw_payload
        elif isinstance(raw_payload, dict):
            days_raw = raw_payload.get("forecast", raw_payload.get("data", []))

        issue_date = datetime.now(KOLKATA_TZ).strftime("%Y-%m-%d")

        return IMDCityForecast(
            city_id=city_key,
            city_name=info["city_name"],
            matched_telangana_district=info["district"],
            retrieved_at=retrieved_at,
            issue_date=issue_date,
            forecast_days=days_raw,
            freshness_status=FreshnessStatus.CURRENT,
            disclaimer=get_weather_disclaimer(language),
        )

    # -------------------------------------------------------------------------
    # Backward Compatible Base Provider Methods
    # -------------------------------------------------------------------------
    def get_current_weather(
        self,
        query: str,
        lat: Optional[float] = None,
        lon: Optional[float] = None,
        language: str = "te-IN",
    ) -> CurrentWeatherConditions:
        """
        Retrieve ground AWS observations or nowcasts from IMD.
        Fails safely if official credentials are not yet configured.
        """
        self._ensure_configured()
        raise NotImplementedError("Live IMD endpoint invocation pending active credentials verification.")

    def get_forecast(
        self,
        query: str,
        days: int = 5,
        lat: Optional[float] = None,
        lon: Optional[float] = None,
        language: str = "te-IN",
    ) -> WeatherForecastResponse:
        """
        Retrieve 5-day district rainfall forecast or 7-day city forecast from IMD.
        Fails safely if official credentials are not yet configured.
        """
        self._ensure_configured()
        raise NotImplementedError("Live IMD endpoint invocation pending active credentials verification.")

