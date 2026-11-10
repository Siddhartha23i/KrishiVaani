"""
Temporary Media Manager for Twilio WhatsApp Voice Notes — Phase 8.2.

Twilio requires outbound WhatsApp audio to be hosted at an accessible HTTPS URL (MediaUrl),
unlike Meta WhatsApp Cloud API which accepts direct binary uploads.

This manager:
1. Stores converted mono OGG Opus audio files in a dedicated temporary storage directory.
2. Generates unpredictable, cryptographic tokens for media URLs (32-byte URL-safe tokens).
3. Enforces strict TTL expiration (default 30 minutes, ample time for Twilio to download).
4. Deletes expired audio files safely to protect disk resources and privacy.
5. Builds externally accessible URLs using TWILIO_WEBHOOK_PUBLIC_BASE_URL.
"""

import os
import json
import time
import secrets
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Dict, Any

from app.core.config import settings, BASE_DIR

logger = logging.getLogger(__name__)

DEFAULT_MEDIA_TTL_SECONDS = 1800  # 30 minutes


class TwilioMediaManager:
    """
    Manages short-lived audio files exposed for Twilio media fetching.
    """

    def __init__(self, storage_dir: Optional[Path] = None, default_ttl: int = DEFAULT_MEDIA_TTL_SECONDS):
        if storage_dir is not None:
            self.storage_dir = Path(storage_dir)
        elif hasattr(settings, "TWILIO_MEDIA_DIR") and settings.TWILIO_MEDIA_DIR:
            self.storage_dir = Path(settings.TWILIO_MEDIA_DIR)
        elif hasattr(settings, "BASE_DIR") and settings.BASE_DIR:
            self.storage_dir = Path(settings.BASE_DIR) / "data" / "twilio_media"
        else:
            self.storage_dir = BASE_DIR / "data" / "twilio_media"
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.default_ttl = default_ttl

    def store_media(self, ogg_bytes: bytes, ttl_seconds: Optional[int] = None) -> str:
        """
        Persist OGG Opus audio bytes and return an unguessable token.

        Parameters:
            ogg_bytes: Converted mono OGG Opus audio bytes.
            ttl_seconds: Lifespan in seconds before expiry (default: 30 minutes).

        Returns:
            URL-safe token string.
        """
        ttl = ttl_seconds if ttl_seconds is not None else self.default_ttl
        token = secrets.token_urlsafe(32)

        audio_path = self.storage_dir / f"{token}.ogg"
        meta_path = self.storage_dir / f"{token}.meta.json"

        # Write audio file
        audio_path.write_bytes(ogg_bytes)

        # Write metadata
        now = time.time()
        meta = {
            "token": token,
            "created_at": now,
            "expires_at": now + ttl,
            "size_bytes": len(ogg_bytes),
        }
        meta_path.write_text(json.dumps(meta), encoding="utf-8")

        logger.debug("Stored temporary Twilio media token=%s (%d bytes, ttl=%ds)", token, len(ogg_bytes), ttl)
        return token

    def get_media(self, token: str) -> Optional[bytes]:
        """
        Retrieve audio bytes by token if not expired.
        Automatically cleans up and returns None if expired or not found.
        """
        if not token or not token.isalnum() and not all(c in "-_" for c in token if not c.isalnum()):
            return None

        audio_path = self.storage_dir / f"{token}.ogg"
        meta_path = self.storage_dir / f"{token}.meta.json"

        if not audio_path.exists():
            return None

        # Check expiration if metadata exists
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                if time.time() > meta.get("expires_at", 0):
                    logger.info("Twilio media token=%s has expired. Deleting.", token)
                    self._delete_token_files(token)
                    return None
            except Exception as e:
                logger.warning("Error reading metadata for token %s: %s", token, e)

        try:
            return audio_path.read_bytes()
        except Exception as e:
            logger.error("Failed to read audio file for token %s: %s", token, e)
            return None

    def build_media_url(self, token: str, base_url: Optional[str] = None) -> str:
        """
        Construct the fully qualified public HTTPS URL for Twilio to retrieve the audio file.
        """
        public_base = (base_url or settings.twilio_webhook_public_base_url or "").strip().rstrip("/")
        path = f"/api/v1/twilio/media/{token}.ogg"
        if public_base:
            return f"{public_base}{path}"
        return path

    def cleanup_expired(self) -> int:
        """
        Scan the storage directory and delete expired audio files and orphaned metadata.
        Returns the number of expired media items purged.
        """
        purged = 0
        now = time.time()

        for meta_file in self.storage_dir.glob("*.meta.json"):
            try:
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
                token = meta.get("token")
                if token and now > meta.get("expires_at", 0):
                    self._delete_token_files(token)
                    purged += 1
            except Exception as e:
                logger.warning("Failed processing media cleanup for %s: %s", meta_file.name, e)

        if purged > 0:
            logger.info("Cleaned up %d expired Twilio media files.", purged)
        return purged

    def _delete_token_files(self, token: str) -> None:
        """Delete both .ogg and .meta.json for a token."""
        audio_path = self.storage_dir / f"{token}.ogg"
        meta_path = self.storage_dir / f"{token}.meta.json"

        for p in (audio_path, meta_path):
            if p.exists():
                try:
                    p.unlink()
                except Exception as e:
                    logger.warning("Failed to delete %s: %s", p, e)

