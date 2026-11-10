"""
Pydantic schemas for Knowledge Base query validation and response formatting.
Enhanced in Phase 5.1 with explicit knowledge types, seasonal parameters, and provenance explanations.
"""

from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, ConfigDict


class SourceProvenanceSchema(BaseModel):
    """Authoritative source metadata citation for a knowledge item."""
    model_config = ConfigDict(from_attributes=True)

    source_id: str
    publisher: str
    document_title: str
    source_url: Optional[str] = None
    source_type: str
    authority_status: str
    published_at: Optional[str] = None
    reference_location: Optional[str] = None
    reviewed_by: Optional[str] = None


class KnowledgeItemResponseSchema(BaseModel):
    """Complete knowledge record with associated provenance citations."""
    model_config = ConfigDict(from_attributes=True)

    knowledge_id: str
    category: str
    knowledge_type: str
    title: str
    content: str
    language_code: str
    translation_status: str
    state: str
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
    verification_status: str
    verified_at: Optional[str] = None
    verified_by: Optional[str] = None
    retrieval_applicability_explanation: Optional[str] = None
    applicable_region: Dict[str, Optional[str]] = Field(default_factory=dict)
    sources: List[SourceProvenanceSchema] = Field(default_factory=list)


class KnowledgeSearchFilterSchema(BaseModel):
    """Filter parameters for querying verified agricultural knowledge."""
    category: Optional[str] = None
    knowledge_type: Optional[str] = None
    crop_name: Optional[str] = None
    crop_variety: Optional[str] = None
    crop_stage: Optional[str] = None
    state: Optional[str] = "Telangana"
    district: Optional[str] = None
    mandal: Optional[str] = None
    village: Optional[str] = None
    season: Optional[str] = None
    season_year: Optional[int] = None
    planning_horizon: Optional[str] = None  # "current", "upcoming", or specific
    as_of_date: Optional[str] = None         # ISO date YYYY-MM-DD
    language_code: Optional[str] = None
    soil_type: Optional[str] = None
    water_condition: Optional[str] = None


class KnowledgeSearchResponseSchema(BaseModel):
    """Standardized search response returning matching guidance and explicit no-data messaging."""
    total_matches: int
    items: List[KnowledgeItemResponseSchema]
    message: str
    as_of_date: str
    active_season: Optional[str] = None
    season: Optional[str] = None
    season_year: Optional[int] = None
    season_start_date: Optional[str] = None
    season_end_date: Optional[str] = None
    planning_horizon: Optional[str] = None
    is_future_period: bool = False
    clarification_required: bool = False
    query_filters: Dict[str, Any]
