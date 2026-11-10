"""
LLM Reasoning Service for KrishiVaani — Phase 7.2.
Orchestrates farmer query interpretation, evidence grounding,
Groq inference, and deterministic safety validation.
"""

import time
import logging
import re
from typing import Optional, List, Dict, Any, Protocol

from app.llm.schemas import (
    LLMReasoningRequest,
    LLMResponseSchema,
    FarmerContextSchema,
    ApprovedEvidenceItem,
    WeatherFactItem,
)
from app.llm.providers.groq_provider import GroqProvider
from app.llm.providers.sarvam_provider import SarvamProvider
from app.core.config import settings
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


def normalize_response_style(
    text: str, language: str = "Telugu", allow_follow_up: bool = False
) -> str:
    """Apply the short spoken-response style without cutting inside a sentence."""
    if not text:
        return text
    normalized = text.strip()
    is_telugu = language.casefold().startswith(("te", "telugu"))
    had_andi = is_telugu and bool(re.search(r"అండి", normalized))
    if not is_telugu:
        normalized = re.sub(r"\s*అండి\s*,?", "", normalized)
        normalized = re.sub(r"[ \t]{2,}", " ", normalized)
    else:
        normalized = re.sub(r"\s*అండి\s*,?", "", normalized)
    generic_closings = (
        r"ఇంకా ఏమైనా సందేహాలుంటే అడగండి\.?",
        r"దీని గురించి ఇంకేమైనా తెలుసుకోవాలంటే అడగండి\.?",
        r"Ask if you have another question\.?",
        r"If you have any other questions,? ask\.?",
        r"और कोई सवाल हो तो पूछिए\.?",
        r"क्या आप अपने खेत में इस व्यवस्था के बारे में और जानना चाहते हैं\??",
        r"இது எப்படி நடக்கிறது என்று உங்களுக்கு இன்னும் விரிவாக சொல்லட்டுமா\??",
        r"మీ ఊరి పేరు చెబితే.*?సమాచారం.*?(?:వెతకగలను|చెప్పగలను)\.?",
        r"మీ .*?(?:వివరాలు|పేరు) చెబితే.*?(?:సహాయం|సూచనలు).*?\??",
        r"For advice on your specific .*?please share .*?\.",
        r"If you want .*? tell me .*?\.",
        r"अगर आप .*? तो बताइए.*?\.",
        r"మీ పంటకు సంబంధించి ఏమైనా సందేహాలు ఉంటే అడగండి\.?",
        r"For specific management steps in your field, you will need to share your local location and crop details\.?",
    )
    normalized = re.sub(
        r"(?:^|(?<=[.!?।])\s+)(?:" + "|".join(generic_closings) + r")\s*",
        "",
        normalized,
        flags=re.IGNORECASE,
    ).strip()
    if not allow_follow_up:
        normalized = re.sub(r"(?:^|(?<=[.!?।])\s+)[^.!?।]*\?\s*", "", normalized).strip()
    if is_telugu and had_andi and normalized:
        terminal = re.search(r"([.!?।])\s*$", normalized)
        if terminal:
            normalized = (
                normalized[: terminal.start()].rstrip()
                + " అండి"
                + normalized[terminal.start() :]
            )
        else:
            normalized = normalized.rstrip() + " అండి"
    sentences = re.split(r"(?<=[.!?।])\s+", normalized)
    if len(sentences) > 4:
        normalized = " ".join(sentences[:4]).strip()
    return normalized


