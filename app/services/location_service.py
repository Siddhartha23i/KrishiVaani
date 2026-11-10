"""
Location validation and interpretation service.
Handles whitespace normalization, Indic digit translation, PIN code extraction/validation,
and voice-friendly confirmation prompt generation.
"""

import re
from typing import Optional, List, Tuple
from app.schemas.farmer import (
    LocationPreviewRequest,
    LocationPreviewResponse,
    InterpretedLocation,
)
from app.content.onboarding import (
    get_location_confirmation_prompt,
    get_clarification_prompt,
)

# Indic digits mapping to ASCII 0-9
# Telugu: ౦=0 to ౯=9
# Devanagari: ०=0 to ९=9
INDIC_DIGITS_TABLE = str.maketrans(
    "౦౧౨౩౪౫౬౭౮౯०१२३४५६७८९",
    "01234567890123456789"
)

# Standard Indian postal PIN code format: 6 digits, does not start with 0
PIN_CODE_PATTERN = re.compile(r"^[1-9][0-9]{5}$")

# Regex to detect 6-digit sequences that may have spaces or hyphens between digits
PIN_EXTRACT_PATTERN = re.compile(
    r"(?:^|[^\d])([1-9](?:[\s-]*\d){5})(?:$|[^\d])"
)

# Basic heuristic patterns for extracting village name from speech transcript
# if not explicitly supplied as a structured field
VILLAGE_EXTRACT_PATTERNS = [
    re.compile(r"(?:village(?:\s*(?:name|is|:)?\s*))([A-Za-z\u0C00-\u0C7F\u0900-\u097F]+)", re.IGNORECASE),
    re.compile(r"(?:గ్రామం|ఊరు|విలేజ్)(?:\s*(?:పేరు|is|:)?\s*)([A-Za-z\u0C00-\u0C7F]+)", re.IGNORECASE),
    re.compile(r"(?:गाँव|गांव|विलेज)(?:\s*(?:नाम|है|:)?\s*)([A-Za-z\u0900-\u097F]+)", re.IGNORECASE),
]


def normalize_whitespace(text: Optional[str]) -> Optional[str]:
    """Strip leading/trailing whitespace and collapse internal consecutive spaces."""
    if not text:
        return None
    cleaned = re.sub(r"\s+", " ", text.strip())
    return cleaned if cleaned else None


def normalize_indic_digits(text: str) -> str:
    """Convert Telugu and Devanagari numeral characters to standard ASCII digits."""
    if not text:
        return ""
    return text.translate(INDIC_DIGITS_TABLE)


def normalize_and_validate_pin(raw_pin: Optional[str]) -> Tuple[Optional[str], bool]:
    """
    Normalizes a candidate PIN code string:
    - Converts Indic digits to standard ASCII.
    - Strips internal spaces or hyphens (e.g. '500 014' or '5 0 0 0 1 4').
    - Validates against Indian 6-digit postal PIN standards (100000 - 999999).
    Returns (normalized_pin, is_valid).
    """
    if not raw_pin:
        return None, False

    converted = normalize_indic_digits(raw_pin)
    cleaned = re.sub(r"[\s-]+", "", converted)

    if PIN_CODE_PATTERN.match(cleaned):
        return cleaned, True

    # If it fails validation, return cleaned representation if non-empty, marked invalid
    return cleaned if cleaned else None, False


def extract_pin_from_text(text: Optional[str]) -> Tuple[Optional[str], bool]:
    """
    Deterministically search for a 6-digit Indian PIN code within arbitrary text.
    Handles Indic numerals and spaces between digits.
    """
    if not text:
        return None, False

    converted = normalize_indic_digits(text)
    match = PIN_EXTRACT_PATTERN.search(converted)
    if match:
        candidate = re.sub(r"[\s-]+", "", match.group(1))
        if PIN_CODE_PATTERN.match(candidate):
            return candidate, True

    return None, False


def extract_village_from_text(text: Optional[str]) -> Optional[str]:
    """
    Attempt deterministic extraction of village name from speech transcript.
    Returns normalized village name if unambiguous pattern matched, else None.
    """
    if not text:
        return None

    for pattern in VILLAGE_EXTRACT_PATTERNS:
        match = pattern.search(text)
        if match:
            candidate = match.group(1).strip()
            # Exclude common false positives or stopwords
            if len(candidate) >= 2 and not candidate.isdigit():
                return normalize_whitespace(candidate)

    return None


class LocationService:
    """
    Service responsible for parsing, validating, and formatting farmer location details.
    """

    @classmethod
    def preview_location(cls, request: LocationPreviewRequest) -> LocationPreviewResponse:
        """
        Preview and validate candidate location details without persisting.
        """
        missing_fields: List[str] = []
        clarification_required = False

        # 1. Village name resolution
        village = normalize_whitespace(request.village_name)
        if not village and request.transcript:
            village = extract_village_from_text(request.transcript)

        if not village:
            missing_fields.append("village_name")
            clarification_required = True

        # 2. PIN code resolution & validation
        pin_code = None
        pin_valid = False

        if request.pin_code:
            pin_code, pin_valid = normalize_and_validate_pin(request.pin_code)
        elif request.transcript:
            pin_code, pin_valid = extract_pin_from_text(request.transcript)

        if not pin_code:
            missing_fields.append("pin_code")
            clarification_required = True
        elif not pin_valid:
            clarification_required = True

        # 3. Optional location fields
        mandal = normalize_whitespace(request.mandal_name)
        district = normalize_whitespace(request.district_name)

        interpreted = InterpretedLocation(
            village_name=village,
            mandal_name=mandal,
            district_name=district,
            pin_code=pin_code,
            latitude=request.latitude,
            longitude=request.longitude,
        )

        ready_for_confirmation = (
            pin_valid and
            bool(village) and
            not missing_fields and
            not clarification_required
        )

        # 4. Generate voice-friendly summary/dialogue
        lang = request.preferred_language or "te-IN"
        if ready_for_confirmation:
            summary = get_location_confirmation_prompt(
                language_code=lang,
                village=village,  # type: ignore[arg-type]
                pin_code=pin_code,  # type: ignore[arg-type]
                mandal=mandal,
                district=district,
            )
        else:
            summary = get_clarification_prompt(
                language_code=lang,
                missing_fields=missing_fields if missing_fields else (["pin_code"] if not pin_valid else [])
            )

        return LocationPreviewResponse(
            interpreted_location=interpreted,
            pin_valid=pin_valid,
            missing_fields=missing_fields,
            clarification_required=clarification_required,
            location_summary=summary,
            ready_for_confirmation=ready_for_confirmation,
        )

