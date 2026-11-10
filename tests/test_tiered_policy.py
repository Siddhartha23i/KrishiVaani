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


def test_leading_telugu_andi_is_removed_without_losing_text():
    result = normalize_response_style("అండి, ఈ సమాచారం ఉపయోగపడుతుంది. తర్వాత అడగండి.")
    assert result == "ఈ సమాచారం ఉపయోగపడుతుంది. తర్వాత అడగండి."

