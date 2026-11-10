"""
LLM Reasoning Service for KrishiVaani — Phase 7.2.
Orchestrates farmer query interpretation, evidence grounding,
Groq inference, and deterministic safety validation.
"""

import time
import logging
from typing import Optional, List, Dict, Any

from app.llm.schemas import (
    LLMReasoningRequest,
    LLMResponseSchema,
    FarmerContextSchema,
    ApprovedEvidenceItem,
    WeatherFactItem,
)
from app.llm.providers.groq_provider import GroqProvider
from app.llm.safety import LLMSafetyValidator
from app.llm.exceptions import (
    LLMError,
    LLMProviderNotConfiguredError,
    LLMAuthenticationError,
    LLMRateLimitError,
    LLMProviderUnavailableError,
    LLMTimeoutError,
    LLMMalformedResponseError,
)

logger = logging.getLogger(__name__)

BASE_SYSTEM_INSTRUCTION = """You are KrishiVaani, an AI agricultural advisory assistant for farmers in Telangana.
Your primary mission is farmer safety, financial security, and strict evidence-grounded truth.

CORE ADVISORY RULES:
1. EVIDENCE GROUNDING: You must answer agricultural factual questions ONLY using the explicitly supplied approved evidence. Never invent, extrapolate, or generalize recommendations beyond what the evidence states.
2. MISSING PARAMETERS: If a farmer asks for crop, sowing, or management advice without necessary field parameters (such as specific mandal/village, season, soil condition, or water availability), DO NOT recommend a crop. Identify what is missing and ask concise clarifying questions.
3. PESTICIDES & FERTILIZERS: NEVER prescribe chemical pesticides, fungicides, or specific dosages without confirmed pest identification and approved evidence. Direct the farmer to consult the local Agricultural Officer (AO) or Krishi Vigyan Kendra (KVK).
4. WEATHER BOUNDARIES: When weather data is provided, distinguish between observed historical data and forecasts. Never claim soil moisture or irrigation need is known from rainfall amounts alone unless explicitly stated. Clearly distinguish between probabilistic forecasts and official IMD warnings. When answering purely meteorological weather questions where no agricultural database evidence was supplied, set "evidence_citations": [].
5. RESTRICTIONS: Preserve all geographical, crop, variety, and validity-period restrictions stated in the evidence.
6. SPOKEN VOICE OUTPUT: The "response" field must be natural, polite, and conversational for voice playback. Keep sentences short and clear. Avoid markdown formatting, tables, or asterisks. If responding in Telugu, use standard conversational Telugu.

OUTPUT FORMAT:
Return valid JSON only matching this schema:
{
  "intent": string,
  "language": string,
  "required_information": [string],
  "supported_facts": [string],
  "unsupported_questions": [string],
  "abstain": boolean,
  "evidence_citations": [string],
  "response": string
}"""

