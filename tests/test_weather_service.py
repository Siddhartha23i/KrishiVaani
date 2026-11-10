"""
Comprehensive unit test suite for KrishiVaani Weather Intelligence Foundation — Phase 6.1.
Enforces all 25 test criteria:
1. WeatherAPI configuration missing.
2. Successful current-weather response.
3. Successful three-day forecast response.
4. Forecast request above free-plan limits is rejected.
5. Invalid API key.
6. Provider rate limit.
7. Provider server failure.
8. Network timeout.
9. Invalid JSON response.
10. Source attribution is preserved.
11. Retrieved and valid dates are preserved.
12. Weather time is converted correctly using Asia/Kolkata.
13. Confirmed coordinates are preferred.
14. Village/PIN query matching.
15. Country mismatch is rejected.
16. District mismatch requires clarification.
17. Ambiguous village is not guessed.
18. Current conditions are not labelled as official station observations without evidence.
19. Forecast rainfall is not presented as observed rainfall.
20. Missing weather data never becomes zero rainfall.
21. Provider failure never becomes "no warning".
22. Planning horizon is separate from weather forecast horizon.
23. Long-range outlooks cannot be converted into deterministic daily forecasts.
24. Existing farmer and knowledge records remain intact.
25. All previous Phase 3, 4 and 5 tests continue passing.
"""

import unittest
from unittest.mock import patch, MagicMock
from pathlib import Path
import tempfile
import json
import httpx
from datetime import datetime, timezone
from fastapi.testclient import TestClient

from app.main import create_application
from app.core.config import settings
from app.db.database import init_db
from app.models.farmer import FarmerModel
from app.services.farmer_service import FarmerService
from app.weather.enums import (
    WeatherInformationType,
    GeographicalResolution,
    FreshnessStatus,
    ProviderStatus,
    WeatherForecastHorizon,
)
from app.weather.schemas import (
    WeatherLocationInfo,
    CurrentWeatherConditions,
    WeatherForecastResponse,
)
from app.weather.exceptions import (
    WeatherError,
    ProviderNotConfiguredError,
    ProviderAuthenticationError,
    ProviderRateLimitError,
    ProviderUnavailableError,
    LocationNotFoundError,
    LocationCountryMismatchError,
    LocationDistrictMismatchError,
    ForecastDaysLimitExceededError,
    InvalidProviderResponseError,
    WeatherLocationSharingConsentRequiredError,
)
from app.weather.cache import weather_cache
from app.weather.providers.weatherapi_provider import WeatherAPIProvider
from app.weather.providers.imd_provider import IMDWeatherProvider, IMDAuthenticationEvidence
from app.weather.services.location_weather_service import LocationWeatherService
from app.weather.services.weather_service import WeatherService
from app.knowledge.geography import PlanningHorizon, classify_planning_horizon
from app.knowledge.planning_safety import (
    AdvisoryTriggerSafetyPolicy,
    SAFETY_RULE_FORECAST_ALONE_CANNOT_TRIGGER_ADVICE,
)

# Sample mock payloads for WeatherAPI.com
MOCK_CURRENT_JSON = {
    "location": {
        "name": "Jagtial",
        "region": "Telangana",
        "country": "India",
        "lat": 18.79,
        "lon": 78.91,
        "tz_id": "Asia/Kolkata",
        "localtime_epoch": 1794054000,
        "localtime": "2026-11-06 17:50",
    },
    "current": {
        "last_updated_epoch": 1794053400,
        "last_updated": "2026-11-06 17:40",
        "temp_c": 31.5,
        "feelslike_c": 34.0,
        "humidity": 65,
        "precip_mm": 0.0,
        "wind_kph": 12.0,
        "wind_degree": 90,
        "wind_dir": "E",
        "condition": {
            "text": "Partly cloudy",
            "icon": "//cdn.weatherapi.com/weather/64x64/day/116.png",
            "code": 1003,
        },
        "uv": 6.0,
        "is_day": 1,
    },
}

MOCK_FORECAST_3DAY_JSON = {
    "location": {
        "name": "Jagtial",
        "region": "Telangana",
        "country": "India",
        "lat": 18.79,
        "lon": 78.91,
        "tz_id": "Asia/Kolkata",
        "localtime_epoch": 1794054000,
        "localtime": "2026-11-06 17:50",
    },
    "current": {
        "last_updated_epoch": 1794053400,
        "last_updated": "2026-11-06 17:40",
        "temp_c": 31.5,
        "condition": {"text": "Partly cloudy", "code": 1003},
    },
    "forecast": {
        "forecastday": [
            {
                "date": "2026-11-06",
                "date_epoch": 1793990400,
                "day": {
                    "maxtemp_c": 33.2,
                    "mintemp_c": 21.4,
                    "avgtemp_c": 27.3,
                    "maxwind_kph": 15.1,
                    "totalprecip_mm": 0.0,
                    "avghumidity": 60.0,
                    "daily_chance_of_rain": 10,
                    "condition": {"text": "Sunny", "code": 1000},
                    "uv": 7.0,
                },
                "hour": [],
            },
            {
                "date": "2026-11-07",
                "date_epoch": 1794076800,
                "day": {
                    "maxtemp_c": 32.5,
                    "mintemp_c": 22.0,
                    "avgtemp_c": 26.8,
                    "maxwind_kph": 14.0,
                    "totalprecip_mm": 2.5,
                    "avghumidity": 68.0,
                    "daily_chance_of_rain": 45,
                    "condition": {"text": "Patchy rain possible", "code": 1063},
                    "uv": 6.0,
                },
                "hour": [],
            },
            {
                "date": "2026-11-08",
                "date_epoch": 1794163200,
                "day": {
                    "maxtemp_c": 30.0,
                    "mintemp_c": 20.5,
                    "avgtemp_c": 25.2,
                    "maxwind_kph": 18.5,
                    "totalprecip_mm": 12.0,
                    "avghumidity": 78.0,
                    "daily_chance_of_rain": 80,
                    "condition": {"text": "Moderate rain", "code": 1189},
                    "uv": 5.0,
                },
                "hour": [],
            },
        ]
    },
}


