"""Bounded text-only live policy check; no credentials are printed or inspected."""

from __future__ import annotations

import sys
import time
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.conversation.schemas import ConversationRequest, GuestWeatherConsentEvent, LocationInput
from app.conversation.service import ConversationOrchestrator
from app.llm.knowledge_adapter import KnowledgeRetrievalFilter
from app.core.config import settings


CASES = [
    {"id": "el-nino-te", "question": "ఎల్ నినో ప్రభావం గురించి చెప్పండి", "language": "te-IN", "expected_intent": "general_explanation", "expected_reply_script": "te", "must_not_contain": ["ఇంకా ఏమైనా సందేహాలుంటే అడగండి"], "must_contain": []},
    {"id": "el-nino-en", "question": "What is El Nino and how does it affect Indian farmers?", "language": "en-IN", "expected_intent": "general_explanation", "expected_reply_script": "en", "must_not_contain": ["అండి", "ఇంకా ఏమైనా సందేహాలుంటే అడగండి"], "must_contain": []},
    {"id": "drip-hi", "question": "ड्रिप सिंचाई क्या है?", "language": "hi-IN", "expected_intent": "general_explanation", "expected_reply_script": "hi", "must_not_contain": ["अंडी", "అండి"], "must_contain": []},
    {"id": "monsoon-ta", "question": "எப்படி பருவமழை உருவாகிறது?", "language": "ta-IN", "expected_intent": "general_explanation", "expected_reply_script": "ta", "must_not_contain": ["అండి"], "must_contain": []},
    {"id": "wheat-haryana", "question": "हरियाणा में गेहूं की बुवाई कब करें?", "language": "hi-IN", "state": "Haryana", "expected_intent": "crop_recommendation", "expected_reply_script": "hi", "must_not_contain": ["అండి"], "must_contain": ["1800-180-1551"]},
    {"id": "stubble-punjabi", "question": "ਪੰਜਾਬ ਵਿੱਚ ਪਰਾਲੀ ਬਾਰੇ ਕੀ ਕਰੀਏ?", "language": "pa-IN", "state": "Punjab", "expected_intent": "crop_recommendation", "expected_reply_script": "pa", "must_not_contain": ["అండి"], "must_contain": ["1800-180-1551"]},
    {"id": "cotton-telangana", "question": "వరంగల్‌లో పత్తి పంటకు ఏ జాగ్రత్తలు తీసుకోవాలి?", "language": "te-IN", "state": "Telangana", "district": "Warangal", "expected_intent": "crop_recommendation", "expected_reply_script": "te", "must_not_contain": ["ఇంకా ఏమైనా సందేహాలుంటే అడగండి"], "must_contain": ["1800-180-1551"]},
    {"id": "pesticide-dose", "question": "పత్తిలో పురుగు మందు ఎంత మోతాదులో కలపాలి?", "language": "te-IN", "state": "Telangana", "expected_intent": "pest_disease_inquiry", "expected_reply_script": "te", "must_not_contain": [], "must_contain": []},
    {"id": "pm-kisan", "question": "What is the PM-KISAN eligibility?", "language": "en-IN", "expected_intent": "government_scheme", "expected_reply_script": "en", "must_not_contain": ["అండి"], "must_contain": []},
    {"id": "weather-pune", "question": "पुणे में आज का मौसम कैसा है?", "language": "mr-IN", "state": "Maharashtra", "district": "Pune", "expected_intent": "weather_inquiry", "expected_reply_script": "mr", "must_not_contain": ["అండి"], "must_contain": []},
    {"id": "greeting", "question": "నమస్తే", "language": "te-IN", "expected_intent": "general_conversation", "expected_reply_script": "te", "must_not_contain": ["అండి"], "must_contain": []},
    {"id": "thanks", "question": "धन्यवाद", "language": "hi-IN", "expected_intent": "general_conversation", "expected_reply_script": "hi", "must_not_contain": ["అండి"], "must_contain": []},
    {"id": "thanks-en", "question": "Thanks", "language": "en-IN", "expected_intent": "general_conversation", "expected_reply_script": "en", "must_not_contain": ["అండి", "ధన్యవాదాలు"], "must_contain": []},
    {"id": "cricket", "question": "Who won the cricket match?", "language": "en-IN", "expected_intent": "agricultural_advice", "expected_reply_script": "en", "must_not_contain": ["అండి"], "must_contain": []},
]


def _script_matches(text: str, script: str) -> bool:
    ranges = {
        "te": ("\u0c00", "\u0c7f"),
        "hi": ("\u0900", "\u097f"),
        "ta": ("\u0b80", "\u0bff"),
        "pa": ("\u0a00", "\u0a7f"),
        "mr": ("\u0900", "\u097f"),
    }
    if script == "en":
        return not any("\u0900" <= char <= "\u0d7f" for char in text)
    if script not in ranges:
        return True
    start, end = ranges[script]
    return any(start <= char <= end for char in text)


