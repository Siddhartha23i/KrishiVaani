"""
Knowledge Base business logic and verification engine.
Enforces strict provenance validation, lifecycle transitions, explicit knowledge types,
review policies, agricultural season awareness, and date-aware guidance retrieval.
"""

import uuid
from datetime import datetime, date, timezone
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple
from zoneinfo import ZoneInfo

from app.knowledge.models import (
    KnowledgeItemModel,
    KnowledgeSourceModel,
    KnowledgeCategory,
    KnowledgeType,
    VerificationStatus,
    AuthorityStatus,
    TranslationStatus,
    KnowledgeItemWithSourcesModel,
)
from app.knowledge.schemas import (
    KnowledgeSearchFilterSchema,
    KnowledgeSearchResponseSchema,
    KnowledgeItemResponseSchema,
    SourceProvenanceSchema,
)
from app.knowledge.repository import KnowledgeRepository
from app.knowledge.source_registry import SourceRegistry, SourceValidationError
from app.knowledge.season_calendar import AgriculturalCalendar

# Indian Standard Time (IST)
IST_ZONE = ZoneInfo("Asia/Kolkata")


class KnowledgeVerificationError(Exception):
    """Raised when a knowledge item fails prerequisite verification checks."""
    pass


class SourceProvenanceMissingError(Exception):
    """Raised when an item is submitted without supporting source citation."""
    pass


