"""
Twilio Webhook Event Repository — Phase 8.2.

Tracks the lifecycle of incoming Twilio events and guarantees MessageSid-level idempotency
via the SQLite twilio_events table.
Statuses: RECEIVED -> PROCESSING -> COMPLETED (or FAILED).

Privacy Guarantee: Raw audio recordings are NEVER persisted in this table or database.
"""

import sqlite3
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any, List

from app.core.config import settings
from app.db.database import get_connection

logger = logging.getLogger(__name__)


class TwilioEventRepository:
    """
    SQLite repository for Twilio webhook idempotency tracking and audit trail.
    """

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or settings.DATABASE_PATH

    def record_event(
        self,
        message_sid: str,
        account_sid: Optional[str],
        from_number: str,
        to_number: str,
        message_type: str,
        body: Optional[str] = None,
        media_url: Optional[str] = None,
        media_content_type: Optional[str] = None,
    ) -> bool:
        """
        Record a new incoming Twilio WhatsApp message event.
        Returns:
            True if newly recorded event.
            False if MessageSid already recorded (duplicate delivery).
        """
        if not message_sid:
            return False

        now_iso = datetime.now(timezone.utc).isoformat()
        conn = get_connection(self.db_path)
        try:
            with conn:
                conn.execute(
                    """
                    INSERT INTO twilio_events (
                        message_sid, account_sid, from_number, to_number, message_type,
                        body, media_url, media_content_type, status,
                        received_at, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'RECEIVED', ?, ?, ?)
                    """,
                    (
                        message_sid,
                        account_sid,
                        from_number,
                        to_number,
                        message_type,
                        body,
                        media_url,
                        media_content_type,
                        now_iso,
                        now_iso,
                        now_iso,
                    ),
                )
            return True
        except sqlite3.IntegrityError:
            logger.info("Duplicate Twilio webhook delivery detected: MessageSid=%s", message_sid)
            return False
        finally:
            conn.close()

    def update_status(
        self,
        message_sid: str,
        status: str,
        processed_at: Optional[str] = None,
        error_message: Optional[str] = None,
        response_summary: Optional[str] = None,
    ) -> None:
        """
        Update the processing status of a Twilio event.
        """
        now_iso = datetime.now(timezone.utc).isoformat()
        proc_time = processed_at or (now_iso if status in ("COMPLETED", "FAILED") else None)

        conn = get_connection(self.db_path)
        try:
            with conn:
                conn.execute(
                    """
                    UPDATE twilio_events
                    SET status = ?,
                        processed_at = COALESCE(?, processed_at),
                        error_message = ?,
                        response_summary = ?,
                        updated_at = ?
                    WHERE message_sid = ?
                    """,
                    (status, proc_time, error_message, response_summary, now_iso, message_sid),
                )
        finally:
            conn.close()

    def get_event(self, message_sid: str) -> Optional[Dict[str, Any]]:
        """Fetch event record by message_sid."""
        conn = get_connection(self.db_path)
        try:
            cur = conn.execute(
                "SELECT * FROM twilio_events WHERE message_sid = ?",
                (message_sid,),
            )
            row = cur.fetchone()
            if row:
                return dict(row)
            return None
        finally:
            conn.close()

    def list_events_by_sender(self, from_number: str, limit: int = 20) -> List[Dict[str, Any]]:
        """Fetch recent events for a given sender number."""
        conn = get_connection(self.db_path)
        try:
            cur = conn.execute(
                """
                SELECT * FROM twilio_events
                WHERE from_number = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (from_number, limit),
            )
            return [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()

