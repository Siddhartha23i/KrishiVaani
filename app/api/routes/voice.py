"""
FastAPI Router for KrishiVaani Telugu Voice Pipeline — Phase 8.0.
Exposes multipart audio upload endpoint for voice conversations.
"""

from typing import Optional
from fastapi import APIRouter, UploadFile, File, Form, HTTPException, status
import logging

from app.conversation.schemas import LocationInput
from app.voice.schemas import VoiceProcessingRequest, VoiceProcessingResponse
from app.voice.service import VoicePipelineService
from app.voice.exceptions import (
    AudioDurationExceededError,
    UnsupportedAudioFormatError,
    AudioValidationError,
    VoicePipelineError,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post(
    "/process",
    response_model=VoiceProcessingResponse,
    summary="Process Farmer Spoken Audio",
    description="Accepts Telugu/multilingual audio (strictly <= 30 seconds), transcribes via Prisma v3.0, "
    "processes through KrishiVaani conversation orchestrator, and returns synthesized Timbre v2.5 WAV audio.",
)
async def process_voice(
    file: UploadFile = File(..., description="Spoken audio file (.m4a, .wav, .mp3, .ogg, .aac, .flac) <= 30 seconds"),
    farmer_id: Optional[str] = Form(None, description="Optional registered farmer profile ID"),
    district: Optional[str] = Form(None, description="Optional confirmed district name"),
    mandal: Optional[str] = Form(None, description="Optional confirmed mandal name"),
    village: Optional[str] = Form(None, description="Optional confirmed village name"),
    language: str = Form("te-IN", description="Language code: te-IN (default), hi-IN, or en-IN"),
    as_of_date: Optional[str] = Form(None, description="Optional reference date YYYY-MM-DD"),
) -> VoiceProcessingResponse:
    """
    End-to-end voice conversation endpoint for farmers.
    """
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file must have a valid filename with an audio extension.",
        )

    try:
        audio_bytes = await file.read()
    except Exception as read_err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to read uploaded audio file: {str(read_err)}",
        )

    if not audio_bytes or len(audio_bytes) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded audio file is empty (0 bytes).",
        )

    location_input = None
    if district or mandal or village:
        location_input = LocationInput(
            district=district,
            mandal=mandal,
            village=village,
            location_confirmed=True,
        )

    request_payload = VoiceProcessingRequest(
        farmer_id=farmer_id,
        location=location_input,
        language=language,
        as_of_date=as_of_date,
    )

    try:
        service = VoicePipelineService()
        result = service.process_audio_bytes(
            audio_bytes=audio_bytes,
            filename=file.filename,
            request=request_payload,
        )
        return result
    except AudioDurationExceededError as e:
        logger.warning("Voice endpoint rejected: duration exceeded limit (%s)", e)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except UnsupportedAudioFormatError as e:
        logger.warning("Voice endpoint rejected: unsupported format (%s)", e)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except AudioValidationError as e:
        logger.warning("Voice endpoint rejected: validation error (%s)", e)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except VoicePipelineError as e:
        logger.error("Voice pipeline error: %s", e)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
    except Exception as e:
        logger.error("Unhandled voice processing error: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal voice processing failure: {str(e)}",
        )

