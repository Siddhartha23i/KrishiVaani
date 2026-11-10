"""
Unit and Integration Test Suite for KrishiVaani Telugu Voice Pipeline — Phase 8.0.

Verifies:
1. Audio format, duration limit (30.0s), and payload validation.
2. 30-second duration limit rejection (AudioDurationExceededError / HTTP 400).
3. Unsupported format rejection (.txt, .avi / HTTP 400).
4. Empty/zero-byte audio rejection (AudioValidationError / HTTP 400).
5. Prisma v3.0 STT transcription (mocked & live).
6. Empty transcript polite clarification handling.
7. STT failure graceful degradation to safe text.
8. Conversation orchestrator integration (grounded reasoning, IMD warnings, PJTAU referrals).
9. Deterministic safety validation rejection guard (suppressing speech synthesis).
10. Timbre v2.5 TTS synthesis and graceful fallback to text if TTS fails.
11. Strict temporary file cleanup — zero audio residue on disk.
12. Multilingual handling (Telugu default, Hindi, English).
13. FastAPI multipart voice endpoint (/api/v1/voice/process).
14. Live smoke test on test-audio/telugu-test.m4a when GNANI_API_KEY is available.
"""

import io
import os
import wave
import base64
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.main import create_application
from app.core.config import settings
from app.conversation.schemas import (
    ConversationResponse,
    LocationInput,
    WeatherMetadata,
)
from app.voice.exceptions import (
    AudioValidationError,
    AudioDurationExceededError,
    UnsupportedAudioFormatError,
    AudioSizeExceededError,
    STTServiceError,
)
from app.voice.validator import (
    validate_audio_file,
    inspect_audio_duration,
    MAX_AUDIO_DURATION_SECONDS,
)
from app.voice.schemas import (
    VoiceProcessingRequest,
    VoiceProcessingResponse,
)
from app.voice.service import (
    VoicePipelineService,
    EMPTY_TRANSCRIPT_MESSAGES,
    STT_ERROR_MESSAGES,
)


