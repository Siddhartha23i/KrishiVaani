"""
Farmer service managing onboarding, profile persistence, location updates, and privacy lifecycle.
Enforces strict consent checks and data minimization principles.
"""

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from app.db.farmer_repository import FarmerRepository
from app.models.farmer import FarmerModel
from app.schemas.farmer import (
    LocationPreviewRequest,
    LocationPreviewResponse,
    FarmerCreateRequest,
    FarmerLocationUpdateRequest,
)
from app.services.location_service import (
    LocationService,
    normalize_whitespace,
    normalize_and_validate_pin,
)


class DuplicateWhatsAppIdentifierError(Exception):
    """Raised when a profile already exists for the given WhatsApp ID."""
    pass


class FarmerConsentRequiredError(Exception):
    """Raised when profile creation is attempted without explicit farmer consent."""
    pass


class LocationConfirmationRequiredError(Exception):
    """Raised when profile creation is attempted without farmer confirmation."""
    pass


class InvalidLocationDataError(Exception):
    """Raised when village or PIN code data fails format validation."""
    pass


class FarmerService:
    """
    Business service orchestrating farmer profile lifecycle.
    """

    def __init__(self, db_path: Optional[Path] = None):
        self.repository = FarmerRepository(db_path=db_path)

    def preview_location(self, request: LocationPreviewRequest) -> LocationPreviewResponse:
        """
        Validate candidate location details.
        STRICT RULE: Preview never persists data to the database.
        """
        return LocationService.preview_location(request)

    def create_farmer(self, request: FarmerCreateRequest) -> FarmerModel:
        """
        Create and persist a new farmer profile.

        Enforces:
        - Explicit farmer consent (consent_given must be True).
        - Location confirmation (location_confirmed must be True).
        - Validated village and PIN code.
        - Safe handling of duplicate WhatsApp identifiers.
        """
        if not request.consent_given:
            raise FarmerConsentRequiredError(
                "Explicit farmer consent is required before saving any profile information."
            )

        if not request.location_confirmed:
            raise LocationConfirmationRequiredError(
                "Farmer must confirm the interpreted location before the profile can be created."
            )

        # Normalize and validate village
        village = normalize_whitespace(request.village_name)
        if not village:
            raise InvalidLocationDataError("Village name is required.")

        # Normalize and validate PIN code
        normalized_pin, pin_valid = normalize_and_validate_pin(request.pin_code)
        if not pin_valid or not normalized_pin:
            raise InvalidLocationDataError(
                f"Invalid 6-digit Indian PIN code: '{request.pin_code}'. Must be 6 digits and start with 1-9."
            )

        # Check duplicate WhatsApp identifier if provided
        if request.whatsapp_user_id:
            existing = self.repository.get_by_whatsapp_id(request.whatsapp_user_id)
            if existing:
                raise DuplicateWhatsAppIdentifierError(
                    f"A farmer profile already exists for the provided WhatsApp ID."
                )

        now_iso = datetime.now(timezone.utc).isoformat()
        farmer = FarmerModel(
            farmer_id=str(uuid.uuid4()),
            whatsapp_user_id=request.whatsapp_user_id,
            preferred_language=request.preferred_language or "te-IN",
            village_name=village,
            mandal_name=normalize_whitespace(request.mandal_name),
            district_name=normalize_whitespace(request.district_name),
            pin_code=normalized_pin,
            latitude=request.latitude,
            longitude=request.longitude,
            location_source=request.location_source or "voice_transcript",
            location_confirmed=True,
            consent_given=True,
            consent_given_at=now_iso,
            weather_provider_sharing_consent=getattr(request, "weather_provider_sharing_consent", False),
            weather_provider_sharing_consent_at=now_iso if getattr(request, "weather_provider_sharing_consent", False) else None,
            weather_provider_disclosure_version=getattr(request, "weather_provider_disclosure_version", None) if getattr(request, "weather_provider_sharing_consent", False) else None,
            created_at=now_iso,
            updated_at=now_iso,
        )

        return self.repository.create(farmer)

    def get_farmer_by_id(self, farmer_id: str) -> Optional[FarmerModel]:
        """Retrieve farmer profile by internal ID."""
        return self.repository.get_by_id(farmer_id)

    def get_farmer_by_whatsapp_id(self, whatsapp_user_id: str) -> Optional[FarmerModel]:
        """Retrieve farmer profile by WhatsApp identifier."""
        return self.repository.get_by_whatsapp_id(whatsapp_user_id)

    def update_farmer_location(
        self,
        farmer_id: str,
        request: FarmerLocationUpdateRequest,
    ) -> Optional[FarmerModel]:
        """
        Update location details for an existing farmer profile.
        Validates PIN if a new one is provided.
        """
        existing = self.repository.get_by_id(farmer_id)
        if not existing:
            return None

        # Validate PIN code if updated
        new_pin = None
        if request.pin_code is not None:
            new_pin, pin_valid = normalize_and_validate_pin(request.pin_code)
            if not pin_valid:
                raise InvalidLocationDataError(
                    f"Invalid 6-digit Indian PIN code: '{request.pin_code}'."
                )

        new_village = normalize_whitespace(request.village_name) if request.village_name is not None else None
        new_mandal = normalize_whitespace(request.mandal_name) if request.mandal_name is not None else None
        new_district = normalize_whitespace(request.district_name) if request.district_name is not None else None
        now_iso = datetime.now(timezone.utc).isoformat()

        return self.repository.update_location(
            farmer_id=farmer_id,
            village_name=new_village,
            mandal_name=new_mandal,
            district_name=new_district,
            pin_code=new_pin,
            latitude=request.latitude,
            longitude=request.longitude,
            location_source=request.location_source or "manual_text",
            location_confirmed=request.location_confirmed,
            updated_at=now_iso,
        )

    def update_weather_sharing_consent(
        self,
        farmer_id: str,
        consent_given: bool,
        disclosure_version: str = "v1.0",
    ) -> Optional[FarmerModel]:
        """
        Record explicit consent decision for third-party weather provider location sharing.
        Phase 6.1.1 privacy refinement.
        """
        existing = self.repository.get_by_id(farmer_id)
        if not existing:
            return None

        now_iso = datetime.now(timezone.utc).isoformat()
        consent_at = now_iso if consent_given else None

        return self.repository.update_weather_sharing_consent(
            farmer_id=farmer_id,
            consent_given=consent_given,
            consent_at=consent_at,
            disclosure_version=disclosure_version,
            updated_at=now_iso,
        )

    def delete_farmer(self, farmer_id: str) -> bool:
        """
        Permanently delete farmer profile and personal data upon request.
        """
        return self.repository.delete(farmer_id)

