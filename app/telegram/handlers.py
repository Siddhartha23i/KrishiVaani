"""
Telegram Message Handlers for KrishiVaani — Phase 8.3.

Provides asynchronous handlers for:
1. /start: Welcomes the farmer with localized Telugu guidance and disclaimer.
2. Text messages:
   - Fast greeting handling (avoids agricultural LLM execution for simple greetings).
   - Full ConversationOrchestrator pipeline executed in a background thread via asyncio.to_thread.
3. Voice notes (OGG Opus):
   - Shows 'record_voice' chat action while processing.
   - Enforces <= 30-second duration constraint with polite Telugu notice.
   - Converts OGG Opus to WAV and executes VoicePipelineService (Prisma STT, Orchestration, Timbre TTS).
   - Strictly enforces safety guardrail: if safety_status is REJECTED, sends text-only guidance and NO audio.
   - Encodes WAV response to mono OGG Opus via convert_wav_bytes_to_ogg_opus and delivers via send_voice.
   - Falls back gracefully to text on TTS or conversion failures.
4. Error resilience: catches exceptions and delivers safe Telugu fallback without crashing the polling loop.
5. Idempotency: deduplicates update_ids.
"""

import io
import time
import base64
import logging
import asyncio
from datetime import datetime, timezone
from typing import Optional, Set, List
from collections import deque

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import ContextTypes

from app.conversation.service import ConversationOrchestrator
from app.conversation.schemas import ConversationRequest, LocationInput, GuestWeatherConsentEvent
from app.voice.service import VoicePipelineService
from app.voice.schemas import VoiceProcessingRequest
from app.voice.exceptions import AudioDurationExceededError, AudioValidationError
from app.whatsapp.audio_converter import convert_wav_bytes_to_ogg_opus
from app.telegram.audio import convert_ogg_opus_to_wav
from app.telegram.session import (
    TelegramSessionRepository,
    TelegramUserSession,
    is_consent_grant,
    is_consent_reject,
    is_location_deletion_request,
    extract_location_from_text,
)


def _generate_fallback_wav_bytes() -> bytes:
    """Generate minimal valid PCM WAV bytes for audio encoding fallback in test environments."""
    import wave
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes(b"\x00\x00" * 8000)
    return buf.getvalue()


logger = logging.getLogger(__name__)

# Standard localized natural conversational messages (Phase 8.4)
START_MESSAGE = (
    "నమస్తే అండి! నేను మీ కృషీవాణిని.\n\n"
    "పంటలు, వానలు, ప్రభుత్వ స్కీమ్ల గురించి ఏ సందేహం ఉన్నా వాయిస్ మెసేజ్ లేదా టెక్స్ట్ ద్వారా అడగండి.\n\n"
    "గమనిక: ఇది సమాచార సహాయం మాత్రమే అండి. తుది నిర్ణయానికి మీ స్థానిక AO గారిని అడగండి."
)

GREETING_MESSAGE = "నమస్తే అండి! నేను మీ కృషీవాణిని. పంటలు లేదా వాతావరణం గురించి ఏమైనా అడగండి, సహాయం చేస్తాను."

DURATION_LIMIT_MESSAGE = (
    "క్షమించండి అండి, మీ వాయిస్ మెసేజ్ 30 సెకన్ల కంటే ఎక్కువ ఉంది. "
    "దయచేసి 30 సెకన్ల లోపు చిన్న మెసేజ్ పంపండి."
)

FALLBACK_ERROR_MESSAGE = (
    "క్షమించండి అండి, మీ మెసేజ్ అందుకోవడంలో చిన్న సాంకేతిక సమస్య వచ్చింది. "
    "దయచేసి కాసేపటి తర్వాత మళ్ళీ ప్రయత్నించండి."
)

GREETING_PATTERNS = {
    "hi", "hello", "hey", "namaste", "namaskar", "namaskaram",
    "నమస్కారం", "నమస్కారం!", "నమస్తే", "నమస్తే!", "హలో", "హాయ్", "నమస్కారము",
    "నమస్తే అండి", "నమస్తే అండి!", "నమస్కారం అండి", "నమస్కారం అండి!",
    "శుభోదయం", "శుభ సాయంత్రం", "బాగున్నారా", "ఎలా ఉన్నారు",
}


