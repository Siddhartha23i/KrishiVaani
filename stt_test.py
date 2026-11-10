
from pathlib import Path
import os
import sys

from dotenv import load_dotenv
from gnani.stt import GnaniSTTClient


def main():
    # Read the API key from the project's .env file.
    load_dotenv()

    api_key = os.getenv("GNANI_API_KEY")
    if not api_key:
        raise SystemExit(
            "Missing GNANI_API_KEY. Add it to the .env file."
        )

    # Use the audio path supplied in the terminal.
    if len(sys.argv) < 2:
        raise SystemExit(
            'Usage: python .\\stt_test.py ".\\test-audio\\telugu-test.m4a"'
        )

    audio_path = Path(sys.argv[1])

    if not audio_path.is_file():
        raise SystemExit(f"Audio file not found: {audio_path}")

    print("Sending audio to Gnani Prisma v3.0...")

    client = GnaniSTTClient(api_key=api_key)

    try:
        result = client.transcribe(
            str(audio_path),
            language_code="te-IN",
            model="prisma-v3.0",
            format="transcribe",
            topic="Telangana farming and agriculture",
        )
    except Exception as error:
        print(f"STT request failed: {error}")
        raise SystemExit(1)

    print("\n--- TRANSCRIPTION RESULT ---")
    print(result.get("transcript", "No transcript returned"))

    detected_language = result.get("detected_language_code")
    if detected_language:
        print(f"Detected language: {detected_language}")

    request_id = result.get("request_id")
    if request_id:
        print(f"Request ID: {request_id}")


if __name__ == "__main__":
    main()