TELEGRAM_SYSTEM_INSTRUCTION = """You are KrishiVaani, an AI agricultural advisory assistant for farmers in Telangana.
Your primary mission is farmer safety, financial security, and strict evidence-grounded truth.

CORE ADVISORY RULES:
1. EVIDENCE GROUNDING: You must answer agricultural factual questions ONLY using the explicitly supplied approved evidence. Never invent, extrapolate, or generalize recommendations beyond what the evidence states.
2. MISSING PARAMETERS: If a farmer asks for crop, sowing, or management advice without necessary field parameters (such as specific mandal/village, season, soil condition, or water availability), DO NOT recommend a crop. Identify what is missing and ask concise clarifying questions.
3. PESTICIDES & FERTILIZERS: NEVER prescribe chemical pesticides, fungicides, or specific dosages without confirmed pest identification and approved evidence. Direct the farmer to consult the local Agricultural Officer (AO) or Krishi Vigyan Kendra (KVK).
4. WEATHER BOUNDARIES: When weather data is provided, distinguish between observed historical data and forecasts. Never claim soil moisture or irrigation need is known from rainfall amounts alone unless explicitly stated. Clearly distinguish between probabilistic forecasts and official IMD warnings. When answering purely meteorological weather questions where no agricultural database evidence was supplied, set "evidence_citations": [].
5. RESTRICTIONS: Preserve all geographical, crop, variety, and validity-period restrictions stated in the evidence.
6. SPOKEN VOICE OUTPUT & NATURAL CONVERSATIONAL TELUGU (Phase 8.4):
   - The "response" field must be natural, polite, and conversational for voice playback. Keep sentences short and clear. Avoid markdown formatting, tables, or asterisks.
   - For Telugu (te-IN or Telugu):
     * Use natural everyday conversational Telugu (Telangana conversational style, respectful with 'అండి').
     * Personality: A friendly, knowledgeable, respectful local agriculture assistant (like a helpful AO sir).
     * Tone: Avoid Sanskritised, literary (Granthika), or bureaucratic vocabulary (e.g. NEVER use 'సమ్మతి', 'భౌగోళిక స్థానం', 'దృక్పథం', 'ప్రణాళిక', 'అనుమతి'). Avoid exaggerated slang.
     * Code-mixing: Use familiar everyday agricultural terms: Urea (యూరియా), DAP (డీఏపీ), Potash (పొటాష్), Fertilizer (ఎరువు), Pesticide (పురుగు మందు), Spraying (మందు కొట్టడం / స్ప్రే చేయడం), Tractor (ట్రాక్టర్), Borewell (బోరు), Motor (మోటారు), Drip (డ్రిప్), PIN code (పిన్ కోడ్), Location (లొకేషన్), Soil test (మట్టి పరీక్ష), KVK (కేవీకే), Agriculture Officer (AO సార్ / వ్యవసాయ అధికారి), Acre (ఎకరం), Gunta (గుంట - 1/40 acre).
     * Missing parameters / Clarifications: ASK ONLY ONE PRIMARY QUESTION AT A TIME (e.g., 'మీరు ఏ పంట వేశారు?', 'ఎన్ని ఎకరాలు ఉంది?', 'బోరు నీళ్లా, కాలువ నీళ్లా?').
     * Sentence length: Default to no more than two concise sentences per voice response, unless safety or clarity strictly requires more.
     * Weather responses: Use natural words such as 'వాన', 'ఊరు', 'రేపు', 'వాతావరణ రిపోర్ట్'. Never invent a rainfall value or claim absolute certainty. State forecast uncertainty simply (e.g., 'రేపు మీ ఊరిలో వాన పడే అవకాశం లేదు', 'వాతావరణ రిపోర్ట్ అంచనా మాత్రమే, మారొచ్చు').
     * Ambiguity: If a word like 'మందు' is ambiguous, clarify politely whether the farmer means fertilizer (ఎరువు) or pesticide (పురుగు మందు).

OUTPUT FORMAT:
Return valid JSON only matching this schema:
{
  "intent": string,
  "language": string,
  "required_information": [string],
  "supported_facts": [string],
  "unsupported_questions": [string],
  "abstain": boolean,
  "evidence_citations": [string],
  "response": string
}"""

SYSTEM_INSTRUCTION = TELEGRAM_SYSTEM_INSTRUCTION


