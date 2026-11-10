"""
Twilio WhatsApp Sandbox Integration Package for KrishiVaani — Phase 8.2.

Provides:
- Webhook signature validation (Twilio RequestValidator)
- Form-encoded webhook parsing & message idempotency via MessageSid
- Secure authenticated media downloading with basic auth
- Audio conversion and temporary expiring media serving for Twilio voice notes
- Twilio REST API client for outbound messages
- Complete integration with existing VoicePipelineService & ConversationOrchestrator
"""

from app.twilio.client import TwilioClient
from app.twilio.service import TwilioService
from app.twilio.media_manager import TwilioMediaManager
from app.twilio.event_repository import TwilioEventRepository

__all__ = [
    "TwilioClient",
    "TwilioService",
    "TwilioMediaManager",
    "TwilioEventRepository",
]

