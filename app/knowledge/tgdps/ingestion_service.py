"""
TGDPS Daily Weather Report Ingestion Service.
Coordinates report discovery, safe retrieval, structured extraction,
and strict mapping into KrishiVaani's authoritative knowledge models.
Phase 6.4 - TGDPS Daily Weather Report Discovery & Ingestion.
"""

import logging
import re
import uuid
from datetime import datetime, timezone, timedelta
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
from app.knowledge.tgdps.adapter import (
    TGDPSSourceAdapter,
    TGDPSAdapterError,
)
from app.knowledge.tgdps.extractor import TGDPSReportExtractor
from app.knowledge.tgdps.schemas import (
    TGDPSReportLink,
    TGDPSReportDocument,
    TGDPSDistrictRainfallRecord,
    TGDPSStationRainfallRecord,
    TGDPSIngestionSummary,
    TGDPSExtractionQuality,
)

logger = logging.getLogger("krishivaani.tgdps.ingestion")
KOLKATA_TZ = ZoneInfo("Asia/Kolkata")


def _slugify(text: str) -> str:
    """Generate safe, clean alphanumeric slug for database IDs."""
    return re.sub(r"[^a-zA-Z0-9]+", "_", text).strip("_").lower()


class TGDPSReportIngestionService:
    """
    Service orchestrating the complete ingestion lifecycle for TGDPS Daily Weather Reports.
    Ensures all extracted rainfall summaries and AWS observations are stored
    as pending verification, preserving observation periods, units, and page citations.
    """

    def __init__(
        self,
        db_path: Optional[Path] = None,
        adapter: Optional[TGDPSSourceAdapter] = None,
        extractor: Optional[TGDPSReportExtractor] = None,
    ):
        self.db_path = db_path
        self.repository = KnowledgeRepository(db_path=db_path)
        self.adapter = adapter or TGDPSSourceAdapter(data_dir=settings.TGDPS_DATA_DIR)
        self.extractor = extractor or TGDPSReportExtractor()

    def ingest_reports(
        self,
        limit: Optional[int] = None,
        dry_run: bool = False,
        incremental: bool = True,
        portal_html: Optional[str] = None,
    ) -> TGDPSIngestionSummary:
        """
        Discover official TGDPS reports, download securely, extract structured records,
        and persist candidate knowledge items in the database with pending_verification status.
        """
        summary = TGDPSIngestionSummary(dry_run=dry_run)

        try:
            links = self.adapter.discover_reports(portal_html=portal_html)
        except TGDPSAdapterError as exc:
            logger.error(f"Discovery error: {exc}")
            summary.errors.append(f"Portal discovery failed: {str(exc)}")
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

                # 2. Download report PDF
                pdf_path, checksum, was_downloaded = self.adapter.download_report_pdf(link)
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

                # 4. Store in knowledge database (unless dry-run)
                if not dry_run:
                    stored_count = self._store_report_document(doc)
                    summary.items_stored_count += stored_count
                else:
                    total_records = len(doc.district_summaries) + len(doc.station_observations)
                    logger.info(
                        f"[DRY-RUN] Extracted TGDPS report {doc.report_title}: "
                        f"{len(doc.district_summaries)} district summaries, "
                        f"{len(doc.station_observations)} station observations."
                    )
                    summary.items_stored_count += total_records

            except Exception as exc:
                err_msg = f"Failed processing report '{link.displayed_label}': {str(exc)}"
                logger.error(err_msg, exc_info=True)
                summary.failed_count += 1
                summary.errors.append(err_msg)

        return summary

    def ingest_local_file(
        self,
        pdf_path: Path,
        report_date: Optional[str] = None,
        dry_run: bool = False,
    ) -> Tuple[TGDPSReportDocument, int]:
        """
        Manually import a locally available TGDPS report PDF without network access.
        Returns the parsed document and number of items stored.
        """
        file_path, checksum = self.adapter.import_local_pdf(
            pdf_path,
            report_date=report_date,
        )

        doc = self.extractor.extract_from_file(file_path, checksum=checksum)
        if report_date:
            doc.report_date = report_date

        stored_count = 0
        if not dry_run:
            stored_count = self._store_report_document(doc)
        else:
            stored_count = len(doc.district_summaries) + len(doc.station_observations)

        return doc, stored_count

    # -------------------------------------------------------------------------
    # Database Persistence & Strict Provenance
    # -------------------------------------------------------------------------
    def _store_report_document(self, doc: TGDPSReportDocument) -> int:
        """
        Create KnowledgeSourceModel and linked KnowledgeItemModels for each
        district summary and station observation.
        All records are strictly marked pending_verification.
        """
        now_iso = datetime.now(timezone.utc).isoformat()
        source_id = f"src_tgdps_{doc.document_checksum[:16]}"

        # 1. Register or retrieve knowledge source
        existing_source = self.repository.get_source_by_id(source_id)
        if not existing_source:
            source_model = KnowledgeSourceModel(
                source_id=source_id,
                publisher=doc.publisher,
                document_title=doc.report_title,
                source_url=doc.source_url,
                source_type="official_weather_report",
                authority_status=AuthorityStatus.PENDING_VERIFICATION.value,
                created_at=now_iso,
                updated_at=now_iso,
                published_at=doc.report_date,
                last_checked_at=now_iso,
                reviewed_by=None,
                review_notes=(
                    f"Auto-ingested official TGDPS Daily Weather Report. "
                    f"Extraction quality: {doc.extraction_quality.value}. "
                    f"Observation period: {doc.observation_period}."
                ),
            )
            self.repository.create_source(source_model)
            self.repository.create_verification_audit(
                audit_id=f"aud_src_{uuid.uuid4().hex[:12]}",
                entity_type="knowledge_source",
                entity_id=source_id,
                action="auto_ingested_pending_review",
                actor="system:tgdps_ingestion",
                actor_role="automated_ingestion_service",
                is_test_audit=False,
                notes=f"Ingested TGDPS report for date {doc.report_date}.",
                created_at=now_iso,
            )

        # Validity dates derivation: observation day to next morning / validity window (YYYY-MM-DD)
        try:
            pub_date = datetime.strptime(doc.report_date, "%Y-%m-%d")
            valid_from = doc.report_date
            valid_until = (pub_date + timedelta(days=1)).strftime("%Y-%m-%d")
        except ValueError:
            valid_from = doc.report_date
            valid_until = doc.report_date

        stored_count = 0

        # 2. Store District Rainfall Summaries (Page 2)
        for dist in doc.district_summaries:
            slug = _slugify(dist.district)
            knowledge_id = f"ki_tgdps_{doc.document_checksum[:8]}_dist_{slug}"

            existing_item = self.repository.get_item_by_id(knowledge_id)
            if existing_item:
                continue

            actual_display = f"{dist.actual_rainfall_mm:.1f} mm" if dist.actual_rainfall_mm is not None else "Missing/Unavailable"
            normal_display = f"{dist.normal_rainfall_mm:.1f} mm" if dist.normal_rainfall_mm is not None else "N/A"
            dev_display = f"{dist.deviation_percent:+.0f}%" if dist.deviation_percent is not None else "N/A"

            content_text = (
                f"Official TGDPS District Rainfall Summary:\n"
                f"- District: {dist.district}\n"
                f"- Observation Date: {dist.observation_date}\n"
                f"- Observation Period: {dist.observation_period or doc.observation_period}\n"
                f"- Today's Actual Rainfall: {actual_display}\n"
                f"- Today's Normal Rainfall: {normal_display}\n"
                f"- Today's Deviation: {dev_display}\n"
                f"- Cumulative Actual (from 01-Jun): {dist.cumulative_actual_mm if dist.cumulative_actual_mm is not None else 'N/A'} mm\n"
                f"- Cumulative Normal: {dist.cumulative_normal_mm if dist.cumulative_normal_mm is not None else 'N/A'} mm\n"
                f"- Cumulative Deviation: {dist.cumulative_deviation_percent if dist.cumulative_deviation_percent is not None else 'N/A'}%\n"
                f"- Cumulative Status: {dist.status or 'N/A'}\n"
                f"- Rainy Days: {dist.rainy_days if dist.rainy_days is not None else 'N/A'}\n"
                f"Important: This is an aggregated district-level meteorological summary from TGDPS; "
                f"it does not represent an individual village or farm-gate rainfall measurement."
            )

            item_model = KnowledgeItemModel(
                knowledge_id=knowledge_id,
                category=KnowledgeCategory.AGRICULTURAL_ADVISORY.value,
                knowledge_type=KnowledgeType.TIME_BOUND_ADVISORY.value,
                title=f"TGDPS District Rainfall: {dist.district} ({dist.observation_date})",
                content=content_text,
                language_code="en-IN",
                translation_status=TranslationStatus.ORIGINAL.value,
                state="Telangana",
                district=dist.district,
                mandal=None,  # District aggregate - NEVER assign mandal
                village=None, # NEVER assign village
                pin_code=None,
                crop_name=None,
                crop_stage=None,
                season=None,
                season_year=None,
                soil_type=None,
                water_condition=None,
                applicable_from=valid_from,
                applicable_until=valid_until,
                publication_date=doc.report_date,
                is_permanent_reference=False,
                review_cycle_days=None,
                last_reviewed_at=None,
                verification_status=VerificationStatus.PENDING_VERIFICATION.value,  # PENDING REVIEW
                verified_at=None,
                verified_by=None,
                retrieval_applicability_notes=(
                    f"Official district-level rainfall summary from TGDPS Daily Weather Report (Page {dist.page_number})."
                ),
                created_at=now_iso,
                updated_at=now_iso,
            )
            self.repository.create_item(item_model)
            self.repository.link_item_source(
                item_id=knowledge_id,
                source_id=source_id,
                reference_location=f"Page {dist.page_number}",
                created_at=now_iso,
            )
            self.repository.create_verification_audit(
                audit_id=f"aud_ki_{uuid.uuid4().hex[:12]}",
                entity_type="knowledge_item",
                entity_id=knowledge_id,
                action="auto_ingested_pending_review",
                actor="system:tgdps_ingestion",
                actor_role="automated_ingestion_service",
                is_test_audit=False,
                notes=f"Ingested district rainfall summary for {dist.district}.",
                created_at=now_iso,
            )
            stored_count += 1

        # 3. Store Station / Mandal Observations (Page 3 & Page 1)
        for idx, obs in enumerate(doc.station_observations):
            slug = _slugify(f"{obs.district}_{obs.station_or_mandal}_{idx}")
            knowledge_id = f"ki_tgdps_{doc.document_checksum[:8]}_mandal_{slug}"

            existing_item = self.repository.get_item_by_id(knowledge_id)
            if existing_item:
                continue

            rain_display = f"{obs.rainfall_mm:.1f} {obs.rainfall_unit}" if obs.rainfall_mm is not None else "Missing/Unavailable"

            obs_content = (
                f"Official TGDPS Automatic Weather Station (AWS) Observation:\n"
                f"- Reporting Location/Mandal: {obs.station_or_mandal}\n"
                f"- District: {obs.district}\n"
                f"- Recorded Rainfall: {rain_display}\n"
                f"- Observation Date: {obs.observation_date}\n"
                f"- Observation Period: {obs.observation_period or doc.observation_period}\n"
                f"Important: This reading represents an official Automatic Weather Station (AWS) "
                f"ground measurement at the mandal level. It must not be treated as a direct farm-gate "
                f"or village-specific observation."
            )

            item_model = KnowledgeItemModel(
                knowledge_id=knowledge_id,
                category=KnowledgeCategory.AGRICULTURAL_ADVISORY.value,
                knowledge_type=KnowledgeType.TIME_BOUND_ADVISORY.value,
                title=f"TGDPS AWS Observation: {obs.station_or_mandal}, {obs.district} ({obs.observation_date})",
                content=obs_content,
                language_code="en-IN",
                translation_status=TranslationStatus.ORIGINAL.value,
                state="Telangana",
                district=obs.district,
                mandal=obs.station_or_mandal,  # Mandal AWS location
                village=None,                 # NEVER infer village
                pin_code=None,
                crop_name=None,
                crop_stage=None,
                season=None,
                season_year=None,
                soil_type=None,
                water_condition=None,
                applicable_from=valid_from,
                applicable_until=valid_until,
                publication_date=doc.report_date,
                is_permanent_reference=False,
                review_cycle_days=None,
                last_reviewed_at=None,
                verification_status=VerificationStatus.PENDING_VERIFICATION.value,  # PENDING REVIEW
                verified_at=None,
                verified_by=None,
                retrieval_applicability_notes=(
                    f"Official AWS station observation from TGDPS Daily Weather Report (Page {obs.page_number})."
                ),
                created_at=now_iso,
                updated_at=now_iso,
            )
            self.repository.create_item(item_model)
            self.repository.link_item_source(
                item_id=knowledge_id,
                source_id=source_id,
                reference_location=f"Page {obs.page_number}",
                created_at=now_iso,
            )
            self.repository.create_verification_audit(
                audit_id=f"aud_ki_{uuid.uuid4().hex[:12]}",
                entity_type="knowledge_item",
                entity_id=knowledge_id,
                action="auto_ingested_pending_review",
                actor="system:tgdps_ingestion",
                actor_role="automated_ingestion_service",
                is_test_audit=False,
                notes=f"Ingested AWS observation for {obs.station_or_mandal}, {obs.district}.",
                created_at=now_iso,
            )
            stored_count += 1

        logger.info(f"Successfully stored {stored_count} items from TGDPS report {doc.report_title}.")
        return stored_count

    # -------------------------------------------------------------------------
    # Incremental Deduplication Helpers
    # -------------------------------------------------------------------------
    def _source_already_exists_by_url(self, source_url: str) -> bool:
        """Check if a source record with matching source_url already exists."""
        from app.db.database import get_connection
        conn = get_connection(self.db_path)
        try:
            cursor = conn.execute(
                "SELECT 1 FROM knowledge_sources WHERE source_url = ?",
                (source_url,),
            )
            return cursor.fetchone() is not None
        finally:
            conn.close()

    def _source_already_exists_by_checksum(self, checksum: str) -> bool:
        """Check if a source document with matching checksum prefix already exists."""
        source_id = f"src_tgdps_{checksum[:16]}"
        return self.repository.get_source_by_id(source_id) is not None
