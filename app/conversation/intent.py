"""
Intent Classification and Routing Module for KrishiVaani — Phase 7.5 / 8.9.

Provides multilingual intent classification (Telugu, Hindi, English) for routing
inquiries to appropriate data retrieval pipelines (weather, agronomic evidence, schemes).

Phase 8.9: Added is_lightning_safety_query() to detect thunderstorm/lightning precaution
questions and prevent them from being incorrectly routed through the weather forecast
gate (which requires weather-provider consent and location).
"""

import re
from typing import Tuple

# Standard Intent Constants
INTENT_WEATHER_INQUIRY = "weather_inquiry"
INTENT_CROP_RECOMMENDATION = "crop_recommendation"
INTENT_PEST_DISEASE_INQUIRY = "pest_disease_inquiry"
INTENT_FERTILIZER_GUIDANCE = "fertilizer_guidance"
INTENT_GOVERNMENT_SCHEME = "government_scheme"
INTENT_AGRICULTURAL_ADVICE = "agricultural_advice"
INTENT_GENERAL_CONVERSATION = "general_conversation"

# Weather keyword patterns across Telugu, Hindi, English
WEATHER_KEYWORDS_TE = [
    "వాతావరణ", "వాతావరణం", "వర్ష", "వర్షం", "వర్షాలు", "వాన", "వానలు", "ఉష్ణోగ్రత", "ఎండ", "చలి", "గాలి",
    "తేమ", "వర్షపాతం", "మేఘాలు", "తుఫాను", "ఉరుములు", "హెచ్చరిక", "హెచ్చరికలు", "అలర్ట్",
]

WEATHER_KEYWORDS_HI = [
    "मौसम", "बारिश", "वर्षा", "तापमान", "धूप", "हवा", "आर्द्रता",
    "बादल", "तूफान", "कोहरा", "ठंड", "चेतावनी", "चेतावनियां", "अलर्ट",
]

WEATHER_KEYWORDS_EN = [
    "weather", "rain", "rainfall", "temperature", "forecast", "precipitation",
    "climate", "humidity", "wind", "storm", "cyclone", "cloud", "heat",
    "warning", "warnings", "alert", "alerts",
]

# Weather warning specific keywords (Phase 7.8)
WARNING_KEYWORDS_TE = ["హెచ్చరిక", "హెచ్చరికలు", "అలర్ట్", "తీవ్ర హెచ్చరిక"]
WARNING_KEYWORDS_HI = ["चेतावनी", "चेतावनियां", "अलर्ट"]
WARNING_KEYWORDS_EN = ["warning", "warnings", "alert", "alerts", "hazard", "severe weather", "imd warning"]

# Fertilizer and Nutrient management keywords
FERTILIZER_KEYWORDS_TE = [
    "ఎరువు", "ఎరువులు", "యూరియా", "డిఎపి", "పోటాష్", "ఎన్పికె", "పోషక", "పోషకాలు",
    "సూక్ష్మ పోషకాలు", "జింక్", "బోరాన్", "సేంద్రీయ ఎరువు", "రసాయన ఎరువు", "వర్మీ కంపోస్ట్",
    "పశువుల ఎరువు", "ఎరువుల మోతాదు", "ఎరువు వేయాలి", "ఎరువులు వేయాలి", "భూసార",
    "నేల సారం", "నేల పరీక్ష", "భూసార పరీక్ష", "నేల సారము",
]

FERTILIZER_KEYWORDS_HI = [
    "उर्वरक", "खाद", "यूरिया", "डीएपी", "पोटाश", "एनपीके", "पोषक तत्व", "सूक्ष्म पोषक",
    "जिंक", "बोरॉन", "जैविक खाद", "रासायनिक खाद", "कम्पोस्ट", "गोबर खाद", "खाद की मात्रा",
    "मिट्टी परीक्षण", "उर्वरक की सिफारिश", "उर्वरता", "मिट्टी की उर्वरता", "मृदा परीक्षण",
]

