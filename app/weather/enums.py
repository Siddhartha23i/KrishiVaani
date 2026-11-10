"""
Weather domain enums for KrishiVaani — Phase 6.1.
Enforces strict distinction between:
- Information types (observations vs forecasts vs advisories vs outlooks)
- Geographical resolutions (grid point vs rain-gauge station vs mandal vs district)
- Freshness states
- Weather forecast horizons vs Agricultural planning horizons
"""

from enum import Enum


class WeatherInformationType(str, Enum):
    """
    Standardized categorization of meteorological information.
    Maintains strict separation between physical observations and model forecasts.
    """
    CURRENT_CONDITIONS = "current_conditions"
    WEATHER_FORECAST = "weather_forecast"
    WEATHER_WARNING = "weather_warning"
    RAINFALL_OBSERVATION = "rainfall_observation"
    AGROMET_ADVISORY = "agromet_advisory"
    EXTENDED_RANGE_OUTLOOK = "extended_range_outlook"
    MONTHLY_OUTLOOK = "monthly_outlook"
    SEASONAL_OUTLOOK = "seasonal_outlook"


class GeographicalResolution(str, Enum):
    """
    Spatial resolution of weather information.
    Ensures that nearby grid points are never described as exact village weather stations.
    """
    POINT_GRID = "point_grid"          # Numerical model grid interpolation (e.g., WeatherAPI)
    STATION = "station"                # Physical ground telemetry / rain-gauge station (e.g., IMD AWS)
    MANDAL = "mandal"                  # Mandal-level aggregate (e.g., TSDPS automatic rain-gauge)
    DISTRICT = "district"              # District-level aggregate / warning / bulletin
    SUBDIVISION = "subdivision"        # Meteorological subdivision (e.g., Telangana subdivision)
    STATE = "state"                    # State-level outlook or advisory


class FreshnessStatus(str, Enum):
    """Temporal freshness classification of retrieved meteorological data."""
    CURRENT = "current"
    STALE = "stale"
    EXPIRED = "expired"


class ProviderStatus(str, Enum):
    """Operational status of a weather data provider integration."""
    ACTIVE = "active"
    CONFIGURED = "configured"
    NOT_CONFIGURED = "not_configured"
    AUTHENTICATION_ERROR = "authentication_error"
    PENDING_CREDENTIALS = "pending_credentials"
    PENDING_MACHINE_READABLE_FEED = "pending_machine_readable_feed"
    UNAVAILABLE = "unavailable"


class WeatherForecastHorizon(str, Enum):
    """
    Meteorological forecast horizon windows.
    Strictly distinguished from agricultural decision-support planning horizons.
    """
    HOURLY_24H = "hourly_24h"
    SHORT_RANGE_1_3D = "short_range_1_3d"       # Free plan limit for WeatherAPI.com
    MEDIUM_RANGE_4_7D = "medium_range_4_7d"     # 4-7 days (requires IMD or paid tier)
    EXTENDED_RANGE_8_15D = "extended_range_8_15d"  # IMD weekly anomaly outlooks
    MONTHLY_OUTLOOK_16_30D = "monthly_outlook_16_30d"  # Monthly outlooks / trends
    SEASONAL_OUTLOOK_31_60D = "seasonal_outlook_31_60d" # Probabilistic seasonal outlooks


# -----------------------------------------------------------------------------
# Phase 6.2: IMD Official Warning, Nowcast, and Rainfall Domain Enums
# -----------------------------------------------------------------------------
class IMDDistrictWarningColor(str, Enum):
    """
    IMD District Warning Severity Color Mapping (/api/v1/districtwarning).
    Documented mapping:
    Code 1 -> Red (Take Action)
    Code 2 -> Orange (Be Prepared)
    Code 3 -> Yellow (Be Updated)
    Code 4 -> Green (No Warning)
    """
    RED = "Red"
    ORANGE = "Orange"
    YELLOW = "Yellow"
    GREEN = "Green"
    UNKNOWN = "Unknown"


class IMDNowcastColor(str, Enum):
    """
    IMD District Nowcast Severity Color Mapping (/api/v1/districtnowcast).
    Documented mapping (INVERTED from districtwarning):
    Code 1 -> Green (No Warning)
    Code 2 -> Yellow (Watch / Be Updated)
    Code 3 -> Orange (Alert / Be Prepared)
    Code 4 -> Red (Warning / Take Action)
    """
    GREEN = "Green"
    YELLOW = "Yellow"
    ORANGE = "Orange"
    RED = "Red"
    UNKNOWN = "Unknown"


class IMDRainfallCategory(str, Enum):
    """
    IMD District Rainfall Observation Categories (/api/v1/districtrainfall).
    LE: Large Excess (>= +60% departure)
    E: Excess (+20% to +59% departure)
    N: Normal (-19% to +19% departure)
    D: Deficient (-59% to -20% departure)
    LD: Large Deficient (-99% to -60% departure)
    NR: No Rain (0.0 mm received)
    ND: No Data (missing telemetry; MUST NOT be treated as zero rainfall!)
    """
    LARGE_EXCESS = "LE"
    EXCESS = "E"
    NORMAL = "N"
    DEFICIENT = "D"
    LARGE_DEFICIENT = "LD"
    NO_RAIN = "NR"
    NO_DATA = "ND"
    UNKNOWN = "UNKNOWN"


class IMDRainfallDistribution(str, Enum):
    """
    IMD 5-Day District Rainfall Distribution Categories (/api/v1/state_district_rainfall_forecast).
    WS: Widespread (76-100% of stations reporting rain)
    FWS: Fairly Widespread (51-75% of stations reporting rain)
    SCT: Scattered (26-50% of stations reporting rain)
    ISOL: Isolated (1-25% of stations reporting rain)
    DRY: Dry (0% of stations reporting rain)
    """
    WIDESPREAD = "WS"
    FAIRLY_WIDESPREAD = "FWS"
    SCATTERED = "SCT"
    ISOLATED = "ISOL"
    DRY = "DRY"
    UNKNOWN = "UNKNOWN"


def map_district_warning_color(code: object) -> str:
    """
    Maps IMD districtwarning color code (1=Red, 2=Orange, 3=Yellow, 4=Green).
    """
    try:
        val = int(code)  # type: ignore
        mapping = {1: "Red", 2: "Orange", 3: "Yellow", 4: "Green"}
        return mapping.get(val, "Unknown")
    except (TypeError, ValueError):
        if isinstance(code, str):
            c = code.strip().capitalize()
            if c in ("Red", "Orange", "Yellow", "Green"):
                return c
        return "Unknown"


def map_district_nowcast_color(code: object) -> str:
    """
    Maps IMD districtnowcast color code (1=Green, 2=Yellow, 3=Orange, 4=Red).
    Note: Severity direction is opposite of districtwarning!
    """
    try:
        val = int(code)  # type: ignore
        mapping = {1: "Green", 2: "Yellow", 3: "Orange", 4: "Red"}
        return mapping.get(val, "Unknown")
    except (TypeError, ValueError):
        if isinstance(code, str):
            c = code.strip().capitalize()
            if c in ("Green", "Yellow", "Orange", "Red"):
                return c
        return "Unknown"

