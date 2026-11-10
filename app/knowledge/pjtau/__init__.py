"""
PJTAU Agromet Advisory Bulletin Ingestion Module.
Phase 6.3 - Automatic PJTAU Bulletin Ingestion.
"""

from app.knowledge.pjtau.schemas import (
    BulletinLanguage,
    ExtractionQuality,
    PJTAUBulletinLink,
    PJTAUPastWeather,
    PJTAUForecast,
    PJTAUWarning,
    PJTAUAgriculturalAdvice,
    PJTAUBulletinDocument,
    PJTAUIngestionSummary,
)
from app.knowledge.pjtau.adapter import (
    PJTAUSourceAdapter,
    PJTAUAdapterError,
    PJTAUArchiveFetchError,
    PJTAUDownloadError,
    PJTAUInvalidPDFError,
)
from app.knowledge.pjtau.extractor import PJTAUBulletinExtractor
from app.knowledge.pjtau.ingestion_service import PJTAUIngestionService

__all__ = [
    "BulletinLanguage",
    "ExtractionQuality",
    "PJTAUBulletinLink",
    "PJTAUPastWeather",
    "PJTAUForecast",
    "PJTAUWarning",
    "PJTAUAgriculturalAdvice",
    "PJTAUBulletinDocument",
    "PJTAUIngestionSummary",
    "PJTAUSourceAdapter",
    "PJTAUAdapterError",
    "PJTAUArchiveFetchError",
    "PJTAUDownloadError",
    "PJTAUInvalidPDFError",
    "PJTAUBulletinExtractor",
    "PJTAUIngestionService",
]

