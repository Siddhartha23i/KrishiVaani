"""
Twilio WhatsApp Service Orchestrator for KrishiVaani — Phase 8.2.3.

Processes inbound WhatsApp messages and voice notes from Twilio Sandbox webhooks,
returning immediate synchronous TwiML MessagingResponse XML:
1. Text messages -> ConversationOrchestrator -> TwiML <Response><Message>{reply_text}</Message></Response>.
2. Voice notes (Audio MediaUrl0) -> Authenticated Download -> Validate (<=30s, <=15MB)
   -> VoicePipelineService -> Timbre WAV -> Mono OGG Opus -> Temporary Media Endpoint
   -> TwiML <Response><Message><Media>{public_media_url}</Media></Message></Response>.
3. Strict idempotency enforcement via SQLite twilio_events MessageSid tracking (returns empty TwiML on duplicate).
4. On safety rejection: return safe guidance text in TwiML; do NOT synthesize or return speech.
5. Graceful fallback: If voice generation fails, return safe text fallback in TwiML.
6. Does NOT invoke outbound REST API send_text_message/send_media_message for incoming webhook replies,
   completely bypassing Error 21654 (ContentSid Required) while preserving TwilioClient for business-initiated sends.
"""

import os
import uuid
import base64
import logging
import tempfile
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any, Tuple
import imageio_ffmpeg
from twilio.twiml.messaging_response import MessagingResponse

from app.core.config import settings
from app.services.farmer_service import FarmerService
from app.models.farmer import FarmerModel
from app.conversation.service import ConversationOrchestrator
from app.conversation.schemas import ConversationRequest
from app.voice.service import VoicePipelineService
from app.voice.schemas import VoiceProcessingRequest
from app.voice.exceptions import (
    AudioValidationError,
    AudioDurationExceededError,
    UnsupportedAudioFormatError,
    AudioSizeExceededError,
)
from app.whatsapp.audio_converter import convert_wav_bytes_to_ogg_opus
from app.twilio.exceptions import (
    TwilioError,
    TwilioConfigurationError,
    TwilioMediaDownloadError,
    TwilioMessageSendError,
    TwilioDuplicateMessageError,
    TwilioAudioValidationError,
)
from app.twilio.client import TwilioClient
from app.twilio.event_repository import TwilioEventRepository
from app.twilio.media_manager import TwilioMediaManager
from app.twilio.security import mask_phone_number

logger = logging.getLogger(__name__)

# Standard localized guidance messages
UNSUPPORTED_MEDIA_MESSAGES = {
    "te-IN": "నమస్కారం! కృషివాణి ప్రస్తుతం వాయిస్ నోట్స్ (వాయిస్ సందేశాలు) మరియు టెక్స్ట్ సందేశాలను మాత్రమే స్వీకరిస్తుంది. దయచేసి మీ వ్యవసాయ సందేహాన్ని వాయిస్ లేదా టెక్స్ట్ రూపంలో పంపండి.",
    "hi-IN": "नमस्ते! कृषवाणी वर्तमान में केवल वॉयस संदेश (वॉयस नोट्स) और टेक्स्ट संदेश स्वीकार करती है। कृपया अपना कृषि प्रश्न वॉयस या टेक्स्ट के रूप में भेजें।",
    "en-IN": "Hello! KrishiVaani currently accepts voice notes and text messages. Please send your agricultural query as a voice or text message.",
}

AUDIO_DURATION_LIMIT_MESSAGES = {
    "te-IN": "క్షమించండి, మీ వాయిస్ సందేశం 30 సెకన్ల పరిమితిని మించింది. దయచేసి 30 సెకన్ల లోపు ఉండేలా చిన్న సందేశాన్ని పంపండి.",
    "hi-IN": "क्षमा करें, आपका वॉयस संदेश 30 सेकंड की सीमा से अधिक है। कृपया 30 सेकंड से कम का संदेश भेजें।",
    "en-IN": "Sorry, your voice message exceeds the 30-second limit. Please send a shorter voice note under 30 seconds.",
}

