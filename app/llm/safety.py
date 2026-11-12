"""
Independent Deterministic Safety Layer for KrishiVaani LLM Reasoning — Phase 7.2.

Enforces deterministic Python checks on LLM outputs before they can reach farmers.
Validates evidence references, approval status, expiration, geographic match,
and strictly rejects unsupported crop, pesticide, fertilizer, or numerical claims.

VALIDATION LIMITATIONS:
Deterministic regex and keyword/entity matching provide rigorous baseline enforcement
against known dosage patterns, unapproved citations, and forbidden inferences,
but cannot guarantee 100% semantic proof of all possible natural language edge cases.
It operates as an independent layer of defense in depth alongside prompt-level constraints.
"""

import re
import logging
from typing import List, Dict, Any, Optional, Set
from datetime import datetime, date

from app.llm.schemas import (
    LLMReasoningRequest,
    LLMResponseSchema,
    ApprovedEvidenceItem,
    WeatherFactItem,
)

logger = logging.getLogger(__name__)

# Common chemical insecticides/pesticides monitored for unverified prescription
MONITORED_CHEMICALS = {
    "monocrotophos", "chlorpyrifos", "imidacloprid", "carbaryl",
    "acephate", "cypermethrin", "dimethoate", "triazophos",
    "profenofos", "fipronil", "thiamethoxam", "spinosad",
    "chlorantraniliprole", "coragen", "indoxacarb", "endosulfan",
}

# Regex patterns for actionable numerical dosages: e.g. "2 ml per liter", "50 kg/acre", "25 kg DAP per acre"
DOSAGE_PATTERN = re.compile(
    r"\b\d+(?:\.\d+)?\s*(?:ml|g|gm|kg|litres?|liters?|ltr)(?:\s+(?:of\s+)?[a-zA-Z]+)?\s*(?:per|\/)\s*(?:acre|ha|hectare|liter|litre|l\b)",
    re.IGNORECASE,
)

# Regex pattern for fabricated yields: e.g. "25 quintals", "15 bags", "20 క్వింటాళ్లు"
YIELD_PATTERN = re.compile(
    r"\b\d+(?:\.\d+)?\s*(?:quintals?|bags|క్వింటా|బస్తా)",
    re.IGNORECASE,
)

# Regex pattern for fabricated financial claims: e.g. "Rs. 25000", "50000 rupees", "20000 రూపాయలు"
FINANCIAL_PATTERN = re.compile(
    r"(?:rs\.?|rupees?|inr|₹|రూపాయ)\s*\d+(?:,\d+)?|\b\d+(?:,\d+)?\s*(?:rs|rupees|రూపాయ)",
    re.IGNORECASE,
)

# Actionable crop recommendation phrases in English and Telugu
ACTIONABLE_CROP_PHRASES_EN = [
    "you should grow", "you should plant", "i recommend growing", "i recommend planting",
    "plant jowar", "plant cotton", "plant maize", "grow groundnut", "grow pulses",
    "suitable crop for you is", "the best crop for you is",
]

ACTIONABLE_CROP_PHRASES_TE = [
    "పంట వేయండి", "సాగు చేయండి", "సిఫార్సు చేస్తున్నాము", "సిఫార్సు చేయబడింది",
    "పంట వేసుకోవచ్చు", "సాగు చేసుకోవచ్చు",
]

# Common government schemes monitored for ungrounded citations
MONITORED_SCHEMES = [
    "rythu bandhu", "rythu bima", "pm-kisan", "pm kisan", "kalia", "rythu bharosa"
]


