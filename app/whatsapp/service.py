"""
WhatsApp Service Orchestrator for KrishiVaani — Phase 8.1.

Processes inbound WhatsApp messages from Meta Cloud API webhooks:
1. Voice notes (Audio) -> Download -> Validate (<=30s) -> VoicePipelineService -> Timbre WAV -> OGG Opus -> Send Voice Note.
2. Text messages -> ConversationOrchestrator -> Send Text Message.
3. Location pins -> Save coordinates as unconfirmed location -> Request district confirmation.
4. Unsupported media -> Send helpful capability guidance.
5. Strict idempotency enforcement via SQLite wamid tracking.
6. Graceful fallbacks: if TTS, media upload, or sending fails, reply with safety-validated text.
"""

import uuid
import base64
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any

from app.core.config import settings
from app.services.farmer_service import FarmerService
from app.models.farmer import FarmerModel
from app.conversation.service import ConversationOrchestrator
from app.conversation.schemas import ConversationRequest, LocationInput
from app.voice.service import VoicePipelineService
from app.voice.schemas import VoiceProcessingRequest
from app.voice.validator import validate_audio_file, MAX_AUDIO_DURATION_SECONDS
from app.whatsapp.exceptions import (
    WhatsAppError,
    WhatsAppConfigurationError,
    WhatsAppMediaDownloadError,
    WhatsAppMediaUploadError,
    WhatsAppMessageSendError,
    DuplicateMessageError,
)
from app.whatsapp.client import WhatsAppCloudAPIClient
from app.whatsapp.event_repository import WhatsAppEventRepository
from app.whatsapp.audio_converter import convert_wav_bytes_to_ogg_opus
from app.whatsapp.security import mask_phone_number

logger = logging.getLogger(__name__)

# Standard localized prompt templates
LOCATION_ACK_MESSAGES = {
    "te-IN": "మీ లొకేషన్ వివరాలు అందాయి. ఖచ్చితమైన వాతావరణ మరియు వ్యవసాయ సలహాల కోసం మీ జిల్లా పేరును నిర్ధారించండి (ఉదాహరణకు: వరంగల్). గమనిక: లైవ్ జీపీఎస్ లొకేషన్ మీ పొలం లొకేషన్ కాకపోవచ్చు.",
    "hi-IN": "आपकी लोकेशन प्राप्त हुई। सटीक मौसम और कृषि सलाह के लिए कृपया अपने जिले के नाम की पुष्टि करें (उदाहरण: वारंगल)।",
    "en-IN": "Your location has been received. For accurate weather and agricultural advisories, please confirm your district name (e.g. Warangal). Note: Shared GPS pin is not automatically assumed to be your farm location.",
}

UNSUPPORTED_MEDIA_MESSAGES = {
    "te-IN": "నమస్కారం! కృషివాణి ప్రస్తుతం వాయిస్ సందేశాలు (వాయిస్ నోట్స్), టెక్స్ట్ సందేశాలు మరియు లొకేషన్ పిన్‌లను మాత్రమే స్వీకరిస్తుంది. దయచేసి మీ వ్యవసాయ సందేహాన్ని వాయిస్ లేదా టెక్స్ట్ ద్వారా పంపండి.",
    "hi-IN": "नमस्ते! कृषवाणी वर्तमान में केवल वॉयस संदेश (वॉयस नोट्स), टेक्स्ट संदेश और लोकेशन पिन स्वीकार करती है। कृपया अपना कृषि प्रश्न वॉयस या टेक्स्ट के रूप में भेजें।",
    "en-IN": "Hello! KrishiVaani currently accepts voice notes, text messages, and location pins. Please send your agricultural question as a voice or text message.",
}


