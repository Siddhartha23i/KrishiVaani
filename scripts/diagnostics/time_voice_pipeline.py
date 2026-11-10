"""Bounded live timing probe for the KrishiVaani Telugu voice path.

This script intentionally performs exactly three STT calls and three TTS calls.
It prints timings and non-sensitive status only; it never prints transcripts,
responses, identifiers, configuration values, or exception text.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
import time
from pathlib import Path

import imageio_ffmpeg

from app.conversation.schemas import ConversationRequest
from app.conversation.service import ConversationOrchestrator
from app.telegram.audio import convert_ogg_opus_to_wav
from app.voice.service import VoicePipelineService


ROOT = Path(__file__).resolve().parents[2]
INPUT_AUDIO = ROOT / "test-audio" / "telugu-test.m4a"


def _make_ogg(source: Path, destination: Path) -> None:
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    result = subprocess.run(
        [
            ffmpeg,
            "-y",
            "-i",
            str(source),
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "libopus",
            "-f",
            "ogg",
            str(destination),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError("local sample conversion failed")


def _timed(callable_, *args, **kwargs):
    started = time.perf_counter()
    value = callable_(*args, **kwargs)
    return value, round((time.perf_counter() - started) * 1000, 2)


def main() -> None:
    if not INPUT_AUDIO.is_file():
        raise SystemExit("sample audio is missing")

    service = VoicePipelineService()
    if service.stt_client is None or service.tts_client is None:
        raise SystemExit("Gnani clients are not configured")

    orchestrator = ConversationOrchestrator()
    rows = []

    with tempfile.TemporaryDirectory(prefix="krishivaani-timing-") as temp_dir:
        ogg_path = Path(temp_dir) / "sample.ogg"
        _make_ogg(INPUT_AUDIO, ogg_path)

        for run_number in range(1, 4):
            row = {"run": run_number}
            wav_bytes, row["ogg_to_wav_ms"] = _timed(
                convert_ogg_opus_to_wav, ogg_path.read_bytes()
            )
            with tempfile.NamedTemporaryFile(
                suffix=".wav", dir=temp_dir, delete=False
            ) as wav_file:
                wav_file.write(wav_bytes)
                wav_path = Path(wav_file.name)

            try:
                stt_result, row["stt_ms"] = _timed(
                    service.stt_client.transcribe,
                    str(wav_path),
                    language_code="te-IN",
                    model="prisma-v3.0",
                    format="transcribe",
                    topic="Telangana farming and agriculture",
                )
                transcript = (stt_result.get("transcript") or "").strip()
                if not transcript:
                    row["status"] = "empty_transcript"
                    rows.append(row)
                    continue

                conv_request = ConversationRequest(
                    question=transcript,
                    language="te-IN",
                    channel="telegram",
                )
                conv_response, row["orchestration_and_guardrails_ms"] = _timed(
                    orchestrator.process_message, conv_request
                )
                row["intent"] = conv_response.intent
                row["safety_status"] = conv_response.safety_status

                wav_reply, row["tts_ms"] = _timed(
                    service._synthesize_speech,
                    conv_response.response_text,
                    "te-IN",
                    "telegram",
                )
                _, row["wav_to_ogg_ms"] = _timed(
                    __import__(
                        "app.whatsapp.audio_converter",
                        fromlist=["convert_wav_bytes_to_ogg_opus"],
                    ).convert_wav_bytes_to_ogg_opus,
                    wav_reply,
                )
                row["status"] = "ok"
            except Exception:
                row["status"] = "stage_failed"
            finally:
                wav_path.unlink(missing_ok=True)
            rows.append(row)

    print(json.dumps({"runs": rows, "gnani_call_budget": "3 STT + 3 TTS"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
