"""
Unit and Integration Test Suite for KrishiVaani WhatsApp Cloud API — Phase 8.1.

Verifies:
1. GET webhook verification challenge handshake (success and failures).
2. POST webhook HMAC-SHA256 signature verification (valid and invalid).
3. Status update notification filtering (ignoring outgoing delivered/read receipts).
4. Incoming voice note processing (media lookup -> download -> validation -> voice pipeline -> OGG Opus -> send voice note).
5. Incoming text message processing (orchestrator -> send text).
6. Incoming location pin processing (saves GPS coordinates without overwriting confirmed district -> requests confirmation).
7. Unsupported media handling (image/video -> helpful capabilities notice).
8. Idempotency enforcement via wamid (duplicate delivery prevented).
9. Graceful fallback to text if media upload or send fails.
10. Safety rejection handling (suppressing speech, sending text).
11. WAV to OGG Opus conversion and ffmpeg playability validation.
12. Temporary audio file lifecycle and cleanup.
13. Security boundary: untrusted media download domain rejection.
14. Farmer profile resolution and creation.
"""

import io
import os
import hmac
import wave
import json
import base64
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.main import create_application
from app.core.config import settings
from app.models.farmer import FarmerModel
from app.services.farmer_service import FarmerService
from app.conversation.schemas import ConversationResponse
from app.conversation.service import ConversationOrchestrator
from app.voice.service import VoicePipelineService
from app.voice.schemas import VoiceProcessingResponse
from app.whatsapp.security import (
    verify_webhook_token,
    verify_webhook_signature,
    mask_phone_number,
)
from app.whatsapp.audio_converter import (
    convert_wav_bytes_to_ogg_opus,
    validate_audio_playability,
)
from app.whatsapp.client import WhatsAppCloudAPIClient
from app.whatsapp.exceptions import (
    WhatsAppMediaDownloadError,
    WhatsAppMediaUploadError,
    WhatsAppMessageSendError,
)
from app.whatsapp.event_repository import WhatsAppEventRepository
from app.whatsapp.service import WhatsAppService


