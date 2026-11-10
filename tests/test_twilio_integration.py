"""
Unit and Integration Test Suite for KrishiVaani Twilio WhatsApp Sandbox Integration — Phase 8.2.

Verifies:
1. Webhook signature validation via Twilio RequestValidator.
2. Webhook callback URL reconstruction with TWILIO_WEBHOOK_PUBLIC_BASE_URL.
3. Form-encoded webhook acceptance returning valid empty TwiML (<Response></Response>).
4. Idempotency and persistence in SQLite twilio_events via MessageSid.
5. Incoming text message processing through ConversationOrchestrator.
6. Incoming voice note processing through VoicePipelineService and audio conversion.
7. Safety rejection handling: suppresses speech synthesis and sends safe guidance text.
8. Voice delivery failure fallback: sends text response if media dispatch fails.
9. Audio duration (>30s) and size (>15MB) limit enforcement.
10. Unpredictable expiring media URLs with audio/ogg MIME serving and disk cleanup.
11. Profile resolution and unification across Meta and Twilio WhatsApp formats.
12. Privacy protection: phone masking and zero raw audio persistence in SQLite.
"""

import io
import os
import time
import wave
import json
import base64
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
from twilio.request_validator import RequestValidator

from app.main import create_application
from app.core.config import settings
from app.models.farmer import FarmerModel
from app.services.farmer_service import FarmerService
from app.conversation.schemas import ConversationResponse
from app.conversation.service import ConversationOrchestrator
from app.voice.service import VoicePipelineService
from app.voice.schemas import VoiceProcessingResponse
from app.voice.exceptions import AudioDurationExceededError, AudioSizeExceededError
from app.whatsapp.audio_converter import convert_wav_bytes_to_ogg_opus
from app.twilio.exceptions import (
    TwilioError,
    TwilioConfigurationError,
    TwilioMessageSendError,
    TwilioMediaDownloadError,
    TwilioAudioValidationError,
)
from app.twilio.security import (
    verify_twilio_signature,
    build_webhook_url,
    mask_phone_number,
)
from app.twilio.media_manager import TwilioMediaManager
from app.twilio.event_repository import TwilioEventRepository
from app.twilio.client import TwilioClient
from app.twilio.service import TwilioService


def _generate_test_wav_bytes(duration_seconds: float = 1.0, sample_rate: int = 16000) -> bytes:
    """Generate in-memory linear PCM WAV audio bytes for testing."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        num_frames = int(sample_rate * duration_seconds)
        w.writeframes(b"\x00\x00" * num_frames)
    return buf.getvalue()


class TestTwilioSecurity(unittest.TestCase):
    """Tests for Twilio RequestValidator signature verification and URL reconstruction."""

    def setUp(self):
        self.auth_token = "test_auth_token_secret_12345"
        self.validator = RequestValidator(self.auth_token)
        self.url = "https://krishivaani.ngrok.app/api/v1/twilio/whatsapp/webhook"
        self.params = {
            "MessageSid": "SM1234567890abcdef",
            "From": "whatsapp:+919876543210",
            "To": "whatsapp:+14155238886",
            "Body": "వరి తెగులు నివారణ",
        }

    def test_verify_twilio_signature_valid(self):
        sig = self.validator.compute_signature(self.url, self.params)
        is_valid = verify_twilio_signature(self.url, self.params, sig, self.auth_token)
        self.assertTrue(is_valid)

    def test_verify_twilio_signature_invalid(self):
        is_valid = verify_twilio_signature(self.url, self.params, "tampered_signature", self.auth_token)
        self.assertFalse(is_valid)

    def test_verify_twilio_signature_missing_inputs(self):
        self.assertFalse(verify_twilio_signature(self.url, self.params, None, self.auth_token))
        self.assertFalse(verify_twilio_signature(self.url, self.params, "sig", None))
        self.assertFalse(verify_twilio_signature(self.url, self.params, "sig", ""))

    def test_build_webhook_url_reconstruction(self):
        request_url = "http://127.0.0.1:8000/api/v1/twilio/whatsapp/webhook"
        public_base = "https://subdomain.ngrok-free.app"
        reconstructed = build_webhook_url(request_url, public_base, "/api/v1/twilio/whatsapp/webhook")
        self.assertEqual(reconstructed, "https://subdomain.ngrok-free.app/api/v1/twilio/whatsapp/webhook")

    def test_build_webhook_url_with_query_params(self):
        request_url = "http://localhost:8000/api/v1/twilio/whatsapp/webhook?source=sandbox"
        public_base = "https://subdomain.ngrok-free.app"
        reconstructed = build_webhook_url(request_url, public_base, "/api/v1/twilio/whatsapp/webhook")
        self.assertEqual(
            reconstructed,
            "https://subdomain.ngrok-free.app/api/v1/twilio/whatsapp/webhook?source=sandbox",
        )

    def test_build_webhook_url_no_public_base(self):
        request_url = "https://api.example.com/api/v1/twilio/whatsapp/webhook"
        reconstructed = build_webhook_url(request_url, None)
        self.assertEqual(reconstructed, request_url)

    def test_mask_phone_number(self):
        self.assertEqual(mask_phone_number("whatsapp:+919876543210"), "whatsapp:+91*****210")
        self.assertEqual(mask_phone_number("+919876543210"), "+91*****210")
        self.assertEqual(mask_phone_number("123"), "***")
        self.assertEqual(mask_phone_number(None), "[UNKNOWN]")


class TestTwilioMediaManager(unittest.TestCase):
    """Tests for temporary expiring media storage and URL generation."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.media_mgr = TwilioMediaManager(
            storage_dir=Path(self.temp_dir.name),
            default_ttl=3600,
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_store_and_get_media(self):
        test_bytes = b"OggS\x00\x02\x00\x00test_opus_bytes"
        token = self.media_mgr.store_media(test_bytes)
        self.assertIsNotNone(token)
        self.assertGreater(len(token), 20)

        retrieved = self.media_mgr.get_media(token)
        self.assertEqual(retrieved, test_bytes)

    def test_media_expiration(self):
        test_bytes = b"OggS_short_lived"
        # 1-second TTL
        token = self.media_mgr.store_media(test_bytes, ttl_seconds=1)

        # Manually alter the expires_at timestamp to simulated past
        meta_file = Path(self.temp_dir.name) / f"{token}.meta.json"
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
        meta["expires_at"] = time.time() - 10  # 10 seconds ago
        meta_file.write_text(json.dumps(meta), encoding="utf-8")

        # Now get_media should detect expiration, delete files, and return None
        retrieved = self.media_mgr.get_media(token)
        self.assertIsNone(retrieved)
        self.assertFalse((Path(self.temp_dir.name) / f"{token}.ogg").exists())

    def test_cleanup_expired(self):
        test_bytes = b"OggS_cleanup_test"
        token1 = self.media_mgr.store_media(test_bytes, ttl_seconds=3600)
        token2 = self.media_mgr.store_media(test_bytes, ttl_seconds=1)

        # Expire token2
        meta2 = Path(self.temp_dir.name) / f"{token2}.meta.json"
        data = json.loads(meta2.read_text(encoding="utf-8"))
        data["expires_at"] = time.time() - 5
        meta2.write_text(json.dumps(data), encoding="utf-8")

        purged = self.media_mgr.cleanup_expired()
        self.assertEqual(purged, 1)

        # token1 should still exist
        self.assertIsNotNone(self.media_mgr.get_media(token1))
        # token2 should be gone
        self.assertIsNone(self.media_mgr.get_media(token2))

    def test_build_media_url(self):
        token = "test_sample_token_xyz"
        url = self.media_mgr.build_media_url(token, base_url="https://krishivaani.ngrok.app")
        self.assertEqual(url, f"https://krishivaani.ngrok.app/api/v1/twilio/media/{token}.ogg")

    def test_invalid_token_returns_none(self):
        self.assertIsNone(self.media_mgr.get_media(""))
        self.assertIsNone(self.media_mgr.get_media("non_existent_token_12345"))

    def test_default_instantiation_no_attribute_error(self):
        """Regression test: TwilioMediaManager() with default storage_dir must not raise AttributeError."""
        mgr = TwilioMediaManager()
        self.assertIsNotNone(mgr.storage_dir)
        self.assertTrue(mgr.storage_dir.is_absolute())
        self.assertTrue(mgr.storage_dir.exists())
        self.assertTrue(str(mgr.storage_dir).endswith("twilio_media"))


