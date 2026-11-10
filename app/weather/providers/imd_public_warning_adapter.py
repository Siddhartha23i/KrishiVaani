"""
Public India Meteorological Department (IMD) District-Warning Adapter for KrishiVaani — Phase 7.8.

Extracts official, structured 5-day district weather warnings for all 33 Telangana districts
from the public Meteorological Centre Hyderabad portal:
https://mausam.imd.gov.in/imd_latest/contents/districtwise-warning_mc.php?id=1&day=Day_1

Key Architecture and Safety Guarantees:
1. Public Web Adapter (Unauthenticated):
   - Uses MC Hyderabad (id=1). Does NOT use id=18 (Srinagar).
   - Extracts structured district JSON directly from embedded 'areas' JavaScript array.
   - Does NOT rely on screenshot reading or image color extraction.
2. Phenomenon Code vs Severity Color Code Strict Separation:
   - Phenomenon Codes (1 to 17): Hazard types (1=No Warning, 2=Heavy Rain, 4=Thunderstorm, etc.)
   - Severity Color Codes (1 to 4): Alert severity (1=Red, 2=Orange, 3=Yellow, 4=Green)
   - NEVER confuses phenomenon code with severity code.
3. Day / Date Mapping:
   - Day_1 = Issue Date, Day_2 = Issue + 1, ..., Day_5 = Issue + 4.
   - Extracts and preserves the actual page-displayed dates.
4. Data Freshness and Safe Fallbacks:
   - In-memory TTL caching prevents redundant HTTP calls.
   - Rejects stale data per configurable freshness policy.
   - NEVER interprets missing, unparsable, or network-failed data as Green/No Warning.
   - Strictly distinguishes "No Warning" from "Data Unavailable".
5. Non-Authoritative Weather Information:
   - Warnings are district-level meteorological context, not farm-specific.
   - A warning is weather intelligence, NEVER an automatic instruction to spray, fertilize, or irrigate.
"""

import re
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List, Tuple, Union
from zoneinfo import ZoneInfo
from dataclasses import dataclass, field, asdict

import httpx

from app.weather.enums import (
    FreshnessStatus,
    GeographicalResolution,
    WeatherInformationType,
)

logger = logging.getLogger(__name__)

KOLKATA_TZ = ZoneInfo("Asia/Kolkata")
IMD_ATTRIBUTION = "Data provided by India Meteorological Department (IMD), Ministry of Earth Sciences, Government of India"
IMD_PUBLIC_PORTAL_URL = "https://mausam.imd.gov.in/imd_latest/contents/districtwise-warning_mc.php?id=1&day=Day_1"

# -----------------------------------------------------------------------------
# Phenomenon Codes (1 to 17) & Severity Color Codes (1 to 4)
# -----------------------------------------------------------------------------
IMD_PHENOMENON_CODES: Dict[int, str] = {
    1: "No Warning",
    2: "Heavy Rain",
    3: "Heavy Snow",
    4: "Thunderstorm & Lightning, Squall etc",
    5: "Hailstorm",
    6: "Dust Storm",
    7: "Dust Raising Winds",
    8: "Strong Surface Winds",
    9: "Heat Wave",
    10: "Hot Day",
    11: "Warm Night",
    12: "Cold Wave",
    13: "Cold Day",
    14: "Ground Frost",
    15: "Fog",
    16: "Very Heavy Rain",
    17: "Extremely Heavy Rain",
}

# Telugu translations for phenomenon hazards
IMD_PHENOMENON_TELUGU: Dict[int, str] = {
    1: "ఎటువంటి హెచ్చరిక లేదు",
    2: "భారీ వర్షం",
    3: "భారీ మంచు",
    4: "ఉరుములు, మెరుపులతో కూడిన వర్షం",
    5: "వడగండ్ల వాన",
    6: "ధూళి తుఫాను",
    7: "తీవ్ర దుమ్ము గాలులు",
    8: "ఈదురు గాలులు",
    9: "వడగాల్పులు",
    10: "తీవ్రమైన ఎండ",
    11: "వేడి రాత్రి",
    12: "శీతల గాలులు",
    13: "తీవ్ర చలి రోజు",
    14: "నేల మంచు",
    15: "దట్టమైన పొగమంచు",
    16: "చాలా భారీ వర్షం",
    17: "అత్యంత భారీ వర్షం",
}

