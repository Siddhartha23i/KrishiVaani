"""
Pydantic schemas for LLM reasoning service, request validation,
evidence constraints, and structured output formatting — Phase 7.2.
"""

from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, ConfigDict, field_validator


class FarmerContextSchema(BaseModel):
    """Contextual profile information about the inquiring farmer."""
    model_config = ConfigDict(extra="ignore")

    state: str = "Telangana"
    district: Optional[str] = None
    mandal: Optional[str] = None
    village: Optional[str] = None
    crop_name: Optional[str] = None
    crop_variety: Optional[str] = None
    crop_stage: Optional[str] = None
    land_size_acres: Optional[float] = None
    soil_type: Optional[str] = None
    water_source: Optional[str] = None
    preferred_language: str = "Telugu"
    conversation_memory: Optional[str] = None


class ApprovedEvidenceItem(BaseModel):
    """Explicitly supplied approved knowledge item from the KrishiVaani knowledge base."""
    model_config = ConfigDict(extra="ignore")

    evidence_id: str = Field(description="Unique identifier for the knowledge item (e.g. KNOW-ADIL-001)")
    source_id: str = Field(description="Authoritative source ID (e.g. SRC-PJTAU-2026-11-04)")
    source_type: str = Field(description="Source organization/type (e.g. PJTAU_AGROMET_ADVISORY, TGDPS_DAILY_REPORT)")
    title: str = Field(description="Advisory title or header")
    content: str = Field(description="Approved factual text content")
    verification_status: str = Field(default="APPROVED", description="Verification status (APPROVED, PENDING, REJECTED)")
    state: str = "Telangana"
    district: Optional[str] = None
    mandal: Optional[str] = None
    village: Optional[str] = None
    crop_name: Optional[str] = None
    season: Optional[str] = None
    valid_from: Optional[str] = None  # ISO date string YYYY-MM-DD
    valid_until: Optional[str] = None # ISO date string YYYY-MM-DD
    is_expired: bool = False

    # Provenance and citation fields (Phase 7.3)
    source_url: Optional[str] = Field(default=None, description="Direct URL to authoritative source document")
    source_date: Optional[str] = Field(default=None, description="Publication date of the source document")
    reference_location: Optional[str] = Field(default=None, description="Page, table, or section reference (e.g. Page 2, Table 3)")
    citation_id: Optional[str] = Field(default=None, description="Unique citation identifier linking item to source")
    agro_climatic_zone: Optional[str] = Field(default=None, description="PJTSAU Agro-Climatic Zone if applicable")
    category: Optional[str] = Field(default=None, description="Knowledge category (e.g. crop_management, weather)")
    knowledge_type: Optional[str] = Field(default=None, description="Type (e.g. seasonal_advisory, static_reference)")


class WeatherFactItem(BaseModel):
    """Explicitly supplied weather observation or forecast fact."""
    model_config = ConfigDict(extra="ignore")

    station_name: Optional[str] = None
    district: Optional[str] = None
    mandal: Optional[str] = None
    observation_time: Optional[str] = None
    is_forecast: bool = False
    forecast_days: Optional[int] = None
    observed_rainfall_mm: Optional[float] = None
    forecast_rainfall_mm: Optional[float] = None
    temperature_c: Optional[float] = None
    summary: str = Field(description="Factual summary of the weather data")


class LLMResponseSchema(BaseModel):
    """
    Validated response schema returned by the LLM and the reasoning service.
    Contains the 7 mandatory fields required by Phase 7.2 specifications,
    plus internal metadata for observability and safety diagnostics.
    """
    model_config = ConfigDict(extra="ignore", protected_namespaces=())

    # 7 Mandatory fields
    intent: str = Field(description="Classified farmer intent")
    language: str = Field(description="Language of the response (e.g. Telugu, English, Hindi)")
    required_information: List[str] = Field(
        default_factory=list,
        description="List of essential field parameters that are missing"
    )
    supported_facts: List[str] = Field(
        default_factory=list,
        description="Factual claims directly supported by the supplied evidence"
    )
    unsupported_questions: List[str] = Field(
        default_factory=list,
        description="Questions or requests that could not be answered from evidence"
    )
    abstain: bool = Field(
        description="True if the assistant must abstain from an unsupported recommendation"
    )
    response: str = Field(
        description="Natural conversational text formatted for voice playback"
    )

    # Internal metadata for observability and safety auditing
    evidence_citations: List[str] = Field(
        default_factory=list,
        description="Evidence IDs referenced by the response"
    )
    model_id: Optional[str] = None
    latency_ms: Optional[float] = None
    validation_latency_ms: Optional[float] = Field(default=None, description="Time taken for deterministic safety validation in ms")
    usage: Dict[str, int] = Field(default_factory=dict)
    safety_violations: List[str] = Field(default_factory=list)
    safety_status: str = Field(default="UNVERIFIED", description="Safety status: PASSED, REJECTED, ABSTAINED")

    @field_validator("intent", "language", "response")
    @classmethod
    def validate_non_empty_strings(cls, v: str) -> str:
        if not isinstance(v, str) or not v.strip():
            raise ValueError("Field must be a non-empty string")
        return v.strip()


class LLMReasoningRequest(BaseModel):
    """Request payload for the LLM reasoning service."""
    model_config = ConfigDict(extra="ignore")

    farmer_question: str = Field(description="Farmer voice transcript or text query")
    language: str = Field(default="Telugu", description="Target response language")
    farmer_context: Optional[FarmerContextSchema] = None
    approved_evidence: List[ApprovedEvidenceItem] = Field(default_factory=list)
    weather_facts: List[WeatherFactItem] = Field(default_factory=list)
    as_of_date: Optional[str] = None  # ISO date string YYYY-MM-DD
    channel: Optional[str] = Field(default=None, description="Incoming channel: 'telegram', 'whatsapp', 'twilio'")