class TestTwilioEventRepository(unittest.TestCase):
    """Tests for TwilioEventRepository idempotency and SQLite persistence."""

    def setUp(self):
        self.temp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.db_path = Path(self.temp_db.name)
        self.temp_db.close()

        # Initialize schema
        from app.db.database import init_db
        init_db(self.db_path)
        self.repo = TwilioEventRepository(db_path=self.db_path)

    def tearDown(self):
        if self.db_path.exists():
            self.db_path.unlink()

    def test_record_event_and_idempotency(self):
        sid = "SM_test_unique_idempotency_01"
        is_first = self.repo.record_event(
            message_sid=sid,
            account_sid="AC12345",
            from_number="whatsapp:+919876543210",
            to_number="whatsapp:+14155238886",
            message_type="text",
            body="Hello",
        )
        self.assertTrue(is_first)

        # Second delivery of same MessageSid must be rejected
        is_second = self.repo.record_event(
            message_sid=sid,
            account_sid="AC12345",
            from_number="whatsapp:+919876543210",
            to_number="whatsapp:+14155238886",
            message_type="text",
            body="Hello retry",
        )
        self.assertFalse(is_second)

    def test_update_status(self):
        sid = "SM_status_tracking_02"
        self.repo.record_event(
            message_sid=sid,
            account_sid="AC12345",
            from_number="whatsapp:+919876543210",
            to_number="whatsapp:+14155238886",
            message_type="text",
        )

        event = self.repo.get_event(sid)
        self.assertEqual(event["status"], "RECEIVED")

        # Transition to PROCESSING
        self.repo.update_status(message_sid=sid, status="PROCESSING")
        event = self.repo.get_event(sid)
        self.assertEqual(event["status"], "PROCESSING")

        # Transition to COMPLETED
        self.repo.update_status(
            message_sid=sid,
            status="COMPLETED",
            response_summary="type=text;status=success",
        )
        event = self.repo.get_event(sid)
        self.assertEqual(event["status"], "COMPLETED")
        self.assertIsNotNone(event["processed_at"])
        self.assertEqual(event["response_summary"], "type=text;status=success")

    def test_failed_status_with_error(self):
        sid = "SM_failed_event_03"
        self.repo.record_event(
            message_sid=sid,
            account_sid="AC12345",
            from_number="whatsapp:+919876543210",
            to_number="whatsapp:+14155238886",
            message_type="audio",
        )

        self.repo.update_status(
            message_sid=sid,
            status="FAILED",
            error_message="Audio decoding failure",
        )
        event = self.repo.get_event(sid)
        self.assertEqual(event["status"], "FAILED")
        self.assertEqual(event["error_message"], "Audio decoding failure")

    def test_raw_audio_never_persisted(self):
        """Security requirement: raw audio is NEVER persisted in SQLite."""
        sid = "SM_security_no_raw_audio"
        self.repo.record_event(
            message_sid=sid,
            account_sid="AC12345",
            from_number="whatsapp:+919876543210",
            to_number="whatsapp:+14155238886",
            message_type="audio",
            media_url="https://api.twilio.com/Media/ME123",
            media_content_type="audio/ogg",
        )
        event = self.repo.get_event(sid)
        self.assertNotIn("audio_bytes", event)
        self.assertNotIn("raw_audio", event)


