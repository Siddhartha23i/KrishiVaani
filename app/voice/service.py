"""
KrishiVaani Telugu Voice Pipeline Orchestration Service — Phase 8.0.

Integrates:
1. Audio format, duration (strictly <= 30.0s), and payload validation.
2. Gnani Prisma v3.0 STT for Telugu transcription (preserving detected language).
3. Existing ConversationOrchestrator for grounded reasoning, IMD warnings, and PJTAU referrals.
4. Deterministic safety validation verification before speech generation.
5. Gnani Timbre v2.5 TTS for natural Telugu speech output (Kaveri voice).
6. Graceful failure degradation: STT failure, empty transcript, safety rejection,
   and TTS failure fallback to safe text.
7. Strict temporary file cleanup — zero permanent storage of raw audio.
"""

import os
import time
import base64
import logging
import tempfile
from pathlib import Path
from typing import Optional, Dict, Any, Union

from app.core.config import settings
from app.conversation.service import ConversationOrchestrator, normalize_language
from app.conversation.schemas import ConversationRequest, ConversationResponse
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
    SUPPORTED_AUDIO_EXTENSIONS,
    MAX_AUDIO_DURATION_SECONDS,
    inspect_audio_duration,
)
from app.voice.schemas import VoiceProcessingRequest, VoiceProcessingResponse

from gnani.stt import GnaniSTTClient
from gnani.tts import GnaniTTSClient, AudioConfig

logger = logging.getLogger(__name__)

# Fallback polite clarification texts by language
EMPTY_TRANSCRIPT_MESSAGES = {
    "te-IN": "మీ సందేశం స్పష్టంగా వినిపించలేదు. దయచేసి మీ వ్యవసాయ సందేహాన్ని లేదా అడిగే విషయాన్ని మళ్ళీ స్పష్టంగా మాట్లాడండి.",
    "hi-IN": "आपकी आवाज़ स्पष्ट नहीं सुनाई दी। कृपया अपना कृषि प्रश्न फिर से स्पष्ट बोलें।",
    "en-IN": "Your voice message was not clearly audible. Please speak your agricultural question again clearly.",
}

STT_ERROR_MESSAGES = {
    "te-IN": "క్షమించండి, మీ వాయిస్ సందేశాన్ని ప్రాసెస్ చేయడంలో సాంకేతిక సమస్య ఏర్పడింది. దయచేసి కాసేపటి తర్వాత మళ్ళీ ప్రయత్నించండి.",
    "hi-IN": "क्षमा करें, आपके ध्वनि संदेश को संसाधित करने में तकनीकी समस्या हुई। कृपया कुछ समय बाद पुनः प्रयास करें।",
    "en-IN": "Sorry, there was a technical issue processing your voice message. Please try again after some time.",
}