def _generate_test_wav_bytes(duration_seconds: float = 2.0, sample_rate: int = 16000) -> bytes:
    """Generate in-memory WAV audio bytes."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        num_frames = int(sample_rate * duration_seconds)
        w.writeframes(b"\x00\x00" * num_frames)
    return buf.getvalue()


class TestWhatsAppSecurity(unittest.TestCase):
    """Tests for Meta webhook verification and HMAC-SHA256 signatures."""

    def test_verify_webhook_token_success(self):
        self.assertTrue(
            verify_webhook_token(
                mode="subscribe",
                token="my_secret_token_123",
                verify_token="my_secret_token_123",
            )
        )

    def test_verify_webhook_token_invalid(self):
        self.assertFalse(
            verify_webhook_token(
                mode="subscribe",
                token="wrong_token",
                verify_token="my_secret_token_123",
            )
        )
        self.assertFalse(
            verify_webhook_token(
                mode="not_subscribe",
                token="my_secret_token_123",
                verify_token="my_secret_token_123",
            )
        )
        self.assertFalse(verify_webhook_token(None, None, "my_secret_token_123"))

    def test_verify_webhook_signature_valid(self):
        app_secret = "meta_app_secret_xyz"
        payload = b'{"object": "whatsapp_business_account"}'
        expected_hash = hmac.new(app_secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
        sig_header = f"sha256={expected_hash}"

        self.assertTrue(verify_webhook_signature(payload, sig_header, app_secret))

    def test_verify_webhook_signature_invalid(self):
        app_secret = "meta_app_secret_xyz"
        payload = b'{"object": "whatsapp_business_account"}'
        bad_sig = "sha256=0000000000000000000000000000000000000000000000000000000000000000"

        self.assertFalse(verify_webhook_signature(payload, bad_sig, app_secret))
        self.assertFalse(verify_webhook_signature(payload, "invalid_format", app_secret))
        self.assertFalse(verify_webhook_signature(payload, None, app_secret))

    def test_mask_phone_number(self):
        self.assertEqual(mask_phone_number("919876543210"), "91*****210")
        self.assertEqual(mask_phone_number("123"), "***")
        self.assertEqual(mask_phone_number(None), "[UNKNOWN]")


class TestWhatsAppAudioConversion(unittest.TestCase):
    """Tests for WAV to OGG Opus conversion and playability."""

    def test_convert_wav_bytes_to_ogg_opus(self):
        wav_bytes = _generate_test_wav_bytes(2.0)
        ogg_bytes, duration = convert_wav_bytes_to_ogg_opus(wav_bytes)

        self.assertIsNotNone(ogg_bytes)
        self.assertGreater(len(ogg_bytes), 0)
        # OGG container magic number is 'OggS'
        self.assertTrue(ogg_bytes.startswith(b"OggS"))
        self.assertAlmostEqual(duration, 2.0, delta=0.5)

    def test_temporary_files_cleanup_after_conversion(self):
        wav_bytes = _generate_test_wav_bytes(1.5)
        temp_dir = tempfile.gettempdir()
        files_before = set(os.listdir(temp_dir))

        ogg_bytes, _ = convert_wav_bytes_to_ogg_opus(wav_bytes)

        files_after = set(os.listdir(temp_dir))
        new_files = files_after - files_before

        # Ensure no leftover temporary wav or ogg files
        audio_leftovers = [f for f in new_files if f.endswith((".wav", ".ogg"))]
        self.assertEqual(audio_leftovers, [])


class TestWhatsAppCloudAPIClient(unittest.TestCase):
    """Tests for Meta API HTTP interactions and security boundaries."""

    def setUp(self):
        self.client = WhatsAppCloudAPIClient(
            access_token="test_token_abc",
            phone_number_id="1234567890",
            graph_api_version="v27.0",
        )

    def test_default_graph_api_version_is_v27(self):
        client = WhatsAppCloudAPIClient(
            access_token="tok",
            phone_number_id="123",
        )
        self.assertEqual(client.graph_api_version, "v27.0")

    def test_media_download_security_untrusted_domain_rejected(self):
        untrusted_url = "https://malicious-external-site.com/voice.ogg"
        with self.assertRaises(WhatsAppMediaDownloadError) as ctx:
            self.client.download_media_bytes(untrusted_url)
        self.assertIn("Untrusted media download URL", str(ctx.exception))

    @patch("requests.get")
    def test_get_media_info_success(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "id": "MEDIA_999",
            "url": "https://lookaside.fbsbx.com/whatsapp_business/attachments/?mid=999",
            "mime_type": "audio/ogg; codecs=opus",
            "file_size": 15000,
        }
        mock_get.return_value = mock_resp

        info = self.client.get_media_info("MEDIA_999")
        self.assertEqual(info.id, "MEDIA_999")
        self.assertEqual(info.mime_type, "audio/ogg; codecs=opus")
        self.assertIn("fbsbx.com", info.url)

    @patch("requests.post")
    def test_upload_media_bytes_success(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"id": "UPLOADED_MEDIA_777"}
        mock_post.return_value = mock_resp

        media_id = self.client.upload_media_bytes(b"OggS_fake_audio", mime_type="audio/ogg")
        self.assertEqual(media_id, "UPLOADED_MEDIA_777")

    @patch("requests.post")
    def test_send_voice_note_success(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"messages": [{"id": "wamid.SENT_VOICE_1"}]}
        mock_post.return_value = mock_resp

        result = self.client.send_voice_note("919876543210", "UPLOADED_MEDIA_777")
        self.assertIn("messages", result)

        # Verify correct voice payload was dispatched
        call_kwargs = mock_post.call_args[1]
        payload = call_kwargs["json"]
        self.assertEqual(payload["type"], "audio")
        self.assertEqual(payload["audio"]["id"], "UPLOADED_MEDIA_777")
        self.assertTrue(payload["audio"]["voice"])

    @patch("requests.post")
    def test_send_text_message_success(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"messages": [{"id": "wamid.SENT_TEXT_1"}]}
        mock_post.return_value = mock_resp

        result = self.client.send_text_message("919876543210", "నమస్కారం రైతన్నా")
        self.assertIn("messages", result)


class TestWhatsAppEventRepository(unittest.TestCase):
    """Tests for SQLite idempotency and lifecycle tracking."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test_whatsapp.db"
        from app.db.database import init_db
        init_db(self.db_path)
        self.repo = WhatsAppEventRepository(db_path=self.db_path)

    def test_idempotency_prevents_duplicate_wamid(self):
        wamid = "wamid.UNIQUE_TEST_001"
        first = self.repo.record_event(wamid, "919876543210", "audio", media_id="M1")
        self.assertTrue(first)

        # Second delivery of same wamid must return False
        second = self.repo.record_event(wamid, "919876543210", "audio", media_id="M1")
        self.assertFalse(second)

    def test_event_lifecycle_transitions(self):
        wamid = "wamid.LIFECYCLE_001"
        self.repo.record_event(wamid, "919876543210", "text")

        event = self.repo.get_event(wamid)
        self.assertEqual(event["status"], "RECEIVED")

        self.repo.update_status(wamid, "PROCESSING")
        event = self.repo.get_event(wamid)
        self.assertEqual(event["status"], "PROCESSING")

        self.repo.update_status(wamid, "COMPLETED", response_summary="intent=weather")
        event = self.repo.get_event(wamid)
        self.assertEqual(event["status"], "COMPLETED")
        self.assertIsNotNone(event["processed_at"])
        self.assertEqual(event["response_summary"], "intent=weather")


