from app.conversation.intent import (
    INTENT_GENERAL_CONVERSATION,
    INTENT_GENERAL_EXPLANATION,
    INTENT_PEST_DISEASE_INQUIRY,
    classify_intent,
)
from app.llm.service import normalize_response_style


def test_general_explanations_are_tier_one_across_requested_languages():
    questions = [
        "ఎల్ నినో ప్రభావం గురించి చెప్పండి",
        "What is El Nino?",
        "ड्रिप सिंचाई क्या है?",
        "எப்படி பருவமழை உருவாகிறது?",
        "ಕೃಷಿ ಎಂದರೇನು?",
        "മഴ എങ്ങനെ രൂപപ്പെടുന്നു?",
        "कसे कार्य करते?",
        "ਪਾਣੀ ਦੀ ਬਚਤ ਕਿਵੇਂ ਕਰੀਏ?",
        "বৃষ্টিপাত কীভাবে হয়?",
        "સિંચાઈ કેવી રીતે કામ કરે છે?",
    ]
    assert all(classify_intent(question) == INTENT_GENERAL_EXPLANATION for question in questions)


def test_thanks_and_punjabi_greeting_are_conversation():
    assert classify_intent("ధన్యవాదాలు") == INTENT_GENERAL_CONVERSATION
    assert classify_intent("ਸਤ ਸ੍ਰੀ ਅਕਾਲ") == INTENT_GENERAL_CONVERSATION


def test_pesticide_dose_remains_consequential():
    assert classify_intent("పురుగు మందు మోతాదు ఎంత?") == INTENT_PEST_DISEASE_INQUIRY


def test_english_consequential_questions_route_to_safe_intents():
    assert classify_intent("Which cotton variety should I sow?") == "crop_recommendation"
    assert classify_intent("Which crop should I plant in Haryana?") == "crop_recommendation"
    assert classify_intent("When should I sow wheat?") == "crop_recommendation"
    assert classify_intent("How much to spray for aphids?") == "pest_disease_inquiry"
    assert classify_intent("How much fertilizer should I apply?") == "fertilizer_guidance"


def test_leading_telugu_andi_is_removed_without_losing_text():
    result = normalize_response_style("అండి, ఈ సమాచారం ఉపయోగపడుతుంది. తర్వాత అడగండి.")
    assert result == "ఈ సమాచారం ఉపయోగపడుతుంది. తర్వాత అడగండి అండి."


def test_telugu_andi_is_kept_once_at_final_sentence_end():
    result = normalize_response_style(
        "అండి, ఇది ముఖ్యం అండి. మళ్లీ అండి వివరాలు చూడండి అండి.",
        "te-IN",
    )
    assert result.count("అండి") == 1
    assert result.endswith("అండి.")


def test_andi_is_removed_from_non_telugu_responses():
    result = normalize_response_style(
        "El Nino affects rainfall in India అండి. Please check local updates.",
        "English",
    )
    assert "అండి" not in result
    assert result == "El Nino affects rainfall in India. Please check local updates."


def test_generic_follow_up_closings_are_removed():
    assert "क्या आप" not in normalize_response_style(
        "ड्रिप सिंचाई पानी बचाती है। क्या आप अपने खेत में इस व्यवस्था के बारे में और जानना चाहते हैं?",
        "Hindi",
    )
    assert "சொல்லட்டுமா" not in normalize_response_style(
        "பருவமழை கடல் காற்றால் உருவாகிறது. இது எப்படி நடக்கிறது என்று உங்களுக்கு இன்னும் விரிவாக சொல்லட்டுமா?",
        "Tamil",
    )