class LLMProvider(Protocol):
    model_id: str

    def generate_completion(
        self,
        messages: List[Dict[str, str]],
        json_mode: bool = True,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> LLMResponseSchema:
        ...

BASE_SYSTEM_INSTRUCTION = """You are కృషివాణి, an AI agricultural advisory assistant. Your name is exactly "కృషివాణి" and you are not a farmer.
Your primary mission is farmer safety, financial security, and strict evidence-grounded truth.

CORE ADVISORY RULES:
1. TIERED POLICY: For Tier 1 general explanatory questions, you may answer from general model knowledge and must not mention missing bulletins. For Tier 2 live weather, use only fetched weather facts. For Tier 3 consequential claims, use only explicitly supplied approved evidence; never invent crop, variety, sowing, chemical, dose, scheme eligibility/amount, price, yield, or profit claims.
2. MISSING PARAMETERS: If a farmer asks for crop, sowing, or management advice without necessary field parameters (such as specific mandal/village, season, soil condition, or water availability), DO NOT recommend a crop. Identify what is missing and ask concise clarifying questions.
3. PESTICIDES & FERTILIZERS: NEVER prescribe chemical pesticides, fungicides, or specific dosages without confirmed pest identification and approved evidence. Direct the farmer to consult the local Agricultural Officer (AO) or Krishi Vigyan Kendra (KVK).
4. WEATHER BOUNDARIES: When weather data is provided, distinguish between observed historical data and forecasts. Never claim soil moisture or irrigation need is known from rainfall amounts alone unless explicitly stated. Clearly distinguish between probabilistic forecasts and official IMD warnings. When answering purely meteorological weather questions where no agricultural database evidence was supplied, set "evidence_citations": [].
5. RESTRICTIONS: Preserve all geographical, crop, variety, and validity-period restrictions stated in the evidence.
6. SPOKEN VOICE OUTPUT: The "response" field must be natural, polite, and conversational for voice playback. Use 2-4 short complete sentences, no filler, no generic closing, repetition, follow-up questions, or offers to search/tell more for Tier 1 general questions. State only what you can do now; do not ask for village, land size, or water source for general questions. Use "అండి" only when the target language is Telugu; never use it in other languages. In Telugu, use it at most once at the end of the final sentence.

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

TELEGRAM_SYSTEM_INSTRUCTION = """You are కృషివాణి, an AI agricultural advisory assistant. Your assistant name is exactly "కృషివాణి"; you are not a farmer.
Your primary mission is farmer safety, financial security, and strict evidence-grounded truth.

CORE ADVISORY RULES:
1. TIERED POLICY: For Tier 1 general explanatory questions, you may answer from general model knowledge and must not mention missing bulletins. For Tier 2 live weather, use only fetched weather facts. For Tier 3 consequential claims, use only explicitly supplied approved evidence; never invent crop, variety, sowing, chemical, dose, scheme eligibility/amount, price, yield, or profit claims.
2. MISSING PARAMETERS: If a farmer asks for crop, sowing, or management advice without necessary field parameters (such as specific mandal/village, season, soil condition, or water availability), DO NOT recommend a crop. Identify what is missing and ask concise clarifying questions.
3. PESTICIDES & FERTILIZERS: NEVER prescribe chemical pesticides, fungicides, or specific dosages without confirmed pest identification and approved evidence. Direct the farmer to consult the local Agricultural Officer (AO) or Krishi Vigyan Kendra (KVK).
4. WEATHER BOUNDARIES: When weather data is provided, distinguish between observed historical data and forecasts. Never claim soil moisture or irrigation need is known from rainfall amounts alone unless explicitly stated. Clearly distinguish between probabilistic forecasts and official IMD warnings. When answering purely meteorological weather questions where no agricultural database evidence was supplied, set "evidence_citations": [].
5. RESTRICTIONS: Preserve all geographical, crop, variety, and validity-period restrictions stated in the evidence.
6. SPOKEN VOICE OUTPUT & NATURAL CONVERSATIONAL TELUGU (Telegram Channel):
   - Use evidence only when it is directly relevant to the farmer's question; ignore unrelated weather or safety evidence.
   - If evidence only partly covers the question, give the supported part first, then clearly say what is missing.
   - Answer in 2-4 short complete sentences. Never stop mid-sentence, use filler, generic closing lines, repetition, follow-up questions, or offers to search/tell more for Tier 1 general questions. State only what you can do now; do not ask for village, land size, or water source for general questions.
   - Use "అండి" only for Telugu responses. Never include it in any non-Telugu response.
   - The "response" field must be natural, polite, and conversational for voice playback. Keep sentences short and clear. Avoid markdown formatting, tables, asterisks, and NEVER use parentheses () anywhere in your Telugu response.
   - For Telugu (te-IN or Telugu):
     * Use natural everyday conversational Telugu (Telangana conversational style, friendly, positive, and respectful with 'అండి').
     * Personality: Speak like a patient, knowledgeable, friendly local agricultural advisor having a face-to-face chat — never like a government form, automated questionnaire, or scripted survey. Never blame or discourage farmers, and stay calm and realistic without empty hype or exaggerated promises.
     * NATURAL SENTENCE FRAMING & 'అండి' PLACEMENT:
       - NEVER begin every sentence or response automatically with 'అండి,' (for example, avoid "అండి, మీరు వరి పంటకు ఏ రకమైన నీటి వనరును (బోరు, కాలువ, వర్షపు నీరు) ఉపయోగిస్తున్నారు?").
       - Use 'అండి' naturally at the end of a sentence or clause where politeness fits naturally, and avoid repeating greetings like 'నమస్తే' or 'హలో' in regular responses unless the farmer just greeted you.
       - Instead of parenthetical lists, ask naturally and briefly explain why the detail helps (e.g., "వరి పంటకు మీరు ఏ నీటిని ఉపయోగిస్తున్నారు? బోరు నీరా, కాలువ నీరా, లేక వర్షపు నీరా? మీ పరిస్థితికి తగ్గట్టు మంచి సూచనలు చెప్పడానికి అడుగుతున్నాను.").
     * Tone: Avoid Sanskritised, literary (Granthika), or bureaucratic vocabulary (e.g. NEVER use 'సమ్మతి', 'భౌగోళిక స్థానం', 'దృక్పథం', 'ప్రణాళిక', 'అనుమతి', 'వనరు', 'పరిశీలన'). Avoid exaggerated slang.
     * Code-mixing & Pronunciation: Avoid excessive English mixing. Use familiar everyday agricultural terms and write abbreviations/units cleanly in Telugu so speech synthesis pronounces them smoothly: Urea (యూరియా), DAP (డీఏపీ), Potash (పొటాష్), Fertilizer (ఎరువు), Pesticide (పురుగు మందు), Spraying (మందు కొట్టడం / స్ప్రే చేయడం), Tractor (ట్రాక్టర్), Borewell (బోరు), Motor (మోటారు), Drip (డ్రిప్), PIN code (పిన్ కోడ్), Location (లొకేషన్), Soil test (మట్టి పరీక్ష), KVK (కేవీకే / కృషి విజ్ఞాన కేంద్రం), Agriculture Officer (AO సార్ / ఏఓ గారు / వ్యవసాయ అధికారి), Acre (ఎకరం), Gunta (గుంట). Write 'శాతం' instead of '%', 'మిల్లీమీటర్లు' instead of 'mm', and 'డిగ్రీల సెల్సియస్' instead of '°C'.
     * Helpful First, One Question at a Time: Give useful, verified facts FIRST before asking any follow-up question. When missing field details, ASK ONLY ONE PRIMARY QUESTION AT A TIME (e.g., 'మీరు ఏ పంట వేశారు?', 'ఎన్ని ఎకరాలు ఉంది?', 'బోరు నీళ్లా, కాలువ నీళ్లా?') and briefly say why it helps.
     * Sentence length & Accuracy: Keep sentences short and clear (default 2-3 concise spoken sentences unless safety requires more). Always preserve exact validated numbers, dates, units, and percentages.
     * Weather responses: Use natural words such as 'వాన', 'ఊరు', 'రేపు', 'వాతావరణ రిపోర్ట్'. Never invent a rainfall value or claim absolute certainty. State forecast uncertainty accurately using the exact numbers provided (e.g., 'రేపు మీ ఊరిలో వాన పడే అవకాశం చాలా తక్కువగా ఉంది', 'వాతావరణ రిపోర్ట్ అంచనా మాత్రమే, మారొచ్చు').
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

    def __init__(self, provider: Optional[LLMProvider] = None, validator: Optional[LLMSafetyValidator] = None):
        self.provider = provider or self._create_default_provider()
        self.validator = validator or LLMSafetyValidator()

    @staticmethod
    def _create_default_provider() -> LLMProvider:
        provider_name = (getattr(settings, "LLM_PROVIDER", "groq") or "groq").strip().lower()
        if provider_name == "sarvam":
            return SarvamProvider()
        if provider_name == "groq":
            return GroqProvider()
        raise ValueError(f"Unsupported LLM_PROVIDER '{provider_name}'. Expected 'groq' or 'sarvam'.")

    def process_query(self, request: LLMReasoningRequest) -> LLMResponseSchema:
        """
        Process a farmer reasoning query with full evidence constraints and safety validation.
        """
        # 1. Build messages payload
        messages = self._build_prompt_messages(request)

        # 2. Execute LLM completion via provider
        try:
            raw_response = self.provider.generate_completion(messages=messages, json_mode=True)
        except LLMError as e:
            if isinstance(self.provider, SarvamProvider):
                return self._try_groq_fallback(request, messages, e)
            logger.error("LLM Provider execution failure: %s", str(e))
            error_code = "PROVIDER_NOT_CONFIGURED" if isinstance(e, LLMProviderNotConfiguredError) else (
                "MALFORMED_RESPONSE" if isinstance(e, LLMMalformedResponseError) else type(e).__name__
            )
            return self._create_error_abstention(request, error_code, str(e))
        except Exception as e:
            if isinstance(self.provider, SarvamProvider):
                return self._try_groq_fallback(request, messages, e)
            logger.error("Unexpected error in LLM reasoning service: %s", str(e))
            return self._create_error_abstention(request, "UNEXPECTED_ERROR", str(e))

        raw_response.evidence_citations = [
            re.sub(r"^\s*EVIDENCE\s*\[\s*|\s*\]\s*$", "", citation, flags=re.IGNORECASE).strip()
            for citation in raw_response.evidence_citations
        ]

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
        allow_follow_up = validated_response.intent in {
            "crop_recommendation",
            "pest_disease_inquiry",
            "fertilizer_guidance",
            "government_scheme",
        }
        validated_response.response = normalize_response_style(
            validated_response.response,
            validated_response.language or request.language,
            allow_follow_up=allow_follow_up,
        )
        if validated_response.safety_status == "REJECTED":
            validated_response.response = self._localized_safety_fallback(request.language)

        return validated_response

    def _try_groq_fallback(
        self, request: LLMReasoningRequest, messages: List[Dict[str, str]], sarvam_error: Exception
    ) -> LLMResponseSchema:
        logger.warning("Sarvam failed with %s; trying Groq fallback once.", type(sarvam_error).__name__)
        try:
            raw_response = GroqProvider().generate_completion(messages=messages, json_mode=True)
        except LLMError as fallback_error:
            logger.error("Groq fallback failed after Sarvam error: %s", str(fallback_error))
            error_code = "PROVIDER_NOT_CONFIGURED" if isinstance(fallback_error, LLMProviderNotConfiguredError) else (
                "MALFORMED_RESPONSE" if isinstance(fallback_error, LLMMalformedResponseError) else type(fallback_error).__name__
            )
            return self._create_error_abstention(request, error_code, str(fallback_error))
        except Exception as fallback_error:
            logger.error("Groq fallback failed after Sarvam error: %s", str(fallback_error))
            return self._create_error_abstention(request, "UNEXPECTED_ERROR", str(fallback_error))

        raw_response.evidence_citations = [
            re.sub(r"^\s*EVIDENCE\s*\[\s*|\s*\]\s*$", "", citation, flags=re.IGNORECASE).strip()
            for citation in raw_response.evidence_citations
        ]
        t_val_start = time.perf_counter_ns()
        try:
            validated_response = self.validator.validate(request, raw_response)
        except Exception as validation_error:
            logger.error("Fail-closed after Groq fallback: %s", str(validation_error), exc_info=True)
            validated_response = self._create_error_abstention(
                request, "SAFETY_VALIDATION_ERROR", f"Safety validation exception (fail-closed): {str(validation_error)}"
            )
            validated_response.safety_status = "REJECTED"
        validated_response.validation_latency_ms = round(
            (time.perf_counter_ns() - t_val_start) / 1_000_000.0, 3
        )
        allow_follow_up = validated_response.intent in {
            "crop_recommendation",
            "pest_disease_inquiry",
            "fertilizer_guidance",
            "government_scheme",
        }
        validated_response.response = normalize_response_style(
            validated_response.response,
            validated_response.language or request.language,
            allow_follow_up=allow_follow_up,
        )
        if validated_response.safety_status == "REJECTED":
            validated_response.response = self._localized_safety_fallback(request.language)
        return validated_response

    @staticmethod
    def _localized_safety_fallback(language: str) -> str:
        normalized = (language or "").casefold()
        if normalized.startswith(("hi", "hindi")):
            return "इस सवाल के लिए मेरे पास अभी सत्यापित जानकारी नहीं है। कृपया अपने स्थानीय कृषि अधिकारी या निकटतम KVK से सलाह लें।"
        if normalized.startswith(("mr", "marathi")):
            return "या प्रश्नासाठी माझ्याकडे सध्या पडताळलेली माहिती नाही. कृपया स्थानिक कृषी अधिकारी किंवा जवळच्या KVK शी संपर्क करा."
        if normalized.startswith(("ta", "tamil")):
            return "இந்தக் கேள்விக்கு என்னிடம் தற்போது சரிபார்க்கப்பட்ட தகவல் இல்லை. உள்ளூர் வேளாண்மை அதிகாரி அல்லது அருகிலுள்ள KVK-யை அணுகுங்கள்."
        if normalized.startswith(("kn", "kannada")):
            return "ಈ ಪ್ರಶ್ನೆಗೆ ನನ್ನ ಬಳಿ ಈಗ ಪರಿಶೀಲಿತ ಮಾಹಿತಿ ಇಲ್ಲ. ಸ್ಥಳೀಯ ಕೃಷಿ ಅಧಿಕಾರಿ ಅಥವಾ ಹತ್ತಿರದ KVK ಅನ್ನು ಸಂಪರ್ಕಿಸಿ."
        if normalized.startswith(("ml", "malayalam")):
            return "ഈ ചോദ്യത്തിന് ഇപ്പോൾ പരിശോധിച്ച വിവരം എന്റെ പക്കൽ ഇല്ല. പ്രാദേശിക കൃഷി ഉദ്യോഗസ്ഥനെയോ അടുത്തുള്ള KVK-യെയോ ബന്ധപ്പെടൂ."
        if normalized.startswith(("pa", "punjabi")):
            return "ਇਸ ਸਵਾਲ ਲਈ ਮੇਰੇ ਕੋਲ ਇਸ ਵੇਲੇ ਪ੍ਰਮਾਣਿਤ ਜਾਣਕਾਰੀ ਨਹੀਂ ਹੈ। ਆਪਣੇ ਸਥਾਨਕ ਖੇਤੀਬਾੜੀ ਅਧਿਕਾਰੀ ਜਾਂ ਨੇੜਲੇ KVK ਨਾਲ ਸੰਪਰਕ ਕਰੋ।"
        if normalized.startswith(("bn", "bengali")):
            return "এই প্রশ্নের জন্য আমার কাছে এখন যাচাই করা তথ্য নেই। স্থানীয় কৃষি আধিকারিক বা নিকটস্থ KVK-এর সঙ্গে যোগাযোগ করুন।"
        if normalized.startswith(("gu", "gujarati")):
            return "આ પ્રશ્ન માટે મારી પાસે હાલમાં ચકાસેલી માહિતી નથી. સ્થાનિક કૃષિ અધિકારી અથવા નજીકના KVKનો સંપર્ક કરો."
        if normalized.startswith(("te", "telugu")):
            return "ఈ ప్రశ్నకు ప్రస్తుతం నా దగ్గర నిర్ధారించిన సమాచారం లేదు. మీ స్థానిక వ్యవసాయ అధికారిని లేదా దగ్గర్లోని కేవీకేను సంప్రదించండి."
        return "I do not have verified information for this question yet. Please consult your local Agricultural Officer or nearest KVK."

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
            if ctx.conversation_memory:
                user_sections.append(f"FARMER CONVERSATION CONTEXT:\n{ctx.conversation_memory}")

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
            if error_code == "LLMRateLimitError":
                fallback = (
                    "అండి, ప్రస్తుతం చాలా మంది అడుగుతున్నారు. కొన్ని సెకన్లు ఆగి మళ్లీ అడగండి."
                )
            elif request.channel == "telegram":
                fallback = (
                    "సాంకేతిక సమస్య వల్ల ప్రస్తుతం సమాధానం ఇవ్వలేకపోతున్నాను అండి. "
                    "అత్యవసరమైతే మీ స్థానిక వ్యవసాయ అధికారిని అడగండి, లేదా కాసేపటి తర్వాత మళ్ళీ అడగండి."
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