FERTILIZER_KEYWORDS_EN = [
    "fertilizer", "fertiliser", "urea", "dap", "potash", "mop", "npk", "nutrient",
    "nutrients", "soil fertility", "soil test", "biofertilizer", "manure", "compost",
    "micronutrient", "zinc sulfate", "fertilizer dosage", "fertilizer dose", "top dressing",
    "basal application", "fertigation",
]

# Crop recommendation keywords
CROP_RECOMMENDATION_KEYWORDS_TE = [
    "ఏ పంట", "పంట వేయాలి", "పంట సాగు", "ఏ విత్తనం", "పంట సిఫార్సు",
    "విత్తనాలు వేసుకోవచ్చా", "ఏది మంచిది", "ఏ పంట లాభం",
]

CROP_RECOMMENDATION_KEYWORDS_HI = [
    "कौन सी फसल", "फसल बोएं", "फसल की बुवाई", "कौन सा बीज", "फसल सिफारिश",
    "कौन सी फसल उपयुक्त", "कौन सी फसल अच्छी",
]

CROP_RECOMMENDATION_KEYWORDS_EN = [
    "which crop", "what crop", "recommend a crop", "crop recommendation",
    "should i plant", "should i grow", "best crop to sow", "suitable crop",
]

# Pest and Disease keywords (dosage removed to prevent fertilizer dosage collision)
PEST_DISEASE_KEYWORDS_TE = [
    "పురుగు", "తెగులు", "పురుగు మందు", "కీటకాలు", "ఆకు ముడత",
    "రసం పీల్చే", "నివారణ", "తెగుళ్ళు", "కలుపు", "కలుపు మందు",
    "పురుగుల మందు", "పురుగు మందు మోతాదు",
]

PEST_DISEASE_KEYWORDS_HI = [
    "कीट", "रोग", "कीटनाशक", "कीटनाशक दवा", "इल्ली", "पत्ती मरोड़",
    "कीड़े", "रोग रोकथाम", "फफूंद", "खरपतवार", "खरपतवार नाशक",
]

PEST_DISEASE_KEYWORDS_EN = [
    "pest", "disease", "insect", "pesticide", "fungicide", "insecticide",
    "herbicide", "weedicide", "infestation", "blight", "caterpillar",
    "leaf curl", "stem borer", "bollworm", "aphid", "whitefly", "mite",
    "thrips", "rust", "wilt", "rot", "pesticide dosage", "spray dosage",
]

# Government scheme keywords
SCHEME_KEYWORDS_TE = [
    "రైతు బంధు", "రైతు బీమా", "రైతు భరోసా", "పీఎం కిసాన్", "సబ్సిడీ", "రుణమాఫీ", "పథకం",
]

SCHEME_KEYWORDS_HI = [
    "पीएम किसान", "सब्सिडी", "ऋण माफी", "योजना", "फसल बीमा", "मुआवजा",
]

SCHEME_KEYWORDS_EN = [
    "rythu bandhu", "rythu bima", "rythu bharosa", "pm kisan", "pm-kisan",
    "subsidy", "scheme", "loan waiver", "crop insurance",
]

# Lightning / thunderstorm safety-action keywords (Phase 8.9)
# These signal that the farmer is asking for precautions or safety advice,
# NOT a weather forecast. Questions containing these must route to agricultural
# advisory (knowledge retrieval), not the weather forecast pipeline.
LIGHTNING_SAFETY_KEYWORDS_TE = [
    "పిడుగు", "పిడుగులు", "మెరుపు", "మెరుపులు",
    "జాగ్రత్త", "జాగ్రత్తలు", "జాగ్రత్తలు తీసుకోవాలి",
    "ఏం చేయాలి", "ఏమి చేయాలి", "ఏం చేయవచ్చు",
    "నివారణ", "రక్షణ", "సురక్షిత",
    "తగ్గించుకోవాలి", "తప్పించుకోవాలి",
]
LIGHTNING_SAFETY_KEYWORDS_HI = [
    "बिजली", "वज्रपात", "सावधानी", "बचाव", "क्या करें",
    "सुरक्षा", "बचने के उपाय",
]
LIGHTNING_SAFETY_KEYWORDS_EN = [
    "lightning", "thunder", "thunderstorm", "precaution", "precautions",
    "safety tips", "what to do", "protect", "shelter", "strike",
]

