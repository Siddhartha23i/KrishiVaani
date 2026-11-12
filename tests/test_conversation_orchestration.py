"""
Unit and Integration Test Suite for KrishiVaani Text Conversation Orchestration — Phase 7.5.

Tests:
1. General agricultural question with zero approved evidence.
2. Crop recommendation request with zero approved evidence.
3. Scheme question with zero approved evidence.
4. Weather question with valid consent.
5. Weather question without consent.
6. Weather question without sufficient location.
7. Forecast information cannot independently trigger crop advice.
8. Approved, geographically applicable evidence reaches the LLM.
9. Pending and verified evidence never reaches the LLM.
10. Expired or geographically mismatched evidence is excluded.
11. Groq timeout or rate limit produces a safe response.
12. Invalid model output produces safe abstention.
13. Telugu question receives a Telugu response.
14. Hindi question receives a Hindi response.
15. Farmer context lookup failure is handled safely.
16. No database mutation or accidental farmer creation.
"""

import unittest
from pathlib import Path
import tempfile
import sqlite3
import shutil
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

from app.db.database import init_db, get_connection
from app.models.farmer import FarmerModel
from app.services.farmer_service import FarmerService
from app.weather.services.weather_service import WeatherService
from app.weather.schemas import (
    CurrentWeatherConditions,
    WeatherForecastResponse,
    DailyWeatherForecast,
    WeatherLocationInfo,
    FreshnessStatus,
)
from app.llm.knowledge_adapter import ApprovedKnowledgeAdapter
from app.llm.service import LLMReasoningService
from app.llm.providers.groq_provider import GroqProvider
from app.llm.safety import LLMSafetyValidator
from app.llm.schemas import (
    LLMReasoningRequest,
    LLMResponseSchema,
    ApprovedEvidenceItem,
    WeatherFactItem,
    FarmerContextSchema,
)
from app.llm.exceptions import (
    LLMTimeoutError,
    LLMRateLimitError,
    LLMMalformedResponseError,
)
from app.conversation.schemas import (
    ConversationRequest,
    ConversationResponse,
    LocationInput,
    GuestWeatherConsentEvent,
)
from app.conversation.service import (
    ConversationOrchestrator,
    normalize_language,
)
from app.conversation.intent import (
    classify_intent,
    is_weather_query,
    is_lightning_safety_query,
    INTENT_WEATHER_INQUIRY,
    INTENT_CROP_RECOMMENDATION,
    INTENT_GOVERNMENT_SCHEME,
    INTENT_PEST_DISEASE_INQUIRY,
    INTENT_FERTILIZER_GUIDANCE,
    INTENT_AGRICULTURAL_ADVICE,
)


