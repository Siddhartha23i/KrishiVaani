"""
Pydantic Schemas for Twilio WhatsApp Webhooks and Messages — Phase 8.2.
"""

from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field, ConfigDict


class TwilioWebhookPayload(BaseModel):
    """
    Validated incoming webhook form data received from Twilio.
    """
    model_config = ConfigDict(extra="ignore")

    MessageSid: str = Field(description="Twilio unique message SID")
    AccountSid: Optional[str] = Field(default=None, description="Twilio Account SID")
    From: str = Field(description="Sender WhatsApp number, e.g. whatsapp:+919876543210")
    To: str = Field(description="Recipient WhatsApp sandbox number, e.g. whatsapp:+14155238886")
    Body: Optional[str] = Field(default=None, description="Text message content if present")
    NumMedia: int = Field(default=0, description="Number of attached media files")
    MediaUrl0: Optional[str] = Field(default=None, description="URL of primary attached media file")
    MediaContentType0: Optional[str] = Field(default=None, description="MIME content type of primary media")
    ProfileName: Optional[str] = Field(default=None, description="Sender's WhatsApp profile name if available")
    SmsStatus: Optional[str] = Field(default=None, description="Message status from Twilio")
    WaId: Optional[str] = Field(default=None, description="Raw WhatsApp ID digits if provided")


class TwilioMessageResult(BaseModel):
    """
    Outcome of inbound webhook processing.
    """
    status: str = Field(description="Execution status: success, duplicate_ignored, error, etc.")
    message_sid: Optional[str] = Field(default=None, description="Message SID processed")
    message_type: Optional[str] = Field(default=None, description="Type: text, audio, unsupported_media")
    voice_sent: Optional[bool] = Field(default=None, description="Whether an audio voice note was dispatched")
    transcript: Optional[str] = Field(default=None, description="Recognized speech transcript if voice note")
    intent: Optional[str] = Field(default=None, description="Classified conversation intent")
    error: Optional[str] = Field(default=None, description="Error detail if failed")