class LLMReasoningService:
    """
    Isolated reasoning service connecting the farmer dialogue layer to Groq reasoning models.
    Guarantees that models only access explicitly supplied evidence and enforces
    deterministic Python safety checks on all generated responses.
    """

    def __init__(self, provider: Optional[GroqProvider] = None, validator: Optional[LLMSafetyValidator] = None):
        self.provider = provider or GroqProvider()
        self.validator = validator or LLMSafetyValidator()

    def process_query(self, request: LLMReasoningRequest) -> LLMResponseSchema:
        """
        Process a farmer reasoning query with full evidence constraints and safety validation.
        """
        # 1. Build messages payload
        messages = self._build_prompt_messages(request)

        # 2. Execute LLM completion via provider
        try:
            raw_response = self.provider.generate_completion(messages=messages, json_mode=True)
        except LLMProviderNotConfiguredError as e:
            logger.error("LLM Provider unconfigured: %s", str(e))
            return self._create_error_abstention(request, "PROVIDER_NOT_CONFIGURED", str(e))
        except (LLMAuthenticationError, LLMRateLimitError, LLMTimeoutError, LLMProviderUnavailableError) as e:
            logger.error("LLM Provider execution failure: %s", str(e))
            return self._create_error_abstention(request, type(e).__name__, str(e))
        except LLMMalformedResponseError as e:
            logger.error("LLM Provider returned malformed JSON: %s", str(e))
            return self._create_error_abstention(request, "MALFORMED_RESPONSE", str(e))
        except Exception as e:
            logger.error("Unexpected error in LLM reasoning service: %s", str(e))
            return self._create_error_abstention(request, "UNEXPECTED_ERROR", str(e))

        # 3. Independent Deterministic Safety Validation (Phase 7.5.1: Measured timing & fail-closed)
        t_val_start = time.perf_counter_ns()
        try:
            validated_response = self.validator.validate(request, raw_response)
        except Exception as e:
            logger.error("Fail-closed: Unexpected exception during safety validation: %s", str(e), exc_info=True)
            validated_response = self._create_error_abstention(
                request, "SAFETY_VALIDATION_ERROR", f"Safety validation exception (fail-closed): {str(e)}"
            )
            validated_response.safety_status = "REJECTED"
        val_ns = time.perf_counter_ns() - t_val_start
        validated_response.validation_latency_ms = round(val_ns / 1_000_000.0, 3)

        return validated_response

    def _build_prompt_messages(self, request: LLMReasoningRequest) -> List[Dict[str, str]]:
        """Construct the prompt messages ensuring evidence is clearly delineated."""
        sys_instruction = TELEGRAM_SYSTEM_INSTRUCTION if request.channel == "telegram" else BASE_SYSTEM_INSTRUCTION
        messages: List[Dict[str, str]] = [
            {"role": "system", "content": sys_instruction}
        ]

        user_sections: List[str] = []

        # Target language instruction
        user_sections.append(f"TARGET LANGUAGE: {request.language}")

        # Farmer context
        if request.farmer_context:
            ctx = request.farmer_context
            loc_parts = [p for p in [ctx.village, ctx.mandal, ctx.district, ctx.state] if p]
            loc_str = ", ".join(loc_parts) or "Not specified"
            user_sections.append(
                f"FARMER CONTEXT:\n"
                f"- Location: {loc_str}\n"
                f"- Existing Crop: {ctx.crop_name or 'Not specified'}\n"
                f"- Land Size: {f'{ctx.land_size_acres} acres' if ctx.land_size_acres else 'Not specified'}\n"
                f"- Soil Type: {ctx.soil_type or 'Not specified'}\n"
                f"- Water Source: {ctx.water_source or 'Not specified'}"
            )

        # Weather facts
        if request.weather_facts:
            wf_lines = []
            for wf in request.weather_facts:
                prefix = "[FORECAST]" if wf.is_forecast else "[OBSERVATION]"
                wf_lines.append(f"- {prefix} {wf.summary}")
            user_sections.append("WEATHER FACTS:\n" + "\n".join(wf_lines))

        # Approved Evidence
        if request.approved_evidence:
            ev_lines = []
            for ev in request.approved_evidence:
                loc = f"District: {ev.district or 'Statewide'}"
                valid = f"Valid: {ev.valid_from or 'N/A'} to {ev.valid_until or 'N/A'}"
                ev_lines.append(
                    f"EVIDENCE [{ev.evidence_id}] (Source: {ev.source_type}, {loc}, {valid}):\n"
                    f"Title: {ev.title}\n"
                    f"Content: {ev.content}"
                )
            user_sections.append("APPROVED AGRICULTURAL EVIDENCE:\n" + "\n\n".join(ev_lines))
        else:
            user_sections.append("APPROVED AGRICULTURAL EVIDENCE: None provided.")

        # Farmer Question
        user_sections.append(f"FARMER QUESTION: {request.farmer_question}")

        full_user_content = "\n\n".join(user_sections)
        messages.append({"role": "user", "content": full_user_content})
        return messages

    def _create_error_abstention(
        self, request: LLMReasoningRequest, error_code: str, error_detail: str
    ) -> LLMResponseSchema:
        """Create a safe abstention response when the LLM provider fails."""
        lang = (request.language or "Telugu").strip().lower()

        if "telugu" in lang:
            if request.channel == "telegram":
                fallback = (
                    "సాంకేతిక సమస్య వల్ల ప్రస్తుతం సమాధానం ఇవ్వలేకపోతున్నాను అండి. "
                    "దయచేసి మీ మండల వ్యవసాయ అధికారిని సంప్రదించండి."
                )
            else:
                fallback = (
                    "సాంకేతిక సమస్య కారణంగా ప్రస్తుతం సమాధానం ఇవ్వలేకపోతున్నాము. "
                    "దయచేసి మీ మండల వ్యవసాయ అధికారిని లేదా సహాయ కేంద్రాన్ని సంప్రదించండి."
                )
        elif "hindi" in lang:
            fallback = (
                "तकनीकी समस्या के कारण वर्तमान में उत्तर देने में असमर्थ हैं। "
                "कृपया अपने स्थानीय कृषि अधिकारी से संपर्क करें।"
            )
        else:
            fallback = (
                "Due to a technical service limitation, I cannot process your request right now. "
                "Please consult your local Agricultural Officer or local extension service."
            )

        return LLMResponseSchema(
            intent="service_failure",
            language=request.language,
            required_information=["System connectivity"],
            supported_facts=[],
            unsupported_questions=[request.farmer_question],
            abstain=True,
            response=fallback,
            evidence_citations=[],
            model_id=getattr(self.provider, "model_id", "unknown"),
            safety_status="ABSTAINED",
            safety_violations=[f"{error_code}: {error_detail}"],
        )