# General greeting keywords
GREETING_KEYWORDS_TE = [
    "నమస్కారం", "నమస్తే", "హలో", "హాయ్", "ధన్యవాదాలు", "ఎవరు మీరు", "సహాయం",
    "ఎట్లున్నారు", "ఎలా ఉన్నారు", "బాగున్నారా", "బాగున్నాం", "మంచిదేనా", "కుశలమా",
    "శుభోదయం", "శుభ సాయంత్రం", "శుభ రాత్రి",
]
GREETING_KEYWORDS_HI = [
    "नमस्ते", "प्रणाम", "हेलो", "हाय", "धन्यवाद", "मदद", "आप कौन हैं",
    "कैसे हैं", "क्या हाल है", "सब ठीक", "शुभ प्रभात", "शुभ संध्या",
]
GREETING_KEYWORDS_EN = [
    "hello", "hi", "namaste", "thank you", "thanks", "who are you", "help",
    "how are you", "good morning", "good afternoon", "good evening", "how's it going",
]


def is_pure_greeting(question: str) -> bool:
    """Return true only for standalone Telugu, Hindi, or English greetings."""
    if not question:
        return False
    cleaned = question.strip().lower()
    cleaned = cleaned.strip(" !?,.:;~`'\"|•\t\n\r\u0964\u0965")
    if cleaned.endswith(" అండి"):
        cleaned = cleaned[:-5].rstrip()
    return cleaned in {
        "నమస్కారం", "నమస్తే", "హలో", "హాయ్", "నమస్కారము",
        "नमस्ते", "प्रणाम", "हेलो", "हाय",
        "hi", "hello", "hey", "namaste", "namaskar", "namaskaram",
    }


def is_weather_query(question: str) -> bool:
    """
    Check whether a query requires meteorological / weather information.
    Performs case-insensitive regex matching across Telugu, Hindi, and English terms.
    """
    if not question or not question.strip():
        return False

    q_lower = question.lower()

    # Check English
    for kw in WEATHER_KEYWORDS_EN:
        if re.search(rf"\b{re.escape(kw)}\b", q_lower):
            return True

    # Check Telugu
    for kw in WEATHER_KEYWORDS_TE:
        if kw in q_lower:
            return True

    # Check Hindi
    for kw in WEATHER_KEYWORDS_HI:
        if kw in q_lower:
            return True

    return False


def is_weather_warning_query(question: str) -> bool:
    """
    Check whether a query specifically asks about severe weather warnings, hazards, or alerts.
    """
    if not question or not question.strip():
        return False

    q_lower = question.lower()

    for kw in WARNING_KEYWORDS_EN:
        if re.search(rf"\b{re.escape(kw)}\b", q_lower):
            return True

    for kw in WARNING_KEYWORDS_TE + WARNING_KEYWORDS_HI:
        if kw in q_lower:
            return True

    return False


def is_lightning_safety_query(question: str) -> bool:
    """
    Check whether a query asks for thunderstorm or lightning safety precautions.

    Phase 8.9: These questions should route to agricultural advisory (knowledge
    retrieval for the approved PJTAU lightning-safety record), NOT through the
    weather forecast pipeline which requires weather-provider consent and location.

    A question is a lightning safety query when it contains a lightning/thunder
    safety term AND a safety-action term (precaution, what-to-do, protection).
    Plain thunder-forecast questions like 'ఉరుములు ఎప్పుడు వస్తాయి' are NOT
    matched because they lack a safety-action keyword.
    """
    if not question or not question.strip():
        return False

    q_lower = question.lower()

    # English: match explicit lightning/thunder safety terms
    for kw in LIGHTNING_SAFETY_KEYWORDS_EN:
        if re.search(rf"\b{re.escape(kw)}\b", q_lower):
            return True

    # Telugu: match any lightning/thunder safety keyword
    for kw in LIGHTNING_SAFETY_KEYWORDS_TE:
        if kw in q_lower:
            return True

    # Hindi: match any lightning/thunder safety keyword
    for kw in LIGHTNING_SAFETY_KEYWORDS_HI:
        if kw in q_lower:
            return True

    return False


