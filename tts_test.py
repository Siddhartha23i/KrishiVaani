
import os
from pathlib import Path

from dotenv import load_dotenv
from gnani.tts import GnaniTTSClient, AudioConfig


def main():
    load_dotenv()

    api_key = os.getenv("GNANI_API_KEY")
    if not api_key:
        raise SystemExit("Missing GNANI_API_KEY in .env")

    text = (
        "నమస్కారం రైతన్నా. "
        "మీ గ్రామం పేరు చెప్పండి. "
        "మీకు సరైన వ్యవసాయ సమాచారం అందిస్తాను."
    )

    # Start with a voice listed by the Timbre v2.5 catalogue.
    voice = "Kaveri"

    client = GnaniTTSClient(api_key=api_key)

    print("Generating Telugu speech with Timbre v2.5...")

    try:
        audio = client.synthesize(
            text,
            voice=voice,
            model="timbre-v2.5",
            language="te-IN",
            speed=0.95,
            audio_config=AudioConfig(
                container="wav",
                encoding="linear_pcm",
                sample_rate=48000,
            ),
        )
    except Exception as error:
        print(f"TTS request failed: {error}")
        raise SystemExit(1)

    output_path = Path("telugu-response.wav")
    output_path.write_bytes(audio)

    print(f"Audio saved to: {output_path.resolve()}")
    print(f"Audio size: {len(audio):,} bytes")


if __name__ == "__main__":
    main()
