"""
Pydantic Schemas for Meta WhatsApp Cloud API — Phase 8.1.
"""

from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, ConfigDict


class WhatsAppAudio(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    mime_type: Optional[str] = None


class WhatsAppText(BaseModel):
    model_config = ConfigDict(extra="ignore")
    body: str


class WhatsAppLocation(BaseModel):
    model_config = ConfigDict(extra="ignore")
    latitude: float
    longitude: float
    name: Optional[str] = None
    address: Optional[str] = None


class WhatsAppMessage(BaseModel):
    model_config = ConfigDict(extra="ignore")
    from_: str = Field(alias="from")
    id: str
    timestamp: str
    type: str
    audio: Optional[WhatsAppAudio] = None
    text: Optional[WhatsAppText] = None
    location: Optional[WhatsAppLocation] = None


class WhatsAppContact(BaseModel):
    model_config = ConfigDict(extra="ignore")
    profile: Optional[Dict[str, str]] = None
    wa_id: str


class WhatsAppValue(BaseModel):
    model_config = ConfigDict(extra="ignore")
    messaging_product: Optional[str] = "whatsapp"
    metadata: Optional[Dict[str, Any]] = None
    contacts: Optional[List[WhatsAppContact]] = None
    messages: Optional[List[WhatsAppMessage]] = None
    statuses: Optional[List[Dict[str, Any]]] = None


class WhatsAppChange(BaseModel):
    model_config = ConfigDict(extra="ignore")
    value: WhatsAppValue
    field: Optional[str] = "messages"


class WhatsAppEntry(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: Optional[str] = None
    changes: List[WhatsAppChange] = Field(default_factory=list)


class WhatsAppWebhookPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")
    object: Optional[str] = None
    entry: List[WhatsAppEntry] = Field(default_factory=list)


class WhatsAppMediaInfo(BaseModel):
    """Metadata returned by Meta Graph API GET /{media_id}."""
    model_config = ConfigDict(extra="ignore")
    id: str
    url: str
    mime_type: str
    sha256: Optional[str] = None
    file_size: Optional[int] = None
    messaging_product: Optional[str] = "whatsapp"


class WhatsAppSendResult(BaseModel):
    """Outcome of sending a WhatsApp message."""
    model_config = ConfigDict(extra="ignore")
    success: bool
    recipient_id: str
    message_id: Optional[str] = None
    message_type: str = "text"
    error_detail: Optional[str] = None

