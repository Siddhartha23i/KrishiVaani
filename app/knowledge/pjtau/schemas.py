"""
Domain models and schema definitions for PJTAU Agromet Advisory Bulletin Ingestion.
Phase 6.3 - Automatic PJTAU Bulletin Ingestion.
"""

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Optional, List, Dict, Any


class BulletinLanguage(str, Enum):
    """Language edition of the bulletin."""
    TELUGU = "te-IN"
    ENGLISH = "en-IN"
    BILINGUAL = "te-IN,en-IN"


class ExtractionQuality(str, Enum):
    """Text extraction quality level from PDF."""
    GOOD = "good"
    POOR = "poor"
    UNRELIABLE = "unreliable"


@dataclass
class PJTAUBulletinLink:
    """Discovered advisory link from the PJTAU agromet archive web page."""
    displayed_label: str
    archive_bulletin_number: str
    archive_publication_date: str          # YYYY-MM-DD
    language: BulletinLanguage
    original_url: str                     # e.g. Google Drive view link or direct link
    resolved_url: str                     # Direct download export URL
    raw_date_text: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["language"] = self.language.value
        return d


@dataclass
class PJTAUPastWeather:
    """Section B: Observed weather details over the preceding observation window."""
    observation_period: str                # e.g. "During last three days"
    rainfall_description: str             # e.g. "light to moderate rains occurred at isolated places"
    max_temperature_c: Optional[str] = None  # e.g. "30oC to 36oC"
    min_temperature_c: Optional[str] = None  # e.g. "18oC to 25oC"
    geographical_scope: str = "different parts of the State"
    original_text: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PJTAUForecast:
    """Section C: 5-Day outlook and synoptic meteorological forecast."""
    forecast_period: str                   # e.g. "next 5 days (Based on today's forecast at 1300 hrs)"
    forecast_days_count: int = 5
    rainfall_description: str = ""        # e.g. "Light to Moderate rains very likely to occur..."
    spatial_distribution_wording: str = "" # e.g. "at many places for next 24 hours, few places for next 2 days..."
    max_temperature_c: Optional[str] = None  # e.g. "25oC to 34oC"
    min_temperature_c: Optional[str] = None  # e.g. "19oC to 24oC"
    original_text: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PJTAUWarning:
    """Section D: Day-wise weather warning for specific districts."""
    day_number: int                       # 1, 2, 3, etc.
    derived_valid_date: Optional[str] = None  # YYYY-MM-DD if reliably derived
    date_derivation_logic: Optional[str] = None  # Explanation of derivation
    explicitly_named_districts: List[str] = field(default_factory=list)
    rainfall_severity: Optional[str] = None   # Preserves original terms: "Heavy to Very Heavy", "Extremely Heavy"
    thunderstorm_lightning: Optional[str] = None  # e.g. "Thunderstorm accompanied by Lightning"
    wind_speed_gust: Optional[str] = None     # e.g. "Squally Winds of 40-50 kmph gusting to 60 kmph"
    remaining_districts_scope: Optional[str] = None  # e.g. "Gusty Winds 30-40 kmph at isolated places in remaining districts"
    spatial_coverage_wording: Optional[str] = None   # e.g. "at isolated places"
    original_text: str = ""
    page_number: int = 1

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PJTAUAgriculturalAdvice:
    """Section E: Weather-based agro advisory recommendations."""
    crop_or_group: Optional[str] = None   # e.g. "already sown rabi crops", "cotton kapas"
    crop_stage: Optional[str] = None      # e.g. "sowing", "harvesting"
    weather_condition_trigger: Optional[str] = None  # e.g. "In view of heavy rainfall forecast"
    recommended_action: str = ""          # e.g. "provide drainage channels and drain excess water"
    geographic_applicability: str = "State of Telangana"  # e.g. "above-mentioned districts"
    valid_from: Optional[str] = None      # YYYY-MM-DD
    valid_until: Optional[str] = None     # YYYY-MM-DD
    is_safety_instruction: bool = False   # True for lightning/thunderstorm safety
    original_text: str = ""
    page_number: int = 1

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PJTAUBulletinDocument:
    """Complete parsed and structured representation of an ingested PJTAU Bulletin PDF."""
    archive_bulletin_number: str
    archive_publication_date: str         # YYYY-MM-DD
    pdf_bulletin_number: Optional[str] = None
    pdf_issue_date: Optional[str] = None  # YYYY-MM-DD
    validity_start_date: Optional[str] = None
    validity_end_date: Optional[str] = None
    publisher: str = "Professor Jayashankar Telangana Agricultural University"
    research_unit: str = "Agro Climate Research Unit (ACRU), Rajendranagar"
    programme: str = "Grameen Krishi Mausam Seva (GKMS)"
    meteorological_source: Optional[str] = "Meteorological Centre, Hyderabad / India Meteorological Department"
    language: str = "te-IN,en-IN"
    original_url: str = ""
    resolved_url: str = ""
    document_checksum: str = ""           # SHA-256 of downloaded PDF
    file_size_bytes: int = 0
    page_count: int = 0
    downloaded_at: str = ""               # ISO Asia/Kolkata
    raw_pdf_path: Optional[str] = None
    telugu_extraction_quality: ExtractionQuality = ExtractionQuality.POOR
    english_extraction_quality: ExtractionQuality = ExtractionQuality.GOOD
    broken_telugu_characters_count: int = 0
    ocr_recommended_as_future_task: bool = False
    past_weather: Optional[PJTAUPastWeather] = None
    forecast: Optional[PJTAUForecast] = None
    warnings: List[PJTAUWarning] = field(default_factory=list)
    advisories: List[PJTAUAgriculturalAdvice] = field(default_factory=list)
    page_texts: Dict[int, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["telugu_extraction_quality"] = self.telugu_extraction_quality.value
        d["english_extraction_quality"] = self.english_extraction_quality.value
        return d


@dataclass
class PJTAUIngestionSummary:
    """Summary of batch ingestion execution."""
    discovered_count: int = 0
    downloaded_count: int = 0
    unchanged_count: int = 0
    failed_count: int = 0
    extracted_count: int = 0
    items_stored_count: int = 0
    dry_run: bool = False
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