class TestConversationOrchestration(unittest.TestCase):
    """Isolated unit tests for KrishiVaani conversation orchestration."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test_convo.db"
        init_db(self.db_path)

        self.farmer_service = FarmerService(db_path=self.db_path)
        self.knowledge_adapter = ApprovedKnowledgeAdapter(db_path=self.db_path)

        # Mock weather provider
        self.mock_weather_provider = MagicMock()
        self.weather_service = WeatherService(
            farmer_service=self.farmer_service,
            weatherapi_provider=self.mock_weather_provider,
            db_path=self.db_path,
        )

        # Mock Groq provider
        self.mock_groq_provider = MagicMock(spec=GroqProvider)
        self.mock_groq_provider.model_id = "openai/gpt-oss-120b"
        self.llm_service = LLMReasoningService(
            provider=self.mock_groq_provider,
            validator=LLMSafetyValidator(),
        )

        self.orchestrator = ConversationOrchestrator(
            farmer_service=self.farmer_service,
            weather_service=self.weather_service,
            knowledge_adapter=self.knowledge_adapter,
            llm_service=self.llm_service,
            db_path=self.db_path,
        )

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _insert_farmer(
        self,
        farmer_id="FARMER-TEST-001",
        village="Dharmasagar",
        mandal="Dharmasagar",
        district="Warangal",
        pin="506142",
        consent_weather=True,
        language="te-IN",
        consent_at="2026-11-08T00:00:00Z",
        disclosure_version="v1.0",
    ):
        conn = get_connection(self.db_path)
        with conn:
            conn.execute(
                """
                INSERT INTO farmers (
                    farmer_id, whatsapp_user_id, preferred_language, village_name,
                    mandal_name, district_name, pin_code, latitude, longitude,
                    location_source, location_confirmed, consent_given,
                    weather_provider_sharing_consent,
                    weather_provider_sharing_consent_at,
                    weather_provider_disclosure_version,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 17.98, 79.53, 'manual', 1, 1, ?, ?, ?, '2026-11-08', '2026-11-08')
                """,
                (
                    farmer_id, f"wa_{farmer_id}", language, village, mandal, district, pin,
                    1 if consent_weather else 0,
                    consent_at if consent_weather else None,
                    disclosure_version if consent_weather else None,
                ),
            )
        conn.close()

    def _insert_knowledge_source(
        self,
        source_id="SRC-PJTAU-001",
        publisher="PJTAU",
        document_title="PJTAU Agromet Advisory Bulletin",
    ):
        conn = get_connection(self.db_path)
        with conn:
            conn.execute(
                """
                INSERT INTO knowledge_sources (
                    source_id, publisher, document_title, source_url, source_type,
                    authority_status, published_at, created_at, updated_at
                ) VALUES (?, ?, ?, 'https://pjtau.edu.in/advisory.pdf', 'PJTAU_AGROMET_ADVISORY', 'verified_official', '2026-11-04', '2026-11-04', '2026-11-04')
                """,
                (source_id, publisher, document_title),
            )
        conn.close()

    def _insert_knowledge_item(
        self,
        knowledge_id,
        title,
        content,
        verification_status="approved",
        district="Warangal",
        crop_name="Groundnut",
        applicable_from="2026-11-01",
        applicable_until="2026-11-20",
    ):
        conn = get_connection(self.db_path)
        with conn:
            conn.execute(
                """
                INSERT INTO knowledge_items (
                    knowledge_id, category, knowledge_type, title, content,
                    language_code, translation_status, state, district,
                    crop_name, season, applicable_from, applicable_until,
                    is_permanent_reference, last_reviewed_at, review_cycle_days,
                    verification_status, retrieval_applicability_notes,
                    created_at, updated_at
                ) VALUES (
                    ?, 'crop_management', 'seasonal_advisory', ?, ?,
                    'te', 'human_verified', 'Telangana', ?,
                    ?, 'Yasangi', ?, ?,
                    0, NULL, 365,
                    ?, NULL,
                    '2026-11-04', '2026-11-04'
                )
                """,
                (knowledge_id, title, content, district, crop_name, applicable_from, applicable_until, verification_status),
            )
            conn.execute(
                """
                INSERT INTO knowledge_item_sources (item_id, source_id, reference_location, created_at)
                VALUES (?, 'SRC-PJTAU-001', 'Page 1, Table 1', '2026-11-04')
                """,
                (knowledge_id,),
            )
        conn.close()

    def _mock_weather_data(self, district="Warangal", temp_c=29.0, rain_mm=0.0):
        loc = WeatherLocationInfo(
            location_name=f"{district}, Telangana",
            region="Telangana",
            country="India",
            matched_district=district,
        )
        curr = CurrentWeatherConditions(
            source_name="WeatherAPI.com",
            source_url="https://www.weatherapi.com/",
            retrieved_at="2026-11-08T06:00:00Z",
            issued_at="2026-11-08T05:45:00Z",
            valid_from="2026-11-08T05:00:00Z",
            valid_until="2026-11-08T07:00:00Z",
            location=loc,
            attribution="Weather data provided by WeatherAPI.com",
            disclaimer="Weather estimate disclaimer.",
            temperature_c=temp_c,
            precipitation_mm=rain_mm,
            condition_text="Sunny",
        )
        forecast = WeatherForecastResponse(
            source_name="WeatherAPI.com",
            source_url="https://www.weatherapi.com/",
            retrieved_at="2026-11-08T06:00:00Z",
            issued_at="2026-11-08T05:45:00Z",
            valid_from="2026-11-08T00:00:00Z",
            valid_until="2026-11-10T23:59:59Z",
            days_count=3,
            location=loc,
            attribution="Weather data provided by WeatherAPI.com",
            disclaimer="Weather estimate disclaimer.",
            forecast_days=[
                DailyWeatherForecast(date="2026-11-08", max_temp_c=31.0, min_temp_c=21.0, total_precipitation_mm=0.0, condition_text="Clear"),
                DailyWeatherForecast(date="2026-11-09", max_temp_c=30.0, min_temp_c=20.0, total_precipitation_mm=0.0, condition_text="Partly cloudy"),
                DailyWeatherForecast(date="2026-11-10", max_temp_c=29.0, min_temp_c=19.0, total_precipitation_mm=0.0, condition_text="Sunny"),
            ],
        )
        self.mock_weather_provider.get_current_weather.return_value = curr
        self.mock_weather_provider.get_forecast.return_value = forecast

    @staticmethod
    def _make_llm_response(
        intent="general_conversation",
        language="Telugu",
        response="సమాధానం",
        abstain=False,
        required_information=None,
        supported_facts=None,
        unsupported_questions=None,
        evidence_citations=None,
    ) -> LLMResponseSchema:
        return LLMResponseSchema(
            intent=intent,
            language=language,
            response=response,
            abstain=abstain,
            required_information=required_information or [],
            supported_facts=supported_facts or [],
            unsupported_questions=unsupported_questions or [],
            evidence_citations=evidence_citations or [],
            model_id="openai/gpt-oss-120b",
            safety_status="UNVERIFIED",
        )

    # --- Test 1: General Agricultural Question with Zero Approved Evidence ---
    def test_general_agricultural_question_zero_approved_evidence(self):
        self.mock_groq_provider.generate_completion.return_value = self._make_llm_response(
            intent="agricultural_advice",
            language="Telugu",
            required_information=["Soil type", "Specific crop"],
            supported_facts=[],
            unsupported_questions=["When should I irrigate?"],
            abstain=True,
            response="ఖచ్చితమైన వ్యవసాయ ఆధారాలు అందుబాటులో లేవు. దయచేసి మండల వ్యవసాయ అధికారిని సంప్రదించండి.",
            evidence_citations=[],
        )

        req = ConversationRequest(
            question="పొలానికి నీరు ఎప్పుడు పెట్టాలి?",
            language="te-IN",
        )
        res = self.orchestrator.process_message(req)

        self.assertTrue(res.is_abstention)
        self.assertEqual(res.language, "te-IN")
        self.assertEqual(len(res.evidence_citations), 0)
        self.assertIn("వ్యవసాయ అధికారిని", res.response_text)

    # --- Test 2: Crop Recommendation Request with Zero Approved Evidence ---
    def test_crop_recommendation_request_zero_approved_evidence(self):
        # Even if the LLM attempts to fabricate a crop, LLMSafetyValidator must block it!
        self.mock_groq_provider.generate_completion.return_value = self._make_llm_response(
            intent="crop_recommendation",
            language="Telugu",
            required_information=[],
            supported_facts=[],
            unsupported_questions=[],
            abstain=False,
            response="మీరు మొక్కజొన్న లేదా పత్తి పంట వేయండి.",  # Unapproved actionable crop recommendation!
            evidence_citations=[],
        )

        req = ConversationRequest(
            question="ఈ కాలంలో ఏ పంట వేయాలి?",
            language="te-IN",
        )
        res = self.orchestrator.process_message(req)

        self.assertTrue(res.is_abstention)
        self.assertEqual(res.safety_status, "REJECTED")
        self.assertIn("crop recommendation", res.safety_reason.lower())
        self.assertEqual(len(res.evidence_citations), 0)

    # --- Test 3: Scheme Question with Zero Approved Evidence ---
    def test_scheme_question_zero_approved_evidence(self):
        self.mock_groq_provider.generate_completion.return_value = self._make_llm_response(
            intent="government_scheme",
            language="English",
            required_information=[],
            supported_facts=[],
            unsupported_questions=["How much is Rythu Bandhu?"],
            abstain=True,
            response="Official scheme details are currently not available in approved evidence. Please visit the local agriculture office.",
            evidence_citations=[],
        )

        req = ConversationRequest(
            question="How much financial assistance do I get from Rythu Bandhu?",
            language="en-IN",
        )
        res = self.orchestrator.process_message(req)

        self.assertTrue(res.is_abstention)
        self.assertEqual(res.intent, INTENT_GOVERNMENT_SCHEME)
        self.assertEqual(len(res.evidence_citations), 0)

    # --- Test 4: Weather Question with Valid Consent ---
    def test_weather_question_with_valid_consent(self):
        farmer_id = "FARMER-W-001"
        self._insert_farmer(farmer_id=farmer_id, district="Karimnagar", consent_weather=True)
        self._mock_weather_data(district="Karimnagar", temp_c=28.5)

        self.mock_groq_provider.generate_completion.return_value = self._make_llm_response(
            intent="weather_inquiry",
            language="Telugu",
            required_information=[],
            supported_facts=["Temperature is 28.5 C in Karimnagar."],
            unsupported_questions=[],
            abstain=False,
            response="కరీంనగర్‌లో ప్రస్తుత ఉష్ణోగ్రత 28.5 డిగ్రీల సెల్సియస్ మరియు వాతావరణం పొడిగా ఉంది.",
            evidence_citations=[],
        )

        req = ConversationRequest(
            question="కరీంనగర్‌లో ఈరోజు వర్షం పడుతుందా?",
            language="te-IN",
            farmer_id=farmer_id,
        )
        res = self.orchestrator.process_message(req)

        self.assertFalse(res.is_abstention)
        self.assertEqual(res.intent, INTENT_WEATHER_INQUIRY)
        self.assertIsNotNone(res.weather_metadata)
        self.assertEqual(res.weather_metadata.source_name, "WeatherAPI.com")
        self.assertTrue(res.weather_metadata.is_grid_estimate)
        self.assertIn("కరీంనగర్‌లో", res.response_text)

    # --- Test 5: Weather Question Without Consent ---
    def test_weather_question_without_consent(self):
        farmer_id = "FARMER-NO-CONSENT"
        self._insert_farmer(farmer_id=farmer_id, district="Warangal", consent_weather=False)

        req = ConversationRequest(
            question="What is the weather forecast for my village?",
            language="en-IN",
            farmer_id=farmer_id,
        )
        res = self.orchestrator.process_message(req)

        # WeatherAPI must NEVER be called!
        self.mock_weather_provider.get_current_weather.assert_not_called()
        self.mock_weather_provider.get_forecast.assert_not_called()

        self.assertTrue(res.is_abstention)
        self.assertEqual(res.safety_reason, "WEATHER_LOCATION_SHARING_CONSENT_REQUIRED")
        self.assertIn("consent to share your location", res.response_text)

    # --- Test 6: Weather Question Without Sufficient Location ---
    def test_weather_question_without_sufficient_location(self):
        # Caller gives explicit guest consent but no farmer profile and no location details
        guest_consent = GuestWeatherConsentEvent(
            consent_given=True,
            disclosure_version="v1.0",
            consent_timestamp="2026-11-08T10:00:00Z",
            channel="whatsapp_text",
        )
        req = ConversationRequest(
            question="What is the weather today?",
            language="en-IN",
            guest_consent=guest_consent,
        )
        res = self.orchestrator.process_message(req)

        self.mock_weather_provider.get_current_weather.assert_not_called()
        self.assertTrue(res.is_abstention)
        self.assertEqual(res.safety_reason, "LOCATION_PARAMETERS_REQUIRED")
        self.assertIn("Please specify your district", res.response_text)

    # --- Test 7: Forecast Information Cannot Independently Trigger Crop Advice ---
    def test_forecast_alone_cannot_trigger_crop_advice(self):
        farmer_id = "FARMER-W-002"
        self._insert_farmer(farmer_id=farmer_id, district="Nalgonda", consent_weather=True)
        self._mock_weather_data(district="Nalgonda", rain_mm=25.0)

        # Mock LLM trying to recommend planting based only on weather forecast!
        self.mock_groq_provider.generate_completion.return_value = self._make_llm_response(
            intent="crop_recommendation",
            language="Telugu",
            required_information=[],
            supported_facts=["25 mm rain forecast"],
            unsupported_questions=[],
            abstain=False,
            response="వర్షం పడుతుంది కాబట్టి మీరు వెంటనే జొన్న పంట వేయండి.",  # Sowing advice without approved crop evidence!
            evidence_citations=[],
        )

        req = ConversationRequest(
            question="వర్ష సూచన ఉంది కదా, నేను ఏ పంట వేసుకోవచ్చు?",
            language="te-IN",
            farmer_id=farmer_id,
        )
        res = self.orchestrator.process_message(req)

        # Safety validator must block this and reject the advice!
        self.assertTrue(res.is_abstention)
        self.assertEqual(res.safety_status, "REJECTED")
        self.assertIn("weather forecast alone cannot trigger crop recommendations", res.safety_reason.lower())

    # --- Test 8: Approved, Geographically Applicable Evidence Reaches the LLM ---
    def test_approved_evidence_reaches_llm(self):
        self._insert_knowledge_source()
        kid = "KNOW-APP-001"
        self._insert_knowledge_item(
            knowledge_id=kid,
            title="Groundnut Sowing Guidance",
            content="Sow TAG-24 groundnut between Oct 15 and Nov 20 in Warangal district.",
            verification_status="approved",
            district="Warangal",
            crop_name="Groundnut",
        )

        captured_request = {}

        def fake_completion(messages, json_mode=True):
            user_msg = messages[-1]["content"]
            captured_request["user_msg"] = user_msg
            return self._make_llm_response(
                intent="agricultural_advice",
                language="English",
                required_information=[],
                supported_facts=["Sow TAG-24 groundnut between Oct 15 and Nov 20."],
                unsupported_questions=[],
                abstain=False,
                response="For Warangal district, you can sow TAG-24 groundnut up to November 20.",
                evidence_citations=[kid],
            )

        self.mock_groq_provider.generate_completion.side_effect = fake_completion

        req = ConversationRequest(
            question="When can I sow groundnut?",
            language="en-IN",
            location=LocationInput(district="Warangal"),
            farmer_context=FarmerContextSchema(crop_name="Groundnut"),
        )
        res = self.orchestrator.process_message(req)

        self.assertIn(kid, captured_request["user_msg"])
        self.assertIn("TAG-24", captured_request["user_msg"])
        self.assertFalse(res.is_abstention)
        self.assertEqual(res.evidence_citations, [kid])
        self.assertEqual(res.safety_status, "PASSED")

    # --- Test 9: Pending and Verified Evidence Never Reaches the LLM ---
    def test_pending_and_verified_evidence_never_reaches_llm(self):
        self._insert_knowledge_source()
        self._insert_knowledge_item(
            knowledge_id="KNOW-PEND-001",
            title="Pending Item",
            content="Pending secret guidance.",
            verification_status="pending_verification",
            district="Warangal",
        )
        self._insert_knowledge_item(
            knowledge_id="KNOW-VERI-001",
            title="Verified Item",
            content="Verified secret guidance.",
            verification_status="verified",
            district="Warangal",
        )

        captured_evidence_count = {}

        def fake_completion(messages, json_mode=True):
            user_msg = messages[-1]["content"]
            captured_evidence_count["found_pend"] = "KNOW-PEND-001" in user_msg
            captured_evidence_count["found_veri"] = "KNOW-VERI-001" in user_msg
            return self._make_llm_response(
                intent="agricultural_advice",
                language="English",
                required_information=[],
                supported_facts=[],
                unsupported_questions=["Any advice?"],
                abstain=True,
                response="No approved evidence is available.",
                evidence_citations=[],
            )

        self.mock_groq_provider.generate_completion.side_effect = fake_completion

        req = ConversationRequest(
            question="Do you have any new advice for Warangal?",
            language="en-IN",
            location=LocationInput(district="Warangal"),
        )
        res = self.orchestrator.process_message(req)

        self.assertFalse(captured_evidence_count["found_pend"])
        self.assertFalse(captured_evidence_count["found_veri"])
        self.assertTrue(res.is_abstention)

    # --- Test 10: Expired or Geographically Mismatched Evidence is Excluded ---
    def test_expired_or_mismatched_evidence_excluded(self):
        self._insert_knowledge_source()
        past_date = (date.today() - timedelta(days=5)).isoformat()
        # Expired item in Khammam
        self._insert_knowledge_item(
            knowledge_id="KNOW-EXP-001",
            title="Expired Khammam Item",
            content="Expired advice.",
            verification_status="approved",
            district="Khammam",
            applicable_until=past_date,
        )
        # Geographically mismatched item in Adilabad
        self._insert_knowledge_item(
            knowledge_id="KNOW-ADIL-001",
            title="Adilabad Specific Item",
            content="Adilabad advice.",
            verification_status="approved",
            district="Adilabad",
        )

        captured_user_msg = {}

        def fake_completion(messages, json_mode=True):
            captured_user_msg["text"] = messages[-1]["content"]
            return self._make_llm_response(
                intent="agricultural_advice",
                language="English",
                required_information=[],
                supported_facts=[],
                unsupported_questions=[],
                abstain=True,
                response="No approved evidence available for Khammam.",
                evidence_citations=[],
            )

        self.mock_groq_provider.generate_completion.side_effect = fake_completion

        # Query for Khammam farmer
        req = ConversationRequest(
            question="Any advice for Khammam?",
            language="en-IN",
            location=LocationInput(district="Khammam"),
        )
        res = self.orchestrator.process_message(req)

        self.assertNotIn("KNOW-EXP-001", captured_user_msg["text"])
        self.assertNotIn("KNOW-ADIL-001", captured_user_msg["text"])
        self.assertTrue(res.is_abstention)

    # --- Test 11: Groq Timeout or Rate Limit Produces a Safe Response ---
    def test_groq_timeout_produces_safe_response(self):
        self.mock_groq_provider.generate_completion.side_effect = LLMTimeoutError("Groq request timed out after 5.0s")

        req = ConversationRequest(
            question="What is the fertilizer schedule for groundnut?",
            language="te-IN",
        )
        res = self.orchestrator.process_message(req)

        self.assertTrue(res.is_abstention)
        self.assertEqual(res.safety_status, "ABSTAINED")
        self.assertIn("సాంకేతిక సమస్య", res.response_text)
        self.assertEqual(len(res.evidence_citations), 0)

    # --- Test 12: Invalid Model Output Produces Safe Abstention ---
    def test_invalid_model_output_produces_safe_abstention(self):
        self.mock_groq_provider.generate_completion.side_effect = LLMMalformedResponseError("Unparseable JSON from Groq")

        req = ConversationRequest(
            question="Can you help me with cotton yield?",
            language="en-IN",
        )
        res = self.orchestrator.process_message(req)

        self.assertTrue(res.is_abstention)
        self.assertEqual(res.safety_status, "ABSTAINED")
        self.assertIn("technical service limitation", res.response_text)

    # --- Test 13: Telugu Question Receives a Telugu Response ---
    def test_telugu_question_receives_telugu_response(self):
        self.mock_groq_provider.generate_completion.return_value = self._make_llm_response(
            intent="general_conversation",
            language="Telugu",
            required_information=[],
            supported_facts=[],
            unsupported_questions=[],
            abstain=False,
            response="నమస్కారం! నేను కృషివాణి సహాయకుడిని. మీకు ఎలా సహాయపడగలను?",
            evidence_citations=[],
        )

        req = ConversationRequest(
            question="నమస్కారం, మీరు ఎవరు?",
            language="te-IN",
        )
        res = self.orchestrator.process_message(req)

        self.assertEqual(res.language, "te-IN")
        self.assertIn("నమస్కారం", res.response_text)

    # --- Test 14: Hindi Question Receives a Hindi Response ---
    def test_hindi_question_receives_hindi_response(self):
        self.mock_groq_provider.generate_completion.return_value = self._make_llm_response(
            intent="general_conversation",
            language="Hindi",
            required_information=[],
            supported_facts=[],
            unsupported_questions=[],
            abstain=False,
            response="नमस्ते! मैं कृषिवाणी सहायक हूँ। मैं आपकी क्या मदद कर सकता हूँ?",
            evidence_citations=[],
        )

        req = ConversationRequest(
            question="नमस्ते, आप कौन हैं?",
            language="hi-IN",
        )
        res = self.orchestrator.process_message(req)

        self.assertEqual(res.language, "hi-IN")
        self.assertIn("नमस्ते", res.response_text)

    # --- Test 15: Farmer Context Lookup Failure is Handled Safely ---
    def test_farmer_lookup_failure_handled_safely(self):
        self.mock_groq_provider.generate_completion.return_value = self._make_llm_response(
            intent="general_conversation",
            language="Telugu",
            required_information=[],
            supported_facts=[],
            unsupported_questions=[],
            abstain=False,
            response="నమస్కారం! నేను మీకు సహాయం చేయడానికి సిద్ధంగా ఉన్నాను.",
            evidence_citations=[],
        )

        # Non-existent farmer ID
        req = ConversationRequest(
            question="హలో",
            language="te-IN",
            farmer_id="NON-EXISTENT-FARMER-9999",
        )
        # Must not raise an exception!
        res = self.orchestrator.process_message(req)
        self.assertIsNotNone(res.response_text)

    # --- Test 16: No Database Mutation or Accidental Farmer Creation ---
    def test_no_database_mutation(self):
        # Insert 1 initial farmer
        self._insert_farmer(farmer_id="ORIGINAL-FARMER-1")
        self._insert_knowledge_source()
        self._insert_knowledge_item("KNOW-1", "T", "C")

        conn = get_connection(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM farmers")
        initial_farmers = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM knowledge_items")
        initial_items = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM knowledge_verification_audit")
        initial_audits = cur.fetchone()[0]
        conn.close()

        # Run 5 diverse conversation turns
        self.mock_groq_provider.generate_completion.return_value = self._make_llm_response(
            intent="general_conversation",
            language="Telugu",
            required_information=[],
            supported_facts=[],
            unsupported_questions=[],
            abstain=False,
            response="స్పందన",
            evidence_citations=[],
        )

        requests = [
            ConversationRequest(question="ఏ పంట వేయాలి?", language="te-IN"),
            ConversationRequest(question="వర్షం ఎంత?", language="te-IN", location=LocationInput(weather_sharing_consent=False)),
            ConversationRequest(question="How are you?", language="en-IN", farmer_id="UNKNOWN-FARMER"),
            ConversationRequest(question="Rythu Bandhu status?", language="en-IN"),
            ConversationRequest(question="నమస్కారం", language="te-IN", farmer_id="ORIGINAL-FARMER-1"),
        ]

        for req in requests:
            self.orchestrator.process_message(req)

        # Confirm exact counts remain unchanged
        conn = get_connection(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM farmers")
        final_farmers = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM knowledge_items")
        final_items = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM knowledge_verification_audit")
        final_audits = cur.fetchone()[0]
        conn.close()

        self.assertEqual(initial_farmers, final_farmers)
        self.assertEqual(initial_items, final_items)
        self.assertEqual(initial_audits, final_audits)

    # --- Test 17: Fertilizer & Nutrient Intent Classification Across Languages ---
    def test_fertilizer_intent_classification_languages(self):
        # 1. Exact query from Phase 7.5 report
        q_phase75 = "What is the recommended fertilizer dosage for cotton in Adilabad?"
        self.assertEqual(classify_intent(q_phase75), INTENT_FERTILIZER_GUIDANCE)

        # 2. English fertilizer queries
        en_queries = [
            "What is the recommended fertilizer dosage for cotton in Adilabad?",
            "How much NPK fertilizer should I apply for paddy?",
            "What is the urea dosage per acre for maize?",
            "How can I test the soil fertility of my field?",
            "What is the nutrient management schedule for chilli?",
        ]
        for q in en_queries:
            self.assertEqual(classify_intent(q), INTENT_FERTILIZER_GUIDANCE, f"Failed for English query: {q}")

        # 3. Telugu fertilizer queries
        te_queries = [
            "పత్తి పంటకు యూరియా ఎంత వేయాలి?",
            "వరిలో ఎరువుల మోతాదు ఎంత?",
            "ఎన్పీకే ఎరువులు ఎప్పుడు వేయాలి?",
            "నేల సారం పరీక్ష ఎలా చేయించాలి?",
            "పంటకు ఎంత ఎరువు వేయాలి?",
        ]
        for q in te_queries:
            self.assertEqual(classify_intent(q), INTENT_FERTILIZER_GUIDANCE, f"Failed for Telugu query: {q}")

        # 4. Hindi fertilizer queries
        hi_queries = [
            "कपास के लिए खाद की मात्रा कितनी है?",
            "यूरिया और डीएपी कब डालना चाहिए?",
            "मिट्टी की उर्वरता की जांच कैसे करें?",
        ]
        for q in hi_queries:
            self.assertEqual(classify_intent(q), INTENT_FERTILIZER_GUIDANCE, f"Failed for Hindi query: {q}")

    # --- Test 18: Pest & Disease and Crop Recommendation Queries Remain Distinct ---
    def test_distinct_intent_pest_disease_and_crop(self):
        # Pest & Disease queries must NOT be classified as fertilizer or crop
        pest_queries = [
            "పత్తిలో గులాబీ రంగు పురుగు నివారణ ఎలా?",
            "వరిలో కాండం తొలిచే పురుగు నివారణకు ఏ పురుగుమందు వాడాలి?",
            "How to control pink bollworm in cotton?",
            "What is the pesticide spray dosage for aphids in chilli?",
            "कपास में कीट नियंत्रण के लिए क्या उपाय करें?",
        ]
        for q in pest_queries:
            self.assertEqual(classify_intent(q), INTENT_PEST_DISEASE_INQUIRY, f"Failed for pest query: {q}")

        # Crop Recommendation queries must NOT be classified as fertilizer or pest
        crop_queries = [
            "ఈ వానాకాలంలో ఏ పంట వేస్తే లాభం?",
            "What crop should I plant in Warangal in Kharif?",
            "Which crop is suitable for black soil?",
            "खरीफ में कौन सी फसल बोनी चाहिए?",
        ]
        for q in crop_queries:
            self.assertEqual(classify_intent(q), INTENT_CROP_RECOMMENDATION, f"Failed for crop query: {q}")

    # --- Test 19: Fertilizer Question with Zero Approved Evidence Produces Safe Abstention ---
    def test_fertilizer_question_zero_approved_evidence_abstains(self):
        # Even when intent is classified as fertilizer_guidance, with 0 approved evidence it must abstain
        self.mock_groq_provider.generate_completion.return_value = self._make_llm_response(
            intent=INTENT_FERTILIZER_GUIDANCE,
            language="English",
            required_information=["Soil health card", "Crop stage"],
            supported_facts=[],
            unsupported_questions=["What is the fertilizer dosage for cotton?"],
            abstain=True,
            response="Official fertilizer recommendations for cotton in Adilabad are not available in approved evidence.",
            evidence_citations=[],
        )

        req = ConversationRequest(
            question="What is the recommended fertilizer dosage for cotton in Adilabad?",
            language="en-IN",
        )
        res = self.orchestrator.process_message(req)

        self.assertEqual(res.intent, INTENT_FERTILIZER_GUIDANCE)
        self.assertTrue(res.is_abstention)
        self.assertEqual(len(res.evidence_citations), 0)

    # --- Test 20: Fertilizer Question with Unsupported Chemical Dosage is Blocked by Safety ---
    def test_fertilizer_unsupported_dosage_blocked_by_safety(self):
        # If the LLM generates an unapproved chemical dosage, LLMSafetyValidator must REJECT it
        self.mock_groq_provider.generate_completion.return_value = self._make_llm_response(
            intent=INTENT_FERTILIZER_GUIDANCE,
            language="English",
            required_information=[],
            supported_facts=[],
            unsupported_questions=[],
            abstain=False,
            response="Apply 50 kg urea and 25 kg DAP per acre at 30 days after sowing.",
            evidence_citations=[],
        )

        req = ConversationRequest(
            question="What is the recommended fertilizer dosage for cotton in Adilabad?",
            language="en-IN",
        )
        res = self.orchestrator.process_message(req)

        self.assertTrue(res.is_abstention)
        self.assertEqual(res.safety_status, "REJECTED")
        self.assertIn("dosage", res.safety_reason.lower())

    # --- Test 21: Weather Consent Audit — All 7 Provenance Scenarios ---
    def test_weather_consent_all_seven_scenarios(self):
        # Scenario 1: Existing registered farmer with affirmative consent and valid metadata -> PERMITTED
        f_id_valid = "FARMER-CONSENT-VALID"
        self._insert_farmer(
            farmer_id=f_id_valid,
            district="Karimnagar",
            consent_weather=True,
            consent_at="2026-11-08T06:00:00Z",
            disclosure_version="v1.0",
        )
        self._mock_weather_data(district="Karimnagar", temp_c=30.0)
        self.mock_groq_provider.generate_completion.return_value = self._make_llm_response(
            intent="weather_inquiry", language="English", response="Weather in Karimnagar is clear.",
        )
        req1 = ConversationRequest(question="Weather in Karimnagar?", language="en-IN", farmer_id=f_id_valid)
        res1 = self.orchestrator.process_message(req1)
        self.assertFalse(res1.is_abstention)
        self.assertEqual(res1.safety_status, "PASSED")
        self.mock_weather_provider.get_current_weather.assert_called()

        # Reset mock
        self.mock_weather_provider.get_current_weather.reset_mock()
        self.mock_weather_provider.get_forecast.reset_mock()
        self.mock_weather_provider.get_forecast.reset_mock()

        # Scenario 2: Existing registered farmer without consent (or missing metadata) -> BLOCKED
        f_id_no_consent = "FARMER-NO-CONSENT-2"
        self._insert_farmer(farmer_id=f_id_no_consent, district="Warangal", consent_weather=False)
        req2 = ConversationRequest(question="Weather forecast?", language="en-IN", farmer_id=f_id_no_consent)
        res2 = self.orchestrator.process_message(req2)
        self.assertTrue(res2.is_abstention)
        self.assertEqual(res2.safety_reason, "WEATHER_LOCATION_SHARING_CONSENT_REQUIRED")
        self.mock_weather_provider.get_current_weather.assert_not_called()

        # Scenario 3: A named place is a direct WeatherAPI lookup and needs no consent.
        req3 = ConversationRequest(
            question="What is the weather in Nizamabad?",
            language="en-IN",
            location=LocationInput(district="Nizamabad"),
        )
        res3 = self.orchestrator.process_message(req3)
        self.assertFalse(res3.is_abstention)
        self.mock_weather_provider.get_current_weather.assert_called()
        self.assertEqual(
            self.mock_weather_provider.get_current_weather.call_args.kwargs["query"],
            "Nizamabad",
        )
        self.mock_weather_provider.get_current_weather.reset_mock()
        self.mock_weather_provider.get_forecast.reset_mock()

        # Scenario 4: Guest with only caller-supplied boolean LocationInput(weather_sharing_consent=True) -> BLOCKED
        req4 = ConversationRequest(
            question="Weather today?",
            language="en-IN",
            location=LocationInput(district="Adilabad", weather_sharing_consent=True),
        )
        res4 = self.orchestrator.process_message(req4)
        self.assertTrue(res4.is_abstention)
        self.assertEqual(res4.safety_reason, "WEATHER_LOCATION_SHARING_CONSENT_REQUIRED")
        self.mock_weather_provider.get_current_weather.assert_not_called()

        # Scenario 5: Guest with valid explicit GuestWeatherConsentEvent -> PERMITTED
        self._mock_weather_data(district="Adilabad", temp_c=31.0)
        self.mock_groq_provider.generate_completion.return_value = self._make_llm_response(
            intent="weather_inquiry", language="English", response="Weather in Adilabad is warm.",
        )
        gc_valid = GuestWeatherConsentEvent(
            consent_given=True,
            disclosure_version="v1.0",
            consent_timestamp="2026-11-08T10:30:00Z",
            channel="whatsapp_text",
            presented_notice="Disclosure notice",
        )
        req5 = ConversationRequest(
            question="Weather in Adilabad today?",
            language="en-IN",
            location=LocationInput(district="Adilabad"),
            guest_consent=gc_valid,
        )
        res5 = self.orchestrator.process_message(req5)
        self.assertFalse(res5.is_abstention)
        self.mock_weather_provider.get_current_weather.assert_called()

        # Reset mock
        self.mock_weather_provider.get_current_weather.reset_mock()
        self.mock_weather_provider.get_forecast.reset_mock()

        # Scenario 6: Weather provider is never called when consent is invalid
        # Verified across Scenarios 2, 3, 4 and explicitly tested with invalid guest consent event:
        gc_invalid = GuestWeatherConsentEvent(
            consent_given=False,  # explicit non-consent
            disclosure_version="v1.0",
            consent_timestamp="2026-11-08T10:30:00Z",
            channel="whatsapp_text",
        )
        req6 = ConversationRequest(
            question="Weather update?",
            language="en-IN",
            location=LocationInput(district="Warangal"),
            guest_consent=gc_invalid,
        )
        res6 = self.orchestrator.process_message(req6)
        self.assertTrue(res6.is_abstention)
        self.assertEqual(res6.safety_reason, "WEATHER_LOCATION_SHARING_CONSENT_REQUIRED")
        self.mock_weather_provider.get_current_weather.assert_not_called()
        self.mock_weather_provider.get_forecast.assert_not_called()

        # Scenario 7: Location sharing alone (latitude, longitude, district) never implies consent
        req7 = ConversationRequest(
            question="Will it rain today?",
            language="en-IN",
            location=LocationInput(
                latitude=17.98,
                longitude=79.53,
                district="Warangal",
                village="Dharmasagar",
            ),
        )
        res7 = self.orchestrator.process_message(req7)
        self.assertTrue(res7.is_abstention)
        self.assertEqual(res7.safety_reason, "WEATHER_LOCATION_SHARING_CONSENT_REQUIRED")
        self.mock_weather_provider.get_current_weather.assert_not_called()

    # --- Test 22: Safety Validation Execution and Latency Measurement Audit ---
    def test_safety_validation_latency_and_execution_audit(self):
        # When LLM runs, safety validation must execute and record latency > 0.0 ms
        self._insert_farmer(farmer_id="FARMER-SAFE-001")
        self.mock_groq_provider.generate_completion.return_value = self._make_llm_response(
            intent="general_conversation",
            language="Telugu",
            response="నమస్కారం! ఎలా ఉన్నారు?",
        )

        req = ConversationRequest(question="నమస్కారం, పత్తి పంట ఎలా చూసుకోవాలి?", language="te-IN", farmer_id="FARMER-SAFE-001")
        res = self.orchestrator.process_message(req)

        self.assertEqual(res.safety_validation_status, "PASSED")
        self.assertIn("safety_validation_ms", res.latency_breakdown_ms)
        val_ms = res.latency_breakdown_ms["safety_validation_ms"]
        self.assertIsNotNone(val_ms)
        self.assertIsInstance(val_ms, float)
        self.assertGreaterEqual(val_ms, 0.0)
        self.assertEqual(res.latency_breakdown_ms["safety_validation_status"], "PASSED")

        # When request early-abtains (e.g. consent missing), safety validation is NOT_RUN
        req_early = ConversationRequest(question="Weather forecast?", language="en-IN")
        res_early = self.orchestrator.process_message(req_early)

        self.assertEqual(res_early.safety_validation_status, "NOT_RUN")
        self.assertIsNone(res_early.latency_breakdown_ms.get("safety_validation_ms"))
        self.assertEqual(res_early.latency_breakdown_ms.get("safety_validation_status"), "NOT_RUN")

    # --- Test 23: Safety Validation Exception Fails Closed ---
    def test_safety_validation_exception_fails_closed(self):
        # If validator.validate throws an unexpected exception, the system must fail closed
        with patch.object(self.llm_service.validator, "validate", side_effect=RuntimeError("Unexpected validator fault")):
            self.mock_groq_provider.generate_completion.return_value = self._make_llm_response(
                intent="general_conversation",
                language="English",
                response="Normal conversational greeting.",
            )
            req = ConversationRequest(question="Can you help me with my crop?", language="en-IN")
            res = self.orchestrator.process_message(req)

            self.assertTrue(res.is_abstention)
            self.assertEqual(res.safety_status, "REJECTED")
            self.assertEqual(res.safety_validation_status, "REJECTED")
            self.assertIn("SAFETY_VALIDATION_ERROR", res.safety_reason)


class TestLightningSafetyRouting(unittest.TestCase):
    """
    Phase 8.9 — Focused tests for lightning/thunderstorm safety query routing.

    Verifies that:
    1. is_lightning_safety_query() correctly identifies safety-action questions.
    2. These questions do NOT trigger weather forecast routing (needs_weather=False).
    3. Plain weather forecast questions still route to weather pipeline.
    4. The orchestrator routes lightning safety questions directly to knowledge retrieval,
       bypassing the consent/location gate.
    """

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test_lightning.db"
        init_db(self.db_path)

        self.knowledge_adapter = ApprovedKnowledgeAdapter(db_path=self.db_path)

        self.mock_weather = MagicMock(spec=WeatherService)
        self.mock_farmer_service = MagicMock(spec=FarmerService)
        self.mock_farmer_service.get_farmer_by_id.return_value = None

        mock_provider = MagicMock(spec=GroqProvider)
        mock_provider.generate_completion.return_value = LLMResponseSchema(
            intent="agricultural_advice",
            language="Telugu",
            required_information=[],
            supported_facts=["Farmers should stay away from trees during lightning."],
            unsupported_questions=[],
            abstain=False,
            response="పిడుగులు పడినప్పుడు చెట్ల కింద నిలబడవద్దు .",
            evidence_citations=[],
            model_id="openai/gpt-oss-120b",
            safety_status="UNVERIFIED",
        )
        mock_validator = MagicMock(spec=LLMSafetyValidator)
        mock_validator.validate.side_effect = lambda req, out: (
            setattr(out, "safety_status", "PASSED") or setattr(out, "safety_violations", []) or out
        )
        self.mock_llm = LLMReasoningService(provider=mock_provider, validator=mock_validator)

        self.orchestrator = ConversationOrchestrator(
            farmer_service=self.mock_farmer_service,
            weather_service=self.mock_weather,
            knowledge_adapter=self.knowledge_adapter,
            llm_service=self.mock_llm,
            db_path=self.db_path,
        )

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    # ------------------------------------------------------------------ #
    # 1. is_lightning_safety_query detection                               #
    # ------------------------------------------------------------------ #

    def test_lightning_safety_telugu_detected(self):
        """Telugu thunder+precaution questions are detected as lightning safety."""
        cases = [
            "ఉరుములు పడినప్పుడు పొలంలో ఏమి చేయాలి",
            "పిడుగులు వచ్చినప్పుడు జాగ్రత్తలు",
            "వర్షం ఉరుములు పిడుగులు వచ్చినప్పుడు ఏం చేయాలి",
            "తుఫాను సమయంలో పిడుగు జాగ్రత్తలు",
            "పిడుగు పడకుండా జాగ్రత్తలు తెలపండి",
            "మెరుపు తాకితే ఏం చేయాలి",
        ]
        for q in cases:
            with self.subTest(q=q):
                self.assertTrue(is_lightning_safety_query(q), f"Expected lightning safety for: {q}")

    def test_lightning_safety_english_detected(self):
        """English lightning safety questions are detected."""
        cases = [
            "thunderstorm precautions for farmers",
            "what to do during lightning strike",
            "lightning safety tips",
            "how to protect from thunder",
        ]
        for q in cases:
            with self.subTest(q=q):
                self.assertTrue(is_lightning_safety_query(q), f"Expected lightning safety for: {q}")

    def test_weather_forecast_not_lightning_safety(self):
        """Pure weather forecast questions are NOT lightning safety queries."""
        cases = [
            "రేపు వర్షం పడుతుందా",
            "ఉరుములు ఎప్పుడు వస్తాయి",
            "వాతావరణం ఎలా ఉంటుంది",
            "నిజామాబాద్ లో ఈ రోజు వర్షం పడుతుందా",
            "tomorrow rain forecast",
        ]
        for q in cases:
            with self.subTest(q=q):
                self.assertFalse(is_lightning_safety_query(q), f"Should NOT be lightning safety: {q}")

    # ------------------------------------------------------------------ #
    # 2. needs_weather routing exclusion                                   #
    # ------------------------------------------------------------------ #

    def test_lightning_safety_excludes_weather_routing(self):
        """
        Questions with weather surface-words (ఉరుములు, తుఫాను) combined with safety
        keywords must NOT trigger the weather forecast pipeline.
        """
        from app.conversation.intent import is_weather_warning_query

        # These contain weather-trigger words but are safety questions
        lightning_safety_qs = [
            "ఉరుములు పడినప్పుడు పొలంలో ఏమి చేయాలి",
            "వర్షం ఉరుములు పిడుగులు వచ్చినప్పుడు ఏం చేయాలి",
            "తుఫాను సమయంలో పిడుగు జాగ్రత్తలు",
        ]
        for q in lightning_safety_qs:
            with self.subTest(q=q):
                is_ls = is_lightning_safety_query(q)
                is_wx = is_weather_query(q)
                is_warn = is_weather_warning_query(q)
                intent = classify_intent(q)
                # Confirm weather keywords would fire without lightning safety check
                self.assertTrue(is_wx or intent == INTENT_WEATHER_INQUIRY,
                                "Test precondition: question must contain weather keyword")
                # After lightning safety override, needs_weather must be False
                needs_weather = not is_ls and (is_wx or intent == INTENT_WEATHER_INQUIRY or is_warn)
                self.assertFalse(needs_weather,
                                 f"Lightning safety question incorrectly routed to weather pipeline: {q}")

    def test_weather_forecast_still_routed_to_weather(self):
        """Plain weather forecast questions still route to weather pipeline."""
        from app.conversation.intent import is_weather_warning_query

        forecast_qs = [
            "రేపు వర్షం పడుతుందా",
            "వాతావరణం ఎలా ఉంటుంది",
            "ఉరుములు ఎప్పుడు వస్తాయి",
        ]
        for q in forecast_qs:
            with self.subTest(q=q):
                is_ls = is_lightning_safety_query(q)
                is_wx = is_weather_query(q)
                is_warn = is_weather_warning_query(q)
                intent = classify_intent(q)
                needs_weather = not is_ls and (is_wx or intent == INTENT_WEATHER_INQUIRY or is_warn)
                self.assertTrue(needs_weather,
                                f"Forecast question lost weather routing: {q}")

    # ------------------------------------------------------------------ #
    # 3. Orchestrator: lightning safety bypasses consent/location gate     #
    # ------------------------------------------------------------------ #

    def test_lightning_safety_does_not_ask_for_location_or_consent(self):
        """
        A lightning safety question must reach knowledge retrieval without
        triggering the weather consent/location gate.
        The weather service must never be called.
        """
        req = ConversationRequest(
            question="ఉరుములు పడినప్పుడు పొలంలో ఏమి చేయాలి",
            language="te-IN",
            channel="telegram",
        )
        resp = self.orchestrator.process_message(req)

        # Weather service must NOT have been called
        self.mock_weather.get_current_weather.assert_not_called()
        self.mock_weather.get_forecast.assert_not_called()
        self.mock_weather.get_imd_district_warning.assert_not_called()

        # Response must not be a consent-required abstention
        self.assertNotIn("సమ్మతి", resp.response_text or "")
        self.assertNotIn("consent", (resp.response_text or "").lower())
        # Must not ask for location
        self.assertNotIn("జిల్లా", resp.response_text or "")
        # safety_reason must not be consent-related
        self.assertNotEqual(resp.safety_reason, "WEATHER_LOCATION_SHARING_CONSENT_REQUIRED")

    def test_lightning_safety_intent_classified_as_agricultural_advice(self):
        """classify_intent returns INTENT_AGRICULTURAL_ADVICE for lightning safety questions."""
        cases = [
            "ఉరుములు పడినప్పుడు పొలంలో ఏమి చేయాలి",
            "పిడుగులు వచ్చినప్పుడు జాగ్రత్తలు",
            "తుఫాను సమయంలో పిడుగు జాగ్రత్తలు",
            "thunderstorm precautions for farmers",
        ]
        for q in cases:
            with self.subTest(q=q):
                self.assertEqual(classify_intent(q), INTENT_AGRICULTURAL_ADVICE,
                                 f"Expected INTENT_AGRICULTURAL_ADVICE for: {q}")


if __name__ == "__main__":
    unittest.main()