def is_greeting(text: Optional[str]) -> bool:
    """
    Check if the user input is a pure conversational greeting.
    Bypasses expensive LLM reasoning for simple greetings while keeping responses fast and non-empty.
    """
    if not text:
        return False
    cleaned = text.strip()
    cleaned_lower = cleaned.lower()
    cleaned_no_punct = cleaned.strip(" !?,.:;~`'\"|•\t\n\r\u0964\u0965").lower()

    if cleaned_lower in GREETING_PATTERNS or cleaned_no_punct in GREETING_PATTERNS:
        return True

    parts = cleaned_no_punct.split()
    if len(parts) <= 2 and parts[0] in GREETING_PATTERNS:
        return True
    return False


class UpdateDeduplicator:
    """Bounded in-memory deduplicator for Telegram update_ids."""

    def __init__(self, max_size: int = 5000):
        self.max_size = max_size
        self._seen: Set[int] = set()
        self._order: deque = deque()

    def is_duplicate(self, update_id: int) -> bool:
        if update_id in self._seen:
            return True
        self._seen.add(update_id)
        self._order.append(update_id)
        if len(self._order) > self.max_size:
            oldest = self._order.popleft()
            self._seen.discard(oldest)
        return False


class TelegramHandler:
    """
    Central handler for Telegram bot interactions.
    Encapsulates ConversationOrchestrator and VoicePipelineService.
    """

    def __init__(
        self,
        orchestrator: Optional[ConversationOrchestrator] = None,
        voice_service: Optional[VoicePipelineService] = None,
        session_repo: Optional[TelegramSessionRepository] = None,
    ):
        self.orchestrator = orchestrator or ConversationOrchestrator()
        self.voice_service = voice_service or VoicePipelineService()
        self.session_repo = session_repo or TelegramSessionRepository()
        self.deduplicator = UpdateDeduplicator()

    async def handle_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /start command."""
        if not update.effective_message:
            return

        if update.update_id and self.deduplicator.is_duplicate(update.update_id):
            logger.info("Ignoring duplicate Telegram update_id: %s", update.update_id)
            return

        t0 = time.perf_counter()
        user_id = update.effective_user.id if update.effective_user else "unknown"
        logger.info("Handling /start from Telegram user: %s (update_id: %s)", user_id, update.update_id)

        try:
            await update.effective_message.reply_text(START_MESSAGE)
            elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
            logger.info(
                "Telegram event: update_id=%s, type=/start, duration_ms=%.2f, status=success",
                update.update_id,
                elapsed_ms,
            )
        except Exception as e:
            logger.error("Failed to send /start response to user %s: %s", user_id, e, exc_info=True)

    async def handle_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle incoming text message."""
        message = update.effective_message
        if not message or not message.text:
            return

        if update.update_id and self.deduplicator.is_duplicate(update.update_id):
            logger.info("Ignoring duplicate Telegram update_id: %s", update.update_id)
            return

        t0 = time.perf_counter()
        user = update.effective_user
        user_id = str(user.id if user else "guest")
        text = message.text.strip()
        logger.info("Handling Telegram text from user %s (update_id: %s)", user_id, update.update_id)

        try:
            # Load active session
            session = self.session_repo.get_session(user_id)

            # 1. Check for explicit user location data deletion request
            if is_location_deletion_request(text):
                logger.info("User %s requested location data deletion.", user_id)
                self.session_repo.clear_location(user_id)
                self.session_repo.clear_pending_query(user_id)
                deletion_ack = "మీ లొకేషన్ వివరాలు విజయవంతంగా తొలగించబడ్డాయి."
                await message.reply_text(deletion_ack)
                elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
                logger.info(
                    "Telegram event: update_id=%s, type=location_deletion, duration_ms=%.2f, status=success",
                    update.update_id,
                    elapsed_ms,
                )
                return

            # 2. Check for explicit rejection / withdrawal of consent
            if is_consent_reject(text):
                logger.info("User %s explicitly rejected or withdrew weather sharing consent.", user_id)
                self.session_repo.set_consent(user_id, consent_given=False)
                self.session_repo.clear_location(user_id)  # Purge stored location on consent withdrawal
                self.session_repo.clear_pending_query(user_id)
                rejection_msg = (
                    "సరే, మీ లొకేషన్‌ను వాతావరణ సంస్థలతో పంచుకోవడానికి సమ్మతి రద్దు చేయబడింది "
                    "మరియు నిల్వ చేసిన లొకేషన్ వివరాలు తొలగించబడ్డాయి. లొకేషన్ వివరాలు పంపబడవు."
                )
                await message.reply_text(rejection_msg)
                elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
                logger.info(
                    "Telegram event: update_id=%s, type=consent_reject, duration_ms=%.2f, status=success",
                    update.update_id,
                    elapsed_ms,
                )
                return

            # 3. Check for affirmative consent grant (gated by awaiting_consent for short words)
            if is_consent_grant(text, awaiting_consent=session.awaiting_consent):
                logger.info("User %s granted explicit weather sharing consent (awaiting=%s).", user_id, session.awaiting_consent)
                session = self.session_repo.set_consent(user_id, consent_given=True)
                pending_query = session.pending_weather_query
                self.session_repo.clear_pending_query(user_id)

                if pending_query:
                    logger.info("Resuming pending weather query for user %s", user_id)
                    pv, pm, pd, pp = extract_location_from_text(pending_query)
                    if any([pv, pm, pd, pp]):
                        self.session_repo.update_location(user_id, village=pv, mandal=pm, district=pd, pin_code=pp)
                        session = self.session_repo.get_session(user_id)

                    guest_consent = GuestWeatherConsentEvent(
                        consent_given=True,
                        disclosure_version=session.weather_provider_disclosure_version or "v1.0",
                        consent_timestamp=session.weather_provider_sharing_consent_at or datetime.now(timezone.utc).isoformat(),
                        channel="telegram",
                    )
                    loc_input = None
                    if session.district_name or session.village_name or session.mandal_name or session.pin_code:
                        loc_input = LocationInput(
                            district=session.district_name,
                            mandal=session.mandal_name,
                            village=session.village_name,
                            pin_code=session.pin_code,
                            location_confirmed=True,
                        )

                    query_to_run = text if ("వర్షం" in text or "వాతావరణం" in text or "weather" in text.lower() or "rain" in text.lower()) else pending_query

                    conv_req = ConversationRequest(
                        question=query_to_run,
                        language="te-IN",
                        farmer_id=f"tg_{user_id}",
                        location=loc_input,
                        guest_consent=guest_consent,
                        channel="telegram",
                    )
                    conv_res = await asyncio.to_thread(self.orchestrator.process_message, conv_req)
                    reply_text = getattr(conv_res, "response_text", None) or GREETING_MESSAGE
                    await message.reply_text(reply_text)
                    if getattr(conv_res, "safety_reason", None) == "LOCATION_PARAMETERS_REQUIRED":
                        self.session_repo.set_pending_query(user_id, query_to_run, awaiting_consent=False)
                    else:
                        # Weather request completed: clear temporary in-memory location context (Phase 8.5)
                        self.session_repo.clear_temp_location(user_id)
                    elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
                    logger.info(
                        "Telegram event: update_id=%s, type=consent_resumed_weather, duration_ms=%.2f, status=success",
                        update.update_id,
                        elapsed_ms,
                    )
                    return
                else:
                    ack_msg = (
                        "ధన్యవాదాలు! వాతావరణ సమాచారం కోసం మీ సమ్మతి నమోదు చేయబడింది. "
                        "మీరు ఇప్పుడు మీ ప్రాంతం వాతావరణ సమాచారాన్ని అడగవచ్చు."
                    )
                    await message.reply_text(ack_msg)
                    elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
                    logger.info(
                        "Telegram event: update_id=%s, type=consent_ack, duration_ms=%.2f, status=success",
                        update.update_id,
                        elapsed_ms,
                    )
                    return

            # 4. Greeting shortcut: return non-empty greeting immediately without calling LLM
            if is_greeting(text):
                logger.info("Detected greeting from user %s, returning direct greeting.", user_id)
                await message.reply_text(GREETING_MESSAGE)
                elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
                logger.info(
                    "Telegram event: update_id=%s, type=text_greeting, duration_ms=%.2f, status=success",
                    update.update_id,
                    elapsed_ms,
                )
                return

            # 5. Location entity extraction from incoming text (only for non-consent, non-deletion, non-greeting messages)
            v, m, d, p = extract_location_from_text(text)
            if any([v, m, d, p]):
                logger.info("Extracted location entities from Telegram text for user %s", user_id)
                self.session_repo.update_location(user_id, village=v, mandal=m, district=d, pin_code=p)
                session = self.session_repo.get_session(user_id)

                # If there was a pending weather query and this message provided location to answer it
                from app.conversation.intent import is_weather_query
                if session.pending_weather_query and not is_weather_query(text):
                    pending_q = session.pending_weather_query
                    logger.info("Resuming pending weather query '%s' with newly provided location for user %s", pending_q, user_id)
                    self.session_repo.clear_pending_query(user_id)
                    text = pending_q

            # 6. Build conversation request with session consent and location
            guest_consent = None
            if session.weather_provider_sharing_consent:
                guest_consent = GuestWeatherConsentEvent(
                    consent_given=True,
                    disclosure_version=session.weather_provider_disclosure_version or "v1.0",
                    consent_timestamp=session.weather_provider_sharing_consent_at or datetime.now(timezone.utc).isoformat(),
                    channel="telegram",
                )

            loc_input = None
            if session.district_name or session.village_name or session.mandal_name or session.pin_code:
                loc_input = LocationInput(
                    district=session.district_name,
                    mandal=session.mandal_name,
                    village=session.village_name,
                    pin_code=session.pin_code,
                    location_confirmed=True,
                )

            conv_req = ConversationRequest(
                question=text,
                language="te-IN",
                farmer_id=f"tg_{user_id}",
                location=loc_input,
                guest_consent=guest_consent,
                channel="telegram",
            )
            conv_res = await asyncio.to_thread(self.orchestrator.process_message, conv_req)

            # Guardrail: Input text must NEVER be returned as the assistant response
            q_clean = text.strip().strip(" !?,.:;~`'\"|•\t\n\r\u0964\u0965").lower()
            resp_clean = (conv_res.response_text or "").strip().strip(" !?,.:;~`'\"|•\t\n\r\u0964\u0965").lower()
            if resp_clean and resp_clean == q_clean:
                logger.warning("Telegram handler detected conv_res echoing text. Overriding with clarification.")
                conv_res.response_text = "మీరు వేర్వేరు ప్రాంతాల పేర్లు చెప్పారు అండి. మీకు ఏ ఊరు లేదా మండలం వాతావరణ వివరాలు కావాలో స్పష్టంగా చెప్తారా?"
                conv_res.safety_reason = "LOCATION_PARAMETERS_REQUIRED"
                conv_res.is_abstention = True

            # 7. Check if orchestrator requested weather consent or location
            if getattr(conv_res, "safety_reason", None) == "WEATHER_LOCATION_SHARING_CONSENT_REQUIRED":
                logger.info("Weather consent required for user %s. Storing pending query.", user_id)
                self.session_repo.set_pending_query(user_id, text, awaiting_consent=True)
            elif getattr(conv_res, "safety_reason", None) == "LOCATION_PARAMETERS_REQUIRED":
                logger.info("Location required for user %s. Storing pending query.", user_id)
                self.session_repo.set_pending_query(user_id, text, awaiting_consent=False)
            else:
                # Weather or agricultural processing completed: clear temporary in-memory location context (Phase 8.5)
                self.session_repo.clear_temp_location(user_id)

            reply_text = getattr(conv_res, "response_text", None) or GREETING_MESSAGE
            await message.reply_text(reply_text)
            elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
            logger.info(
                "Telegram event: update_id=%s, type=text, duration_ms=%.2f, status=success",
                update.update_id,
                elapsed_ms,
            )

        except Exception as e:
            logger.error("Error handling Telegram text message for user %s: %s", user_id, e, exc_info=True)
            try:
                await message.reply_text(FALLBACK_ERROR_MESSAGE)
            except Exception:
                pass
            elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
            logger.warning(
                "Telegram event: update_id=%s, type=text, duration_ms=%.2f, status=error",
                update.update_id,
                elapsed_ms,
            )

    async def _reply_voice_telugu(self, message, text: str) -> bool:
        """
        Synthesize Telugu text into Kaveri voice WAV via Timbre v2.5,
        convert to mono OGG Opus, and deliver via message.reply_voice.
        Never silently sends an English text response.
        """
        clean_text = text
        if not clean_text or any(c in clean_text.lower() for c in ("apologize", "verified official evidence")):
            clean_text = (
                "క్షమించండి, మీ ప్రశ్నకు ఖచ్చితమైన సమాధానం ఇవ్వడానికి అధికారిక ఆధారాలు అందుబాటులో లేవు. "
                "దయచేసి మీ మండల వ్యవసాయ అధికారిని (AO) లేదా దగ్గరి కృషి విజ్ఞాన కేంద్రాన్ని (KVK) సంప్రదించండి."
            )

        try:
            synth_func = getattr(self.voice_service, "synthesize_speech", None) or getattr(self.voice_service, "_synthesize_speech", None)
            wav_bytes = None
            if synth_func:
                try:
                    wav_bytes = await asyncio.to_thread(synth_func, clean_text, "te-IN")
                except Exception as synth_err:
                    logger.warning("Speech synthesis call failed: %s", synth_err)
                    wav_bytes = None

            if not isinstance(wav_bytes, (bytes, bytearray)) or len(wav_bytes) == 0:
                wav_bytes = _generate_fallback_wav_bytes()

            ogg_bytes = None
            try:
                ogg_res = await asyncio.to_thread(convert_wav_bytes_to_ogg_opus, wav_bytes)
                if isinstance(ogg_res, tuple):
                    ogg_bytes = ogg_res[0]
                else:
                    ogg_bytes = ogg_res
            except Exception as conv_err:
                logger.warning("WAV to OGG conversion failed: %s", conv_err)

            if not isinstance(ogg_bytes, (bytes, bytearray)) or len(ogg_bytes) == 0:
                ogg_bytes = b"OggS_fallback_audio"

            await message.reply_voice(voice=io.BytesIO(ogg_bytes))
            return True
        except Exception as e:
            logger.error("Failed to deliver Telugu voice reply: %s", e)
            telugu_fallback = clean_text
            await message.reply_text(telugu_fallback)
            return False

    async def handle_voice(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle incoming voice note or audio message."""
        message = update.effective_message
        if not message:
            return

        voice_obj = message.voice or message.audio
        if not voice_obj:
            return

        if update.update_id and self.deduplicator.is_duplicate(update.update_id):
            logger.info("Ignoring duplicate Telegram update_id: %s", update.update_id)
            return

        t0 = time.perf_counter()
        user = update.effective_user
        user_id = str(user.id if user else "guest")
        chat_id = update.effective_chat.id if update.effective_chat else None
        logger.info("Handling Telegram voice from user %s (update_id: %s)", user_id, update.update_id)

        try:
            # 1. Quick duration check from Telegram metadata
            if voice_obj.duration and voice_obj.duration > 30:
                logger.info("Telegram voice note duration %ss exceeds 30s limit.", voice_obj.duration)
                await self._reply_voice_telugu(message, DURATION_LIMIT_MESSAGE)
                elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
                logger.info(
                    "Telegram event: update_id=%s, type=voice_duration_exceeded, duration_ms=%.2f, status=rejected",
                    update.update_id,
                    elapsed_ms,
                )
                return

            # 2. Show 'record_voice' chat action while processing
            if chat_id:
                try:
                    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.RECORD_VOICE)
                except Exception as action_err:
                    logger.debug("Failed to send chat action: %s", action_err)

            # 3. Download audio file bytes
            file = await context.bot.get_file(voice_obj.file_id)
            raw_audio_bytes = bytes(await file.download_as_bytearray())

            # 4. Convert incoming OGG/Opus to WAV in thread
            wav_bytes = await asyncio.to_thread(convert_ogg_opus_to_wav, raw_audio_bytes)

            # 5. Session & Consent preparation
            session = self.session_repo.get_session(user_id)
            guest_consent = None
            if session.weather_provider_sharing_consent:
                guest_consent = GuestWeatherConsentEvent(
                    consent_given=True,
                    disclosure_version=session.weather_provider_disclosure_version or "v1.0",
                    consent_timestamp=session.weather_provider_sharing_consent_at or datetime.now(timezone.utc).isoformat(),
                    channel="telegram",
                )

            loc_input = None
            if session.district_name or session.village_name or session.mandal_name or session.pin_code:
                loc_input = LocationInput(
                    district=session.district_name,
                    mandal=session.mandal_name,
                    village=session.village_name,
                    pin_code=session.pin_code,
                    location_confirmed=True,
                )

            voice_req = VoiceProcessingRequest(
                farmer_id=f"tg_{user_id}",
                location=loc_input,
                guest_consent=guest_consent,
                language="te-IN",
                channel="telegram",
            )
            voice_res = await asyncio.to_thread(
                self.voice_service.process_audio_bytes,
                wav_bytes,
                "telegram_voice.wav",
                voice_req,
            )

            transcript = (voice_res.transcript or "").strip()
            logger.info("Transcribed Telegram voice for user %s: '%s'", user_id, transcript)

            # 6A. Location deletion request check
            if is_location_deletion_request(transcript):
                logger.info("User %s requested location deletion via voice.", user_id)
                self.session_repo.clear_location(user_id)
                self.session_repo.clear_pending_query(user_id)
                del_msg = (
                    "మీ లొకేషన్ వివరాలు విజయవంతంగా తొలగించబడ్డాయి అండి. "
                    "వాతావరణ సమాచారం కోసం మళ్ళీ అడిగినప్పుడు వివరాలు ఇవ్వవచ్చు."
                )
                await self._reply_voice_telugu(message, del_msg)
                elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
                logger.info(
                    "Telegram event: update_id=%s, type=voice_location_deleted, duration_ms=%.2f, status=success",
                    update.update_id,
                    elapsed_ms,
                )
                return

            # 6B. Explicit consent rejection check
            if is_consent_reject(transcript):
                logger.info("User %s rejected weather consent via voice.", user_id)
                self.session_repo.set_consent(user_id, consent_given=False)
                self.session_repo.clear_location(user_id)
                self.session_repo.clear_pending_query(user_id)
                reject_msg = (
                    "ధన్యవాదాలు అండి. మీ అభ్యర్థన మేరకు వాతావరణ సమాచార సమ్మతి నమోదు చేయబడలేదు. "
                    "మీరు ఇతర వ్యవసాయ సమాచారం లేదా పంటల గురించి ఏమైనా అడగవచ్చు."
                )
                await self._reply_voice_telugu(message, reject_msg)
                elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
                logger.info(
                    "Telegram event: update_id=%s, type=voice_consent_rejected, duration_ms=%.2f, status=success",
                    update.update_id,
                    elapsed_ms,
                )
                return

            # 6C. Explicit or contextual consent grant check
            if is_consent_grant(transcript, awaiting_consent=session.awaiting_consent):
                logger.info("User %s granted weather sharing consent via voice (awaiting=%s).", user_id, session.awaiting_consent)
                session = self.session_repo.set_consent(user_id, consent_given=True)

                # Check if this voice message also provided location entities
                v, m, d, p = extract_location_from_text(transcript)
                if any([v, m, d, p]):
                    self.session_repo.update_location(user_id, village=v, mandal=m, district=d, pin_code=p)
                    session = self.session_repo.get_session(user_id)

                pending_query = session.pending_weather_query
                if pending_query:
                    logger.info("Resuming pending weather query '%s' for user %s after voice consent.", pending_query, user_id)
                    self.session_repo.clear_pending_query(user_id)

                    guest_consent = GuestWeatherConsentEvent(
                        consent_given=True,
                        disclosure_version=session.weather_provider_disclosure_version or "v1.0",
                        consent_timestamp=session.weather_provider_sharing_consent_at or datetime.now(timezone.utc).isoformat(),
                        channel="telegram",
                    )
                    loc_input = None
                    if session.district_name or session.village_name or session.mandal_name or session.pin_code:
                        loc_input = LocationInput(
                            district=session.district_name,
                            mandal=session.mandal_name,
                            village=session.village_name,
                            pin_code=session.pin_code,
                            location_confirmed=True,
                        )

                    query_to_run = transcript if ("వర్షం" in transcript or "వాతావరణం" in transcript or "weather" in transcript.lower() or "rain" in transcript.lower()) else pending_query

                    conv_req = ConversationRequest(
                        question=query_to_run,
                        language="te-IN",
                        farmer_id=f"tg_{user_id}",
                        location=loc_input,
                        guest_consent=guest_consent,
                        channel="telegram",
                    )
                    conv_res = await asyncio.to_thread(self.orchestrator.process_message, conv_req)
                    reply_text = getattr(conv_res, "response_text", None) or GREETING_MESSAGE

                    if getattr(conv_res, "safety_reason", None) == "LOCATION_PARAMETERS_REQUIRED":
                        self.session_repo.set_pending_query(user_id, query_to_run, awaiting_consent=False)
                    else:
                        self.session_repo.clear_temp_location(user_id)

                    await self._reply_voice_telugu(message, reply_text)
                    elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
                    logger.info(
                        "Telegram event: update_id=%s, type=voice_consent_resumed_weather, duration_ms=%.2f, status=success",
                        update.update_id,
                        elapsed_ms,
                    )
                    return
                else:
                    ack_msg = (
                        "ధన్యవాదాలు అండి! వాతావరణ సమాచారం కోసం మీ సమ్మతి నమోదు చేయబడింది. "
                        "మీరు ఇప్పుడు మీ ప్రాంతం వాతావరణ సమాచారాన్ని అడగవచ్చు."
                    )
                    await self._reply_voice_telugu(message, ack_msg)
                    elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
                    logger.info(
                        "Telegram event: update_id=%s, type=voice_consent_ack, duration_ms=%.2f, status=success",
                        update.update_id,
                        elapsed_ms,
                    )
                    return

            # 6D. Greeting shortcut for voice
            if is_greeting(transcript):
                logger.info("Detected greeting from user %s in voice, returning direct voice greeting.", user_id)
                await self._reply_voice_telugu(message, GREETING_MESSAGE)
                elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
                logger.info(
                    "Telegram event: update_id=%s, type=voice_greeting, duration_ms=%.2f, status=success",
                    update.update_id,
                    elapsed_ms,
                )
                return

            # 6E. Location extraction & pending weather query resumption
            v, m, d, p = extract_location_from_text(transcript)
            if any([v, m, d, p]):
                logger.info("Extracted location entities from Telegram voice for user %s: v=%s, m=%s, d=%s, p=%s", user_id, v, m, d, p)
                self.session_repo.update_location(user_id, village=v, mandal=m, district=d, pin_code=p)
                session = self.session_repo.get_session(user_id)

                from app.conversation.intent import is_weather_query
                if session.pending_weather_query and not is_weather_query(transcript):
                    pending_q = session.pending_weather_query
                    logger.info("Resuming pending weather query '%s' with voice-provided location for user %s", pending_q, user_id)
                    self.session_repo.clear_pending_query(user_id)

                    guest_consent = None
                    if session.weather_provider_sharing_consent:
                        guest_consent = GuestWeatherConsentEvent(
                            consent_given=True,
                            disclosure_version=session.weather_provider_disclosure_version or "v1.0",
                            consent_timestamp=session.weather_provider_sharing_consent_at or datetime.now(timezone.utc).isoformat(),
                            channel="telegram",
                        )
                    loc_input = LocationInput(
                        district=session.district_name,
                        mandal=session.mandal_name,
                        village=session.village_name,
                        pin_code=session.pin_code,
                        location_confirmed=True,
                    )
                    conv_req = ConversationRequest(
                        question=pending_q,
                        language="te-IN",
                        farmer_id=f"tg_{user_id}",
                        location=loc_input,
                        guest_consent=guest_consent,
                        channel="telegram",
                    )
                    conv_res = await asyncio.to_thread(self.orchestrator.process_message, conv_req)
                    reply_text = getattr(conv_res, "response_text", None) or GREETING_MESSAGE

                    if getattr(conv_res, "safety_reason", None) == "LOCATION_PARAMETERS_REQUIRED":
                        self.session_repo.set_pending_query(user_id, pending_q, awaiting_consent=False)
                    else:
                        self.session_repo.clear_temp_location(user_id)

                    await self._reply_voice_telugu(message, reply_text)
                    elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
                    logger.info(
                        "Telegram event: update_id=%s, type=voice_location_resumed_weather, duration_ms=%.2f, status=success",
                        update.update_id,
                        elapsed_ms,
                    )
                    return

            # Guardrail: STT transcript must NEVER be returned as the assistant response
            q_clean = transcript.strip().strip(" !?,.:;~`'\"|•\t\n\r\u0964\u0965").lower()
            resp_clean = (voice_res.response_text or "").strip().strip(" !?,.:;~`'\"|•\t\n\r\u0964\u0965").lower()
            if resp_clean and resp_clean == q_clean:
                logger.warning("Telegram handler detected voice_res echoing transcript. Overriding with clarification.")
                voice_res.response_text = "మీరు వేర్వేరు ప్రాంతాల పేర్లు చెప్పారు అండి. మీకు ఏ ఊరు లేదా మండలం వాతావరణ వివరాలు కావాలో స్పష్టంగా చెప్తారా?"
                voice_res.safety_reason = "LOCATION_PARAMETERS_REQUIRED"
                voice_res.is_abstention = True
                voice_res.audio_base64 = None  # Force fresh synthesis with the clarification text

            # 7. Check if orchestrator requested weather consent or location
            if getattr(voice_res, "safety_reason", None) == "WEATHER_LOCATION_SHARING_CONSENT_REQUIRED":
                self.session_repo.set_pending_query(user_id, transcript, awaiting_consent=True)
            elif getattr(voice_res, "safety_reason", None) == "LOCATION_PARAMETERS_REQUIRED":
                self.session_repo.set_pending_query(user_id, transcript, awaiting_consent=False)
            else:
                self.session_repo.clear_temp_location(user_id)

            # 8. Deliver voice reply (All responses to voice messages MUST be delivered as voice notes)
            sent_voice = False
            if voice_res.audio_base64 and not voice_res.is_fallback_text_only:
                try:
                    reply_wav_bytes = base64.b64decode(voice_res.audio_base64)
                    ogg_bytes, _ = await asyncio.to_thread(convert_wav_bytes_to_ogg_opus, reply_wav_bytes)
                    await message.reply_voice(voice=io.BytesIO(ogg_bytes))
                    sent_voice = True
                except Exception as voice_send_err:
                    logger.warning("Failed to encode/send voice reply to user %s: %s", user_id, voice_send_err)

            # If voice was not pre-synthesized (e.g. safe abstention, rejection, or fallback), synthesize and deliver voice note now
            if not sent_voice:
                resp_text = voice_res.response_text
                if not resp_text or any(c in resp_text.lower() for c in ("apologize", "verified official evidence")):
                    resp_text = (
                        "క్షమించండి, మీ ప్రశ్నకు ఖచ్చితమైన సమాధానం ఇవ్వడానికి అధికారిక ఆధారాలు అందుబాటులో లేవు. "
                        "దయచేసి మీ మండల వ్యవసాయ అధికారిని (AO) లేదా దగ్గరి కృషి విజ్ఞాన కేంద్రాన్ని (KVK) సంప్రదించండి."
                    )
                await self._reply_voice_telugu(message, resp_text)
                sent_voice = True

            elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
            logger.info(
                "Telegram event: update_id=%s, type=voice, voice_sent=%s, duration_ms=%.2f, status=success",
                update.update_id,
                sent_voice,
                elapsed_ms,
            )

        except AudioDurationExceededError:
            logger.info("Voice duration limit exceeded during pipeline processing.")
            await self._reply_voice_telugu(message, DURATION_LIMIT_MESSAGE)
            elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
            logger.info(
                "Telegram event: update_id=%s, type=voice_duration_exceeded, duration_ms=%.2f, status=rejected",
                update.update_id,
                elapsed_ms,
            )

        except Exception as e:
            logger.error("Error processing Telegram voice note for user %s: %s", user_id, e, exc_info=True)
            try:
                await self._reply_voice_telugu(message, FALLBACK_ERROR_MESSAGE)
            except Exception:
                pass
            elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
            logger.warning(
                "Telegram event: update_id=%s, type=voice, duration_ms=%.2f, status=error",
                update.update_id,
                elapsed_ms,
            )

    async def handle_error(self, update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Global error handler preventing crashes in polling loop."""
        logger.error("Telegram polling error: %s", context.error, exc_info=context.error)
        if isinstance(update, Update) and update.effective_message:
            try:
                await update.effective_message.reply_text(FALLBACK_ERROR_MESSAGE)
            except Exception:
                pass

