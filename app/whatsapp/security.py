"""
Security and Verification Utilities for WhatsApp Webhooks — Phase 8.1.

Implements:
1. Meta Webhook Verification (hub.mode, hub.verify_token).
2. X-Hub-Signature-256 HMAC-SHA256 signature verification.
3. Privacy-preserving phone number and token masking for application logs.
"""

import hmac
import hashlib
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def verify_webhook_token(
    mode: Optional[str],
    token: Optional[str],
    verify_token: Optional[str],
) -> bool:
    """
    Validate GET webhook verification query parameters from Meta.
    Must have mode == 'subscribe' and token matching the configured verify token.
    """
    if not mode or not token or not verify_token:
        return False
    return mode.strip() == "subscribe" and hmac.compare_digest(token.strip(), verify_token.strip())


def verify_webhook_signature(
    payload_bytes: bytes,
    signature_header: Optional[str],
    app_secret: Optional[str],
) -> bool:
    """
    Validate POST webhook payload against Meta's X-Hub-Signature-256 header.
    Header format: 'sha256=<hex_digest>'
    Uses HMAC-SHA256 with Meta App Secret.
    """
    if not signature_header or not app_secret:
        logger.warning("Webhook signature verification failed: missing header or app secret.")
        return False

    prefix = "sha256="
    if not signature_header.startswith(prefix):
        logger.warning("Webhook signature format invalid (expected 'sha256=' prefix).")
        return False

    expected_hash = signature_header[len(prefix) :].strip().lower()
    mac = hmac.new(
        key=app_secret.strip().encode("utf-8"),
        msg=payload_bytes,
        digestmod=hashlib.sha256,
    )
    computed_hash = mac.hexdigest().lower()

    is_valid = hmac.compare_digest(computed_hash, expected_hash)
    if not is_valid:
        logger.warning("Webhook HMAC signature mismatch.")
    return is_valid


def mask_phone_number(phone: Optional[str]) -> str:
    """
    Mask a phone number or WhatsApp ID for privacy-compliant logging.
    Example: '919876543210' -> '91*****210'
    """
    if not phone:
        return "[UNKNOWN]"
    clean = str(phone).strip()
    if len(clean) <= 5:
        return "***"
    return f"{clean[:2]}*****{clean[-3:]}"

