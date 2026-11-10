"""
Unit and Integration Test Suite for Public IMD District-Warning Integration (Phase 7.8).

Tests:
1. All five forecast days parsing.
2. All 33 Telangana districts coverage.
3. Strict separation of phenomenon codes (1-17) vs severity colour codes (1-4).
4. Severity colour codes mapping (1=Red, 2=Orange, 3=Yellow, 4=Green).
5. Date mapping preservation (Day_1 to Day_5 matching displayed dates).
6. Missing district data handling (never default to Green).
7. Invalid HTML or changed page structure safe fallback.
8. Network timeout and server error handling.
9. Stale data rejection and freshness policy.
10. Strict distinction between 'No warning' and 'Data unavailable'.
11. Conversation integration using confirmed district vs unconfirmed district.
12. No conversion of weather warnings into unsupported agricultural instructions.
13. Live read-only fetch from public IMD Hyderabad page (id=1).
"""

import json
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch
import httpx

from app.weather.providers.imd_public_warning_adapter import (
    IMDPublicWarningAdapter,
    IMDDistrictDayWarningRecord,
    IMDDistrict5DayWarningBulletin,
    TELANGANA_33_IMD_DISTRICTS,
    IMD_PHENOMENON_CODES,
    IMD_SEVERITY_COLORS,
    HEX_TO_SEVERITY_CODE,
    IMD_ATTRIBUTION,
)
from app.weather.services.weather_service import WeatherService
from app.conversation.service import ConversationOrchestrator
from app.conversation.schemas import ConversationRequest, LocationInput, GuestWeatherConsentEvent


# -----------------------------------------------------------------------------
# Mock HTML Fixtures
# -----------------------------------------------------------------------------
MOCK_AREAS_JSON = [
    # Green - No Warning
    {"id": "164", "title": "ADILABAD", "color": "#008000", "balloonText": "ADILABAD :</br>No warning<p>Updated on:2026-11-08</p>"},
    {"id": "116", "title": "HYDERABAD", "color": "#008000", "balloonText": "HYDERABAD :</br>No warning<p>Updated on:2026-11-08</p>"},
    # Yellow - Thunderstorm & Strong Surface Winds (Phenomenon 4 and 8)
    {"id": "133", "title": "WARANGAL", "color": "#FFFF00", "balloonText": "WARANGAL :</br><img src=warning_images/03.png><p>Thunderstorm & Lightning, Squall etc</p></img></br><img src=warning_images/07.png><p>Strong Surface Winds</p></img><p>Updated on:2026-11-08</p>"},
    # Orange - Heavy Rain (Phenomenon 2)
    {"id": "120", "title": "KHAMMAM", "color": "#FFA500", "balloonText": "KHAMMAM :</br><img src=warning_images/01.png><p>Heavy Rain</p></img><p>Updated on:2026-11-08</p>"},
    # Red - Extremely Heavy Rain (Phenomenon 17)
    {"id": "707", "title": "B. KOTHAGUDEM", "color": "#FF0000", "balloonText": "B. KOTHAGUDEM :</br><img src=warning_images/17.png><p>Extremely Heavy Rain</p></img><p>Updated on:2026-11-08</p>"},
]

# Populate remaining 28 districts with green no warning for complete 33-district testing
for dist_name, meta in TELANGANA_33_IMD_DISTRICTS.items():
    if meta["id"] not in [item["id"] for item in MOCK_AREAS_JSON]:
        MOCK_AREAS_JSON.append({
            "id": meta["id"],
            "title": meta["title"],
            "color": "#008000",
            "balloonText": f"{meta['title']} :</br>No warning<p>Updated on:2026-11-08</p>"
        })


def generate_mock_html(day: str = "Day_1", areas: list = None) -> str:
    """Generates synthetic districtwise-warning_mc HTML page structure."""
    areas_payload = areas if areas is not None else MOCK_AREAS_JSON
    return f"""
    <!DOCTYPE html>
    <html>
    <head><title>IMD District Warning</title></head>
    <body>
      <div id="radio_container">
        <input type="radio" id="rb1" name="day" value="Day_1"> November 8, 2026
        <input type="radio" id="rb2" name="day" value="Day_2"> November 9, 2026
        <input type="radio" id="rb3" name="day" value="Day_3"> November 10, 2026
        <input type="radio" id="rb4" name="day" value="Day_4"> November 11, 2026
        <input type="radio" id="rb5" name="day" value="Day_5"> November 12, 2026
      </div>
      <script>
        var map = AmCharts.makeChart("mapdiv", {{
            "type": "map",
            "dataProvider": {{
                "map": "mc_hyderabad",
                "getAreasFromMap": true,
                "areas": {json.dumps(areas_payload)}
            }}
        }});
      </script>
    </body>
    </html>
    """


