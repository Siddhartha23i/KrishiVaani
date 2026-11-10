"""
Pydantic schemas for KrishiVaani Weather Intelligence Service — Phase 6.1.1.
Enforces strict provenance, metadata preservation, explicit spatial resolution,
end-user legal disclaimers, and clear separation between observed telemetry
and numerical model forecast estimates.
"""

from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field

from app.weather.enums import (
    WeatherInformationType,
    GeographicalResolution,
    FreshnessStatus,
    WeatherForecastHorizon,
)


class WeatherLocationInfo(BaseModel):
    """
    Resolved location metadata for a weather query.
    Maintains strict separation between requested coordinates, provider-reported location,
    and underlying meteorological grid resolution (~1-11 km).
    """
    location_name: str = Field(..., description="Matched locality or weather station name")
    region: Optional[str] = Field(None, description="State or administrative region reported by provider")
    country: str = Field(..., description="Country name (must be India)")

    # Phase 6.1.1 explicit precision & resolution fields
    requested_latitude: Optional[float] = Field(None, description="Farmer profile latitude supplied in query")
    requested_longitude: Optional[float] = Field(None, description="Farmer profile longitude supplied in query")
    provider_location_latitude: Optional[float] = Field(None, description="Latitude of matched provider grid center or station")
    provider_location_longitude: Optional[float] = Field(None, description="Longitude of matched provider grid center or station")
    provider_grid_resolution_km: str = Field(
        "1-11 km",
        description="Documented spatial resolution range of provider's numerical prediction model grid (~1-11 km)"
    )
    location_match_status: str = Field(
        "not_independently_verified",
        description="Location verification status: coordinates_matched, text_matched_not_independently_verified, etc."
    )
    geographical_resolution: GeographicalResolution = Field(
        GeographicalResolution.POINT_GRID,
        description="Standardized spatial resolution enum"
    )
    resolution: GeographicalResolution = Field(
        GeographicalResolution.POINT_GRID,
        description="Backward-compatible alias for geographical_resolution"
    )
    station_identifier: Optional[str] = Field(None, description="Physical ground station ID if verified by provider")
    station_observation_confirmed: bool = Field(
        False,
        description="True ONLY if verified to originate from a physical on-site telemetry/rain-gauge station"
    )
    is_nearby_grid_estimate: bool = Field(
        True,
        description="True when data represents a numerical model grid estimate rather than an on-site village station"
    )
    matched_district: Optional[str] = Field(None, description="Farmer profile district associated with query")
    matched_village: Optional[str] = Field(None, description="Farmer profile village name")
    timezone: str = Field("Asia/Kolkata", description="IANA timezone identifier")

    # Backward-compatible latitude/longitude getters
    @property
    def latitude(self) -> Optional[float]:
        return self.provider_location_latitude or self.requested_latitude

    @property
    def longitude(self) -> Optional[float]:
        return self.provider_location_longitude or self.requested_longitude


