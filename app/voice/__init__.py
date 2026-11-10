"""
KrishiVaani Voice Pipeline Package — Phase 8.0.
"""

from app.voice.exceptions import (
    VoicePipelineError,
    AudioValidationError,
    AudioDurationExceededError,
    UnsupportedAudioFormatError,
    AudioSizeExceededError,
    EmptyTranscriptError,
    STTServiceError,
    TTSServiceError,
)
from app.voice.validator import (
    validate_audio_file,
    inspect_audio_duration,
    SUPPORTED_AUDIO_EXTENSIONS,
    MAX_AUDIO_DURATION_SECONDS,
)
from app.voice.schemas import (
    VoiceProcessingRequest,
    VoiceProcessingResponse,
)
from app.voice.service import VoicePipelineService

__all__ = [
    "VoicePipelineService",
    "VoiceProcessingRequest",
    "VoiceProcessingResponse",
    "VoicePipelineError",
    "AudioValidationError",
    "AudioDurationExceededError",
    "UnsupportedAudioFormatError",
    "AudioSizeExceededError",
    "EmptyTranscriptError",
    "STTServiceError",
    "TTSServiceError",
    "validate_audio_file",
    "inspect_audio_duration",
    "SUPPORTED_AUDIO_EXTENSIONS",
    "MAX_AUDIO_DURATION_SECONDS",
]

