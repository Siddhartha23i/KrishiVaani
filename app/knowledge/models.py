"""
Domain models and enumeration types for KrishiVaani Agricultural Knowledge Base.
"""

from dataclasses import dataclass, asdict
from enum import Enum
from typing import Optional, List


class AuthorityStatus(str, Enum):
    """Authority status for official source institutions and documents."""
    PENDING_VERIFICATION = "pending_verification"
    APPROVED = "approved"
    REJECTED = "rejected"
    ARCHIVED = "archived"


class VerificationStatus(str, Enum):
    """Strict lifecycle verification status for agricultural knowledge items."""
    DRAFT = "draft"
    PENDING_VERIFICATION = "pending_verification"
    VERIFIED = "verified"
    EXPIRED = "expired"
    REJECTED = "rejected"


class TranslationStatus(str, Enum):
    """Translation provenance to prevent unverified machine translations being treated as authoritative."""
    ORIGINAL = "original"
    VERIFIED_HUMAN = "verified_human_translation"
    MACHINE_UNVERIFIED = "machine_translated_unverified"


class KnowledgeCategory(str, Enum):
    """Core agricultural domain categories."""
    CROP_SELECTION = "crop_selection"
    CROP_MANAGEMENT = "crop_management"
    GOVERNMENT_SCHEMES = "government_schemes"
    DROUGHT_CONTINGENCY = "drought_contingency"
    AGRICULTURAL_ADVISORY = "agricultural_advisory"


class KnowledgeType(str, Enum):
    """
    Explicit agricultural knowledge categorization distinguishing validity behaviors.
    """
    STATIC_REFERENCE = "static_reference"        # Soils, anatomy, general terminology (review cycle managed)
    SEASONAL_GUIDANCE = "seasonal_guidance"      # Sowing windows, seasonal calendars, crop selection
    TIME_BOUND_ADVISORY = "time_bound_advisory"  # Short-term pest alerts, weather precautions, urgent advisories


@dataclass
class KnowledgeSourceModel:
    """Represents an official publication or source document."""
    source_id: str
    publisher: str
    document_title: str
    source_type: str
    authority_status: str
    created_at: str
    updated_at: str
    source_url: Optional[str] = None
    published_at: Optional[str] = None
    last_checked_at: Optional[str] = None
    reviewed_by: Optional[str] = None
    review_notes: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class SourceProvenanceModel:
    """Source reference coupled with citation location (page, table, section)."""
    source_id: str
    publisher: str
    document_title: str
    source_url: Optional[str]
    source_type: str
    authority_status: str
    published_at: Optional[str]
    reference_location: Optional[str]
    reviewed_by: Optional[str] = None


@dataclass
class KnowledgeItemModel:
    """Core agricultural guidance record."""
    knowledge_id: str
    category: str
    title: str
    content: str
    language_code: str
    translation_status: str
    state: str
    verification_status: str
    created_at: str
    updated_at: str
    knowledge_type: str = "seasonal_guidance"
    district: Optional[str] = None
    mandal: Optional[str] = None
    village: Optional[str] = None
    pin_code: Optional[str] = None
    crop_name: Optional[str] = None
    crop_variety: Optional[str] = None
    crop_stage: Optional[str] = None
    season: Optional[str] = None
    season_year: Optional[int] = None
    soil_type: Optional[str] = None
    water_condition: Optional[str] = None
    applicable_from: Optional[str] = None
    applicable_until: Optional[str] = None
    publication_date: Optional[str] = None
    is_permanent_reference: bool = False
    review_cycle_days: Optional[int] = None
    last_reviewed_at: Optional[str] = None
    verified_at: Optional[str] = None
    verified_by: Optional[str] = None
    retrieval_applicability_notes: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class KnowledgeItemWithSourcesModel:
    """Knowledge item combined with its supporting authoritative source citations."""
    item: KnowledgeItemModel
    sources: List[SourceProvenanceModel]