class CurrentWeatherConditions(BaseModel):
    """
    Normalized current weather observations or model-grid analysis.
    Preserves full provenance, timestamps, attribution, required legal disclaimer,
    and station vs model distinction.
    """
    source_name: str = Field(..., description="Name of the reporting provider")
    source_url: str = Field(..., description="Provider source URL")
    retrieved_at: str = Field(..., description="ISO-8601 timestamp when KrishiVaani retrieved this record")
    issued_at: Optional[str] = Field(None, description="ISO-8601 timestamp when provider issued/updated this record")
    valid_from: str = Field(..., description="ISO-8601 timestamp start of validity window")
    valid_until: str = Field(..., description="ISO-8601 timestamp end of validity window")
    information_type: WeatherInformationType = Field(
        WeatherInformationType.CURRENT_CONDITIONS,
        description="Information category"
    )
    geographical_resolution: GeographicalResolution = Field(
        GeographicalResolution.POINT_GRID,
        description="Spatial resolution of measurement"
    )
    location: WeatherLocationInfo = Field(..., description="Resolved location details")
    timezone: str = Field("Asia/Kolkata", description="Local timezone")
    attribution: str = Field(..., description="Required provider attribution")
    freshness_status: FreshnessStatus = Field(FreshnessStatus.CURRENT, description="Freshness classification")

    # Phase 6.1.1: Localized end-user weather disclaimer
    disclaimer: str = Field(..., description="Localized intelligible end-user weather disclaimer")
    disclaimer_language: str = Field("te-IN", description="Language of end-user disclaimer (te-IN, hi-IN, en-IN)")

    # Meteorological fields
    temperature_c: float = Field(..., description="Air temperature in Celsius")
    feels_like_c: Optional[float] = Field(None, description="Heat index / wind chill equivalent temperature in Celsius")
    humidity_percent: Optional[float] = Field(None, description="Relative humidity percentage (0-100)")
    wind_kph: Optional[float] = Field(None, description="Wind speed in kilometers per hour")
    wind_dir: Optional[str] = Field(None, description="Wind direction compass abbreviation (e.g., ENE, SSW)")
    condition_text: Optional[str] = Field(None, description="Weather condition description (e.g., Sunny, Partly cloudy)")
    condition_code: Optional[int] = Field(None, description="Provider weather condition numeric code")
    uv_index: Optional[float] = Field(None, description="Ultraviolet radiation index")
    precipitation_mm: Optional[float] = Field(None, description="Recent precipitation / rain rate in millimeters")
    is_day: Optional[bool] = Field(None, description="Whether it is daytime at the location")

    # Critical distinction between ground rain-gauge observation and model estimate
    is_station_observation: bool = Field(
        False,
        description="False for model-interpolated weather data; True ONLY for physical ground AWS/telemetry stations"
    )
    station_observation_confirmed: bool = Field(
        False,
        description="True ONLY if provider explicitly confirms measurement from a named physical ground station"
    )
    data_source_nature: str = Field(
        "provider_reported_current_conditions",
        description="Identifies nature of current data: provider_reported_current_conditions vs confirmed_ground_station_telemetry"
    )
    observed_rainfall_mm: Optional[float] = Field(
        None,
        description="Ground rain-gauge measurement (None for model estimates; never labeled as TSDPS/IMD without evidence)"
    )
    forecast_rainfall_mm: Optional[float] = Field(
        None,
        description="Forecast or model-analyzed rainfall estimate"
    )


class HourlyWeatherForecast(BaseModel):
    """Hourly weather prediction record."""
    time: str = Field(..., description="ISO-8601 local timestamp")
    temp_c: float = Field(..., description="Forecast temperature in Celsius")
    condition_text: Optional[str] = Field(None, description="Condition description")
    condition_code: Optional[int] = Field(None, description="Condition numeric code")
    precip_mm: Optional[float] = Field(None, description="Forecast precipitation in mm")
    humidity_percent: Optional[float] = Field(None, description="Forecast relative humidity")
    wind_kph: Optional[float] = Field(None, description="Forecast wind speed in kph")
    chance_of_rain_percent: Optional[int] = Field(None, description="Probability of rain (0-100)")


class DailyWeatherForecast(BaseModel):
    """Daily forecast record within a short-range forecast period."""
    date: str = Field(..., description="Date string in YYYY-MM-DD format")
    max_temp_c: float = Field(..., description="Forecast maximum temperature in Celsius")
    min_temp_c: float = Field(..., description="Forecast minimum temperature in Celsius")
    avg_temp_c: Optional[float] = Field(None, description="Forecast average temperature in Celsius")
    max_wind_kph: Optional[float] = Field(None, description="Forecast peak wind speed in kph")
    total_precipitation_mm: float = Field(0.0, description="Forecast total precipitation in millimeters")
    avg_humidity_percent: Optional[float] = Field(None, description="Forecast average relative humidity")
    condition_text: Optional[str] = Field(None, description="Weather condition description")
    condition_code: Optional[int] = Field(None, description="Numeric condition code")
    uv_index: Optional[float] = Field(None, description="Forecast UV index")
    chance_of_rain_percent: Optional[int] = Field(None, description="Probability of precipitation (0-100)")
    is_model_estimate: bool = Field(True, description="True for numerical model forecasts")
    forecast_rainfall_mm: Optional[float] = Field(None, description="Model forecast rainfall in mm")
    observed_rainfall_mm: Optional[float] = Field(None, description="Always None for forecast days")
    hourly: Optional[List[HourlyWeatherForecast]] = Field(None, description="Optional hourly breakdown")


