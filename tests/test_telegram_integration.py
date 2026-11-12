"""
Unit and Integration Tests for KrishiVaani Telegram Channel — Phase 8.3.

Verifies:
1. /start command: delivers localized Telugu welcome message and advisory disclaimer.
2. Text message handling:
   - Pure greeting ("hi", "నమస్కారం") returns immediate friendly greeting without triggering agricultural LLM.
   - Agricultural question invokes ConversationOrchestrator and returns localized advice.
3. Voice note handling:
   - Rejects voice notes > 30 seconds with polite Telugu notice.
   - Sends 'record_voice' chat action during processing.
   - Valid voice note invokes VoicePipelineService, converts reply to OGG Opus, and replies with reply_voice.
   - Safety REJECTED voice note suppresses audio output and delivers text guidance only.
4. Error resilience: unexpected exceptions trigger polite Telugu fallback without crashing handlers.
5. Idempotency: duplicate Telegram update_ids are safely ignored.
"""

import io
import base64
import tempfile
import sqlite3
from pathlib import Path
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from telegram import Update, Message, User, Chat, Voice
from telegram.constants import ChatAction

from app.core.config import settings
from app.conversation.schemas import ConversationResponse, ConversationRequest, LocationInput, GuestWeatherConsentEvent
from app.conversation.service import ConversationOrchestrator
from app.voice.schemas import VoiceProcessingResponse
from app.voice.service import VoicePipelineService
from app.telegram.session import (
    TelegramSessionRepository,
    TelegramUserSession,
    is_consent_grant,
    is_consent_reject,
    extract_location_from_text,
)
from app.telegram.handlers import (
    TelegramHandler,
    START_MESSAGE,
    START_MESSAGES,
    GREETING_MESSAGE,
    DURATION_LIMIT_MESSAGE,
    FALLBACK_ERROR_MESSAGE,
    is_greeting,
)


class TestTelegramGreetingHelper(unittest.TestCase):
    """Test fast greeting detection helper."""

    def test_greetings_detected(self):
        self.assertTrue(is_greeting("hi"))
        self.assertTrue(is_greeting("Hi"))
        self.assertTrue(is_greeting("HELLO"))
        self.assertTrue(is_greeting("నమస్కారం"))
        self.assertTrue(is_greeting("నమస్కారం!"))
        self.assertTrue(is_greeting("నమస్తే"))
        self.assertTrue(is_greeting("నమస్తే "))
        self.assertTrue(is_greeting("నమస్తే !"))
        self.assertTrue(is_greeting("హలో"))
        self.assertTrue(is_greeting("Namaste"))

    def test_agricultural_questions_not_greetings(self):
        self.assertFalse(is_greeting("వరిలో అగ్గితెగులు నివారణ ఏమిటి?"))
        self.assertFalse(is_greeting("వర్షం ఎప్పుడు పడుతుంది?"))
        self.assertFalse(is_greeting("pesticide for cotton bollworm"))
        self.assertFalse(is_greeting(""))
        self.assertFalse(is_greeting(None))