class VoicePipelineService:
    """
    End-to-end voice processing service connecting Gnani Prisma STT,
    KrishiVaani Conversation Orchestrator, and Gnani Timbre TTS.
    """

    def __init__(
        self,
        stt_client: Optional[GnaniSTTClient] = None,
        tts_client: Optional[GnaniTTSClient] = None,
        orchestrator: Optional[ConversationOrchestrator] = None,
        api_key: Optional[str] = None,
        max_duration_seconds: float = MAX_AUDIO_DURATION_SECONDS,
    ):
        self.api_key = api_key or settings.GNANI_API_KEY
        self.max_duration_seconds = max_duration_seconds

        # Initialize STT client
        if stt_client is not None:
            self.stt_client = stt_client
        elif self.api_key:
            self.stt_client = GnaniSTTClient(api_key=self.api_key)
        else:
            self.stt_client = None

        # Initialize TTS client
        if tts_client is not None:
            self.tts_client = tts_client
        elif self.api_key:
            self.tts_client = GnaniTTSClient(api_key=self.api_key)
        else:
            self.tts_client = None

        # Initialize conversation orchestrator
        self.orchestrator = orchestrator or ConversationOrchestrator()

    def process_audio_file(
        self,
        audio_path: Union[str, Path],
        request: Optional[VoiceProcessingRequest] = None,
    ) -> VoiceProcessingResponse:
        """
        Process an audio file through the complete voice pipeline.
        Strictly enforces duration limit <= 30.0s before transcribing.
        """
        start_total = time.perf_counter()
        latencies: Dict[str, Any] = {}
        request = request or VoiceProcessingRequest()

        target_lang, prompt_lang = normalize_language(request.language)
        path_obj = Path(audio_path)

        # -------------------------------------------------------------
        # Stage 1: Audio Validation (Format, Size, Duration <= 30.0s)
        # -------------------------------------------------------------
        t0 = time.perf_counter()
        val_result = validate_audio_file(
            path_obj, max_duration=self.max_duration_seconds
        )
        latencies["audio_validation_ms"] = round((time.perf_counter() - t0) * 1000, 2)
        input_duration = val_result["duration_seconds"]

        # -------------------------------------------------------------
        # Stage 2: Prisma v3.0 STT Transcription
        # -------------------------------------------------------------
        if self.stt_client is None:
            raise STTServiceError("Gnani STT Client is not configured. Missing GNANI_API_KEY.")

        t0 = time.perf_counter()
        try:
            stt_result = self.stt_client.transcribe(
                str(path_obj),
                language_code=target_lang,
                model="prisma-v3.0",
                format="transcribe",
                topic="Telangana farming and agriculture",
            )
            latencies["stt_ms"] = round((time.perf_counter() - t0) * 1000, 2)
        except Exception as e:
            latencies["stt_ms"] = round((time.perf_counter() - t0) * 1000, 2)
            latencies["total_ms"] = round((time.perf_counter() - start_total) * 1000, 2)
            logger.error("STT transcription failure: %s", str(e))
            fallback_text = STT_ERROR_MESSAGES.get(target_lang, STT_ERROR_MESSAGES["te-IN"])
            return VoiceProcessingResponse(
                status="error",
                transcript="",
                detected_language=target_lang,
                intent="stt_failure",
                response_text=fallback_text,
                audio_base64=None,
                input_audio_duration_seconds=input_duration,
                is_abstention=True,
                safety_status="ABSTAINED",
                is_fallback_text_only=True,
                stage_latencies_ms=latencies,
                error_detail=f"STT processing failed: {str(e)}",
            )

        transcript = (stt_result.get("transcript") or "").strip()
        detected_lang = stt_result.get("detected_language_code") or target_lang
        if getattr(request, "channel", None) == "telegram":
            detected_lang = "te-IN"

        # -------------------------------------------------------------
        # Stage 2.1: Empty Transcript Handling (Silence / Unintelligible)
        # -------------------------------------------------------------
        if not transcript:
            clarification_text = EMPTY_TRANSCRIPT_MESSAGES.get(
                detected_lang, EMPTY_TRANSCRIPT_MESSAGES["te-IN"]
            )
            latencies["orchestration_ms"] = 0.0

            # Attempt to generate speech for the clarification prompt
            tts_audio_b64 = None
            audio_dur = None
            is_fallback = False
            error_msg = None

            t_tts = time.perf_counter()
            if self.tts_client:
                try:
                    tts_bytes = self._synthesize_speech(clarification_text, detected_lang)
                    tts_audio_b64 = base64.b64encode(tts_bytes).decode("ascii")
                    audio_dur = len(tts_bytes) / (48000 * 2)  # 48kHz 16-bit mono estimate
                except Exception as tts_err:
                    logger.warning("TTS failed on empty transcript clarification: %s", tts_err)
                    is_fallback = True
                    error_msg = f"TTS error: {str(tts_err)}"
            else:
                is_fallback = True

            latencies["tts_ms"] = round((time.perf_counter() - t_tts) * 1000, 2)
            latencies["total_ms"] = round((time.perf_counter() - start_total) * 1000, 2)

            return VoiceProcessingResponse(
                status="success",
                transcript="",
                detected_language=detected_lang,
                intent="unintelligible_audio",
                response_text=clarification_text,
                audio_base64=tts_audio_b64,
                audio_duration_seconds=audio_dur,
                input_audio_duration_seconds=input_duration,
                is_abstention=True,
                safety_status="PASSED",
                is_fallback_text_only=is_fallback,
                stage_latencies_ms=latencies,
                error_detail=error_msg,
            )

        # -------------------------------------------------------------
        # Stage 3: Conversation Orchestrator Reasoning
        # -------------------------------------------------------------
        t0 = time.perf_counter()
        conv_req = ConversationRequest(
            question=transcript,
            language=detected_lang,
            farmer_id=request.farmer_id,
            location=request.location,
            guest_consent=request.guest_consent,
            as_of_date=request.as_of_date,
            channel=request.channel,
        )
        conv_resp: ConversationResponse = self.orchestrator.process_message(conv_req)
        latencies["orchestration_ms"] = round((time.perf_counter() - t0) * 1000, 2)

        # Merge orchestrator internal latencies if present
        if conv_resp.latency_breakdown_ms:
            for k, v in conv_resp.latency_breakdown_ms.items():
                if k not in ("total_ms",):
                    latencies[k] = v

        # Guardrail: STT transcript must NEVER be returned as the assistant response
        q_clean = transcript.strip().strip(" !?,.:;~`'\"|•\t\n\r\u0964\u0965").lower()
        r_clean = (conv_resp.response_text or "").strip().strip(" !?,.:;~`'\"|•\t\n\r\u0964\u0965").lower()
        if r_clean and r_clean == q_clean:
            logger.warning("Voice pipeline detected response echoing transcript. Overriding with safe clarification.")
            clarification_msg = (
                "మీరు వేర్వేరు ప్రాంతాల పేర్లు చెప్పారు అండి. మీకు ఏ ఊరు లేదా మండలం వాతావరణ వివరాలు కావాలో స్పష్టంగా చెప్తారా?"
                if conv_resp.language.startswith("te") else
                "Please clarify which village or mandal in Telangana you need weather details for."
            )
            conv_resp.response_text = clarification_msg
            conv_resp.is_abstention = True
            conv_resp.safety_reason = "LOCATION_PARAMETERS_REQUIRED"
            conv_resp.safety_status = "ABSTAINED"

        # -------------------------------------------------------------
        # Stage 4: Safety Validation Rejection Guard
        # -------------------------------------------------------------
        # If safety status is strictly REJECTED (e.g. unsafe chemical advice hallucinated),
        # NEVER generate speech for the unapproved content.
        if conv_resp.safety_status == "REJECTED":
            logger.warning(
                "Voice pipeline: Safety validation REJECTED text. Suppressing speech synthesis."
            )
            latencies["tts_ms"] = 0.0
            latencies["total_ms"] = round((time.perf_counter() - start_total) * 1000, 2)
            return VoiceProcessingResponse(
                status="success",
                transcript=transcript,
                detected_language=conv_resp.language,
                intent=conv_resp.intent,
                response_text=conv_resp.response_text,
                audio_base64=None,
                input_audio_duration_seconds=input_duration,
                is_abstention=conv_resp.is_abstention,
                safety_status="REJECTED",
                safety_reason=getattr(conv_resp, "safety_reason", None),
                evidence_citations=conv_resp.evidence_citations,
                weather_metadata=conv_resp.weather_metadata,
                is_fallback_text_only=True,
                stage_latencies_ms=latencies,
                error_detail="Safety validation rejected output. Speech synthesis suppressed.",
            )

        # -------------------------------------------------------------
        # Stage 5: Gnani Timbre v2.5 TTS Synthesis
        # -------------------------------------------------------------
        t0 = time.perf_counter()
        audio_b64 = None
        audio_dur = None
        is_fallback_text = False
        tts_error_detail = None

        if self.tts_client and conv_resp.response_text:
            try:
                audio_bytes = self._synthesize_speech(
                    text=conv_resp.response_text, language=conv_resp.language
                )
                latencies["tts_ms"] = round((time.perf_counter() - t0) * 1000, 2)
                audio_b64 = base64.b64encode(audio_bytes).decode("ascii")
                audio_dur = len(audio_bytes) / (48000 * 2)  # 48kHz 16-bit mono estimate
            except Exception as e:
                # TTS failure must gracefully fall back to safe text response without losing the answer!
                latencies["tts_ms"] = round((time.perf_counter() - t0) * 1000, 2)
                logger.error("TTS synthesis failed: %s; falling back to text response", str(e))
                is_fallback_text = True
                audio_b64 = None
                tts_error_detail = f"TTS synthesis failed: {str(e)}"
        else:
            latencies["tts_ms"] = 0.0
            is_fallback_text = True
            if not self.tts_client:
                tts_error_detail = "TTS client not configured."

        latencies["total_ms"] = round((time.perf_counter() - start_total) * 1000, 2)

        return VoiceProcessingResponse(
            status="success",
            transcript=transcript,
            detected_language=conv_resp.language,
            intent=conv_resp.intent,
            response_text=conv_resp.response_text,
            audio_base64=audio_b64,
            audio_content_type="audio/wav",
            audio_duration_seconds=round(audio_dur, 2) if audio_dur else None,
            input_audio_duration_seconds=input_duration,
            is_abstention=conv_resp.is_abstention,
            safety_status=conv_resp.safety_status,
            safety_reason=getattr(conv_resp, "safety_reason", None),
            evidence_citations=conv_resp.evidence_citations,
            weather_metadata=conv_resp.weather_metadata,
            is_fallback_text_only=is_fallback_text,
            stage_latencies_ms=latencies,
            error_detail=tts_error_detail,
        )

    def process_audio_bytes(
        self,
        audio_bytes: bytes,
        filename: str = "audio.m4a",
        request: Optional[VoiceProcessingRequest] = None,
    ) -> VoiceProcessingResponse:
        """
        Process raw audio bytes by writing to a temporary file, running the pipeline,
        and guaranteeing immediate temporary file cleanup in all situations.
        """
        if not audio_bytes or len(audio_bytes) == 0:
            raise AudioValidationError("Audio payload is empty (0 bytes).")

        # Determine extension from filename
        ext = Path(filename).suffix.lower() or ".m4a"
        if ext not in SUPPORTED_AUDIO_EXTENSIONS:
            raise UnsupportedAudioFormatError(
                f"Unsupported audio format '{ext}'. Supported: {', '.join(sorted(SUPPORTED_AUDIO_EXTENSIONS))}."
            )

        temp_path: Optional[Path] = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as temp_file:
                temp_file.write(audio_bytes)
                temp_file.flush()
                temp_path = Path(temp_file.name)

            return self.process_audio_file(temp_path, request=request)
        finally:
            if temp_path and temp_path.exists():
                try:
                    temp_path.unlink()
                    logger.debug("Cleaned up temporary audio file: %s", temp_path)
                except Exception as cleanup_err:
                    logger.warning("Failed to remove temporary file %s: %s", temp_path, cleanup_err)

    def synthesize_speech(self, text: str, language: str = "te-IN") -> bytes:
        """
        Synthesize text into WAV audio using Gnani Timbre v2.5 Kaveri voice.
        """
        return self._synthesize_speech(text=text, language=language)

    def _synthesize_speech(self, text: str, language: str) -> bytes:
        """
        Synthesize text into WAV audio using Gnani Timbre v2.5 Kaveri voice.
        """
        if not self.tts_client:
            raise TTSServiceError("Gnani TTS client is not configured.")

        # Timbre v2.5 Kaveri voice
        voice = "Kaveri"
        target_lang, _ = normalize_language(language)

        audio_bytes = self.tts_client.synthesize(
            text=text,
            voice=voice,
            model="timbre-v2.5",
            language=target_lang,
            speed=0.95,
            audio_config=AudioConfig(
                container="wav",
                encoding="linear_pcm",
                sample_rate=48000,
            ),
        )
        return audio_bytes

