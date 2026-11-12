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
import re
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
    "ta-IN": "உங்கள் குரல் செய்தி தெளிவாக கேட்கவில்லை. உங்கள் விவசாயக் கேள்வியை மீண்டும் தெளிவாகப் பேசுங்கள்.",
    "kn-IN": "ನಿಮ್ಮ ಧ್ವನಿ ಸಂದೇಶ ಸ್ಪಷ್ಟವಾಗಿ ಕೇಳಿಸಲಿಲ್ಲ. ನಿಮ್ಮ ಕೃಷಿ ಪ್ರಶ್ನೆಯನ್ನು ಮತ್ತೆ ಸ್ಪಷ್ಟವಾಗಿ ಹೇಳಿ.",
    "ml-IN": "നിങ്ങളുടെ ശബ്ദസന്ദേശം വ്യക്തമായി കേൾക്കാനായില്ല. നിങ്ങളുടെ കൃഷി ചോദ്യം വീണ്ടും വ്യക്തമായി പറയൂ.",
    "mr-IN": "तुमचा आवाज संदेश स्पष्ट ऐकू आला नाही. तुमचा कृषी प्रश्न पुन्हा स्पष्टपणे बोला.",
    "pa-IN": "ਤੁਹਾਡਾ ਵੌਇਸ ਸੁਨੇਹਾ ਸਾਫ਼ ਨਹੀਂ ਸੁਣਿਆ। ਆਪਣਾ ਖੇਤੀਬਾੜੀ ਸਵਾਲ ਫਿਰ ਸਾਫ਼ ਬੋਲੋ।",
    "bn-IN": "আপনার ভয়েস বার্তা স্পষ্ট শোনা যায়নি। আপনার কৃষি প্রশ্নটি আবার পরিষ্কার করে বলুন।",
    "gu-IN": "તમારો વૉઇસ સંદેશ સ્પષ્ટ સંભળાયો નહીં. તમારો કૃષિ પ્રશ્ન ફરી સ્પષ્ટ બોલો.",
}

STT_ERROR_MESSAGES = {
    "te-IN": "క్షమించండి, మీ వాయిస్ సందేశాన్ని ప్రాసెస్ చేయడంలో సాంకేతిక సమస్య ఏర్పడింది. దయచేసి కాసేపటి తర్వాత మళ్ళీ ప్రయత్నించండి.",
    "hi-IN": "क्षमा करें, आपके ध्वनि संदेश को संसाधित करने में तकनीकी समस्या हुई। कृपया कुछ समय बाद पुनः प्रयास करें।",
    "en-IN": "Sorry, there was a technical issue processing your voice message. Please try again after some time.",
    "ta-IN": "மன்னிக்கவும், குரல் செய்தியை செயலாக்குவதில் சிக்கல் ஏற்பட்டது. சிறிது நேரம் கழித்து முயற்சிக்கவும்.",
    "kn-IN": "ಕ್ಷಮಿಸಿ, ಧ್ವನಿ ಸಂದೇಶವನ್ನು ಸಂಸ್ಕರಿಸುವಲ್ಲಿ ತೊಂದರೆ ಉಂಟಾಗಿದೆ. ಸ್ವಲ್ಪ ಸಮಯದ ನಂತರ ಪ್ರಯತ್ನಿಸಿ.",
    "ml-IN": "ക്ഷമിക്കണം, ശബ്ദസന്ദേശം പ്രോസസ്സ് ചെയ്യുന്നതിൽ പ്രശ്നമുണ്ടായി. കുറച്ച് കഴിഞ്ഞ് ശ്രമിക്കൂ.",
    "mr-IN": "माफ करा, आवाज संदेशावर प्रक्रिया करताना अडचण आली. थोड्या वेळाने पुन्हा प्रयत्न करा.",
    "pa-IN": "ਮਾਫ਼ ਕਰਨਾ, ਵੌਇਸ ਸੁਨੇਹੇ ਦੀ ਪ੍ਰਕਿਰਿਆ ਵਿੱਚ ਸਮੱਸਿਆ ਆਈ। ਕੁਝ ਦੇਰ ਬਾਅਦ ਕੋਸ਼ਿਸ਼ ਕਰੋ।",
    "bn-IN": "দুঃখিত, ভয়েস বার্তা প্রক্রিয়া করতে সমস্যা হয়েছে। কিছুক্ষণ পরে চেষ্টা করুন।",
    "gu-IN": "માફ કરશો, વૉઇસ સંદેશ પ્રક્રિયા કરવામાં સમસ્યા આવી. થોડી વાર પછી પ્રયાસ કરો.",
}


