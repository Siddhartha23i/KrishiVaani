from app.conversation.service import ConversationOrchestrator, normalize_language
from app.conversation.intent import INTENT_CROP_RECOMMENDATION


def test_haryana_crop_response_is_hindi_and_refers_to_kcc():
    response = ConversationOrchestrator._create_out_of_state_response(
        object(), "hi-IN", "Hindi", INTENT_CROP_RECOMMENDATION, "Crops in Haryana"
    )
    assert response.language == "hi-IN"
    assert "1800-180-1551" in response.response_text
    assert "Telangana" not in response.response_text
    assert response.evidence_citations == []


def test_supported_language_codes_normalize():
    assert normalize_language("kn-IN") == ("kn-IN", "Kannada")
    assert normalize_language("ta-IN") == ("ta-IN", "Tamil")
    assert normalize_language("mr-IN") == ("mr-IN", "Marathi")