class LLMSafetyValidator:
    """
    Deterministic validator enforcing agricultural safety boundaries on LLM outputs.
    Replaces any violating output with a structured, safe abstention.
    """

    @classmethod
    def validate(cls, request: LLMReasoningRequest, output: LLMResponseSchema) -> LLMResponseSchema:
        """
        Execute all deterministic safety checks.
        If any check fails, mutates the output into a safe abstention and logs the violation.
        """
        violations: List[str] = []

        # 1. Evidence Existence & Unknown Citation Check
        cls._check_unknown_evidence_references(request, output, violations)

        # 2. Source Approval Status Check
        cls._check_source_approval_status(request, output, violations)

        # 3. Advisory Expiration Check
        cls._check_advisory_expiration(request, output, violations)

        # 4. Geographic Applicability Check
        cls._check_geographic_applicability(request, output, violations)

        # 5. Unsupported Actionable Crop Recommendations Check
        cls._check_unsupported_crop_recommendations(request, output, violations)

        # 6. Unsupported Pesticide and Fertilizer Dosages Check
        cls._check_unsupported_chemical_dosages(request, output, violations)

        # 7. Weather Forecast Alone Triggering Crop Advice Check
        cls._check_forecast_alone_crop_advice(request, output, violations)

        # 8. Unsupported Numerical and Scheme Claims Check
        cls._check_unsupported_numbers_and_schemes(request, output, violations)

        # 9. Echoed Input Question Check
        cls._check_echoed_input_question(request, output, violations)

        if violations:
            logger.warning("Deterministic safety validation FAILED with %d violations: %s", len(violations), violations)
            return cls._create_safe_abstention(request, output, violations)

        # If model voluntarily abstained, ensure status is ABSTAINED
        if output.abstain:
            output.safety_status = "ABSTAINED"
            output.safety_violations = []
            return output

        output.safety_status = "PASSED"
        output.safety_violations = []
        return output

    @classmethod
    def _check_unknown_evidence_references(
        cls, request: LLMReasoningRequest, output: LLMResponseSchema, violations: List[str]
    ) -> None:
        """Reject outputs referencing evidence IDs not present in the supplied request."""
        valid_ids: Set[str] = {item.evidence_id for item in request.approved_evidence}

        # Check explicit citations
        for cite_id in output.evidence_citations:
            if cite_id not in valid_ids:
                # Meteorological context / weather facts are not database knowledge items.
                # If weather facts were supplied and this citation references weather data, allow it.
                if request.weather_facts:
                    cite_lower = cite_id.lower()
                    if any(kw in cite_lower for kw in ("weather", "imd", "forecast", "observation", "rain", "temp", "grid", "model")):
                        continue
                violations.append(f"Referenced unknown evidence citation '{cite_id}' not in supplied evidence set.")

        # Scan supported_facts and response for citation patterns
        text_to_scan = " ".join(output.supported_facts) + " " + output.response
        found_ids = set(re.findall(r"\bKNOW-[A-Za-z0-9_-]+\b", text_to_scan))
        for fid in found_ids:
            if fid not in valid_ids:
                violations.append(f"Detected unknown knowledge ID reference '{fid}' in output text.")

    @classmethod
    def _check_source_approval_status(
        cls, request: LLMReasoningRequest, output: LLMResponseSchema, violations: List[str]
    ) -> None:
        """Ensure unapproved or pending knowledge items are never used as factual foundation."""
        for item in request.approved_evidence:
            if item.verification_status != "APPROVED":
                # If model cites or uses unapproved item in supported_facts
                if item.evidence_id in output.evidence_citations:
                    violations.append(
                        f"Cited unapproved evidence item '{item.evidence_id}' (status: {item.verification_status})."
                    )

    @classmethod
    def _check_advisory_expiration(
        cls, request: LLMReasoningRequest, output: LLMResponseSchema, violations: List[str]
    ) -> None:
        """Reject actionable advice derived from expired advisories."""
        as_of = cls._parse_iso_date(request.as_of_date) or date.today()

        for item in request.approved_evidence:
            if item.valid_until:
                until_date = cls._parse_iso_date(item.valid_until)
                if until_date and until_date < as_of:
                    # Advisory is expired
                    if item.evidence_id in output.evidence_citations and not output.abstain:
                        violations.append(
                            f"Advisory '{item.evidence_id}' expired on {item.valid_until} (as of {as_of.isoformat()}). Cannot provide active recommendations."
                        )

    @classmethod
    def _check_geographic_applicability(
        cls, request: LLMReasoningRequest, output: LLMResponseSchema, violations: List[str]
    ) -> None:
        """Verify evidence is geographically compatible with the farmer's district."""
        if not request.farmer_context or not request.farmer_context.district:
            return

        farmer_district = request.farmer_context.district.strip().lower()

        # If evidence items exist, check if all of them are for a different district
        evidence_districts = {
            item.district.strip().lower() for item in request.approved_evidence if item.district
        }

        # If all supplied items are strictly for other districts, and output did not abstain or qualify
        if evidence_districts and farmer_district not in evidence_districts:
            # Check if model gave actionable recommendation without noting district restriction
            if not output.abstain and ("not applicable" not in output.response.lower() and "చెల్లదు" not in output.response):
                violations.append(
                    f"Geographic mismatch: Farmer is in '{farmer_district}', but supplied evidence is for {evidence_districts}."
                )

    @classmethod
    def _check_unsupported_crop_recommendations(
        cls, request: LLMReasoningRequest, output: LLMResponseSchema, violations: List[str]
    ) -> None:
        """Prevent recommending crops when no approved crop evidence supports it."""
        approved_crops: Set[str] = {
            item.crop_name.strip().lower() for item in request.approved_evidence if item.crop_name
        }

        text_lower = output.response.lower()

        # Check actionable phrases
        has_actionable_en = any(phrase in text_lower for phrase in ACTIONABLE_CROP_PHRASES_EN)
        has_actionable_te = any(phrase in text_lower for phrase in ACTIONABLE_CROP_PHRASES_TE)

        if (has_actionable_en or has_actionable_te) and not approved_crops:
            # Model made an actionable crop recommendation with ZERO approved crop evidence
            violations.append("Made actionable crop recommendation without approved supporting crop evidence.")

    @classmethod
    def _check_unsupported_chemical_dosages(
        cls, request: LLMReasoningRequest, output: LLMResponseSchema, violations: List[str]
    ) -> None:
        """Reject unverified chemical pesticide and fertilizer dosages not in approved evidence."""
        # Gather all evidence text
        evidence_text = " ".join(item.content for item in request.approved_evidence).lower()

        # 1. Check for dosage regex patterns in response
        dosage_matches = DOSAGE_PATTERN.findall(output.response)
        for match in dosage_matches:
            if match.lower() not in evidence_text:
                violations.append(f"Prescribed unsupported chemical/fertilizer dosage '{match}' not found in approved evidence.")

        # 2. Check for monitored chemical names
        response_words = set(re.findall(r"\b[a-z]+\b", output.response.lower()))
        for chemical in MONITORED_CHEMICALS:
            if chemical in response_words and chemical not in evidence_text:
                violations.append(f"Prescribed unverified chemical pesticide '{chemical}' not found in approved evidence.")

    @classmethod
    def _check_forecast_alone_crop_advice(
        cls, request: LLMReasoningRequest, output: LLMResponseSchema, violations: List[str]
    ) -> None:
        """Prevent weather forecasts alone from triggering crop advice without agronomic advisories."""
        has_forecast = any(wf.is_forecast for wf in request.weather_facts)
        has_crop_evidence = any(item.crop_name for item in request.approved_evidence)

        if has_forecast and not has_crop_evidence:
            text_lower = output.response.lower()
            if any(phrase in text_lower for phrase in ACTIONABLE_CROP_PHRASES_EN + ACTIONABLE_CROP_PHRASES_TE):
                violations.append("Weather forecast alone cannot trigger crop recommendations without an approved agronomic advisory.")

    @classmethod
    def _check_unsupported_numbers_and_schemes(
        cls, request: LLMReasoningRequest, output: LLMResponseSchema, violations: List[str]
    ) -> None:
        """Reject fabricated yield numbers, market prices, or ungrounded scheme names."""
        evidence_text = " ".join(item.content for item in request.approved_evidence).lower()

        # Check yield fabrication
        yield_matches = YIELD_PATTERN.findall(output.response)
        for y in yield_matches:
            if y.lower() not in evidence_text:
                violations.append(f"Fabricated unsupported yield claim '{y}' without supporting evidence.")

        # Check financial fabrication
        fin_matches = FINANCIAL_PATTERN.findall(output.response)
        for f in fin_matches:
            if f.lower() not in evidence_text:
                violations.append(f"Fabricated unsupported financial claim '{f}' without supporting evidence.")

        # Check government scheme names
        for scheme in MONITORED_SCHEMES:
            if scheme in output.response.lower() and scheme not in evidence_text:
                violations.append(f"Cited ungrounded government scheme '{scheme}' not in approved evidence.")

    @classmethod
    def _check_echoed_input_question(
        cls, request: LLMReasoningRequest, output: LLMResponseSchema, violations: List[str]
    ) -> None:
        """Reject assistant responses that simply repeat or echo the farmer's input question."""
        if not output.response or not request.farmer_question:
            return
        resp_clean = output.response.strip().strip(" !?,.:;~`'\"|•\t\n\r\u0964\u0965").lower()
        q_clean = request.farmer_question.strip().strip(" !?,.:;~`'\"|•\t\n\r\u0964\u0965").lower()
        if resp_clean and resp_clean == q_clean:
            violations.append("Assistant response simply repeated or echoed the input farmer question.")

    @classmethod
    def _create_safe_abstention(
        cls, request: LLMReasoningRequest, output: LLMResponseSchema, violations: List[str]
    ) -> LLMResponseSchema:
        """Generate a safe, voice-friendly abstention response in the requested language."""
        lang = (request.language or "Telugu").strip().lower()

        if getattr(request, "channel", None) == "telegram":
            fallback_text = (
                "దీని గురించి పూర్తిగా నిర్ధారించిన వివరాలు నా దగ్గర ప్రస్తుతం లేవు . "
                "మీ పొలం పరిస్థితికి తగ్గట్టు సరైన సలహా కోసం మీ మండల వ్యవసాయ అధికారిని గానీ, దగ్గర్లో ఉన్న కృషి విజ్ఞాన కేంద్రాన్ని గానీ అడగండి."
            )
        elif "telugu" in lang:
            fallback_text = (
                "క్షమించండి, మీ ప్రశ్నకు ఖచ్చితమైన సమాధానం ఇవ్వడానికి అధికారిక ఆధారాలు అందుబాటులో లేవు. "
                "దయచేసి మీ మండల వ్యవసాయ అధికారిని (AO) లేదా దగ్గరి కృషి విజ్ఞాన కేంద్రాన్ని (KVK) సంప్రదించండి."
            )
        elif "hindi" in lang:
            fallback_text = (
                "क्षमा करें, आपके प्रश्न का सटीक उत्तर देने के लिए आधिकारिक साक्ष्य उपलब्ध नहीं हैं। "
                "कृपया अपने स्थानीय कृषि अधिकारी या कृषि विज्ञान केंद्र (KVK) से संपर्क करें।"
            )
        else:
            fallback_text = (
                "I apologize, but verified official evidence is not available to answer your request safely. "
                "Please contact your local Agricultural Officer (AO) or nearest Krishi Vigyan Kendra (KVK) for verified guidance."
            )

        return LLMResponseSchema(
            intent=output.intent or "unsupported_inquiry",
            language=request.language,
            required_information=output.required_information or [
                "Exact village and mandal", "Soil test report", "Verified PJTAU/TGDPS advisory"
            ],
            supported_facts=[],
            unsupported_questions=[request.farmer_question],
            abstain=True,
            response=fallback_text,
            evidence_citations=[],
            model_id=output.model_id,
            latency_ms=output.latency_ms,
            usage=output.usage,
            safety_violations=violations,
            safety_status="REJECTED",
        )

    @staticmethod
    def _parse_iso_date(date_str: Optional[str]) -> Optional[date]:
        """Safely parse YYYY-MM-DD date string."""
        if not date_str:
            return None
        try:
            return datetime.strptime(date_str.strip()[:10], "%Y-%m-%d").date()
        except Exception:
            return None

