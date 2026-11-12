"""
Unit test suite for KrishiVaani LLM Modular Reasoning & Groq Provider — Phase 7.2.

Covers all 14 mandatory test cases using mocked Groq responses:
1. Successful Telugu response.
2. Successful English response.
3. Valid JSON schema parsing.
4. Malformed/broken JSON handling.
5. Missing evidence clarification behavior.
6. Unknown evidence reference rejection.
7. Expired evidence rejection.
8. Geographically mismatched evidence rejection.
9. Unsupported numerical claims rejection.
10. Unsupported pesticide recommendation rejection.
11. Provider timeout handling.
12. Provider authentication error handling.
13. Provider rate limiting handling.
14. Safe abstention enforcement.
15. Weather forecast alone boundary enforcement.
16. Unconfigured provider error handling.
"""

import unittest
from unittest.mock import MagicMock, patch
import json
from datetime import date, timedelta
from groq import (
    AuthenticationError,
    RateLimitError,
    APITimeoutError,
    APIConnectionError,
)

from app.llm.config import LLMConfig, mask_api_key
from app.llm.schemas import (
    LLMResponseSchema,
    LLMReasoningRequest,
    FarmerContextSchema,
    ApprovedEvidenceItem,
    WeatherFactItem,
)
from app.llm.exceptions import (
    LLMError,
    LLMProviderNotConfiguredError,
    LLMAuthenticationError,
    LLMRateLimitError,
    LLMProviderUnavailableError,
    LLMTimeoutError,
    LLMMalformedResponseError,
    LLMSafetyViolationError,
)
from app.llm.providers.groq_provider import GroqProvider
from app.llm.providers.sarvam_provider import SarvamProvider
from app.llm.safety import LLMSafetyValidator
from app.llm.service import LLMReasoningService


def create_mock_completion(content_dict_or_str, prompt_tokens=100, completion_tokens=200):
    """Helper to create a realistic mocked Groq chat completion response."""
    if isinstance(content_dict_or_str, dict):
        content_str = json.dumps(content_dict_or_str, ensure_ascii=False)
    else:
        content_str = str(content_dict_or_str)

    mock_choice = MagicMock()
    mock_choice.message.content = content_str
    mock_choice.message.reasoning = "Mocked chain of thought reasoning tokens."
    mock_choice.finish_reason = "stop"

    mock_usage = MagicMock()
    mock_usage.prompt_tokens = prompt_tokens
    mock_usage.completion_tokens = completion_tokens
    mock_usage.total_tokens = prompt_tokens + completion_tokens

    mock_completion = MagicMock()
    mock_completion.choices = [mock_choice]
    mock_completion.usage = mock_usage
    return mock_completion