def _generate_test_wav_bytes(duration_seconds: float, sample_rate: int = 16000) -> bytes:
    """Generate in-memory WAV audio bytes with the given duration."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        num_frames = int(sample_rate * duration_seconds)
        w.writeframes(b"\x00\x00" * num_frames)
    return buf.getvalue()


class TestAudioValidation(unittest.TestCase):
    """Tests for audio file inspection and validation."""

    def setUp(self):
        self.temp_files = []

    def tearDown(self):
        for p in self.temp_files:
            if os.path.exists(p):
                try:
                    os.remove(p)
                except Exception:
                    pass

    def _create_temp_file(self, filename: str, content: bytes) -> Path:
        path = Path(filename)
        path.write_bytes(content)
        self.temp_files.append(str(path))
        return path

    def test_validate_audio_valid_wav(self):
        wav_bytes = _generate_test_wav_bytes(5.0)
        p = self._create_temp_file("temp_valid_5s.wav", wav_bytes)

        result = validate_audio_file(p, max_duration=30.0)
        self.assertAlmostEqual(result["duration_seconds"], 5.0, places=1)
        self.assertEqual(result["extension"], ".wav")
        self.assertGreater(result["size_bytes"], 0)

    def test_validate_audio_duration_exceeded(self):
        wav_bytes = _generate_test_wav_bytes(35.0)
        p = self._create_temp_file("temp_exceeded_35s.wav", wav_bytes)

        with self.assertRaises(AudioDurationExceededError) as ctx:
            validate_audio_file(p, max_duration=30.0)
        self.assertIn("exceeds the 30-second limit", str(ctx.exception))
        self.assertAlmostEqual(ctx.exception.duration, 35.0, places=1)

    def test_validate_audio_unsupported_format(self):
        p = self._create_temp_file("temp_doc.txt", b"This is plain text.")

        with self.assertRaises(UnsupportedAudioFormatError) as ctx:
            validate_audio_file(p)
        self.assertIn("Unsupported audio format '.txt'", str(ctx.exception))

    def test_validate_audio_empty_file(self):
        p = self._create_temp_file("temp_empty.wav", b"")

        with self.assertRaises(AudioValidationError) as ctx:
            validate_audio_file(p)
        self.assertIn("empty (0 bytes)", str(ctx.exception))

    def test_validate_audio_real_m4a_telugu_test(self):
        m4a_path = Path("test-audio/telugu-test.m4a")
        if not m4a_path.exists():
            self.skipTest("test-audio/telugu-test.m4a not found")

        result = validate_audio_file(m4a_path, max_duration=30.0)
        # File is ~9.54s
        self.assertGreater(result["duration_seconds"], 8.0)
        self.assertLess(result["duration_seconds"], 12.0)
        self.assertEqual(result["extension"], ".m4a")


class TestVoicePipelineService(unittest.TestCase):
    """Tests for VoicePipelineService end-to-end integration."""

    def setUp(self):
        self.temp_files = []

    def tearDown(self):
        for p in self.temp_files:
            if os.path.exists(p):
                try:
                    os.remove(p)
                except Exception:
                    pass

    def _create_temp_file(self, filename: str, content: bytes) -> Path:
        path = Path(filename)
        path.write_bytes(content)
        self.temp_files.append(str(path))
        return path

    def test_end_to_end_voice_processing_success(self):
        mock_stt = MagicMock()
        mock_stt.transcribe.return_value = {
            "success": True,
            "transcript": "వరి పంటలో యూరియా ఎరువు మోతాదు ఎంత?",
            "detected_language_code": "te-IN",
        }

        mock_tts = MagicMock()
        mock_tts.synthesize.return_value = _generate_test_wav_bytes(3.0)

        mock_orch = MagicMock()
        mock_orch.process_message.return_value = ConversationResponse(
            intent="fertilizer_guidance",
            language="te-IN",
            response_text="వరి పంటకు ఎకరాకు 50 కిలోల యూరియా సిఫార్సు చేయబడింది.",
            is_abstention=False,
            evidence_citations=["PJTAU_RICE_001"],
            safety_status="PASSED",
            safety_validation_status="PASSED",
            latency_breakdown_ms={"llm_inference_ms": 250.0},
        )

        service = VoicePipelineService(
            stt_client=mock_stt,
            tts_client=mock_tts,
            orchestrator=mock_orch,
        )

        wav_bytes = _generate_test_wav_bytes(4.0)
        p = self._create_temp_file("temp_query.wav", wav_bytes)

        result = service.process_audio_file(p, request=VoiceProcessingRequest(language="te-IN"))

        self.assertEqual(result.status, "success")
        self.assertEqual(result.transcript, "వరి పంటలో యూరియా ఎరువు మోతాదు ఎంత?")
        self.assertEqual(result.detected_language, "te-IN")
        self.assertEqual(result.intent, "fertilizer_guidance")
        self.assertEqual(result.safety_status, "PASSED")
        self.assertFalse(result.is_abstention)
        self.assertFalse(result.is_fallback_text_only)
        self.assertIsNotNone(result.audio_base64)
        self.assertIn("PJTAU_RICE_001", result.evidence_citations)
        self.assertIn("stt_ms", result.stage_latencies_ms)
        self.assertIn("orchestration_ms", result.stage_latencies_ms)
        self.assertIn("tts_ms", result.stage_latencies_ms)

        # Verify TTS synthesis was called with Kaveri and prompt text
        mock_tts.synthesize.assert_called_once()
        call_kwargs = mock_tts.synthesize.call_args[1]
        self.assertEqual(call_kwargs["voice"], "Kaveri")
        self.assertEqual(call_kwargs["language"], "te-IN")
        self.assertEqual(call_kwargs["text"], "వరి పంటకు ఎకరాకు 50 కిలోల యూరియా సిఫార్సు చేయబడింది.")

    def test_empty_transcript_handling(self):
        mock_stt = MagicMock()
        mock_stt.transcribe.return_value = {
            "success": True,
            "transcript": "   ",  # whitespace / silence
            "detected_language_code": "te-IN",
        }

        mock_tts = MagicMock()
        mock_tts.synthesize.return_value = _generate_test_wav_bytes(2.0)

        mock_orch = MagicMock()

        service = VoicePipelineService(
            stt_client=mock_stt,
            tts_client=mock_tts,
            orchestrator=mock_orch,
        )

        wav_bytes = _generate_test_wav_bytes(3.0)
        p = self._create_temp_file("temp_silence.wav", wav_bytes)

        result = service.process_audio_file(p, request=VoiceProcessingRequest(language="te-IN"))

        self.assertEqual(result.status, "success")
        self.assertEqual(result.transcript, "")
        self.assertEqual(result.intent, "unintelligible_audio")
        self.assertTrue(result.is_abstention)
        self.assertIn("మీ సందేశం స్పష్టంగా వినిపించలేదు", result.response_text)
        self.assertIsNotNone(result.audio_base64)

        # Orchestrator should NOT have been invoked for empty transcript
        mock_orch.process_message.assert_not_called()

    def test_stt_failure_graceful_handling(self):
        mock_stt = MagicMock()
        mock_stt.transcribe.side_effect = RuntimeError("STT Server Timeout")

        mock_tts = MagicMock()
        mock_orch = MagicMock()

        service = VoicePipelineService(
            stt_client=mock_stt,
            tts_client=mock_tts,
            orchestrator=mock_orch,
        )

        wav_bytes = _generate_test_wav_bytes(2.0)
        p = self._create_temp_file("temp_stt_err.wav", wav_bytes)

        result = service.process_audio_file(p, request=VoiceProcessingRequest(language="te-IN"))

        self.assertEqual(result.status, "error")
        self.assertEqual(result.transcript, "")
        self.assertEqual(result.intent, "stt_failure")
        self.assertTrue(result.is_fallback_text_only)
        self.assertIsNone(result.audio_base64)
        self.assertIn("సాంకేతిక సమస్య ఏర్పడింది", result.response_text)
        self.assertIn("STT Server Timeout", result.error_detail)

        # Neither orchestrator nor TTS should have been called
        mock_orch.process_message.assert_not_called()
        mock_tts.synthesize.assert_not_called()

    def test_safety_rejection_suppresses_speech(self):
        mock_stt = MagicMock()
        mock_stt.transcribe.return_value = {
            "success": True,
            "transcript": "పురుగులను చంపడానికి నిషేధిత పురుగుమందులు వాడవచ్చా?",
            "detected_language_code": "te-IN",
        }

        mock_tts = MagicMock()

        mock_orch = MagicMock()
        mock_orch.process_message.return_value = ConversationResponse(
            intent="pest_disease_inquiry",
            language="te-IN",
            response_text="క్షమించండి, భద్రతా కారణాల వల్ల ఈ సమాచారం అందించలేము.",
            is_abstention=True,
            safety_status="REJECTED",
            safety_validation_status="REJECTED",
            safety_reason="Unapproved chemical pesticide guidance detected",
        )

        service = VoicePipelineService(
            stt_client=mock_stt,
            tts_client=mock_tts,
            orchestrator=mock_orch,
        )

        wav_bytes = _generate_test_wav_bytes(3.0)
        p = self._create_temp_file("temp_unsafe.wav", wav_bytes)

        result = service.process_audio_file(p, request=VoiceProcessingRequest(language="te-IN"))

        self.assertEqual(result.safety_status, "REJECTED")
        self.assertTrue(result.is_fallback_text_only)
        self.assertIsNone(result.audio_base64)
        self.assertIn("Safety validation rejected output", result.error_detail)

        # Crucial check: speech synthesis was strictly SUPPRESSED
        mock_tts.synthesize.assert_not_called()

    def test_tts_failure_fallback_to_text(self):
        mock_stt = MagicMock()
        mock_stt.transcribe.return_value = {
            "success": True,
            "transcript": "హైదరాబాద్ లో వాతావరణం ఎలా ఉంది?",
            "detected_language_code": "te-IN",
        }

        mock_tts = MagicMock()
        mock_tts.synthesize.side_effect = RuntimeError("Timbre TTS Connection Lost")

        mock_orch = MagicMock()
        mock_orch.process_message.return_value = ConversationResponse(
            intent="weather_inquiry",
            language="te-IN",
            response_text="హైదరాబాద్ లో నేడు తేలికపాటి వర్షం కురిసే అవకాశం ఉంది.",
            is_abstention=False,
            safety_status="PASSED",
        )

        service = VoicePipelineService(
            stt_client=mock_stt,
            tts_client=mock_tts,
            orchestrator=mock_orch,
        )

        wav_bytes = _generate_test_wav_bytes(2.5)
        p = self._create_temp_file("temp_tts_err.wav", wav_bytes)

        result = service.process_audio_file(p, request=VoiceProcessingRequest(language="te-IN"))

        # Pipeline must NOT fail! It gracefully preserves the text answer
        self.assertEqual(result.status, "success")
        self.assertTrue(result.is_fallback_text_only)
        self.assertIsNone(result.audio_base64)
        self.assertEqual(result.response_text, "హైదరాబాద్ లో నేడు తేలికపాటి వర్షం కురిసే అవకాశం ఉంది.")
        self.assertIn("Timbre TTS Connection Lost", result.error_detail)

    def test_temporary_file_cleanup_on_bytes_processing(self):
        mock_stt = MagicMock()
        mock_stt.transcribe.return_value = {
            "success": True,
            "transcript": "పత్తి పంట తెగుళ్ల సమాచారం ఇవ్వండి",
            "detected_language_code": "te-IN",
        }

        mock_tts = MagicMock()
        mock_tts.synthesize.return_value = _generate_test_wav_bytes(2.0)

        mock_orch = MagicMock()
        mock_orch.process_message.return_value = ConversationResponse(
            intent="pest_disease_inquiry",
            language="te-IN",
            response_text="పత్తి పంటలో గులాబీ రంగు కాయతొలుచు పురుగు నివారణకు వివరాలు.",
            is_abstention=False,
            safety_status="PASSED",
        )

        service = VoicePipelineService(
            stt_client=mock_stt,
            tts_client=mock_tts,
            orchestrator=mock_orch,
        )

        wav_bytes = _generate_test_wav_bytes(3.0)

        # Track created temporary files in temp dir
        import tempfile
        temp_dir = tempfile.gettempdir()
        files_before = set(os.listdir(temp_dir))

        result = service.process_audio_bytes(
            audio_bytes=wav_bytes,
            filename="farmer_query.wav",
            request=VoiceProcessingRequest(language="te-IN"),
        )

        files_after = set(os.listdir(temp_dir))
        new_files = files_after - files_before

        self.assertEqual(result.status, "success")
        # Ensure no temporary file with .wav residue remained in temp dir
        wav_residue = [f for f in new_files if f.endswith(".wav")]
        self.assertEqual(wav_residue, [])

    def test_multilingual_hindi_support(self):
        mock_stt = MagicMock()
        mock_stt.transcribe.return_value = {
            "success": True,
            "transcript": "कपास की फसल के लिए अनुशंसित उर्वरक क्या है?",
            "detected_language_code": "hi-IN",
        }

        mock_tts = MagicMock()
        mock_tts.synthesize.return_value = _generate_test_wav_bytes(2.0)

        mock_orch = MagicMock()
        mock_orch.process_message.return_value = ConversationResponse(
            intent="fertilizer_guidance",
            language="hi-IN",
            response_text="कपास की फसल के लिए अनुशंसित उर्वरक प्रति एकड़ 40 किलोग्राम यूरिया है।",
            is_abstention=False,
            safety_status="PASSED",
        )

        service = VoicePipelineService(
            stt_client=mock_stt,
            tts_client=mock_tts,
            orchestrator=mock_orch,
        )

        wav_bytes = _generate_test_wav_bytes(2.0)
        p = self._create_temp_file("temp_hindi.wav", wav_bytes)

        result = service.process_audio_file(p, request=VoiceProcessingRequest(language="hi-IN"))

        self.assertEqual(result.detected_language, "hi-IN")
        self.assertEqual(result.response_text, "कपास की फसल के लिए अनुशंसित उर्वरक प्रति एकड़ 40 किलोग्राम यूरिया है।")
        mock_tts.synthesize.assert_called_once()
        self.assertEqual(mock_tts.synthesize.call_args[1]["language"], "hi-IN")

    def test_multilingual_english_support(self):
        mock_stt = MagicMock()
        mock_stt.transcribe.return_value = {
            "success": True,
            "transcript": "What is the recommended fertilizer for cotton?",
            "detected_language_code": "en-IN",
        }

        mock_tts = MagicMock()
        mock_tts.synthesize.return_value = _generate_test_wav_bytes(2.0)

        mock_orch = MagicMock()
        mock_orch.process_message.return_value = ConversationResponse(
            intent="fertilizer_guidance",
            language="en-IN",
            response_text="The recommended fertilizer dose for cotton is 40 kg urea per acre.",
            is_abstention=False,
            safety_status="PASSED",
        )

        service = VoicePipelineService(
            stt_client=mock_stt,
            tts_client=mock_tts,
            orchestrator=mock_orch,
        )

        wav_bytes = _generate_test_wav_bytes(2.0)
        p = self._create_temp_file("temp_eng.wav", wav_bytes)

        result = service.process_audio_file(p, request=VoiceProcessingRequest(language="en-IN"))

        self.assertEqual(result.detected_language, "en-IN")
        self.assertEqual(result.response_text, "The recommended fertilizer dose for cotton is 40 kg urea per acre.")
        mock_tts.synthesize.assert_called_once()
        self.assertEqual(mock_tts.synthesize.call_args[1]["language"], "en-IN")

    def test_voice_integration_with_imd_warning(self):
        mock_stt = MagicMock()
        mock_stt.transcribe.return_value = {
            "success": True,
            "transcript": "హైదరాబాద్ లో ఈరోజు వాతావరణ హెచ్చరికలు ఏమిటి?",
            "detected_language_code": "te-IN",
        }

        mock_tts = MagicMock()
        mock_tts.synthesize.return_value = _generate_test_wav_bytes(3.0)

        # Real orchestrator call with weather mock
        mock_orch = MagicMock()
        meta = WeatherMetadata(
            source_name="India Meteorological Department (IMD)",
            source_url="https://mausam.imd.gov.in",
            retrieved_at="2026-11-08T10:00:00Z",
            issued_at="08-11-2026",
            is_grid_estimate=False,
            station_name="Meteorological Centre Hyderabad",
            freshness_status="CURRENT",
            disclaimer="Data provided by India Meteorological Department (IMD).",
            disclaimer_language="te-IN",
        )
        mock_orch.process_message.return_value = ConversationResponse(
            intent="weather_inquiry",
            language="te-IN",
            response_text="హైదరాబాద్ జిల్లాకు IMD వాతావరణ హెచ్చరిక: ఉరుములు, మెరుపులతో కూడిన తేలికపాటి వర్షం.",
            is_abstention=False,
            weather_metadata=meta,
            safety_status="PASSED",
        )

        service = VoicePipelineService(
            stt_client=mock_stt,
            tts_client=mock_tts,
            orchestrator=mock_orch,
        )

        wav_bytes = _generate_test_wav_bytes(3.0)
        p = self._create_temp_file("temp_imd_q.wav", wav_bytes)

        req = VoiceProcessingRequest(
            language="te-IN",
            location=LocationInput(district="Hyderabad", location_confirmed=True),
        )
        result = service.process_audio_file(p, request=req)

        self.assertEqual(result.intent, "weather_inquiry")
        self.assertIsNotNone(result.weather_metadata)
        self.assertEqual(result.weather_metadata.source_name, "India Meteorological Department (IMD)")
        self.assertIsNotNone(result.audio_base64)
        mock_tts.synthesize.assert_called_once()

    def test_voice_integration_with_pjtau_referral(self):
        mock_stt = MagicMock()
        mock_stt.transcribe.return_value = {
            "success": True,
            "transcript": "ఆదిలాబాద్ వ్యవసాయ పరిశోధనా కేంద్రం ఫోన్ నెంబర్ ఏమిటి?",
            "detected_language_code": "te-IN",
        }

        mock_tts = MagicMock()
        mock_tts.synthesize.return_value = _generate_test_wav_bytes(3.0)

        mock_orch = MagicMock()
        mock_orch.process_message.return_value = ConversationResponse(
            intent="agricultural_advice",
            language="te-IN",
            response_text="ఆదిలాబాద్ వ్యవసాయ పరిశోధనా కేంద్రం (ARS Adilabad) ఫోన్ నెంబర్: 8333818203.",
            is_abstention=False,
            evidence_citations=["PJTAU_ARS_ADILABAD_001"],
            safety_status="PASSED",
        )

        service = VoicePipelineService(
            stt_client=mock_stt,
            tts_client=mock_tts,
            orchestrator=mock_orch,
        )

        wav_bytes = _generate_test_wav_bytes(3.0)
        p = self._create_temp_file("temp_pjtau_q.wav", wav_bytes)

        req = VoiceProcessingRequest(
            language="te-IN",
            location=LocationInput(district="Adilabad", location_confirmed=True),
        )
        result = service.process_audio_file(p, request=req)

        self.assertIn("8333818203", result.response_text)
        self.assertIn("PJTAU_ARS_ADILABAD_001", result.evidence_citations)
        self.assertIsNotNone(result.audio_base64)
        mock_tts.synthesize.assert_called_once()


class TestFastAPIVoiceEndpoint(unittest.TestCase):
    """Tests for the FastAPI /api/v1/voice/process route."""

    @classmethod
    def setUpClass(cls):
        cls.app = create_application()
        cls.client = TestClient(cls.app)

    @patch("app.voice.service.GnaniSTTClient")
    @patch("app.voice.service.GnaniTTSClient")
    def test_fastapi_voice_process_success(self, mock_tts_cls, mock_stt_cls):
        mock_stt = MagicMock()
        mock_stt.transcribe.return_value = {
            "success": True,
            "transcript": "నమస్కారం, పత్తి పంట గురించి చెప్పండి",
            "detected_language_code": "te-IN",
        }
        mock_stt_cls.return_value = mock_stt

        mock_tts = MagicMock()
        mock_tts.synthesize.return_value = _generate_test_wav_bytes(2.5)
        mock_tts_cls.return_value = mock_tts

        wav_bytes = _generate_test_wav_bytes(4.0)

        response = self.client.post(
            "/api/v1/voice/process",
            files={"file": ("query.wav", wav_bytes, "audio/wav")},
            data={"language": "te-IN", "district": "Warangal"},
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["transcript"], "నమస్కారం, పత్తి పంట గురించి చెప్పండి")
        self.assertEqual(data["detected_language"], "te-IN")
        self.assertIsNotNone(data["response_text"])
        self.assertIsNotNone(data["audio_base64"])
        self.assertEqual(data["audio_content_type"], "audio/wav")
        self.assertIn("stt_ms", data["stage_latencies_ms"])
        self.assertIn("tts_ms", data["stage_latencies_ms"])

    def test_fastapi_voice_duration_exceeded_400(self):
        wav_bytes = _generate_test_wav_bytes(35.0)

        response = self.client.post(
            "/api/v1/voice/process",
            files={"file": ("long_speech.wav", wav_bytes, "audio/wav")},
            data={"language": "te-IN"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("exceeds the 30-second limit", response.json()["detail"])

    def test_fastapi_voice_unsupported_format_400(self):
        response = self.client.post(
            "/api/v1/voice/process",
            files={"file": ("speech.pdf", b"%PDF-1.4...", "application/pdf")},
            data={"language": "te-IN"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Unsupported audio format '.pdf'", response.json()["detail"])

    def test_fastapi_voice_empty_file_400(self):
        response = self.client.post(
            "/api/v1/voice/process",
            files={"file": ("empty.wav", b"", "audio/wav")},
            data={"language": "te-IN"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("empty", response.json()["detail"])


class TestLiveVoiceSmoke(unittest.TestCase):
    """
    Live smoke test executing real Prisma STT and Timbre TTS
    when GNANI_API_KEY is configured in the environment.
    """

    def test_live_smoke_telugu_test_m4a(self):
        if not settings.GNANI_API_KEY:
            self.skipTest("GNANI_API_KEY not configured")

        audio_path = Path("test-audio/telugu-test.m4a")
        if not audio_path.exists():
            self.skipTest("test-audio/telugu-test.m4a not found")

        service = VoicePipelineService()
        result = service.process_audio_file(
            audio_path, request=VoiceProcessingRequest(language="te-IN")
        )

        self.assertEqual(result.status, "success")
        self.assertTrue(len(result.transcript) > 0)
        self.assertEqual(result.detected_language, "te-IN")
        self.assertIn(result.safety_status, ("PASSED", "ABSTAINED"))
        self.assertTrue(len(result.response_text) > 0)
        self.assertIsNotNone(result.audio_base64)

        # Verify decoded audio is valid WAV
        decoded_wav = base64.b64decode(result.audio_base64)
        self.assertTrue(decoded_wav.startswith(b"RIFF"))
        self.assertIn(b"WAVE", decoded_wav[:12])
        self.assertGreater(len(decoded_wav), 10000)

        # Verify latencies exist
        self.assertIn("audio_validation_ms", result.stage_latencies_ms)
        self.assertIn("stt_ms", result.stage_latencies_ms)
        self.assertIn("orchestration_ms", result.stage_latencies_ms)
        self.assertIn("tts_ms", result.stage_latencies_ms)
        self.assertIn("total_ms", result.stage_latencies_ms)


if __name__ == "__main__":
    unittest.main()

