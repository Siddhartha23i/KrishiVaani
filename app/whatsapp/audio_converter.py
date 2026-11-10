"""
Audio Conversion Service for WhatsApp Voice Notes — Phase 8.1.

Converts linear PCM WAV (produced by Gnani Timbre) into WhatsApp-compatible
mono OGG encoded with Opus codec using bundled ffmpeg.
Validates playability and strictly cleans up temporary audio files.
"""

import os
import subprocess
import tempfile
import logging
from pathlib import Path
from typing import Optional, Tuple
import imageio_ffmpeg

from app.whatsapp.exceptions import WhatsAppAudioConversionError

logger = logging.getLogger(__name__)


def validate_audio_playability(file_path: Path) -> bool:
    """
    Validate that an audio file is fully decodeable and playable using ffmpeg.
    Returns True if decode check succeeds with zero errors.
    """
    path_obj = Path(file_path)
    if not path_obj.exists() or path_obj.stat().st_size == 0:
        return False

    try:
        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
        proc = subprocess.run(
            [ffmpeg_exe, "-v", "error", "-i", str(path_obj), "-f", "null", "-"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10,
        )
        return proc.returncode == 0
    except Exception as e:
        logger.warning("Playability check error for %s: %s", path_obj.name, str(e))
        return False


def convert_wav_to_ogg_opus(
    wav_path: Path,
    output_path: Optional[Path] = None,
    bitrate: str = "24k",
) -> Path:
    """
    Convert a WAV audio file into a mono OGG Opus file.

    Parameters:
        wav_path: Path to existing WAV file.
        output_path: Optional destination path. If omitted, uses same stem + '.ogg'.
        bitrate: Target Opus bitrate (default: 24k).

    Returns:
        Path to the converted .ogg file.

    Raises:
        WhatsAppAudioConversionError: if conversion or playability check fails.
    """
    in_path = Path(wav_path)
    if not in_path.exists():
        raise WhatsAppAudioConversionError(f"Input WAV file does not exist: {wav_path}")

    target_ogg = output_path or in_path.with_suffix(".ogg")

    try:
        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
        cmd = [
            ffmpeg_exe,
            "-y",  # Overwrite destination if exists
            "-i", str(in_path),
            "-ac", "1",  # Strictly Mono
            "-c:a", "libopus",  # Opus Codec
            "-b:a", bitrate,  # Voice bitrate
            "-f", "ogg",  # OGG container
            str(target_ogg),
        ]
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=15,
        )

        if proc.returncode != 0:
            err_msg = proc.stderr.decode("utf-8", errors="replace").strip()
            raise WhatsAppAudioConversionError(f"ffmpeg conversion failed: {err_msg}")

        if not target_ogg.exists() or target_ogg.stat().st_size == 0:
            raise WhatsAppAudioConversionError("ffmpeg created an empty or missing output file.")

        # Validate playability
        if not validate_audio_playability(target_ogg):
            raise WhatsAppAudioConversionError(
                f"Generated OGG Opus file '{target_ogg.name}' failed playability validation."
            )

        logger.debug(
            "Converted %s (%d bytes) -> %s (%d bytes)",
            in_path.name,
            in_path.stat().st_size,
            target_ogg.name,
            target_ogg.stat().st_size,
        )
        return target_ogg

    except WhatsAppAudioConversionError:
        raise
    except Exception as e:
        raise WhatsAppAudioConversionError(f"Unexpected error during audio conversion: {str(e)}") from e


def convert_wav_bytes_to_ogg_opus(
    wav_bytes: bytes,
    bitrate: str = "24k",
) -> Tuple[bytes, float]:
    """
    Convert WAV bytes into OGG Opus bytes in memory using short-lived temporary files.
    Guarantees strict deletion of both temporary files in a finally block.

    Returns:
        (ogg_bytes, duration_seconds)
    """
    if not wav_bytes or len(wav_bytes) == 0:
        raise WhatsAppAudioConversionError("WAV bytes payload is empty.")

    wav_temp: Optional[Path] = None
    ogg_temp: Optional[Path] = None

    try:
        # Write temporary WAV
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as f_wav:
            f_wav.write(wav_bytes)
            f_wav.flush()
            wav_temp = Path(f_wav.name)

        ogg_temp = wav_temp.with_suffix(".ogg")

        # Convert to OGG Opus
        convert_wav_to_ogg_opus(wav_temp, output_path=ogg_temp, bitrate=bitrate)

        # Inspect duration
        from app.voice.validator import inspect_audio_duration
        try:
            duration = inspect_audio_duration(ogg_temp)
        except Exception:
            duration = 0.0

        ogg_bytes = ogg_temp.read_bytes()
        return ogg_bytes, duration

    finally:
        # Strict cleanup of both temporary files
        if wav_temp and wav_temp.exists():
            try:
                wav_temp.unlink()
            except Exception as e:
                logger.warning("Failed to unlink temporary wav file %s: %s", wav_temp, e)

        if ogg_temp and ogg_temp.exists():
            try:
                ogg_temp.unlink()
            except Exception as e:
                logger.warning("Failed to unlink temporary ogg file %s: %s", ogg_temp, e)