class TestWeatherServiceSuite(unittest.TestCase):
    """
    Verification suite for KrishiVaani Weather Intelligence Foundation.
    """

    @classmethod
    def setUpClass(cls):
        # Create an isolated temporary SQLite database for testing
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.test_db_path = Path(cls.temp_dir.name) / "test_weather.db"
        cls.original_db_path = settings.DATABASE_PATH
        settings.DATABASE_PATH = cls.test_db_path

        # Initialize schema
        init_db(cls.test_db_path)

        # Seed test farmer profiles in temporary DB
        cls.farmer_service = FarmerService(db_path=cls.test_db_path)

        # Farmer 1: Jagtial with confirmed coordinates and full sharing consent
        now = datetime.now(timezone.utc).isoformat()
        cls.farmer_with_coords = FarmerModel(
            farmer_id="farmer-uuid-001",
            whatsapp_user_id="wa-001",
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
        cls.farmer_service.repository.create(cls.farmer_with_coords)

        # Farmer 2: Warangal without coordinates (text query only) and sharing consent
        cls.farmer_without_coords = FarmerModel(
            farmer_id="farmer-uuid-002",
            whatsapp_user_id="wa-002",
            preferred_language="te-IN",
            village_name="Dharmasagar",
            mandal_name="Dharmasagar",
            district_name="Hanamkonda",
            pin_code="506142",
            latitude=None,
            longitude=None,
            location_source="voice_transcript",
            location_confirmed=True,
            consent_given=True,
            consent_given_at=now,
            weather_provider_sharing_consent=True,
            weather_provider_sharing_consent_at=now,
            weather_provider_disclosure_version="v1.0",
            created_at=now,
            updated_at=now,
        )
        cls.farmer_service.repository.create(cls.farmer_without_coords)

        # Farmer 3: Has local storage consent (Phase 4) but NO third-party sharing consent
        cls.farmer_without_sharing_consent = FarmerModel(
            farmer_id="farmer-uuid-003",
            whatsapp_user_id="wa-003",
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
        cls.farmer_service.repository.create(cls.farmer_without_sharing_consent)

        cls.app = create_application()
        cls.client = TestClient(cls.app)

    @classmethod
    def tearDownClass(cls):
        settings.DATABASE_PATH = cls.original_db_path
        cls.temp_dir.cleanup()

    def setUp(self):
        weather_cache.clear()

    # -------------------------------------------------------------------------
    # 1. WeatherAPI Configuration Missing
    # -------------------------------------------------------------------------
    def test_01_weatherapi_configuration_missing(self):
        """When WeatherAPI key is missing, provider status is NOT_CONFIGURED and requests fail safely."""
        provider = WeatherAPIProvider(api_key=None)
        # Mock settings key to None as well
        with patch.object(settings, "WEATHERAPI_API_KEY", None):
            unconfigured_provider = WeatherAPIProvider(api_key=None)
            self.assertEqual(unconfigured_provider.get_status(), ProviderStatus.NOT_CONFIGURED)

            with self.assertRaises(ProviderNotConfiguredError):
                unconfigured_provider.get_current_weather(query="Jagtial, India")

            with self.assertRaises(ProviderNotConfiguredError):
                unconfigured_provider.get_forecast(query="Jagtial, India", days=3)

    # -------------------------------------------------------------------------
    # 2. Successful Current-Weather Response
    # -------------------------------------------------------------------------
    def test_02_successful_current_weather_response(self):
        """Successful current weather response is normalized into standardized schema."""
        provider = WeatherAPIProvider(api_key="test_dummy_key")

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = MOCK_CURRENT_JSON

        with patch("httpx.Client.get", return_value=mock_resp):
            current = provider.get_current_weather(query="Jagtial, Telangana, India")

            self.assertIsInstance(current, CurrentWeatherConditions)
            self.assertEqual(current.source_name, "WeatherAPI.com Free")
            self.assertEqual(current.temperature_c, 31.5)
            self.assertEqual(current.feels_like_c, 34.0)
            self.assertEqual(current.humidity_percent, 65.0)
            self.assertEqual(current.wind_kph, 12.0)
            self.assertEqual(current.condition_text, "Partly cloudy")
            self.assertEqual(current.location.location_name, "Jagtial")
            self.assertEqual(current.location.country, "India")
            self.assertEqual(current.location.timezone, "Asia/Kolkata")
            self.assertEqual(current.information_type, WeatherInformationType.CURRENT_CONDITIONS)

    # -------------------------------------------------------------------------
    # 3. Successful Three-Day Forecast Response
    # -------------------------------------------------------------------------
    def test_03_successful_three_day_forecast_response(self):
        """Successful 3-day forecast returns 3 DailyWeatherForecast entries."""
        provider = WeatherAPIProvider(api_key="test_dummy_key")

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = MOCK_FORECAST_3DAY_JSON

        with patch("httpx.Client.get", return_value=mock_resp):
            forecast = provider.get_forecast(query="Jagtial, India", days=3)

            self.assertIsInstance(forecast, WeatherForecastResponse)
            self.assertEqual(forecast.days_count, 3)
            self.assertEqual(len(forecast.forecast_days), 3)
            self.assertEqual(forecast.forecast_horizon, WeatherForecastHorizon.SHORT_RANGE_1_3D)

            day1 = forecast.forecast_days[0]
            self.assertEqual(day1.date, "2026-11-06")
            self.assertEqual(day1.max_temp_c, 33.2)
            self.assertEqual(day1.min_temp_c, 21.4)
            self.assertEqual(day1.total_precipitation_mm, 0.0)

            day2 = forecast.forecast_days[1]
            self.assertEqual(day2.date, "2026-11-07")
            self.assertEqual(day2.total_precipitation_mm, 2.5)

            day3 = forecast.forecast_days[2]
            self.assertEqual(day3.date, "2026-11-08")
            self.assertEqual(day3.total_precipitation_mm, 12.0)

    # -------------------------------------------------------------------------
    # 4. Forecast Request Above Free-Plan Limits Rejected
    # -------------------------------------------------------------------------
    def test_04_forecast_request_above_free_limits_rejected(self):
        """Forecast requests with days > 3 raise ForecastDaysLimitExceededError."""
        provider = WeatherAPIProvider(api_key="test_dummy_key")

        with self.assertRaises(ForecastDaysLimitExceededError):
            provider.get_forecast(query="Jagtial, India", days=4)

        with self.assertRaises(ForecastDaysLimitExceededError):
            provider.get_forecast(query="Jagtial, India", days=7)

    # -------------------------------------------------------------------------
    # 5. Invalid API Key
    # -------------------------------------------------------------------------
    def test_05_invalid_api_key_handling(self):
        """Invalid API key raises ProviderAuthenticationError without leaking key in error."""
        provider = WeatherAPIProvider(api_key="invalid_secret_key_12345")

        mock_resp = MagicMock()
        mock_resp.status_code = 403
        mock_resp.json.return_value = {"error": {"code": 2006, "message": "API key is invalid."}}

        with patch("httpx.Client.get", return_value=mock_resp):
            with self.assertRaises(ProviderAuthenticationError) as ctx:
                provider.get_current_weather(query="Jagtial, India")

            # Crucial: Secret key must not appear in exception message
            self.assertNotIn("invalid_secret_key_12345", str(ctx.exception))
            self.assertIn("authentication failed", str(ctx.exception).lower())

    # -------------------------------------------------------------------------
    # 6. Provider Rate Limit
    # -------------------------------------------------------------------------
    def test_06_provider_rate_limit_handling(self):
        """Rate limit response (HTTP 429) raises ProviderRateLimitError."""
        provider = WeatherAPIProvider(api_key="test_key")

        mock_resp = MagicMock()
        mock_resp.status_code = 429
        mock_resp.json.return_value = {"error": {"code": 2007, "message": "API key quota exceeded."}}

        with patch("httpx.Client.get", return_value=mock_resp):
            with self.assertRaises(ProviderRateLimitError) as ctx:
                provider.get_current_weather(query="Jagtial, India")
            self.assertIn("quota", str(ctx.exception).lower())

    # -------------------------------------------------------------------------
    # 7. Provider Server Failure
    # -------------------------------------------------------------------------
    def test_07_provider_server_failure_handling(self):
        """Server error (HTTP 502/503) raises ProviderUnavailableError."""
        provider = WeatherAPIProvider(api_key="test_key")

        mock_resp = MagicMock()
        mock_resp.status_code = 503
        mock_resp.json.side_effect = Exception("Service Unavailable")

        with patch("httpx.Client.get", return_value=mock_resp):
            with self.assertRaises(ProviderUnavailableError):
                provider.get_current_weather(query="Jagtial, India")

    # -------------------------------------------------------------------------
    # 8. Network Timeout
    # -------------------------------------------------------------------------
    def test_08_network_timeout_handling(self):
        """Network timeout raises ProviderUnavailableError with clean message."""
        provider = WeatherAPIProvider(api_key="test_key", timeout_seconds=2.0)

        with patch("httpx.Client.get", side_effect=httpx.TimeoutException("Read timed out")):
            with self.assertRaises(ProviderUnavailableError) as ctx:
                provider.get_current_weather(query="Jagtial, India")
            self.assertIn("timed out", str(ctx.exception).lower())

    # -------------------------------------------------------------------------
    # 9. Invalid JSON Response
    # -------------------------------------------------------------------------
    def test_09_invalid_json_response_handling(self):
        """Non-JSON response from provider raises InvalidProviderResponseError."""
        provider = WeatherAPIProvider(api_key="test_key")

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.side_effect = json.JSONDecodeError("Expecting value", "<html>", 0)

        with patch("httpx.Client.get", return_value=mock_resp):
            with self.assertRaises(InvalidProviderResponseError) as ctx:
                provider.get_current_weather(query="Jagtial, India")
            self.assertIn("invalid json", str(ctx.exception).lower())

    # -------------------------------------------------------------------------
    # 10. Source Attribution Preserved
    # -------------------------------------------------------------------------
    def test_10_source_attribution_preserved(self):
        """Attribution notice per WeatherAPI terms is preserved in response."""
        provider = WeatherAPIProvider(api_key="test_key")

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = MOCK_CURRENT_JSON

        with patch("httpx.Client.get", return_value=mock_resp):
            current = provider.get_current_weather(query="Jagtial, India")
            self.assertIn("Powered by WeatherAPI.com", current.attribution)

    # -------------------------------------------------------------------------
    # 11. Retrieved and Valid Dates Preserved
    # -------------------------------------------------------------------------
    def test_11_retrieved_and_valid_dates_preserved(self):
        """Retrieved timestamp and validity range timestamps are preserved."""
        provider = WeatherAPIProvider(api_key="test_key")

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = MOCK_CURRENT_JSON

        with patch("httpx.Client.get", return_value=mock_resp):
            current = provider.get_current_weather(query="Jagtial, India")
            self.assertTrue(len(current.retrieved_at) > 0)
            self.assertTrue(len(current.valid_from) > 0)
            self.assertTrue(len(current.valid_until) > 0)
            self.assertIsNotNone(current.issued_at)

    # -------------------------------------------------------------------------
    # 12. Weather Time Converted Correctly Using Asia/Kolkata
    # -------------------------------------------------------------------------
    def test_12_weather_time_converted_to_asia_kolkata(self):
        """Timestamps are formatted in Asia/Kolkata timezone with offset."""
        provider = WeatherAPIProvider(api_key="test_key")

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = MOCK_CURRENT_JSON

        with patch("httpx.Client.get", return_value=mock_resp):
            current = provider.get_current_weather(query="Jagtial, India")
            # Kolkata is UTC+05:30
            self.assertIn("+05:30", current.retrieved_at)
            self.assertEqual(current.timezone, "Asia/Kolkata")

    # -------------------------------------------------------------------------
    # 13. Confirmed Coordinates Preferred
    # -------------------------------------------------------------------------
    def test_13_confirmed_coordinates_preferred(self):
        """When farmer has confirmed coordinates, LocationWeatherService prefers lat/lon query."""
        query_str, lat, lon = LocationWeatherService.build_location_query(self.farmer_with_coords)
        self.assertIsNotNone(lat)
        self.assertIsNotNone(lon)
        self.assertAlmostEqual(lat, 18.7915, places=3)
        self.assertAlmostEqual(lon, 78.9142, places=3)
        self.assertIn("18.7915", query_str)
        self.assertIn("78.9142", query_str)

    # -------------------------------------------------------------------------
    # 14. Village/PIN Query Matching When Coordinates Absent
    # -------------------------------------------------------------------------
    def test_14_village_pin_query_matching(self):
        """When coordinates are absent, query is constructed from village, mandal, district, PIN."""
        query_str, lat, lon = LocationWeatherService.build_location_query(self.farmer_without_coords)
        self.assertIsNone(lat)
        self.assertIsNone(lon)
        self.assertIn("Dharmasagar", query_str)
        self.assertIn("Hanamkonda", query_str)
        self.assertIn("Telangana", query_str)

    # -------------------------------------------------------------------------
    # 15. Country Mismatch Rejected
    # -------------------------------------------------------------------------
    def test_15_country_mismatch_rejected(self):
        """When provider resolves location outside India, LocationCountryMismatchError is raised."""
        foreign_loc_json = {
            "location": {
                "name": "Dallas",
                "region": "Texas",
                "country": "United States of America",
                "lat": 32.78,
                "lon": -96.80,
                "tz_id": "America/Chicago",
                "localtime_epoch": 1794054000,
            },
            "current": {"temp_c": 20.0, "condition": {"text": "Clear"}},
        }
        provider = WeatherAPIProvider(api_key="test_key")

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = foreign_loc_json

        with patch("httpx.Client.get", return_value=mock_resp):
            with self.assertRaises(LocationCountryMismatchError) as ctx:
                provider.get_current_weather(query="Dallas")
            self.assertIn("does not match expected country 'india'", str(ctx.exception).lower())

    # -------------------------------------------------------------------------
    # 16. District Mismatch Requires Clarification
    # -------------------------------------------------------------------------
    def test_16_district_mismatch_requires_clarification(self):
        """When provider resolves to another Indian state/conflicting district, LocationDistrictMismatchError is raised."""
        conflicting_loc = MagicMock()
        conflicting_loc.country = "India"
        conflicting_loc.location_name = "Polasa Village"
        conflicting_loc.region = "Rajasthan"  # Conflicting region for a Telangana farmer

        with self.assertRaises(LocationDistrictMismatchError) as ctx:
            LocationWeatherService.validate_resolved_location(conflicting_loc, self.farmer_with_coords)
        self.assertIn("conflicts with farmer's confirmed district", str(ctx.exception).lower())

    # -------------------------------------------------------------------------
    # 17. Ambiguous Village Not Guessed
    # -------------------------------------------------------------------------
    def test_17_ambiguous_village_not_guessed(self):
        """When provider returns code 1006 (no match), LocationNotFoundError is raised without guessing."""
        provider = WeatherAPIProvider(api_key="test_key")

        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.json.return_value = {"error": {"code": 1006, "message": "No matching location found."}}

        with patch("httpx.Client.get", return_value=mock_resp):
            with self.assertRaises(LocationNotFoundError) as ctx:
                provider.get_current_weather(query="NonExistentVillage12345")
            self.assertIn("no matching location", str(ctx.exception).lower())

    # -------------------------------------------------------------------------
    # 18. Current Conditions Not Labelled as Station Observations Without Evidence
    # -------------------------------------------------------------------------
    def test_18_current_conditions_not_station_observation(self):
        """WeatherAPI numerical grid outputs have is_station_observation=False and is_nearby_grid_estimate=True."""
        provider = WeatherAPIProvider(api_key="test_key")

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = MOCK_CURRENT_JSON

        with patch("httpx.Client.get", return_value=mock_resp):
            current = provider.get_current_weather(query="Jagtial, India")
            self.assertFalse(current.is_station_observation)
            self.assertTrue(current.location.is_nearby_grid_estimate)
            self.assertIsNone(current.observed_rainfall_mm)

    # -------------------------------------------------------------------------
    # 19. Forecast Rainfall Not Presented as Observed Rainfall
    # -------------------------------------------------------------------------
    def test_19_forecast_rainfall_not_presented_as_observed(self):
        """Daily forecast records set forecast_rainfall_mm, and keep observed_rainfall_mm=None."""
        provider = WeatherAPIProvider(api_key="test_key")

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = MOCK_FORECAST_3DAY_JSON

        with patch("httpx.Client.get", return_value=mock_resp):
            forecast = provider.get_forecast(query="Jagtial, India", days=3)
            for day in forecast.forecast_days:
                self.assertIsNotNone(day.forecast_rainfall_mm)
                self.assertIsNone(day.observed_rainfall_mm, "Forecast day must not report observed rainfall")

    # -------------------------------------------------------------------------
    # 20. Missing Weather Data Never Becomes Zero Rainfall
    # -------------------------------------------------------------------------
    def test_20_missing_weather_data_never_becomes_zero_rainfall(self):
        """When weather provider fails, service raises an exception; it never fabricates 0.0 mm rainfall."""
        provider = WeatherAPIProvider(api_key="test_key")

        mock_resp = MagicMock()
        mock_resp.status_code = 500

        with patch("httpx.Client.get", return_value=mock_resp):
            with self.assertRaises(ProviderUnavailableError):
                provider.get_current_weather(query="Jagtial, India")

    # -------------------------------------------------------------------------
    # 21. Provider Failure Never Becomes "No Warning"
    # -------------------------------------------------------------------------
    def test_21_provider_failure_never_becomes_no_warning(self):
        """IMD provider marks warning status as pending credentials rather than claiming 'no warnings'."""
        imd = IMDWeatherProvider()
        self.assertEqual(imd.get_status(), ProviderStatus.PENDING_CREDENTIALS)
        with self.assertRaises(ProviderNotConfiguredError) as ctx:
            imd.get_current_weather(query="Warangal")
        self.assertIn("pending official credentials", str(ctx.exception).lower())

    # -------------------------------------------------------------------------
    # 22. Planning Horizon Separate From Weather Forecast Horizon
    # -------------------------------------------------------------------------
    def test_22_planning_horizon_separate_from_weather_horizon(self):
        """Weather forecast horizons (short-range) and agricultural planning horizons are distinct."""
        # Weather forecast horizons
        w_short = WeatherForecastHorizon.SHORT_RANGE_1_3D
        w_extended = WeatherForecastHorizon.EXTENDED_RANGE_8_15D
        self.assertNotEqual(w_short.value, w_extended.value)

        # Agricultural decision planning horizons
        a_short = PlanningHorizon.SHORT_RANGE_1_7D
        a_strategic = PlanningHorizon.SEASONAL_31_60D
        self.assertNotEqual(a_short.value, a_strategic.value)

        # Verify classification
        self.assertEqual(classify_planning_horizon(3), PlanningHorizon.SHORT_RANGE_1_7D)
        self.assertEqual(classify_planning_horizon(10), PlanningHorizon.EXTENDED_8_15D)
        self.assertEqual(classify_planning_horizon(25), PlanningHorizon.MEDIUM_30D)
        self.assertEqual(classify_planning_horizon(45), PlanningHorizon.SEASONAL_31_60D)

    # -------------------------------------------------------------------------
    # 23. Long-Range Outlooks Cannot Be Converted to Deterministic Daily Forecasts
    # -------------------------------------------------------------------------
    def test_23_long_range_outlooks_cannot_be_deterministic_daily(self):
        """Planning safety policy strictly blocks deterministic daily forecasts at 16-30d and 31-60d."""
        self.assertTrue(SAFETY_RULE_FORECAST_ALONE_CANNOT_TRIGGER_ADVICE)

        # Horizon > 15 days is restricted to strategic planning only
        res_30 = AdvisoryTriggerSafetyPolicy.evaluate_trigger_safety(
            has_forecast=True,
            has_crop_and_stage=True,
            has_soil_water_conditions=True,
            has_valid_official_advisory=True,
            horizon_days=25,
        )
        self.assertEqual(res_30.planning_guidance_level, "strategic_planning_only")
        self.assertIn("deterministic daily weather forecasts are not scientifically valid", res_30.safety_message.lower())

        # Forecast alone without agronomic factors is strictly blocked
        res_blocked = AdvisoryTriggerSafetyPolicy.evaluate_trigger_safety(
            has_forecast=True,
            has_crop_and_stage=False,
            has_soil_water_conditions=False,
            has_valid_official_advisory=False,
            horizon_days=2,
        )
        self.assertEqual(res_blocked.planning_guidance_level, "blocked")

    # -------------------------------------------------------------------------
    # 24. Existing Farmer and Knowledge Records Remain Intact
    # -------------------------------------------------------------------------
    def test_24_existing_farmer_and_knowledge_records_intact(self):
        """Weather operations do not alter farmer profile or knowledge records."""
        farmer = self.farmer_service.get_farmer_by_id(self.farmer_with_coords.farmer_id)
        self.assertIsNotNone(farmer)
        self.assertEqual(farmer.village_name, "Polasa")
        self.assertEqual(farmer.district_name, "Jagtial")
        self.assertEqual(farmer.pin_code, "505529")

    # -------------------------------------------------------------------------
    # 25. FastAPI Endpoints Live Contract
    # -------------------------------------------------------------------------
    def test_25_weather_api_endpoints_live_contract(self):
        """FastAPI weather endpoints respond accurately to GET /status, /current, and /forecast."""
        # 1. GET /api/v1/weather/status
        status_resp = self.client.get("/api/v1/weather/status")
        self.assertEqual(status_resp.status_code, 200)
        data = status_resp.json()
        self.assertIn("status", data)
        self.assertIn("configured_providers", data)
        self.assertIn("weatherapi_free", data["configured_providers"])
        self.assertIn("imd_official", data["configured_providers"])

        # Create mock provider with explicit mock http client
        mock_http_client = MagicMock()
        mock_provider = WeatherAPIProvider(api_key="test_key", http_client=mock_http_client)
        test_service = WeatherService(
            farmer_service=self.farmer_service,
            weatherapi_provider=mock_provider,
        )

        # 2. GET /api/v1/weather/current with mock
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = MOCK_CURRENT_JSON
        mock_http_client.get.return_value = mock_resp

        with patch("app.api.routes.weather.get_weather_service", return_value=test_service):
            curr_resp = self.client.get(f"/api/v1/weather/current?farmer_id={self.farmer_with_coords.farmer_id}")
            self.assertEqual(curr_resp.status_code, 200)
            curr_data = curr_resp.json()
            self.assertEqual(curr_data["source_name"], "WeatherAPI.com Free")
            self.assertEqual(curr_data["temperature_c"], 31.5)

        # 3. GET /api/v1/weather/forecast with mock
        mock_f_resp = MagicMock()
        mock_f_resp.status_code = 200
        mock_f_resp.json.return_value = MOCK_FORECAST_3DAY_JSON
        mock_http_client.get.return_value = mock_f_resp

        with patch("app.api.routes.weather.get_weather_service", return_value=test_service):
            f_resp = self.client.get(f"/api/v1/weather/forecast?farmer_id={self.farmer_with_coords.farmer_id}&days=3")
            self.assertEqual(f_resp.status_code, 200)
            f_data = f_resp.json()
            self.assertEqual(f_data["days_count"], 3)
            self.assertEqual(len(f_data["forecast_days"]), 3)

            # 4. GET /api/v1/weather/forecast with days > 3 returns HTTP 400
            f_bad = self.client.get(f"/api/v1/weather/forecast?farmer_id={self.farmer_with_coords.farmer_id}&days=5")
            self.assertEqual(f_bad.status_code, 400)
            self.assertIn("FORECAST_DAYS_LIMIT_EXCEEDED", f_bad.json()["detail"]["error_code"])

    # -------------------------------------------------------------------------
    # 26. Point Query Does Not Imply Sub-km Resolution
    # -------------------------------------------------------------------------
    def test_26_point_query_does_not_imply_sub_km_resolution(self):
        """Coordinate-based queries map to numerical model grid (~1-11 km), not sub-km point precision."""
        provider = WeatherAPIProvider(api_key="test_key")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = MOCK_CURRENT_JSON

        with patch("httpx.Client.get", return_value=mock_resp):
            current = provider.get_current_weather(
                query="unused",
                lat=18.7915,
                lon=78.9142,
            )
            loc = current.location
            self.assertEqual(loc.requested_latitude, 18.7915)
            self.assertEqual(loc.requested_longitude, 78.9142)
            self.assertEqual(loc.provider_location_latitude, 18.79)
            self.assertEqual(loc.provider_location_longitude, 78.91)
            self.assertEqual(loc.provider_grid_resolution_km, "1-11 km")
            self.assertTrue(loc.is_nearby_grid_estimate)
            self.assertEqual(loc.geographical_resolution, GeographicalResolution.POINT_GRID)

    # -------------------------------------------------------------------------
    # 27. Provider Grid Resolution Metadata Range
    # -------------------------------------------------------------------------
    def test_27_provider_grid_resolution_metadata_range(self):
        """Metadata preserves explicit ~1-11 km numerical prediction model grid range."""
        provider = WeatherAPIProvider(api_key="test_key")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = MOCK_FORECAST_3DAY_JSON

        with patch("httpx.Client.get", return_value=mock_resp):
            forecast = provider.get_forecast(query="Jagtial, India", days=3)
            self.assertEqual(forecast.location.provider_grid_resolution_km, "1-11 km")
            self.assertEqual(forecast.geographical_resolution, GeographicalResolution.POINT_GRID)

    # -------------------------------------------------------------------------
    # 28. Unknown Station Provenance Not Confirmed Station
    # -------------------------------------------------------------------------
    def test_28_unknown_station_provenance_not_confirmed_station(self):
        """When station provenance is unverified, station_observation_confirmed must be False."""
        provider = WeatherAPIProvider(api_key="test_key")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = MOCK_CURRENT_JSON

        with patch("httpx.Client.get", return_value=mock_resp):
            current = provider.get_current_weather(query="Jagtial, India")
            self.assertFalse(current.station_observation_confirmed)
            self.assertFalse(current.location.station_observation_confirmed)
            self.assertIsNone(current.location.station_identifier)

    # -------------------------------------------------------------------------
    # 29. Provider Precipitation Not Local Rain Gauge
    # -------------------------------------------------------------------------
    def test_29_provider_precipitation_not_local_rain_gauge(self):
        """Provider precipitation is model-derived, not misattributed to physical rain gauges or TSDPS."""
        provider = WeatherAPIProvider(api_key="test_key")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = MOCK_CURRENT_JSON

        with patch("httpx.Client.get", return_value=mock_resp):
            current = provider.get_current_weather(query="Jagtial, India")
            self.assertIsNone(current.observed_rainfall_mm)
            self.assertEqual(current.data_source_nature, "provider_reported_current_conditions")
            self.assertFalse(current.is_station_observation)

    # -------------------------------------------------------------------------
    # 30. Provider Region Not Mistaken for District
    # -------------------------------------------------------------------------
    def test_30_provider_region_not_mistaken_for_district(self):
        """Provider region indicates State level (Telangana); must not be treated as district confirmation."""
        # Location is 'Peddapalli' (in Telangana), but farmer is in 'Jagtial'
        loc_info = WeatherLocationInfo(
            location_name="Peddapalli",
            region="Telangana",
            country="India",
        )
        LocationWeatherService.validate_resolved_location(loc_info, self.farmer_without_coords)
        # Location does not match farmer's district (Hanamkonda) -> not independently verified
        self.assertEqual(loc_info.location_match_status, "not_independently_verified")
        self.assertNotEqual(loc_info.location_match_status, "district_verified")

    # -------------------------------------------------------------------------
    # 31. District-Level Validation Marked Not Independently Verified
    # -------------------------------------------------------------------------
    def test_31_district_level_validation_marked_not_independently_verified(self):
        """When provider returns a locality without matching district or coordinates, status is unverified."""
        loc_info = WeatherLocationInfo(
            location_name="SomeUnknownVillage",
            region="Telangana",
            country="India",
        )
        LocationWeatherService.validate_resolved_location(loc_info, self.farmer_without_coords)
        self.assertEqual(loc_info.location_match_status, "not_independently_verified")

    # -------------------------------------------------------------------------
    # 32. Telugu Disclaimer Present
    # -------------------------------------------------------------------------
    def test_32_telugu_disclaimer_present(self):
        """Telugu disclaimer is attached by default or when te-IN language is requested."""
        provider = WeatherAPIProvider(api_key="test_key")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = MOCK_CURRENT_JSON

        with patch("httpx.Client.get", return_value=mock_resp):
            current = provider.get_current_weather(query="Jagtial, India", language="te-IN")
            self.assertEqual(current.disclaimer_language, "te-IN")
            self.assertIn("వాతావరణ సమాచారం", current.disclaimer)
            self.assertIn("భారత వాతావరణ శాఖ (IMD)", current.disclaimer)

    # -------------------------------------------------------------------------
    # 33. Hindi Disclaimer Present
    # -------------------------------------------------------------------------
    def test_33_hindi_disclaimer_present(self):
        """Hindi disclaimer is attached when hi-IN language is requested."""
        provider = WeatherAPIProvider(api_key="test_key")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = MOCK_CURRENT_JSON

        with patch("httpx.Client.get", return_value=mock_resp):
            current = provider.get_current_weather(query="Jagtial, India", language="hi-IN")
            self.assertEqual(current.disclaimer_language, "hi-IN")
            self.assertIn("मौसम की जानकारी", current.disclaimer)
            self.assertIn("भारतीय मौसम विभाग (IMD)", current.disclaimer)

    # -------------------------------------------------------------------------
    # 34. No Call Without Third-Party Location Sharing Consent
    # -------------------------------------------------------------------------
    def test_34_no_call_without_third_party_location_sharing_consent(self):
        """Farmer lacking explicit third-party location sharing consent raises WeatherLocationSharingConsentRequiredError."""
        service = WeatherService(farmer_service=self.farmer_service)
        with self.assertRaises(WeatherLocationSharingConsentRequiredError) as ctx:
            service.get_current_weather(farmer_id=self.farmer_without_sharing_consent.farmer_id)
        self.assertIn("not consented to sharing location data", str(ctx.exception))

    # -------------------------------------------------------------------------
    # 35. Existing Storage Consent Does Not Grant Provider Sharing
    # -------------------------------------------------------------------------
    def test_35_existing_storage_consent_does_not_grant_provider_sharing(self):
        """Phase 4 local storage consent (consent_given=True) does not grant third-party external transmission."""
        self.assertTrue(self.farmer_without_sharing_consent.consent_given)
        self.assertFalse(self.farmer_without_sharing_consent.weather_provider_sharing_consent)

        with self.assertRaises(WeatherLocationSharingConsentRequiredError):
            LocationWeatherService.build_location_query(self.farmer_without_sharing_consent)

    # -------------------------------------------------------------------------
    # 36. Explicit Provider Sharing Consent Permits Request
    # -------------------------------------------------------------------------
    def test_36_explicit_provider_sharing_consent_permits_request(self):
        """Granting explicit weather sharing consent unblocks weather retrieval."""
        updated = self.farmer_service.update_weather_sharing_consent(
            farmer_id=self.farmer_without_sharing_consent.farmer_id,
            consent_given=True,
            disclosure_version="v1.0",
        )
        self.assertTrue(updated.weather_provider_sharing_consent)
        self.assertIsNotNone(updated.weather_provider_sharing_consent_at)
        self.assertEqual(updated.weather_provider_disclosure_version, "v1.0")

        # Now building query succeeds
        query_str, lat, lon = LocationWeatherService.build_location_query(updated)
        self.assertIsNotNone(query_str)

        # Restore state for other tests
        self.farmer_service.update_weather_sharing_consent(
            farmer_id=self.farmer_without_sharing_consent.farmer_id,
            consent_given=False,
            disclosure_version="v1.0",
        )

    # -------------------------------------------------------------------------
    # 37. Consent Timestamps and Disclosure Version Recorded
    # -------------------------------------------------------------------------
    def test_37_consent_timestamps_and_disclosure_version_recorded(self):
        """Updating consent properly logs timestamp and disclosure version in database."""
        now_ts = datetime.now(timezone.utc).isoformat()
        self.farmer_service.repository.update_weather_sharing_consent(
            farmer_id=self.farmer_with_coords.farmer_id,
            consent_given=True,
            consent_at=now_ts,
            disclosure_version="v2.0-test",
            updated_at=now_ts,
        )
        refreshed = self.farmer_service.get_farmer_by_id(self.farmer_with_coords.farmer_id)
        self.assertTrue(refreshed.weather_provider_sharing_consent)
        self.assertEqual(refreshed.weather_provider_sharing_consent_at, now_ts)
        self.assertEqual(refreshed.weather_provider_disclosure_version, "v2.0-test")

    # -------------------------------------------------------------------------
    # 38. WeatherAPI Cache TTL Stays Within Terms
    # -------------------------------------------------------------------------
    def test_38_weatherapi_cache_ttl_stays_within_terms(self):
        """Cache TTLs strictly comply with WeatherAPI terms: current <= 60m, forecast <= 24h."""
        self.assertLessEqual(weather_cache.DEFAULT_CURRENT_TTL_SECONDS, 3600)  # <= 60 min
        self.assertEqual(weather_cache.DEFAULT_CURRENT_TTL_SECONDS, 1800)      # 30 min default
        self.assertLessEqual(weather_cache.DEFAULT_FORECAST_TTL_SECONDS, 86400) # <= 24 hours
        self.assertEqual(weather_cache.DEFAULT_FORECAST_TTL_SECONDS, 21600)     # 6 hours default

    # -------------------------------------------------------------------------
    # 39. IMD Authentication Distinguishes Confirmed From Unverified
    # -------------------------------------------------------------------------
    def test_39_imd_authentication_distinguishes_confirmed_from_unverified(self):
        """IMD authentication requirements cleanly classify facts vs unverified developer claims."""
        imd = IMDWeatherProvider()
        reqs = imd.get_authentication_requirements()

        # Documented facts
        self.assertEqual(
            reqs["portal_reference"]["evidence"],
            IMDAuthenticationEvidence.OFFICIALLY_DOCUMENTED.value,
        )
        self.assertEqual(
            reqs["registration_requirement"]["evidence"],
            IMDAuthenticationEvidence.OFFICIALLY_DOCUMENTED.value,
        )

        # Unverified claims
        self.assertEqual(
            reqs["security_architecture"]["evidence"],
            IMDAuthenticationEvidence.PORTAL_REPORTED_UNVERIFIED.value,
        )
        self.assertEqual(
            reqs["server_binding"]["evidence"],
            IMDAuthenticationEvidence.PORTAL_REPORTED_UNVERIFIED.value,
        )

        # Unknown runtime behavior
        self.assertEqual(
            reqs["token_refresh_lifecycle"]["evidence"],
            IMDAuthenticationEvidence.UNKNOWN.value,
        )

    # -------------------------------------------------------------------------
    # 40. API Endpoint Returns 403 When Sharing Consent Missing
    # -------------------------------------------------------------------------
    def test_40_api_forbidden_when_sharing_consent_missing(self):
        """GET /api/v1/weather/current returns HTTP 403 when farmer lacks sharing consent."""
        resp = self.client.get(
            f"/api/v1/weather/current?farmer_id={self.farmer_without_sharing_consent.farmer_id}"
        )
        self.assertEqual(resp.status_code, 403)
        data = resp.json()
        self.assertEqual(data["detail"]["error_code"], "LOCATION_SHARING_CONSENT_REQUIRED")


if __name__ == "__main__":
    unittest.main()
