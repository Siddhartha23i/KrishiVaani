"""
Audio Validation Service for KrishiVaani Telugu Voice Pipeline — Phase 8.0.

Enforces:
1. File format validation (.m4a, .wav, .mp3, .ogg, .aac, .flac).
2. Strict duration limit enforcement (Gnani REST 30.0-second limit).
3. Payload size check (maximum 15 MB).
4. Zero-byte/empty audio rejection.
"""

import os
import re
import wave
import struct
import logging
import subprocess
from pathlib import Path
from typing import Dict, Any, Optional

from app.voice.exceptions import (
    AudioValidationError,
    AudioDurationExceededError,
    UnsupportedAudioFormatError,
    AudioSizeExceededError,
)

logger = logging.getLogger(__name__)

SUPPORTED_AUDIO_EXTENSIONS = {".m4a", ".wav", ".mp3", ".ogg", ".aac", ".flac"}
SUPPORTED_MIME_TYPES = {
    "audio/m4a",
    "audio/mp4",
    "audio/x-m4a",
    "audio/wav",
    "audio/x-wav",
    "audio/wave",
    "audio/mpeg",
    "audio/mp3",
    "audio/ogg",
    "audio/opus",
    "audio/aac",
    "audio/flac",
    "application/octet-stream",
}

MAX_AUDIO_DURATION_SECONDS = 30.0
MAX_AUDIO_SIZE_BYTES = 15 * 1024 * 1024  # 15 MB


def inspect_audio_duration(file_path: Path) -> float:
    """
    Deterministically inspect audio duration in seconds without mutating the file.
    Supports WAV (standard library), M4A/MP4 (ISO BMFF box parser), and
    general containers (via imageio-ffmpeg bundled binary).
    """
    path_obj = Path(file_path)
    if not path_obj.exists():
        raise AudioValidationError(f"Audio file not found: {file_path}")

    ext = path_obj.suffix.lower()

    # Strategy 1: Standard Python wave module for WAV files
    if ext == ".wav":
        try:
            with wave.open(str(path_obj), "rb") as w:
                frames = w.getnframes()
                rate = w.getframerate()
                channels = w.getnchannels()
                sampwidth = w.getsampwidth()
                # Check for streaming INT_MAX header (common in live/streaming PCM WAV)
                if (frames == 2147483647 or frames <= 0) and rate > 0 and channels > 0 and sampwidth > 0:
                    file_size = path_obj.stat().st_size
                    pcm_bytes = max(0, file_size - 44)
                    return pcm_bytes / float(rate * channels * sampwidth)
                elif rate > 0:
                    return frames / float(rate)
        except Exception as e:
            logger.debug("WAV parser failed for %s: %s", path_obj.name, str(e))

    # Strategy 2: ISO Base Media File Format (BMFF) atom parser for M4A / MP4 / AAC
    if ext in (".m4a", ".mp4", ".aac"):
        try:
            with open(path_obj, "rb") as f:
                data = f.read(1024 * 1024)  # Read header up to 1MB
            moov_pos = data.find(b"moov")
            if moov_pos != -1:
                mvhd_pos = data.find(b"mvhd", moov_pos)
                if mvhd_pos != -1:
                    version = data[mvhd_pos + 4]
                    if version == 0:
                        timescale, duration = struct.unpack(
                            ">II", data[mvhd_pos + 16 : mvhd_pos + 24]
                        )
                    else:
                        timescale, duration = struct.unpack(
                            ">IQ", data[mvhd_pos + 24 : mvhd_pos + 36]
                        )
                    if timescale > 0:
                        return duration / float(timescale)
        except Exception as e:
            logger.debug("M4A ISO-BMFF parser failed for %s: %s", path_obj.name, str(e))

    # Strategy 3: Fast inspection via bundled imageio_ffmpeg
    try:
        import imageio_ffmpeg
        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
        proc = subprocess.run(
            [ffmpeg_exe, "-i", str(path_obj)],
            stderr=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
            timeout=10,
        )
        match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", proc.stderr)
        if match:
            h, m, s = match.groups()
            return int(h) * 3600 + int(m) * 60 + float(s)
    except Exception as e:
        logger.debug("imageio-ffmpeg inspection failed for %s: %s", path_obj.name, str(e))

    raise AudioValidationError(
        f"Unable to determine audio duration for file '{path_obj.name}'. File may be corrupt or unreadable."
    )


def validate_audio_file(
    file_path: Path,
    max_duration: float = MAX_AUDIO_DURATION_SECONDS,
    max_size_bytes: int = MAX_AUDIO_SIZE_BYTES,
) -> Dict[str, Any]:
    """
    Validate audio file against KrishiVaani format, size, and duration constraints.

    Returns:
        Dict with duration_seconds, size_bytes, and extension.

    Raises:
        AudioValidationError: file missing or empty.
        UnsupportedAudioFormatError: unaccepted extension.
        AudioSizeExceededError: file size > max_size_bytes.
        AudioDurationExceededError: duration > max_duration (strictly 30.0s).
    """
    path_obj = Path(file_path)
    if not path_obj.exists() or not path_obj.is_file():
        raise AudioValidationError(f"Audio file does not exist: {file_path}")

    size_bytes = path_obj.stat().st_size
    if size_bytes == 0:
        raise AudioValidationError("Audio file is empty (0 bytes).")

    if size_bytes > max_size_bytes:
        raise AudioSizeExceededError(
            f"Audio file size ({size_bytes / (1024*1024):.2f} MB) exceeds maximum allowed {max_size_bytes / (1024*1024):.0f} MB limit."
        )

    ext = path_obj.suffix.lower()
    if ext not in SUPPORTED_AUDIO_EXTENSIONS:
        raise UnsupportedAudioFormatError(
            f"Unsupported audio format '{ext}'. Supported formats: {', '.join(sorted(SUPPORTED_AUDIO_EXTENSIONS))}."
        )

    duration_seconds = inspect_audio_duration(path_obj)
    if duration_seconds > max_duration:
        raise AudioDurationExceededError(duration=duration_seconds, limit=max_duration)

    return {
        "duration_seconds": round(duration_seconds, 3),
        "size_bytes": size_bytes,
        "extension": ext,
    }

