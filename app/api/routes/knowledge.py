"""
Knowledge Base retrieval routes.
Exposes read-only verified agricultural guidance endpoints under /api/v1/knowledge.
Enhanced in Phase 5.1 with explicit knowledge types, date-aware search, and season planning horizons.
"""

from typing import Optional
from fastapi import APIRouter, Query
from app.knowledge.schemas import (
    KnowledgeSearchFilterSchema,
    KnowledgeSearchResponseSchema,
)
from app.knowledge.service import KnowledgeService

router = APIRouter()
knowledge_service = KnowledgeService()


@router.get(
    "/search",
    response_model=KnowledgeSearchResponseSchema,
    summary="Search Verified Agricultural Guidance",
    description=(
        "Retrieve authoritative, source-verified, and currently applicable "
        "agricultural advisories, crop calendars, and government scheme guidance."
    ),
)
async def search_knowledge(
    category: Optional[str] = Query(None, description="Domain category (e.g. 'crop_selection', 'government_schemes')"),
    knowledge_type: Optional[str] = Query(None, description="Knowledge type ('static_reference', 'seasonal_guidance', 'time_bound_advisory')"),
    crop_name: Optional[str] = Query(None, description="Crop name (e.g. 'Cotton', 'Paddy', 'Red Gram')"),
    crop_variety: Optional[str] = Query(None, description="Specific seed or crop variety"),
    crop_stage: Optional[str] = Query(None, description="Growth stage (e.g. 'sowing', 'flowering', 'harvesting')"),
    state: Optional[str] = Query("Telangana", description="Applicable state (defaults to 'Telangana')"),
    district: Optional[str] = Query(None, description="Applicable district (e.g. 'Medchal-Malkajgiri', 'Warangal')"),
    mandal: Optional[str] = Query(None, description="Applicable mandal"),
    village: Optional[str] = Query(None, description="Applicable village"),
    season: Optional[str] = Query(None, description="Explicit agricultural season (e.g. 'Kharif', 'Rabi')"),
    season_year: Optional[int] = Query(None, description="Season year (e.g. 2026)"),
    planning_horizon: Optional[str] = Query(None, description="Planning horizon: 'current' (active season), 'upcoming' (next season)"),
    as_of_date: Optional[str] = Query(None, description="Reference ISO date (defaults to current date in Asia/Kolkata timezone)"),
    language_code: Optional[str] = Query(None, description="Language ('te-IN', 'hi-IN', 'en-IN')"),
    soil_type: Optional[str] = Query(None, description="Soil classification (e.g. 'Black cotton', 'Red loamy')"),
    water_condition: Optional[str] = Query(None, description="Water availability (e.g. 'Irrigated', 'Rainfed')"),
):
    """
    Search active, source-verified knowledge records.
    Expired or unverified records are automatically excluded.
    """
    filters = KnowledgeSearchFilterSchema(
        category=category,
        knowledge_type=knowledge_type,
        crop_name=crop_name,
        crop_variety=crop_variety,
        crop_stage=crop_stage,
        state=state,
        district=district,
        mandal=mandal,
        village=village,
        season=season,
        season_year=season_year,
        planning_horizon=planning_horizon,
        as_of_date=as_of_date,
        language_code=language_code,
        soil_type=soil_type,
        water_condition=water_condition,
    )
    return knowledge_service.search_guidance(filters)


@router.get(
    "/{knowledge_id}/audit-trail",
    summary="Get Knowledge Verification Audit Trail",
    description="Retrieve chronological immutable verification and re-review audit log for a knowledge record.",
)
async def get_knowledge_audit_trail(knowledge_id: str):
    """
    Returns audit trail showing verification, re-review, and rejection history
    with explicit test-verifier vs official-verifier designation.
    NOTE: In production, administrative authentication is required to access audit trails.
    """
    item = knowledge_service.repository.get_item_by_id(knowledge_id)
    if not item:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Knowledge item '{knowledge_id}' not found.")
    return {
        "knowledge_id": knowledge_id,
        "title": item.title,
        "verification_status": item.verification_status,
        "audit_trail": knowledge_service.get_item_audit_trail(knowledge_id),
    }