class WeatherForecastResponse(BaseModel):
    """
    Standardized multi-day weather forecast response.
    Includes provenance, forecast horizon categorization, provider attribution,
    end-user disclaimer, and agricultural planning safety reminder.
    """
    source_name: str = Field(..., description="Name of the reporting provider")
    source_url: str = Field(..., description="Provider source URL")
    retrieved_at: str = Field(..., description="ISO-8601 timestamp when KrishiVaani retrieved this forecast")
    issued_at: Optional[str] = Field(None, description="ISO-8601 timestamp when provider issued this forecast")
    valid_from: str = Field(..., description="ISO-8601 timestamp start of forecast validity")
    valid_until: str = Field(..., description="ISO-8601 timestamp end of forecast validity")
    information_type: WeatherInformationType = Field(
        WeatherInformationType.WEATHER_FORECAST,
        description="Information category"
    )
    geographical_resolution: GeographicalResolution = Field(
        GeographicalResolution.POINT_GRID,
        description="Spatial resolution of forecast"
    )
    forecast_horizon: WeatherForecastHorizon = Field(
        WeatherForecastHorizon.SHORT_RANGE_1_3D,
        description="Meteorological forecast horizon window"
    )
    days_count: int = Field(..., description="Number of daily forecast records included")
    location: WeatherLocationInfo = Field(..., description="Resolved location metadata")
    timezone: str = Field("Asia/Kolkata", description="Local timezone")
    attribution: str = Field(..., description="Required provider attribution string")
    freshness_status: FreshnessStatus = Field(FreshnessStatus.CURRENT, description="Freshness classification")
    forecast_days: List[DailyWeatherForecast] = Field(..., description="List of daily forecast records")

    # Phase 6.1.1: Localized end-user weather disclaimer
    disclaimer: str = Field(..., description="Localized intelligible end-user weather disclaimer")
    disclaimer_language: str = Field("te-IN", description="Language of end-user disclaimer (te-IN, hi-IN, en-IN)")

    planning_safety_note: str = Field(
        "A weather forecast alone must never automatically trigger an agricultural recommendation. "
        "Field decisions require verified crop, stage, soil, and official advisory context.",
        description="Mandatory advisory safety notice"
    )


class WeatherServiceStatusResponse(BaseModel):
    """Operational status report for KrishiVaani weather intelligence system."""
    status: str = Field(..., description="Overall service status (healthy, degraded, unconfigured)")
    configured_providers: Dict[str, str] = Field(..., description="Provider names mapped to their operational status")
    default_provider: Optional[str] = Field(None, description="Default active provider for short-range weather")
    supported_horizons: List[str] = Field(..., description="List of currently supported meteorological horizons")
    cache_entries_count: int = Field(0, description="Active items in weather memory cache")
    notes: List[str] = Field(default_factory=list, description="Operational notes and caveats")


class WeatherErrorResponse(BaseModel):
    """Standardized API error envelope for weather service failures."""
    error_code: str = Field(..., description="Machine-readable error identifier")
    message: str = Field(..., description="Farmer-safe human-readable explanation")
    provider: Optional[str] = Field(None, description="Provider associated with failure")
    details: Optional[Dict[str, Any]] = Field(None, description="Diagnostic details")


# -----------------------------------------------------------------------------
# Phase 6.2: Official IMD Weather Intelligence Schemas
# -----------------------------------------------------------------------------
class IMDDistrictDailyWarning(BaseModel):
    """Daily weather warning within a 5-day district warning horizon."""
    day_number: int = Field(..., ge=1, le=5, description="Forecast day index (1 to 5)")
    date: str = Field(..., description="Date of validity (YYYY-MM-DD)")
    warning_codes: List[str] = Field(default_factory=list, description="Warning categories (e.g. Heavy rain, Thunderstorm)")
    raw_color_code: Optional[int] = Field(None, description="Raw integer color code from IMD (1=Red, 2=Orange, 3=Yellow, 4=Green)")
    color_name: str = Field("Green", description="Color severity name: Red, Orange, Yellow, Green")
    severity_level: str = Field("no_warning", description="take_action, be_prepared, be_updated, no_warning")
    action_guidance: str = Field("", description="Standardized guidance for warning severity")


