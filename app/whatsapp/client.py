"""
Meta WhatsApp Cloud API Client — Phase 8.1.

Implements:
1. Media metadata lookup (GET /{media_id}).
2. Authenticated media download with domain whitelist verification.
3. Media upload for voice notes (POST /{phone_number_id}/media).
4. Audio voice-note dispatch (POST /{phone_number_id}/messages).
5. Text message dispatch (POST /{phone_number_id}/messages).
6. Robust timeouts, error logging, and masked credentials.
"""

import requests
import logging
from urllib.parse import urlparse
from typing import Optional, Dict, Any, Union

from app.core.config import settings
from app.whatsapp.exceptions import (
    WhatsAppConfigurationError,
    WhatsAppMediaDownloadError,
    WhatsAppMediaUploadError,
    WhatsAppMessageSendError,
)
from app.whatsapp.schemas import WhatsAppMediaInfo
from app.whatsapp.security import mask_phone_number

logger = logging.getLogger(__name__)

# Permitted domain suffixes for media downloads (security boundary against arbitrary URLs)
ALLOWED_META_DOMAINS = (
    "facebook.com",
    "fbsbx.com",
    "fbcdn.net",
    "whatsapp.net",
    "whatsapp.com",
)


class WhatsAppCloudAPIClient:
    """
    Client for Meta's WhatsApp Business Cloud API.
    """

    def __init__(
        self,
        access_token: Optional[str] = None,
        phone_number_id: Optional[str] = None,
        graph_api_version: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout_seconds: Optional[float] = None,
    ):
        self.access_token = access_token or settings.whatsapp_access_token
        self.phone_number_id = phone_number_id or settings.whatsapp_phone_number_id
        self.graph_api_version = (
            graph_api_version or settings.whatsapp_graph_api_version or "v27.0"
        )
        self.base_url = (base_url or settings.WHATSAPP_API_BASE_URL).rstrip("/")
        self.timeout = timeout_seconds or settings.WHATSAPP_REQUEST_TIMEOUT_SECONDS

    def _get_auth_headers(self) -> Dict[str, str]:
        if not self.access_token:
            raise WhatsAppConfigurationError("WHATSAPP_ACCESS_TOKEN is missing or not configured.")
        return {
            "Authorization": f"Bearer {self.access_token}",
        }

    def is_configured(self) -> bool:
        """Check if minimum required credentials exist."""
        return bool(self.access_token and self.phone_number_id)

    def get_media_info(self, media_id: str) -> WhatsAppMediaInfo:
        """
        Query Meta Graph API for media URL and metadata.
        GET https://graph.facebook.com/{version}/{media_id}
        """
        headers = self._get_auth_headers()
        url = f"{self.base_url}/{self.graph_api_version}/{media_id}"

        try:
            resp = requests.get(url, headers=headers, timeout=self.timeout)
            if resp.status_code != 200:
                logger.error("Meta get_media_info failed | status=%d | body=%s", resp.status_code, resp.text)
                raise WhatsAppMediaDownloadError(
                    f"Failed to fetch media info for '{media_id}': HTTP {resp.status_code}"
                )
            data = resp.json()
            return WhatsAppMediaInfo(
                id=data.get("id", media_id),
                url=data["url"],
                mime_type=data.get("mime_type", "audio/ogg"),
                sha256=data.get("sha256"),
                file_size=data.get("file_size"),
            )
        except Exception as e:
            if isinstance(e, WhatsAppMediaDownloadError):
                raise
            raise WhatsAppMediaDownloadError(f"Error requesting media info for '{media_id}': {str(e)}") from e

    def download_media_bytes(self, media_url: str) -> bytes:
        """
        Download media bytes using Bearer token from Meta's authenticated URL.
        Validates that the host belongs to Meta before requesting.
        """
        headers = self._get_auth_headers()

        # Security Check: Ensure domain is Meta-owned
        parsed = urlparse(media_url)
        hostname = (parsed.hostname or "").lower()
        if not any(hostname.endswith(domain) for domain in ALLOWED_META_DOMAINS):
            logger.error("Security block: Untrusted media download domain '%s'", hostname)
            raise WhatsAppMediaDownloadError(f"Untrusted media download URL host: '{hostname}'.")

        try:
            resp = requests.get(media_url, headers=headers, timeout=self.timeout)
            if resp.status_code != 200:
                logger.error("Media download failed | status=%d", resp.status_code)
                raise WhatsAppMediaDownloadError(
                    f"Failed to download media bytes: HTTP {resp.status_code}"
                )
            return resp.content
        except Exception as e:
            if isinstance(e, WhatsAppMediaDownloadError):
                raise
            raise WhatsAppMediaDownloadError(f"Error downloading media from Meta: {str(e)}") from e

    def upload_media_bytes(
        self,
        file_bytes: bytes,
        mime_type: str = "audio/ogg",
        filename: str = "voice_note.ogg",
    ) -> str:
        """
        Upload audio file to WhatsApp Cloud API media endpoint.
        POST https://graph.facebook.com/{version}/{phone_number_id}/media
        Returns media_id.
        """
        if not self.phone_number_id:
            raise WhatsAppConfigurationError("WHATSAPP_PHONE_NUMBER_ID is not configured.")

        headers = self._get_auth_headers()
        url = f"{self.base_url}/{self.graph_api_version}/{self.phone_number_id}/media"

        data = {"messaging_product": "whatsapp", "type": mime_type}
        files = {"file": (filename, file_bytes, mime_type)}

        try:
            resp = requests.post(url, headers=headers, data=data, files=files, timeout=self.timeout)
            if resp.status_code not in (200, 201):
                logger.error("Meta media upload failed | status=%d | body=%s", resp.status_code, resp.text)
                raise WhatsAppMediaUploadError(f"Failed to upload media: HTTP {resp.status_code} - {resp.text}")

            result = resp.json()
            media_id = result.get("id")
            if not media_id:
                raise WhatsAppMediaUploadError(f"Meta media upload did not return an id: {result}")
            return media_id
        except Exception as e:
            if isinstance(e, (WhatsAppMediaUploadError, WhatsAppConfigurationError)):
                raise
            raise WhatsAppMediaUploadError(f"Error uploading media to Meta: {str(e)}") from e

    def send_voice_note(self, recipient_phone: str, media_id: str) -> Dict[str, Any]:
        """
        Send an audio voice note to a WhatsApp recipient.
        POST https://graph.facebook.com/{version}/{phone_number_id}/messages
        Payload includes type='audio' and audio.voice=True.
        """
        if not self.phone_number_id:
            raise WhatsAppConfigurationError("WHATSAPP_PHONE_NUMBER_ID is not configured.")

        headers = self._get_auth_headers()
        headers["Content-Type"] = "application/json"
        url = f"{self.base_url}/{self.graph_api_version}/{self.phone_number_id}/messages"

        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": recipient_phone.strip(),
            "type": "audio",
            "audio": {
                "id": media_id,
                "voice": True,
            },
        }

        masked = mask_phone_number(recipient_phone)
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=self.timeout)
            if resp.status_code not in (200, 201):
                logger.error("Meta send_voice_note failed to %s | status=%d | body=%s", masked, resp.status_code, resp.text)
                raise WhatsAppMessageSendError(
                    f"Failed to send voice note to {masked}: HTTP {resp.status_code} - {resp.text}"
                )
            logger.info("Sent voice note successfully to %s", masked)
            return resp.json()
        except Exception as e:
            if isinstance(e, (WhatsAppMessageSendError, WhatsAppConfigurationError)):
                raise
            raise WhatsAppMessageSendError(f"Error sending voice note to {masked}: {str(e)}") from e

    def send_text_message(
        self,
        recipient_phone: str,
        text: str,
        preview_url: bool = False,
    ) -> Dict[str, Any]:
        """
        Send a text message to a WhatsApp recipient.
        POST https://graph.facebook.com/{version}/{phone_number_id}/messages
        """
        if not self.phone_number_id:
            raise WhatsAppConfigurationError("WHATSAPP_PHONE_NUMBER_ID is not configured.")

        headers = self._get_auth_headers()
        headers["Content-Type"] = "application/json"
        url = f"{self.base_url}/{self.graph_api_version}/{self.phone_number_id}/messages"

        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": recipient_phone.strip(),
            "type": "text",
            "text": {
                "preview_url": preview_url,
                "body": text,
            },
        }

        masked = mask_phone_number(recipient_phone)
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=self.timeout)
            if resp.status_code not in (200, 201):
                logger.error("Meta send_text_message failed to %s | status=%d | body=%s", masked, resp.status_code, resp.text)
                raise WhatsAppMessageSendError(
                    f"Failed to send text message to {masked}: HTTP {resp.status_code} - {resp.text}"
                )
            logger.info("Sent text message successfully to %s", masked)
            return resp.json()
        except Exception as e:
            if isinstance(e, (WhatsAppMessageSendError, WhatsAppConfigurationError)):
                raise
            raise WhatsAppMessageSendError(f"Error sending text message to {masked}: {str(e)}") from e

