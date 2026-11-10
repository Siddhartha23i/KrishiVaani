"""
TGDPS Daily Weather Report Ingestion Package.
Phase 6.4 - Official TGDPS Daily Weather Report Discovery & Ingestion.
"""

from app.knowledge.tgdps.adapter import (
    TGDPSSourceAdapter,
    TGDPSAdapterError,
    TGDPSDiscoveryError,
    TGDPSDownloadError,
    TGDPSInvalidPDFError,
    TGDPSSecurityError,
    DEFAULT_ALLOWED_DOMAINS,
)
from app.knowledge.tgdps.extractor import (
    TGDPSReportExtractor,
    parse_rainfall_amount,
    parse_deviation_percent,
    parse_rainy_days,
)
from app.knowledge.tgdps.ingestion_service import TGDPSReportIngestionService
from app.knowledge.tgdps.schemas import (
    TGDPSDistrictRainfallRecord,
    TGDPSStationRainfallRecord,
    TGDPSReportDocument,
    TGDPSReportLink,
    TGDPSIngestionSummary,
    TGDPSExtractionQuality,
)

__all__ = [
    "TGDPSSourceAdapter",
    "TGDPSReportExtractor",
    "TGDPSReportIngestionService",
    "TGDPSDistrictRainfallRecord",
    "TGDPSStationRainfallRecord",
    "TGDPSReportDocument",
    "TGDPSReportLink",
    "TGDPSIngestionSummary",
    "TGDPSExtractionQuality",
    "TGDPSAdapterError",
    "TGDPSDiscoveryError",
    "TGDPSDownloadError",
    "TGDPSInvalidPDFError",
    "TGDPSSecurityError",
    "DEFAULT_ALLOWED_DOMAINS",
    "parse_rainfall_amount",
    "parse_deviation_percent",
    "parse_rainy_days",
]

