"""
Exceptions for KrishiVaani WhatsApp Cloud API Integration — Phase 8.1.
"""

class WhatsAppError(Exception):
    """Base exception for WhatsApp integration."""
    pass


class WhatsAppConfigurationError(WhatsAppError):
    """Raised when required WhatsApp credentials/settings are missing."""
    pass


class WhatsAppSignatureVerificationError(WhatsAppError):
    """Raised when X-Hub-Signature-256 HMAC-SHA256 signature is invalid."""
    pass


class WhatsAppMediaDownloadError(WhatsAppError):
    """Raised when retrieving or downloading media from Meta fails."""
    pass


class WhatsAppMediaUploadError(WhatsAppError):
    """Raised when uploading media to Meta WhatsApp endpoint fails."""
    pass


class WhatsAppMessageSendError(WhatsAppError):
    """Raised when dispatching a message through Meta Graph API fails."""
    pass


class WhatsAppAudioConversionError(WhatsAppError):
    """Raised when ffmpeg conversion from WAV to OGG Opus fails."""
    pass


class DuplicateMessageError(WhatsAppError):
    """Raised when an incoming WhatsApp message ID (wamid) is already processed."""
    pass