def classify_intent(question: str) -> str:
    """
    Classify the incoming text question into a primary functional intent category.
    """
    if not question or not question.strip():
        return INTENT_GENERAL_CONVERSATION

    q_lower = question.lower().strip()

    # 1. Scheme Inquiry
    for kw in SCHEME_KEYWORDS_EN:
        if kw in q_lower:
            return INTENT_GOVERNMENT_SCHEME
    for kw in SCHEME_KEYWORDS_TE + SCHEME_KEYWORDS_HI:
        if kw in q_lower:
            return INTENT_GOVERNMENT_SCHEME

    # 2. Fertilizer & Nutrient Management Inquiry (Phase 7.5.1 separation)
    for kw in FERTILIZER_KEYWORDS_EN:
        if re.search(rf"\b{re.escape(kw)}\b", q_lower):
            return INTENT_FERTILIZER_GUIDANCE
    for kw in FERTILIZER_KEYWORDS_TE + FERTILIZER_KEYWORDS_HI:
        if kw in q_lower:
            return INTENT_FERTILIZER_GUIDANCE

    # 3. Pest & Disease Inquiry
    for kw in PEST_DISEASE_KEYWORDS_EN:
        if re.search(rf"\b{re.escape(kw)}\b", q_lower):
            return INTENT_PEST_DISEASE_INQUIRY
    for kw in PEST_DISEASE_KEYWORDS_TE + PEST_DISEASE_KEYWORDS_HI:
        if kw in q_lower:
            return INTENT_PEST_DISEASE_INQUIRY

    # 3. Lightning / Thunderstorm Safety (Phase 8.9 — must precede weather routing)
    # Questions asking for safety precautions during lightning/thunder are agricultural
    # safety advisory, NOT weather forecasts. They must NOT trigger the weather forecast
    # pipeline (which requires weather-provider consent and location).
    if is_lightning_safety_query(q_lower):
        return INTENT_AGRICULTURAL_ADVICE

    # 4. Weather Inquiry (Priority before crop recommendation if purely meteorological)
    if is_weather_query(q_lower):
        # If it specifically asks for crop recommendation in context of weather, route as crop_recommendation
        for kw in CROP_RECOMMENDATION_KEYWORDS_EN:
            if kw in q_lower:
                return INTENT_CROP_RECOMMENDATION
        for kw in CROP_RECOMMENDATION_KEYWORDS_TE + CROP_RECOMMENDATION_KEYWORDS_HI:
            if kw in q_lower:
                return INTENT_CROP_RECOMMENDATION
        return INTENT_WEATHER_INQUIRY

    # 4. Crop Recommendation
    for kw in CROP_RECOMMENDATION_KEYWORDS_EN:
        if kw in q_lower:
            return INTENT_CROP_RECOMMENDATION
    for kw in CROP_RECOMMENDATION_KEYWORDS_TE + CROP_RECOMMENDATION_KEYWORDS_HI:
        if kw in q_lower:
            return INTENT_CROP_RECOMMENDATION

    # 5. General Greeting / Identity
    for kw in GREETING_KEYWORDS_EN:
        if re.search(rf"\b{re.escape(kw)}\b", q_lower):
            return INTENT_GENERAL_CONVERSATION
    for kw in GREETING_KEYWORDS_TE + GREETING_KEYWORDS_HI:
        if kw in q_lower:
            return INTENT_GENERAL_CONVERSATION

    # Default to general agricultural advice
    return INTENT_AGRICULTURAL_ADVICE
