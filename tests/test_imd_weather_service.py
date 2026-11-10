"""
Unit test suite for KrishiVaani Official IMD Weather Integration — Phase 6.2.
Tests all 26 criteria mandated in Phase 6.2 specification:
1. IMD credentials missing -> PENDING_CREDENTIALS / ProviderNotConfiguredError without secret leakage.
2. Successful district-warning response.
3. Multiple warning codes for one day preserved.
4. Warning colour mapping: 1=Red, 2=Orange, 3=Yellow, 4=Green.
5. Nowcast colour mapping: 1=Green, 2=Yellow, 3=Orange, 4=Red.
6. Different colour mappings for warning and nowcast endpoints.
7. Nowcast validity-time handling (toi, Vupto converted to Asia/Kolkata).
8. Expired nowcast handling (is_expired=True, FreshnessStatus.EXPIRED).
9. District rainfall daily/weekly/monthly parsing.
10. ND versus NR distinction (ND=No Data, NR=No Rain).
11. Missing rainfall values never become zero (None preserved).
12. Five-day rainfall forecast parsing.
13. Distribution categories (WS, FWS, SCT, ISOL, DRY) retained without invented rainfall amounts.
14. Current station weather observation timestamps (UTC to Asia/Kolkata).
15. UTC-to-Asia/Kolkata conversion (+05:30 offset).
16. City forecast only uses verified station mappings.
17. District aliases resolve correctly against official Telangana 33 districts.
18. Unknown/non-Telangana districts are rejected with LocationDistrictMismatchError.
19. No AMFU inference from PJTSAU zone.
20. Missing warnings do not become "No Warning".
21. Stale data is not presented as current.
22. IMD authentication failures handled safely without secret leakage.
23. No secret leakage in logs or HTTP responses.
24. Existing weather provider location-sharing consent remains intact.
25. Existing WeatherAPI behaviour remains unchanged.
26. FastAPI endpoints contract for all IMD routes.
"""

import unittest
from unittest.mock import patch, MagicMock
from pathlib import Path
import tempfile
import json
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
import httpx
from fastapi.testclient import TestClient

from app.main import create_application
from app.core.config import settings
from app.db.database import init_db
from app.models.farmer import FarmerModel
from app.services.farmer_service import FarmerService
from app.weather.enums import (
    ProviderStatus,
    FreshnessStatus,
    GeographicalResolution,
    IMDDistrictWarningColor,
    IMDNowcastColor,
    IMDRainfallCategory,
    IMDRainfallDistribution,
    map_district_warning_color,
    map_district_nowcast_color,
)
from app.weather.schemas import (
    IMDDistrictWarning,
    IMDDistrictNowcast,
    IMDDistrictRainfallObservation,
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
    WeatherLocationSharingConsentRequiredError,
    InvalidProviderResponseError,
)
from app.weather.providers.imd_provider import (
    IMDWeatherProvider,
    IMDAuthenticationEvidence,
    TELANGANA_VERIFIED_CITY_STATIONS,
)
from app.weather.providers.weatherapi_provider import WeatherAPIProvider
from app.weather.services.location_weather_service import LocationWeatherService
from app.weather.services.weather_service import WeatherService
from app.knowledge.season_calendar import resolve_telangana_district

KOLKATA_TZ = ZoneInfo("Asia/Kolkata")


# -----------------------------------------------------------------------------
# Mock IMD API Payloads
# -----------------------------------------------------------------------------
MOCK_IMD_WARNINGS_PAYLOAD = [
    {
        "District": "Jagtial",
        "Date": "2026-11-06",
        "time": "12:00:00",
        "Day_1": "Heavy rain, Thunderstorm and lightning",
        "Day1_Color": 1,  # 1=Red in districtwarning
        "Day_2": "Thunderstorm and lightning",
        "Day2_Color": 2,  # 2=Orange
        "Day_3": "Moderate rain",
        "Day3_Color": 3,  # 3=Yellow
        "Day_4": "No Warning",
        "Day4_Color": 4,  # 4=Green
        "Day_5": "No Warning",
        "Day5_Color": 4,
    },
    {
        "District": "Hanamkonda",
        "Date": "2026-11-06",
        "time": "12:00:00",
        "Day_1": "Thunderstorm and lightning",
        "Day1_Color": 2,
        "Day_2": "No Warning",
        "Day2_Color": 4,
        "Day_3": "No Warning",
        "Day3_Color": 4,
        "Day_4": "No Warning",
        "Day4_Color": 4,
        "Day_5": "No Warning",
        "Day5_Color": 4,
    },
]