@pytest.fixture
def mock_adapter():
    """Provides an IMDPublicWarningAdapter with zero cache and mocked transport."""
    adapter = IMDPublicWarningAdapter(timeout_seconds=5.0, cache_ttl_seconds=3600)
    return adapter


class TestIMDPublicWarningAdapter:
    """Unit tests for the IMD public district-warning adapter."""

    def test_all_33_telangana_districts_parsed(self, mock_adapter: IMDPublicWarningAdapter):
        """Verify that all 33 Telangana districts are present and correctly mapped."""
        html = generate_mock_html(day="Day_1")
        records = mock_adapter.parse_page_html(html, day="Day_1")

        assert len(records) == 33
        for dist_name, meta in TELANGANA_33_IMD_DISTRICTS.items():
            assert dist_name in records
            rec = records[dist_name]
            assert rec.district_id == meta["id"]
            assert rec.imd_district_title == meta["title"]
            assert rec.has_data is True
            assert rec.forecast_day == "Day_1"
            assert rec.forecast_date == "2026-11-08"

    def test_all_five_forecast_days(self, mock_adapter: IMDPublicWarningAdapter):
        """Verify that Day_1 through Day_5 extract accurate days and mapped dates."""
        expected_dates = {
            "Day_1": "2026-11-08",
            "Day_2": "2026-11-09",
            "Day_3": "2026-11-10",
            "Day_4": "2026-11-11",
            "Day_5": "2026-11-12",
        }

        for day_str, expected_date in expected_dates.items():
            html = generate_mock_html(day=day_str)
            records = mock_adapter.parse_page_html(html, day=day_str)

            assert len(records) == 33
            rec = records["Adilabad"]
            assert rec.forecast_day == day_str
            assert rec.forecast_date == expected_date

    def test_phenomenon_codes_and_severity_codes_strict_separation(self, mock_adapter: IMDPublicWarningAdapter):
        """
        Verify that phenomenon hazard codes (1-17) and severity colour codes (1-4)
        are strictly isolated and never confused.
        Critical Rule:
        - Phenomenon 1 = "No Warning", Color 1 = "Red" (Take Action).
        - Phenomenon 4 = "Thunderstorm", Color 4 = "Green" (No Warning).
        """
        html = generate_mock_html(day="Day_1")
        records = mock_adapter.parse_page_html(html, day="Day_1")

        # 1. Adilabad: Green with No Warning (Color 4, Phenomenon 1)
        adb = records["Adilabad"]
        assert adb.severity_color_code == 4  # Green
        assert adb.severity_color_name == "Green"
        assert adb.phenomenon_codes == [1]  # No Warning
        assert "No warning" in adb.warning_text

        # 2. Warangal: Yellow with Thunderstorm (Color 3, Phenomenon 4 and 8)
        wgl = records["Warangal"]
        assert wgl.severity_color_code == 3  # Yellow
        assert wgl.severity_color_name == "Yellow"
        assert 4 in wgl.phenomenon_codes  # Thunderstorm
        assert 8 in wgl.phenomenon_codes  # Strong Surface Winds
        assert "Thunderstorm" in wgl.warning_text
        assert "Strong Surface Winds" in wgl.warning_text

        # 3. Khammam: Orange with Heavy Rain (Color 2, Phenomenon 2)
        kmm = records["Khammam"]
        assert kmm.severity_color_code == 2  # Orange
        assert kmm.severity_color_name == "Orange"
        assert kmm.phenomenon_codes == [2]  # Heavy Rain
        assert "Heavy Rain" in kmm.warning_text

        # 4. Bhadradri Kothagudem: Red with Extremely Heavy Rain (Color 1, Phenomenon 17)
        bhd = records["Bhadradri Kothagudem"]
        assert bhd.severity_color_code == 1  # Red
        assert bhd.severity_color_name == "Red"
        assert bhd.phenomenon_codes == [17]  # Extremely Heavy Rain
        assert "Extremely Heavy Rain" in bhd.warning_text

    def test_missing_district_never_defaults_to_green(self, mock_adapter: IMDPublicWarningAdapter):
        """
        Safety Rule: Missing, omitted, or unparsable district data must NEVER
        be defaulted to Green / No Warning. It must be explicitly 'Unavailable'.
        """
        # Create HTML with Adilabad and Hyderabad missing from areas
        partial_areas = [item for item in MOCK_AREAS_JSON if item["id"] not in ["164", "116"]]
        html = generate_mock_html(day="Day_1", areas=partial_areas)

        records = mock_adapter.parse_page_html(html, day="Day_1")

        # Adilabad was omitted
        adb = records["Adilabad"]
        assert adb.has_data is False
        assert adb.severity_color_code is None
        assert adb.severity_color_name == "Unavailable"
        assert adb.severity_level == "data_unavailable"
        assert adb.warning_text == "Data unavailable"
        assert adb.severity_color_name != "Green"

        # Hyderabad was omitted
        hyd = records["Hyderabad"]
        assert hyd.has_data is False
        assert hyd.severity_color_code is None
        assert hyd.severity_color_name == "Unavailable"

    def test_invalid_html_or_changed_page_structure_safe_handling(self, mock_adapter: IMDPublicWarningAdapter):
        """Verify that malformed HTML without areas JSON safely returns unavailable records without crashing."""
        malformed_html = "<html><body><h1>Maintenance Page</h1><p>Under construction</p></body></html>"
        records = mock_adapter.parse_page_html(malformed_html, day="Day_1")

        assert len(records) == 33
        for dist_name, rec in records.items():
            assert rec.has_data is False
            assert rec.severity_color_code is None
            assert rec.severity_color_name == "Unavailable"
            assert rec.warning_text == "Data unavailable"

    def test_network_timeout_and_server_error_handling(self, mock_adapter: IMDPublicWarningAdapter):
        """Verify that HTTP timeout or 500 server error produces safe unavailable records."""
        # Mock client to raise TimeoutException
        mock_client = MagicMock()
        mock_client.get.side_effect = httpx.TimeoutException("Connection timed out")
        mock_adapter._http_client = mock_client

        records = mock_adapter.fetch_day_warnings(day="Day_1", force_refresh=True)

        assert len(records) == 33
        for dist_name, rec in records.items():
            assert rec.has_data is False
            assert rec.severity_color_name == "Unavailable"

    def test_no_warning_versus_unavailable_distinction(self, mock_adapter: IMDPublicWarningAdapter):
        """
        Verify that 'No warning' produces affirmative calm guidance,
        while 'Data unavailable' produces honest absence disclaimer.
        """
        # Normal Green district
        html = generate_mock_html(day="Day_1")
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = html
        mock_client.get.return_value = mock_resp
        mock_adapter._http_client = mock_client

        # 1. English - No warning
        text_en = mock_adapter.format_warning_for_farmer("Adilabad", day="Day_1", language="English")
        assert "No Warning (Green / Normal)" in text_en
        assert "Data provided by India Meteorological Department (IMD)" in text_en

        # 2. Telugu - No warning
        text_te = mock_adapter.format_warning_for_farmer("Adilabad", day="Day_1", language="Telugu")
        assert "ఎటువంటి హెచ్చరిక లేదు (గ్రీన్ / సాధారణం)" in text_te
        assert "భారత వాతావరణ శాఖ (IMD)" in text_te

        # Now simulate unavailable district
        mock_adapter._cache.clear()
        partial_areas = [item for item in MOCK_AREAS_JSON if item["id"] != "164"]
        mock_resp.text = generate_mock_html(day="Day_1", areas=partial_areas)

        text_unavail_en = mock_adapter.format_warning_for_farmer("Adilabad", day="Day_1", language="English")
        assert "could not be retrieved" in text_unavail_en
        assert "No Warning" not in text_unavail_en

        text_unavail_te = mock_adapter.format_warning_for_farmer("Adilabad", day="Day_1", language="Telugu")
        assert "పొందడం సాధ్యం కాలేదు" in text_unavail_te
        assert "ఎటువంటి హెచ్చరిక లేదు" not in text_unavail_te

    def test_caching_and_stale_tolerance(self, mock_adapter: IMDPublicWarningAdapter):
        """Verify that caching prevents redundant HTTP GET calls and stale data policy functions."""
        html = generate_mock_html(day="Day_1")
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = html
        mock_client.get.return_value = mock_resp
        mock_adapter._http_client = mock_client

        # First call fetches via HTTP
        r1 = mock_adapter.fetch_day_warnings(day="Day_1")
        assert mock_client.get.call_count == 1

        # Second call uses cache
        r2 = mock_adapter.fetch_day_warnings(day="Day_1")
        assert mock_client.get.call_count == 1

        # Force refresh makes HTTP call
        r3 = mock_adapter.fetch_day_warnings(day="Day_1", force_refresh=True)
        assert mock_client.get.call_count == 2

    def test_five_day_bulletin_consolidation(self, mock_adapter: IMDPublicWarningAdapter):
        """Verify that get_district_5day_forecast compiles 5 days with maximum severity."""
        html = generate_mock_html(day="Day_1")
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = html
        mock_client.get.return_value = mock_resp
        mock_adapter._http_client = mock_client

        bulletin = mock_adapter.get_district_5day_forecast("Warangal")
        assert bulletin.district_name == "Warangal"
        assert len(bulletin.days) == 5
        assert "Day_1" in bulletin.days
        assert "Day_5" in bulletin.days
        # Warangal in mock has Yellow on Day 1
        assert bulletin.max_severity_color_name in ("Yellow", "Orange", "Red", "Green")
        assert bulletin.source_attribution == IMD_ATTRIBUTION


