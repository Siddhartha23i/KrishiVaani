"""
FastAPI Routes for Meta WhatsApp Cloud API Webhooks — Phase 8.1.

Implements:
1. GET /webhook: Verification challenge handshake for Meta webhook configuration.
2. POST /webhook: Authenticated incoming message handler with HMAC-SHA256 signature
   verification, idempotency checks, and asynchronous background processing.
"""

import json
import logging
from typing import Optional, Dict, Any

from fastapi import APIRouter, Request, Response, BackgroundTasks, Query, Header, HTTPException, status

from app.core.config import settings
from app.whatsapp.security import verify_webhook_token, verify_webhook_signature
from app.whatsapp.service import WhatsAppService

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/webhook", summary="Meta Webhook Verification")
async def verify_webhook(
    hub_mode: Optional[str] = Query(None, alias="hub.mode"),
    hub_challenge: Optional[str] = Query(None, alias="hub.challenge"),
    hub_verify_token: Optional[str] = Query(None, alias="hub.verify_token"),
) -> Response:
    """
    Handle Meta's GET verification handshake.
    Returns hub.challenge as plain text upon valid verification token match.
    """
    configured_token = settings.whatsapp_webhook_verify_token

    if not configured_token:
        logger.error("WhatsApp webhook verify token is not configured in settings.")
        return Response(content="Webhook verify token not configured", status_code=status.HTTP_503_SERVICE_UNAVAILABLE)

    if verify_webhook_token(hub_mode, hub_verify_token, configured_token):
        logger.info("WhatsApp webhook verified successfully with Meta.")
        # Meta strictly requires hub.challenge as plain text
        return Response(content=hub_challenge or "", media_type="text/plain", status_code=status.HTTP_200_OK)

    logger.warning("WhatsApp webhook verification failed: invalid token or mode.")
    return Response(content="Forbidden", status_code=status.HTTP_403_FORBIDDEN)


@router.post("/webhook", summary="Receive WhatsApp Webhook Events")
async def receive_webhook_event(
    request: Request,
    background_tasks: BackgroundTasks,
    x_hub_signature_256: Optional[str] = Header(None, alias="X-Hub-Signature-256"),
) -> Response:
    """
    Process incoming WhatsApp webhook payloads from Meta.
    1. Validates HMAC-SHA256 signature using App Secret.
    2. Parses incoming messages.
    3. Ignores outgoing delivery/read statuses.
    4. Dispatches processing to background tasks.
    5. Returns HTTP 200 quickly to satisfy Meta timeout requirements.
    """
    raw_bytes = await request.body()
    app_secret = settings.whatsapp_app_secret

    # Validate signature if app_secret is configured
    if app_secret:
        if not verify_webhook_signature(raw_bytes, x_hub_signature_256, app_secret):
            logger.warning("Rejected webhook request: invalid HMAC signature.")
            return Response(content="Invalid signature", status_code=status.HTTP_403_FORBIDDEN)
    else:
        logger.warning("WHATSAPP_APP_SECRET is not configured; running in unverified development mode.")

    # Parse JSON payload
    try:
        payload = json.loads(raw_bytes.decode("utf-8"))
    except Exception as parse_err:
        logger.error("Failed to parse incoming webhook JSON: %s", parse_err)
        return Response(content="Malformed JSON", status_code=status.HTTP_400_BAD_REQUEST)

    # Process entries
    entries = payload.get("entry", [])
    service = WhatsAppService()

    dispatched_count = 0
    for entry in entries:
        changes = entry.get("changes", [])
        for change in changes:
            value = change.get("value", {})

            # Ignore delivery status updates (sent, delivered, read)
            if "statuses" in value and not value.get("messages"):
                logger.debug("Ignored WhatsApp delivery status notification.")
                continue

            messages = value.get("messages", [])
            for msg in messages:
                # Add to background tasks for asynchronous handling
                background_tasks.add_task(service.process_incoming_message, msg)
                dispatched_count += 1

    return Response(
        content=json.dumps({"status": "received", "dispatched": dispatched_count}),
        media_type="application/json",
        status_code=status.HTTP_200_OK,
    )