class IMDDistrictWarning(BaseModel):
    """
    Official 5-Day District Warning from India Meteorological Department (/api/v1/districtwarning).
    Preserves multiple warning codes per day, color mappings, and provenance.
    """
    source_name: str = Field("India Meteorological Department (IMD)", description="Provider name")
    source_url: str = Field("https://api.imd.gov.in/public/", description="Provider URL")
    endpoint: str = Field("/api/v1/districtwarning", description="Documented IMD API endpoint")
    district_name: str = Field(..., description="Provider reported district name")
    matched_telangana_district: Optional[str] = Field(None, description="Matched canonical Telangana district")
    retrieved_at: str = Field(..., description="ISO-8601 timestamp in Asia/Kolkata")
    issue_date: str = Field(..., description="Forecast issue date")
    issue_time_utc: Optional[str] = Field(None, description="Original UTC issue time from IMD")
    issue_time_kolkata: Optional[str] = Field(None, description="Converted Asia/Kolkata issue timestamp")
    geographical_resolution: GeographicalResolution = Field(
        GeographicalResolution.DISTRICT,
        description="Spatial resolution"
    )
    daily_warnings: List[IMDDistrictDailyWarning] = Field(default_factory=list, description="5-day warnings breakdown")
    freshness_status: FreshnessStatus = Field(FreshnessStatus.CURRENT, description="Temporal freshness")
    attribution: str = Field(
        "Data provided by India Meteorological Department (IMD), Ministry of Earth Sciences, Government of India",
        description="Attribution notice"
    )
    disclaimer: str = Field(..., description="Localized safety disclaimer")
    advisory_safety_note: str = Field(
        "A weather warning alone must not trigger automatic agricultural operations (Phase 5.4.1/6.2 policy).",
        description="Agricultural action gate"
    )


class IMDDistrictNowcast(BaseModel):
    """
    Official Short-Lived District Nowcast from IMD (/api/v1/districtnowcast).
    Nowcasts are valid for 3 hours; expired nowcasts must never be presented as active.
    Severity mapping: 1=Green, 2=Yellow, 3=Orange, 4=Red.
    """
    source_name: str = Field("India Meteorological Department (IMD)", description="Provider name")
    source_url: str = Field("https://api.imd.gov.in/public/", description="Provider URL")
    endpoint: str = Field("/api/v1/districtnowcast", description="Documented IMD API endpoint")
    station_or_district: str = Field(..., description="Reporting station or district name")
    matched_telangana_district: Optional[str] = Field(None, description="Matched canonical Telangana district")
    retrieved_at: str = Field(..., description="ISO-8601 timestamp in Asia/Kolkata")
    nowcast_date: str = Field(..., description="Nowcast date string")
    time_of_issue_utc: Optional[str] = Field(None, description="Raw UTC time of issue (toi)")
    time_of_issue_kolkata: Optional[str] = Field(None, description="Converted Asia/Kolkata issue timestamp")
    valid_until_utc: Optional[str] = Field(None, description="Raw UTC valid-until timestamp (Vupto)")
    valid_until_kolkata: Optional[str] = Field(None, description="Converted Asia/Kolkata valid-until timestamp")
    is_expired: bool = Field(False, description="True if valid-until time has passed")
    raw_color_code: Optional[int] = Field(None, description="Raw nowcast color code (1=Green, 2=Yellow, 3=Orange, 4=Red)")
    color_name: str = Field("Green", description="Color severity name: Green, Yellow, Orange, Red")
    severity_level: str = Field("no_warning", description="no_warning, be_updated, be_prepared, take_action")
    warning_categories: List[str] = Field(default_factory=list, description="Warning categories (e.g. Thunderstorm, Lightning)")
    consolidated_message: str = Field(..., description="Consolidated bulletin message")
    geographical_resolution: GeographicalResolution = Field(
        GeographicalResolution.DISTRICT,
        description="Spatial resolution"
    )
    freshness_status: FreshnessStatus = Field(FreshnessStatus.CURRENT, description="Freshness status")
    attribution: str = Field(
        "Data provided by India Meteorological Department (IMD), Ministry of Earth Sciences, Government of India",
        description="Attribution notice"
    )
    disclaimer: str = Field(..., description="Localized safety disclaimer")


