"""
Pydantic schemas for Farmer onboarding, location preview, and profile management.
"""

from typing import Optional, List
from pydantic import BaseModel, Field, ConfigDict


class InterpretedLocation(BaseModel):
    """Interpreted geographic fields from voice transcript or manual input."""
    village_name: Optional[str] = None
    mandal_name: Optional[str] = None
    district_name: Optional[str] = None
    pin_code: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None


class LocationPreviewRequest(BaseModel):
    """
    Request payload to preview and validate farmer-supplied location details
    prior to requesting confirmation and explicit storage consent.
    """
    transcript: Optional[str] = Field(
        default=None,
        description="Raw or transcribed speech text from the farmer."
    )
    village_name: Optional[str] = Field(
        default=None,
        description="Explicit village name if extracted or provided."
    )
    mandal_name: Optional[str] = Field(
        default=None,
        description="Optional mandal / block name."
    )
    district_name: Optional[str] = Field(
        default=None,
        description="Optional district name."
    )
    pin_code: Optional[str] = Field(
        default=None,
        description="Explicit 6-digit Indian PIN code."
    )
    latitude: Optional[float] = Field(
        default=None,
        description="Optional GPS latitude (from voluntary WhatsApp location pin)."
    )
    longitude: Optional[float] = Field(
        default=None,
        description="Optional GPS longitude (from voluntary WhatsApp location pin)."
    )
    location_source: str = Field(
        default="voice_transcript",
        description="Source of location info: 'voice_transcript', 'manual_text', or 'whatsapp_pin'."
    )
    preferred_language: str = Field(
        default="te-IN",
        description="Language code: 'te-IN' (Telugu) or 'hi-IN' (Hindi)."
    )


class LocationPreviewResponse(BaseModel):
    """
    Validation and preview outcome.
    Allows backend and voice interface to read back the interpreted details
    and verify if confirmation can proceed.
    """
    interpreted_location: InterpretedLocation
    pin_valid: bool
    missing_fields: List[str]
    clarification_required: bool
    location_summary: str
    ready_for_confirmation: bool


class FarmerCreateRequest(BaseModel):
    """
    Request payload to persist a farmer profile.
    STRICT PRIVACY RULE: Must contain location_confirmed=True and consent_given=True.
    """
    whatsapp_user_id: Optional[str] = Field(
        default=None,
        description="WhatsApp user ID or phone string (optional during Phase 4)."
    )
    preferred_language: str = Field(
        default="te-IN",
        description="Preferred language code ('te-IN' or 'hi-IN')."
    )
    village_name: str = Field(
        ...,
        min_length=1,
        description="Verified/confirmed village name."
    )
    mandal_name: Optional[str] = Field(
        default=None,
        description="Optional mandal name."
    )
    district_name: Optional[str] = Field(
        default=None,
        description="Optional district name."
    )
    pin_code: str = Field(
        ...,
        description="6-digit postal PIN code."
    )
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    location_source: str = Field(
        default="voice_transcript",
        description="Source of location info."
    )
    location_confirmed: bool = Field(
        ...,
        description="Farmer confirmed the interpreted location."
    )
    consent_given: bool = Field(
        ...,
        description="Explicit permission granted by the farmer to store their profile."
    )
    weather_provider_sharing_consent: bool = Field(
        default=False,
        description="Explicit consent to share location with external third-party weather providers."
    )
    weather_provider_disclosure_version: Optional[str] = Field(
        default=None,
        description="Version of disclosure statement farmer consented to."
    )


class FarmerLocationUpdateRequest(BaseModel):
    """
    Payload for updating an existing farmer's location when they move or correct details.
    """
    village_name: Optional[str] = None
    mandal_name: Optional[str] = None
    district_name: Optional[str] = None
    pin_code: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    location_source: str = "manual_text"
    location_confirmed: bool = True


class WeatherSharingConsentUpdateRequest(BaseModel):
    """
    Payload for granting or revoking third-party weather location sharing consent.
    """
    consent_given: bool = Field(..., description="Consent decision")
    disclosure_version: str = Field("v1.0", description="Version of disclosure statement")


class FarmerResponse(BaseModel):
    """
    Farmer profile response payload.
    """
    model_config = ConfigDict(from_attributes=True)

    farmer_id: str
    whatsapp_user_id: Optional[str] = None
    preferred_language: str
    village_name: str
    mandal_name: Optional[str] = None
    district_name: Optional[str] = None
    pin_code: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    location_source: str
    location_confirmed: bool
    consent_given: bool
    consent_given_at: Optional[str] = None
    weather_provider_sharing_consent: bool = False
    weather_provider_sharing_consent_at: Optional[str] = None
    weather_provider_disclosure_version: Optional[str] = None
    created_at: str
    updated_at: str

