"""
KrishiVaani End-to-End Telugu Voice Pipeline CLI — Phase 8.0.

Integrates:
- Gnani Prisma v3.0 STT (Telugu te-IN)
- KrishiVaani Conversation Orchestrator (with approved evidence & deterministic safety)
- Gnani Timbre v2.5 TTS (Kaveri voice, 48kHz WAV)

Usage:
    python .\\voice_pipeline.py ".\\test-audio\\telugu-test.m4a"
"""

import sys
import base64
from pathlib import Path
from dotenv import load_dotenv

# Ensure app package is importable
current_dir = Path(__file__).resolve().parent
if str(current_dir) not in sys.path:
    sys.path.insert(0, str(current_dir))

from app.core.config import settings
from app.voice.service import VoicePipelineService
from app.voice.schemas import VoiceProcessingRequest


def main():
    load_dotenv()

    if not settings.GNANI_API_KEY:
        raise SystemExit("Missing GNANI_API_KEY in .env")

    if len(sys.argv) < 2:
        raise SystemExit('Usage: python .\\voice_pipeline.py ".\\test-audio\\telugu-test.m4a"')

    input_audio = Path(sys.argv[1])
    if not input_audio.is_file():
        raise SystemExit(f"Audio file not found: {input_audio}")

    print("==================================================")
    print("KrishiVaani End-to-End Telugu Voice Pipeline")
    print("==================================================")
    print(f"Input Audio: {input_audio.resolve()}")

    try:
        service = VoicePipelineService()
        request = VoiceProcessingRequest(language="te-IN")

        print("\nProcessing voice query through Prisma STT -> Orchestrator -> Timbre TTS...")
        result = service.process_audio_file(input_audio, request=request)

        print("\n--- VOICE PIPELINE RESULTS ---")
        print(f"Status:            {result.status}")
        print(f"Transcript:        {result.transcript}")
        print(f"Detected Language: {result.detected_language}")
        print(f"Intent:            {result.intent}")
        print(f"Safety Status:     {result.safety_status}")
        print(f"Is Abstention:     {result.is_abstention}")
        if result.evidence_citations:
            print(f"Evidence Citations:{', '.join(result.evidence_citations)}")
        print(f"\nAssistant Spoken Text:\n{result.response_text}")

        # Save audio output if synthesized
        if result.audio_base64:
            output_audio = Path("pipeline-reply.wav")
            audio_bytes = base64.b64decode(result.audio_base64)
            output_audio.write_bytes(audio_bytes)
            print(f"\nSynthesized Audio: {output_audio.resolve()} ({len(audio_bytes):,} bytes)")
        elif result.is_fallback_text_only:
            print("\n[Notice] Response returned in safe text mode (audio synthesis was skipped or degraded).")
            if result.error_detail:
                print(f"Detail: {result.error_detail}")

        print("\n--- LATENCY BREAKDOWN (ms) ---")
        for stage, latency in result.stage_latencies_ms.items():
            print(f"  {stage:25s}: {latency} ms")

        print("\nPipeline completed successfully.")

    except Exception as error:
        print(f"\nPipeline failed: {error}")
        sys.exit(1)


if __name__ == "__main__":
    main()