# Hindi translations for phenomenon hazards
IMD_PHENOMENON_HINDI: Dict[int, str] = {
    1: "कोई चेतावनी नहीं",
    2: "भारी वर्षा",
    3: "भारी बर्फबारी",
    4: "गरज और बिजली के साथ बारिश",
    5: "ओलावृष्टि",
    6: "धूल भरी आंधी",
    7: "धूल भरी हवाएं",
    8: "तेज सतही हवाएं",
    9: "लू (हीट वेव)",
    10: "गर्म दिन",
    11: "गर्म रात",
    12: "शीत लहर",
    13: "ठंडा दिन",
    14: "पाला",
    15: "घना कोहरा",
    16: "बहुत भारी वर्षा",
    17: "अत्यधिक भारी वर्षा",
}

# 5-Day Severity Color Codes
IMD_SEVERITY_COLORS: Dict[int, str] = {
    1: "Red",
    2: "Orange",
    3: "Yellow",
    4: "Green",
}

IMD_SEVERITY_LEVEL_NAMES: Dict[int, str] = {
    1: "warning_take_action",
    2: "alert_be_prepared",
    3: "watch_be_updated",
    4: "no_warning",
}

IMD_ACTION_GUIDANCE_EN: Dict[int, str] = {
    1: "Warning — Take Action",
    2: "Alert — Be Prepared",
    3: "Watch — Be Updated",
    4: "No Warning — No Action Required",
}

IMD_ACTION_GUIDANCE_TE: Dict[int, str] = {
    1: "హెచ్చరిక — తక్షణ జాగ్రత్తలు తీసుకోండి",
    2: "అప్రమత్తత — సిద్ధంగా ఉండండి",
    3: "పరిశీలన — సమాచారం తెలుసుకుంటూ ఉండండి",
    4: "సాధారణం — ఎటువంటి చర్యలు అవసరం లేదు",
}

IMD_ACTION_GUIDANCE_HI: Dict[int, str] = {
    1: "चेतावनी — कार्रवाई करें",
    2: "अलर्ट — तैयार रहें",
    3: "निगरानी — अपडेट रहें",
    4: "कोई चेतावनी नहीं — कोई कार्रवाई की आवश्यकता नहीं",
}

HEX_TO_SEVERITY_CODE: Dict[str, int] = {
    "#FF0000": 1,
    "#FFA500": 2,
    "#FFFF00": 3,
    "#008000": 4,
    "#7CFC00": 4,
}

# Verified Telangana 33 Districts Mapping (Phase 7.6)
TELANGANA_33_IMD_DISTRICTS: Dict[str, Dict[str, str]] = {
    "Adilabad": {"id": "164", "title": "ADILABAD"},
    "Bhadradri Kothagudem": {"id": "707", "title": "B. KOTHAGUDEM"},
    "Hanamkonda": {"id": "132", "title": "HANAMKONDA"},
    "Hyderabad": {"id": "116", "title": "HYDERABAD"},
    "Jagtial": {"id": "148", "title": "JAGTIAL"},
    "Jangaon": {"id": "126", "title": "JANGAON"},
    "Jayashankar Bhupalpally": {"id": "629", "title": "J. BHUPALPALLY"},
    "Jogulamba Gadwal": {"id": "104", "title": "JOGULAMBA GADWAL"},
    "Kamareddy": {"id": "708", "title": "KAMAREDDY"},
    "Karimnagar": {"id": "141", "title": "KARIMNAGAR"},
    "Khammam": {"id": "120", "title": "KHAMMAM"},
    "Kumuram Bheem Asifabad": {"id": "161", "title": "KUMARAM BHEEM"},
    "Mahabubabad": {"id": "128", "title": "MAHABUBABAD"},
    "Mahabubnagar": {"id": "112", "title": "MAHABUBNAGAR"},
    "Mancherial": {"id": "153", "title": "MANCHERIAL"},
    "Medak": {"id": "129", "title": "MEDAK"},
    "Medchal-Malkajgiri": {"id": "123", "title": "M. MALKAJGIRI"},
    "Mulugu": {"id": "145", "title": "MULUGU"},
    "Nagarkurnool": {"id": "109", "title": "NAGARKURNOOL"},
    "Nalgonda": {"id": "115", "title": "NALGONDA"},
    "Narayanpet": {"id": "700", "title": "NARAYANPET"},
    "Nirmal": {"id": "706", "title": "NIRMAL"},
    "Nizamabad": {"id": "147", "title": "NIZAMABAD"},
    "Peddapalli": {"id": "144", "title": "PEDDAPALLE"},
    "Rajanna Sircilla": {"id": "140", "title": "RAJANNA SIRCILLA"},
    "Rangareddy": {"id": "118", "title": "RANGAREDDY"},
    "Sangareddy": {"id": "134", "title": "SANGAREDDY"},
    "Siddipet": {"id": "136", "title": "SIDDIPET"},
    "Suryapet": {"id": "117", "title": "SURYAPET"},
    "Vikarabad": {"id": "121", "title": "VIKARABAD"},
    "Wanaparthy": {"id": "106", "title": "WANAPARTHY"},
    "Warangal": {"id": "133", "title": "WARANGAL"},
    "Yadadri Bhuvanagiri": {"id": "125", "title": "Y. BHUVANAGIRI"},
}