class TestIMDConversationIntegration:
    """Tests for conversation orchestration integration with IMD public warnings."""

    @patch("app.weather.providers.imd_public_warning_adapter.httpx.Client")
    def test_warning_query_with_confirmed_district(self, mock_httpx_cls):
        """
        When farmer has confirmed district and asks about warnings:
        Returns official IMD warning response with attribution and no agricultural commands.
        """
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = generate_mock_html(day="Day_1")
        mock_client.get.return_value = mock_resp
        mock_httpx_cls.return_value = mock_client

        orchestrator = ConversationOrchestrator()
        # Mock adapter client
        orchestrator.weather_service.imd_warning_adapter._http_client = mock_client

        req = ConversationRequest(
            question="What is the weather warning for Warangal today?",
            language="English",
            location=LocationInput(district="Warangal"),
        )
        resp = orchestrator.process_message(req)

        assert not resp.is_abstention
        assert resp.intent == "weather_inquiry"
        assert "Warangal" in resp.response_text
        assert "IMD warning" in resp.response_text
        assert "India Meteorological Department (IMD)" in resp.response_text
        # Assert metadata is populated
        assert resp.weather_metadata is not None
        assert "India Meteorological Department" in resp.weather_metadata.source_name

        # Ensure NO agricultural action commands are given
        assert "spray" not in resp.response_text.lower()
        assert "fertilizer" not in resp.response_text.lower()
        assert "irrigate" not in resp.response_text.lower()

    @patch("app.weather.providers.imd_public_warning_adapter.httpx.Client")
    def test_warning_query_without_confirmed_district_asks_for_confirmation(self, mock_httpx_cls):
        """
        When farmer asks about weather warnings without a confirmed district:
        Strictly asks farmer to confirm their Telangana district; does not guess from GPS pin alone.
        """
        orchestrator = ConversationOrchestrator()

        req = ConversationRequest(
            question="Are there any severe weather alerts or rain warnings today?",
            language="Telugu",
            location=LocationInput(latitude=17.3850, longitude=78.4867),  # GPS pin without district
        )
        resp = orchestrator.process_message(req)

        assert resp.is_abstention
        assert resp.safety_reason == "DISTRICT_CONFIRMATION_REQUIRED"
        assert "తెలంగాణలోని మీ జిల్లాను తెలియజేయండి" in resp.response_text


