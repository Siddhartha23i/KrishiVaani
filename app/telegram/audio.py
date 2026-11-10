"""
Audio conversion utilities for KrishiVaani Telegram Channel — Phase 8.3.

Converts Telegram OGG Opus voice notes to linear PCM WAV for processing by
VoicePipelineService (Prisma STT). Reuses bundled imageio-ffmpeg.
"""

import logging
import subprocess
import tempfile
from pathlib import Path
import imageio_ffmpeg

logger = logging.getLogger(__name__)


def convert_ogg_opus_to_wav(
    ogg_bytes: bytes,
    sample_rate: int = 16000,
) -> bytes:
    """
    Convert incoming Telegram OGG/Opus audio bytes to linear PCM WAV.
    Output: 16 kHz, 16-bit mono WAV.
    Cleans up all temporary files safely in a finally block.
    """
    if not ogg_bytes or len(ogg_bytes) == 0:
        raise ValueError("Incoming audio bytes payload is empty.")

    ogg_path: Path | None = None
    wav_path: Path | None = None

    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".ogg") as f_ogg:
            f_ogg.write(ogg_bytes)
            f_ogg.flush()
            ogg_path = Path(f_ogg.name)

        wav_path = ogg_path.with_suffix(".wav")
        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()

        proc = subprocess.run(
            [
                ffmpeg_exe,
                "-y",
                "-i", str(ogg_path),
                "-ar", str(sample_rate),
                "-ac", "1",
                "-f", "wav",
                str(wav_path),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=15,
        )

        if proc.returncode != 0 or not wav_path.exists() or wav_path.stat().st_size == 0:
            err_msg = proc.stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(f"FFmpeg conversion from OGG to WAV failed: {err_msg}")

        return wav_path.read_bytes()

    finally:
        for p in (ogg_path, wav_path):
            if p and p.exists():
                try:
                    p.unlink()
                except Exception as e:
                    logger.warning("Failed to remove temporary file %s: %s", p, e)

