"""
Farmer onboarding and profile management routes.
Exposes endpoints under /api/v1/farmers.
"""

from fastapi import APIRouter, HTTPException, status
from app.schemas.farmer import (
    LocationPreviewRequest,
    LocationPreviewResponse,
    FarmerCreateRequest,
    FarmerLocationUpdateRequest,
    FarmerResponse,
)
from app.services.farmer_service import (
    FarmerService,
    FarmerConsentRequiredError,
    LocationConfirmationRequiredError,
    InvalidLocationDataError,
    DuplicateWhatsAppIdentifierError,
)

router = APIRouter()
farmer_service = FarmerService()


@router.post(
    "/onboarding/preview",
    response_model=LocationPreviewResponse,
    summary="Preview and Validate Location",
    description="Validates candidate location from transcript or structured input. Never persists data.",
)
async def preview_location(request: LocationPreviewRequest):
    """
    Preview candidate location details and generate voice confirmation dialogues.
    """
    return farmer_service.preview_location(request)


@router.post(
    "",
    response_model=FarmerResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create Farmer Profile",
    description="Persist farmer profile with confirmed location and explicit consent.",
)
async def create_farmer(request: FarmerCreateRequest):
    """
    Register a newly onboarded farmer.
    Enforces explicit consent and location confirmation before persisting.
    """
    try:
        farmer = farmer_service.create_farmer(request)
        return farmer
    except FarmerConsentRequiredError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    except LocationConfirmationRequiredError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    except InvalidLocationDataError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    except DuplicateWhatsAppIdentifierError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        )


@router.get(
    "/{farmer_id}",
    response_model=FarmerResponse,
    summary="Retrieve Farmer Profile",
    description="Fetch a farmer's profile by their unique internal ID.",
)
async def get_farmer(farmer_id: str):
    """
    Retrieve profile details. Used for internal routing and local verification.
    """
    farmer = farmer_service.get_farmer_by_id(farmer_id)
    if not farmer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Farmer profile with ID '{farmer_id}' not found.",
        )
    return farmer


@router.patch(
    "/{farmer_id}/location",
    response_model=FarmerResponse,
    summary="Update Farmer Location",
    description="Update location details when a farmer moves or corrects their information.",
)
async def update_farmer_location(farmer_id: str, request: FarmerLocationUpdateRequest):
    """
    Update location for an existing farmer profile.
    """
    try:
        updated = farmer_service.update_farmer_location(farmer_id, request)
        if not updated:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Farmer profile with ID '{farmer_id}' not found.",
            )
        return updated
    except InvalidLocationDataError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )


@router.delete(
    "/{farmer_id}",
    summary="Delete Farmer Profile",
    description="Permanently remove a farmer profile and associated personal data upon request.",
)
async def delete_farmer(farmer_id: str):
    """
    Privacy compliance endpoint. Completely erases profile data from the database.
    """
    deleted = farmer_service.delete_farmer(farmer_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Farmer profile with ID '{farmer_id}' not found.",
        )
    return {
        "message": "Farmer profile and personal data deleted successfully",
        "farmer_id": farmer_id,
    }

