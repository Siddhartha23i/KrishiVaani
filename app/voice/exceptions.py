"""
Custom exceptions for KrishiVaani Telugu Voice Pipeline — Phase 8.0.
"""

class VoicePipelineError(Exception):
    """Base exception for all voice pipeline operations."""
    pass


class AudioValidationError(VoicePipelineError):
    """Raised when an audio input file fails format, size, or duration checks."""
    pass


class AudioDurationExceededError(AudioValidationError):
    """
    Raised when audio duration exceeds the allowed limit (strictly 30.0 seconds).
    Gnani REST API has a strict 30-second cap; longer files must be rejected,
    never silently truncated.
    """
    def __init__(self, duration: float, limit: float = 30.0):
        super().__init__(
            f"Audio duration ({duration:.2f}s) exceeds the {limit:.0f}-second limit for voice processing. Please record a shorter message."
        )
        self.duration = duration
        self.limit = limit


class UnsupportedAudioFormatError(AudioValidationError):
    """Raised when an audio file extension or MIME type is not supported."""
    pass


class AudioSizeExceededError(AudioValidationError):
    """Raised when audio payload exceeds the maximum allowed file size."""
    pass


class EmptyTranscriptError(VoicePipelineError):
    """Raised when STT yields an empty transcript from audio input."""
    pass


class STTServiceError(VoicePipelineError):
    """Raised when STT processing encounters an API or connectivity failure."""
    pass


class TTSServiceError(VoicePipelineError):
    """Raised when TTS synthesis fails."""
    pass