def _evaluate(case: dict, response_text: str, intent: str) -> str:
    failures = []
    if intent != case["expected_intent"]:
        failures.append(f"intent={intent}")
    if not _script_matches(response_text, case["expected_reply_script"]):
        failures.append("reply-script")
    if response_text.count("అండి") > 1:
        failures.append("andi-count>1")
    if case["expected_intent"] == "general_explanation" and response_text.rstrip().endswith("?"):
        failures.append("tier1-trailing-question")
    if any(fragment.casefold() in response_text.casefold() for fragment in ("i can search", "tell you more", "can help you find")):
        failures.append("capability-offer")
    for fragment in case["must_not_contain"]:
        if fragment.casefold() in response_text.casefold():
            failures.append(f"contains-forbidden={fragment}")
    for fragment in case["must_contain"]:
        if fragment.casefold() not in response_text.casefold():
            failures.append(f"missing-required={fragment}")
    return "FAIL: " + ", ".join(failures) if failures else "PASS"


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    orchestrator = ConversationOrchestrator()
    cotton_evidence = orchestrator.knowledge_adapter.retrieve_approved_evidence(
        KnowledgeRetrievalFilter(
            farmer_state="Telangana",
            farmer_district="Warangal",
            crop_name="Cotton",
            category="crop_management",
            as_of_date=None,
        )
    )
    cotton_categories = sorted({getattr(item, "category", "unknown") for item in cotton_evidence.items})
    print(
        "cotton-evidence | count=%d | categories=%s | gate=%s"
        % (
            len(cotton_evidence.items),
            ",".join(cotton_categories) or "none",
            "attach-crop-evidence" if cotton_evidence.items else "no-matching-evidence",
        )
    )
    print("approved-telangana-coverage | district | crop | category | count")
    with sqlite3.connect(settings.DATABASE_PATH) as conn:
        coverage_rows = conn.execute(
            """
            SELECT COALESCE(district, 'Statewide'), COALESCE(crop_name, 'All crops'),
                   COALESCE(category, 'Uncategorized'), COUNT(*)
            FROM knowledge_items
            WHERE LOWER(state) = 'telangana'
              AND LOWER(verification_status) IN ('approved', 'verified')
            GROUP BY district, crop_name, category
            ORDER BY district, crop_name, category
            """
        ).fetchall()
    for district_name, crop_name, category_name, count in coverage_rows:
        print(f"approved-telangana-coverage | {district_name} | {crop_name} | {category_name} | {count}")
    rows = []
    for case in CASES:
        case_id = case["id"]
        question = case["question"]
        language = case["language"]
        state = case.get("state")
        district = case.get("district")
        location = LocationInput(state=state, district=district, location_confirmed=bool(district)) if state or district else None
        consent = (
            GuestWeatherConsentEvent(
                consent_given=True,
                disclosure_version="live-check-v1",
                consent_timestamp="2026-01-01T00:00:00Z",
                channel="telegram",
            )
            if district
            else None
        )
        started = time.perf_counter()
        try:
            response = orchestrator.process_message(
                ConversationRequest(
                    question=question,
                    language=language,
                    location=location,
                    guest_consent=consent,
                    channel="telegram",
                )
            )
            row = {
                "id": case_id,
                "question": question,
                "intent": response.intent,
                "gate": response.safety_reason or ("ABSTENTION" if response.is_abstention else "NONE"),
                "safety": response.safety_status,
                "answer": response.response_text,
                "latency": time.perf_counter() - started,
                "verdict": _evaluate(case, response.response_text or "", response.intent),
            }
        except Exception as exc:
            row = {
                "id": case_id,
                "question": question,
                "intent": "ERROR",
                "gate": type(exc).__name__,
                "safety": "ERROR",
                "answer": "",
                "latency": time.perf_counter() - started,
                "verdict": "UNVERIFIED: runtime error",
            }
        rows.append(row)
        print(
            f"{row['id']} | {row['intent']} | {row['gate']} | "
            f"{row['safety']} | {row['latency']:.2f}s | {row['answer'] or '[empty]'}"
        )
        if case_id != CASES[-1]["id"]:
            time.sleep(15)

    report = ROOT / "PROJECT_AUDIT_REPORT.md"
    existing = report.read_text(encoding="utf-8")
    marker = "\n\n## Updated live policy check"
    if marker in existing:
        existing = existing.split(marker, 1)[0].rstrip()
    with report.open("w", encoding="utf-8") as handle:
        handle.write(existing + "\n\n## Updated live policy check\n\n")
        handle.write("### Approved Telangana coverage (counts only)\n\n")
        handle.write("| District | Crop | Category | Count |\n|---|---|---|---:|\n")
        for district_name, crop_name, category_name, count in coverage_rows:
            handle.write(f"| {district_name} | {crop_name} | {category_name} | {count} |\n")
        handle.write("\n")
        handle.write("| Case | Intent | Gate | Safety | Verdict | Latency (s) | Answer |\n|---|---|---|---|---|---:|---|\n")
        for row in rows:
            answer = (row["answer"] or "").replace("|", "\\|").replace("\n", " ")
            handle.write(
                f"| {row['id']} | {row['intent']} | {row['gate']} | "
                f"{row['safety']} | {row['verdict']} | {row['latency']:.2f} | {answer} |\n"
            )


if __name__ == "__main__":
    main()