class WhatsAppService:
    """
    Central service for processing inbound WhatsApp messages and dispatching replies.
    """

    def __init__(
        self,
        client: Optional[WhatsAppCloudAPIClient] = None,
        event_repo: Optional[WhatsAppEventRepository] = None,
        farmer_service: Optional[FarmerService] = None,
        voice_service: Optional[VoicePipelineService] = None,
        orchestrator: Optional[ConversationOrchestrator] = None,
        db_path: Optional[Path] = None,
    ):
        self.db_path = db_path or settings.DATABASE_PATH
        self.client = client or WhatsAppCloudAPIClient()
        self.event_repo = event_repo or WhatsAppEventRepository(db_path=self.db_path)
        self.farmer_service = farmer_service or FarmerService(db_path=self.db_path)
        self.voice_service = voice_service or VoicePipelineService()
        self.orchestrator = orchestrator or ConversationOrchestrator(
            farmer_service=self.farmer_service, db_path=self.db_path
        )

    def process_incoming_message(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process a single incoming WhatsApp message dictionary extracted from webhook payload.
        Guarantees idempotency via wamid.
        """
        wamid = message.get("id")
        sender_id = message.get("from")
        msg_type = message.get("type", "unknown")

        if not wamid or not sender_id:
            logger.warning("Malformed WhatsApp message: missing wamid or sender_id.")
            return {"status": "ignored", "reason": "malformed_message"}

        masked_sender = mask_phone_number(sender_id)

        # 1. Idempotency Check
        media_id = None
        if msg_type == "audio" and message.get("audio"):
            media_id = message["audio"].get("id")

        is_new = self.event_repo.record_event(
            wamid=wamid,
            sender_id=sender_id,
            message_type=msg_type,
            media_id=media_id,
        )
        if not is_new:
            logger.info("Ignoring duplicate webhook delivery for wamid=%s sender=%s", wamid, masked_sender)
            return {"status": "duplicate_ignored", "wamid": wamid}

        # Mark as processing
        self.event_repo.update_status(wamid=wamid, status="PROCESSING")

        try:
            # 2. Resolve Farmer Profile
            farmer = self._get_or_create_farmer(sender_id)
            preferred_lang = farmer.preferred_language or "te-IN"

            # 3. Dispatch to message-type handler
            if msg_type == "audio":
                result = self._handle_audio_message(message, farmer, wamid)
            elif msg_type == "text":
                result = self._handle_text_message(message, farmer, wamid)
            elif msg_type == "location":
                result = self._handle_location_message(message, farmer, wamid)
            else:
                result = self._handle_unsupported_media(sender_id, preferred_lang, wamid)

            # Mark as completed
            summary = f"type={msg_type};status={result.get('status', 'success')}"
            self.event_repo.update_status(wamid=wamid, status="COMPLETED", response_summary=summary)
            return result

        except Exception as e:
            logger.error("Error processing WhatsApp message wamid=%s from %s: %s", wamid, masked_sender, str(e), exc_info=True)
            self.event_repo.update_status(wamid=wamid, status="FAILED", error_message=str(e))
            return {"status": "error", "wamid": wamid, "error": str(e)}

    def _handle_audio_message(
        self,
        message: Dict[str, Any],
        farmer: FarmerModel,
        wamid: str,
    ) -> Dict[str, Any]:
        """
        Handle incoming voice note from farmer.
        Downloads media -> validates <= 30s -> VoicePipeline -> Timbre WAV -> OGG Opus -> WhatsApp.
        """
        audio_info = message.get("audio", {})
        media_id = audio_info.get("id")
        sender_id = message["from"]
        masked_sender = mask_phone_number(sender_id)

        if not media_id:
            raise WhatsAppError("Audio message missing media ID.")

        logger.info("Processing voice note media_id=%s from %s", media_id, masked_sender)

        # Step 1: Retrieve Meta Media URL
        media_metadata = self.client.get_media_info(media_id)

        # Step 2: Download Media Bytes
        audio_bytes = self.client.download_media_bytes(media_metadata.url)

        # Step 3: Run through Voice Pipeline Service
        # Derive extension from mime_type or default to .ogg / .m4a
        ext = ".ogg" if "ogg" in media_metadata.mime_type else ".m4a"
        filename = f"whatsapp_voice_{media_id}{ext}"

        voice_req = VoiceProcessingRequest(
            farmer_id=farmer.farmer_id,
            language=farmer.preferred_language or "te-IN",
        )

        voice_res = self.voice_service.process_audio_bytes(
            audio_bytes=audio_bytes,
            filename=filename,
            request=voice_req,
        )

        response_text = voice_res.response_text

        # Step 4: Safety Check: If REJECTED, NEVER synthesize or send speech
        if voice_res.safety_status == "REJECTED":
            logger.warning("Safety REJECTED voice response for %s. Sending safe text fallback only.", masked_sender)
            self.client.send_text_message(sender_id, response_text)
            return {"status": "safety_rejected_text_sent", "wamid": wamid}

        # Step 5: Convert WAV to OGG Opus and Send Voice Note
        sent_voice = False
        if voice_res.audio_base64 and not voice_res.is_fallback_text_only:
            try:
                wav_bytes = base64.b64decode(voice_res.audio_base64)
                ogg_bytes, duration = convert_wav_bytes_to_ogg_opus(wav_bytes)

                # Upload to Meta
                uploaded_media_id = self.client.upload_media_bytes(
                    file_bytes=ogg_bytes,
                    mime_type="audio/ogg; codecs=opus",
                    filename="krishivaani_reply.ogg",
                )

                # Send WhatsApp voice message
                self.client.send_voice_note(sender_id, uploaded_media_id)
                sent_voice = True
                logger.info("Sent WhatsApp voice note to %s (media_id=%s)", masked_sender, uploaded_media_id)

            except Exception as voice_send_err:
                logger.warning(
                    "Voice note dispatch failed for %s (%s). Falling back gracefully to text response.",
                    masked_sender,
                    str(voice_send_err),
                )
                sent_voice = False

        # Step 6: Graceful fallback to text if voice note was not sent
        if not sent_voice:
            logger.info("Sending text response to %s as fallback/text-only mode.", masked_sender)
            self.client.send_text_message(sender_id, response_text)

        return {
            "status": "success",
            "wamid": wamid,
            "voice_sent": sent_voice,
            "transcript": voice_res.transcript,
            "intent": voice_res.intent,
        }

    def _handle_text_message(
        self,
        message: Dict[str, Any],
        farmer: FarmerModel,
        wamid: str,
    ) -> Dict[str, Any]:
        """
        Handle incoming text message from farmer.
        Passes query to ConversationOrchestrator and replies with text.
        """
        sender_id = message["from"]
        text_info = message.get("text", {})
        body = (text_info.get("body") or "").strip()

        if not body:
            return {"status": "ignored", "reason": "empty_text_body"}

        conv_req = ConversationRequest(
            question=body,
            language=farmer.preferred_language or "te-IN",
            farmer_id=farmer.farmer_id,
        )

        conv_res = self.orchestrator.process_message(conv_req)
        self.client.send_text_message(sender_id, conv_res.response_text)

        return {
            "status": "success",
            "wamid": wamid,
            "intent": conv_res.intent,
            "is_abstention": conv_res.is_abstention,
        }

    def _handle_location_message(
        self,
        message: Dict[str, Any],
        farmer: FarmerModel,
        wamid: str,
    ) -> Dict[str, Any]:
        """
        Handle incoming GPS location pin from farmer.
        Saves coordinates as farmer-shared location without overwriting confirmed district.
        """
        sender_id = message["from"]
        loc_info = message.get("location", {})
        lat = loc_info.get("latitude")
        lng = loc_info.get("longitude")

        # Save coordinates in database without marking location as confirmed
        # Rule: A home location must not be assumed to be farm location.
        # Rule: Never overwrite an existing confirmed district with unconfirmed GPS.
        now_iso = datetime.now(timezone.utc).isoformat()
        new_loc_confirmed = farmer.location_confirmed  # Preserve existing confirmation flag

        try:
            self.farmer_service.repository.update_location(
                farmer_id=farmer.farmer_id,
                village_name=farmer.village_name,
                mandal_name=farmer.mandal_name,
                district_name=farmer.district_name,
                pin_code=farmer.pin_code,
                latitude=lat,
                longitude=lng,
                location_source="whatsapp_gps",
                location_confirmed=new_loc_confirmed,
                updated_at=now_iso,
            )
            logger.info("Saved GPS location (lat=%s, lng=%s) for farmer %s", lat, lng, farmer.farmer_id)
        except Exception as loc_err:
            logger.error("Failed to update farmer location coordinates: %s", loc_err)

        # Ask farmer to confirm district name in their preferred language
        lang = farmer.preferred_language or "te-IN"
        ack_text = LOCATION_ACK_MESSAGES.get(lang, LOCATION_ACK_MESSAGES["te-IN"])
        self.client.send_text_message(sender_id, ack_text)

        return {"status": "location_saved_confirmation_requested", "wamid": wamid}

    def _handle_unsupported_media(
        self,
        sender_id: str,
        language: str,
        wamid: str,
    ) -> Dict[str, Any]:
        """
        Handle unsupported incoming media (images, videos, documents, stickers).
        Replies with a polite capabilities notice.
        """
        guidance = UNSUPPORTED_MEDIA_MESSAGES.get(language, UNSUPPORTED_MEDIA_MESSAGES["te-IN"])
        self.client.send_text_message(sender_id, guidance)
        return {"status": "unsupported_media_guided", "wamid": wamid}

    def _get_or_create_farmer(self, whatsapp_user_id: str) -> FarmerModel:
        """
        Retrieve existing farmer profile or safely initialize a new one for this WhatsApp sender.
        """
        existing = self.farmer_service.get_farmer_by_whatsapp_id(whatsapp_user_id)
        if existing:
            return existing

        # Safely create lightweight onboarding record
        now_iso = datetime.now(timezone.utc).isoformat()
        new_farmer = FarmerModel(
            farmer_id=str(uuid.uuid4()),
            whatsapp_user_id=whatsapp_user_id,
            preferred_language="te-IN",
            village_name="Pending Confirmation",
            mandal_name=None,
            district_name=None,
            pin_code="500001",
            latitude=None,
            longitude=None,
            location_source="whatsapp_onboarding",
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
            # Handle possible race condition if duplicate profile created simultaneously
            logger.warning("Farmer profile creation race condition for %s: %s", whatsapp_user_id, e)
            existing_after = self.farmer_service.get_farmer_by_whatsapp_id(whatsapp_user_id)
            if existing_after:
                return existing_after
            raise