class TestTwilioClient(unittest.TestCase):
    """Tests for TwilioClient REST messaging and authenticated media download."""

    def setUp(self):
        self.mock_rest_client = MagicMock()
        self.client = TwilioClient(
            account_sid="AC_test_account",
            auth_token="auth_token_test",
            from_number="whatsapp:+14155238886",
            rest_client=self.mock_rest_client,
        )

    def test_send_text_message(self):
        mock_msg = MagicMock()
        mock_msg.sid = "SM_sent_text_123"
        self.mock_rest_client.messages.create.return_value = mock_msg

        sid = self.client.send_text_message("whatsapp:+919876543210", "నమస్కారం!")
        self.assertEqual(sid, "SM_sent_text_123")
        self.mock_rest_client.messages.create.assert_called_once_with(
            body="నమస్కారం!",
            from_="whatsapp:+14155238886",
            to="whatsapp:+919876543210",
        )

    def test_send_media_message_strictly_no_caption(self):
        """Section 7 requirement: Do not include a text caption with the audio message."""
        mock_msg = MagicMock()
        mock_msg.sid = "SM_sent_media_456"
        self.mock_rest_client.messages.create.return_value = mock_msg

        media_url = "https://krishivaani.ngrok.app/api/v1/twilio/media/tok123.ogg"
        sid = self.client.send_media_message("whatsapp:+919876543210", media_url)
        self.assertEqual(sid, "SM_sent_media_456")

        # Verify body is NOT passed
        call_kwargs = self.mock_rest_client.messages.create.call_args[1]
        self.assertNotIn("body", call_kwargs)
        self.assertEqual(call_kwargs["media_url"], [media_url])
        self.assertEqual(call_kwargs["from_"], "whatsapp:+14155238886")
        self.assertEqual(call_kwargs["to"], "whatsapp:+919876543210")

    @patch("requests.get")
    def test_download_media_success(self, mock_requests_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"Content-Type": "audio/ogg; codecs=opus"}
        mock_resp.iter_content.return_value = [b"OggS\x00\x02", b"audio_chunk_data"]
        mock_requests_get.return_value = mock_resp

        media_url = "https://api.twilio.com/2010-04-01/Accounts/AC123/Messages/MM123/Media/ME123"
        audio_bytes, content_type = self.client.download_media(media_url)

        self.assertEqual(audio_bytes, b"OggS\x00\x02audio_chunk_data")
        self.assertEqual(content_type, "audio/ogg")
        mock_requests_get.assert_called_once()
        call_kwargs = mock_requests_get.call_args[1]
        self.assertTrue(call_kwargs.get("allow_redirects"))

    @patch("requests.get")
    def test_download_media_failure_status(self, mock_requests_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_resp.text = "Not Found"
        mock_requests_get.return_value = mock_resp

        with self.assertRaises(TwilioMediaDownloadError):
            self.client.download_media("https://api.twilio.com/Media/missing")

    @patch("requests.get")
    def test_download_media_size_exceeded(self, mock_requests_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"Content-Type": "audio/ogg"}
        # Return a chunk exceeding 15 MB
        mock_resp.iter_content.return_value = [b"A" * (16 * 1024 * 1024)]
        mock_requests_get.return_value = mock_resp

        with self.assertRaises(TwilioAudioValidationError):
            self.client.download_media("https://api.twilio.com/Media/huge")


class TestTwilioClientError21654Regression(unittest.TestCase):
    """
    Regression tests for Twilio error 21654 (ContentSid Required).
    Verifies that:
    - Free-form text send passes only body, from_, to (no content_variables or content_sid).
    - The actual serialized HTTP form payload at the Twilio SDK transport boundary
      contains strictly {'To', 'From', 'Body'} and proves ContentVariables is absent.
    - Media send serialized HTTP form payload contains strictly {'To', 'From', 'MediaUrl'}.
    - Existing error handling and exception mapping is preserved.
    """

    def setUp(self):
        self.mock_rest_client = MagicMock()

    def _make_client(self):
        """Create TwilioClient with a mock REST client."""
        return TwilioClient(
            account_sid="AC_test_account",
            auth_token="auth_token_test",
            from_number="whatsapp:+14155238886",
            rest_client=self.mock_rest_client,
        )

    def test_free_form_send_passes_only_body_from_to(self):
        """
        Regression for error 21654: Free-form text send must pass ONLY body, from_, to.
        Must NOT include content_variables, content_sid, or any template parameters.
        """
        mock_msg = MagicMock()
        mock_msg.sid = "SM_regression_free_form"
        self.mock_rest_client.messages.create.return_value = mock_msg

        client = self._make_client()
        sid = client.send_text_message("whatsapp:+919876543210", "వరి తెగులు నివారణ చర్యలు.")

        self.assertEqual(sid, "SM_regression_free_form")

        call_kwargs = self.mock_rest_client.messages.create.call_args[1]
        self.assertEqual(call_kwargs["body"], "వరి తెగులు నివారణ చర్యలు.")
        self.assertEqual(call_kwargs["from_"], "whatsapp:+14155238886")
        self.assertEqual(call_kwargs["to"], "whatsapp:+919876543210")
        self.assertNotIn("content_variables", call_kwargs)
        self.assertNotIn("content_sid", call_kwargs)
        self.assertEqual(set(call_kwargs.keys()), {"body", "from_", "to"})

    def test_actual_serialized_http_payload_lacks_content_variables_in_free_form_mode(self):
        """
        Task 10 Regression: Captures the actual serialized HTTP form payload at the
        Twilio SDK transport boundary and proves ContentVariables is absent in free-form mode.
        """
        from twilio.rest import Client as TwilioRestClient

        # Create real TwilioRestClient but intercept http_client.request
        real_sdk_client = TwilioRestClient("AC1234567890abcdef1234567890abcdef", "test_auth_token_secret_12345")
        captured_data = {}
        captured_method = None
        captured_url = None

        def mock_request(method, url, params=None, data=None, headers=None, auth=None, timeout=None, allow_redirects=False):
            nonlocal captured_data, captured_method, captured_url
            captured_method = method
            captured_url = url
            captured_data = data or {}
            mock_resp = MagicMock()
            mock_resp.status_code = 201
            mock_resp.text = '{"sid": "SM_transport_verified", "status": "queued"}'
            return mock_resp

        real_sdk_client.http_client.request = mock_request

        client = TwilioClient(
            account_sid="AC1234567890abcdef1234567890abcdef",
            auth_token="test_auth_token_secret_12345",
            from_number="whatsapp:+14155238886",
            rest_client=real_sdk_client,
        )

        sid = client.send_text_message(
            to="whatsapp:+919876543210",
            text="నమస్కారం! వరి తెగులు సలహా.",
        )

        self.assertEqual(sid, "SM_transport_verified")
        self.assertEqual(captured_method, "POST")
        self.assertIn("/Messages.json", captured_url)

        # Verify exact form data serialized across the wire
        self.assertEqual(captured_data["To"], "whatsapp:+919876543210")
        self.assertEqual(captured_data["From"], "whatsapp:+14155238886")
        self.assertEqual(captured_data["Body"], "నమస్కారం! వరి తెగులు సలహా.")

        # PROVE ContentVariables and ContentSid are strictly absent from the serialized form payload
        self.assertNotIn("ContentVariables", captured_data)
        self.assertNotIn("content_variables", captured_data)
        self.assertNotIn("ContentSid", captured_data)
        self.assertNotIn("content_sid", captured_data)

        # PROVE the payload keys consist strictly of To, From, Body
        self.assertEqual(set(captured_data.keys()), {"To", "From", "Body"})

    def test_media_send_actual_serialized_http_payload_lacks_body_and_content_variables(self):
        """
        Task 10 Regression: Captures the actual serialized HTTP form payload for media sends
        and proves neither Body nor ContentVariables is present.
        """
        from twilio.rest import Client as TwilioRestClient

        real_sdk_client = TwilioRestClient("AC1234567890abcdef1234567890abcdef", "test_auth_token_secret_12345")
        captured_data = {}

        def mock_request(method, url, params=None, data=None, headers=None, auth=None, timeout=None, allow_redirects=False):
            nonlocal captured_data
            captured_data = data or {}
            mock_resp = MagicMock()
            mock_resp.status_code = 201
            mock_resp.text = '{"sid": "MM_transport_verified", "status": "queued"}'
            return mock_resp

        real_sdk_client.http_client.request = mock_request

        client = TwilioClient(
            account_sid="AC1234567890abcdef1234567890abcdef",
            auth_token="test_auth_token_secret_12345",
            from_number="whatsapp:+14155238886",
            rest_client=real_sdk_client,
        )

        media_url = "https://krishivaani.ngrok.app/api/v1/twilio/media/token_abc.ogg"
        sid = client.send_media_message(
            to="whatsapp:+919876543210",
            media_url=media_url,
        )

        self.assertEqual(sid, "MM_transport_verified")
        self.assertEqual(captured_data["To"], "whatsapp:+919876543210")
        self.assertEqual(captured_data["From"], "whatsapp:+14155238886")
        self.assertEqual(captured_data["MediaUrl"], [media_url])

        # PROVE Body and ContentVariables are strictly absent
        self.assertNotIn("Body", captured_data)
        self.assertNotIn("ContentVariables", captured_data)
        self.assertNotIn("ContentSid", captured_data)
        self.assertEqual(set(captured_data.keys()), {"To", "From", "MediaUrl"})

    def test_media_send_passes_only_from_to_media_url(self):
        """
        Regression: Media send kwargs must pass from_, to, media_url ONLY.
        """
        mock_msg = MagicMock()
        mock_msg.sid = "SM_regression_media"
        self.mock_rest_client.messages.create.return_value = mock_msg

        client = self._make_client()
        url = "https://krishivaani.ngrok.app/api/v1/twilio/media/token_xyz.ogg"
        sid = client.send_media_message("whatsapp:+919876543210", url)

        self.assertEqual(sid, "SM_regression_media")

        call_kwargs = self.mock_rest_client.messages.create.call_args[1]
        self.assertEqual(call_kwargs["from_"], "whatsapp:+14155238886")
        self.assertEqual(call_kwargs["to"], "whatsapp:+919876543210")
        self.assertEqual(call_kwargs["media_url"], [url])
        self.assertNotIn("body", call_kwargs)
        self.assertNotIn("content_variables", call_kwargs)
        self.assertNotIn("content_sid", call_kwargs)
        self.assertEqual(set(call_kwargs.keys()), {"from_", "to", "media_url"})

    def test_send_text_message_error_handling(self):
        """Preserves existing error handling and wraps in TwilioMessageSendError."""
        self.mock_rest_client.messages.create.side_effect = Exception("Twilio network error")
        client = self._make_client()

        with self.assertRaises(TwilioMessageSendError) as ctx:
            client.send_text_message("whatsapp:+919876543210", "పరిశోధన")

        self.assertIn("Twilio network error", str(ctx.exception))


class TestTwilioService(unittest.TestCase):
    """Tests for TwilioService message routing, conversation orchestration, and fallbacks."""

    def setUp(self):
        self.temp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.db_path = Path(self.temp_db.name)
        self.temp_db.close()

        from app.db.database import init_db
        init_db(self.db_path)

        self.temp_media_dir = tempfile.TemporaryDirectory()

        self.mock_client = MagicMock(spec=TwilioClient)
        self.event_repo = TwilioEventRepository(db_path=self.db_path)
        self.media_manager = TwilioMediaManager(storage_dir=Path(self.temp_media_dir.name))
        self.farmer_service = FarmerService(db_path=self.db_path)
        self.mock_voice_service = MagicMock(spec=VoicePipelineService)
        self.mock_orchestrator = MagicMock(spec=ConversationOrchestrator)

        self.service = TwilioService(
            client=self.mock_client,
            event_repo=self.event_repo,
            media_manager=self.media_manager,
            farmer_service=self.farmer_service,
            voice_service=self.mock_voice_service,
            orchestrator=self.mock_orchestrator,
            db_path=self.db_path,
        )

    def tearDown(self):
        self.temp_media_dir.cleanup()
        if self.db_path.exists():
            self.db_path.unlink()

    def test_twilio_service_default_instantiation_regression(self):
        """Regression test: TwilioService() with zero arguments must initialize without AttributeError."""
        svc = TwilioService()
        self.assertIsNotNone(svc.media_manager)
        self.assertIsNotNone(svc.media_manager.storage_dir)
        self.assertTrue(svc.media_manager.storage_dir.exists())
        self.assertTrue(str(svc.media_manager.storage_dir).endswith("twilio_media"))

    def test_incoming_text_message_success(self):
        # Mock orchestrator response
        mock_conv_res = MagicMock()
        mock_conv_res.intent = "AGRICULTURAL_ADVISORY"
        mock_conv_res.llm_response = MagicMock()
        mock_conv_res.llm_response.reply_text = "వరిలో అగ్గితెగులు నివారణకు ట్రైసైక్లాజోల్ పిచికారీ చేయండి."
        mock_conv_res.response_text = "వరిలో అగ్గితెగులు నివారణకు ట్రైసైక్లాజోల్ పిచికారీ చేయండి."
        self.mock_orchestrator.process_message.return_value = mock_conv_res

        payload = {
            "MessageSid": "SM_text_test_01",
            "AccountSid": "AC_test",
            "From": "whatsapp:+919876543210",
            "To": "whatsapp:+14155238886",
            "Body": "వరి తెగులు",
            "NumMedia": "0",
        }

        result = self.service.process_incoming_webhook(payload)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["message_type"], "text")
        self.assertIn("వరిలో అగ్గితెగులు నివారణకు ట్రైసైక్లాజోల్ పిచికారీ చేయండి.", result["reply_text"])

        # Verify orchestrator was called
        self.mock_orchestrator.process_message.assert_called_once()

        # In Phase 8.2.3: Inbound reply is returned via TwiML, NOT outbound REST API
        self.mock_client.send_text_message.assert_not_called()
        self.mock_client.send_media_message.assert_not_called()

        # Verify TwiML structure contains message text
        self.assertIn("<Response>", result["twiml"])
        self.assertIn("<Message>", result["twiml"])
        self.assertIn("వరిలో అగ్గితెగులు నివారణకు ట్రైసైక్లాజోల్ పిచికారీ చేయండి.", result["twiml"])

        # Verify event repository marked as COMPLETED
        event = self.event_repo.get_event("SM_text_test_01")
        self.assertEqual(event["status"], "COMPLETED")

    def test_duplicate_message_ignored(self):
        payload = {
            "MessageSid": "SM_dup_01",
            "From": "whatsapp:+919876543210",
            "To": "whatsapp:+14155238886",
            "Body": "హలో",
            "NumMedia": "0",
        }

        mock_conv_res = MagicMock()
        mock_conv_res.intent = "GREETING"
        mock_conv_res.response_text = "నమస్కారం!"
        mock_conv_res.llm_response = MagicMock(reply_text="నమస్కారం!")
        self.mock_orchestrator.process_message.return_value = mock_conv_res

        # First call: processed
        res1 = self.service.process_incoming_webhook(payload)
        self.assertEqual(res1["status"], "success")

        # Second call: duplicate ignored
        res2 = self.service.process_incoming_webhook(payload)
        self.assertEqual(res2["status"], "duplicate_ignored")
        self.assertEqual(res2["message_sid"], "SM_dup_01")
        self.assertIn("<Response></Response>", res2["twiml"])

        # Orchestrator called only once
        self.assertEqual(self.mock_orchestrator.process_message.call_count, 1)

    def test_incoming_voice_message_success(self):
        wav_bytes = _generate_test_wav_bytes(duration_seconds=1.5)
        wav_b64 = base64.b64decode  # check base64 encoding
        wav_b64_str = base64.b64encode(wav_bytes).decode("ascii")

        # Mock Twilio client download
        self.mock_client.download_media.return_value = (b"mock_ogg_input", "audio/ogg")

        # Mock VoicePipelineService
        mock_voice_res = VoiceProcessingResponse(
            status="success",
            transcript="వరికి ఏ ఎరువు వేయాలి",
            detected_language="te-IN",
            intent="FERTILIZER_GUIDANCE",
            response_text="ఎకరాకు 50 కేజీల యూరియా వేయండి.",
            audio_base64=wav_b64_str,
            audio_content_type="audio/wav",
            audio_duration_seconds=1.5,
            safety_status="PASSED",
            is_abstention=False,
            is_fallback_text_only=False,
        )
        self.mock_voice_service.process_audio_bytes.return_value = mock_voice_res

        payload = {
            "MessageSid": "SM_voice_test_01",
            "AccountSid": "AC_test",
            "From": "whatsapp:+919876543210",
            "To": "whatsapp:+14155238886",
            "NumMedia": "1",
            "MediaUrl0": "https://api.twilio.com/Media/ME999",
            "MediaContentType0": "audio/ogg",
        }

        result = self.service.process_incoming_webhook(payload)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["message_type"], "audio")
        self.assertTrue(result["voice_sent"])
        self.assertIsNotNone(result["media_url"])
        self.assertTrue(result["media_url"].endswith(".ogg"))

        # In Phase 8.2.3: Voice reply is returned via TwiML <Media>, NOT outbound REST API
        self.mock_client.send_media_message.assert_not_called()
        self.mock_client.send_text_message.assert_not_called()

        # Verify TwiML structure contains <Media> and URL
        self.assertIn("<Response>", result["twiml"])
        self.assertIn("<Message>", result["twiml"])
        self.assertIn("<Media>", result["twiml"])
        self.assertIn(result["media_url"], result["twiml"])

    def test_voice_safety_rejected_sends_text_only(self):
        """
        Requirement: When safety status is REJECTED, do NOT synthesize or send speech.
        Return safe guidance text in TwiML instead.
        """
        self.mock_client.download_media.return_value = (b"mock_audio", "audio/ogg")

        mock_voice_res = VoiceProcessingResponse(
            status="success",
            transcript="పురుగుల మందులు కలిపి కొట్టవచ్చా",
            detected_language="te-IN",
            intent="PESTICIDE_SAFETY",
            response_text="రెండు రకాల పురుగుమందులను కలపడం ప్రమాదకరం. వేర్వేరుగా మాత్రమే వాడండి.",
            audio_base64=None,
            safety_status="REJECTED",  # REJECTED
            is_abstention=True,
            is_fallback_text_only=True,
        )
        self.mock_voice_service.process_audio_bytes.return_value = mock_voice_res

        payload = {
            "MessageSid": "SM_rejected_voice_02",
            "From": "whatsapp:+919876543210",
            "To": "whatsapp:+14155238886",
            "NumMedia": "1",
            "MediaUrl0": "https://api.twilio.com/Media/unsafe",
            "MediaContentType0": "audio/ogg",
        }

        result = self.service.process_incoming_webhook(payload)
        self.assertEqual(result["status"], "safety_rejected_text_sent")
        self.assertFalse(result["voice_sent"])

        # Verify NO outbound REST calls
        self.mock_client.send_media_message.assert_not_called()
        self.mock_client.send_text_message.assert_not_called()

        # Verify safe text was returned in TwiML without <Media>
        self.assertIn("<Response>", result["twiml"])
        self.assertIn("<Message>", result["twiml"])
        self.assertNotIn("<Media>", result["twiml"])
        self.assertIn("రెండు రకాల పురుగుమందులను కలపడం ప్రమాదకరం", result["twiml"])

    def test_voice_delivery_failure_fallback_to_text(self):
        """
        Requirement: Return text TwiML fallback if voice generation/conversion fails.
        """
        wav_bytes = _generate_test_wav_bytes(duration_seconds=1.0)
        wav_b64_str = base64.b64encode(wav_bytes).decode("ascii")

        self.mock_client.download_media.return_value = (b"mock_ogg", "audio/ogg")

        mock_voice_res = VoiceProcessingResponse(
            status="success",
            transcript="పత్తి విత్తనాలు",
            detected_language="te-IN",
            intent="CROP_INFORMATION",
            response_text="పత్తికి సిఫార్సు చేసిన హైబ్రిడ్ విత్తనాలు వాడండి.",
            audio_base64=wav_b64_str,
            safety_status="PASSED",
        )
        self.mock_voice_service.process_audio_bytes.return_value = mock_voice_res

        payload = {
            "MessageSid": "SM_voice_fallback_03",
            "From": "whatsapp:+919876543210",
            "To": "whatsapp:+14155238886",
            "NumMedia": "1",
            "MediaUrl0": "https://api.twilio.com/Media/ME1",
            "MediaContentType0": "audio/ogg",
        }

        # Simulate conversion error during audio processing
        with patch("app.twilio.service.convert_wav_bytes_to_ogg_opus", side_effect=Exception("FFmpeg encoding error")):
            result = self.service.process_incoming_webhook(payload)

        self.assertEqual(result["status"], "success")
        self.assertFalse(result["voice_sent"])

        # No REST API calls
        self.mock_client.send_text_message.assert_not_called()
        self.mock_client.send_media_message.assert_not_called()

        # Verified fallback to text TwiML without <Media>
        self.assertIn("<Response>", result["twiml"])
        self.assertIn("<Message>", result["twiml"])
        self.assertNotIn("<Media>", result["twiml"])
        self.assertIn("పత్తికి సిఫార్సు చేసిన హైబ్రిడ్ విత్తనాలు వాడండి.", result["twiml"])

    def test_audio_duration_exceeded_notice(self):
        """
        Requirement: Enforce the existing 30-second duration limit.
        """
        self.mock_client.download_media.return_value = (b"mock_long_audio", "audio/ogg")
        self.mock_voice_service.process_audio_bytes.side_effect = AudioDurationExceededError(
            duration=35.0, limit=30.0
        )

        payload = {
            "MessageSid": "SM_long_audio_04",
            "From": "whatsapp:+919876543210",
            "To": "whatsapp:+14155238886",
            "NumMedia": "1",
            "MediaUrl0": "https://api.twilio.com/Media/long",
            "MediaContentType0": "audio/ogg",
        }

        result = self.service.process_incoming_webhook(payload)
        self.assertEqual(result["status"], "duration_exceeded_notice_sent")

        # No REST API calls
        self.mock_client.send_text_message.assert_not_called()

        # Sent limit notice text in TwiML
        self.assertIn("<Response>", result["twiml"])
        self.assertIn("<Message>", result["twiml"])
        self.assertIn("30 సెకన్ల", result["twiml"])

    def test_unsupported_media_guided(self):
        payload = {
            "MessageSid": "SM_image_media_05",
            "From": "whatsapp:+919876543210",
            "To": "whatsapp:+14155238886",
            "NumMedia": "1",
            "MediaUrl0": "https://api.twilio.com/Media/image1",
            "MediaContentType0": "image/jpeg",
        }

        result = self.service.process_incoming_webhook(payload)
        self.assertEqual(result["status"], "unsupported_media_guided")

        # No REST API calls
        self.mock_client.send_text_message.assert_not_called()

        # Sent guidance text in TwiML
        self.assertIn("<Response>", result["twiml"])
        self.assertIn("<Message>", result["twiml"])
        self.assertIn("వాయిస్ నోట్స్", result["twiml"])

    def test_farmer_profile_unification(self):
        """
        Farmer profile registered via Meta as '919876543210' should match
        incoming Twilio 'whatsapp:+919876543210'.
        """
        # Pre-seed farmer in DB
        farmer = FarmerModel(
            farmer_id="farmer-unified-123",
            whatsapp_user_id="919876543210",
            preferred_language="te-IN",
            village_name="Warangal Rural",
            mandal_name="Warangal",
            district_name="Warangal",
            pin_code="506001",
            location_source="manual",
            location_confirmed=True,
            consent_given=True,
            created_at="2026-11-08T00:00:00Z",
            updated_at="2026-11-08T00:00:00Z",
        )
        self.farmer_service.repository.create(farmer)

        # Incoming Twilio sender
        matched = self.service._get_or_create_farmer("whatsapp:+919876543210")
        self.assertEqual(matched.farmer_id, "farmer-unified-123")
        self.assertEqual(matched.district_name, "Warangal")