class IMDDistrictRainfallObservation(BaseModel):
    """
    Official District Rainfall Observation from IMD (/api/v1/districtrainfall).
    Distinguishes ND (No Data) from NR (No Rain = 0.0 mm).
    """
    source_name: str = Field("India Meteorological Department (IMD)", description="Provider name")
    source_url: str = Field("https://api.imd.gov.in/public/", description="Provider URL")
    endpoint: str = Field("/api/v1/districtrainfall", description="Documented IMD API endpoint")
    district_name: str = Field(..., description="Provider reported district name")
    matched_telangana_district: Optional[str] = Field(None, description="Matched canonical Telangana district")
    retrieved_at: str = Field(..., description="ISO-8601 timestamp in Asia/Kolkata")
    observation_date: str = Field(..., description="Observation date (YYYY-MM-DD)")
    daily_actual_mm: Optional[float] = Field(None, description="Actual rainfall received in past 24h (None if ND)")
    daily_normal_mm: Optional[float] = Field(None, description="Climatological normal rainfall for the day")
    daily_departure_percent: Optional[float] = Field(None, description="Percentage departure from normal")
    weekly_actual_mm: Optional[float] = Field(None, description="Weekly cumulative actual rainfall")
    weekly_normal_mm: Optional[float] = Field(None, description="Weekly cumulative normal rainfall")
    cumulative_actual_mm: Optional[float] = Field(None, description="Season/cumulative actual rainfall")
    cumulative_normal_mm: Optional[float] = Field(None, description="Season/cumulative normal rainfall")
    monthly_actual_mm: Optional[float] = Field(None, description="Monthly cumulative actual rainfall")
    monthly_normal_mm: Optional[float] = Field(None, description="Monthly cumulative normal rainfall")
    rainfall_category: str = Field(..., description="Raw category: LE, E, N, D, LD, NR, ND")
    category_description: str = Field(..., description="Human readable category name")
    is_no_data: bool = Field(False, description="True if telemetry is missing (ND); does NOT mean 0 mm")
    is_no_rain: bool = Field(False, description="True if documented zero rainfall (NR)")
    geographical_resolution: GeographicalResolution = Field(
        GeographicalResolution.DISTRICT,
        description="Spatial resolution (district aggregate)"
    )
    freshness_status: FreshnessStatus = Field(FreshnessStatus.CURRENT, description="Freshness status")
    attribution: str = Field(
        "Data provided by India Meteorological Department (IMD), Ministry of Earth Sciences, Government of India",
        description="Attribution notice"
    )


class IMDDistrictRainfallForecastDay(BaseModel):
    """Daily forecast entry in 5-day district rainfall forecast."""
    day_number: int = Field(..., ge=1, le=5, description="Day index (1 to 5)")
    date: str = Field(..., description="Forecast date (YYYY-MM-DD)")
    distribution_code: str = Field(..., description="Raw distribution code: WS, FWS, SCT, ISOL, DRY")
    distribution_name: str = Field(..., description="Human-readable distribution: Widespread, Fairly Widespread, etc.")
    station_percentage_range: str = Field(..., description="Percentage of reporting stations expected to receive rain")
    warning_color: Optional[str] = Field(None, description="Associated warning color if provided")


class IMDDistrictRainfallForecast(BaseModel):
    """
    Official 5-Day District Rainfall Forecast from IMD (/api/v1/state_district_rainfall_forecast).
    Preserves distribution categories without manufacturing false millimetre estimates.
    """
    source_name: str = Field("India Meteorological Department (IMD)", description="Provider name")
    source_url: str = Field("https://api.imd.gov.in/public/", description="Provider URL")
    endpoint: str = Field("/api/v1/state_district_rainfall_forecast", description="Documented IMD API endpoint")
    district_name: str = Field(..., description="Provider reported district name")
    state_name: str = Field("Telangana", description="State name")
    matched_telangana_district: Optional[str] = Field(None, description="Matched canonical Telangana district")
    retrieved_at: str = Field(..., description="ISO-8601 timestamp in Asia/Kolkata")
    issue_date: str = Field(..., description="Forecast issue date")
    forecast_days: List[IMDDistrictRainfallForecastDay] = Field(default_factory=list, description="5-day distribution entries")
    geographical_resolution: GeographicalResolution = Field(
        GeographicalResolution.DISTRICT,
        description="Spatial resolution"
    )
    freshness_status: FreshnessStatus = Field(FreshnessStatus.CURRENT, description="Freshness status")
    attribution: str = Field(
        "Data provided by India Meteorological Department (IMD), Ministry of Earth Sciences, Government of India",
        description="Attribution notice"
    )
    disclaimer: str = Field(..., description="Localized safety disclaimer")


