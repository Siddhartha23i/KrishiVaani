"""
Weather End-User Disclaimers for KrishiVaani — Phase 6.1.1.
Required by WeatherAPI.com terms and KrishiVaani agricultural safety policies.
Provides localized text for display and Timbre voice synthesis.

Languages supported:
- Telugu (te-IN): Primary user-facing language for Telangana farmers
- Hindi (hi-IN): Secondary supported language
- English (en-IN): Internal and diagnostic default
"""

from typing import Dict

WEATHER_DISCLAIMERS: Dict[str, str] = {
    "en-IN": (
        "Weather information is provided for general informational guidance only. "
        "Forecasts and weather conditions are probabilistic estimates and may not reflect "
        "exact conditions at your specific field or village. This data must not be the sole "
        "basis for safety-critical, irrigation, or harvest decisions. Please consult official "
        "India Meteorological Department (IMD) forecasts, warnings, and agricultural advisories "
        "before making important farming decisions."
    ),
    "te-IN": (
        "వాతావరణ సమాచారం సాధారణ సమాచార ప్రయోజనాల కొరకు మాత్రమే అందించబడుతుంది. "
        "వాతావరణ సూచనలు మరియు పరిస్థితులు సంభావ్యత అంచనాలు మాత్రమే, మీ నిర్దిష్ట గ్రామం లేదా పొలంలో "
        "ఖచ్చితమైన పరిస్థితులను ప్రతిబింబించకపోవచ్చు. ఈ డేటాను భద్రత, నీటిపారుదల లేదా పంట కోత వంటి "
        "కీలక నిర్ణయాలకు ఏకైక ఆధారంగా తీసుకోకూడదు. ముఖ్యమైన వ్యవసాయ నిర్ణయాల కొరకు దయచేసి భారత "
        "వాతావరణ శాఖ (IMD) అధికారిక నివేదికలు మరియు హెచ్చరికలను సంప్రదించండి."
    ),
    "hi-IN": (
        "मौसम की जानकारी केवल सामान्य सूचना मार्गदर्शन के लिए प्रदान की जाती है। "
        "पूर्वानुमान और वर्तमान स्थितियां संभाविता आधारित अनुमान हैं, जो आपके विशिष्ट गांव या खेत "
        "की सटीक स्थिति से भिन्न हो सकती हैं। इस डेटा को सिंचाई, कीटनाशक छिड़काव या फसल कटाई जैसे "
        "महत्वपूर्ण निर्णयों का एकमात्र आधार न बनाएं। महत्वपूर्ण कृषि निर्णयों के लिए कृपया भारतीय "
        "मौसम विभाग (IMD) के आधिकारिक पूर्वानुमानों और चेतावनियों का पालन करें।"
    ),
}


def get_weather_disclaimer(language_code: str = "te-IN") -> str:
    """
    Retrieve localized end-user weather disclaimer based on language code.
    Defaults to Telugu (te-IN) for Telangana farmers, falling back to English (en-IN).
    """
    if not language_code:
        return WEATHER_DISCLAIMERS["te-IN"]

    lang = language_code.strip().lower()
    if lang.startswith("te"):
        return WEATHER_DISCLAIMERS["te-IN"]
    elif lang.startswith("hi"):
        return WEATHER_DISCLAIMERS["hi-IN"]
    elif lang.startswith("en"):
        return WEATHER_DISCLAIMERS["en-IN"]

    return WEATHER_DISCLAIMERS["en-IN"]