class KnowledgeService:
    """
    Service responsible for knowledge ingestion, verification workflows,
    and authoritative search retrieval.
    """

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path
        self.repository = KnowledgeRepository(db_path=db_path)
        self.source_registry = SourceRegistry(db_path=db_path)

    # -------------------------------------------------------------------------
    # Ingestion & Linking
    # -------------------------------------------------------------------------
    def ingest_item(
        self,
        category: KnowledgeCategory,
        title: str,
        content: str,
        source_id: str,
        reference_location: Optional[str] = None,
        knowledge_type: KnowledgeType = KnowledgeType.SEASONAL_GUIDANCE,
        language_code: str = "te-IN",
        translation_status: TranslationStatus = TranslationStatus.ORIGINAL,
        state: str = "Telangana",
        district: Optional[str] = None,
        mandal: Optional[str] = None,
        village: Optional[str] = None,
        pin_code: Optional[str] = None,
        crop_name: Optional[str] = None,
        crop_variety: Optional[str] = None,
        crop_stage: Optional[str] = None,
        season: Optional[str] = None,
        season_year: Optional[int] = None,
        soil_type: Optional[str] = None,
        water_condition: Optional[str] = None,
        applicable_from: Optional[str] = None,
        applicable_until: Optional[str] = None,
        publication_date: Optional[str] = None,
        is_permanent_reference: bool = False,
        review_cycle_days: Optional[int] = None,
        last_reviewed_at: Optional[str] = None,
        retrieval_applicability_notes: Optional[str] = None,
        initial_status: VerificationStatus = VerificationStatus.PENDING_VERIFICATION,
    ) -> KnowledgeItemWithSourcesModel:
        """
        Ingest a new knowledge item.
        STRICT RULE: Every record MUST link to a valid registered source.
        New records default to PENDING_VERIFICATION (never automatically verified).
        """
        # Ensure source exists
        source = self.repository.get_source_by_id(source_id)
        if not source:
            raise SourceProvenanceMissingError(
                f"Cannot ingest item without a valid source citation. Source '{source_id}' does not exist."
            )

        now_iso = datetime.now(timezone.utc).isoformat()
        item_id = str(uuid.uuid4())

        # Disallow automatic verification at ingestion
        safe_status = (
            VerificationStatus.PENDING_VERIFICATION
            if initial_status == VerificationStatus.VERIFIED
            else initial_status
        )

        item = KnowledgeItemModel(
            knowledge_id=item_id,
            category=category.value,
            knowledge_type=knowledge_type.value,
            title=title.strip(),
            content=content.strip(),
            language_code=language_code,
            translation_status=translation_status.value,
            state=state.strip(),
            district=district.strip() if district else None,
            mandal=mandal.strip() if mandal else None,
            village=village.strip() if village else None,
            pin_code=pin_code.strip() if pin_code else None,
            crop_name=crop_name.strip() if crop_name else None,
            crop_variety=crop_variety.strip() if crop_variety else None,
            crop_stage=crop_stage.strip() if crop_stage else None,
            season=season.strip() if season else None,
            season_year=season_year,
            soil_type=soil_type.strip() if soil_type else None,
            water_condition=water_condition.strip() if water_condition else None,
            applicable_from=applicable_from,
            applicable_until=applicable_until,
            publication_date=publication_date,
            is_permanent_reference=is_permanent_reference,
            review_cycle_days=review_cycle_days,
            last_reviewed_at=last_reviewed_at,
            verification_status=safe_status.value,
            verified_at=None,
            verified_by=None,
            retrieval_applicability_notes=retrieval_applicability_notes,
            created_at=now_iso,
            updated_at=now_iso,
        )

        created_item = self.repository.create_item(item)
        self.repository.link_item_source(
            item_id=item_id,
            source_id=source_id,
            reference_location=reference_location,
            created_at=now_iso,
        )

        sources = self.repository.get_sources_for_item(item_id)
        return KnowledgeItemWithSourcesModel(item=created_item, sources=sources)

    # -------------------------------------------------------------------------
    # Verification Engine (Phase 5.1 & 5.2 Strengthened Verification Gates & Accountability)
    # -------------------------------------------------------------------------
    def verify_item(
        self,
        knowledge_id: str,
        verified_by: str = "Agricultural Verification Officer",
        is_test: Optional[bool] = None,
        notes: Optional[str] = None,
    ) -> KnowledgeItemWithSourcesModel:
        """
        Approve and mark a knowledge item as VERIFIED.

        Enforces all 8 prerequisite verification gates:
        Gate 1: Item must exist.
        Gate 2: Supporting source citation must exist.
        Gate 3: Linked source must have authority_status == 'approved'.
        Gate 4: Source URL must be traceable (not placeholder, mock, or malformed).
        Gate 5: Meaningful citation location (page, table, section, heading) is mandatory.
        Gate 6: Geographic applicability (state) must be explicitly supported.
        Gate 7: Temporal applicability:
                - time_bound_advisory MUST have applicable_until.
                - seasonal_guidance MUST have season AND applicable_until.
                - static_reference MUST be explicitly classified as permanent reference with review cycle.
        Gate 8: Translation status cannot be machine_translated_unverified.
        Gate 9: Reviewer and verification timestamp must be recorded.

        Reviewer Accountability (Phase 5.2):
        - Distinguishes test reviewer identities from actual official verifiers.
        - Records an immutable audit log entry in knowledge_verification_audit.
        - NOTE: In production, authenticated administrative authorization (RBAC/JWT)
          is required to bind verified_by to a certified agronomist/officer identity.
        """
        item = self.repository.get_item_by_id(knowledge_id)
        if not item:
            raise KnowledgeVerificationError(f"Knowledge item '{knowledge_id}' not found.")

        # Gate 2 & 3: Check linked sources and approval
        sources = self.repository.get_sources_for_item(knowledge_id)
        if not sources:
            raise KnowledgeVerificationError(
                f"Cannot verify item '{knowledge_id}': no supporting source citation attached."
            )

        approved_sources = [
            s for s in sources if s.authority_status == AuthorityStatus.APPROVED.value
        ]
        if not approved_sources:
            raise KnowledgeVerificationError(
                f"Cannot verify item '{knowledge_id}': none of its linked sources are approved."
            )

        # Gate 4: Source URL traceability
        for src in approved_sources:
            is_valid_url, reason = SourceRegistry.validate_source_url(src.source_url)
            if not is_valid_url:
                raise KnowledgeVerificationError(
                    f"Cannot verify item: supporting source '{src.source_id}' has untraceable or placeholder URL: {reason}"
                )

        # Gate 5: Meaningful citation location (page, table, section)
        has_valid_citation = any(
            bool(s.reference_location and len(s.reference_location.strip()) >= 3)
            for s in approved_sources
        )
        if not has_valid_citation:
            raise KnowledgeVerificationError(
                f"Cannot verify item '{knowledge_id}': at least one meaningful citation location "
                "(page number, table, section, or heading) is required."
            )

        # Gate 6: Geographic applicability
        if not item.state:
            raise KnowledgeVerificationError(
                f"Cannot verify item '{knowledge_id}': geographic applicability (state) must be documented."
            )

        # Gate 7: Temporal applicability based on knowledge_type
        k_type = item.knowledge_type
        if k_type == KnowledgeType.TIME_BOUND_ADVISORY.value:
            if not item.applicable_until:
                raise KnowledgeVerificationError(
                    f"Cannot verify time-bound advisory '{knowledge_id}': explicit validity expiry (applicable_until) is mandatory."
                )
        elif k_type == KnowledgeType.SEASONAL_GUIDANCE.value:
            if not item.season:
                raise KnowledgeVerificationError(
                    f"Cannot verify seasonal guidance '{knowledge_id}': season applicability is mandatory."
                )
            if not item.applicable_until:
                raise KnowledgeVerificationError(
                    f"Cannot verify seasonal guidance '{knowledge_id}': documented validity expiry (applicable_until) is mandatory."
                )
        elif k_type == KnowledgeType.STATIC_REFERENCE.value:
            if not item.is_permanent_reference:
                raise KnowledgeVerificationError(
                    f"Cannot verify static reference '{knowledge_id}': must be explicitly classified with is_permanent_reference=True."
                )
            if not item.review_cycle_days and not item.last_reviewed_at:
                raise KnowledgeVerificationError(
                    f"Cannot verify static reference '{knowledge_id}': review policy (review_cycle_days or last_reviewed_at) is mandatory."
                )

        # Gate 8: Translation check
        if item.translation_status == TranslationStatus.MACHINE_UNVERIFIED.value:
            raise KnowledgeVerificationError(
                f"Cannot verify item '{knowledge_id}': machine-translated unverified content cannot be marked as authoritative."
            )

        now_iso = datetime.now(timezone.utc).isoformat()
        updated_item = self.repository.update_verification_status(
            knowledge_id=knowledge_id,
            status=VerificationStatus.VERIFIED.value,
            verified_at=now_iso,
            verified_by=verified_by,
            updated_at=now_iso,
        )

        if not updated_item:
            raise KnowledgeVerificationError("Failed to update verification status.")

        # Reviewer Accountability: Log audit entry
        if is_test is None:
            is_test = bool("[test]" in verified_by.lower() or "test" in verified_by.lower())

        actor_role = "Test Reviewer" if is_test else "Agricultural Verification Officer"
        audit_notes = notes or f"Verification approved under 8 strict quality gates. Reviewer: {verified_by}"
        self.repository.create_verification_audit(
            audit_id=str(uuid.uuid4()),
            entity_type="knowledge_item",
            entity_id=knowledge_id,
            action="verified",
            actor=verified_by,
            actor_role=actor_role,
            is_test_audit=is_test,
            notes=audit_notes,
            created_at=now_iso,
        )

        return KnowledgeItemWithSourcesModel(item=updated_item, sources=approved_sources)

    def re_review_item(
        self,
        knowledge_id: str,
        reviewed_by: str,
        review_notes: Optional[str] = None,
        new_review_cycle_days: Optional[int] = None,
        is_test: Optional[bool] = None,
    ) -> KnowledgeItemWithSourcesModel:
        """
        Conduct a periodic re-review of an existing static reference or guidance item.
        Refreshes last_reviewed_at to now, updates reviewer identity, and reinstates verified status.
        Logs an immutable audit event in knowledge_verification_audit.
        """
        item = self.repository.get_item_by_id(knowledge_id)
        if not item:
            raise KnowledgeVerificationError(f"Knowledge item '{knowledge_id}' not found.")

        now_iso = datetime.now(timezone.utc).isoformat()
        updated_item = self.repository.re_review_item(
            knowledge_id=knowledge_id,
            reviewed_by=reviewed_by,
            review_notes=review_notes,
            new_review_cycle_days=new_review_cycle_days,
            updated_at=now_iso,
        )
        if not updated_item:
            raise KnowledgeVerificationError("Failed to record re-review in repository.")

        if is_test is None:
            is_test = bool("[test]" in reviewed_by.lower() or "test" in reviewed_by.lower())

        actor_role = "Test Reviewer" if is_test else "Agricultural Verification Officer"
        audit_notes = review_notes or f"Periodic static reference re-review completed by {reviewed_by}."
        self.repository.create_verification_audit(
            audit_id=str(uuid.uuid4()),
            entity_type="knowledge_item",
            entity_id=knowledge_id,
            action="re_reviewed",
            actor=reviewed_by,
            actor_role=actor_role,
            is_test_audit=is_test,
            notes=audit_notes,
            created_at=now_iso,
        )

        sources = self.repository.get_sources_for_item(knowledge_id)
        approved_sources = [s for s in sources if s.authority_status == AuthorityStatus.APPROVED.value]
        return KnowledgeItemWithSourcesModel(item=updated_item, sources=approved_sources)

    def reject_item(
        self, knowledge_id: str, reason: str = "", actor: str = "Agricultural Verification Officer", is_test: Optional[bool] = None
    ) -> Optional[KnowledgeItemModel]:
        """Mark an item as REJECTED with audit tracking."""
        now_iso = datetime.now(timezone.utc).isoformat()
        updated = self.repository.update_verification_status(
            knowledge_id=knowledge_id,
            status=VerificationStatus.REJECTED.value,
            verified_at=None,
            verified_by=None,
            updated_at=now_iso,
        )
        if is_test is None:
            is_test = bool("[test]" in actor.lower() or "test" in actor.lower())
        self.repository.create_verification_audit(
            audit_id=str(uuid.uuid4()),
            entity_type="knowledge_item",
            entity_id=knowledge_id,
            action="rejected",
            actor=actor,
            actor_role="Test Reviewer" if is_test else "Agricultural Verification Officer",
            is_test_audit=is_test,
            notes=reason or "Knowledge item rejected during verification review.",
            created_at=now_iso,
        )
        return updated

    def expire_item(
        self, knowledge_id: str, actor: str = "Agricultural System Daemon", is_test: Optional[bool] = None
    ) -> Optional[KnowledgeItemModel]:
        """Mark an item as EXPIRED with audit tracking."""
        now_iso = datetime.now(timezone.utc).isoformat()
        updated = self.repository.update_verification_status(
            knowledge_id=knowledge_id,
            status=VerificationStatus.EXPIRED.value,
            verified_at=None,
            verified_by=None,
            updated_at=now_iso,
        )
        if is_test is None:
            is_test = bool("[test]" in actor.lower() or "test" in actor.lower())
        self.repository.create_verification_audit(
            audit_id=str(uuid.uuid4()),
            entity_type="knowledge_item",
            entity_id=knowledge_id,
            action="expired",
            actor=actor,
            actor_role="Test Daemon" if is_test else "Agricultural System Daemon",
            is_test_audit=is_test,
            notes="Item validity expired or review cycle lapsed.",
            created_at=now_iso,
        )
        return updated

    def get_item_audit_trail(self, knowledge_id: str) -> List[Dict[str, Any]]:
        """Retrieve complete immutable verification and re-review history for an item."""
        return self.repository.get_verification_audit_trail(knowledge_id)

    # -------------------------------------------------------------------------
    # Search & Retrieval (Phase 5.1 Date-Aware & Season-Aware)
    # -------------------------------------------------------------------------
    def search_guidance(
        self, filters: KnowledgeSearchFilterSchema
    ) -> KnowledgeSearchResponseSchema:
        """
        Search verified agricultural knowledge with:
        - Date-awareness using Asia/Kolkata (IST) timezone.
        - Configurable regional agricultural calendar evaluation.
        - Strict exclusion of expired and unverified items.
        - Provenance explanation and citation metadata for each match.
        """
        # Resolve reference date using IST timezone
        if filters.as_of_date:
            try:
                as_of_dt = date.fromisoformat(filters.as_of_date)
                as_of_date_iso = as_of_dt.isoformat()
            except ValueError:
                as_of_dt = datetime.now(IST_ZONE).date()
                as_of_date_iso = as_of_dt.isoformat()
        else:
            as_of_dt = datetime.now(IST_ZONE).date()
            as_of_date_iso = as_of_dt.isoformat()

        # Regional season resolution
        calendar = AgriculturalCalendar(state=filters.state or "Telangana")
        horizon_res = calendar.resolve_planning_horizon(
            planning_horizon=filters.planning_horizon,
            query_season=filters.season,
            as_of_date=as_of_dt,
            district=filters.district,
        )

        if horizon_res.clarification_required:
            return KnowledgeSearchResponseSchema(
                total_matches=0,
                items=[],
                message=horizon_res.explanation,
                as_of_date=as_of_date_iso,
                active_season=None,
                season=None,
                season_year=None,
                season_start_date=None,
                season_end_date=None,
                planning_horizon=filters.planning_horizon,
                is_future_period=False,
                clarification_required=True,
                query_filters=filters.model_dump(exclude_none=True),
            )

        target_season = horizon_res.season
        target_year = horizon_res.season_year

        # Apply resolved season to search filters if user requested seasonal guidance
        effective_filters = filters.model_copy()
        if not effective_filters.season and effective_filters.knowledge_type != KnowledgeType.STATIC_REFERENCE.value:
            effective_filters.season = target_season
            if target_year and not effective_filters.season_year:
                effective_filters.season_year = target_year

        matched = self.repository.search_verified_items(
            filters=effective_filters, as_of_date_iso=as_of_date_iso
        )

        items_response: List[KnowledgeItemResponseSchema] = []
        for match in matched:
            sources_schemas = [
                SourceProvenanceSchema.model_validate(s) for s in match.sources
            ]

            # Build human-readable applicability explanation
            explanation = self._build_applicability_explanation(
                item=match.item,
                sources=match.sources,
                as_of_date=as_of_date_iso,
                effective_season=target_season,
            )

            region_dict = {
                "state": match.item.state,
                "district": match.item.district,
                "mandal": match.item.mandal,
                "village": match.item.village,
            }

            item_schema = KnowledgeItemResponseSchema(
                knowledge_id=match.item.knowledge_id,
                category=match.item.category,
                knowledge_type=match.item.knowledge_type,
                title=match.item.title,
                content=match.item.content,
                language_code=match.item.language_code,
                translation_status=match.item.translation_status,
                state=match.item.state,
                district=match.item.district,
                mandal=match.item.mandal,
                village=match.item.village,
                pin_code=match.item.pin_code,
                crop_name=match.item.crop_name,
                crop_variety=match.item.crop_variety,
                crop_stage=match.item.crop_stage,
                season=match.item.season,
                season_year=match.item.season_year,
                soil_type=match.item.soil_type,
                water_condition=match.item.water_condition,
                applicable_from=match.item.applicable_from,
                applicable_until=match.item.applicable_until,
                publication_date=match.item.publication_date,
                is_permanent_reference=match.item.is_permanent_reference,
                review_cycle_days=match.item.review_cycle_days,
                last_reviewed_at=match.item.last_reviewed_at,
                verification_status=match.item.verification_status,
                verified_at=match.item.verified_at,
                verified_by=match.item.verified_by,
                retrieval_applicability_explanation=explanation,
                applicable_region=region_dict,
                sources=sources_schemas,
            )
            items_response.append(item_schema)

        total = len(items_response)
        if total == 0:
            message = "No verified agricultural guidance found matching the specified criteria."
        else:
            message = f"Found {total} verified agricultural guidance record(s)."

        active_filters = {
            k: v for k, v in effective_filters.model_dump().items() if v is not None
        }

        return KnowledgeSearchResponseSchema(
            total_matches=total,
            items=items_response,
            message=message,
            as_of_date=as_of_date_iso,
            active_season=horizon_res.season,
            season=horizon_res.season,
            season_year=horizon_res.season_year,
            season_start_date=horizon_res.season_start_date,
            season_end_date=horizon_res.season_end_date,
            planning_horizon=horizon_res.planning_horizon,
            is_future_period=horizon_res.is_future_period,
            clarification_required=False,
            query_filters=active_filters,
        )

    def _build_applicability_explanation(
        self,
        item: KnowledgeItemModel,
        sources: List[Any],
        as_of_date: str,
        effective_season: Optional[str],
    ) -> str:
        """Construct detailed explanation for why a record was selected and verified."""
        src_names = ", ".join(set(s.publisher for s in sources))
        validity = (
            f"Valid until {item.applicable_until}"
            if item.applicable_until
            else "Permanent agronomic reference"
        )
        geo = item.district or item.state

        if item.knowledge_type == KnowledgeType.STATIC_REFERENCE.value:
            return (
                f"Permanent reference from {src_names} for {geo}. "
                f"Reviewed and verified under static reference policy."
            )
        elif item.knowledge_type == KnowledgeType.TIME_BOUND_ADVISORY.value:
            return (
                f"Active time-bound advisory from {src_names} for {geo}. "
                f"{validity} (Evaluated as of {as_of_date})."
            )
        else:
            season_str = f"{item.season or effective_season} {item.season_year or ''}".strip()
            return (
                f"Verified seasonal guidance from {src_names} for {season_str} in {geo}. "
                f"{validity} (Active as of {as_of_date})."
            )