class IMDStationObservation(BaseModel):
    """
    Official Surface Meteorological Observation from Named IMD Station (/api/v1/current_wx).
    Represents ground telemetry at the named station; not farmer's exact village.
    """
    source_name: str = Field("India Meteorological Department (IMD)", description="Provider name")
    source_url: str = Field("https://api.imd.gov.in/public/", description="Provider URL")
    endpoint: str = Field("/api/v1/current_wx", description="Documented IMD API endpoint")
    station_id: str = Field(..., description="Official IMD station identifier")
    station_name: str = Field(..., description="Official station location name")
    matched_telangana_district: Optional[str] = Field(None, description="Associated Telangana district")
    retrieved_at: str = Field(..., description="ISO-8601 timestamp in Asia/Kolkata")
    observation_date: str = Field(..., description="Date of observation")
    observation_time_utc: str = Field(..., description="Original observation time in UTC")
    observation_time_kolkata: str = Field(..., description="Converted observation time in Asia/Kolkata")
    temperature_c: Optional[float] = Field(None, description="Air temperature in Celsius")
    humidity_percent: Optional[float] = Field(None, description="Relative humidity percentage")
    wind_speed_kph: Optional[float] = Field(None, description="Wind speed in km/h")
    wind_direction_deg: Optional[float] = Field(None, description="Wind direction in degrees")
    wind_direction_compass: Optional[str] = Field(None, description="Wind direction compass abbreviation")
    rainfall_last_24h_mm: Optional[float] = Field(None, description="Precipitation in last 24h")
    is_station_observation: bool = Field(True, description="Always True for physical AWS observation")
    station_observation_confirmed: bool = Field(True, description="Always True for verified IMD station")
    geographical_resolution: GeographicalResolution = Field(
        GeographicalResolution.STATION,
        description="Physical ground station"
    )
    freshness_status: FreshnessStatus = Field(FreshnessStatus.CURRENT, description="Freshness status")
    station_context_note: str = Field(
        "Ground observation measured at named IMD station; does not imply identical microclimatic conditions at specific farm fields.",
        description="Context notice"
    )
    attribution: str = Field(
        "Data provided by India Meteorological Department (IMD), Ministry of Earth Sciences, Government of India",
        description="Attribution notice"
    )


class IMDCityForecast(BaseModel):
    """
    Official 7-Day City Forecast from IMD (/api/v1/cityforecast).
    Requires verified city/station mapping before querying.
    """
    source_name: str = Field("India Meteorological Department (IMD)", description="Provider name")
    source_url: str = Field("https://api.imd.gov.in/public/", description="Provider URL")
    endpoint: str = Field("/api/v1/cityforecast", description="Documented IMD API endpoint")
    city_id: str = Field(..., description="Verified IMD city identifier")
    city_name: str = Field(..., description="Verified city name")
    matched_telangana_district: Optional[str] = Field(None, description="Associated Telangana district")
    retrieved_at: str = Field(..., description="ISO-8601 timestamp in Asia/Kolkata")
    issue_date: str = Field(..., description="Forecast issue date")
    forecast_days: List[Dict[str, Any]] = Field(default_factory=list, description="7-day city predictions")
    geographical_resolution: GeographicalResolution = Field(
        GeographicalResolution.DISTRICT,
        description="Spatial resolution"
    )
    freshness_status: FreshnessStatus = Field(FreshnessStatus.CURRENT, description="Freshness status")
    attribution: str = Field(
        "Data provided by India Meteorological Department (IMD), Ministry of Earth Sciences, Government of India",
        description="Attribution notice"
    )
    disclaimer: str = Field(..., description="Localized safety disclaimer")