class TestLLMServiceAndProvider(unittest.TestCase):
    """Unit tests for Phase 7.2 Groq provider and reasoning service."""

    def setUp(self):
        self.config = LLMConfig(
            model_id="openai/gpt-oss-120b",
            api_key="gsk_mock_test_key_1234567890abcdef",
            temperature=0.1,
            max_tokens=1500,
            timeout_seconds=5.0,
        )
        self.mock_groq_client = MagicMock()
        self.provider = GroqProvider(config=self.config, client=self.mock_groq_client)
        self.service = LLMReasoningService(provider=self.provider, validator=LLMSafetyValidator())

    # 1. Successful Telugu response
    def test_successful_telugu_response(self):
        telugu_payload = {
            "intent": "advisory_summary",
            "language": "Telugu",
            "required_information": [],
            "supported_facts": ["వేరుశెనగ TAG-24 ఉత్తర తెలంగాణకు అనుకూలం"],
            "unsupported_questions": [],
            "abstain": False,
            "evidence_citations": ["KNOW-ADIL-001"],
            "response": "ఈ సలహా ప్రకారం యాసంగి సీజన్‌లో తేలికపాటి నేలల్లో వేరుశెనగ సాగు అనుకూలం.",
        }
        self.mock_groq_client.chat.completions.create.return_value = create_mock_completion(telugu_payload)

        evidence = [
            ApprovedEvidenceItem(
                evidence_id="KNOW-ADIL-001",
                source_id="SRC-PJTAU-001",
                source_type="PJTAU_AGROMET_ADVISORY",
                title="Groundnut Advisory",
                content="Groundnut TAG-24 variety is recommended for light soils in Northern Telangana for Yasangi.",
                verification_status="APPROVED",
                district="Adilabad",
                crop_name="Groundnut",
            )
        ]
        req = LLMReasoningRequest(
            farmer_question="వేరుశెనగ గురించి సలహా ఏమిటి?",
            language="Telugu",
            farmer_context=FarmerContextSchema(district="Adilabad"),
            approved_evidence=evidence,
        )

        resp = self.service.process_query(req)
        self.assertFalse(resp.abstain)
        self.assertEqual(resp.safety_status, "PASSED")
        self.assertEqual(resp.language, "Telugu")
        self.assertIn("వేరుశెనగ", resp.response)
        self.assertIn("KNOW-ADIL-001", resp.evidence_citations)

    # 2. Successful English response
    def test_successful_english_response(self):
        english_payload = {
            "intent": "weather_inquiry",
            "language": "English",
            "required_information": [],
            "supported_facts": ["12 mm observed rainfall at Adilabad station"],
            "unsupported_questions": ["Will it rain tomorrow?"],
            "abstain": False,
            "evidence_citations": ["KNOW-WEATHER-001"],
            "response": "Adilabad recorded 12 mm of rainfall in the past 24 hours.",
        }
        self.mock_groq_client.chat.completions.create.return_value = create_mock_completion(english_payload)

        req = LLMReasoningRequest(
            farmer_question="How much rain was recorded?",
            language="English",
            approved_evidence=[
                ApprovedEvidenceItem(
                    evidence_id="KNOW-WEATHER-001",
                    source_id="SRC-TGDPS-001",
                    source_type="TGDPS_DAILY_REPORT",
                    title="Rainfall Report",
                    content="Observed rainfall of 12 mm recorded at Adilabad AWS.",
                    verification_status="APPROVED",
                    district="Adilabad",
                )
            ]
        )

        resp = self.service.process_query(req)
        self.assertFalse(resp.abstain)
        self.assertEqual(resp.safety_status, "PASSED")
        self.assertEqual(resp.language, "English")
        self.assertIn("12 mm", resp.response)

    # 3. Valid JSON schema parsing
    def test_valid_json_schema(self):
        valid_payload = {
            "intent": "crop_clarification",
            "language": "English",
            "required_information": ["mandal", "season", "water source"],
            "supported_facts": [],
            "unsupported_questions": ["Which crop should I grow?"],
            "abstain": False,
            "evidence_citations": [],
            "response": "To help you choose a crop, could you share your mandal and season?",
        }
        self.mock_groq_client.chat.completions.create.return_value = create_mock_completion(valid_payload)

        req = LLMReasoningRequest(farmer_question="Which crop should I grow?")
        resp = self.service.process_query(req)
        self.assertIsInstance(resp, LLMResponseSchema)
        self.assertEqual(resp.intent, "crop_clarification")
        self.assertEqual(len(resp.required_information), 3)

    # 4. Malformed/broken JSON handling
    def test_malformed_json_response(self):
        broken_json = '{"intent": "broken", "response": "missing closing braces...'
        self.mock_groq_client.chat.completions.create.return_value = create_mock_completion(broken_json)

        req = LLMReasoningRequest(farmer_question="Hello", language="English")
        resp = self.service.process_query(req)

        self.assertTrue(resp.abstain)
        self.assertEqual(resp.safety_status, "ABSTAINED")
        self.assertIn("MALFORMED_RESPONSE", resp.safety_violations[0])
        self.assertIn("technical service limitation", resp.response)

    # 5. Missing evidence clarification behavior
    def test_missing_evidence_clarification(self):
        clarification_payload = {
            "intent": "crop_recommendation",
            "language": "English",
            "required_information": ["mandal", "season", "land size", "irrigation capacity"],
            "supported_facts": [],
            "unsupported_questions": ["Which crop should I grow?"],
            "abstain": False,
            "evidence_citations": [],
            "response": "I cannot recommend a crop without more details. Please share your mandal, season, and land size.",
        }
        self.mock_groq_client.chat.completions.create.return_value = create_mock_completion(clarification_payload)

        req = LLMReasoningRequest(
            farmer_question="Which crop should I grow in black soil with limited water?",
            language="English",
            approved_evidence=[],
        )
        resp = self.service.process_query(req)
        self.assertEqual(resp.safety_status, "PASSED")
        self.assertIn("mandal", resp.response.lower())

    # 6. Unknown evidence reference rejection
    def test_unknown_evidence_references(self):
        hallucinated_citation_payload = {
            "intent": "crop_recommendation",
            "language": "English",
            "required_information": [],
            "supported_facts": ["Sow cotton variety RCH-659 as per KNOW-SECRET-999"],
            "unsupported_questions": [],
            "abstain": False,
            "evidence_citations": ["KNOW-SECRET-999"],  # Unknown ID!
            "response": "According to advisory KNOW-SECRET-999 you should plant cotton.",
        }
        self.mock_groq_client.chat.completions.create.return_value = create_mock_completion(hallucinated_citation_payload)

        req = LLMReasoningRequest(
            farmer_question="What should I plant?",
            language="English",
            approved_evidence=[
                ApprovedEvidenceItem(
                    evidence_id="KNOW-REAL-001",
                    source_id="SRC-001",
                    source_type="PJTAU",
                    title="Real advisory",
                    content="Groundnut info",
                )
            ]
        )
        resp = self.service.process_query(req)

        self.assertTrue(resp.abstain)
        self.assertEqual(resp.safety_status, "REJECTED")
        self.assertTrue(any("unknown evidence" in v.lower() for v in resp.safety_violations))
        self.assertIn("KVK", resp.response)

    # 7. Expired evidence rejection
    def test_expired_evidence_rejection(self):
        yesterday = (date.today() - timedelta(days=5)).isoformat()
        expired_payload = {
            "intent": "advisory",
            "language": "English",
            "required_information": [],
            "supported_facts": ["Groundnut recommended"],
            "unsupported_questions": [],
            "abstain": False,
            "evidence_citations": ["KNOW-EXPIRED-001"],
            "response": "You should plant groundnut right now based on this advisory.",
        }
        self.mock_groq_client.chat.completions.create.return_value = create_mock_completion(expired_payload)

        req = LLMReasoningRequest(
            farmer_question="Can I plant groundnut now?",
            language="English",
            as_of_date=date.today().isoformat(),
            approved_evidence=[
                ApprovedEvidenceItem(
                    evidence_id="KNOW-EXPIRED-001",
                    source_id="SRC-001",
                    source_type="PJTAU",
                    title="Old Advisory",
                    content="Groundnut recommendation",
                    valid_until=yesterday,
                    crop_name="Groundnut",
                )
            ]
        )
        resp = self.service.process_query(req)

        self.assertTrue(resp.abstain)
        self.assertEqual(resp.safety_status, "REJECTED")
        self.assertTrue(any("expired" in v.lower() for v in resp.safety_violations))

    # 8. Geographically mismatched evidence rejection
    def test_geographically_mismatched_evidence(self):
        mismatch_payload = {
            "intent": "crop_advisory",
            "language": "English",
            "required_information": [],
            "supported_facts": ["Groundnut TAG-24 recommended"],
            "unsupported_questions": [],
            "abstain": False,
            "evidence_citations": ["KNOW-ADIL-001"],
            "response": "You should plant groundnut TAG-24 in your fields immediately.",
        }
        self.mock_groq_client.chat.completions.create.return_value = create_mock_completion(mismatch_payload)

        req = LLMReasoningRequest(
            farmer_question="What should I plant in my field?",
            language="English",
            farmer_context=FarmerContextSchema(district="Khammam"),  # Farmer is in Khammam
            approved_evidence=[
                ApprovedEvidenceItem(
                    evidence_id="KNOW-ADIL-001",
                    source_id="SRC-001",
                    source_type="PJTAU",
                    title="Adilabad Advisory",
                    content="Groundnut TAG-24 recommended for Adilabad district.",
                    district="Adilabad",  # Evidence strictly for Adilabad
                    crop_name="Groundnut",
                )
            ]
        )
        resp = self.service.process_query(req)

        self.assertTrue(resp.abstain)
        self.assertEqual(resp.safety_status, "REJECTED")
        self.assertTrue(any("geographic mismatch" in v.lower() for v in resp.safety_violations))

    # 9. Unsupported numerical claims rejection
    def test_unsupported_numerical_claims(self):
        fabricated_yield_payload = {
            "intent": "yield_forecast",
            "language": "English",
            "required_information": [],
            "supported_facts": [],
            "unsupported_questions": [],
            "abstain": False,
            "evidence_citations": [],
            "response": "You will get an expected yield of 25 quintals per acre and earn Rs. 50,000 profit.",
        }
        self.mock_groq_client.chat.completions.create.return_value = create_mock_completion(fabricated_yield_payload)

        req = LLMReasoningRequest(
            farmer_question="What yield will I get?",
            language="English",
            approved_evidence=[
                ApprovedEvidenceItem(
                    evidence_id="KNOW-001",
                    source_id="SRC-001",
                    source_type="PJTAU",
                    title="Maize general",
                    content="Maize is a major kharif crop in Telangana.",
                )
            ]
        )
        resp = self.service.process_query(req)

        self.assertTrue(resp.abstain)
        self.assertEqual(resp.safety_status, "REJECTED")
        self.assertTrue(any("yield" in v.lower() or "financial" in v.lower() for v in resp.safety_violations))

    # 10. Unsupported pesticide recommendation rejection
    def test_unsupported_pesticide_recommendation(self):
        pesticide_payload = {
            "intent": "pest_control",
            "language": "English",
            "required_information": [],
            "supported_facts": [],
            "unsupported_questions": [],
            "abstain": False,
            "evidence_citations": [],
            "response": "Spray monocrotophos at 2 ml per liter of water on your cotton crop.",
        }
        self.mock_groq_client.chat.completions.create.return_value = create_mock_completion(pesticide_payload)

        req = LLMReasoningRequest(
            farmer_question="Which pesticide should I spray on my cotton?",
            language="English",
            approved_evidence=[]  # Zero pesticide evidence supplied
        )
        resp = self.service.process_query(req)

        self.assertTrue(resp.abstain)
        self.assertEqual(resp.safety_status, "REJECTED")
        self.assertTrue(any("pesticide" in v.lower() or "dosage" in v.lower() for v in resp.safety_violations))

    # 11. Provider timeout handling
    def test_provider_timeout_handling(self):
        self.mock_groq_client.chat.completions.create.side_effect = APITimeoutError(
            request=MagicMock()
        )

        req = LLMReasoningRequest(farmer_question="Hello", language="English")
        resp = self.service.process_query(req)

        self.assertTrue(resp.abstain)
        self.assertEqual(resp.safety_status, "ABSTAINED")
        self.assertTrue(any("LLMTimeoutError" in v for v in resp.safety_violations))

    # 12. Provider authentication error handling
    def test_provider_authentication_error(self):
        mock_response = MagicMock(status_code=401)
        self.mock_groq_client.chat.completions.create.side_effect = AuthenticationError(
            message="Invalid API key provided",
            response=mock_response,
            body={"error": {"message": "Invalid API key"}},
        )

        req = LLMReasoningRequest(farmer_question="Hello", language="English")
        resp = self.service.process_query(req)

        self.assertTrue(resp.abstain)
        self.assertEqual(resp.safety_status, "ABSTAINED")
        self.assertTrue(any("LLMAuthenticationError" in v for v in resp.safety_violations))

    # 13. Provider rate limiting handling
    def test_provider_rate_limit_error(self):
        mock_response = MagicMock(status_code=429)
        self.mock_groq_client.chat.completions.create.side_effect = RateLimitError(
            message="Rate limit exceeded",
            response=mock_response,
            body={"error": {"message": "Rate limit exceeded"}},
        )

        req = LLMReasoningRequest(farmer_question="Hello", language="Telugu")
        resp = self.service.process_query(req)

        self.assertTrue(resp.abstain)
        self.assertEqual(resp.safety_status, "ABSTAINED")
        self.assertTrue(any("LLMRateLimitError" in v for v in resp.safety_violations))
        self.assertIn("కొన్ని సెకన్లు ఆగి", resp.response)

    # 14. Safe abstention enforcement
    def test_safe_abstention_enforcement(self):
        voluntary_abstain_payload = {
            "intent": "pest_control",
            "language": "English",
            "required_information": ["Pest symptoms", "Crop stage"],
            "supported_facts": [],
            "unsupported_questions": ["What pesticide should I use?"],
            "abstain": True,
            "evidence_citations": [],
            "response": "I cannot recommend a pesticide without identifying the pest. Please visit your local KVK.",
        }
        self.mock_groq_client.chat.completions.create.return_value = create_mock_completion(voluntary_abstain_payload)

        req = LLMReasoningRequest(farmer_question="Which pesticide?", language="English")
        resp = self.service.process_query(req)

        self.assertTrue(resp.abstain)
        self.assertEqual(resp.safety_status, "ABSTAINED")
        self.assertEqual(len(resp.safety_violations), 0)

    # 15. Weather forecast alone cannot trigger crop advice
    def test_weather_forecast_alone_cannot_trigger_crop_advice(self):
        crop_advice_on_weather_payload = {
            "intent": "crop_advice",
            "language": "English",
            "required_information": [],
            "supported_facts": ["Forecast indicates 40 mm rain"],
            "unsupported_questions": [],
            "abstain": False,
            "evidence_citations": [],
            "response": "Heavy rain is forecast, so you should plant jowar right now.",
        }
        self.mock_groq_client.chat.completions.create.return_value = create_mock_completion(crop_advice_on_weather_payload)

        req = LLMReasoningRequest(
            farmer_question="It might rain, what should I grow?",
            language="English",
            weather_facts=[
                WeatherFactItem(
                    is_forecast=True,
                    forecast_rainfall_mm=40.0,
                    summary="40 mm rainfall forecast over the next 48 hours."
                )
            ],
            approved_evidence=[]  # Zero crop evidence
        )
        resp = self.service.process_query(req)

        self.assertTrue(resp.abstain)
        self.assertEqual(resp.safety_status, "REJECTED")
        self.assertTrue(any("forecast alone" in v.lower() for v in resp.safety_violations))

    # 16. Provider not configured error
    def test_provider_not_configured(self):
        unconfigured_provider = GroqProvider(config=LLMConfig(api_key=None), client=None)
        with self.assertRaises(LLMProviderNotConfiguredError):
            _ = unconfigured_provider.client

    # 17. Mask API key helper
    def test_mask_api_key_helper(self):
        self.assertEqual(mask_api_key(None), "<NOT_SET>")
        self.assertEqual(mask_api_key("short"), "***")
        self.assertEqual(mask_api_key("gsk_1234567890abcdef"), "gsk_...cdef")


