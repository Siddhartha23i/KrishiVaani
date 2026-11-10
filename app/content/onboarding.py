"""
Onboarding greetings and voice-friendly dialogue templates.
Supports Telugu (te-IN, default for Telangana) and Hindi (hi-IN).
"""

from typing import Optional, List

TELUGU_ONBOARDING_MESSAGE = (
    "నమస్కారం! కృషివాణికి స్వాగతం.\n\n"
    "మీ ప్రాంతానికి సంబంధించిన వాతావరణం మరియు వ్యవసాయ సమాచారం అందించడానికి, "
    "దయచేసి మీ గ్రామం పేరు మరియు పిన్ కోడ్ చెప్పండి.\n\n"
    "మీకు తెలిస్తే మండలం మరియు జిల్లా పేర్లు కూడా చెప్పండి.\n\n"
    "WhatsAppలో మీ లొకేషన్ పంపాల్సిన అవసరం లేదు. మీ వాయిస్ మెసేజ్లోనే ఈ వివరాలు చెప్పవచ్చు.\n\n"
    "మీరు చెప్పిన వివరాలను నేను మళ్లీ చెబుతాను. అవి సరైనవని నిర్ధారించిన తర్వాత, "
    "మీ అనుమతితో వాటిని భద్రపరుస్తాను.\n\n"
    "ధన్యవాదాలు!"
)

HINDI_ONBOARDING_MESSAGE = (
    "नमस्कार! कृषिवाणी में आपका स्वागत है।\n\n"
    "आपके क्षेत्र की मौसम और खेती से जुड़ी जानकारी देने के लिए कृपया अपने गाँव का नाम और पिन कोड बताइए।\n\n"
    "यदि पता हो तो मंडल और ज़िले का नाम भी बताइए।\n\n"
    "WhatsApp पर अपनी लोकेशन भेजना ज़रूरी नहीं है। आप ये सभी जानकारी एक ही वॉइस मैसेज में बता सकते हैं।\n\n"
    "मैं आपकी बताई जानकारी दोहराकर पुष्टि करूँगा। आपकी अनुमति मिलने के बाद ही इसे सुरक्षित रखूँगा।\n\n"
    "धन्यवाद!"
)


def get_onboarding_greeting(language_code: str = "te-IN") -> str:
    """Return localized onboarding welcome message."""
    if language_code == "hi-IN":
        return HINDI_ONBOARDING_MESSAGE
    return TELUGU_ONBOARDING_MESSAGE


def get_location_confirmation_prompt(
    language_code: str,
    village: str,
    pin_code: str,
    mandal: Optional[str] = None,
    district: Optional[str] = None,
) -> str:
    """
    Format interpreted location details into a voice-friendly confirmation prompt.
    Asks the farmer to confirm accuracy and grant explicit storage consent.
    """
    if language_code == "hi-IN":
        extra = []
        if mandal:
            extra.append(f"मंडल: {mandal}")
        if district:
            extra.append(f"ज़िला: {district}")
        extra_str = f", {', '.join(extra)}" if extra else ""
        return (
            f"आपकी दी गई जानकारी: गाँव: {village}, पिन कोड: {pin_code}{extra_str}। "
            "क्या यह जानकारी सही है? क्या आपके प्रोफ़ाइल को सुरक्षित रखने के लिए आपकी अनुमति है?"
        )

    # Default Telugu
    extra = []
    if mandal:
        extra.append(f"మండలం: {mandal}")
    if district:
        extra.append(f"జిల్లా: {district}")
    extra_str = f", {', '.join(extra)}" if extra else ""
    return (
        f"మీరు చెప్పిన వివరాలు: గ్రామం: {village}, పిన్ కోడ్: {pin_code}{extra_str}. "
        "ఇది సరైనదేనా? మీ ప్రొఫైల్‌ను భద్రపరచడానికి మీ అనుమతి ఇవ్వగలరా?"
    )


def get_clarification_prompt(language_code: str, missing_fields: List[str]) -> str:
    """Return voice prompt requesting missing location details."""
    has_village = "village_name" in missing_fields
    has_pin = "pin_code" in missing_fields

    if language_code == "hi-IN":
        if has_village and has_pin:
            return "कृपया अपने गाँव का नाम और 6 अंकों का पिन कोड स्पष्ट रूप से बताइए।"
        elif has_village:
            return "कृपया अपने गाँव का नाम स्पष्ट रूप से बताइए।"
        elif has_pin:
            return "कृपया अपना 6 अंकों का पिन कोड स्पष्ट रूप से बताइए।"
        return "कृपया अपनी लोकेशन की सही जानकारी दोबारा बताइए।"

    # Default Telugu
    if has_village and has_pin:
        return "దయచేసి మీ గ్రామం పేరు మరియు 6 అంకెల పిన్ కోడ్ స్పష్టంగా చెప్పండి."
    elif has_village:
        return "దయచేసి మీ గ్రామం పేరు స్పష్టంగా చెప్పండి."
    elif has_pin:
        return "దయచేసి మీ 6 అంకెల పిన్ కోడ్ స్పష్టంగా చెప్పండి."
    return "దయచేసి మీ ప్రాంత వివరాలను మళ్లీ స్పష్టంగా చెప్పండి."