class TestTelegramHandler(unittest.IsolatedAsyncioTestCase):
    """Async unit tests for TelegramHandler using mocked Update and Context."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_db_path = Path(self.temp_dir.name) / "test_telegram.db"
        self.session_repo = TelegramSessionRepository(db_path=self.test_db_path)

        self.mock_orchestrator = MagicMock(spec=ConversationOrchestrator)
        self.mock_voice_service = MagicMock(spec=VoicePipelineService)
        self.handler = TelegramHandler(
            orchestrator=self.mock_orchestrator,
            voice_service=self.mock_voice_service,
            session_repo=self.session_repo,
        )

        # Build mock update and context
        self.mock_context = MagicMock()
        self.mock_context.bot = MagicMock()
        self.mock_context.bot.send_chat_action = AsyncMock()
        self.mock_context.bot.get_file = AsyncMock()

    def tearDown(self):
        self.temp_dir.cleanup()

    def _create_mock_update(self, update_id: int, text: str = None, voice: Voice = None) -> Update:
        update = MagicMock(spec=Update)
        update.update_id = update_id

        user = MagicMock(spec=User)
        user.id = 987654321
        user.first_name = "Farmer"
        update.effective_user = user

        chat = MagicMock(spec=Chat)
        chat.id = 123456789
        update.effective_chat = chat

        message = MagicMock(spec=Message)
        message.text = text
        message.voice = voice
        message.audio = None
        message.reply_text = AsyncMock()
        message.reply_voice = AsyncMock()
        update.effective_message = message

        return update

    # --- Test 1: /start Command ---
    async def test_start_command_returns_english_welcome_and_language_buttons(self):
        update = self._create_mock_update(update_id=101, text="/start")

        await self.handler.handle_start(update, self.mock_context)

        call = update.effective_message.reply_text.call_args
        self.assertEqual(call.args[0], START_MESSAGES["en-IN"])
        self.assertIn("reply_markup", call.kwargs)
        self.mock_orchestrator.process_message.assert_not_called()

    # --- Test 2: Text Greetings Bypass LLM ---
    async def test_text_greeting_returns_fast_non_empty_reply(self):
        update = self._create_mock_update(update_id=102, text="hi")

        await self.handler.handle_text(update, self.mock_context)

        update.effective_message.reply_text.assert_called_once()
        self.assertNotRegex(
            update.effective_message.reply_text.call_args.args[0],
            "\u0c05\u0c02\u0c21\u0c3f",
        )
        # Core requirement: greetings must not trigger the agricultural LLM path
        self.mock_orchestrator.process_message.assert_not_called()

    # --- Test 2b: Focused Four Greeting Variations Bypass LLM ---
    async def test_four_greeting_variations_trigger_greeting_and_bypass_llm(self):
        four_variations = ["నమస్కారం", "నమస్కారం!", "నమస్తే", "నమస్తే "]
        for idx, greeting_text in enumerate(four_variations, start=200):
            with self.subTest(greeting=greeting_text):
                update = self._create_mock_update(update_id=idx, text=greeting_text)
                await self.handler.handle_text(update, self.mock_context)
                update.effective_message.reply_text.assert_called_once()
                self.assertNotRegex(
                    update.effective_message.reply_text.call_args.args[0],
                    "\u0c05\u0c02\u0c21\u0c3f",
                )
                self.mock_orchestrator.process_message.assert_not_called()
                self.mock_orchestrator.reset_mock()

    # --- Test 3: Agricultural Text Message Routes to Orchestrator ---
    async def test_text_agricultural_question_success(self):
        update = self._create_mock_update(update_id=103, text="వరిలో తెగులు నివారణ")

        mock_conv_res = MagicMock(spec=ConversationResponse)
        mock_conv_res.response_text = "వరిలో అగ్గితెగులు నివారణకు ట్రైసైక్లాజోల్ పిచికారీ చేయండి."
        self.mock_orchestrator.process_message.return_value = mock_conv_res

        await self.handler.handle_text(update, self.mock_context)

        self.mock_orchestrator.process_message.assert_called_once()
        update.effective_message.reply_text.assert_called_once_with(
            "వరిలో అగ్గితెగులు నివారణకు ట్రైసైక్లాజోల్ పిచికారీ చేయండి."
        )

    async def test_real_handler_path_reuses_free_text_district_for_follow_up(self):
        first = ConversationResponse(
            intent="general_conversation",
            language="en-IN",
            response_text="I recorded Warangal as your district.",
            is_abstention=False,
            safety_status="PASSED",
        )
        second = ConversationResponse(
            intent="crop_recommendation",
            language="en-IN",
            response_text=(
                "No approved evidence is available for this crop in Warangal. "
                "Please contact your Agricultural Officer, nearest KVK, or Kisan Call Centre at 1800-180-1551."
            ),
            is_abstention=True,
            safety_status="ABSTAINED",
            safety_reason="NO_APPROVED_EVIDENCE",
        )
        self.mock_orchestrator.process_message.side_effect = [first, second]

        first_update = self._create_mock_update(update_id=130, text="I am in Warangal")
        await self.handler.handle_text(first_update, self.mock_context)
        second_update = self._create_mock_update(update_id=131, text="Which cotton variety should I sow?")
        await self.handler.handle_text(second_update, self.mock_context)

        request = self.mock_orchestrator.process_message.call_args_list[1].args[0]
        self.assertEqual(request.location.district, "Warangal")
        self.assertNotIn("district", second_update.effective_message.reply_text.call_args.args[0].lower())
        self.assertIn("1800-180-1551", second_update.effective_message.reply_text.call_args.args[0])

    async def test_consent_decline_uses_detected_english_language(self):
        update = self._create_mock_update(update_id=132, text="No")
        await self.handler.handle_text(update, self.mock_context)
        reply = update.effective_message.reply_text.call_args.args[0]
        self.assertIn("location", reply.lower())
        self.assertNotIn("వాతావరణ", reply)

    # --- Test 4: Voice Message Success ---
    @patch("app.telegram.handlers.convert_ogg_opus_to_wav")
    @patch("app.telegram.handlers.convert_wav_bytes_to_ogg_opus")
    async def test_voice_message_success(self, mock_to_ogg, mock_to_wav):
        mock_voice = MagicMock(spec=Voice)
        mock_voice.file_id = "voice_file_abc_123"
        mock_voice.duration = 15  # 15s (valid <= 30s)

        update = self._create_mock_update(update_id=104, voice=mock_voice)

        # Mock Telegram file download
        mock_file = MagicMock()
        mock_file.download_as_bytearray = AsyncMock(return_value=bytearray(b"dummy_ogg_bytes"))
        self.mock_context.bot.get_file.return_value = mock_file

        # Mock audio conversions
        mock_to_wav.return_value = b"RIFF_dummy_wav_bytes"
        mock_to_ogg.return_value = (b"OggS_dummy_reply_ogg", 3.0)

        # Mock VoicePipelineService response
        dummy_wav_reply = b"RIFF_tts_wav_bytes"
        mock_voice_res = VoiceProcessingResponse(
            status="success",
            transcript="వరి ఎరువులు",
            detected_language="te-IN",
            intent="FERTILIZER_GUIDANCE",
            response_text="ఎకరాకు 50 కేజీల యూరియా వేయండి.",
            audio_base64=base64.b64encode(dummy_wav_reply).decode("ascii"),
            audio_content_type="audio/wav",
            audio_duration_seconds=3.0,
            safety_status="PASSED",
            is_abstention=False,
            is_fallback_text_only=False,
        )
        self.mock_voice_service.process_audio_bytes.return_value = mock_voice_res

        await self.handler.handle_voice(update, self.mock_context)

        # Verify chat action RECORD_VOICE was sent
        self.mock_context.bot.send_chat_action.assert_called_once_with(
            chat_id=123456789, action=ChatAction.RECORD_VOICE
        )

        # Verify voice pipeline was executed
        self.mock_voice_service.process_audio_bytes.assert_called_once()

        # Verify reply_voice was called with converted OGG audio
        update.effective_message.reply_voice.assert_called_once()
        call_kwargs = update.effective_message.reply_voice.call_args[1]
        voice_arg = call_kwargs["voice"]
        self.assertIsInstance(voice_arg, io.BytesIO)
        self.assertEqual(voice_arg.getvalue(), b"OggS_dummy_reply_ogg")

    # --- Test 5: Voice No Verified Evidence Delivers Telugu Voice Abstention ---
    @patch("app.telegram.handlers.convert_ogg_opus_to_wav")
    @patch("app.telegram.handlers.convert_wav_bytes_to_ogg_opus")
    async def test_voice_safety_rejected_delivers_voice_abstention(self, mock_to_ogg, mock_to_wav):
        mock_voice = MagicMock(spec=Voice)
        mock_voice.file_id = "voice_file_unsafe_456"
        mock_voice.duration = 10

        update = self._create_mock_update(update_id=105, voice=mock_voice)

        mock_file = MagicMock()
        mock_file.download_as_bytearray = AsyncMock(return_value=bytearray(b"raw_ogg"))
        self.mock_context.bot.get_file.return_value = mock_file
        mock_to_wav.return_value = b"wav_bytes"
        mock_to_ogg.return_value = (b"OggS_abstention_ogg", 2.0)

        # Mock REJECTED safety response
        mock_voice_res = VoiceProcessingResponse(
            status="success",
            transcript="పురుగుల మందులు కలపవచ్చా",
            detected_language="te-IN",
            intent="PESTICIDE_SAFETY",
            response_text="రెండు రకాల పురుగుమందులను కలపడం ప్రమాదకరం.",
            audio_base64=None,
            safety_status="REJECTED",  # REJECTED
            is_abstention=True,
            is_fallback_text_only=True,
        )
        self.mock_voice_service.process_audio_bytes.return_value = mock_voice_res

        await self.handler.handle_voice(update, self.mock_context)

        # Core requirement: All voice queries must reply with voice messages in Telugu, never text
        update.effective_message.reply_voice.assert_called_once()
        update.effective_message.reply_text.assert_not_called()

    # --- Test 6: Voice Duration Limit Exceeded (> 30s) ---
    @patch("app.telegram.handlers.convert_wav_bytes_to_ogg_opus")
    async def test_voice_duration_exceeded_notice(self, mock_to_ogg):
        mock_to_ogg.return_value = (b"OggS_duration_limit_ogg", 2.0)
        mock_voice = MagicMock(spec=Voice)
        mock_voice.file_id = "voice_file_long_789"
        mock_voice.duration = 35  # > 30 seconds

        update = self._create_mock_update(update_id=106, voice=mock_voice)

        await self.handler.handle_voice(update, self.mock_context)

        # Politeness notice sent via voice without downloading or processing audio
        update.effective_message.reply_voice.assert_called_once()
        update.effective_message.reply_text.assert_not_called()
        self.mock_voice_service.process_audio_bytes.assert_not_called()
        self.mock_context.bot.get_file.assert_not_called()

    # --- Test 7: Unexpected Failure Fallback ---
    async def test_failure_fallback_on_exception(self):
        update = self._create_mock_update(update_id=107, text="పత్తి ధరలు")
        self.mock_orchestrator.process_message.side_effect = Exception("Database timeout")

        await self.handler.handle_text(update, self.mock_context)

        # Handlers must catch exceptions and reply with safe fallback without crashing
        update.effective_message.reply_text.assert_called_once()
        self.assertNotRegex(
            update.effective_message.reply_text.call_args.args[0],
            "\u0c05\u0c02\u0c21\u0c3f",
        )

    # --- Test 8: Duplicate Update Id Ignored ---
    async def test_duplicate_update_id_ignored(self):
        update1 = self._create_mock_update(update_id=108, text="hi")
        update2 = self._create_mock_update(update_id=108, text="hi")

        await self.handler.handle_text(update1, self.mock_context)
        await self.handler.handle_text(update2, self.mock_context)

        # update1 was processed (1 reply)
        self.assertEqual(update1.effective_message.reply_text.call_count, 1)
        # update2 was duplicate ignored (0 replies)
        self.assertEqual(update2.effective_message.reply_text.call_count, 0)


class TestTelegramConsentSession(unittest.TestCase):
    """Unit tests for consent parsing, location entity extraction, and SQLite session persistence."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_db_path = Path(self.temp_dir.name) / "test_sessions.db"
        self.repo = TelegramSessionRepository(db_path=self.test_db_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_is_consent_grant(self):
        # Explicit phrases are accepted even when awaiting_consent is False
        self.assertTrue(is_consent_grant("సమ్మతి ఇస్తున్నాను", awaiting_consent=False))
        self.assertTrue(is_consent_grant("సమ్మతిస్తున్నాను", awaiting_consent=False))
        self.assertTrue(is_consent_grant("నా సమ్మతి ఇస్తున్నాను", awaiting_consent=False))
        self.assertTrue(is_consent_grant("i consent", awaiting_consent=False))
        self.assertTrue(is_consent_grant("i give consent", awaiting_consent=False))

        # Contextual short terms are accepted ONLY when awaiting_consent is True
        self.assertFalse(is_consent_grant("సరే", awaiting_consent=False))
        self.assertTrue(is_consent_grant("సరే", awaiting_consent=True))
        self.assertFalse(is_consent_grant("అవును", awaiting_consent=False))
        self.assertTrue(is_consent_grant("అవును", awaiting_consent=True))
        self.assertFalse(is_consent_grant("ok", awaiting_consent=False))
        self.assertTrue(is_consent_grant("ok", awaiting_consent=True))
        self.assertFalse(is_consent_grant("yes", awaiting_consent=False))
        self.assertTrue(is_consent_grant("yes", awaiting_consent=True))
        self.assertFalse(is_consent_grant("sure", awaiting_consent=False))
        self.assertTrue(is_consent_grant("sure", awaiting_consent=True))

        # Negative phrases must not be treated as consent even if affirmative words are present
        self.assertFalse(is_consent_grant("సమ్మతి లేదు", awaiting_consent=True))
        self.assertFalse(is_consent_grant("వద్దు సమ్మతి ఇవ్వను", awaiting_consent=True))

        # Agricultural / conversational queries must never accidentally trigger consent
        self.assertFalse(is_consent_grant("వరికి యూరియా ఇస్తున్నాను", awaiting_consent=True))
        self.assertFalse(is_consent_grant("పత్తికి నీరు ఇస్తున్నాను", awaiting_consent=True))
        self.assertFalse(is_consent_grant("look at my crop disease", awaiting_consent=True))
        self.assertFalse(is_consent_grant("pesticide measure for 1 acre", awaiting_consent=True))
        self.assertFalse(is_consent_grant("token fertilizer", awaiting_consent=True))
        self.assertFalse(is_consent_grant("", awaiting_consent=True))
        self.assertFalse(is_consent_grant(None, awaiting_consent=True))

    def test_is_consent_reject(self):
        self.assertTrue(is_consent_reject("సమ్మతి లేదు"))
        self.assertTrue(is_consent_reject("వద్దు"))
        self.assertTrue(is_consent_reject("వద్దండి"))
        self.assertTrue(is_consent_reject("లేదు"))
        self.assertTrue(is_consent_reject("తిరస్కరిస్తున్నాను"))
        self.assertTrue(is_consent_reject("no"))
        self.assertTrue(is_consent_reject("i do not consent"))
        self.assertTrue(is_consent_reject("cancel"))
        self.assertFalse(is_consent_reject("సమ్మతి ఇస్తున్నాను"))
        self.assertFalse(is_consent_reject("వరిలో తెగులు"))

    def test_extract_location_from_text(self):
        # Full text with Telugu district, mandal, village, and PIN
        text = "సూర్యాపేట జిల్లా కోదాడ మండలం రామవరం గ్రామం 508206 లో రేపు వర్షం పడుతుందా?"
        village, mandal, district, pin = extract_location_from_text(text)
        self.assertEqual(village, "రామవరం")
        self.assertEqual(mandal, "కోదాడ")
        self.assertEqual(district, "Suryapet")
        self.assertEqual(pin, "508206")

        # English text
        text_en = "Ramavaram village Kodad mandal Suryapet district 508206"
        village, mandal, district, pin = extract_location_from_text(text_en)
        self.assertEqual(village, "Ramavaram")
        self.assertEqual(mandal, "Kodad")
        self.assertEqual(district, "Suryapet")
        self.assertEqual(pin, "508206")

        # Indic digits
        text_indic = "పిన్ కోడ్ ౫౦౮౨౦౬ నల్గొండ జిల్లా"
        village, mandal, district, pin = extract_location_from_text(text_indic)
        self.assertEqual(district, "Nalgonda")
        self.assertEqual(pin, "508206")

    def test_session_repository_persistence_and_restart(self):
        user_id = "tg_12345"
        self.repo.set_consent(user_id, consent_given=True)
        self.repo.update_location(user_id, village="రామవరం", district="Suryapet", pin_code="508206")
        self.repo.set_pending_query(user_id, "రేపు వర్షం పడుతుందా?", awaiting_consent=True)

        session = self.repo.get_session(user_id)
        self.assertTrue(session.weather_provider_sharing_consent)
        # Location is available in temporary in-memory context during interaction
        self.assertEqual(session.village_name, "రామవరం")
        self.assertEqual(session.district_name, "Suryapet")
        self.assertEqual(session.pin_code, "508206")
        self.assertEqual(session.pending_weather_query, "రేపు వర్షం పడుతుందా?")
        self.assertTrue(session.awaiting_consent)

        # Verify location was NEVER written to persistent SQLite storage (Phase 8.5)
        conn = sqlite3.connect(self.test_db_path)
        row = conn.execute(
            "SELECT village_name, district_name, pin_code FROM telegram_user_consents WHERE telegram_user_id = ?",
            (user_id,),
        ).fetchone()
        conn.close()
        self.assertIsNone(row[0])
        self.assertIsNone(row[1])
        self.assertIsNone(row[2])

        # Clear pending query
        self.repo.clear_pending_query(user_id)
        session_cleared = self.repo.get_session(user_id)
        self.assertIsNone(session_cleared.pending_weather_query)
        self.assertFalse(session_cleared.awaiting_consent)
        self.assertTrue(session_cleared.weather_provider_sharing_consent)

        # Simulate bot restart by creating a new repository pointing to the same db
        new_repo = TelegramSessionRepository(db_path=self.test_db_path)
        restarted_session = new_repo.get_session(user_id)
        # Consent is persisted independently across restart
        self.assertTrue(restarted_session.weather_provider_sharing_consent)
        # Restart does NOT restore previously stored locations (Phase 8.5)
        self.assertIsNone(restarted_session.village_name)
        self.assertIsNone(restarted_session.district_name)

    def test_location_expiry_after_30_minutes(self):
        user_id = "tg_expiry_test"
        t_base = 1000.0
        self.repo.update_location(user_id, village="రామవరం", district="Suryapet", current_time=t_base)

        # Before 30 minutes (29 minutes = 1740s)
        session_active = self.repo.get_session(user_id, current_time=t_base + 1740.0)
        self.assertEqual(session_active.district_name, "Suryapet")
        self.assertEqual(session_active.village_name, "రామవరం")

        # After 30 minutes (30 minutes + 1 second = 1801s)
        session_expired = self.repo.get_session(user_id, current_time=t_base + 1801.0)
        self.assertIsNone(session_expired.district_name)
        self.assertIsNone(session_expired.village_name)

    def test_legacy_sqlite_location_migration(self):
        # Directly insert legacy row with location in SQLite
        conn = sqlite3.connect(self.test_db_path)
        conn.execute("""
            INSERT OR REPLACE INTO telegram_user_consents (
                telegram_user_id, weather_provider_sharing_consent, village_name, district_name, created_at, updated_at
            ) VALUES ('legacy_user', 1, 'హైదరాబాద్', 'Hyderabad', '2026-01-01', '2026-01-01')
        """)
        conn.commit()
        conn.close()

        # Initialize repository triggering Phase 8.5 safe migration
        migrated_repo = TelegramSessionRepository(db_path=self.test_db_path)

        # Verify SQLite row was cleared of location fields
        conn = sqlite3.connect(self.test_db_path)
        row = conn.execute(
            "SELECT weather_provider_sharing_consent, village_name, district_name FROM telegram_user_consents WHERE telegram_user_id = 'legacy_user'"
        ).fetchone()
        conn.close()

        self.assertEqual(row[0], 1)  # Consent preserved independently
        self.assertIsNone(row[1])   # Village purged
        self.assertIsNone(row[2])   # District purged

    def test_session_user_isolation(self):
        user_a = "user_aaa"
        user_b = "user_bbb"

        self.repo.set_consent(user_a, consent_given=True)
        self.repo.update_location(user_a, village="రామవరం", district="Suryapet")

        session_a = self.repo.get_session(user_a)
        session_b = self.repo.get_session(user_b)

        self.assertTrue(session_a.weather_provider_sharing_consent)
        self.assertFalse(session_b.weather_provider_sharing_consent)
        self.assertIsNone(session_b.village_name)
        self.assertIsNone(session_b.district_name)

    def test_clear_location_and_delete_user_session(self):
        user_id = "user_del_test"
        self.repo.set_consent(user_id, consent_given=True)
        self.repo.update_location(user_id, village="రామవరం", mandal="కోదాడ", district="Suryapet", pin_code="508206")

        # Verify location was set
        session = self.repo.get_session(user_id)
        self.assertEqual(session.village_name, "రామవరం")
        self.assertEqual(session.pin_code, "508206")

        # Clear location only
        self.repo.clear_location(user_id)
        session_cleared = self.repo.get_session(user_id)
        self.assertIsNone(session_cleared.village_name)
        self.assertIsNone(session_cleared.mandal_name)
        self.assertIsNone(session_cleared.district_name)
        self.assertIsNone(session_cleared.pin_code)
        # Consent remains intact
        self.assertTrue(session_cleared.weather_provider_sharing_consent)

        # Permanently delete entire record
        self.repo.delete_user_session(user_id)
        session_deleted = self.repo.get_session(user_id)
        self.assertFalse(session_deleted.weather_provider_sharing_consent)
        self.assertIsNone(session_deleted.village_name)


class TestTelegramWeatherConsentFlow(unittest.IsolatedAsyncioTestCase):
    """Integration tests for Telegram weather consent flow and location resolution."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_db_path = Path(self.temp_dir.name) / "test_flow.db"
        self.session_repo = TelegramSessionRepository(db_path=self.test_db_path)

        self.mock_orchestrator = MagicMock(spec=ConversationOrchestrator)
        self.mock_voice_service = MagicMock(spec=VoicePipelineService)
        self.handler = TelegramHandler(
            orchestrator=self.mock_orchestrator,
            voice_service=self.mock_voice_service,
            session_repo=self.session_repo,
        )

        self.mock_context = MagicMock()
        self.mock_context.bot = MagicMock()
        self.mock_context.bot.send_chat_action = AsyncMock()

    def tearDown(self):
        self.temp_dir.cleanup()

    def _create_mock_update(self, user_id: int, text: str, update_id: int = 1) -> Update:
        update = MagicMock(spec=Update)
        update.update_id = update_id

        user = MagicMock(spec=User)
        user.id = user_id
        update.effective_user = user

        chat = MagicMock(spec=Chat)
        chat.id = user_id
        update.effective_chat = chat

        message = MagicMock(spec=Message)
        message.text = text
        message.voice = None
        message.audio = None
        message.reply_text = AsyncMock()
        message.reply_voice = AsyncMock()
        update.effective_message = message
        return update

    def _create_mock_voice_update(self, user_id: int, file_id: str = "voice_file_123", duration: int = 5, update_id: int = 1) -> Update:
        update = MagicMock(spec=Update)
        update.update_id = update_id

        user = MagicMock(spec=User)
        user.id = user_id
        update.effective_user = user

        chat = MagicMock(spec=Chat)
        chat.id = user_id
        update.effective_chat = chat

        voice_obj = MagicMock(spec=Voice)
        voice_obj.file_id = file_id
        voice_obj.duration = duration

        message = MagicMock(spec=Message)
        message.voice = voice_obj
        message.audio = None
        message.text = None
        message.reply_text = AsyncMock()
        message.reply_voice = AsyncMock()
        update.effective_message = message
        return update

    async def test_weather_question_prompts_consent_and_stores_pending_query(self):
        """1. User asks weather question without consent -> bot prompts for consent & stores pending query."""
        user_id = 7001
        update = self._create_mock_update(user_id=user_id, text="రేపు మా గ్రామంలో వర్షం పడుతుందా?")

        # Mock orchestrator consent-required abstention
        mock_resp = MagicMock(spec=ConversationResponse)
        mock_resp.response_text = "వాతావరణ సమాచారం పొందడానికి మీ సమ్మతి అవసరం."
        mock_resp.safety_reason = "WEATHER_LOCATION_SHARING_CONSENT_REQUIRED"
        self.mock_orchestrator.process_message.return_value = mock_resp

        await self.handler.handle_text(update, self.mock_context)

        # Bot replies with consent prompt
        update.effective_message.reply_text.assert_called_once()
        prompt_args, prompt_kwargs = update.effective_message.reply_text.call_args
        self.assertIn("అవును", prompt_args[0])
        self.assertIn("reply_markup", prompt_kwargs)
        self.assertEqual(len(prompt_kwargs["reply_markup"].inline_keyboard[0]), 2)
        self.assertEqual(
            [button.text for button in prompt_kwargs["reply_markup"].inline_keyboard[0]],
            ["అవును", "వద్దు"],
        )

        # Session records pending query and awaiting_consent
        session = self.session_repo.get_session(str(user_id))
        self.assertTrue(session.awaiting_consent)
        self.assertEqual(session.pending_weather_query, "రేపు మా గ్రామంలో వర్షం పడుతుందా?")
        self.assertFalse(session.weather_provider_sharing_consent)

    async def test_named_weather_place_answers_without_consent_prompt(self):
        user_id = 7011
        update = self._create_mock_update(
            user_id=user_id,
            text="What is the weather today in Warangal?",
            update_id=70111,
        )
        response = MagicMock(spec=ConversationResponse)
        response.response_text = "Warangal is currently warm and clear."
        response.safety_reason = None
        self.mock_orchestrator.process_message.return_value = response

        await self.handler.handle_text(update, self.mock_context)

        request = self.mock_orchestrator.process_message.call_args.args[0]
        self.assertEqual(request.location.place_name, "Warangal")
        self.assertTrue(request.location.named_in_message)
        update.effective_message.reply_text.assert_called_once_with(response.response_text)
        session = self.session_repo.get_session(str(user_id))
        self.assertFalse(session.awaiting_consent)
        self.assertIsNone(session.pending_weather_query)

    async def test_english_weather_consent_prompt_explains_yes_or_no(self):
        user_id = 7012
        update = self._create_mock_update(
            user_id=user_id,
            text="What is the weather today?",
            update_id=70121,
        )
        response = MagicMock(spec=ConversationResponse)
        response.response_text = "Please provide consent for weather."
        response.safety_reason = "WEATHER_LOCATION_SHARING_CONSENT_REQUIRED"
        self.mock_orchestrator.process_message.return_value = response

        await self.handler.handle_text(update, self.mock_context)

        prompt, kwargs = update.effective_message.reply_text.call_args
        self.assertIn("Yes", prompt[0])
        self.assertIn("No", prompt[0])
        self.assertEqual(
            [button.text for button in kwargs["reply_markup"].inline_keyboard[0]],
            ["Yes", "No"],
        )

    async def test_consent_granted_resumes_pending_weather_query(self):
        """2. User replies 'సమ్మతి ఇస్తున్నాను' -> persists consent and resumes original weather query."""
        user_id = 7002
        # Seed session as awaiting consent with pending query
        self.session_repo.set_pending_query(str(user_id), "రేపు మా గ్రామంలో వర్షం పడుతుందా?", awaiting_consent=True)

        update = self._create_mock_update(user_id=user_id, text="సమ్మతి ఇస్తున్నాను")

        mock_resp = MagicMock(spec=ConversationResponse)
        mock_resp.response_text = "రేపు మీ ప్రాంతంలో వర్షం పడే అవకాశం లేదు."
        mock_resp.safety_reason = None
        self.mock_orchestrator.process_message.return_value = mock_resp

        await self.handler.handle_text(update, self.mock_context)

        # Orchestrator was called with the resumed question and affirmative guest_consent
        self.mock_orchestrator.process_message.assert_called_once()
        conv_req = self.mock_orchestrator.process_message.call_args[0][0]
        self.assertEqual(conv_req.question, "రేపు మా గ్రామంలో వర్షం పడుతుందా?")
        self.assertIsNotNone(conv_req.guest_consent)
        self.assertTrue(conv_req.guest_consent.consent_given)

        # Reply delivered to user
        update.effective_message.reply_text.assert_called_once_with(
            "రేపు మీ ప్రాంతంలో వర్షం పడే అవకాశం లేదు."
        )

        # Session state verified
        session = self.session_repo.get_session(str(user_id))
        self.assertTrue(session.weather_provider_sharing_consent)
        self.assertFalse(session.awaiting_consent)
        self.assertIsNone(session.pending_weather_query)

    async def test_weather_ask_consent_answer_then_ask_again_uses_persisted_consent(self):
        user_id = 7010
        ask = self._create_mock_update(user_id=user_id, text="What is the weather in Warangal?", update_id=70101)
        consent_response = MagicMock(spec=ConversationResponse)
        consent_response.response_text = "Location consent is required for weather."
        consent_response.safety_reason = "WEATHER_LOCATION_SHARING_CONSENT_REQUIRED"
        answer = MagicMock(spec=ConversationResponse)
        answer.response_text = "The weather service returned the current weather for Warangal."
        answer.safety_reason = None
        self.mock_orchestrator.process_message.side_effect = [consent_response, answer, answer]

        await self.handler.handle_text(ask, self.mock_context)
        yes = self._create_mock_update(user_id=user_id, text="yes", update_id=70102)
        await self.handler.handle_text(yes, self.mock_context)

        session = self.session_repo.get_session(str(user_id))
        self.assertTrue(session.weather_provider_sharing_consent)
        self.assertFalse(session.awaiting_consent)
        self.assertIsNone(session.pending_weather_query)
        resumed_request = self.mock_orchestrator.process_message.call_args_list[1].args[0]
        self.assertTrue(resumed_request.guest_consent.consent_given)
        self.assertEqual(resumed_request.question, "What is the weather in Warangal?")

        again = self._create_mock_update(user_id=user_id, text="What is the weather in Warangal?", update_id=70103)
        await self.handler.handle_text(again, self.mock_context)
        again_reply = again.effective_message.reply_text.call_args.args[0]
        self.assertEqual(again_reply, answer.response_text)
        self.assertNotIn("consent", again_reply.lower())
        self.assertNotIn("అవును", again_reply)

    async def test_consent_rejected_revokes_consent_and_cancels_pending(self):
        """3. User replies 'సమ్మతి లేదు' -> revokes consent, purges location, cancels pending, sends polite Telugu notice."""
        user_id = 7003
        self.session_repo.set_pending_query(str(user_id), "రేపు వర్షం పడుతుందా?", awaiting_consent=True)
        self.session_repo.update_location(str(user_id), village="రామవరం", district="Suryapet")

        update = self._create_mock_update(user_id=user_id, text="సమ్మతి లేదు")

        await self.handler.handle_text(update, self.mock_context)

        # Orchestrator was NOT called for weather
        self.mock_orchestrator.process_message.assert_not_called()

        # Polite Telugu revocation message sent
        update.effective_message.reply_text.assert_called_once_with(
            "సరే. వాతావరణం కోసం మీ లొకేషన్ పంచబడదు. నిల్వ చేసిన లొకేషన్ వివరాలను తొలగించాను."
        )

        # Consent is False, pending query is cleared, and location is purged
        session = self.session_repo.get_session(str(user_id))
        self.assertFalse(session.weather_provider_sharing_consent)
        self.assertFalse(session.awaiting_consent)
        self.assertIsNone(session.pending_weather_query)
        self.assertIsNone(session.village_name)
        self.assertIsNone(session.district_name)

    async def test_user_requested_location_deletion(self):
        """User sends 'లొకేషన్ తొలగించండి' -> clears stored location from SQLite."""
        user_id = 7006
        self.session_repo.set_consent(str(user_id), consent_given=True)
        self.session_repo.update_location(str(user_id), village="రామవరం", mandal="కోదాడ", district="Suryapet", pin_code="508206")

        update = self._create_mock_update(user_id=user_id, text="లొకేషన్ తొలగించండి")

        await self.handler.handle_text(update, self.mock_context)

        # Acknowledged in Telugu
        update.effective_message.reply_text.assert_called_once_with(
            "మీ లొకేషన్ వివరాలు విజయవంతంగా తొలగించబడ్డాయి."
        )

        # Stored location is wiped
        session = self.session_repo.get_session(str(user_id))
        self.assertIsNone(session.village_name)
        self.assertIsNone(session.mandal_name)
        self.assertIsNone(session.district_name)
        self.assertIsNone(session.pin_code)
        # Weather consent flag remains unchanged
        self.assertTrue(session.weather_provider_sharing_consent)

    async def test_subsequent_weather_question_uses_saved_consent(self):
        """4. Subsequent weather question uses saved consent without asking again."""
        user_id = 7004
        # User already granted consent
        self.session_repo.set_consent(str(user_id), consent_given=True)

        text = "సూర్యాపేట జిల్లా కోదాడ మండలం రామవరం గ్రామం 508206 లో రేపు వర్షం పడుతుందా?"
        update = self._create_mock_update(user_id=user_id, text=text)

        mock_resp = MagicMock(spec=ConversationResponse)
        mock_resp.response_text = "సూర్యాపేటలో రేపు తేలికపాటి వర్షం పడే అవకాశం ఉంది."
        mock_resp.safety_reason = None
        self.mock_orchestrator.process_message.return_value = mock_resp

        await self.handler.handle_text(update, self.mock_context)

        # Orchestrator was called with location and guest consent
        self.mock_orchestrator.process_message.assert_called_once()
        conv_req = self.mock_orchestrator.process_message.call_args[0][0]
        self.assertIsNotNone(conv_req.guest_consent)
        self.assertTrue(conv_req.guest_consent.consent_given)
        self.assertIsNotNone(conv_req.location)
        self.assertEqual(conv_req.location.district, "Suryapet")
        self.assertEqual(conv_req.location.mandal, "కోదాడ")
        self.assertEqual(conv_req.location.village, "రామవరం")
        self.assertEqual(conv_req.location.pin_code, "508206")

        update.effective_message.reply_text.assert_called_once_with(
            "సూర్యాపేటలో రేపు తేలికపాటి వర్షం పడే అవకాశం ఉంది."
        )

        # Phase 8.5: Location is cleared after successful weather processing
        self.assertIsNone(self.session_repo.get_temp_location(str(user_id)))
        session_after = self.session_repo.get_session(str(user_id))
        self.assertIsNone(session_after.district_name)
        self.assertIsNone(session_after.village_name)

    async def test_location_cleared_after_weather_processing_causes_reprompt_if_no_location(self):
        """Phase 8.5: If location context is unavailable after completion or expiry, orchestrator asks again."""
        user_id = 7009
        self.session_repo.set_consent(str(user_id), consent_given=True)

        # 1. First weather interaction provides location
        text1 = "సూర్యాపేటలో రేపు వర్షం పడుతుందా?"
        update1 = self._create_mock_update(user_id=user_id, text=text1, update_id=901)
        mock_resp1 = MagicMock(spec=ConversationResponse)
        mock_resp1.response_text = "సూర్యాపేటలో రేపు వర్షం పడదు."
        mock_resp1.safety_reason = None
        self.mock_orchestrator.process_message.return_value = mock_resp1

        await self.handler.handle_text(update1, self.mock_context)
        # Location was cleared
        self.assertIsNone(self.session_repo.get_temp_location(str(user_id)))

        # 2. Second weather interaction without location
        self.mock_orchestrator.reset_mock()
        mock_resp2 = MagicMock(spec=ConversationResponse)
        mock_resp2.response_text = "మీ ఊరి వాతావరణ వివరాల కోసం, మీది ఏ మండలం లేదా జిల్లానో చెప్తారా ?"
        mock_resp2.safety_reason = "LOCATION_PARAMETERS_REQUIRED"
        self.mock_orchestrator.process_message.return_value = mock_resp2

        text2 = "ఎల్లుండి వర్షం పడుతుందా?"
        update2 = self._create_mock_update(user_id=user_id, text=text2, update_id=902)
        await self.handler.handle_text(update2, self.mock_context)

        # Orchestrator received no location
        conv_req2 = self.mock_orchestrator.process_message.call_args[0][0]
        self.assertIsNone(conv_req2.location)
        update2.effective_message.reply_text.assert_called_once_with(
            "మీ ఊరి వాతావరణ వివరాల కోసం, మీది ఏ మండలం లేదా జిల్లానో చెప్తారా ?"
        )

    async def test_farmers_table_not_modified(self):
        """5. Verifies Telegram consent operations never insert rows into core 'farmers' table."""
        user_id = 7005
        # Perform session operations
        self.session_repo.set_consent(str(user_id), consent_given=True)
        self.session_repo.update_location(str(user_id), village="రామవరం", district="Suryapet")

        # Check real application database
        conn = sqlite3.connect(str(settings.DATABASE_PATH))
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM farmers")
            count = cursor.fetchone()[0]
            self.assertEqual(count, 0)
        finally:
            conn.close()

    # --- Phase 9.0+ Voice Tests: Voice Message In -> Voice Note Out ---

    @patch("app.telegram.handlers.convert_ogg_opus_to_wav")
    @patch("app.telegram.handlers.convert_wav_bytes_to_ogg_opus")
    async def test_voice_weather_question_prompts_consent_and_stores_pending_query(self, mock_to_ogg, mock_to_wav):
        """1. Voice weather question -> voice consent prompt & pending query stored."""
        user_id = 7101
        update = self._create_mock_voice_update(user_id=user_id, duration=10, update_id=201)

        mock_file = MagicMock()
        mock_file.download_as_bytearray = AsyncMock(return_value=bytearray(b"raw_ogg"))
        self.mock_context.bot.get_file = AsyncMock(return_value=mock_file)
        mock_to_wav.return_value = b"wav_bytes"
        mock_to_ogg.return_value = (b"OggS_consent_prompt_ogg", 3.0)

        mock_voice_res = VoiceProcessingResponse(
            status="success",
            transcript="రేపు మా గ్రామంలో వర్షం పడుతుందా?",
            detected_language="te-IN",
            intent="weather_inquiry",
            response_text="వాతావరణ సమాచారం పొందడానికి మీ సమ్మతి అవసరం.",
            audio_base64=base64.b64encode(b"RIFF_consent_wav").decode("ascii"),
            safety_status="ABSTAINED",
            safety_reason="WEATHER_LOCATION_SHARING_CONSENT_REQUIRED",
            is_abstention=True,
            is_fallback_text_only=False,
        )
        self.mock_voice_service.process_audio_bytes.return_value = mock_voice_res

        await self.handler.handle_voice(update, self.mock_context)

        # Bot delivers consent prompt as voice message, never text
        update.effective_message.reply_voice.assert_called_once()
        update.effective_message.reply_text.assert_not_called()

        # Session state correctly set to awaiting consent with pending query
        session = self.session_repo.get_session(str(user_id))
        self.assertTrue(session.awaiting_consent)
        self.assertEqual(session.pending_weather_query, "రేపు మా గ్రామంలో వర్షం పడుతుందా?")
        self.assertFalse(session.weather_provider_sharing_consent)

    @patch("app.telegram.handlers.convert_ogg_opus_to_wav")
    @patch("app.telegram.handlers.convert_wav_bytes_to_ogg_opus")
    async def test_voice_consent_granted_with_sare_resumes_pending_weather_query(self, mock_to_ogg, mock_to_wav):
        """2. Voice 'సరే' -> recognizes consent, resumes weather query, delivers voice response."""
        user_id = 7102
        self.session_repo.set_pending_query(str(user_id), "రేపు నిజామాబాద్ లో వర్షం పడుతుందా?", awaiting_consent=True)
        self.session_repo.update_location(str(user_id), district="Nizamabad")

        update = self._create_mock_voice_update(user_id=user_id, duration=3, update_id=202)

        mock_file = MagicMock()
        mock_file.download_as_bytearray = AsyncMock(return_value=bytearray(b"raw_ogg"))
        self.mock_context.bot.get_file = AsyncMock(return_value=mock_file)
        mock_to_wav.return_value = b"wav_bytes"
        mock_to_ogg.return_value = (b"OggS_weather_result_ogg", 4.0)

        # Farmer speaks "సరే"
        mock_voice_res = VoiceProcessingResponse(
            status="success",
            transcript="సరే",
            detected_language="te-IN",
            intent="unsupported_inquiry",
            response_text="I apologize, but verified official evidence is not available...",
            audio_base64=None,
            safety_status="REJECTED",
            is_abstention=True,
            is_fallback_text_only=True,
        )
        self.mock_voice_service.process_audio_bytes.return_value = mock_voice_res

        # Orchestrator responds to resumed weather query
        mock_conv_res = ConversationResponse(
            intent="weather_inquiry",
            language="te-IN",
            response_text="రేపు నిజామాబాద్ జిల్లాలో వాన పడే అవకాశం లేదు .",
            is_abstention=False,
            safety_status="PASSED",
        )
        self.mock_orchestrator.process_message.return_value = mock_conv_res

        await self.handler.handle_voice(update, self.mock_context)

        # Orchestrator was called with resumed weather query and granted consent
        self.mock_orchestrator.process_message.assert_called_once()
        conv_req = self.mock_orchestrator.process_message.call_args[0][0]
        self.assertEqual(conv_req.question, "రేపు నిజామాబాద్ లో వర్షం పడుతుందా?")
        self.assertTrue(conv_req.guest_consent.consent_given)

        # Voice reply delivered with weather forecast, text was NOT sent
        update.effective_message.reply_voice.assert_called_once()
        update.effective_message.reply_text.assert_not_called()

        # Session state: consent is granted, pending query cleared
        session = self.session_repo.get_session(str(user_id))
        self.assertTrue(session.weather_provider_sharing_consent)
        self.assertFalse(session.awaiting_consent)
        self.assertIsNone(session.pending_weather_query)

    @patch("app.telegram.handlers.convert_ogg_opus_to_wav")
    @patch("app.telegram.handlers.convert_wav_bytes_to_ogg_opus")
    async def test_voice_consent_granted_with_avunu_resumes_weather(self, mock_to_ogg, mock_to_wav):
        """3. Voice 'అవును' -> recognizes affirmative consent and resumes weather query."""
        user_id = 7103
        self.session_repo.set_pending_query(str(user_id), "రేపు వర్షం పడుతుందా?", awaiting_consent=True)

        update = self._create_mock_voice_update(user_id=user_id, duration=2, update_id=203)
        mock_file = MagicMock()
        mock_file.download_as_bytearray = AsyncMock(return_value=bytearray(b"raw_ogg"))
        self.mock_context.bot.get_file = AsyncMock(return_value=mock_file)
        mock_to_wav.return_value = b"wav_bytes"
        mock_to_ogg.return_value = (b"OggS_weather_ogg", 3.0)

        # Farmer says "అవును"
        mock_voice_res = VoiceProcessingResponse(
            status="success",
            transcript="అవును",
            detected_language="te-IN",
            intent="unsupported_inquiry",
            response_text="I apologize...",
            audio_base64=None,
            safety_status="REJECTED",
            is_abstention=True,
            is_fallback_text_only=True,
        )
        self.mock_voice_service.process_audio_bytes.return_value = mock_voice_res
        self.mock_orchestrator.process_message.return_value = ConversationResponse(
            intent="weather_inquiry",
            language="te-IN",
            response_text="మీ ఊరి వాతావరణ వివరాల కోసం, మీది ఏ మండలం లేదా జిల్లానో చెప్తారా ?",
            is_abstention=True,
            safety_status="ABSTAINED",
            safety_reason="LOCATION_PARAMETERS_REQUIRED",
        )

        await self.handler.handle_voice(update, self.mock_context)

        # Verified weather query resumption
        self.mock_orchestrator.process_message.assert_called_once()
        conv_req = self.mock_orchestrator.process_message.call_args[0][0]
        self.assertEqual(conv_req.question, "రేపు వర్షం పడుతుందా?")
        self.assertTrue(conv_req.guest_consent.consent_given)
        update.effective_message.reply_voice.assert_called_once()
        update.effective_message.reply_text.assert_not_called()

    @patch("app.telegram.handlers.convert_ogg_opus_to_wav")
    @patch("app.telegram.handlers.convert_wav_bytes_to_ogg_opus")
    async def test_voice_no_verified_agricultural_evidence_delivers_voice_abstention(self, mock_to_ogg, mock_to_wav):
        """4. No verified agricultural evidence -> Telugu voice abstention via reply_voice."""
        user_id = 7104
        update = self._create_mock_voice_update(user_id=user_id, duration=8, update_id=204)
        mock_file = MagicMock()
        mock_file.download_as_bytearray = AsyncMock(return_value=bytearray(b"raw_ogg"))
        self.mock_context.bot.get_file = AsyncMock(return_value=mock_file)
        mock_to_wav.return_value = b"wav_bytes"
        mock_to_ogg.return_value = (b"OggS_abstention_ogg", 3.0)

        # Farmer asks about unverified agricultural topic
        mock_voice_res = VoiceProcessingResponse(
            status="success",
            transcript="డ్రాగన్ ఫ్రూట్ సాగు వివరాలు తెలపండి",
            detected_language="te-IN",
            intent="crop_inquiry",
            response_text="క్షమించండి, మీ ప్రశ్నకు ఖచ్చితమైన సమాధానం ఇవ్వడానికి అధికారిక ఆధారాలు అందుబాటులో లేవు.",
            audio_base64=None,
            safety_status="REJECTED",
            is_abstention=True,
            is_fallback_text_only=True,
        )
        self.mock_voice_service.process_audio_bytes.return_value = mock_voice_res

        await self.handler.handle_voice(update, self.mock_context)

        # Telugu voice abstention delivered via reply_voice, never text
        update.effective_message.reply_voice.assert_called_once()
        update.effective_message.reply_text.assert_not_called()

    async def test_text_message_preserves_text_response_behaviour(self):
        """5. Text question -> existing text-response behaviour remains unchanged."""
        user_id = 7105
        update = self._create_mock_update(user_id=user_id, text="వరి సాగు కాలం ఎప్పుడు?")
        self.mock_orchestrator.process_message.return_value = ConversationResponse(
            intent="crop_inquiry",
            language="te-IN",
            response_text="ఖరీఫ్ సీజన్ లో జూన్-జూలై నెలల్లో వరి సాగు చేస్తారు.",
            is_abstention=False,
            safety_status="PASSED",
        )

        await self.handler.handle_text(update, self.mock_context)

        # Text inquiry receives text response
        update.effective_message.reply_text.assert_called_once_with(
            "ఖరీఫ్ సీజన్ లో జూన్-జూలై నెలల్లో వరి సాగు చేస్తారు."
        )


class TestNaturalConversationalTelugu(unittest.TestCase):
    """Focused tests for Phase 8.4 Natural Conversational Telugu implementation."""

    def test_welcome_message_natural_telangana_style(self):
        self.assertIn("నేను కృషివాణిని", START_MESSAGE)
        self.assertIn("వ్యవసాయ అధికారితో", START_MESSAGE)
        self.assertFalse(START_MESSAGE.startswith("\u0c05\u0c02\u0c21\u0c3f"))
        self.assertNotIn("\u0c05\u0c02\u0c21\u0c3f", START_MESSAGE)

    def test_greeting_message_natural_style(self):
        self.assertIn("నమస్తే!", GREETING_MESSAGE)
        self.assertIn("నేను మీ కృషివాణిని", GREETING_MESSAGE)
        self.assertNotIn("కృషివాణికి స్వాగతం", GREETING_MESSAGE)

    def test_duration_and_fallback_natural_style(self):
        self.assertIn("క్షమించండి,", DURATION_LIMIT_MESSAGE)
        self.assertIn("వాయిస్ మెసేజ్", DURATION_LIMIT_MESSAGE)
        self.assertIn("క్షమించండి,", FALLBACK_ERROR_MESSAGE)

    def test_location_question_natural_style(self):
        from app.conversation.service import ConversationOrchestrator
        orchestrator = ConversationOrchestrator()
        # Telegram channel gets natural conversational phrasing.
        loc_resp = orchestrator._create_location_required_abstention("te-IN", "WEATHER_INQUIRY", channel="telegram")
        self.assertIn("మీ ఊరి వాతావరణ వివరాల కోసం", loc_resp.response_text)
        self.assertIn("చెప్తారా?", loc_resp.response_text)
        self.assertNotIn("పేరును తెలపండి", loc_resp.response_text)

        # WhatsApp and default channels preserve original baseline phrasing
        wa_loc_resp = orchestrator._create_location_required_abstention("te-IN", "WEATHER_INQUIRY", channel="whatsapp")
        self.assertIn("వాతావరణ సమాచారం తెలుసుకోవడానికి దయచేసి మీ జిల్లా లేదా మండల పేరును తెలపండి.", wa_loc_resp.response_text)

    def test_weather_error_fallback_natural_style(self):
        from app.conversation.service import ConversationOrchestrator
        orchestrator = ConversationOrchestrator()
        # Telegram channel gets natural conversational error fallback
        err_resp = orchestrator._create_weather_service_error_abstention("te-IN", "Timeout", channel="telegram")
        self.assertIn("సాంకేతిక సమస్య", err_resp.response_text)
        self.assertIn("రిపోర్ట్ అందడం లేదు.", err_resp.response_text)

        # WhatsApp and default channels preserve baseline phrasing
        wa_err_resp = orchestrator._create_weather_service_error_abstention("te-IN", "Timeout", channel="whatsapp")
        self.assertIn("సాంకేతిక సమస్య కారణంగా ప్రస్తుతం వాతావరణ సమాచారం అందుబాటులో లేదు.", wa_err_resp.response_text)

    def test_channel_awareness_district_and_llm(self):
        from app.conversation.service import ConversationOrchestrator
        from app.llm.service import LLMReasoningService, BASE_SYSTEM_INSTRUCTION, TELEGRAM_SYSTEM_INSTRUCTION
        from app.llm.schemas import LLMReasoningRequest

        orchestrator = ConversationOrchestrator()
        # District confirmation prompt
        tg_dist = orchestrator._create_district_confirmation_required_response("te-IN", channel="telegram")
        self.assertIn("మీది తెలంగాణలో ఏ జిల్లానో చెప్తారా?", tg_dist.response_text)

        wa_dist = orchestrator._create_district_confirmation_required_response("te-IN", channel="whatsapp")
        self.assertIn("అధికారిక IMD వాతావరణ హెచ్చరికలను తనిఖీ చేయడానికి దయచేసి తెలంగాణలోని మీ జిల్లాను తెలియజేయండి.", wa_dist.response_text)

        # LLM prompt selection
        llm = LLMReasoningService()
        tg_req = LLMReasoningRequest(farmer_question="హలో", channel="telegram")
        tg_msgs = llm._build_prompt_messages(tg_req)
        self.assertEqual(tg_msgs[0]["content"], TELEGRAM_SYSTEM_INSTRUCTION)

        wa_req = LLMReasoningRequest(farmer_question="హలో", channel="whatsapp")
        wa_msgs = llm._build_prompt_messages(wa_req)
        self.assertEqual(wa_msgs[0]["content"], BASE_SYSTEM_INSTRUCTION)

        # LLM error abstention
        tg_err = llm._create_error_abstention(tg_req, "TEST_ERR", "detail")
        self.assertIn("సమాధానం ఇవ్వలేకపోతున్నాను.", tg_err.response)

        wa_err = llm._create_error_abstention(wa_req, "TEST_ERR", "detail")
        self.assertIn("సమాధానం ఇవ్వలేకపోతున్నాము", wa_err.response)

    def test_llm_system_instruction_contains_natural_telugu_policy(self):
        from app.llm.service import SYSTEM_INSTRUCTION
        # Enforces conversational Telangana style
        self.assertIn("Telangana conversational style", SYSTEM_INSTRUCTION)
        self.assertNotIn("\u0c05\u0c02\u0c21\u0c3f", SYSTEM_INSTRUCTION)
        # Enforces code-mixed vocabulary
        self.assertIn("యూరియా", SYSTEM_INSTRUCTION)
        self.assertIn("డీఏపీ", SYSTEM_INSTRUCTION)
        self.assertIn("AO సార్", SYSTEM_INSTRUCTION)
        # Enforces single-question constraint
        self.assertIn("ASK ONLY ONE PRIMARY QUESTION AT A TIME", SYSTEM_INSTRUCTION)
        # Blacklists Sanskritised / bureaucratic vocabulary
        self.assertIn("NEVER use 'సమ్మతి', 'భౌగోళిక స్థానం'", SYSTEM_INSTRUCTION)


class TestTelegramSettings(unittest.TestCase):
    """Unmocked test asserting Telegram settings and property exist on Settings."""

    def test_telegram_bot_token_property_exists_on_real_settings(self):
        from app.core.config import Settings, settings

        # Check property exists on Settings class
        self.assertTrue(hasattr(Settings, "telegram_bot_token"))
        # Check property exists on instantiated settings singleton
        self.assertTrue(hasattr(settings, "telegram_bot_token"))
        # Check field exists on Settings class
        self.assertIn("TELEGRAM_BOT_TOKEN", Settings.model_fields)
        # Check reading property does not raise AttributeError
        val = settings.telegram_bot_token
        self.assertTrue(val is None or isinstance(val, str))


class TestConflictingLocationAndEchoPrevention(unittest.IsolatedAsyncioTestCase):
    """
    Focused regression tests for conflicting location voice queries and echo prevention.
    Proves that:
    1. Input 'రేపు నిజామాబాద్, జెన్నారం మండలం, తోటపల్లి మండలం పిళ్ళాచ్చిలో వర్షం పడుతుందా?'
       is recognized as having conflicting locations and cannot echo back to the user.
    2. Intent is classified as weather_inquiry.
    3. The assistant asks a polite Telugu clarification question.
    4. Responses are delivered strictly via send_voice / reply_voice in Kaveri voice.
    5. When the user clarifies location, the pending query resumes and delivers weather data.
    """

    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_echo.db"
        self.session_repo = TelegramSessionRepository(db_path=self.db_path)

        self.mock_orchestrator = MagicMock(spec=ConversationOrchestrator)
        self.mock_voice_service = MagicMock(spec=VoicePipelineService)
        self.mock_voice_service.synthesize_speech = MagicMock(return_value=b"RIFF_test_wav")

        self.handler = TelegramHandler(
            orchestrator=self.mock_orchestrator,
            voice_service=self.mock_voice_service,
            session_repo=self.session_repo,
        )

        self.mock_context = MagicMock()
        self.mock_context.bot = MagicMock()

    async def asyncTearDown(self):
        self.temp_dir.cleanup()

    def _create_mock_voice_update(self, user_id: int, file_id: str = "voice_file_123", duration: int = 5, update_id: int = 1) -> Update:
        update = MagicMock(spec=Update)
        update.update_id = update_id

        user = MagicMock(spec=User)
        user.id = user_id
        update.effective_user = user

        chat = MagicMock(spec=Chat)
        chat.id = user_id
        update.effective_chat = chat

        voice_obj = MagicMock(spec=Voice)
        voice_obj.file_id = file_id
        voice_obj.duration = duration

        message = MagicMock(spec=Message)
        message.voice = voice_obj
        message.audio = None
        message.text = None
        message.reply_text = AsyncMock()
        message.reply_voice = AsyncMock()
        update.effective_message = message
        return update

    def test_has_conflicting_locations_and_extraction(self):
        from app.telegram.session import has_conflicting_locations, extract_location_from_text
        conflicting_query = "రేపు నిజామాబాద్, జెన్నారం మండలం, తోటపల్లి మండలం పిళ్ళాచ్చిలో వర్షం పడుతుందా?"
        self.assertTrue(has_conflicting_locations(conflicting_query))
        v, m, d, p = extract_location_from_text(conflicting_query)
        self.assertIsNone(v)
        self.assertIsNone(m)
        self.assertIsNone(d)
        self.assertIsNone(p)

        # Single clear location does not trigger conflict
        clean_query = "రేపు నిజామాబాద్ లో వర్షం పడుతుందా?"
        self.assertFalse(has_conflicting_locations(clean_query))
        v2, m2, d2, p2 = extract_location_from_text(clean_query)
        self.assertEqual(d2, "Nizamabad")

    def test_llm_safety_validator_rejects_echoed_farmer_question(self):
        from app.llm.safety import LLMSafetyValidator
        from app.llm.schemas import LLMReasoningRequest, LLMResponseSchema

        question = "రేపు నిజామాబాద్, జెన్నారం మండలం, తోటపల్లి మండలం పిళ్ళాచ్చిలో వర్షం పడుతుందా?"
        req = LLMReasoningRequest(farmer_question=question, language="Telugu")
        # LLM erroneously echoed the exact question
        out = LLMResponseSchema(
            intent="weather_inquiry",
            language="Telugu",
            response=question,
            abstain=False,
        )
        val = LLMSafetyValidator.validate(req, out)
        self.assertEqual(val.safety_status, "REJECTED")
        self.assertNotEqual(val.response, question)
        self.assertTrue(any("repeated or echoed" in viol for viol in val.safety_violations))

    def test_orchestrator_returns_clarification_for_conflicting_locations(self):
        from app.conversation.service import ConversationOrchestrator
        from app.conversation.schemas import ConversationRequest, GuestWeatherConsentEvent

        question = "రేపు నిజామాబాద్, జెన్నారం మండలం, తోటపల్లి మండలం పిళ్ళాచ్చిలో వర్షం పడుతుందా?"
        orchestrator = ConversationOrchestrator()
        req = ConversationRequest(
            question=question,
            language="te-IN",
            channel="telegram",
            guest_consent=GuestWeatherConsentEvent(
                consent_given=True,
                disclosure_version="v1.0",
                consent_timestamp="2026-11-10T00:00:00Z",
                channel="telegram",
            ),
        )
        resp = orchestrator.process_message(req)
        self.assertEqual(resp.intent, "weather_inquiry")
        self.assertEqual(resp.safety_reason, "LOCATION_PARAMETERS_REQUIRED")
        self.assertTrue(resp.is_abstention)
        self.assertNotEqual(resp.response_text, question)
        self.assertIn("మీరు వేర్వేరు ప్రాంతాల పేర్లు చెప్పారు.", resp.response_text)

    @patch("app.telegram.handlers.convert_ogg_opus_to_wav")
    @patch("app.telegram.handlers.convert_wav_bytes_to_ogg_opus")
    async def test_conflicting_location_voice_query_does_not_echo_transcript_and_asks_clarification(
        self, mock_to_ogg, mock_to_wav
    ):
        """Proves that a voice message with conflicting locations is answered with clarification via voice, not echoed."""
        user_id = 9101
        conflicting_question = "రేపు నిజామాబాద్, జెన్నారం మండలం, తోటపల్లి మండలం పిళ్ళాచ్చిలో వర్షం పడుతుందా?"

        # Pre-seed weather consent in session
        self.session_repo.set_consent(str(user_id), consent_given=True)

        update = self._create_mock_voice_update(user_id=user_id, duration=7, update_id=301)
        mock_file = MagicMock()
        mock_file.download_as_bytearray = AsyncMock(return_value=bytearray(b"raw_ogg_audio"))
        self.mock_context.bot.get_file = AsyncMock(return_value=mock_file)
        mock_to_wav.return_value = b"wav_audio"
        mock_to_ogg.return_value = (b"OggS_clarification_voice", 3.5)

        # Voice service transcribes question and returns clarification from orchestrator
        mock_voice_res = VoiceProcessingResponse(
            status="success",
            transcript=conflicting_question,
            detected_language="te-IN",
            intent="weather_inquiry",
            response_text="మీరు వేర్వేరు ప్రాంతాల పేర్లు చెప్పారు. మీకు ఏ ఊరు లేదా మండలం వాతావరణ వివరాలు కావాలో స్పష్టంగా చెప్తారా?",
            audio_base64=base64.b64encode(b"RIFF_clarification_wav").decode("ascii"),
            safety_status="ABSTAINED",
            safety_reason="LOCATION_PARAMETERS_REQUIRED",
            is_abstention=True,
            is_fallback_text_only=False,
        )
        self.mock_voice_service.process_audio_bytes.return_value = mock_voice_res

        await self.handler.handle_voice(update, self.mock_context)

        # Delivered exclusively via reply_voice
        update.effective_message.reply_voice.assert_called_once()
        update.effective_message.reply_text.assert_not_called()

        # Session stores pending query for resumption
        session = self.session_repo.get_session(str(user_id))
        self.assertEqual(session.pending_weather_query, conflicting_question)
        self.assertFalse(session.awaiting_consent)

    @patch("app.telegram.handlers.convert_ogg_opus_to_wav")
    @patch("app.telegram.handlers.convert_wav_bytes_to_ogg_opus")
    async def test_voice_clarification_resumes_pending_weather_query(
        self, mock_to_ogg, mock_to_wav
    ):
        """Proves that when farmer clarifies location via voice, pending weather query resumes and sends voice forecast."""
        user_id = 9102
        conflicting_question = "రేపు నిజామాబాద్, జెన్నారం మండలం, తోటపల్లి మండలం పిళ్ళాచ్చిలో వర్షం పడుతుందా?"

        # Session has consent and pending query awaiting location
        self.session_repo.set_consent(str(user_id), consent_given=True)
        self.session_repo.set_pending_query(str(user_id), conflicting_question, awaiting_consent=False)

        update = self._create_mock_voice_update(user_id=user_id, duration=4, update_id=302)
        mock_file = MagicMock()
        mock_file.download_as_bytearray = AsyncMock(return_value=bytearray(b"raw_ogg_audio"))
        self.mock_context.bot.get_file = AsyncMock(return_value=mock_file)
        mock_to_wav.return_value = b"wav_audio"
        mock_to_ogg.return_value = (b"OggS_forecast_voice", 4.0)

        # Farmer says: "నిజామాబాద్ జిల్లా"
        mock_voice_res = VoiceProcessingResponse(
            status="success",
            transcript="నిజామాబాద్ జిల్లా",
            detected_language="te-IN",
            intent="general_conversation",
            response_text="నిజామాబాద్ జిల్లా",
            audio_base64=None,
            safety_status="PASSED",
            is_abstention=False,
            is_fallback_text_only=True,
        )
        self.mock_voice_service.process_audio_bytes.return_value = mock_voice_res

        # Orchestrator responds to resumed weather query
        forecast_resp = ConversationResponse(
            intent="weather_inquiry",
            language="te-IN",
            response_text="రేపు నిజామాబాద్ జిల్లాలో వాన పడే అవకాశం లేదు , పొడిగా ఉంటుంది.",
            is_abstention=False,
            evidence_citations=[],
            safety_status="PASSED",
        )
        self.mock_orchestrator.process_message.return_value = forecast_resp

        await self.handler.handle_voice(update, self.mock_context)

        # Orchestrator was called to resume pending query
        self.mock_orchestrator.process_message.assert_called_once()
        conv_req = self.mock_orchestrator.process_message.call_args[0][0]
        self.assertEqual(conv_req.question, conflicting_question)
        self.assertEqual(conv_req.location.district, "Nizamabad")
        self.assertTrue(conv_req.location.location_confirmed)

        # Forecast delivered via reply_voice
        update.effective_message.reply_voice.assert_called_once()
        update.effective_message.reply_text.assert_not_called()

        # Pending query is cleared
        session = self.session_repo.get_session(str(user_id))
        self.assertIsNone(session.pending_weather_query)


class TestPart1HumanFriendlyConversations(unittest.IsolatedAsyncioTestCase):
    """Focused Part 1 tests for natural, human-friendly Telugu conversations and voice consistency."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_part1.db"
        from app.db.database import init_db
        init_db(self.db_path)

        from app.telegram.session import TelegramSessionRepository
        from app.telegram.handlers import TelegramHandler
        self.session_repo = TelegramSessionRepository(db_path=self.db_path)
        self.mock_orchestrator = MagicMock()
        self.mock_voice_service = MagicMock()
        self.handler = TelegramHandler(
            orchestrator=self.mock_orchestrator,
            voice_service=self.mock_voice_service,
            session_repo=self.session_repo,
        )
        self.mock_context = MagicMock()
        self.mock_context.bot.send_chat_action = AsyncMock()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_no_automatic_andi_prefix_in_templates_or_policy(self):
        """Ensure responses never automatically start with ',' and WhatsApp base instructions remain isolated."""
        from app.conversation.service import ConversationOrchestrator
        from app.llm.service import TELEGRAM_SYSTEM_INSTRUCTION, BASE_SYSTEM_INSTRUCTION
        from app.llm.safety import LLMSafetyValidator
        from app.llm.schemas import LLMReasoningRequest, LLMResponseSchema
        from app.telegram.handlers import (
            START_MESSAGE,
            GREETING_MESSAGE,
            DURATION_LIMIT_MESSAGE,
            FALLBACK_ERROR_MESSAGE,
            TELEGRAM_ABSTENTION_FALLBACK,
        )

        orchestrator = ConversationOrchestrator(db_path=self.db_path)
        req_tg = LLMReasoningRequest(farmer_question="ఏ మందు వేయాలి?", language="Telugu", channel="telegram")
        safety_abst = LLMSafetyValidator._create_safe_abstention(req_tg, LLMResponseSchema(intent="pest", language="Telugu", abstain=True, response="placeholder"), ["no_evidence"])

        templates = [
            START_MESSAGE,
            GREETING_MESSAGE,
            DURATION_LIMIT_MESSAGE,
            FALLBACK_ERROR_MESSAGE,
            TELEGRAM_ABSTENTION_FALLBACK,
            safety_abst.response,
            orchestrator._create_consent_required_abstention("te-IN", "weather_inquiry", channel="telegram").response_text,
            orchestrator._create_location_required_abstention("te-IN", "weather_inquiry", channel="telegram").response_text,
            orchestrator._create_conflicting_location_clarification("te-IN", channel="telegram").response_text,
            orchestrator._create_district_confirmation_required_response("te-IN", channel="telegram").response_text,
            orchestrator._create_weather_service_error_abstention("te-IN", "timeout", channel="telegram").response_text,
        ]
        for tpl in templates:
            self.assertFalse(
                tpl.strip().startswith("\u0c05\u0c02\u0c21\u0c3f"),
                f"Template must not automatically start with the removed honorific: {tpl}",
            )

        # Telegram and WhatsApp prompt policies remain isolated.
        self.assertNotIn("NEVER begin every sentence", BASE_SYSTEM_INSTRUCTION)
        self.assertNotIn("మీ పరిస్థితికి తగ్గట్టు మంచి సూచనలు చెప్పడానికి అడుగుతున్నాను", BASE_SYSTEM_INSTRUCTION)

    def test_natural_followup_questions_policy_and_framing(self):
        """Verify Telugu framing guidance includes helpful context-why explanations and single follow-up question."""
        from app.conversation.service import ConversationOrchestrator
        from app.llm.service import TELEGRAM_SYSTEM_INSTRUCTION

        self.assertIn("మీ పరిస్థితికి తగ్గట్టు మంచి సూచనలు చెప్పడానికి అడుగుతున్నాను", TELEGRAM_SYSTEM_INSTRUCTION)
        self.assertIn("Give useful, verified facts FIRST before asking any follow-up question", TELEGRAM_SYSTEM_INSTRUCTION)
        self.assertIn("ASK ONLY ONE PRIMARY QUESTION AT A TIME", TELEGRAM_SYSTEM_INSTRUCTION)

        orchestrator = ConversationOrchestrator(db_path=self.db_path)
        consent_resp = orchestrator._create_consent_required_abstention("te-IN", "weather_inquiry", channel="telegram")
        # Telegram consent message explains why naturally without stiff Sanskrit 'సమ్మతి'
        self.assertNotIn("సమ్మతి", consent_resp.response_text)
        self.assertIn("సరే అని చెప్పండి", consent_resp.response_text)

        # WhatsApp consent preserves original text
        wa_consent_resp = orchestrator._create_consent_required_abstention("te-IN", "weather_inquiry", channel="whatsapp")
        self.assertIn("సమ్మతి అవసరం", wa_consent_resp.response_text)

    def test_natural_conversational_endings_and_short_reply_rule(self):
        """Verify generic closing invitations are disabled."""
        from app.llm.service import TELEGRAM_SYSTEM_INSTRUCTION

        self.assertNotIn("ఇంకా ఏమైనా సందేహాలుంటే అడగండి", TELEGRAM_SYSTEM_INSTRUCTION)
        self.assertIn("generic closing lines", TELEGRAM_SYSTEM_INSTRUCTION)

    def test_no_repetitive_greetings_in_regular_replies(self):
        """Verify regular guidance/clarification responses avoid repeating 'నమస్తే'."""
        from app.conversation.service import ConversationOrchestrator
        from app.llm.service import TELEGRAM_SYSTEM_INSTRUCTION
        from app.telegram.handlers import TELEGRAM_ABSTENTION_FALLBACK

        self.assertIn("Avoid repeating greetings like 'నమస్తే' or 'హలో'", TELEGRAM_SYSTEM_INSTRUCTION)

        orchestrator = ConversationOrchestrator(db_path=self.db_path)
        non_greeting_replies = [
            TELEGRAM_ABSTENTION_FALLBACK,
            orchestrator._create_consent_required_abstention("te-IN", "weather_inquiry", channel="telegram").response_text,
            orchestrator._create_location_required_abstention("te-IN", "weather_inquiry", channel="telegram").response_text,
            orchestrator._create_conflicting_location_clarification("te-IN", channel="telegram").response_text,
        ]
        for reply in non_greeting_replies:
            self.assertNotIn("నమస్తే", reply)

    def test_voice_pronunciation_normalization_preserves_numeric_weather_facts(self):
        """Verify Telugu voice normalization expands abbreviations/units accurately without losing numbers or adding SSML."""
        from app.voice.service import VoicePipelineService, prepare_telugu_text_for_voice

        sample = "**నిజామాబాద్** వాతావరణం: ఉష్ణోగ్రత 28.8°C, వర్షం 12.5 mm, అవకాశం 85% — వివరాలు AO (AO) లేదా KVK ని అడగండి."
        spoken = prepare_telugu_text_for_voice(sample)

        # Numbers preserved verbatim
        self.assertIn("28.8", spoken)
        self.assertIn("12.5", spoken)
        self.assertIn("85", spoken)
        # Units expanded to natural Telugu words
        self.assertIn("28.8 డిగ్రీల సెల్సియస్", spoken)
        self.assertIn("12.5 మిల్లీమీటర్లు", spoken)
        self.assertIn("85 శాతం", spoken)
        # Acronyms expanded, redundant parenthetical (AO) dropped, markdown stripped, NO SSML
        self.assertIn("ఏఓ", spoken)
        self.assertIn("కేవీకే", spoken)
        self.assertNotIn("(AO)", spoken)
        self.assertNotIn("**", spoken)
        self.assertNotIn("<speak>", spoken)
        self.assertNotIn("<break", spoken)

        # Verify channel isolation inside VoicePipelineService._synthesize_speech
        mock_tts = MagicMock()
        mock_tts.synthesize.return_value = b"RIFF_wav"
        service = VoicePipelineService(stt_client=MagicMock(), tts_client=mock_tts, orchestrator=MagicMock())

        # Telegram Telugu applies voice normalization
        service.synthesize_speech("ఉష్ణోగ్రత 30°C, 10%", language="te-IN", channel="telegram")
        tg_sent_text = mock_tts.synthesize.call_args[1]["text"]
        self.assertIn("30 డిగ్రీల సెల్సియస్", tg_sent_text)
        self.assertIn("10 శాతం", tg_sent_text)

        # WhatsApp / default leaves text unaltered
        mock_tts.reset_mock()
        raw_wa = "ఉష్ణోగ్రత 30°C, 10%"
        service.synthesize_speech(raw_wa, language="te-IN", channel="whatsapp")
        self.assertEqual(mock_tts.synthesize.call_args[1]["text"], raw_wa)

    @patch("app.telegram.handlers.convert_ogg_opus_to_wav")
    @patch("app.telegram.handlers.convert_wav_bytes_to_ogg_opus")
    async def test_telegram_voice_and_text_response_consistency(self, mock_to_ogg, mock_to_wav):
        """Verify Telegram text and voice consent acknowledgment & weather replies deliver consistent messages."""
        from app.voice.schemas import VoiceProcessingResponse

        mock_to_wav.return_value = b"wav_bytes"
        mock_to_ogg.return_value = (b"OggS_voice_bytes", 2.0)

        # 1. Text unprompted consent grant without pending query
        txt_update = MagicMock()
        txt_update.update_id = 4101
        txt_update.effective_user = MagicMock(id=8801)
        txt_update.effective_message = MagicMock()
        txt_update.effective_message.text = "సమ్మతి ఇస్తున్నాను"
        txt_update.effective_message.reply_text = AsyncMock()
        await self.handler.handle_text(txt_update, self.mock_context)
        text_ack_sent = txt_update.effective_message.reply_text.call_args[0][0]

        # 2. Voice unprompted consent grant without pending query
        v_update = MagicMock()
        v_update.update_id = 4102
        v_update.effective_user = MagicMock(id=8802)
        v_update.effective_chat = MagicMock(id=8802)
        v_update.effective_message = MagicMock()
        v_update.effective_message.voice = MagicMock(file_id="f1", duration=2)
        v_update.effective_message.audio = None
        v_update.effective_message.reply_voice = AsyncMock()
        v_update.effective_message.reply_text = AsyncMock()

        mock_file = MagicMock()
        mock_file.download_as_bytearray = AsyncMock(return_value=bytearray(b"raw_ogg"))
        self.mock_context.bot.get_file = AsyncMock(return_value=mock_file)

        self.mock_voice_service.process_audio_bytes.return_value = VoiceProcessingResponse(
            status="success",
            transcript="సమ్మతి ఇస్తున్నాను",
            detected_language="te-IN",
            intent="general_conversation",
            response_text="",
            safety_status="PASSED",
        )
        captured_tts_texts = []
        def fake_synth(text, lang="te-IN", channel=None):
            captured_tts_texts.append((text, lang, channel))
            return b"RIFF_wav"
        self.mock_voice_service.synthesize_speech = fake_synth

        await self.handler.handle_voice(v_update, self.mock_context)

        self.assertEqual(len(captured_tts_texts), 1)
        voice_ack_sent, lang_used, channel_used = captured_tts_texts[0]
        self.assertEqual(text_ack_sent, voice_ack_sent)
        self.assertEqual(lang_used, "te-IN")
        self.assertEqual(channel_used, "telegram")
        v_update.effective_message.reply_voice.assert_called_once()
        v_update.effective_message.reply_text.assert_not_called()


class TestTelegramAudioConversion(unittest.TestCase):
    """Unit tests for Telegram audio conversion utilities (OGG Opus <-> WAV)."""

    def _generate_test_wav_bytes(self, duration_seconds: float = 1.0, sample_rate: int = 16000) -> bytes:
        import wave
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            num_frames = int(duration_seconds * sample_rate)
            wf.writeframes(b"\x00\x00" * num_frames)
        return buf.getvalue()

    def test_convert_wav_bytes_to_ogg_opus(self):
        from app.telegram.audio import convert_wav_bytes_to_ogg_opus
        wav_bytes = self._generate_test_wav_bytes(2.0)
        ogg_bytes, duration = convert_wav_bytes_to_ogg_opus(wav_bytes)

        self.assertIsNotNone(ogg_bytes)
        self.assertGreater(len(ogg_bytes), 0)
        self.assertTrue(ogg_bytes.startswith(b"OggS"))
        self.assertAlmostEqual(duration, 2.0, delta=0.5)

    def test_convert_ogg_opus_to_wav(self):
        from app.telegram.audio import convert_wav_bytes_to_ogg_opus, convert_ogg_opus_to_wav
        wav_bytes = self._generate_test_wav_bytes(1.0)
        ogg_bytes, _ = convert_wav_bytes_to_ogg_opus(wav_bytes)

        decoded_wav = convert_ogg_opus_to_wav(ogg_bytes)
        self.assertIsNotNone(decoded_wav)
        self.assertGreater(len(decoded_wav), 0)
        self.assertTrue(decoded_wav.startswith(b"RIFF"))
        self.assertIn(b"WAVE", decoded_wav[:12])

    def test_audio_cleanup_after_conversion(self):
        from app.telegram.audio import convert_wav_bytes_to_ogg_opus
        import os
        import tempfile
        wav_bytes = self._generate_test_wav_bytes(1.0)
        temp_dir = tempfile.gettempdir()
        files_before = set(os.listdir(temp_dir))

        ogg_bytes, _ = convert_wav_bytes_to_ogg_opus(wav_bytes)

        files_after = set(os.listdir(temp_dir))
        new_files = [f for f in files_after - files_before if f.endswith((".wav", ".ogg"))]
        self.assertEqual(len(new_files), 0)


if __name__ == "__main__":
    unittest.main()
