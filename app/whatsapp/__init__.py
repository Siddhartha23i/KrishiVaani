"""
KrishiVaani WhatsApp Integration Package — Phase 8.1.
"""

from app.whatsapp.exceptions import (
    WhatsAppError,
    WhatsAppConfigurationError,
    WhatsAppSignatureVerificationError,
    WhatsAppMediaDownloadError,
    WhatsAppMediaUploadError,
    WhatsAppMessageSendError,
    WhatsAppAudioConversionError,
    DuplicateMessageError,
)
from app.whatsapp.schemas import (
    WhatsAppWebhookPayload,
    WhatsAppMessage,
    WhatsAppMediaInfo,
    WhatsAppSendResult,
)
from app.whatsapp.security import (
    verify_webhook_token,
    verify_webhook_signature,
    mask_phone_number,
)
from app.whatsapp.audio_converter import (
    convert_wav_to_ogg_opus,
    convert_wav_bytes_to_ogg_opus,
    validate_audio_playability,
)
from app.whatsapp.client import WhatsAppCloudAPIClient
from app.whatsapp.event_repository import WhatsAppEventRepository
from app.whatsapp.service import WhatsAppService

__all__ = [
    "WhatsAppError",
    "WhatsAppConfigurationError",
    "WhatsAppSignatureVerificationError",
    "WhatsAppMediaDownloadError",
    "WhatsAppMediaUploadError",
    "WhatsAppMessageSendError",
    "WhatsAppAudioConversionError",
    "DuplicateMessageError",
    "WhatsAppWebhookPayload",
    "WhatsAppMessage",
    "WhatsAppMediaInfo",
    "WhatsAppSendResult",
    "verify_webhook_token",
    "verify_webhook_signature",
    "mask_phone_number",
    "convert_wav_to_ogg_opus",
    "convert_wav_bytes_to_ogg_opus",
    "validate_audio_playability",
    "WhatsAppCloudAPIClient",
    "WhatsAppEventRepository",
    "WhatsAppService",
]

