"""
Pydantic schemas for KrishiVaani Conversation Orchestration — Phase 7.5.

Defines structured text conversation inputs, outputs, location inputs,
weather metadata, and component latency breakdown.
"""

from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, ConfigDict, field_validator

from app.llm.schemas import FarmerContextSchema


class LocationInput(BaseModel):
    """
    Optional confirmed location input supplied directly with the request.
    NOTE: GPS coordinates or village names represent location data only;
    sharing location alone NEVER implies consent to transmit it to third-party weather providers.
    """
    model_config = ConfigDict(extra="ignore")

    district: Optional[str] = None
    state: Optional[str] = None
    mandal: Optional[str] = None
    village: Optional[str] = None
    pin_code: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    location_confirmed: bool = True
    place_name: Optional[str] = None
    named_in_message: bool = False
    # Plain caller-supplied boolean is UNTRUSTED by policy; cannot silently establish consent alone
    weather_sharing_consent: Optional[bool] = None


class GuestWeatherConsentEvent(BaseModel):
    """
    Provenance of explicit, affirmative third-party weather location sharing consent
    captured during an unauthenticated or guest session interaction.
    """
    model_config = ConfigDict(extra="ignore")

    consent_given: bool = Field(..., description="Must be True for affirmative consent")
    disclosure_version: str = Field(..., description="Version of the third-party weather disclosure presented (e.g. 'v1.0')")
    consent_timestamp: str = Field(..., description="ISO-8601 timestamp when affirmative consent was granted")
    channel: str = Field(default="interactive_prompt", description="Channel where consent was captured")
    presented_notice: Optional[str] = Field(default=None, description="Actual localized notice presented to user")


class WeatherMetadata(BaseModel):
    """Meteorological provenance, freshness, and disclaimer metadata."""
    model_config = ConfigDict(extra="ignore")

    source_name: str = Field(description="Weather provider organization or name")
    source_url: Optional[str] = Field(default=None, description="Provider source or attribution URL")
    retrieved_at: str = Field(description="ISO-8601 retrieval timestamp")
    issued_at: Optional[str] = Field(default=None, description="ISO-8601 observation/forecast issue timestamp")
    is_grid_estimate: bool = Field(default=True, description="True for numerical model/grid estimates; False for confirmed AWS")
    station_name: Optional[str] = Field(default=None, description="Physical telemetry station name if confirmed")
    freshness_status: str = Field(default="CURRENT", description="Freshness status (e.g. CURRENT, STALE)")
    disclaimer: str = Field(description="Intelligible localized end-user weather disclaimer")
    disclaimer_language: str = Field(default="te-IN", description="Language of the disclaimer")


class ConversationRequest(BaseModel):
    """Structured text conversation request payload."""
    model_config = ConfigDict(extra="ignore")

    question: str = Field(description="Farmer text query")
    language: str = Field(default="te-IN", description="Target response language: te-IN, hi-IN, or en-IN")
    farmer_id: Optional[str] = Field(default=None, description="Optional confirmed farmer ID in database")
    farmer_context: Optional[FarmerContextSchema] = Field(default=None, description="Optional pre-resolved farmer context")
    location: Optional[LocationInput] = Field(default=None, description="Optional confirmed location details")
    guest_consent: Optional[GuestWeatherConsentEvent] = Field(default=None, description="Optional explicit guest weather consent event")
    as_of_date: Optional[str] = Field(default=None, description="Optional evaluation date string YYYY-MM-DD")
    channel: Optional[str] = Field(default=None, description="Incoming channel: 'telegram', 'whatsapp', 'twilio'")

    @field_validator("question")
    @classmethod
    def validate_question(cls, v: str) -> str:
        if not isinstance(v, str) or not v.strip():
            raise ValueError("Farmer question must be a non-empty string.")
        return v.strip()


class ConversationResponse(BaseModel):
    """Structured text conversation response payload."""
    model_config = ConfigDict(extra="ignore")

    intent: str = Field(description="Detected or classified intent")
    language: str = Field(description="Language code of the response (e.g. te-IN, hi-IN, en-IN)")
    response_text: str = Field(description="Conversational response text suitable for voice playback")
    is_abstention: bool = Field(description="True if the response is an intentional safe abstention")
    evidence_citations: List[str] = Field(default_factory=list, description="IDs of approved evidence cited")
    weather_metadata: Optional[WeatherMetadata] = Field(default=None, description="Weather provenance and freshness metadata")
    safety_status: str = Field(description="Safety status: PASSED, ABSTAINED, or REJECTED")
    safety_validation_status: str = Field(default="NOT_RUN", description="Safety validation execution status: PASSED, REJECTED, ABSTAINED, or NOT_RUN")
    safety_reason: Optional[str] = Field(default=None, description="Reason for abstention or safety rejection")
    latency_breakdown_ms: Dict[str, Any] = Field(default_factory=dict, description="Processing latency by component in milliseconds")