class TestSarvamPrimaryGroqFallback(unittest.TestCase):
    """
    Verification tests for Stage 2 LLM architecture:
    Sarvam AI as primary reasoning provider with Groq as automatic fallback.
    """

    def setUp(self):
        self.validator = LLMSafetyValidator()

    def test_sarvam_success_does_not_call_groq(self):
        mock_sarvam = MagicMock(spec=SarvamProvider)
        mock_sarvam.model_id = "sarvam-105b-conversations"
        mock_sarvam.generate_completion.return_value = LLMResponseSchema(
            intent="crop_guidance",
            language="English",
            response="Groundnut requires light well-drained red soils.",
            evidence_citations=["KNOW-101"],
            unsupported_questions=[],
            abstain=False,
            confidence=0.9,
            model_id="sarvam-105b-conversations",
        )

        service = LLMReasoningService(provider=mock_sarvam, validator=self.validator)

        with patch("app.llm.service.GroqProvider") as mock_groq_cls:
            req = LLMReasoningRequest(
                farmer_question="What soil is best for groundnut?",
                language="English",
                approved_evidence=[
                    ApprovedEvidenceItem(
                        evidence_id="KNOW-101",
                        source_id="SRC-PJTAU-001",
                        source_type="PJTAU_AGROMET_ADVISORY",
                        citation_id="CITE-101",
                        title="Groundnut Soil",
                        content="Groundnut requires light well-drained red soils.",
                        category="Crop Guide",
                        crop_name="Groundnut",
                        state="Telangana",
                    )
                ],
            )
            resp = service.process_query(req)

            mock_sarvam.generate_completion.assert_called_once()
            mock_groq_cls.assert_not_called()
            self.assertEqual(resp.model_id, "sarvam-105b-conversations")
            self.assertEqual(resp.safety_status, "PASSED")

    def test_sarvam_timeout_calls_groq_fallback_once(self):
        mock_sarvam = MagicMock(spec=SarvamProvider)
        mock_sarvam.model_id = "sarvam-105b-conversations"
        mock_sarvam.generate_completion.side_effect = LLMTimeoutError("Sarvam timed out after 12s", provider="sarvam")

        mock_groq_instance = MagicMock()
        mock_groq_instance.model_id = "openai/gpt-oss-120b"
        mock_groq_instance.generate_completion.return_value = LLMResponseSchema(
            intent="crop_guidance",
            language="English",
            response="Red soils are suitable for groundnut with irrigation.",
            evidence_citations=["KNOW-101"],
            unsupported_questions=[],
            abstain=False,
            confidence=0.85,
            model_id="openai/gpt-oss-120b",
        )

        service = LLMReasoningService(provider=mock_sarvam, validator=self.validator)

        with patch("app.llm.service.GroqProvider", return_value=mock_groq_instance) as mock_groq_cls:
            req = LLMReasoningRequest(
                farmer_question="What soil is best for groundnut?",
                language="English",
                approved_evidence=[
                    ApprovedEvidenceItem(
                        evidence_id="KNOW-101",
                        source_id="SRC-PJTAU-001",
                        source_type="PJTAU_AGROMET_ADVISORY",
                        citation_id="CITE-101",
                        title="Groundnut Soil",
                        content="Red soils are suitable for groundnut with irrigation.",
                        category="Crop Guide",
                        crop_name="Groundnut",
                        state="Telangana",
                    )
                ],
            )
            resp = service.process_query(req)

            mock_sarvam.generate_completion.assert_called_once()
            mock_groq_cls.assert_called_once()
            mock_groq_instance.generate_completion.assert_called_once()
            self.assertEqual(resp.model_id, "openai/gpt-oss-120b")
            self.assertEqual(resp.safety_status, "PASSED")

    def test_sarvam_rate_limit_calls_groq_fallback_once(self):
        mock_sarvam = MagicMock(spec=SarvamProvider)
        mock_sarvam.model_id = "sarvam-105b-conversations"
        mock_sarvam.generate_completion.side_effect = LLMRateLimitError("Sarvam 429 rate limit", provider="sarvam")

        mock_groq_instance = MagicMock()
        mock_groq_instance.model_id = "openai/gpt-oss-120b"
        mock_groq_instance.generate_completion.return_value = LLMResponseSchema(
            intent="crop_guidance",
            language="English",
            response="Groundnut requires red sandy loam soils.",
            evidence_citations=["CITE-101"],
            unsupported_questions=[],
            abstain=False,
            confidence=0.85,
            model_id="openai/gpt-oss-120b",
        )

        service = LLMReasoningService(provider=mock_sarvam, validator=self.validator)

        with patch("app.llm.service.GroqProvider", return_value=mock_groq_instance):
            req = LLMReasoningRequest(
                farmer_question="What soil for groundnut?",
                language="English",
                approved_evidence=[
                    ApprovedEvidenceItem(
                        evidence_id="KNOW-101",
                        source_id="SRC-PJTAU-001",
                        source_type="PJTAU_AGROMET_ADVISORY",
                        citation_id="CITE-101",
                        title="Groundnut Soil",
                        content="Groundnut requires red sandy loam soils.",
                        category="Crop Guide",
                        crop_name="Groundnut",
                        state="Telangana",
                    )
                ],
            )
            resp = service.process_query(req)
            self.assertEqual(resp.model_id, "openai/gpt-oss-120b")

    def test_groq_response_passes_through_safety_validator(self):
        mock_sarvam = MagicMock(spec=SarvamProvider)
        mock_sarvam.generate_completion.side_effect = LLMProviderUnavailableError("Sarvam 503 unavailable", provider="sarvam")

        # Groq returns an unsafe response with ungrounded pesticide dosage
        mock_groq_instance = MagicMock()
        mock_groq_instance.model_id = "openai/gpt-oss-120b"
        mock_groq_instance.generate_completion.return_value = LLMResponseSchema(
            intent="crop_guidance",
            language="English",
            response="Spray 50 ml monocrotophos per acre immediately.",
            evidence_citations=[],
            unsupported_questions=[],
            abstain=False,
            confidence=0.9,
            model_id="openai/gpt-oss-120b",
        )

        service = LLMReasoningService(provider=mock_sarvam, validator=self.validator)

        with patch("app.llm.service.GroqProvider", return_value=mock_groq_instance):
            req = LLMReasoningRequest(
                farmer_question="How to kill pests?",
                language="English",
                approved_evidence=[],
            )
            resp = service.process_query(req)

            # Response must be REJECTED by deterministic safety validator
            self.assertEqual(resp.safety_status, "REJECTED")
            self.assertIn("consult your local Agricultural Officer", resp.response)

    def test_both_providers_fail_returns_localized_safe_fallback(self):
        mock_sarvam = MagicMock(spec=SarvamProvider)
        mock_sarvam.generate_completion.side_effect = LLMTimeoutError("Sarvam timed out", provider="sarvam")

        mock_groq_instance = MagicMock()
        mock_groq_instance.generate_completion.side_effect = LLMProviderUnavailableError("Groq 503 unavailable", provider="groq")

        service = LLMReasoningService(provider=mock_sarvam, validator=self.validator)

        with patch("app.llm.service.GroqProvider", return_value=mock_groq_instance):
            req = LLMReasoningRequest(
                farmer_question="What is the forecast?",
                language="Telugu",
                channel="telegram",
                approved_evidence=[],
            )
            resp = service.process_query(req)

            self.assertTrue(resp.abstain)
            self.assertEqual(resp.safety_status, "ABSTAINED")
            self.assertIn("సాంకేతిక సమస్య", resp.response)

    def test_safety_rejection_from_sarvam_does_not_trigger_groq_fallback(self):
        # Sarvam succeeds, but produces an ungrounded chemical dosage
        mock_sarvam = MagicMock(spec=SarvamProvider)
        mock_sarvam.model_id = "sarvam-105b-conversations"
        mock_sarvam.generate_completion.return_value = LLMResponseSchema(
            intent="crop_guidance",
            language="English",
            response="Apply 25 kg DAP per acre right away.",
            evidence_citations=[],
            unsupported_questions=[],
            abstain=False,
            confidence=0.8,
            model_id="sarvam-105b-conversations",
        )

        service = LLMReasoningService(provider=mock_sarvam, validator=self.validator)

        with patch("app.llm.service.GroqProvider") as mock_groq_cls:
            req = LLMReasoningRequest(
                farmer_question="How much fertilizer?",
                language="English",
                approved_evidence=[],
            )
            resp = service.process_query(req)

            # Groq fallback must NOT be called when Sarvam produced a safety violation!
            mock_groq_cls.assert_not_called()
            self.assertEqual(resp.safety_status, "REJECTED")


if __name__ == "__main__":
    unittest.main()