class TestTwilioApiRoutes(unittest.TestCase):
    """FastAPI integration tests for Twilio webhook and media endpoints."""

    def setUp(self):
        self.app = create_application()
        self.client = TestClient(self.app)
        self.auth_token = "test_auth_token_for_api_route"
        self.validator = RequestValidator(self.auth_token)

    @patch("app.api.routes.twilio.get_twilio_service")
    def test_webhook_post_success_twiml(self, mock_get_service):
        mock_service = MagicMock()
        mock_service.process_incoming_webhook.return_value = {
            "status": "success",
            "twiml": '<?xml version="1.0" encoding="UTF-8"?>\n<Response><Message>వరిలో అగ్గితెగులు నివారణకు ట్రైసైక్లాజోల్ పిచికారీ చేయండి.</Message></Response>',
        }
        mock_get_service.return_value = mock_service

        with patch.object(settings, "TWILIO_AUTH_TOKEN", "test_auth_token_for_api_route"), \
             patch.object(settings, "TWILIO_WEBHOOK_PUBLIC_BASE_URL", "https://krishivaani.ngrok.app"):

            url = "https://krishivaani.ngrok.app/api/v1/twilio/whatsapp/webhook"
            form_data = {
                "MessageSid": "SM_webhook_route_test",
                "From": "whatsapp:+919876543210",
                "To": "whatsapp:+14155238886",
                "Body": "వరి తెగులు",
                "NumMedia": "0",
            }
            sig = self.validator.compute_signature(url, form_data)

            response = self.client.post(
                "/api/v1/twilio/whatsapp/webhook",
                data=form_data,
                headers={"X-Twilio-Signature": sig},
            )

            self.assertEqual(response.status_code, 200)
            self.assertIn("application/xml", response.headers["content-type"])
            self.assertIn("<Response>", response.text)
            self.assertIn("<Message>", response.text)
            self.assertIn("వరిలో అగ్గితెగులు నివారణకు ట్రైసైక్లాజోల్ పిచికారీ చేయండి.", response.text)

    @patch("app.api.routes.twilio.get_twilio_service")
    def test_webhook_post_voice_returns_twiml_with_media(self, mock_get_service):
        mock_service = MagicMock()
        mock_service.process_incoming_webhook.return_value = {
            "status": "success",
            "twiml": '<?xml version="1.0" encoding="UTF-8"?>\n<Response><Message><Media>https://krishivaani.ngrok.app/api/v1/twilio/media/tok123.ogg</Media></Message></Response>',
        }
        mock_get_service.return_value = mock_service

        with patch.object(settings, "TWILIO_AUTH_TOKEN", "test_auth_token_for_api_route"), \
             patch.object(settings, "TWILIO_WEBHOOK_PUBLIC_BASE_URL", "https://krishivaani.ngrok.app"):

            url = "https://krishivaani.ngrok.app/api/v1/twilio/whatsapp/webhook"
            form_data = {
                "MessageSid": "SM_voice_route_test",
                "From": "whatsapp:+919876543210",
                "To": "whatsapp:+14155238886",
                "NumMedia": "1",
                "MediaUrl0": "https://api.twilio.com/Media/ME123",
                "MediaContentType0": "audio/ogg",
            }
            sig = self.validator.compute_signature(url, form_data)

            response = self.client.post(
                "/api/v1/twilio/whatsapp/webhook",
                data=form_data,
                headers={"X-Twilio-Signature": sig},
            )

            self.assertEqual(response.status_code, 200)
            self.assertIn("application/xml", response.headers["content-type"])
            self.assertIn("<Media>", response.text)
            self.assertIn("https://krishivaani.ngrok.app/api/v1/twilio/media/tok123.ogg", response.text)

    @patch("app.api.routes.twilio.get_twilio_service")
    def test_webhook_post_duplicate_returns_empty_twiml(self, mock_get_service):
        mock_service = MagicMock()
        mock_service.process_incoming_webhook.return_value = {
            "status": "duplicate_ignored",
            "message_sid": "SM_dup_route_test",
            "twiml": '<?xml version="1.0" encoding="UTF-8"?>\n<Response></Response>',
        }
        mock_get_service.return_value = mock_service

        with patch.object(settings, "TWILIO_AUTH_TOKEN", "test_auth_token_for_api_route"), \
             patch.object(settings, "TWILIO_WEBHOOK_PUBLIC_BASE_URL", "https://krishivaani.ngrok.app"):

            url = "https://krishivaani.ngrok.app/api/v1/twilio/whatsapp/webhook"
            form_data = {
                "MessageSid": "SM_dup_route_test",
                "From": "whatsapp:+919876543210",
                "To": "whatsapp:+14155238886",
                "Body": "hello",
                "NumMedia": "0",
            }
            sig = self.validator.compute_signature(url, form_data)

            response = self.client.post(
                "/api/v1/twilio/whatsapp/webhook",
                data=form_data,
                headers={"X-Twilio-Signature": sig},
            )

            self.assertEqual(response.status_code, 200)
            self.assertIn("application/xml", response.headers["content-type"])
            self.assertIn("<Response></Response>", response.text)

    def test_webhook_post_invalid_signature_forbidden(self):
        with patch.object(settings, "TWILIO_AUTH_TOKEN", "test_auth_token_for_api_route"), \
             patch.object(settings, "TWILIO_WEBHOOK_PUBLIC_BASE_URL", "https://krishivaani.ngrok.app"):

            form_data = {
                "MessageSid": "SM_webhook_invalid",
                "From": "whatsapp:+919876543210",
                "To": "whatsapp:+14155238886",
                "Body": "hello",
                "NumMedia": "0",
            }

            response = self.client.post(
                "/api/v1/twilio/whatsapp/webhook",
                data=form_data,
                headers={"X-Twilio-Signature": "wrong_signature_123"},
            )

            self.assertEqual(response.status_code, 403)
            self.assertIn("Invalid Twilio signature", response.text)

    @patch("app.api.routes.twilio.get_media_manager")
    def test_media_serving_endpoint_success(self, mock_get_media_mgr):
        mock_mgr = MagicMock()
        mock_mgr.get_media.return_value = b"OggS_binary_voice_note"
        mock_get_media_mgr.return_value = mock_mgr

        response = self.client.get("/api/v1/twilio/media/valid_token_123.ogg")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "audio/ogg")
        self.assertEqual(response.content, b"OggS_binary_voice_note")
        self.assertIn("reply_valid_to.ogg", response.headers.get("content-disposition", ""))

    @patch("app.api.routes.twilio.get_media_manager")
    def test_media_serving_endpoint_not_found_or_expired(self, mock_get_media_mgr):
        mock_mgr = MagicMock()
        mock_mgr.get_media.return_value = None  # Expired or not found
        mock_get_media_mgr.return_value = mock_mgr

        response = self.client.get("/api/v1/twilio/media/expired_token_456.ogg")
        self.assertEqual(response.status_code, 404)
        self.assertIn("Media not found or expired", response.text)

    def test_get_twilio_service_and_media_manager_singletons(self):
        """Regression test: FastAPI route accessors must instantiate singletons without AttributeError."""
        from app.api.routes.twilio import get_twilio_service, get_media_manager
        svc = get_twilio_service()
        mgr = get_media_manager()
        self.assertIsInstance(svc, TwilioService)
        self.assertIsInstance(mgr, TwilioMediaManager)
        self.assertTrue(mgr.storage_dir.exists())


if __name__ == "__main__":
    unittest.main()