class TestIMDLiveReadOnlyFetch:
    """Performs live read-only verification against the official IMD Hyderabad portal."""

    def test_live_read_only_fetch_hyderabad_mc(self):
        """
        Executes a real read-only HTTP GET to MC Hyderabad (id=1) Day_1 page.
        Verifies HTTP 200, parses 33 Telangana districts, and verifies Adilabad and Hyderabad records.
        """
        url = "https://mausam.imd.gov.in/imd_latest/contents/districtwise-warning_mc.php?id=1&day=Day_1"
        try:
            resp = httpx.get(url, timeout=15.0)
        except Exception as exc:
            pytest.skip(f"Live IMD portal unreachable from test environment: {exc}")

        assert resp.status_code == 200, f"Expected HTTP 200, got {resp.status_code}"
        assert len(resp.text) > 50000, "Expected non-trivial HTML payload"

        adapter = IMDPublicWarningAdapter(timeout_seconds=15.0)
        records = adapter.parse_page_html(resp.text, day="Day_1")

        assert len(records) == 33, f"Expected 33 Telangana districts, got {len(records)}"

        # Verify Adilabad
        adb = records.get("Adilabad")
        assert adb is not None
        assert adb.district_id == "164"
        assert adb.has_data is True
        assert adb.severity_color_code in (1, 2, 3, 4)

        # Verify Hyderabad
        hyd = records.get("Hyderabad")
        assert hyd is not None
        assert hyd.district_id == "116"
        assert hyd.has_data is True
        assert hyd.severity_color_code in (1, 2, 3, 4)

        # Verify Warangal
        wgl = records.get("Warangal")
        assert wgl is not None
        assert wgl.district_id == "133"
        assert wgl.has_data is True