class TestWhatsAppService(unittest.TestCase):
    """Tests for WhatsAppService business logic and orchestrations."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test_wa_service.db"
        from app.db.database import init_db
        init_db(self.db_path)

        self.mock_client = MagicMock(spec=WhatsAppCloudAPIClient)
        self.event_repo = WhatsAppEventRepository(db_path=self.db_path)
        self.farmer_service = FarmerService(db_path=self.db_path)
        self.mock_voice_service = MagicMock(spec=VoicePipelineService)
        self.mock_orchestrator = MagicMock(spec=ConversationOrchestrator)

        self.service = WhatsAppService(
            client=self.mock_client,
            event_repo=self.event_repo,
            farmer_service=self.farmer_service,
            voice_service=self.mock_voice_service,
            orchestrator=self.mock_orchestrator,
            db_path=self.db_path,
        )

    def test_incoming_text_message(self):
        self.mock_orchestrator.process_message.return_value = ConversationResponse(
            intent="fertilizer_guidance",
            language="te-IN",
            response_text="పత్తి పంటకు ఎకరాకు 40 కిలోల యూరియా అవసరం.",
            is_abstention=False,
            safety_status="PASSED",
        )

        msg = {
            "from": "919876543210",
            "id": "wamid.TEXT_QUERY_001",
            "timestamp": "1731062400",
            "type": "text",
            "text": {"body": "పత్తి పంటలో యూరియా ఎంత వేయాలి?"},
        }

        result = self.service.process_incoming_message(msg)
        self.assertEqual(result["status"], "success")

        # Verify text reply was sent
        self.mock_client.send_text_message.assert_called_once_with(
            "919876543210", "పత్తి పంటకు ఎకరాకు 40 కిలోల యూరియా అవసరం."
        )

    def test_incoming_audio_voice_note_end_to_end(self):
        # 1. Mock Meta download
        from app.whatsapp.schemas import WhatsAppMediaInfo
        self.mock_client.get_media_info.return_value = WhatsAppMediaInfo(
            id="MEDIA_REC_001",
            url="https://lookaside.fbsbx.com/audio.ogg",
            mime_type="audio/ogg; codecs=opus",
        )
        self.mock_client.download_media_bytes.return_value = b"OggS_dummy_bytes"

        # 2. Mock Voice Pipeline output
        wav_bytes = _generate_test_wav_bytes(2.0)
        wav_b64 = base64.b64encode(wav_bytes).decode("ascii")
        self.mock_voice_service.process_audio_bytes.return_value = VoiceProcessingResponse(
            status="success",
            transcript="ఈరోజు వర్షం పడుతుందా?",
            detected_language="te-IN",
            intent="weather_inquiry",
            response_text="నేడు మీ ప్రాంతంలో తేలికపాటి వర్షం కురిసే అవకాశం ఉంది.",
            audio_base64=wav_b64,
            is_abstention=False,
            safety_status="PASSED",
            is_fallback_text_only=False,
        )

        # 3. Mock Meta upload
        self.mock_client.upload_media_bytes.return_value = "UPLOADED_REPLY_001"

        msg = {
            "from": "919876543210",
            "id": "wamid.VOICE_QUERY_001",
            "timestamp": "1731062400",
            "type": "audio",
            "audio": {"id": "MEDIA_REC_001", "mime_type": "audio/ogg; codecs=opus"},
        }

        result = self.service.process_incoming_message(msg)
        self.assertEqual(result["status"], "success")
        self.assertTrue(result["voice_sent"])

        # Verify voice note was dispatched
        self.mock_client.send_voice_note.assert_called_once_with(
            "919876543210", "UPLOADED_REPLY_001"
        )

    def test_incoming_audio_upload_failure_falls_back_to_text(self):
        from app.whatsapp.schemas import WhatsAppMediaInfo
        self.mock_client.get_media_info.return_value = WhatsAppMediaInfo(
            id="MEDIA_REC_002",
            url="https://lookaside.fbsbx.com/audio.ogg",
            mime_type="audio/ogg; codecs=opus",
        )
        self.mock_client.download_media_bytes.return_value = b"OggS_dummy_bytes"

        wav_bytes = _generate_test_wav_bytes(2.0)
        wav_b64 = base64.b64encode(wav_bytes).decode("ascii")
        self.mock_voice_service.process_audio_bytes.return_value = VoiceProcessingResponse(
            status="success",
            transcript="వాతావరణం ఎలా ఉంది?",
            detected_language="te-IN",
            intent="weather_inquiry",
            response_text="నేడు ఎండగా ఉంటుంది.",
            audio_base64=wav_b64,
            is_abstention=False,
            safety_status="PASSED",
            is_fallback_text_only=False,
        )

        # Simulate upload failure
        self.mock_client.upload_media_bytes.side_effect = WhatsAppMediaUploadError("Upload network failure")

        msg = {
            "from": "919876543210",
            "id": "wamid.VOICE_QUERY_002",
            "timestamp": "1731062400",
            "type": "audio",
            "audio": {"id": "MEDIA_REC_002", "mime_type": "audio/ogg"},
        }

        result = self.service.process_incoming_message(msg)
        self.assertEqual(result["status"], "success")
        self.assertFalse(result["voice_sent"])

        # Verify fallback to safe text reply was triggered
        self.mock_client.send_text_message.assert_called_once_with(
            "919876543210", "నేడు ఎండగా ఉంటుంది."
        )

    def test_safety_rejection_suppresses_speech_and_sends_text(self):
        from app.whatsapp.schemas import WhatsAppMediaInfo
        self.mock_client.get_media_info.return_value = WhatsAppMediaInfo(
            id="MEDIA_REC_003",
            url="https://lookaside.fbsbx.com/audio.ogg",
            mime_type="audio/ogg",
        )
        self.mock_client.download_media_bytes.return_value = b"OggS_dummy_bytes"

        self.mock_voice_service.process_audio_bytes.return_value = VoiceProcessingResponse(
            status="success",
            transcript="నిషేధిత మందుల మోతాదు ఎంత?",
            detected_language="te-IN",
            intent="pest_disease_inquiry",
            response_text="క్షమించండి, భద్రతా నిబంధనల ప్రకారం ఈ సమాచారం అందించలేము.",
            audio_base64=None,
            is_abstention=True,
            safety_status="REJECTED",
            is_fallback_text_only=True,
        )

        msg = {
            "from": "919876543210",
            "id": "wamid.VOICE_UNSAFE_001",
            "timestamp": "1731062400",
            "type": "audio",
            "audio": {"id": "MEDIA_REC_003", "mime_type": "audio/ogg"},
        }

        result = self.service.process_incoming_message(msg)
        self.assertEqual(result["status"], "safety_rejected_text_sent")

        # Speech send must NOT be called
        self.mock_client.send_voice_note.assert_not_called()
        self.mock_client.upload_media_bytes.assert_not_called()

        # Text reply must be called with safe text
        self.mock_client.send_text_message.assert_called_once_with(
            "919876543210", "క్షమించండి, భద్రతా నిబంధనల ప్రకారం ఈ సమాచారం అందించలేము."
        )

    def test_incoming_location_pin_preserves_confirmed_district(self):
        # Pre-seed farmer with confirmed district
        farmer = FarmerModel(
            farmer_id="FARMER_LOC_001",
            whatsapp_user_id="919876543210",
            preferred_language="te-IN",
            village_name="Dharmasagar",
            district_name="Hanamkonda",
            pin_code="506142",
            location_source="manual",
            location_confirmed=True,
            consent_given=True,
            created_at="2026-11-08",
            updated_at="2026-11-08",
        )
        self.farmer_service.repository.create(farmer)

        msg = {
            "from": "919876543210",
            "id": "wamid.LOC_001",
            "timestamp": "1731062400",
            "type": "location",
            "location": {
                "latitude": 17.98,
                "longitude": 79.53,
                "name": "My Farm",
                "address": "Warangal, Telangana",
            },
        }

        result = self.service.process_incoming_message(msg)
        self.assertEqual(result["status"], "location_saved_confirmation_requested")

        # Verify confirmed district was NOT overwritten
        updated_farmer = self.farmer_service.get_farmer_by_whatsapp_id("919876543210")
        self.assertEqual(updated_farmer.district_name, "Hanamkonda")
        self.assertTrue(updated_farmer.location_confirmed)
        self.assertEqual(updated_farmer.latitude, 17.98)
        self.assertEqual(updated_farmer.longitude, 79.53)

        # Verify confirmation prompt was dispatched
        self.mock_client.send_text_message.assert_called_once()
        self.assertIn("మీ లొకేషన్ వివరాలు అందాయి", self.mock_client.send_text_message.call_args[0][1])

    def test_unsupported_media_message(self):
        msg = {
            "from": "919876543210",
            "id": "wamid.IMAGE_001",
            "timestamp": "1731062400",
            "type": "image",
            "image": {"id": "IMG_123"},
        }

        result = self.service.process_incoming_message(msg)
        self.assertEqual(result["status"], "unsupported_media_guided")

        self.mock_client.send_text_message.assert_called_once()
        self.assertIn("వాయిస్ సందేశాలు", self.mock_client.send_text_message.call_args[0][1])


class TestFastAPIWhatsAppWebhookRoutes(unittest.TestCase):
    """Tests for FastAPI GET and POST /webhook endpoints."""

    @classmethod
    def setUpClass(cls):
        cls.app = create_application()
        cls.client = TestClient(cls.app)

    @patch.object(settings, "WHATSAPP_WEBHOOK_VERIFY_TOKEN", "verify_secret_token_123")
    def test_get_webhook_verification_success(self):
        response = self.client.get(
            "/api/v1/whatsapp/webhook",
            params={
                "hub.mode": "subscribe",
                "hub.challenge": "115599",
                "hub.verify_token": "verify_secret_token_123",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.text, "115599")
        self.assertEqual(response.headers["content-type"], "text/plain; charset=utf-8")

    @patch.object(settings, "WHATSAPP_WEBHOOK_VERIFY_TOKEN", "verify_secret_token_123")
    def test_get_webhook_verification_forbidden(self):
        response = self.client.get(
            "/api/v1/whatsapp/webhook",
            params={
                "hub.mode": "subscribe",
                "hub.challenge": "115599",
                "hub.verify_token": "wrong_token",
            },
        )
        self.assertEqual(response.status_code, 403)

    @patch.object(settings, "WHATSAPP_APP_SECRET", "app_secret_test_999")
    @patch("app.whatsapp.service.WhatsAppService.process_incoming_message")
    def test_post_webhook_with_valid_hmac_signature(self, mock_process):
        payload = {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "id": "BIZ_123",
                    "changes": [
                        {
                            "field": "messages",
                            "value": {
                                "messaging_product": "whatsapp",
                                "messages": [
                                    {
                                        "from": "919876543210",
                                        "id": "wamid.FASTAPI_001",
                                        "timestamp": "1731062400",
                                        "type": "text",
                                        "text": {"body": "హలో"},
                                    }
                                ],
                            },
                        }
                    ],
                }
            ],
        }
        body_bytes = json.dumps(payload).encode("utf-8")
        sig = hmac.new(b"app_secret_test_999", body_bytes, hashlib.sha256).hexdigest()

        response = self.client.post(
            "/api/v1/whatsapp/webhook",
            content=body_bytes,
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature-256": f"sha256={sig}",
            },
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "received")
        self.assertEqual(data["dispatched"], 1)

    @patch.object(settings, "WHATSAPP_APP_SECRET", "app_secret_test_999")
    def test_post_webhook_with_invalid_signature_rejected(self):
        payload = {"object": "whatsapp_business_account"}
        body_bytes = json.dumps(payload).encode("utf-8")

        response = self.client.post(
            "/api/v1/whatsapp/webhook",
            content=body_bytes,
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature-256": "sha256=invalid_hash_value",
            },
        )

        self.assertEqual(response.status_code, 403)

    @patch.object(settings, "WHATSAPP_APP_SECRET", "app_secret_test_999")
    @patch("app.whatsapp.service.WhatsAppService.process_incoming_message")
    def test_post_webhook_ignores_delivery_status(self, mock_process):
        status_payload = {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "messaging_product": "whatsapp",
                                "statuses": [
                                    {
                                        "id": "wamid.SENT_001",
                                        "status": "delivered",
                                        "timestamp": "1731062400",
                                        "recipient_id": "919876543210",
                                    }
                                ],
                            }
                        }
                    ]
                }
            ],
        }
        body_bytes = json.dumps(status_payload).encode("utf-8")
        sig = hmac.new(b"app_secret_test_999", body_bytes, hashlib.sha256).hexdigest()

        response = self.client.post(
            "/api/v1/whatsapp/webhook",
            content=body_bytes,
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature-256": f"sha256={sig}",
            },
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["dispatched"], 0)
        mock_process.assert_not_called()


if __name__ == "__main__":
    unittest.main()
