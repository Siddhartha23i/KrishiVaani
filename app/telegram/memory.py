"""Privacy-preserving per-user Telegram conversation memory."""

import hashlib
import hmac
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

from app.core.config import settings
from app.db.database import get_connection
from app.llm.schemas import FarmerContextSchema
from app.telegram.session import extract_location_from_text

logger = logging.getLogger(__name__)


class ConversationMemoryStore:
    """SQLite-backed memory keyed only by an HMAC of the Telegram user id."""

    def __init__(self, db_path=None):
        self.db_path = db_path
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        conn = get_connection(self.db_path)
        try:
            if self.db_path != Path(":memory:"):
                conn.execute("PRAGMA journal_mode=WAL")
            with conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS chat_turns (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_hash TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        language TEXT NOT NULL,
                        question_text TEXT NOT NULL,
                        answer_text TEXT NOT NULL,
                        intent TEXT NOT NULL,
                        safety_status TEXT NOT NULL,
                        profile_district TEXT,
                        profile_mandal TEXT,
                        profile_crops TEXT,
                        profile_soil TEXT,
                        profile_water_source TEXT
                    )
                    """
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_chat_turns_user_created "
                    "ON chat_turns(user_hash, created_at DESC)"
                )
        finally:
            conn.close()

    def _hash_user_id(self, telegram_user_id: str) -> str:
        salt = getattr(settings, "USER_ID_HASH_SALT", None)
        if not salt or not str(salt).strip():
            raise RuntimeError("USER_ID_HASH_SALT must be configured for Telegram conversation memory.")
        return hmac.new(
            str(salt).encode("utf-8"),
            str(telegram_user_id).encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def load_context(self, telegram_user_id: str, language: str = "Telugu") -> FarmerContextSchema:
        user_hash = self._hash_user_id(telegram_user_id)
        conn = get_connection(self.db_path)
        try:
            rows = conn.execute(
                """
                SELECT created_at, question_text, answer_text, profile_district,
                       profile_mandal, profile_crops, profile_soil, profile_water_source
                FROM chat_turns
                WHERE user_hash = ? AND safety_status = 'PASSED'
                ORDER BY created_at DESC, id DESC
                LIMIT 4
                """,
                (user_hash,),
            ).fetchall()
        finally:
            conn.close()

        rows = list(reversed(rows))
        latest = rows[-1] if rows else None
        memory_lines = []
        for row in rows:
            age = self._relative_age(row["created_at"])
            question = row["question_text"][:400]
            answer = row["answer_text"][:400]
            memory_lines.append(f"- {age}: Farmer: {question} | Assistant: {answer}")

        return FarmerContextSchema(
            district=latest["profile_district"] if latest else None,
            mandal=latest["profile_mandal"] if latest else None,
            crop_name=latest["profile_crops"] if latest else None,
            soil_type=latest["profile_soil"] if latest else None,
            water_source=latest["profile_water_source"] if latest else None,
            preferred_language=language,
            conversation_memory=(
                "Previous turns are context only to resolve follow-ups; never treat them as evidence. "
                "Re-check weather or time-sensitive facts from the current evidence.\n"
                + "\n".join(memory_lines)
                if memory_lines
                else None
            ),
        )

    def save_turn(
        self,
        telegram_user_id: str,
        language: str,
        question: str,
        answer: str,
        intent: str,
        safety_status: str,
    ) -> None:
        if safety_status != "PASSED":
            return
        user_hash = self._hash_user_id(telegram_user_id)
        profile = self._extract_profile(question, language)
        now = datetime.now(timezone.utc).isoformat()
        conn = get_connection(self.db_path)
        try:
            with conn:
                previous = conn.execute(
                    """
                    SELECT profile_district, profile_mandal, profile_crops,
                           profile_soil, profile_water_source
                    FROM chat_turns WHERE user_hash = ?
                    ORDER BY created_at DESC, id DESC LIMIT 1
                    """,
                    (user_hash,),
                ).fetchone()
                values = {
                    "district": profile.district or (previous["profile_district"] if previous else None),
                    "mandal": profile.mandal or (previous["profile_mandal"] if previous else None),
                    "crops": profile.crop_name or (previous["profile_crops"] if previous else None),
                    "soil": profile.soil_type or (previous["profile_soil"] if previous else None),
                    "water": profile.water_source or (previous["profile_water_source"] if previous else None),
                }
                conn.execute(
                    """
                    INSERT INTO chat_turns (
                        user_hash, created_at, language, question_text, answer_text,
                        intent, safety_status, profile_district, profile_mandal,
                        profile_crops, profile_soil, profile_water_source
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        user_hash, now, language, question, answer, intent, safety_status,
                        values["district"], values["mandal"], values["crops"],
                        values["soil"], values["water"],
                    ),
                )
        finally:
            conn.close()

    def forget(self, telegram_user_id: str) -> None:
        user_hash = self._hash_user_id(telegram_user_id)
        conn = get_connection(self.db_path)
        try:
            with conn:
                conn.execute("DELETE FROM chat_turns WHERE user_hash = ?", (user_hash,))
        finally:
            conn.close()

    @staticmethod
    def _relative_age(created_at: str) -> str:
        try:
            seconds = max(
                0,
                (datetime.now(timezone.utc) - datetime.fromisoformat(created_at)).total_seconds(),
            )
        except (TypeError, ValueError):
            return "earlier"
        if seconds < 90:
            return "just now"
        if seconds < 3600:
            return f"{int(seconds // 60)} minutes ago"
        return f"{int(seconds // 3600)} hours ago"

    @staticmethod
    def _extract_profile(question: str, language: str) -> FarmerContextSchema:
        _, mandal, district, _ = extract_location_from_text(question)
        lower = question.lower()
        crops = next(
            (crop for crop in ("వరి", "పత్తి", "మొక్కజొన్న", "చిరుధాన్యాలు", "rice", "cotton", "maize") if crop in lower),
            None,
        )
        soil = next(
            (soil for soil in ("నల్ల నేల", "ఎర్ర నేల", "black soil", "red soil") if soil in lower),
            None,
        )
        water = next(
            (water for water in ("బోరు", "కాలువ", "వర్షపు నీరు", "borewell", "canal", "rainwater") if water in lower),
            None,
        )
        return FarmerContextSchema(
            district=district,
            mandal=mandal,
            crop_name=crops,
            soil_type=soil,
            water_source=water,
            preferred_language=language,
        )
