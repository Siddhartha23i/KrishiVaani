"""
Pydantic Schemas for KrishiVaani Telugu Voice Pipeline — Phase 8.0.
"""

from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, ConfigDict

from app.conversation.schemas import LocationInput, GuestWeatherConsentEvent, WeatherMetadata


class VoiceProcessingRequest(BaseModel):
    """
    Context parameters for an incoming farmer voice request.
    """
    model_config = ConfigDict(extra="ignore")

    farmer_id: Optional[str] = Field(default=None, description="Optional registered farmer profile ID")
    location: Optional[LocationInput] = Field(default=None, description="Optional confirmed location details")
    guest_consent: Optional[GuestWeatherConsentEvent] = Field(default=None, description="Optional explicit guest consent event")
    language: str = Field(default="te-IN", description="Target language code: te-IN, hi-IN, or en-IN")
    as_of_date: Optional[str] = Field(default=None, description="Optional evaluation date YYYY-MM-DD")
    channel: Optional[str] = Field(default=None, description="Incoming channel: 'telegram', 'whatsapp', 'twilio'")


class VoiceProcessingResponse(BaseModel):
    """
    Structured outcome of the end-to-end voice pipeline:
    Speech -> STT -> ConversationOrchestrator -> Safety Validation -> TTS -> Speech.
    """
    model_config = ConfigDict(extra="ignore")

    status: str = Field(default="success", description="Overall execution status: success or error")
    transcript: str = Field(description="Recognized spoken text from the farmer")
    detected_language: str = Field(default="te-IN", description="Language code detected or used")
    intent: str = Field(description="Classified conversation intent")
    response_text: str = Field(description="Conversational response text suitable for voice playback")
    audio_base64: Optional[str] = Field(default=None, description="Base64-encoded WAV response audio (linear PCM, 48kHz)")
    audio_content_type: str = Field(default="audio/wav", description="Audio MIME content type")
    audio_duration_seconds: Optional[float] = Field(default=None, description="Duration of synthesized response audio in seconds")
    input_audio_duration_seconds: Optional[float] = Field(default=None, description="Duration of input farmer audio in seconds")
    is_abstention: bool = Field(default=False, description="True if the response is an intentional safe abstention")
    safety_status: str = Field(default="PASSED", description="Safety status: PASSED, ABSTAINED, or REJECTED")
    safety_reason: Optional[str] = Field(default=None, description="Safety or abstention reason from conversation orchestrator")
    evidence_citations: List[str] = Field(default_factory=list, description="IDs of approved agricultural evidence cited")
    weather_metadata: Optional[WeatherMetadata] = Field(default=None, description="Meteorological provenance and freshness metadata")
    is_fallback_text_only: bool = Field(default=False, description="True if TTS generation failed, falling back to text without audio loss")
    stage_latencies_ms: Dict[str, Any] = Field(default_factory=dict, description="Latency breakdown across STT, Orchestration, and TTS")
    error_detail: Optional[str] = Field(default=None, description="Error detail if a component suffered graceful degradation")