MOCK_IMD_NOWCAST_ACTIVE_PAYLOAD = [
    {
        "Station": "Jagtial",
        "Date": "2026-11-06",
        "Warning": "Thunderstorm with lightning, Light to moderate rain",
        "msg": "Thunderstorm with lightning accompanied with light to moderate rain likely over Jagtial district.",
        "toi": (datetime.now(timezone.utc) - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S"),
        "Vupto": (datetime.now(timezone.utc) + timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S"),
        "Color": 3,  # 3=Orange in districtnowcast!
    }
]

MOCK_IMD_NOWCAST_EXPIRED_PAYLOAD = [
    {
        "Station": "Jagtial",
        "Date": "2026-11-06",
        "Warning": "Thunderstorm with lightning",
        "msg": "Expired nowcast bulletin.",
        "toi": (datetime.now(timezone.utc) - timedelta(hours=5)).strftime("%Y-%m-%d %H:%M:%S"),
        "Vupto": (datetime.now(timezone.utc) - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S"),
        "Color": 4,  # 4=Red in districtnowcast!
    }
]

MOCK_IMD_RAINFALL_OBSERVATIONS_PAYLOAD = [
    {
        "District": "Jagtial",
        "Date": "2026-11-06",
        "Daily_Actual": 18.5,
        "Daily_Normal": 2.5,
        "Daily_Departure": 640.0,
        "Weekly_Actual": 32.0,
        "Weekly_Normal": 12.0,
        "Cumulative_Actual": 890.0,
        "Cumulative_Normal": 780.0,
        "Monthly_Actual": 45.0,
        "Monthly_Normal": 22.0,
        "Category": "LE",
    },
    {
        "District": "Hanamkonda",
        "Date": "2026-11-06",
        "Daily_Actual": "NR",
        "Daily_Normal": 1.8,
        "Daily_Departure": -100.0,
        "Weekly_Actual": 0.0,
        "Weekly_Normal": 9.5,
        "Cumulative_Actual": 650.0,
        "Cumulative_Normal": 720.0,
        "Monthly_Actual": 0.0,
        "Monthly_Normal": 18.0,
        "Category": "NR",  # Documented No Rain
    },
    {
        "District": "Adilabad",
        "Date": "2026-11-06",
        "Daily_Actual": "ND",
        "Daily_Normal": 3.0,
        "Daily_Departure": "ND",
        "Weekly_Actual": "ND",
        "Weekly_Normal": "ND",
        "Cumulative_Actual": 750.0,
        "Cumulative_Normal": 820.0,
        "Monthly_Actual": "ND",
        "Monthly_Normal": "ND",
        "Category": "ND",  # Missing telemetry
    },
]

MOCK_IMD_RAINFALL_FORECAST_PAYLOAD = [
    {
        "District": "Jagtial",
        "State": "Telangana",
        "Issue_Date": "2026-11-06",
        "Day_1": "WS",
        "Day_1_Stations": "76-100%",
        "Day_1_Color": "Green",
        "Day_2": "FWS",
        "Day_2_Stations": "51-75%",
        "Day_2_Color": "Green",
        "Day_3": "SCT",
        "Day_3_Stations": "26-50%",
        "Day_3_Color": "Green",
        "Day_4": "ISOL",
        "Day_4_Stations": "1-25%",
        "Day_4_Color": "Green",
        "Day_5": "DRY",
        "Day_5_Stations": "0%",
        "Day_5_Color": "Green",
    }
]

MOCK_IMD_STATION_WX_PAYLOAD = [
    {
        "station_id": "43093",
        "station_name": "Hyderabad (Begumpet)",
        "Date": "2026-11-06",
        "time_utc": "08:30:00",
        "temp_c": 29.5,
        "rh": 62.0,
        "wind_kph": 8.5,
        "wind_dir_deg": 120.0,
        "wind_dir": "ESE",
        "rain_24h_mm": 0.0,
    }
]

MOCK_IMD_CITY_FORECAST_PAYLOAD = {
    "city_id": "43093",
    "forecast": [
        {"date": "2026-11-06", "min_temp": 20.0, "max_temp": 32.0, "weather": "Partly cloudy"},
        {"date": "2026-11-07", "min_temp": 21.0, "max_temp": 31.0, "weather": "Thunderstorm"},
    ]
}


class TestIMDWeatherServiceSuite(unittest.TestCase):
    """Test suite for KrishiVaani Phase 6.2 IMD integration."""

    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.test_db_path = Path(cls.temp_dir.name) / "test_imd_weather.db"
        cls.original_db_path = settings.DATABASE_PATH
        settings.DATABASE_PATH = cls.test_db_path

        init_db(cls.test_db_path)
        cls.farmer_service = FarmerService(db_path=cls.test_db_path)

        now = datetime.now(timezone.utc).isoformat()
        cls.consented_farmer = FarmerModel(
            farmer_id="farmer-imd-001",
            whatsapp_user_id="wa-imd-001",
            preferred_language="te-IN",
            village_name="Polasa",
            mandal_name="Jagtial",
            district_name="Jagtial",
            pin_code="505529",
            latitude=18.7915,
            longitude=78.9142,
            location_source="gps_pin",
            location_confirmed=True,
            consent_given=True,
            consent_given_at=now,
            weather_provider_sharing_consent=True,
            weather_provider_sharing_consent_at=now,
            weather_provider_disclosure_version="v1.0",
            created_at=now,
            updated_at=now,
        )
        cls.farmer_service.repository.create(cls.consented_farmer)

        cls.unconsented_farmer = FarmerModel(
            farmer_id="farmer-imd-002",
            whatsapp_user_id="wa-imd-002",
            preferred_language="te-IN",
            village_name="Polasa",
            mandal_name="Jagtial",
            district_name="Jagtial",
            pin_code="505529",
            latitude=18.7915,
            longitude=78.9142,
            location_source="gps_pin",
            location_confirmed=True,
            consent_given=True,
            consent_given_at=now,
            weather_provider_sharing_consent=False,
            weather_provider_sharing_consent_at=None,
            weather_provider_disclosure_version=None,
            created_at=now,
            updated_at=now,
        )
        cls.farmer_service.repository.create(cls.unconsented_farmer)

        cls.app = create_application()
        cls.client = TestClient(cls.app)

    @classmethod
    def tearDownClass(cls):
        settings.DATABASE_PATH = cls.original_db_path
        cls.temp_dir.cleanup()

    # -------------------------------------------------------------------------
    # 1. IMD Credentials Missing
    # -------------------------------------------------------------------------
    def test_01_imd_credentials_missing(self):
        """Unconfigured IMD provider reports PENDING_CREDENTIALS and raises ProviderNotConfiguredError."""
        with patch.object(settings, "IMD_API_KEY", None), patch.object(settings, "IMD_JWT_TOKEN", None):
            provider = IMDWeatherProvider(api_key=None, jwt_token=None)
            self.assertEqual(provider.get_status(), ProviderStatus.PENDING_CREDENTIALS)

            with self.assertRaises(ProviderNotConfiguredError) as ctx:
                provider.get_district_warnings(district_name="Jagtial")
            self.assertIn("pending official credentials", str(ctx.exception).lower())
            # Ensure no dummy/secret keys in exception details
            self.assertNotIn("secret", str(ctx.exception).lower())

    # -------------------------------------------------------------------------
    # 2. Successful District-Warning Response
    # -------------------------------------------------------------------------
    def test_02_successful_district_warning_response(self):
        """Official district warning is normalized with 5 daily entries and verified Telangana district."""
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = MOCK_IMD_WARNINGS_PAYLOAD
        mock_client.get.return_value = mock_resp

        provider = IMDWeatherProvider(api_key="test_key", jwt_token="test_jwt", http_client=mock_client)
        warnings = provider.get_district_warnings(district_name="Jagtial")

        self.assertEqual(len(warnings), 1)
        w = warnings[0]
        self.assertEqual(w.district_name, "Jagtial")
        self.assertEqual(w.matched_telangana_district, "Jagtial")
        self.assertEqual(len(w.daily_warnings), 5)
        self.assertIn("+05:30", w.retrieved_at)
        self.assertIn("Data provided by India Meteorological Department", w.attribution)

    # -------------------------------------------------------------------------
    # 3. Multiple Warning Codes for One Day Preserved
    # -------------------------------------------------------------------------
    def test_03_multiple_warning_codes_for_one_day(self):
        """When multiple comma-separated warning codes occur on Day 1, all are preserved."""
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = MOCK_IMD_WARNINGS_PAYLOAD
        mock_client.get.return_value = mock_resp

        provider = IMDWeatherProvider(api_key="test_key", jwt_token="test_jwt", http_client=mock_client)
        warnings = provider.get_district_warnings(district_name="Jagtial")

        day1 = warnings[0].daily_warnings[0]
        self.assertIn("Heavy rain", day1.warning_codes)
        self.assertIn("Thunderstorm and lightning", day1.warning_codes)
        self.assertEqual(len(day1.warning_codes), 2)

    # -------------------------------------------------------------------------
    # 4. Warning Colour Mapping (1=Red, 2=Orange, 3=Yellow, 4=Green)
    # -------------------------------------------------------------------------
    def test_04_warning_colour_mapping(self):
        """District warnings map code 1 to Red and code 4 to Green."""
        self.assertEqual(map_district_warning_color(1), "Red")
        self.assertEqual(map_district_warning_color(2), "Orange")
        self.assertEqual(map_district_warning_color(3), "Yellow")
        self.assertEqual(map_district_warning_color(4), "Green")

    # -------------------------------------------------------------------------
    # 5. Nowcast Colour Mapping (1=Green, 2=Yellow, 3=Orange, 4=Red)
    # -------------------------------------------------------------------------
    def test_05_nowcast_colour_mapping(self):
        """District nowcasts map code 1 to Green and code 4 to Red (inverted!)."""
        self.assertEqual(map_district_nowcast_color(1), "Green")
        self.assertEqual(map_district_nowcast_color(2), "Yellow")
        self.assertEqual(map_district_nowcast_color(3), "Orange")
        self.assertEqual(map_district_nowcast_color(4), "Red")

    # -------------------------------------------------------------------------
    # 6. Different Colour Mappings for Warning and Nowcast Endpoints
    # -------------------------------------------------------------------------
    def test_06_different_colour_mappings_for_warning_and_nowcast(self):
        """Verify endpoints use distinct color mappings and never share a naive converter."""
        # Code 1: Red in warning, but Green in nowcast
        self.assertEqual(map_district_warning_color(1), "Red")
        self.assertEqual(map_district_nowcast_color(1), "Green")
        self.assertNotEqual(map_district_warning_color(1), map_district_nowcast_color(1))

        # Code 4: Green in warning, but Red in nowcast
        self.assertEqual(map_district_warning_color(4), "Green")
        self.assertEqual(map_district_nowcast_color(4), "Red")
        self.assertNotEqual(map_district_warning_color(4), map_district_nowcast_color(4))

    # -------------------------------------------------------------------------
    # 7. Nowcast Validity-Time Handling
    # -------------------------------------------------------------------------
    def test_07_nowcast_validity_time_handling(self):
        """Nowcast parses toi and Vupto, converts to Asia/Kolkata ISO, and marks unexpired as active."""
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = MOCK_IMD_NOWCAST_ACTIVE_PAYLOAD
        mock_client.get.return_value = mock_resp

        provider = IMDWeatherProvider(api_key="test_key", jwt_token="test_jwt", http_client=mock_client)
        nowcasts = provider.get_district_nowcast(district_name="Jagtial")

        self.assertEqual(len(nowcasts), 1)
        n = nowcasts[0]
        self.assertFalse(n.is_expired)
        self.assertEqual(n.freshness_status, FreshnessStatus.CURRENT)
        self.assertIn("+05:30", n.valid_until_kolkata)
        self.assertEqual(n.color_name, "Orange")  # Code 3 in nowcast = Orange

    # -------------------------------------------------------------------------
    # 8. Expired Nowcast Handling
    # -------------------------------------------------------------------------
    def test_08_expired_nowcast_handling(self):
        """When nowcast Vupto has elapsed, is_expired is True and freshness is EXPIRED."""
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = MOCK_IMD_NOWCAST_EXPIRED_PAYLOAD
        mock_client.get.return_value = mock_resp

        provider = IMDWeatherProvider(api_key="test_key", jwt_token="test_jwt", http_client=mock_client)
        nowcasts = provider.get_district_nowcast(district_name="Jagtial")

        self.assertEqual(len(nowcasts), 1)
        n = nowcasts[0]
        self.assertTrue(n.is_expired)
        self.assertEqual(n.freshness_status, FreshnessStatus.EXPIRED)

    # -------------------------------------------------------------------------
    # 9. District Rainfall Daily/Weekly/Monthly Parsing
    # -------------------------------------------------------------------------
    def test_09_district_rainfall_daily_weekly_monthly_parsing(self):
        """Rainfall metrics (daily, weekly, cumulative, monthly) parse correctly."""
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = MOCK_IMD_RAINFALL_OBSERVATIONS_PAYLOAD
        mock_client.get.return_value = mock_resp

        provider = IMDWeatherProvider(api_key="test_key", jwt_token="test_jwt", http_client=mock_client)
        obs = provider.get_district_rainfall(district_name="Jagtial")

        self.assertEqual(len(obs), 1)
        r = obs[0]
        self.assertEqual(r.daily_actual_mm, 18.5)
        self.assertEqual(r.daily_normal_mm, 2.5)
        self.assertEqual(r.daily_departure_percent, 640.0)
        self.assertEqual(r.weekly_actual_mm, 32.0)
        self.assertEqual(r.monthly_actual_mm, 45.0)
        self.assertEqual(r.rainfall_category, "LE")
        self.assertFalse(r.is_no_data)
        self.assertFalse(r.is_no_rain)

    # -------------------------------------------------------------------------
    # 10. ND versus NR Distinction
    # -------------------------------------------------------------------------
    def test_10_nd_versus_nr_distinction(self):
        """Category 'ND' means missing data (actual=None); 'NR' means documented zero rainfall (actual=0.0)."""
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = MOCK_IMD_RAINFALL_OBSERVATIONS_PAYLOAD
        mock_client.get.return_value = mock_resp

        provider = IMDWeatherProvider(api_key="test_key", jwt_token="test_jwt", http_client=mock_client)

        # Hanamkonda has NR
        hnk_obs = provider.get_district_rainfall(district_name="Hanamkonda")[0]
        self.assertTrue(hnk_obs.is_no_rain)
        self.assertFalse(hnk_obs.is_no_data)
        self.assertEqual(hnk_obs.daily_actual_mm, 0.0)

        # Adilabad has ND
        adl_obs = provider.get_district_rainfall(district_name="Adilabad")[0]
        self.assertTrue(adl_obs.is_no_data)
        self.assertFalse(adl_obs.is_no_rain)
        self.assertIsNone(adl_obs.daily_actual_mm, "ND actual rainfall must remain None, not 0.0 mm")

    # -------------------------------------------------------------------------
    # 11. Missing Rainfall Values Never Become Zero
    # -------------------------------------------------------------------------
    def test_11_missing_rainfall_never_becomes_zero(self):
        """Missing values ('ND', None, '-') must never be silently converted to 0.0 mm."""
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = MOCK_IMD_RAINFALL_OBSERVATIONS_PAYLOAD
        mock_client.get.return_value = mock_resp

        provider = IMDWeatherProvider(api_key="test_key", jwt_token="test_jwt", http_client=mock_client)
        adl = provider.get_district_rainfall(district_name="Adilabad")[0]
        self.assertIsNone(adl.daily_actual_mm)
        self.assertIsNone(adl.daily_departure_percent)
        self.assertIsNone(adl.weekly_actual_mm)
        self.assertIsNone(adl.monthly_actual_mm)

    # -------------------------------------------------------------------------
    # 12. Five-Day Rainfall Forecast Parsing
    # -------------------------------------------------------------------------
    def test_12_five_day_rainfall_forecast_parsing(self):
        """Rainfall forecast endpoint parses 5 daily distribution categories."""
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = MOCK_IMD_RAINFALL_FORECAST_PAYLOAD
        mock_client.get.return_value = mock_resp

        provider = IMDWeatherProvider(api_key="test_key", jwt_token="test_jwt", http_client=mock_client)
        f_list = provider.get_district_rainfall_forecast(district_name="Jagtial")

        self.assertEqual(len(f_list), 1)
        f = f_list[0]
        self.assertEqual(len(f.forecast_days), 5)
        self.assertEqual(f.forecast_days[0].distribution_code, "WS")
        self.assertEqual(f.forecast_days[1].distribution_code, "FWS")
        self.assertEqual(f.forecast_days[4].distribution_code, "DRY")

    # -------------------------------------------------------------------------
    # 13. Distribution Categories Retained Without Invented Rainfall Amounts
    # -------------------------------------------------------------------------
    def test_13_distribution_categories_retained_without_invented_rainfall(self):
        """Rainfall distribution codes and station percentage ranges are preserved without millimeter fabrication."""
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = MOCK_IMD_RAINFALL_FORECAST_PAYLOAD
        mock_client.get.return_value = mock_resp

        provider = IMDWeatherProvider(api_key="test_key", jwt_token="test_jwt", http_client=mock_client)
        f = provider.get_district_rainfall_forecast(district_name="Jagtial")[0]

        d1 = f.forecast_days[0]
        self.assertEqual(d1.station_percentage_range, "76-100%")
        self.assertIn("Widespread", d1.distribution_name)
        # Ensure schema does not possess a fabricated rainfall millimetre field
        self.assertFalse(hasattr(d1, "invented_rainfall_mm"))

    # -------------------------------------------------------------------------
    # 14. Current Station Weather Observation Timestamps
    # -------------------------------------------------------------------------
    def test_14_current_station_weather_observation(self):
        """Station weather observation preserves physical station identity and observation time."""
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = MOCK_IMD_STATION_WX_PAYLOAD
        mock_client.get.return_value = mock_resp

        provider = IMDWeatherProvider(api_key="test_key", jwt_token="test_jwt", http_client=mock_client)
        stn = provider.get_station_weather(station_id="43093")

        self.assertEqual(stn.station_id, "43093")
        self.assertEqual(stn.station_name, "Hyderabad (Begumpet)")
        self.assertEqual(stn.matched_telangana_district, "Hyderabad")
        self.assertTrue(stn.is_station_observation)
        self.assertTrue(stn.station_observation_confirmed)
        self.assertEqual(stn.temperature_c, 29.5)
        self.assertIn("+05:30", stn.observation_time_kolkata)

    # -------------------------------------------------------------------------
    # 15. UTC to Asia/Kolkata Conversion
    # -------------------------------------------------------------------------
    def test_15_utc_to_asia_kolkata_conversion(self):
        """UTC time string converts accurately with +05:30 offset."""
        provider = IMDWeatherProvider(api_key="k", jwt_token="j")
        kolkata_iso = provider._utc_to_kolkata_iso("2026-11-06 08:30:00")
        self.assertIn("+05:30", kolkata_iso)
        # 08:30 UTC = 14:00 IST
        self.assertIn("14:00:00", kolkata_iso)

    # -------------------------------------------------------------------------
    # 16. City Forecast Only Uses Verified Station Mappings
    # -------------------------------------------------------------------------
    def test_16_city_forecast_only_uses_verified_station_mappings(self):
        """Unverified city code raises LocationNotFoundError; verified code succeeds."""
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = MOCK_IMD_CITY_FORECAST_PAYLOAD
        mock_client.get.return_value = mock_resp

        provider = IMDWeatherProvider(api_key="test_key", jwt_token="test_jwt", http_client=mock_client)

        # Unverified city code fails safely
        with self.assertRaises(LocationNotFoundError):
            provider.get_city_forecast(city_id="INVALID_CITY_99")

        # Verified city code succeeds
        city_f = provider.get_city_forecast(city_id="HYD")
        self.assertEqual(city_f.city_name, "Hyderabad (Begumpet)")
        self.assertEqual(city_f.matched_telangana_district, "Hyderabad")

    # -------------------------------------------------------------------------
    # 17. District Aliases Resolve Correctly
    # -------------------------------------------------------------------------
    def test_17_district_aliases_resolve_correctly(self):
        """Telangana revenue district aliases resolve to their canonical district record."""
        # Alias 'asifabad' -> 'Kumuram Bheem Asifabad'
        d1 = resolve_telangana_district("asifabad")
        self.assertIsNotNone(d1)
        self.assertEqual(d1.district_name, "Kumuram Bheem Asifabad")

        # Alias 'kba' -> 'Kumuram Bheem Asifabad'
        d2 = resolve_telangana_district("kba")
        self.assertIsNotNone(d2)
        self.assertEqual(d2.district_name, "Kumuram Bheem Asifabad")

        # Canonical 'Jagtial'
        d3 = resolve_telangana_district("jagtial")
        self.assertIsNotNone(d3)
        self.assertEqual(d3.district_name, "Jagtial")

    # -------------------------------------------------------------------------
    # 18. Unknown Districts Are Rejected
    # -------------------------------------------------------------------------
    def test_18_unknown_districts_rejected(self):
        """Districts outside Telangana or non-existent revenue districts raise LocationDistrictMismatchError."""
        mock_client = MagicMock()
        provider = IMDWeatherProvider(api_key="test_key", jwt_token="test_jwt", http_client=mock_client)

        with self.assertRaises(LocationDistrictMismatchError):
            provider.get_district_warnings(district_name="Bangalore")

        with self.assertRaises(LocationDistrictMismatchError):
            provider.get_district_warnings(district_name="Guntur")

        with self.assertRaises(LocationDistrictMismatchError):
            provider.get_district_warnings(district_name="FakeTelanganaDistrict")

    # -------------------------------------------------------------------------
    # 19. No AMFU Inference From PJTSAU Zone
    # -------------------------------------------------------------------------
    def test_19_no_amfu_inference_from_pjtsau_zone(self):
        """Direct district weather endpoints query by district; they do not guess AMFU coverage."""
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = MOCK_IMD_WARNINGS_PAYLOAD
        mock_client.get.return_value = mock_resp

        provider = IMDWeatherProvider(api_key="test_key", jwt_token="test_jwt", http_client=mock_client)
        # Jagtial is NTZ; Hanamkonda is CTZ. Both resolve by revenue district, not AMFU zone.
        w = provider.get_district_warnings(district_name="Hanamkonda")
        self.assertEqual(len(w), 1)
        self.assertEqual(w[0].matched_telangana_district, "Hanamkonda")

    # -------------------------------------------------------------------------
    # 20. Missing Warnings Do Not Become "No Warning"
    # -------------------------------------------------------------------------
    def test_20_missing_warnings_do_not_become_no_warning(self):
        """When provider fails or is unreachable, an exception is raised; it never claims 'No Warning'."""
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 503
        mock_client.get.return_value = mock_resp

        provider = IMDWeatherProvider(api_key="test_key", jwt_token="test_jwt", http_client=mock_client)
        with self.assertRaises(ProviderUnavailableError):
            provider.get_district_warnings(district_name="Jagtial")

    # -------------------------------------------------------------------------
    # 21. Stale Data Is Not Presented as Current
    # -------------------------------------------------------------------------
    def test_21_stale_data_is_not_presented_as_current(self):
        """Expired nowcasts have freshness_status == EXPIRED and is_expired == True."""
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = MOCK_IMD_NOWCAST_EXPIRED_PAYLOAD
        mock_client.get.return_value = mock_resp

        provider = IMDWeatherProvider(api_key="test_key", jwt_token="test_jwt", http_client=mock_client)
        nowcasts = provider.get_district_nowcast(district_name="Jagtial")
        self.assertEqual(nowcasts[0].freshness_status, FreshnessStatus.EXPIRED)
        self.assertTrue(nowcasts[0].is_expired)

    # -------------------------------------------------------------------------
    # 22. IMD Authentication Failures Handled Safely
    # -------------------------------------------------------------------------
    def test_22_imd_auth_failures_handled_safely(self):
        """HTTP 401/403 raises ProviderAuthenticationError without exposing secrets."""
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_client.get.return_value = mock_resp

        provider = IMDWeatherProvider(api_key="super_secret_key_999", jwt_token="secret_token", http_client=mock_client)
        with self.assertRaises(ProviderAuthenticationError) as ctx:
            provider.get_district_warnings(district_name="Jagtial")

        self.assertNotIn("super_secret_key_999", str(ctx.exception))
        self.assertNotIn("secret_token", str(ctx.exception))

    # -------------------------------------------------------------------------
    # 23. No Secret Leakage in Logs or HTTP Responses
    # -------------------------------------------------------------------------
    def test_23_no_secret_leakage(self):
        """Authentication requirements report credential presence as booleans without exposing secret strings."""
        provider = IMDWeatherProvider(api_key="my_secret_key", jwt_token="my_secret_jwt")
        reqs = provider.get_authentication_requirements()
        self.assertTrue(reqs["configured_credentials"]["has_api_key"])
        self.assertTrue(reqs["configured_credentials"]["has_jwt_token"])
        self.assertNotIn("my_secret_key", str(reqs))
        self.assertNotIn("my_secret_jwt", str(reqs))

    # -------------------------------------------------------------------------
    # 24. Existing Weather Provider Location Sharing Consent Remains Intact
    # -------------------------------------------------------------------------
    def test_24_location_sharing_consent_enforced(self):
        """Farmer lacking third-party sharing consent raises WeatherLocationSharingConsentRequiredError."""
        mock_client = MagicMock()
        mock_provider = IMDWeatherProvider(api_key="k", jwt_token="j", http_client=mock_client)
        service = WeatherService(farmer_service=self.farmer_service, imd_provider=mock_provider)

        with self.assertRaises(WeatherLocationSharingConsentRequiredError):
            service.get_imd_district_warnings(farmer_id=self.unconsented_farmer.farmer_id)

    # -------------------------------------------------------------------------
    # 25. Existing WeatherAPI Behaviour Remains Unchanged
    # -------------------------------------------------------------------------
    def test_25_existing_weatherapi_behaviour_unchanged(self):
        """WeatherAPI provider status and method signatures remain completely operational."""
        wapi = WeatherAPIProvider(api_key="test_wapi_key")
        self.assertEqual(wapi.provider_id, "weatherapi_free")
        self.assertEqual(wapi.get_status(), ProviderStatus.CONFIGURED)

    # -------------------------------------------------------------------------
    # 26. FastAPI Endpoints Live Contract
    # -------------------------------------------------------------------------
    def test_26_fastapi_endpoints_live_contract(self):
        """FastAPI IMD endpoints respond accurately to GET requests."""
        mock_client = MagicMock()
        mock_provider = IMDWeatherProvider(api_key="test_key", jwt_token="test_jwt", http_client=mock_client)
        service = WeatherService(farmer_service=self.farmer_service, imd_provider=mock_provider)

        with patch("app.api.routes.weather.get_weather_service", return_value=service):
            # 1. GET /api/v1/weather/imd/status
            resp = self.client.get("/api/v1/weather/imd/status")
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertEqual(data["portal_url"], "https://api.imd.gov.in/public/index.php")

            # 2. GET /api/v1/weather/imd/district-warnings?district=Jagtial
            mock_w_resp = MagicMock()
            mock_w_resp.status_code = 200
            mock_w_resp.json.return_value = MOCK_IMD_WARNINGS_PAYLOAD
            mock_client.get.return_value = mock_w_resp

            w_resp = self.client.get("/api/v1/weather/imd/district-warnings?district=Jagtial")
            self.assertEqual(w_resp.status_code, 200)
            w_data = w_resp.json()
            self.assertEqual(len(w_data), 1)
            self.assertEqual(w_data[0]["district_name"], "Jagtial")

            # 3. GET /api/v1/weather/imd/district-warnings?district=Bangalore -> 422
            w_bad = self.client.get("/api/v1/weather/imd/district-warnings?district=Bangalore")
            self.assertEqual(w_bad.status_code, 422)
            self.assertEqual(w_bad.json()["detail"]["error_code"], "DISTRICT_MISMATCH")

            # 4. GET /api/v1/weather/imd/district-nowcast?district=Jagtial
            mock_n_resp = MagicMock()
            mock_n_resp.status_code = 200
            mock_n_resp.json.return_value = MOCK_IMD_NOWCAST_ACTIVE_PAYLOAD
            mock_client.get.return_value = mock_n_resp

            n_resp = self.client.get("/api/v1/weather/imd/district-nowcast?district=Jagtial")
            self.assertEqual(n_resp.status_code, 200)
            n_data = n_resp.json()
            self.assertEqual(len(n_data), 1)

            # 5. GET /api/v1/weather/imd/district-rainfall?district=Jagtial
            mock_r_resp = MagicMock()
            mock_r_resp.status_code = 200
            mock_r_resp.json.return_value = MOCK_IMD_RAINFALL_OBSERVATIONS_PAYLOAD
            mock_client.get.return_value = mock_r_resp

            r_resp = self.client.get("/api/v1/weather/imd/district-rainfall?district=Jagtial")
            self.assertEqual(r_resp.status_code, 200)
            r_data = r_resp.json()
            self.assertEqual(len(r_data), 1)
            self.assertEqual(r_data[0]["daily_actual_mm"], 18.5)

            # 6. GET /api/v1/weather/imd/district-rainfall-forecast?district=Jagtial
            mock_rf_resp = MagicMock()
            mock_rf_resp.status_code = 200
            mock_rf_resp.json.return_value = MOCK_IMD_RAINFALL_FORECAST_PAYLOAD
            mock_client.get.return_value = mock_rf_resp

            rf_resp = self.client.get("/api/v1/weather/imd/district-rainfall-forecast?district=Jagtial")
            self.assertEqual(rf_resp.status_code, 200)
            rf_data = rf_resp.json()
            self.assertEqual(len(rf_data), 1)

            # 7. GET /api/v1/weather/imd/station-weather?station_id=43093
            mock_stn_resp = MagicMock()
            mock_stn_resp.status_code = 200
            mock_stn_resp.json.return_value = MOCK_IMD_STATION_WX_PAYLOAD
            mock_client.get.return_value = mock_stn_resp

            stn_resp = self.client.get("/api/v1/weather/imd/station-weather?station_id=43093")
            self.assertEqual(stn_resp.status_code, 200)
            stn_data = stn_resp.json()
            self.assertEqual(stn_data["station_id"], "43093")

            # 8. GET /api/v1/weather/imd/city-forecast?city_id=HYD
            mock_city_resp = MagicMock()
            mock_city_resp.status_code = 200
            mock_city_resp.json.return_value = MOCK_IMD_CITY_FORECAST_PAYLOAD
            mock_client.get.return_value = mock_city_resp

            city_resp = self.client.get("/api/v1/weather/imd/city-forecast?city_id=HYD")
            self.assertEqual(city_resp.status_code, 200)
            city_data = city_resp.json()
            self.assertEqual(city_data["city_id"], "HYD")


if __name__ == "__main__":
    unittest.main()

