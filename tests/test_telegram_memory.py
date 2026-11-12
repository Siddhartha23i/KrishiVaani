import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.core.config import settings
from app.llm.schemas import LLMResponseSchema
from app.telegram.memory import ConversationMemoryStore
from app.telegram.handlers import TelegramHandler


def _store(tmp: str) -> ConversationMemoryStore:
    return ConversationMemoryStore(Path(tmp) / "memory.db")


def test_users_are_isolated_and_raw_ids_are_not_stored():
    with TemporaryDirectory() as tmp:
        with patch.object(settings, "USER_ID_HASH_SALT", "test-salt"):
            store = _store(tmp)
            store.save_turn("user-a", "Telugu", "నా జిల్లా వరంగల్", "సరే .", "general", "PASSED")
            store.save_turn("user-b", "Telugu", "నా జిల్లా నిజామాబాద్", "సరే .", "general", "PASSED")
            a = store.load_context("user-a")
            b = store.load_context("user-b")
            assert a.district == "Warangal"
            assert b.district == "Nizamabad"
            raw = (Path(tmp) / "memory.db").read_bytes()
            assert b"user-a" not in raw
            assert b"user-b" not in raw


def test_followup_context_is_trimmed_and_refusals_are_not_replayed():
    with TemporaryDirectory() as tmp:
        with patch.object(settings, "USER_ID_HASH_SALT", "test-salt"):
            store = _store(tmp)
            store.save_turn("user-a", "Telugu", "మొదటి ప్రశ్న " + "x" * 800, "జవాబు " + "y" * 800, "crop", "PASSED")
            store.save_turn("user-a", "Telugu", "ఇది తిరస్కరణ", "సేఫ్ ఫాల్బ్యాక్", "crop", "ABSTAINED")
            context = store.load_context("user-a")
            assert context.conversation_memory.count("Farmer:") == 1
            assert len(context.conversation_memory) < 1000
            assert "minutes ago" in context.conversation_memory or "just now" in context.conversation_memory


def test_forget_deletes_turns_and_profile():
    with TemporaryDirectory() as tmp:
        with patch.object(settings, "USER_ID_HASH_SALT", "test-salt"):
            store = _store(tmp)
            store.save_turn("user-a", "Telugu", "నా జిల్లా వరంగల్", "సరే .", "general", "PASSED")
            store.forget("user-a")
            context = store.load_context("user-a")
            assert context.district is None
            assert context.conversation_memory is None


def test_missing_salt_fails_clearly():
    with TemporaryDirectory() as tmp:
        with patch.object(settings, "USER_ID_HASH_SALT", None):
            store = _store(tmp)
            try:
                store.load_context("user-a")
            except RuntimeError as error:
                assert "USER_ID_HASH_SALT" in str(error)
            else:
                raise AssertionError("Expected missing salt to fail clearly")


def test_save_failure_is_async_and_does_not_change_reply_path():
    class BrokenStore:
        def save_turn(self, *args):
            raise OSError("database unavailable")

    async def run():
        handler = TelegramHandler(
            orchestrator=MagicMock(memory_store=None),
            voice_service=MagicMock(orchestrator=None),
            session_repo=MagicMock(db_path=None),
            memory_store=BrokenStore(),
        )
        handler._save_turn_background(
            "user", "Telugu", "question",
            SimpleNamespace(safety_status="PASSED", response_text="answer", intent="general"),
        )
        await asyncio.sleep(0.01)

    asyncio.run(run())