DISTRICT_ALIASES: Dict[str, str] = {
    "hanumakonda": "Hanamkonda",
    "warangal urban": "Hanamkonda",
    "warangal rural": "Warangal",
    "asifabad": "Kumuram Bheem Asifabad",
    "komaram bheem": "Kumuram Bheem Asifabad",
    "komaram bheem asifabad": "Kumuram Bheem Asifabad",
    "bhadradri": "Bhadradri Kothagudem",
    "kothagudem": "Bhadradri Kothagudem",
    "bhupalpally": "Jayashankar Bhupalpally",
    "gadwal": "Jogulamba Gadwal",
    "medchal": "Medchal-Malkajgiri",
    "medchal malkajgiri": "Medchal-Malkajgiri",
    "peddapally": "Peddapalli",
    "sircilla": "Rajanna Sircilla",
    "ranga reddy": "Rangareddy",
    "yadadri": "Yadadri Bhuvanagiri",
    "bhuvanagiri": "Yadadri Bhuvanagiri",
}


@dataclass
class IMDDistrictDayWarningRecord:
    """Structured meteorological warning record for a specific district on a single forecast day."""
    district_id: str
    district_name: str
    imd_district_title: str
    forecast_date: str
    issue_date: str
    forecast_day: str  # "Day_1" to "Day_5"
    severity_color_code: Optional[int]  # 1=Red, 2=Orange, 3=Yellow, 4=Green, None if unavailable
    severity_color_name: str  # "Red", "Orange", "Yellow", "Green", "Unavailable"
    severity_level: str  # "warning_take_action", "alert_be_prepared", "watch_be_updated", "no_warning", "data_unavailable"
    phenomenon_codes: List[int]
    phenomenon_names: List[str]
    warning_text: str
    raw_balloon_text: str
    raw_color_hex: str
    source_url: str
    retrieved_at: str
    has_data: bool
    is_stale: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class IMDDistrict5DayWarningBulletin:
    """Consolidated 5-day warning bulletin for a specific Telangana district."""
    district_name: str
    district_id: str
    issue_date: str
    days: Dict[str, IMDDistrictDayWarningRecord]
    max_severity_color_name: str
    max_severity_color_code: Optional[int]
    source_attribution: str = IMD_ATTRIBUTION
    retrieved_at: str = ""
    is_fresh: bool = True

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["days"] = {k: v.to_dict() if hasattr(v, "to_dict") else v for k, v in self.days.items()}
        return d


