"""
PJTAU Agromet Advisory Ingestion Service.
Coordinates bulletin discovery, safe downloading, text extraction,
and strict mapping into KrishiVaani's authoritative knowledge models.
Phase 6.3 - Automatic PJTAU Bulletin Ingestion.
"""

import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple
from zoneinfo import ZoneInfo

from app.core.config import settings
from app.knowledge.models import (
    KnowledgeSourceModel,
    KnowledgeItemModel,
    AuthorityStatus,
    VerificationStatus,
    TranslationStatus,
    KnowledgeCategory,
    KnowledgeType,
)
from app.knowledge.repository import KnowledgeRepository
from app.knowledge.pjtau.adapter import (
    PJTAUSourceAdapter,
    PJTAUAdapterError,
)
from app.knowledge.pjtau.extractor import PJTAUBulletinExtractor
from app.knowledge.pjtau.schemas import (
    PJTAUBulletinLink,
    PJTAUBulletinDocument,
    PJTAUIngestionSummary,
    ExtractionQuality,
)

logger = logging.getLogger("krishivaani.pjtau.ingestion")
KOLKATA_TZ = ZoneInfo("Asia/Kolkata")


class PJTAUIngestionService:
    """
    Service orchestrating the complete ingestion lifecycle for PJTAU agromet bulletins.
    Ensures all extracted advisories are stored as pending review and linked to traceable sources.
    """

    def __init__(
        self,
        db_path: Optional[Path] = None,
        adapter: Optional[PJTAUSourceAdapter] = None,
        extractor: Optional[PJTAUBulletinExtractor] = None,
    ):
        self.db_path = db_path
        self.repository = KnowledgeRepository(db_path=db_path)
        self.adapter = adapter or PJTAUSourceAdapter(data_dir=settings.PJTAU_DATA_DIR)
        self.extractor = extractor or PJTAUBulletinExtractor()

    def ingest_archive(
        self,
        limit: Optional[int] = None,
        dry_run: bool = False,
        incremental: bool = True,
        archive_html: Optional[str] = None,
    ) -> PJTAUIngestionSummary:
        """
        Scan the PJTAU archive, retrieve published bulletins, extract structured data,
        and store candidate knowledge items in the database with pending verification status.
        """
        summary = PJTAUIngestionSummary(dry_run=dry_run)

        try:
            links = self.adapter.discover_bulletins(archive_html=archive_html)
        except PJTAUAdapterError as exc:
            logger.error(f"Discovery error: {exc}")
            summary.errors.append(f"Archive discovery failed: {str(exc)}")
            return summary

        summary.discovered_count = len(links)

        if limit is not None and limit > 0:
            links = links[:limit]
            logger.info(f"Ingestion limit applied: processing first {len(links)} discovered links.")

        for link in links:
            try:
                # 1. Incremental check by source URL if enabled
                if incremental and not dry_run:
                    if self._source_already_exists_by_url(link.original_url):
                        logger.info(f"Source URL already ingested: {link.original_url}. Skipping.")
                        summary.unchanged_count += 1
                        continue

                # 2. Download bulletin PDF
                pdf_path, checksum, was_downloaded = self.adapter.download_bulletin_pdf(link)
                if was_downloaded:
                    summary.downloaded_count += 1
                else:
                    summary.unchanged_count += 1

                # Incremental check by checksum
                if incremental and not dry_run and not was_downloaded:
                    if self._source_already_exists_by_checksum(checksum):
                        logger.info(f"Checksum {checksum[:12]} already present in database. Skipping.")
                        continue

                # 3. Extract structured document
                doc = self.extractor.extract_from_file(pdf_path, link_info=link, checksum=checksum)
                summary.extracted_count += 1

                # 4. Store in knowledge database (unless dry run)
                if not dry_run:
                    stored_count = self._store_bulletin_document(doc)
                    summary.items_stored_count += stored_count
                else:
                    logger.info(
                        f"[DRY-RUN] Extracted bulletin {doc.pdf_bulletin_number or doc.archive_bulletin_number}: "
                        f"{len(doc.warnings)} warnings, {len(doc.advisories)} advisories."
                    )
                    summary.items_stored_count += len(doc.advisories)

            except Exception as exc:
                err_msg = f"Failed processing bulletin '{link.displayed_label}': {str(exc)}"
                logger.error(err_msg, exc_info=True)
                summary.failed_count += 1
                summary.errors.append(err_msg)

        return summary

    def ingest_local_file(
        self,
        pdf_path: Path,
        archive_bulletin_number: Optional[str] = None,
        archive_publication_date: Optional[str] = None,
        dry_run: bool = False,
    ) -> Tuple[PJTAUBulletinDocument, int]:
        """
        Manually import a locally available bulletin PDF without network access.
        Returns the parsed document and number of items stored.
        """
        file_path, checksum = self.adapter.import_local_pdf(
            pdf_path,
            archive_bulletin_number=archive_bulletin_number,
            archive_publication_date=archive_publication_date,
        )

        doc = self.extractor.extract_from_file(file_path, checksum=checksum)
        if archive_bulletin_number:
            doc.archive_bulletin_number = archive_bulletin_number
        if archive_publication_date:
            doc.archive_publication_date = archive_publication_date

        stored_count = 0
        if not dry_run:
            stored_count = self._store_bulletin_document(doc)
        else:
            stored_count = len(doc.advisories)

        return doc, stored_count

    # -------------------------------------------------------------------------
    # Database Storage & Lifecycle Integration
    # -------------------------------------------------------------------------
    def _store_bulletin_document(self, doc: PJTAUBulletinDocument) -> int:
        """
        Create KnowledgeSourceModel and linked KnowledgeItemModels for each advisory.
        Strictly enforces pending verification and non-permanent reference classification.
        """
        now_iso = datetime.now(timezone.utc).isoformat()
        source_id = f"src_pjtau_{doc.document_checksum[:16]}"

        # 1. Register or update the knowledge source
        existing_source = self.repository.get_source_by_id(source_id)
        if not existing_source:
            source_model = KnowledgeSourceModel(
                source_id=source_id,
                publisher=doc.publisher,
                document_title=(
                    f"PJTAU GKMS Agromet Advisory Bulletin No. "
                    f"{doc.pdf_bulletin_number or doc.archive_bulletin_number} "
                    f"({doc.archive_publication_date})"
                ),
                source_url=doc.original_url or f"urn:pjtau:bulletin:{doc.document_checksum[:16]}",
                source_type="official_bulletin",
                authority_status=AuthorityStatus.PENDING_VERIFICATION.value,
                created_at=now_iso,
                updated_at=now_iso,
                published_at=doc.pdf_issue_date or doc.archive_publication_date,
                last_checked_at=now_iso,
                reviewed_by=None,
                review_notes=(
                    f"Auto-ingested PJTAU bulletin. "
                    f"Extraction quality: Telugu={doc.telugu_extraction_quality.value}, "
                    f"English={doc.english_extraction_quality.value}. "
                    f"Meteorological attribution: {doc.meteorological_source}."
                ),
            )
            self.repository.create_source(source_model)
            self.repository.create_verification_audit(
                audit_id=f"aud_src_{uuid.uuid4().hex[:12]}",
                entity_type="knowledge_source",
                entity_id=source_id,
                action="auto_ingested_pending_review",
                actor="system:pjtau_ingestion",
                actor_role="automated_ingestion_service",
                is_test_audit=False,
                notes=f"Discovered and ingested bulletin {doc.pdf_bulletin_number or doc.archive_bulletin_number}.",
                created_at=now_iso,
            )

        # 2. Store each agricultural advisory recommendation as a candidate item
        items_stored = 0
        for idx, adv in enumerate(doc.advisories):
            knowledge_id = f"ki_pjtau_{doc.document_checksum[:8]}_{idx + 1}"

            # Check if item already exists
            existing_item = self.repository.get_item_by_id(knowledge_id)
            if existing_item:
                continue

            item_model = KnowledgeItemModel(
                knowledge_id=knowledge_id,
                category=KnowledgeCategory.AGRICULTURAL_ADVISORY.value,
                knowledge_type=KnowledgeType.TIME_BOUND_ADVISORY.value,
                title=f"Advisory: {adv.crop_or_group or 'Standing Crops'} ({adv.weather_condition_trigger or 'Weather Precaution'})",
                content=adv.recommended_action,
                language_code="en-IN",
                translation_status=TranslationStatus.ORIGINAL.value,
                state="Telangana",
                district=None,  # State-wide / multi-district bulletin
                mandal=None,
                village=None,
                pin_code=None,
                crop_name=adv.crop_or_group,
                crop_stage=adv.crop_stage,
                season=None,
                season_year=None,
                soil_type=None,
                water_condition=None,
                applicable_from=adv.valid_from,
                applicable_until=adv.valid_until,
                publication_date=doc.pdf_issue_date or doc.archive_publication_date,
                is_permanent_reference=False,   # Must NEVER be permanent reference!
                review_cycle_days=None,
                last_reviewed_at=None,
                verification_status=VerificationStatus.PENDING_VERIFICATION.value,  # PENDING REVIEW!
                verified_at=None,
                verified_by=None,
                retrieval_applicability_notes=(
                    f"Trigger: {adv.weather_condition_trigger or 'General forecast'}; "
                    f"Geographic scope: {adv.geographic_applicability}; "
                    f"Safety instruction: {adv.is_safety_instruction}."
                ),
                created_at=now_iso,
                updated_at=now_iso,
            )

            self.repository.create_item(item_model)

            # Link item to source
            self.repository.link_item_source(
                item_id=knowledge_id,
                source_id=source_id,
                reference_location=f"Page {adv.page_number}, Weather based Agro Advisories, Item {idx + 1}",
                created_at=now_iso,
            )

            # Audit trail
            self.repository.create_verification_audit(
                audit_id=f"aud_ki_{uuid.uuid4().hex[:12]}",
                entity_type="knowledge_item",
                entity_id=knowledge_id,
                action="auto_ingested_pending_review",
                actor="system:pjtau_ingestion",
                actor_role="automated_ingestion_service",
                is_test_audit=False,
                notes=f"Candidate advisory extracted from PJTAU bulletin Page {adv.page_number}.",
                created_at=now_iso,
            )

            items_stored += 1

        return items_stored

    def _source_already_exists_by_url(self, source_url: str) -> bool:
        """Check if a source with this URL already exists in knowledge_sources."""
        conn = self.repository._get_connection() if hasattr(self.repository, "_get_connection") else None
        from app.db.database import get_connection
        conn = get_connection(self.db_path)
        try:
            cursor = conn.execute("SELECT 1 FROM knowledge_sources WHERE source_url = ?", (source_url,))
            return cursor.fetchone() is not None
        finally:
            conn.close()

    def _source_already_exists_by_checksum(self, checksum: str) -> bool:
        """Check if a source matching this checksum ID exists."""
        source_id = f"src_pjtau_{checksum[:16]}"
        return self.repository.get_source_by_id(source_id) is not None
