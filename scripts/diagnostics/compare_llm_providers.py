"""Compare Groq and Sarvam through the text ConversationOrchestrator path.

This script never reads .env directly and never prints credentials. It does not
invoke STT or TTS. Weather calls are replaced with deterministic in-process
facts so every question reaches the selected LLM provider without consuming
weather API quota.
"""

from __future__ import annotations

import statistics
import sys
import time
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.conversation.schemas import ConversationRequest, LocationInput, GuestWeatherConsentEvent
from app.conversation.service import ConversationOrchestrator
from app.llm.providers.groq_provider import GroqProvider
from app.llm.providers.sarvam_provider import SarvamProvider
from app.llm.service import LLMReasoningService


REPORT_PATH = ROOT / "docs" / "archive" / "LLM_AB_RESULTS.md"

QUESTIONS = [
    ("weather-1", "నిజామాబాద్ జిల్లాలో రేపు వాన పడే అవకాశం ఎంత?"),
    ("weather-2", "వరంగల్ జిల్లాలో వచ్చే మూడు రోజుల్లో ఉష్ణోగ్రత ఎలా ఉంటుంది?"),
    ("crop-1", "యాసంగిలో తక్కువ నీటితో ఏ పంట వేయడం మంచిది?"),
    ("crop-2", "నల్ల నేలలో పత్తి పంటకు ఏ జాగ్రత్తలు తీసుకోవాలి?"),
    ("scheme-1", "రైతు బంధు పథకం గురించి చెప్పండి."),
    ("off-topic-1", "మీరు ఎవరు?"),
    ("pesticide-1", "పత్తిలో పురుగు మందు ఎంత మోతాదులో కలపాలి?"),
    ("greeting-1", "నమస్తే "),
]


class ComparisonWeatherProvider:
    def get_current_weather(self, **_kwargs):
        location = SimpleNamespace(location_name="Comparison district")
        return SimpleNamespace(
            location=location,
            temperature_c=29.0,
            condition_text="Partly cloudy",
            precipitation_mm=1.2,
            observed_rainfall_mm=None,
            issued_at="2026-11-10T09:00:00+05:30",
            retrieved_at="2026-11-10T09:00:00+05:30",
            source_name="Comparison fixture",
            source_url="https://example.invalid/weather-fixture",
            freshness_status=SimpleNamespace(value="CURRENT"),
        )

    def get_forecast(self, **_kwargs):
        days = [
            SimpleNamespace(
                date="2026-11-11",
                total_precipitation_mm=3.0,
                chance_of_rain_percent=40,
                condition_text="Cloudy",
                max_temp_c=31.0,
                min_temp_c=22.0,
            ),
            SimpleNamespace(
                date="2026-11-12",
                total_precipitation_mm=0.0,
                chance_of_rain_percent=15,
                condition_text="Sunny",
                max_temp_c=32.0,
                min_temp_c=22.0,
            ),
            SimpleNamespace(
                date="2026-11-13",
                total_precipitation_mm=5.0,
                chance_of_rain_percent=55,
                condition_text="Cloudy",
                max_temp_c=30.0,
                min_temp_c=21.0,
            ),
        ]
        return SimpleNamespace(
            forecast_days=days,
            issued_at="2026-11-10T09:00:00+05:30",
            retrieved_at="2026-11-10T09:00:00+05:30",
            source_name="Comparison fixture",
            source_url="https://example.invalid/weather-fixture",
            freshness_status=SimpleNamespace(value="CURRENT"),
        )


class ComparisonWeatherService:
    def __init__(self):
        self.weatherapi_provider = ComparisonWeatherProvider()

    def get_imd_district_warning(self, district, day="Day_1"):
        return SimpleNamespace(
            has_data=True,
            is_stale=False,
            retrieved_at="2026-11-10T09:00:00+05:30",
            warning_text="No official warning in the comparison fixture.",
            severity_color_name="Green",
            source_url="https://example.invalid/imd-fixture",
            issue_date="2026-11-10",
        )


def _request(question: str, weather_district: str | None = None) -> ConversationRequest:
    if not weather_district:
        return ConversationRequest(
            question=question,
            language="te-IN",
            channel="telegram",
        )
    return ConversationRequest(
        question=question,
        language="te-IN",
        channel="telegram",
        location=LocationInput(district=weather_district, location_confirmed=True),
        guest_consent=GuestWeatherConsentEvent(
            consent_given=True,
            disclosure_version="comparison-v1",
            consent_timestamp="2026-11-10T09:00:00+05:30",
            channel="telegram",
        ),
    )


def _provider(name: str):
    return GroqProvider() if name == "Groq" else SarvamProvider()


def main() -> None:
    results = {}
    for provider_name in ("Groq", "Sarvam"):
        service = LLMReasoningService(
            provider=_provider(provider_name),
        )
        orchestrator = ConversationOrchestrator(
            llm_service=service,
            weather_service=ComparisonWeatherService(),
        )
        provider_results = []
        for question_id, question in QUESTIONS:
            started = time.perf_counter()
            weather_district = None
            if question_id == "weather-1":
                weather_district = "Nizamabad"
            elif question_id == "weather-2":
                weather_district = "Warangal"
            response = orchestrator.process_message(
                _request(question, weather_district)
            )
            latency = time.perf_counter() - started
            provider_results.append(
                {
                    "id": question_id,
                    "question": question,
                    "latency": latency,
                    "answer": response.response_text,
                    "answer_length": len(response.response_text or ""),
                    "safety_status": response.safety_status,
                    "abstain": response.is_abstention,
                    "error_class": response.safety_reason or "",
                }
            )
            time.sleep(15)
        results[provider_name] = provider_results

    lines = [
        "# LLM provider comparison",
        "",
        "Text-only ConversationOrchestrator comparison; no STT/TTS calls. Weather uses an in-process fixture.",
        "",
    ]
    for provider_name, provider_results in results.items():
        lines.extend([f"## {provider_name}", ""])
        for result in provider_results:
            lines.extend(
                [
                    f"### {result['id']}",
                    f"- Question: {result['question']}",
                    f"- Latency: {result['latency']:.3f} seconds",
                    f"- Answer length: {result['answer_length']} characters",
                    f"- Safety status: {result['safety_status']}",
                    f"- Abstain: {result['abstain']}",
                    f"- Error class/reason: {result['error_class'] or 'None'}",
                    "- Answer:",
                    "```text",
                    result["answer"] or "",
                    "```",
                    "",
                ]
            )
        median = statistics.median(item["latency"] for item in provider_results)
        lines.extend([f"**Median latency:** {median:.3f} seconds", ""])

    lines.extend(
        [
            "## Interpretation",
            "",
            "The faster provider is the one with the lower median latency above.",
            "Telugu completeness requires human review of the eight answers; character count is not a quality score.",
        ]
    )
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
