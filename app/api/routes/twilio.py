"""
FastAPI Routes for Twilio WhatsApp Webhooks and Media Serving — Phase 8.2.

Implements:
1. POST /whatsapp/webhook (full route: /api/v1/twilio/whatsapp/webhook):
   - Authenticated incoming form-encoded webhook handler with X-Twilio-Signature verification.
   - Public URL reconstruction via TWILIO_WEBHOOK_PUBLIC_BASE_URL (essential for ngrok/proxies).
   - Instant response with valid empty TwiML (<Response></Response>) with HTTP 200.
   - Asynchronous conversation execution via FastAPI BackgroundTasks.
2. GET /media/{token}.ogg (full route: /api/v1/twilio/media/{token}.ogg):
   - Serves expiring temporary mono OGG Opus voice notes with Content-Type: audio/ogg.
"""

import logging
from typing import Optional, Dict, Any

from fastapi import APIRouter, Request, Response, BackgroundTasks, Header, HTTPException, status

from app.core.config import settings
from app.twilio.security import verify_twilio_signature, build_webhook_url
from app.twilio.service import TwilioService
from app.twilio.media_manager import TwilioMediaManager

logger = logging.getLogger(__name__)

router = APIRouter()

# Global or dependency instances
_twilio_service: Optional[TwilioService] = None
_media_manager: Optional[TwilioMediaManager] = None


def get_twilio_service() -> TwilioService:
    """Dependency / accessor for TwilioService singleton."""
    global _twilio_service
    if _twilio_service is None:
        _twilio_service = TwilioService()
    return _twilio_service


def get_media_manager() -> TwilioMediaManager:
    """Dependency / accessor for TwilioMediaManager singleton."""
    global _media_manager
    if _media_manager is None:
        _media_manager = TwilioMediaManager()
    return _media_manager


@router.post("/whatsapp/webhook", summary="Receive Twilio WhatsApp Webhook Events")
async def receive_twilio_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_twilio_signature: Optional[str] = Header(None, alias="X-Twilio-Signature"),
) -> Response:
    """
    Handle incoming form-encoded webhook POST from Twilio WhatsApp Sandbox.
    1. Reconstructs callback URL using TWILIO_WEBHOOK_PUBLIC_BASE_URL.
    2. Validates X-Twilio-Signature using Twilio RequestValidator.
    3. Synchronously processes conversation through ConversationOrchestrator or VoicePipeline.
    4. Returns TwiML MessagingResponse containing free-form text or voice media URL with HTTP 200.
    """
    # 1. Parse form-encoded parameters
    try:
        form = await request.form()
        form_data = dict(form)
    except Exception as form_err:
        logger.error("Failed to parse form-encoded data from Twilio webhook: %s", form_err)
        return Response(content="Malformed form data", status_code=status.HTTP_400_BAD_REQUEST)

    # 2. Signature verification
    auth_token = settings.twilio_auth_token
    public_base = settings.twilio_webhook_public_base_url
    expected_url = build_webhook_url(
        request_url=str(request.url),
        public_base_url=public_base,
        webhook_path="/api/v1/twilio/whatsapp/webhook",
    )

    if auth_token:
        is_valid = verify_twilio_signature(
            url=expected_url,
            params=form_data,
            signature=x_twilio_signature,
            auth_token=auth_token,
        )
        if not is_valid:
            logger.warning(
                "Twilio webhook rejected: signature verification failed for URL: %s", expected_url
            )
            return Response(content="Invalid Twilio signature", status_code=status.HTTP_403_FORBIDDEN)
    else:
        logger.warning(
            "TWILIO_AUTH_TOKEN is not configured; running in unverified development mode."
        )

    # 3. Synchronous conversation execution returning TwiML MessagingResponse
    service = get_twilio_service()
    result = service.process_incoming_webhook(form_data)
    twiml_content = result.get("twiml") or '<?xml version="1.0" encoding="UTF-8"?>\n<Response></Response>'

    return Response(
        content=twiml_content,
        media_type="application/xml",
        status_code=status.HTTP_200_OK,
    )


@router.get("/media/{token}.ogg", summary="Serve Expiring Audio Voice Note to Twilio")
async def serve_twilio_audio_media(token: str) -> Response:
    """
    Expose temporary mono OGG Opus audio file for Twilio to download when dispatching voice notes.
    Returns HTTP 200 with Content-Type: audio/ogg.
    Returns HTTP 404 if token is expired, invalid, or deleted.
    """
    media_mgr = get_media_manager()
    audio_bytes = media_mgr.get_media(token)

    if audio_bytes is None:
        logger.warning("Twilio requested non-existent or expired media token: %s", token)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Media not found or expired",
        )

    return Response(
        content=audio_bytes,
        media_type="audio/ogg",
        headers={
            "Content-Disposition": f'inline; filename="reply_{token[:8]}.ogg"',
            "Cache-Control": "public, max-age=1800",
        },
        status_code=status.HTTP_200_OK,
    )