AUDIO_PROCESSING_ERROR_MESSAGES = {
    "te-IN": "క్షమించండి, మీ వాయిస్ సందేశాన్ని ప్రాసెస్ చేయడంలో సాంకేతిక సమస్య ఏర్పడింది. దయచేసి మరలా ప్రయత్నించండి లేదా మీ సందేహాన్ని టెక్స్ట్ రూపంలో పంపండి.",
    "hi-IN": "क्षमा करें, आपके वॉयस संदेश को प्रोसेस करने में समस्या हुई। कृपया पुनः प्रयास करें या टेक्स्ट संदेश भेजें।",
    "en-IN": "Sorry, there was a technical issue processing your voice note. Please try again or send a text message.",
}

MIME_TO_EXT = {
    "audio/ogg": ".ogg",
    "audio/opus": ".ogg",
    "audio/mp4": ".m4a",
    "audio/x-m4a": ".m4a",
    "audio/m4a": ".m4a",
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/wave": ".wav",
    "audio/aac": ".aac",
    "audio/flac": ".flac",
    "audio/amr": ".amr",
    "audio/3gpp": ".amr",
}


class TwilioService:
    """
    Central service for processing incoming Twilio WhatsApp webhooks and returning TwiML responses.
    """

    def __init__(
        self,
        client: Optional[TwilioClient] = None,
        event_repo: Optional[TwilioEventRepository] = None,
        media_manager: Optional[TwilioMediaManager] = None,
        farmer_service: Optional[FarmerService] = None,
        voice_service: Optional[VoicePipelineService] = None,
        orchestrator: Optional[ConversationOrchestrator] = None,
        db_path: Optional[Path] = None,
    ):
        self.db_path = db_path or settings.DATABASE_PATH
        self.client = client or TwilioClient()
        self.event_repo = event_repo or TwilioEventRepository(db_path=self.db_path)
        self.media_manager = media_manager or TwilioMediaManager()
        self.farmer_service = farmer_service or FarmerService(db_path=self.db_path)
        self.voice_service = voice_service or VoicePipelineService()
        self.orchestrator = orchestrator or ConversationOrchestrator(
            farmer_service=self.farmer_service, db_path=self.db_path
        )

    def process_incoming_webhook(self, form_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process a form-encoded webhook dictionary received from Twilio.
        Enforces MessageSid idempotency, executes conversation pipeline synchronously,
        and returns TwiML MessagingResponse for free-form replies in the WhatsApp Sandbox.
        """
        message_sid = form_data.get("MessageSid")
        account_sid = form_data.get("AccountSid")
        from_number = form_data.get("From")
        to_number = form_data.get("To") or settings.twilio_whatsapp_from
        body = form_data.get("Body")
        num_media_raw = form_data.get("NumMedia", 0)
        try:
            num_media = int(num_media_raw or 0)
        except (ValueError, TypeError):
            num_media = 0

        media_url = form_data.get("MediaUrl0")
        media_content_type = form_data.get("MediaContentType0")

        if not message_sid or not from_number:
            logger.warning("Malformed Twilio webhook: missing MessageSid or From.")
            empty_twiml = '<?xml version="1.0" encoding="UTF-8"?>\n<Response></Response>'
            return {"status": "ignored", "reason": "missing_required_fields", "twiml": empty_twiml}

        masked_sender = mask_phone_number(from_number)

        # 1. Determine message classification
        if num_media > 0 and media_url:
            clean_content_type = (media_content_type or "").split(";")[0].strip().lower()
            if clean_content_type.startswith("audio/") or clean_content_type in ("video/ogg", "application/ogg"):
                msg_type = "audio"
            else:
                msg_type = "unsupported_media"
        elif body and body.strip():
            msg_type = "text"
        else:
            msg_type = "empty_or_unknown"

        # 2. Idempotency Check via SQLite twilio_events
        is_new = self.event_repo.record_event(
            message_sid=message_sid,
            account_sid=account_sid,
            from_number=from_number,
            to_number=to_number,
            message_type=msg_type,
            body=body,
            media_url=media_url,
            media_content_type=media_content_type,
        )

        if not is_new:
            logger.info("Duplicate Twilio delivery ignored: MessageSid=%s from=%s", message_sid, masked_sender)
            empty_twiml = '<?xml version="1.0" encoding="UTF-8"?>\n<Response></Response>'
            return {
                "status": "duplicate_ignored",
                "message_sid": message_sid,
                "twiml": empty_twiml,
            }

        # Mark event status as PROCESSING
        self.event_repo.update_status(message_sid=message_sid, status="PROCESSING")

        try:
            # 3. Resolve Farmer Profile
            farmer = self._get_or_create_farmer(from_number)
            preferred_lang = farmer.preferred_language or "te-IN"

            # 4. Dispatch by message type to generate TwiML
            if msg_type == "audio":
                result = self._handle_audio_message(form_data, farmer, message_sid)
            elif msg_type == "text":
                result = self._handle_text_message(form_data, farmer, message_sid)
            elif msg_type == "unsupported_media":
                result = self._handle_unsupported_media(from_number, preferred_lang, message_sid)
            else:
                result = self._handle_empty_message(from_number, preferred_lang, message_sid)

            # Update event status as COMPLETED
            summary = f"type={msg_type};status={result.get('status', 'success')}"
            self.event_repo.update_status(
                message_sid=message_sid,
                status="COMPLETED",
                response_summary=summary,
            )
            return result

        except Exception as e:
            logger.error("Error processing Twilio webhook MessageSid=%s from %s: %s", message_sid, masked_sender, str(e), exc_info=True)
            self.event_repo.update_status(
                message_sid=message_sid,
                status="FAILED",
                error_message=str(e),
            )
            err_twiml = MessagingResponse()
            err_twiml.message(AUDIO_PROCESSING_ERROR_MESSAGES.get("te-IN"))
            return {
                "status": "error",
                "message_sid": message_sid,
                "error": str(e),
                "twiml": str(err_twiml),
            }

    def _handle_text_message(
        self,
        form_data: Dict[str, Any],
        farmer: FarmerModel,
        message_sid: str,
    ) -> Dict[str, Any]:
        """
        Handle incoming text message.
        Routes through ConversationOrchestrator and returns TwiML MessagingResponse.
        Does NOT call TwilioClient.send_text_message() for inbound webhook replies.
        """
        sender = form_data["From"]
        body = form_data.get("Body", "").strip()
        masked_sender = mask_phone_number(sender)

        logger.info("Processing Twilio text message from %s (MessageSid: %s)", masked_sender, message_sid)

        conv_req = ConversationRequest(
            question=body,
            language=farmer.preferred_language or "te-IN",
            farmer_id=farmer.farmer_id,
        )

        conv_res = self.orchestrator.process_message(conv_req)
        reply_text = conv_res.response_text

        # Generate TwiML MessagingResponse
        twiml = MessagingResponse()
        twiml.message(reply_text)
        twiml_str = str(twiml)

        logger.info("Generated TwiML text reply for %s (MessageSid: %s)", masked_sender, message_sid)

        return {
            "status": "success",
            "message_sid": message_sid,
            "message_type": "text",
            "intent": conv_res.intent.value if hasattr(conv_res.intent, "value") else str(conv_res.intent),
            "reply_text": reply_text,
            "twiml": twiml_str,
        }

    def _handle_audio_message(
        self,
        form_data: Dict[str, Any],
        farmer: FarmerModel,
        message_sid: str,
    ) -> Dict[str, Any]:
        """
        Handle incoming voice note from Twilio.
        Authenticated download -> validate size/duration -> VoicePipelineService -> convert WAV to OGG
        -> expose URL -> return TwiML with <Media> URL.
        On safety rejection: return safe text in TwiML; do NOT synthesize or return speech.
        On failure: return safe text fallback in TwiML.
        Does NOT call TwilioClient.send_media_message() for inbound webhook replies.
        """
        sender = form_data["From"]
        media_url = form_data.get("MediaUrl0")
        media_content_type = form_data.get("MediaContentType0", "audio/ogg")
        masked_sender = mask_phone_number(sender)
        preferred_lang = farmer.preferred_language or "te-IN"

        if not media_url:
            raise TwilioError("Audio message missing MediaUrl0.")

        logger.info("Processing Twilio voice note from %s (MessageSid: %s)", masked_sender, message_sid)

        # Step 1: Securely download audio using Twilio Basic Auth
        try:
            audio_bytes, fetched_content_type = self.client.download_media(media_url)
        except AudioSizeExceededError:
            notice = AUDIO_DURATION_LIMIT_MESSAGES.get(preferred_lang, AUDIO_DURATION_LIMIT_MESSAGES["te-IN"])
            twiml = MessagingResponse()
            twiml.message(notice)
            return {
                "status": "audio_size_exceeded_notice_sent",
                "message_sid": message_sid,
                "reply_text": notice,
                "twiml": str(twiml),
            }
        except Exception as dl_err:
            logger.error("Failed to download media for %s: %s", message_sid, dl_err)
            notice = AUDIO_PROCESSING_ERROR_MESSAGES.get(preferred_lang, AUDIO_PROCESSING_ERROR_MESSAGES["te-IN"])
            twiml = MessagingResponse()
            twiml.message(notice)
            return {
                "status": "download_failed_notice_sent",
                "message_sid": message_sid,
                "error": str(dl_err),
                "reply_text": notice,
                "twiml": str(twiml),
            }

        # Step 2: Determine file extension and normalize if AMR
        content_type_clean = (fetched_content_type or media_content_type or "").split(";")[0].strip().lower()
        ext = MIME_TO_EXT.get(content_type_clean, ".ogg")

        processed_bytes = audio_bytes
        if ext == ".amr":
            try:
                processed_bytes, ext = self._convert_amr_to_wav(audio_bytes)
            except Exception as amr_err:
                logger.warning("AMR conversion failed: %s. Proceeding with raw bytes.", amr_err)

        filename = f"twilio_voice_{message_sid}{ext}"

        # Step 3: Run through Voice Pipeline Service
        voice_req = VoiceProcessingRequest(
            farmer_id=farmer.farmer_id,
            language=preferred_lang,
        )

        try:
            voice_res = self.voice_service.process_audio_bytes(
                audio_bytes=processed_bytes,
                filename=filename,
                request=voice_req,
            )
        except AudioDurationExceededError:
            notice = AUDIO_DURATION_LIMIT_MESSAGES.get(preferred_lang, AUDIO_DURATION_LIMIT_MESSAGES["te-IN"])
            twiml = MessagingResponse()
            twiml.message(notice)
            return {
                "status": "duration_exceeded_notice_sent",
                "message_sid": message_sid,
                "reply_text": notice,
                "twiml": str(twiml),
            }
        except (AudioValidationError, UnsupportedAudioFormatError) as audio_err:
            logger.warning("Audio validation error for %s: %s", message_sid, audio_err)
            notice = AUDIO_PROCESSING_ERROR_MESSAGES.get(preferred_lang, AUDIO_PROCESSING_ERROR_MESSAGES["te-IN"])
            twiml = MessagingResponse()
            twiml.message(notice)
            return {
                "status": "audio_validation_failed_notice_sent",
                "message_sid": message_sid,
                "error": str(audio_err),
                "reply_text": notice,
                "twiml": str(twiml),
            }

        response_text = voice_res.response_text

        # Step 4: Safety Check: If REJECTED, NEVER synthesize or return speech!
        if voice_res.safety_status == "REJECTED":
            logger.warning("Safety REJECTED voice response for %s. Returning safe text in TwiML.", masked_sender)
            twiml = MessagingResponse()
            twiml.message(response_text)
            return {
                "status": "safety_rejected_text_sent",
                "message_sid": message_sid,
                "voice_sent": False,
                "transcript": voice_res.transcript,
                "intent": voice_res.intent,
                "reply_text": response_text,
                "twiml": str(twiml),
            }

        # Step 5: Convert WAV to mono OGG Opus, store in MediaManager, and build TwiML Media URL
        sent_voice = False
        public_media_url = None

        if voice_res.audio_base64 and not voice_res.is_fallback_text_only:
            try:
                wav_bytes = base64.b64decode(voice_res.audio_base64)
                ogg_bytes, duration = convert_wav_bytes_to_ogg_opus(wav_bytes)

                # Store in temporary MediaManager
                token = self.media_manager.store_media(ogg_bytes)
                public_media_url = self.media_manager.build_media_url(
                    token, base_url=settings.twilio_webhook_public_base_url
                )

                # Build TwiML with <Media> URL (strictly no caption text with voice note)
                twiml = MessagingResponse()
                msg = twiml.message()
                msg.media(public_media_url)
                twiml_str = str(twiml)
                sent_voice = True
                logger.info("Generated TwiML voice note for %s (media token: %s)", masked_sender, token)

            except Exception as voice_err:
                logger.warning(
                    "Twilio voice synthesis/conversion failed for %s (%s). Falling back to text TwiML.",
                    masked_sender,
                    str(voice_err),
                )
                sent_voice = False

        # Step 6: Text fallback if voice note was not generated
        if not sent_voice:
            logger.info("Returning text TwiML response to %s as fallback/text-only mode.", masked_sender)
            twiml = MessagingResponse()
            twiml.message(response_text)
            twiml_str = str(twiml)

        return {
            "status": "success",
            "message_sid": message_sid,
            "message_type": "audio",
            "voice_sent": sent_voice,
            "transcript": voice_res.transcript,
            "intent": voice_res.intent,
            "reply_text": response_text,
            "media_url": public_media_url,
            "twiml": twiml_str,
        }

    def _convert_amr_to_wav(self, amr_bytes: bytes) -> Tuple[bytes, str]:
        """Convert incoming AMR audio bytes to WAV for downstream compatibility."""
        with tempfile.NamedTemporaryFile(delete=False, suffix=".amr") as f_amr:
            f_amr.write(amr_bytes)
            f_amr.flush()
            amr_path = Path(f_amr.name)

        wav_path = amr_path.with_suffix(".wav")
        try:
            ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
            proc = subprocess.run(
                [ffmpeg_exe, "-y", "-i", str(amr_path), "-ar", "16000", "-ac", "1", str(wav_path)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=10,
            )
            if proc.returncode == 0 and wav_path.exists():
                return wav_path.read_bytes(), ".wav"
            return amr_bytes, ".amr"
        finally:
            for p in (amr_path, wav_path):
                if p.exists():
                    try:
                        p.unlink()
                    except Exception:
                        pass

    def _handle_unsupported_media(
        self,
        from_number: str,
        preferred_lang: str,
        message_sid: str,
    ) -> Dict[str, Any]:
        """Send capability guidance for unsupported media (images, videos, documents)."""
        guidance = UNSUPPORTED_MEDIA_MESSAGES.get(preferred_lang, UNSUPPORTED_MEDIA_MESSAGES["te-IN"])
        twiml = MessagingResponse()
        twiml.message(guidance)
        return {
            "status": "unsupported_media_guided",
            "message_sid": message_sid,
            "reply_text": guidance,
            "twiml": str(twiml),
        }

    def _handle_empty_message(
        self,
        from_number: str,
        preferred_lang: str,
        message_sid: str,
    ) -> Dict[str, Any]:
        """Handle empty or unparseable payload."""
        guidance = UNSUPPORTED_MEDIA_MESSAGES.get(preferred_lang, UNSUPPORTED_MEDIA_MESSAGES["te-IN"])
        twiml = MessagingResponse()
        twiml.message(guidance)
        return {
            "status": "empty_message_handled",
            "message_sid": message_sid,
            "reply_text": guidance,
            "twiml": str(twiml),
        }

    def _get_or_create_farmer(self, from_number: str) -> FarmerModel:
        """
        Retrieve existing farmer profile or initialize a new profile.
        Normalizes phone numbers to seamlessly unify Meta WhatsApp and Twilio WhatsApp profiles.
        """
        raw_sender = str(from_number).strip()
        clean_sender = raw_sender.replace("whatsapp:", "").strip()
        digits_sender = clean_sender.lstrip("+")

        # Check existing profile under any variation
        for candidate in (digits_sender, clean_sender, raw_sender):
            existing = self.farmer_service.get_farmer_by_whatsapp_id(candidate)
            if existing:
                return existing

        # Safely create lightweight profile
        now_iso = datetime.now(timezone.utc).isoformat()
        new_farmer = FarmerModel(
            farmer_id=str(uuid.uuid4()),
            whatsapp_user_id=digits_sender,
            preferred_language="te-IN",
            village_name="Pending Confirmation",
            mandal_name=None,
            district_name=None,
            pin_code="500001",
            latitude=None,
            longitude=None,
            location_source="twilio_whatsapp_onboarding",
            location_confirmed=False,
            consent_given=True,
            consent_given_at=now_iso,
            weather_provider_sharing_consent=False,
            created_at=now_iso,
            updated_at=now_iso,
        )

        try:
            return self.farmer_service.repository.create(new_farmer)
        except Exception as e:
            logger.warning("Farmer profile creation race condition for %s: %s", digits_sender, e)
            for candidate in (digits_sender, clean_sender, raw_sender):
                existing_after = self.farmer_service.get_farmer_by_whatsapp_id(candidate)
                if existing_after:
                    return existing_after
            raise
