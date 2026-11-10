"""
WhatsApp Webhook Event Repository — Phase 8.1.

Tracks event lifecycle and guarantees message-level idempotency via SQLite.
Statuses: RECEIVED -> PROCESSING -> COMPLETED (or FAILED).
Privacy Guarantee: Raw audio recordings are NEVER persisted in this table.
"""

import sqlite3
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any

from app.core.config import settings
from app.db.database import get_connection

logger = logging.getLogger(__name__)


class WhatsAppEventRepository:
    """
    SQLite repository for WhatsApp webhook idempotency tracking and audit trail.
    """

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or settings.DATABASE_PATH

    def record_event(
        self,
        wamid: str,
        sender_id: str,
        message_type: str,
        media_id: Optional[str] = None,
    ) -> bool:
        """
        Record a new incoming WhatsApp message event.
        Returns:
            True if this is a newly recorded event.
            False if this wamid was already recorded (duplicate delivery).
        """
        if not wamid:
            return False

        now_iso = datetime.now(timezone.utc).isoformat()
        conn = get_connection(self.db_path)
        try:
            with conn:
                conn.execute(
                    """
                    INSERT INTO whatsapp_events (
                        wamid, sender_id, message_type, media_id, status,
                        received_at, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, 'RECEIVED', ?, ?, ?)
                    """,
                    (wamid, sender_id, message_type, media_id, now_iso, now_iso, now_iso),
                )
            return True
        except sqlite3.IntegrityError:
            # Duplicate wamid detected!
            logger.info("Duplicate WhatsApp webhook delivery detected: wamid=%s", wamid)
            return False
        finally:
            conn.close()

    def update_status(
        self,
        wamid: str,
        status: str,
        processed_at: Optional[str] = None,
        error_message: Optional[str] = None,
        response_summary: Optional[str] = None,
    ) -> None:
        """
        Update the processing status of an event.
        """
        now_iso = datetime.now(timezone.utc).isoformat()
        proc_time = processed_at or (now_iso if status in ("COMPLETED", "FAILED") else None)

        conn = get_connection(self.db_path)
        try:
            with conn:
                conn.execute(
                    """
                    UPDATE whatsapp_events
                    SET status = ?,
                        processed_at = COALESCE(?, processed_at),
                        error_message = ?,
                        response_summary = ?,
                        updated_at = ?
                    WHERE wamid = ?
                    """,
                    (status, proc_time, error_message, response_summary, now_iso, wamid),
                )
        finally:
            conn.close()

    def get_event(self, wamid: str) -> Optional[Dict[str, Any]]:
        """Fetch event record by wamid."""
        conn = get_connection(self.db_path)
        try:
            cur = conn.cursor()
            cur.execute("SELECT * FROM whatsapp_events WHERE wamid = ?", (wamid,))
            row = cur.fetchone()
            if not row:
                return None
            return dict(row)
        finally:
            conn.close()

    def is_already_handled(self, wamid: str) -> bool:
        """
        Check if the event is already completed or currently being processed.
        """
        event = self.get_event(wamid)
        if not event:
            return False
        return event["status"] in ("COMPLETED", "PROCESSING")