def prepare_telugu_text_for_voice(text: str) -> str:
    """
    Normalize validated Telugu text for natural Gnani Timbre v2.5 Kaveri pronunciation.
    - Expands meteorological/agricultural units and English abbreviations cleanly into Telugu phonetics.
    - Strips markdown symbols and redundant parenthetical English acronyms without altering factual values.
    - Uses natural plain-text punctuation (no unsupported SSML tags).
    """
    if not text or not text.strip():
        return text

    out = text.strip()

    # 1. Remove markdown bold/italic/code/heading markers and stray XML/SSML tags
    out = re.sub(r"<[^>]+>", " ", out)
    out = re.sub(r"[*_`#]+", "", out)

    # 2. Convert bullet lines and multi-line breaks into well-paced spoken sentences
    lines = []
    for raw_line in out.splitlines():
        line = re.sub(r"^[\s•\-]+", "", raw_line).strip()
        if line:
            lines.append(line)
    if len(lines) > 1:
        joined = []
        for idx, line in enumerate(lines):
            if idx < len(lines) - 1 and line[-1] not in ".?!।\u0964":
                joined.append(f"{line}.")
            else:
                joined.append(line)
        out = " ".join(joined)
    elif lines:
        out = lines[0]

    # 3. Expand numeric weather/agricultural units while preserving numbers accurately
    out = re.sub(r"(\d+(?:\.\d+)?)\s*°\s*C\b", r"\1 డిగ్రీల సెల్సియస్", out, flags=re.IGNORECASE)
    out = re.sub(r"(\d+(?:\.\d+)?)\s*%", r"\1 శాతం", out)
    out = re.sub(r"(\d+(?:\.\d+)?)\s*mm\b", r"\1 మిల్లీమీటర్లు", out, flags=re.IGNORECASE)
    out = re.sub(r"(\d+(?:\.\d+)?)\s*cm\b", r"\1 సెంటీమీటర్లు", out, flags=re.IGNORECASE)
    out = re.sub(r"(\d+(?:\.\d+)?)\s*సెం\.?\s*మీ\.?", r"\1 సెంటీమీటర్లు", out)
    out = re.sub(r"(\d+(?:\.\d+)?)\s*(?:km/h|kph)\b", r"గంటకు \1 కిలోమీటర్లు", out, flags=re.IGNORECASE)
    out = re.sub(r"(\d+(?:\.\d+)?)\s*kg\b", r"\1 కిలోలు", out, flags=re.IGNORECASE)
    out = re.sub(r"(\d+(?:\.\d+)?)\s*ml\b", r"\1 మిల్లీలీటర్లు", out, flags=re.IGNORECASE)

    # 4. Remove redundant parenthetical English acronym repeats following Telugu phrases
    out = re.sub(r"\s*\(\s*(?:AO|KVK|IMD|PIN|DAP|NPK)\s*\)", "", out, flags=re.IGNORECASE)

    # 5. Expand standalone English acronyms into natural Telugu phonetic forms
    out = re.sub(r"\bAO\b", "ఏఓ", out)
    out = re.sub(r"\bKVK\b", "కేవీకే", out)
    out = re.sub(r"\bIMD\b", "ఐఎండీ", out)
    out = re.sub(r"\bDAP\b", "డీఏపీ", out)
    out = re.sub(r"\bNPK\b", "ఎన్‌పీకే", out)
    out = re.sub(r"\bMOP\b", "ఎంఓపీ", out)
    out = re.sub(r"\bPIN\s*code\b", "పిన్ కోడ్", out, flags=re.IGNORECASE)
    out = re.sub(r"\bPIN\b", "పిన్", out)

    # 6. Smooth punctuation for spoken prosody
    out = out.replace("—", ", ")
    out = re.sub(r"\s+-\s+", ", ", out)
    out = re.sub(r"\(\s*\)", "", out)
    out = re.sub(r"\s+", " ", out).strip()
    return out


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
                topic="Indian agriculture",
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
                    tts_bytes = self._synthesize_speech(
                        clarification_text, detected_lang, channel=request.channel
                    )
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
                "మీరు వేర్వేరు ప్రాంతాల పేర్లు చెప్పారు . మీకు ఏ ఊరు లేదా మండలం వాతావరణ వివరాలు కావాలో స్పష్టంగా చెప్తారా?"
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
                    text=conv_resp.response_text,
                    language=conv_resp.language,
                    channel=request.channel,
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

    def synthesize_speech(
        self, text: str, language: str = "te-IN", channel: Optional[str] = None
    ) -> bytes:
        """
        Synthesize text into WAV audio using Gnani Timbre v2.5 Kaveri voice.
        """
        return self._synthesize_speech(text=text, language=language, channel=channel)

    def _synthesize_speech(
        self, text: str, language: str, channel: Optional[str] = None
    ) -> bytes:
        """
        Synthesize text into WAV audio using Gnani Timbre v2.5 Kaveri voice.
        """
        if not self.tts_client:
            raise TTSServiceError("Gnani TTS client is not configured.")

        target_lang, _ = normalize_language(language)
        voice = settings.TTS_VOICE_MAP.get(target_lang)
        if not voice:
            raise TTSServiceError(f"TTS voice is not confirmed for language {target_lang}; text response required.")
        spoken_text = (
            prepare_telugu_text_for_voice(text)
            if (target_lang == "te-IN" and channel == "telegram")
            else text
        )

        audio_bytes = self.tts_client.synthesize(
            text=spoken_text,
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
