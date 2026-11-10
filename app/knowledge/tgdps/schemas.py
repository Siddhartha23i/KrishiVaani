"""
Data models and schemas for TGDPS Daily Weather Report ingestion.
Phase 6.4 - TGDPS Daily Weather Report Discovery & Ingestion.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List, Dict, Any


class TGDPSExtractionQuality(str, Enum):
    """Extraction quality indicator for TGDPS reports."""
    GOOD = "good"
    POOR = "poor"
    CORRUPT = "corrupt"


@dataclass
class TGDPSDistrictRainfallRecord:
    """
    District-level rainfall summary from Page 2 of the TGDPS Daily Weather Report.
    Explicitly distinguished from station-level or village-level measurements.
    """
    district: str
    actual_rainfall_mm: Optional[float]
    normal_rainfall_mm: Optional[float]
    deviation_percent: Optional[float]
    cumulative_actual_mm: Optional[float]
    cumulative_normal_mm: Optional[float]
    cumulative_deviation_percent: Optional[float]
    status: Optional[str]
    rainy_days: Optional[int]
    observation_date: str
    observation_period: Optional[str] = None
    page_number: int = 2
    raw_text: str = ""


@dataclass
class TGDPSStationRainfallRecord:
    """
    Automatic Weather Station (AWS) / Mandal-level rainfall measurement from TGDPS report.
    Represents a specific reporting station/mandal; must never be inferred as village-level reading.
    """
    station_or_mandal: str
    district: str
    rainfall_mm: Optional[float]
    rainfall_unit: str = "mm"
    observation_date: str = ""
    observation_period: Optional[str] = None
    rank: Optional[int] = None
    station_identifier: Optional[str] = None
    page_number: int = 3
    raw_text: str = ""


@dataclass
class TGDPSReportDocument:
    """Structured representation of an extracted TGDPS Daily Weather Report."""
    publisher: str
    report_title: str
    report_date: str
    observation_period: str
    source_url: str
    resolved_url: str
    document_checksum: str
    extraction_quality: TGDPSExtractionQuality
    district_summaries: List[TGDPSDistrictRainfallRecord] = field(default_factory=list)
    station_observations: List[TGDPSStationRainfallRecord] = field(default_factory=list)
    state_average_rainfall_actual_mm: Optional[float] = None
    state_average_rainfall_normal_mm: Optional[float] = None
    pdf_metadata: Dict[str, Any] = field(default_factory=dict)
    raw_text_by_page: Dict[int, str] = field(default_factory=dict)
    extraction_notes: List[str] = field(default_factory=list)


@dataclass
class TGDPSReportLink:
    """Discovered link to a TGDPS weather report document."""
    displayed_label: str
    report_date: str
    original_url: str
    resolved_url: str
    raw_date_text: Optional[str] = None


@dataclass
class TGDPSIngestionSummary:
    """Execution summary for a TGDPS ingestion batch."""
    discovered_count: int = 0
    downloaded_count: int = 0
    unchanged_count: int = 0
    extracted_count: int = 0
    items_stored_count: int = 0
    failed_count: int = 0
    dry_run: bool = False
    errors: List[str] = field(default_factory=list)

