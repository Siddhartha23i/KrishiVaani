"""
Twilio REST API Client for KrishiVaani — Phase 8.2.

Handles outbound WhatsApp communication (messages, media links) and authenticated
media downloading from Twilio infrastructure using credentials.

Complies strictly with free-form WhatsApp messaging rules:
- send_text_message: passes ONLY 'body', 'from_', and 'to'.
- send_media_message: passes ONLY 'from_', 'to', and 'media_url'.
- Strictly excludes ContentVariables, ContentSid, and template parameters for
  normal replies within the 24-hour customer-service window.
"""

import logging
from typing import Optional, Tuple
import requests
from requests.auth import HTTPBasicAuth
from twilio.rest import Client as TwilioRestClient

from app.core.config import settings
from app.twilio.exceptions import (
    TwilioConfigurationError,
    TwilioMessageSendError,
    TwilioMediaDownloadError,
    TwilioAudioValidationError,
)
from app.twilio.security import mask_phone_number
from app.voice.validator import MAX_AUDIO_SIZE_BYTES

logger = logging.getLogger(__name__)


class TwilioClient:
    """
    Client for outbound Twilio WhatsApp messaging and authenticated media retrieval.

    In free-form reply mode within the 24-hour WhatsApp customer-service window,
    sends plain text replies using only body, from_, and to.
    """

    def __init__(
        self,
        account_sid: Optional[str] = None,
        auth_token: Optional[str] = None,
        from_number: Optional[str] = None,
        timeout_seconds: Optional[float] = None,
        rest_client: Optional[TwilioRestClient] = None,
    ):
        self.account_sid = account_sid or settings.twilio_account_sid
        self.auth_token = auth_token or settings.twilio_auth_token
        self.from_number = from_number or settings.twilio_whatsapp_from
        self.timeout = timeout_seconds or getattr(settings, "TWILIO_REQUEST_TIMEOUT_SECONDS", 20.0)
        self._rest_client = rest_client

    @property
    def rest_client(self) -> TwilioRestClient:
        """Lazily initialize Twilio SDK client."""
        if self._rest_client is None:
            if not self.account_sid or not self.auth_token:
                raise TwilioConfigurationError(
                    "Twilio Account SID or Auth Token is missing. Configure TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN."
                )
            self._rest_client = TwilioRestClient(self.account_sid, self.auth_token)
        return self._rest_client

    def _format_whatsapp_number(self, number: str) -> str:
        """Ensure number has 'whatsapp:' prefix."""
        clean = str(number).strip()
        if not clean.startswith("whatsapp:"):
            return f"whatsapp:{clean}"
        return clean

    def send_text_message(self, to: str, text: str) -> str:
        """
        Send a plain text WhatsApp message via Twilio Messages resource.

        Passes strictly:
          - body: message text
          - from_: sender WhatsApp address
          - to: recipient WhatsApp address

        Strictly does NOT include content_variables, content_sid, or template parameters.

        Parameters:
            to: Recipient WhatsApp number (e.g. 'whatsapp:+919876543210' or '+919876543210').
            text: Message body text.

        Returns:
            Twilio Message SID string.

        Raises:
            TwilioMessageSendError: On send failure.
        """
        if not text or not text.strip():
            raise TwilioMessageSendError("Cannot send an empty text message.")

        to_formatted = self._format_whatsapp_number(to)
        from_formatted = self._format_whatsapp_number(self.from_number)
        masked_to = mask_phone_number(to_formatted)

        # Log outgoing form-field names only (never sensitive content)
        logger.debug("Twilio messages.create form-fields: ['body', 'from_', 'to']")

        try:
            message = self.rest_client.messages.create(
                body=text,
                from_=from_formatted,
                to=to_formatted,
            )
            logger.info("Sent Twilio WhatsApp text message to %s (SID: %s)", masked_to, message.sid)
            return message.sid
        except Exception as e:
            logger.error("Failed to send Twilio WhatsApp text to %s: %s", masked_to, str(e))
            raise TwilioMessageSendError(f"Failed to send Twilio text message: {str(e)}") from e

    def send_media_message(self, to: str, media_url: str) -> str:
        """
        Send an audio/media WhatsApp message via Twilio Messages resource.
        Strictly does NOT include a text caption with audio as required by KrishiVaani voice protocol.
        Passes strictly:
          - from_: sender WhatsApp address
          - to: recipient WhatsApp address
          - media_url: list containing the public HTTPS media URL

        Strictly does NOT include body, content_variables, or content_sid.

        Parameters:
            to: Recipient WhatsApp number.
            media_url: Public HTTPS URL pointing to the temporary OGG Opus file.

        Returns:
            Twilio Message SID string.

        Raises:
            TwilioMessageSendError: On dispatch failure.
        """
        if not media_url:
            raise TwilioMessageSendError("Cannot send media message with empty media_url.")

        to_formatted = self._format_whatsapp_number(to)
        from_formatted = self._format_whatsapp_number(self.from_number)
        masked_to = mask_phone_number(to_formatted)

        # Log outgoing form-field names only (never sensitive URLs or phone numbers)
        logger.debug("Twilio messages.create form-fields: ['from_', 'to', 'media_url']")

        try:
            message = self.rest_client.messages.create(
                from_=from_formatted,
                to=to_formatted,
                media_url=[media_url],
            )
            logger.info("Dispatched Twilio WhatsApp media message to %s (SID: %s)", masked_to, message.sid)
            return message.sid
        except Exception as e:
            logger.error("Failed to dispatch Twilio WhatsApp media message to %s: %s", masked_to, str(e))
            raise TwilioMessageSendError(f"Failed to dispatch Twilio media message: {str(e)}") from e

    def download_media(self, media_url: str) -> Tuple[bytes, str]:
        """
        Download media from Twilio infrastructure securely using HTTP Basic Auth.
        Enforces maximum size <= 15 MB and handles redirects.

        Returns:
            Tuple of (audio_bytes, content_type)
        """
        if not media_url:
            raise TwilioMediaDownloadError("media_url cannot be empty.")

        auth = None
        if self.account_sid and self.auth_token:
            auth = HTTPBasicAuth(self.account_sid, self.auth_token)

        try:
            response = requests.get(
                media_url,
                auth=auth,
                stream=True,
                timeout=self.timeout,
                allow_redirects=True,
            )

            if response.status_code != 200:
                raise TwilioMediaDownloadError(
                    f"Twilio media download failed with HTTP status {response.status_code}: {response.text[:200]}"
                )

            content_type = response.headers.get("Content-Type", "").split(";")[0].strip()
            total_bytes = bytearray()

            for chunk in response.iter_content(chunk_size=65536):
                if chunk:
                    total_bytes.extend(chunk)
                    if len(total_bytes) > MAX_AUDIO_SIZE_BYTES:
                        raise TwilioAudioValidationError(
                            f"Downloaded media exceeds maximum allowed size ({MAX_AUDIO_SIZE_BYTES / (1024*1024):.0f} MB)."
                        )

            if len(total_bytes) == 0:
                raise TwilioAudioValidationError("Downloaded media payload is empty (0 bytes).")

            logger.debug("Successfully downloaded %d bytes of media (%s) from Twilio", len(total_bytes), content_type)
            return bytes(total_bytes), content_type

        except (TwilioMediaDownloadError, TwilioAudioValidationError):
            raise
        except Exception as e:
            logger.error("Error downloading Twilio media from %s: %s", media_url, str(e))
            raise TwilioMediaDownloadError(f"Failed to download Twilio media: {str(e)}") from e