class IMDPublicWarningAdapter:
    """
    Public website adapter for IMD Hyderabad district-wise weather warnings.
    Fetches, parses, normalizes, and caches 5-day warning bulletins for Telangana districts.
    """

    BASE_URL = "https://mausam.imd.gov.in/imd_latest/contents/districtwise-warning_mc.php"
    MC_ID = "1"  # MC Hyderabad

    def __init__(
        self,
        timeout_seconds: float = 15.0,
        cache_ttl_seconds: int = 1800,  # 30 minutes
        max_stale_hours: int = 24,
        http_client: Optional[httpx.Client] = None,
    ):
        self.timeout_seconds = timeout_seconds
        self.cache_ttl_seconds = cache_ttl_seconds
        self.max_stale_hours = max_stale_hours
        self._http_client = http_client
        # Memory cache: day_str -> (data_dict, fetched_at_datetime, page_dates_dict, issue_date_str)
        self._cache: Dict[str, Dict[str, Any]] = {}

    def _get_client(self) -> httpx.Client:
        if self._http_client is not None:
            return self._http_client
        return httpx.Client(timeout=self.timeout_seconds)

    def resolve_district_name(self, district_name: str) -> Optional[str]:
        """Resolves raw district input to canonical Telangana district name."""
        if not district_name:
            return None
        clean = district_name.strip()
        # Direct case-insensitive match
        for canonical in TELANGANA_33_IMD_DISTRICTS:
            if canonical.lower() == clean.lower():
                return canonical
        # Alias match
        alias_target = DISTRICT_ALIASES.get(clean.lower())
        if alias_target and alias_target in TELANGANA_33_IMD_DISTRICTS:
            return alias_target
        # Substring match
        for canonical in TELANGANA_33_IMD_DISTRICTS:
            if clean.lower() in canonical.lower() or canonical.lower() in clean.lower():
                return canonical
        return None

    @staticmethod
    def extract_areas_from_html(html: str) -> Optional[List[Dict[str, Any]]]:
        """
        Extracts the structured 'areas' JSON array from embedded page script.
        Uses balanced bracket matching to handle whitespace and nested objects safely.
        """
        if not html:
            return None

        # Look for "areas": [ or var areas = [
        match = re.search(r'"areas"\s*:\s*\[', html)
        if not match:
            match = re.search(r'var\s+areas\s*=\s*\[', html)
        if not match:
            match = re.search(r'areas\s*=\s*\[', html)
        if not match:
            return None

        start_bracket = html.find('[', match.start())
        if start_bracket == -1:
            return None

        depth = 0
        in_string = False
        escape = False
        end_bracket = -1

        for i in range(start_bracket, len(html)):
            char = html[i]
            if escape:
                escape = False
                continue
            if char == '\\':
                escape = True
                continue
            if char == '"':
                in_string = not in_string
                continue
            if not in_string:
                if char == '[':
                    depth += 1
                elif char == ']':
                    depth -= 1
                    if depth == 0:
                        end_bracket = i
                        break

        if end_bracket == -1:
            return None

        raw_json = html[start_bracket:end_bracket + 1]
        try:
            return json.loads(raw_json)
        except Exception as e:
            logger.warning("Failed to parse extracted areas JSON: %s", e)
            return None

    @staticmethod
    def extract_day_dates_from_html(html: str) -> Dict[str, str]:
        """
        Extracts displayed forecast dates for Day_1 to Day_5 from page radio buttons.
        Example: <input type="radio" ... value="Day_1"> November 8, 2026 -> {"Day_1": "2026-11-08"}
        """
        day_dates: Dict[str, str] = {}
        if not html:
            return day_dates

        matches = re.findall(r'<input[^>]*value=[\'"](Day_\d)[\'"][^>]*>([^<]*)', html, re.IGNORECASE)
        for val, text in matches:
            clean_text = text.strip()
            # Parse month date format e.g. "November 8, 2026"
            date_match = re.search(r'([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})', clean_text)
            if date_match:
                month_name, day_num, year_num = date_match.groups()
                try:
                    dt = datetime.strptime(f"{month_name} {day_num} {year_num}", "%B %d %Y")
                    day_dates[val] = dt.strftime("%Y-%m-%d")
                except Exception:
                    pass

        return day_dates

    def _parse_balloon_text(self, balloon_text: str) -> Tuple[List[int], List[str], str, Optional[str]]:
        """
        Extracts phenomenon codes, phenomenon names, clean text, and update date from balloonText HTML.
        Example balloonText:
        "NAGAPATTINAM :</br><img src=warning_images/01.png><p>Heavy Rain</p></img><p>Updated on:2026-11-08</p>"
        """
        if not balloon_text:
            return [], [], "Data unavailable", None

        # Extract update date if present
        update_date = None
        up_match = re.search(r'Updated on\s*:\s*(\d{4}-\d{2}-\d{2})', balloon_text, re.IGNORECASE)
        if up_match:
            update_date = up_match.group(1)

        # Check for explicit "No warning"
        if "no warning" in balloon_text.lower():
            return [1], ["No Warning"], "No warning", update_date

        # Extract hazard descriptions from <p>...</p> blocks (excluding "Updated on:")
        p_matches = re.findall(r'<p>([^<]+)</p>', balloon_text, re.IGNORECASE)
        phenomenon_codes: List[int] = []
        phenomenon_names: List[str] = []

        for p_text in p_matches:
            clean_p = p_text.strip()
            if not clean_p or clean_p.lower().startswith("updated on"):
                continue

            # Match phenomenon name (check longer/more specific names first to prevent "Heavy Rain" matching "Extremely Heavy Rain")
            matched_code = None
            clean_p_lower = clean_p.lower()

            sorted_codes = sorted(
                [c for c in IMD_PHENOMENON_CODES.keys() if c != 1],
                key=lambda c: len(IMD_PHENOMENON_CODES[c]),
                reverse=True
            )

            for code in sorted_codes:
                name = IMD_PHENOMENON_CODES[code]
                if name.lower() in clean_p_lower:
                    matched_code = code
                    break

            if matched_code:
                if matched_code not in phenomenon_codes:
                    phenomenon_codes.append(matched_code)
                    phenomenon_names.append(IMD_PHENOMENON_CODES[matched_code])
            else:
                # Retain raw text if not recognized
                phenomenon_names.append(clean_p)

        # Also check for warning_images/XX.png icons if <p> text wasn't extracted
        if not phenomenon_names:
            img_matches = re.findall(r'warning_images/0?(\d+)\.png', balloon_text, re.IGNORECASE)
            for img_code_str in img_matches:
                try:
                    c_num = int(img_code_str)
                    # Check if matches hazard code or standard IMD icon mapping
                    if c_num in IMD_PHENOMENON_CODES:
                        if c_num not in phenomenon_codes:
                            phenomenon_codes.append(c_num)
                            phenomenon_names.append(IMD_PHENOMENON_CODES[c_num])
                except ValueError:
                    pass

        warning_summary = ", ".join(phenomenon_names) if phenomenon_names else "No warning"
        if not phenomenon_codes and "no warning" in warning_summary.lower():
            phenomenon_codes = [1]

        return phenomenon_codes, phenomenon_names, warning_summary, update_date

    def parse_page_html(
        self,
        html: str,
        day: str = "Day_1",
        retrieval_url: Optional[str] = None,
        retrieval_time_iso: Optional[str] = None,
    ) -> Dict[str, IMDDistrictDayWarningRecord]:
        """
        Parses raw HTML of a districtwise-warning_mc page and returns records
        for all 33 Telangana districts.
        """
        retrieved_at = retrieval_time_iso or datetime.now(timezone.utc).astimezone(KOLKATA_TZ).isoformat()
        source_url = retrieval_url or f"{self.BASE_URL}?id={self.MC_ID}&day={day}"

        # 1. Extract areas array
        areas = self.extract_areas_from_html(html)
        if not areas:
            logger.warning("Could not extract areas JSON from HTML for %s.", day)
            return self._build_unavailable_records(day, source_url, retrieved_at)

        # Index areas by id (Obj_id) and uppercase title
        areas_by_id = {str(item.get("id")): item for item in areas if "id" in item}
        areas_by_title = {str(item.get("title")).upper().strip(): item for item in areas if "title" in item}

        # 2. Extract dates for all 5 days from page radio buttons
        page_dates = self.extract_day_dates_from_html(html)

        # Default issue date from today or page
        today_iso = datetime.now(KOLKATA_TZ).strftime("%Y-%m-%d")
        forecast_date = page_dates.get(day)

        records: Dict[str, IMDDistrictDayWarningRecord] = {}

        for canonical_name, meta in TELANGANA_33_IMD_DISTRICTS.items():
            obj_id = meta["id"]
            title = meta["title"]

            # Lookup by ID first, then title
            raw_item = areas_by_id.get(obj_id) or areas_by_title.get(title.upper())

            if not raw_item:
                # District data missing from page -> strictly UNAVAILABLE, never Green!
                records[canonical_name] = IMDDistrictDayWarningRecord(
                    district_id=obj_id,
                    district_name=canonical_name,
                    imd_district_title=title,
                    forecast_date=forecast_date or today_iso,
                    issue_date=today_iso,
                    forecast_day=day,
                    severity_color_code=None,
                    severity_color_name="Unavailable",
                    severity_level="data_unavailable",
                    phenomenon_codes=[],
                    phenomenon_names=[],
                    warning_text="Data unavailable",
                    raw_balloon_text="",
                    raw_color_hex="",
                    source_url=source_url,
                    retrieved_at=retrieved_at,
                    has_data=False,
                )
                continue

            raw_color = str(raw_item.get("color", "")).strip().upper()
            raw_balloon = str(raw_item.get("balloonText", "")).strip()

            phenom_codes, phenom_names, warn_text, update_date = self._parse_balloon_text(raw_balloon)
            issue_date = update_date or today_iso

            # If forecast_date wasn't in radio buttons, calculate from issue_date and day offset
            day_offset = int(day.replace("Day_", "")) - 1
            if not forecast_date:
                try:
                    dt_issue = datetime.strptime(issue_date, "%Y-%m-%d")
                    forecast_date = (dt_issue + timedelta(days=day_offset)).strftime("%Y-%m-%d")
                except Exception:
                    forecast_date = today_iso

            # Map severity color code strictly from hex color
            color_code = HEX_TO_SEVERITY_CODE.get(raw_color)
            if color_code is None:
                # If color is missing or unrecognized, do not assume green
                if "no warning" in warn_text.lower():
                    color_code = 4  # Green
                else:
                    color_code = None

            if color_code is not None:
                color_name = IMD_SEVERITY_COLORS.get(color_code, "Unknown")
                severity_level = IMD_SEVERITY_LEVEL_NAMES.get(color_code, "unknown")
            else:
                color_name = "Unavailable"
                severity_level = "data_unavailable"

            records[canonical_name] = IMDDistrictDayWarningRecord(
                district_id=obj_id,
                district_name=canonical_name,
                imd_district_title=title,
                forecast_date=forecast_date,
                issue_date=issue_date,
                forecast_day=day,
                severity_color_code=color_code,
                severity_color_name=color_name,
                severity_level=severity_level,
                phenomenon_codes=phenom_codes,
                phenomenon_names=phenom_names,
                warning_text=warn_text,
                raw_balloon_text=raw_balloon,
                raw_color_hex=raw_color,
                source_url=source_url,
                retrieved_at=retrieved_at,
                has_data=True,
            )

        return records

    def _build_unavailable_records(
        self, day: str, source_url: str, retrieved_at: str
    ) -> Dict[str, IMDDistrictDayWarningRecord]:
        """Builds fallback records marked as data_unavailable when fetch or parse fails."""
        today_iso = datetime.now(KOLKATA_TZ).strftime("%Y-%m-%d")
        records: Dict[str, IMDDistrictDayWarningRecord] = {}
        for canonical_name, meta in TELANGANA_33_IMD_DISTRICTS.items():
            records[canonical_name] = IMDDistrictDayWarningRecord(
                district_id=meta["id"],
                district_name=canonical_name,
                imd_district_title=meta["title"],
                forecast_date=today_iso,
                issue_date=today_iso,
                forecast_day=day,
                severity_color_code=None,
                severity_color_name="Unavailable",
                severity_level="data_unavailable",
                phenomenon_codes=[],
                phenomenon_names=[],
                warning_text="Data unavailable",
                raw_balloon_text="",
                raw_color_hex="",
                source_url=source_url,
                retrieved_at=retrieved_at,
                has_data=False,
            )
        return records

    def fetch_day_warnings(
        self, day: str = "Day_1", force_refresh: bool = False
    ) -> Dict[str, IMDDistrictDayWarningRecord]:
        """
        Fetches district warnings for all 33 Telangana districts for a specific forecast day.
        Utilizes caching to prevent hammering the official portal.
        """
        clean_day = day.strip()
        if not re.match(r"^Day_[1-5]$", clean_day):
            raise ValueError(f"Invalid forecast day '{day}'. Must be one of Day_1 to Day_5.")

        now_utc = datetime.now(timezone.utc)

        # Check cache
        if not force_refresh and clean_day in self._cache:
            cache_entry = self._cache[clean_day]
            cached_time = cache_entry["fetched_at"]
            age_seconds = (now_utc - cached_time).total_seconds()
            if age_seconds < self.cache_ttl_seconds:
                return cache_entry["records"]

        # Fetch live HTML
        target_url = f"{self.BASE_URL}?id={self.MC_ID}&day={clean_day}"
        client = self._get_client()
        should_close = (self._http_client is None)

        try:
            resp = client.get(target_url)
            retrieval_time = datetime.now(timezone.utc).astimezone(KOLKATA_TZ).isoformat()
            if resp.status_code != 200:
                logger.error("IMD public warning page returned HTTP %d for %s", resp.status_code, clean_day)
                # If cached version exists within max_stale_hours, return it marked stale
                if clean_day in self._cache:
                    cached_entry = self._cache[clean_day]
                    age_hours = (now_utc - cached_entry["fetched_at"]).total_seconds() / 3600
                    if age_hours <= self.max_stale_hours:
                        stale_records = dict(cached_entry["records"])
                        for r in stale_records.values():
                            r.is_stale = True
                        return stale_records
                return self._build_unavailable_records(clean_day, target_url, retrieval_time)

            records = self.parse_page_html(
                html=resp.text,
                day=clean_day,
                retrieval_url=target_url,
                retrieval_time_iso=retrieval_time,
            )

            # Update cache
            self._cache[clean_day] = {
                "records": records,
                "fetched_at": now_utc,
                "html": resp.text,
            }
            return records

        except (httpx.TimeoutException, httpx.RequestError) as exc:
            logger.error("Network error fetching IMD public warning page (%s): %s", clean_day, exc)
            retrieval_time = datetime.now(timezone.utc).astimezone(KOLKATA_TZ).isoformat()
            if clean_day in self._cache:
                cached_entry = self._cache[clean_day]
                age_hours = (now_utc - cached_entry["fetched_at"]).total_seconds() / 3600
                if age_hours <= self.max_stale_hours:
                    stale_records = dict(cached_entry["records"])
                    for r in stale_records.values():
                        r.is_stale = True
                    return stale_records
            return self._build_unavailable_records(clean_day, target_url, retrieval_time)
        finally:
            if should_close:
                client.close()

    def get_district_warning(
        self, district_name: str, day: str = "Day_1"
    ) -> IMDDistrictDayWarningRecord:
        """
        Retrieves official IMD warning for a specific Telangana district on a given forecast day.
        Guarantees that missing data returns 'data_unavailable' and NEVER 'Green'.
        """
        canonical_district = self.resolve_district_name(district_name)
        if not canonical_district:
            # District not recognized as a Telangana revenue district
            today_iso = datetime.now(KOLKATA_TZ).strftime("%Y-%m-%d")
            return IMDDistrictDayWarningRecord(
                district_id="unknown",
                district_name=district_name,
                imd_district_title="UNKNOWN",
                forecast_date=today_iso,
                issue_date=today_iso,
                forecast_day=day,
                severity_color_code=None,
                severity_color_name="Unavailable",
                severity_level="data_unavailable",
                phenomenon_codes=[],
                phenomenon_names=[],
                warning_text="District not recognized as a Telangana revenue district",
                raw_balloon_text="",
                raw_color_hex="",
                source_url=f"{self.BASE_URL}?id={self.MC_ID}&day={day}",
                retrieved_at=datetime.now(timezone.utc).astimezone(KOLKATA_TZ).isoformat(),
                has_data=False,
            )

        day_records = self.fetch_day_warnings(day=day)
        record = day_records.get(canonical_district)

        if not record:
            today_iso = datetime.now(KOLKATA_TZ).strftime("%Y-%m-%d")
            return IMDDistrictDayWarningRecord(
                district_id=TELANGANA_33_IMD_DISTRICTS[canonical_district]["id"],
                district_name=canonical_district,
                imd_district_title=TELANGANA_33_IMD_DISTRICTS[canonical_district]["title"],
                forecast_date=today_iso,
                issue_date=today_iso,
                forecast_day=day,
                severity_color_code=None,
                severity_color_name="Unavailable",
                severity_level="data_unavailable",
                phenomenon_codes=[],
                phenomenon_names=[],
                warning_text="Data unavailable",
                raw_balloon_text="",
                raw_color_hex="",
                source_url=f"{self.BASE_URL}?id={self.MC_ID}&day={day}",
                retrieved_at=datetime.now(timezone.utc).astimezone(KOLKATA_TZ).isoformat(),
                has_data=False,
            )

        return record

    def get_district_5day_forecast(
        self, district_name: str
    ) -> IMDDistrict5DayWarningBulletin:
        """
        Fetches the complete 5-day warning bulletin for a specific Telangana district.
        """
        canonical_district = self.resolve_district_name(district_name)
        dist_key = canonical_district or district_name
        dist_id = TELANGANA_33_IMD_DISTRICTS.get(canonical_district, {}).get("id", "unknown") if canonical_district else "unknown"

        bulletin_days: Dict[str, IMDDistrictDayWarningRecord] = {}
        max_severity_code = 4  # Default to 4 (Green) if all green, lower is more severe (1=Red)
        issue_date = datetime.now(KOLKATA_TZ).strftime("%Y-%m-%d")
        retrieved_at = datetime.now(timezone.utc).astimezone(KOLKATA_TZ).isoformat()
        is_fresh = True

        for day_idx in range(1, 6):
            day_str = f"Day_{day_idx}"
            rec = self.get_district_warning(dist_key, day=day_str)
            bulletin_days[day_str] = rec
            if rec.issue_date:
                issue_date = rec.issue_date
            if rec.retrieved_at:
                retrieved_at = rec.retrieved_at
            if rec.is_stale:
                is_fresh = False

            if rec.severity_color_code is not None:
                # 1=Red, 2=Orange, 3=Yellow, 4=Green (lower integer = higher severity)
                if rec.severity_color_code < max_severity_code:
                    max_severity_code = rec.severity_color_code

        max_color_name = IMD_SEVERITY_COLORS.get(max_severity_code, "Green")

        return IMDDistrict5DayWarningBulletin(
            district_name=dist_key,
            district_id=dist_id,
            issue_date=issue_date,
            days=bulletin_days,
            max_severity_color_name=max_color_name,
            max_severity_color_code=max_severity_code,
            source_attribution=IMD_ATTRIBUTION,
            retrieved_at=retrieved_at,
            is_fresh=is_fresh,
        )

    def format_warning_for_farmer(
        self, district_name: str, day: str = "Day_1", language: str = "Telugu"
    ) -> str:
        """
        Formats a farmer-safe, voice-ready weather warning response in the requested language.
        Rules:
        - Explicitly identifies the district.
        - Mentions forecast date and severity.
        - Provides official attribution.
        - Warns that it is general weather intelligence, not an agricultural directive.
        - Never fabricates warnings or downgrades severity.
        """
        record = self.get_district_warning(district_name, day=day)
        lang = (language or "Telugu").strip().lower()
        is_telugu = "telugu" in lang or lang.startswith("te")
        is_hindi = "hindi" in lang or lang.startswith("hi")

        if not record.has_data or record.severity_color_code is None:
            # Data unavailable
            if is_telugu:
                return (
                    f"{district_name} జిల్లాకు సంబంధించి ప్రస్తుత అధికారిక IMD వాతావరణ హెచ్చరిక సమాచారం "
                    f"పొందడం సాధ్యం కాలేదు. దయచేసి కొద్దిసేపటి తర్వాత మళ్లీ ప్రయత్నించండి.\n"
                    f"మూలం: భారత వాతావరణ శాఖ (IMD), భూ శాస్త్ర మంత్రిత్వ శాఖ, భారత ప్రభుత్వం."
                )
            elif is_hindi:
                return (
                    f"{district_name} जिले के लिए वर्तमान आधिकारिक IMD मौसम चेतावनी इस समय उपलब्ध नहीं हो सकी। "
                    f"कृपया कुछ समय बाद पुनः प्रयास करें।\n"
                    f"स्रोत: भारत मौसम विज्ञान विभाग (IMD), पृथ्वी विज्ञान मंत्रालय, भारत सरकार।"
                )
            else:
                return (
                    f"Current official IMD weather warning could not be retrieved for {district_name} District at this time. "
                    f"Please try again later.\n"
                    f"{IMD_ATTRIBUTION}"
                )

        # Active or No Warning
        code = record.severity_color_code
        color_en = IMD_SEVERITY_COLORS.get(code, "Unknown")
        guidance_en = IMD_ACTION_GUIDANCE_EN.get(code, "")
        guidance_te = IMD_ACTION_GUIDANCE_TE.get(code, "")
        guidance_hi = IMD_ACTION_GUIDANCE_HI.get(code, "")

        if code == 4:
            # Green / No Warning
            if is_telugu:
                return (
                    f"{record.district_name} జిల్లాకు {record.forecast_date} తేదీన IMD అధికారిక హెచ్చరిక: "
                    f"ఎటువంటి హెచ్చరిక లేదు (గ్రీన్ / సాధారణం). ఇది జిల్లా స్థాయి వాతావరణ సమాచారం మాత్రమే.\n"
                    f"మూలం: భారత వాతావరణ శాఖ (IMD), భూ శాస్త్ర మంత్రిత్వ శాఖ, భారత ప్రభుత్వం."
                )
            elif is_hindi:
                return (
                    f"{record.district_name} जिले के लिए {record.forecast_date} को IMD आधिकारिक चेतावनी: "
                    f"कोई चेतावनी नहीं (हरा / सामान्य)। यह केवल जिला स्तरीय मौसम की जानकारी है।\n"
                    f"स्रोत: भारत मौसम विज्ञान विभाग (IMD), पृथ्वी विज्ञान मंत्रालय, भारत सरकार।"
                )
            else:
                return (
                    f"Official IMD warning for {record.district_name} District on {record.forecast_date}: "
                    f"No Warning (Green / Normal). This is district-level weather information only.\n"
                    f"{IMD_ATTRIBUTION}"
                )

        # Non-Green Warning (Yellow, Orange, Red)
        # Translate phenomena if Telugu or Hindi
        if is_telugu:
            hazards_te = [IMD_PHENOMENON_TELUGU.get(c, record.warning_text) for c in record.phenomenon_codes]
            hazard_desc = ", ".join(hazards_te) if hazards_te else record.warning_text
            color_te_map = {1: "ఎరుపు", 2: "ఆరెంజ్", 3: "పసుపు"}
            c_te = color_te_map.get(code, color_en)
            return (
                f"{record.district_name} జిల్లాకు {record.forecast_date} తేదీన IMD హెచ్చరిక: "
                f"{c_te} ({guidance_te}) — {hazard_desc}. ఇది జిల్లా స్థాయి సమాచారం మాత్రమే.\n"
                f"మూలం: భారత వాతావరణ శాఖ (IMD), భూ శాస్త్ర మంత్రిత్వ శాఖ, భారత ప్రభుత్వం."
            )
        elif is_hindi:
            hazards_hi = [IMD_PHENOMENON_HINDI.get(c, record.warning_text) for c in record.phenomenon_codes]
            hazard_desc = ", ".join(hazards_hi) if hazards_hi else record.warning_text
            color_hi_map = {1: "लाल", 2: "नारंगी", 3: "पीला"}
            c_hi = color_hi_map.get(code, color_en)
            return (
                f"{record.district_name} जिले के लिए {record.forecast_date} को IMD चेतावनी: "
                f"{c_hi} ({guidance_hi}) — {hazard_desc}। यह केवल जिला स्तरीय मौसम की जानकारी है।\n"
                f"स्रोत: भारत मौसम विज्ञान विभाग (IMD), पृथ्वी विज्ञान मंत्रालय, भारत सरकार।"
            )
        else:
            return (
                f"Official IMD warning for {record.district_name} District on {record.forecast_date}: "
                f"{color_en} ({guidance_en}) — {record.warning_text}. This is district-level weather information only.\n"
                f"{IMD_ATTRIBUTION}"
            )
