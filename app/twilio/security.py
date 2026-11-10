"""
Security and Signature Verification Utilities for Twilio WhatsApp Webhooks — Phase 8.2.

Implements:
1. Strict X-Twilio-Signature verification via the official Twilio Python SDK RequestValidator.
2. Callback URL reconstruction utilizing TWILIO_WEBHOOK_PUBLIC_BASE_URL (essential behind ngrok/reverse proxies).
3. Privacy-preserving phone number and token masking for logs.
"""

import logging
from typing import Optional, Dict, Any
from twilio.request_validator import RequestValidator

logger = logging.getLogger(__name__)


def build_webhook_url(
    request_url: str,
    public_base_url: Optional[str] = None,
    webhook_path: str = "/api/v1/twilio/whatsapp/webhook",
) -> str:
    """
    Reconstruct the exact externally visible HTTPS webhook URL as registered in the Twilio Console.
    When KrishiVaani runs behind a reverse proxy or ngrok tunnel, the internal host may be
    http://localhost:8000, whereas Twilio computed the HMAC signature against the public HTTPS URL.
    """
    if public_base_url and public_base_url.strip():
        base = public_base_url.strip().rstrip("/")
        path = webhook_path if webhook_path.startswith("/") else f"/{webhook_path}"
        # Preserve query string if any exists on the incoming request
        query_part = ""
        if "?" in str(request_url):
            query_part = "?" + str(request_url).split("?", 1)[1]
        return f"{base}{path}{query_part}"

    # Return request URL as-is if no public base is specified
    return str(request_url)


def verify_twilio_signature(
    url: str,
    params: Dict[str, Any],
    signature: Optional[str],
    auth_token: Optional[str],
) -> bool:
    """
    Verify incoming webhook authenticity using Twilio's HMAC-SHA1 RequestValidator.
    
    Parameters:
        url: The reconstructed public URL Twilio posted to.
        params: Form-encoded POST parameters sent by Twilio.
        signature: Value of the X-Twilio-Signature HTTP header.
        auth_token: Configured TWILIO_AUTH_TOKEN.
        
    Returns:
        True if the signature is valid; False otherwise.
    """
    if not signature or not signature.strip():
        logger.warning("Twilio signature validation failed: missing X-Twilio-Signature header.")
        return False

    if not auth_token or not auth_token.strip():
        logger.warning("Twilio signature validation failed: TWILIO_AUTH_TOKEN is not configured.")
        return False

    try:
        validator = RequestValidator(auth_token.strip())
        # Ensure all parameter values are strings as expected by RequestValidator
        str_params = {str(k): str(v) for k, v in params.items() if v is not None}
        is_valid = validator.validate(url, str_params, signature.strip())
        if not is_valid:
            logger.warning("Twilio signature mismatch for URL %s", url)
        return is_valid
    except Exception as e:
        logger.warning("Error during Twilio RequestValidator check: %s", str(e))
        return False


def mask_phone_number(phone: Optional[str]) -> str:
    """
    Mask a phone number or WhatsApp ID for privacy-compliant logging.
    Example: 'whatsapp:+919876543210' -> 'whatsapp:+91*****210'
    """
    if not phone:
        return "[UNKNOWN]"
    clean = str(phone).strip()
    prefix = ""
    if clean.startswith("whatsapp:"):
        prefix = "whatsapp:"
        clean = clean[len("whatsapp:") :]

    if len(clean) <= 5:
        return f"{prefix}***"
    return f"{prefix}{clean[:3]}*****{clean[-3:]}"

