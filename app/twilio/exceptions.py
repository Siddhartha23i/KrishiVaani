"""
Custom Exception Classes for Twilio WhatsApp Integration — Phase 8.2.
"""


class TwilioError(Exception):
    """Base exception for all Twilio-related errors."""
    pass


class TwilioConfigurationError(TwilioError):
    """Raised when required Twilio configuration (e.g. Account SID, Auth Token) is missing."""
    pass


class TwilioSignatureVerificationError(TwilioError):
    """Raised when an incoming webhook signature fails X-Twilio-Signature verification."""
    pass


class TwilioMediaDownloadError(TwilioError):
    """Raised when authenticated media retrieval from Twilio fails."""
    pass


class TwilioMessageSendError(TwilioError):
    """Raised when outbound message transmission via Twilio REST API fails."""
    pass


class TwilioDuplicateMessageError(TwilioError):
    """Raised when a webhook with an already-processed MessageSid is received."""
    pass


class TwilioMediaNotFoundError(TwilioError):
    """Raised when an expiring media token is invalid, expired, or not found on disk."""
    pass


class TwilioAudioValidationError(TwilioError):
    """Raised when incoming audio from Twilio fails format, duration, or size checks."""
    pass

