"""
Repository for Knowledge Base SQLite storage operations.
Handles transactional source, item, and provenance citation mappings.
Enhanced in Phase 5.1 with explicit knowledge types, review policy fields,
strict expiration constraints, and date-aware filtering.
"""

import sqlite3
from pathlib import Path
from typing import Optional, List, Dict, Any
from app.db.database import get_connection
from app.knowledge.models import (
    KnowledgeSourceModel,
    KnowledgeItemModel,
    SourceProvenanceModel,
    KnowledgeItemWithSourcesModel,
)
from app.knowledge.schemas import KnowledgeSearchFilterSchema


class KnowledgeRepository:
    """
    Data access layer for agricultural knowledge and source provenance.
    """

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path

    # -------------------------------------------------------------------------
    # Sources Operations
    # -------------------------------------------------------------------------
    def create_source(self, source: KnowledgeSourceModel) -> KnowledgeSourceModel:
        """Insert a new publication source record."""
        conn = get_connection(self.db_path)
        try:
            with conn:
                conn.execute(
                    """
                    INSERT INTO knowledge_sources (
                        source_id, publisher, document_title, source_url,
                        source_type, authority_status, reviewed_by, review_notes,
                        published_at, last_checked_at, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        source.source_id,
                        source.publisher,
                        source.document_title,
                        source.source_url,
                        source.source_type,
                        source.authority_status,
                        source.reviewed_by,
                        source.review_notes,
                        source.published_at,
                        source.last_checked_at,
                        source.created_at,
                        source.updated_at,
                    ),
                )
            return source
        finally:
            conn.close()

    def get_source_by_id(self, source_id: str) -> Optional[KnowledgeSourceModel]:
        """Retrieve source document by ID."""
        conn = get_connection(self.db_path)
        try:
            cursor = conn.execute(
                "SELECT * FROM knowledge_sources WHERE source_id = ?",
                (source_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return KnowledgeSourceModel(
                source_id=row["source_id"],
                publisher=row["publisher"],
                document_title=row["document_title"],
                source_url=row["source_url"],
                source_type=row["source_type"],
                authority_status=row["authority_status"],
                published_at=row["published_at"],
                last_checked_at=row["last_checked_at"],
                reviewed_by=row["reviewed_by"] if "reviewed_by" in row.keys() else None,
                review_notes=row["review_notes"] if "review_notes" in row.keys() else None,
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
        finally:
            conn.close()

    def update_source_status(
        self,
        source_id: str,
        status: str,
        updated_at: str,
        reviewed_by: Optional[str] = None,
        review_notes: Optional[str] = None,
    ) -> Optional[KnowledgeSourceModel]:
        """Update authority status of a publication source with reviewer accountability."""
        conn = get_connection(self.db_path)
        try:
            with conn:
                conn.execute(
                    """
                    UPDATE knowledge_sources
                    SET authority_status = ?, reviewed_by = ?, review_notes = ?, updated_at = ?
                    WHERE source_id = ?
                    """,
                    (status, reviewed_by, review_notes, updated_at, source_id),
                )
            return self.get_source_by_id(source_id)
        finally:
            conn.close()

    # -------------------------------------------------------------------------
    # Knowledge Items Operations
    # -------------------------------------------------------------------------
    def create_item(self, item: KnowledgeItemModel) -> KnowledgeItemModel:
        """Insert a new knowledge item record."""
        conn = get_connection(self.db_path)
        try:
            with conn:
                conn.execute(
                    """
                    INSERT INTO knowledge_items (
                        knowledge_id, category, knowledge_type, title, content,
                        language_code, translation_status, state,
                        district, mandal, village, pin_code,
                        crop_name, crop_variety, crop_stage, season, season_year,
                        soil_type, water_condition, applicable_from,
                        applicable_until, publication_date, is_permanent_reference,
                        review_cycle_days, last_reviewed_at,
                        verification_status, verified_at, verified_by,
                        retrieval_applicability_notes,
                        created_at, updated_at
                    ) VALUES (
                        ?, ?, ?, ?, ?,
                        ?, ?, ?,
                        ?, ?, ?, ?,
                        ?, ?, ?, ?, ?,
                        ?, ?, ?,
                        ?, ?, ?,
                        ?, ?,
                        ?, ?, ?,
                        ?,
                        ?, ?
                    )
                    """,
                    (
                        item.knowledge_id,
                        item.category,
                        item.knowledge_type,
                        item.title,
                        item.content,
                        item.language_code,
                        item.translation_status,
                        item.state,
                        item.district,
                        item.mandal,
                        item.village,
                        item.pin_code,
                        item.crop_name,
                        item.crop_variety,
                        item.crop_stage,
                        item.season,
                        item.season_year,
                        item.soil_type,
                        item.water_condition,
                        item.applicable_from,
                        item.applicable_until,
                        item.publication_date,
                        1 if item.is_permanent_reference else 0,
                        item.review_cycle_days,
                        item.last_reviewed_at,
                        item.verification_status,
                        item.verified_at,
                        item.verified_by,
                        item.retrieval_applicability_notes,
                        item.created_at,
                        item.updated_at,
                    ),
                )
            return item
        finally:
            conn.close()

    def get_item_by_id(self, knowledge_id: str) -> Optional[KnowledgeItemModel]:
        """Retrieve knowledge item by ID."""
        conn = get_connection(self.db_path)
        try:
            cursor = conn.execute(
                "SELECT * FROM knowledge_items WHERE knowledge_id = ?",
                (knowledge_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return self._row_to_item(row)
        finally:
            conn.close()

    def update_item(self, item: KnowledgeItemModel) -> KnowledgeItemModel:
        """Update an existing knowledge item."""
        conn = get_connection(self.db_path)
        try:
            with conn:
                conn.execute(
                    """
                    UPDATE knowledge_items
                    SET category = ?, knowledge_type = ?, title = ?, content = ?,
                        language_code = ?, translation_status = ?,
                        state = ?, district = ?, mandal = ?, village = ?,
                        pin_code = ?, crop_name = ?, crop_variety = ?,
                        crop_stage = ?, season = ?, season_year = ?,
                        soil_type = ?, water_condition = ?,
                        applicable_from = ?, applicable_until = ?,
                        publication_date = ?, is_permanent_reference = ?,
                        review_cycle_days = ?, last_reviewed_at = ?,
                        verification_status = ?, verified_at = ?, verified_by = ?,
                        retrieval_applicability_notes = ?,
                        updated_at = ?
                    WHERE knowledge_id = ?
                    """,
                    (
                        item.category,
                        item.knowledge_type,
                        item.title,
                        item.content,
                        item.language_code,
                        item.translation_status,
                        item.state,
                        item.district,
                        item.mandal,
                        item.village,
                        item.pin_code,
                        item.crop_name,
                        item.crop_variety,
                        item.crop_stage,
                        item.season,
                        item.season_year,
                        item.soil_type,
                        item.water_condition,
                        item.applicable_from,
                        item.applicable_until,
                        item.publication_date,
                        1 if item.is_permanent_reference else 0,
                        item.review_cycle_days,
                        item.last_reviewed_at,
                        item.verification_status,
                        item.verified_at,
                        item.verified_by,
                        item.retrieval_applicability_notes,
                        item.updated_at,
                        item.knowledge_id,
                    ),
                )
            return item
        finally:
            conn.close()

    def update_verification_status(
        self,
        knowledge_id: str,
        status: str,
        verified_at: Optional[str],
        verified_by: Optional[str],
        updated_at: str,
    ) -> Optional[KnowledgeItemModel]:
        """Transition verification status of an item with reviewer accountability."""
        conn = get_connection(self.db_path)
        try:
            with conn:
                conn.execute(
                    """
                    UPDATE knowledge_items
                    SET verification_status = ?, verified_at = ?, verified_by = ?, updated_at = ?
                    WHERE knowledge_id = ?
                    """,
                    (status, verified_at, verified_by, updated_at, knowledge_id),
                )
            return self.get_item_by_id(knowledge_id)
        finally:
            conn.close()

    def re_review_item(
        self,
        knowledge_id: str,
        reviewed_by: str,
        review_notes: Optional[str] = None,
        new_review_cycle_days: Optional[int] = None,
        updated_at: Optional[str] = None,
    ) -> Optional[KnowledgeItemModel]:
        """
        Record a successful re-review of an existing knowledge item,
        refreshing last_reviewed_at and setting verification_status to verified.
        """
        conn = get_connection(self.db_path)
        try:
            with conn:
                if new_review_cycle_days is not None:
                    conn.execute(
                        """
                        UPDATE knowledge_items
                        SET verification_status = 'verified',
                            last_reviewed_at = ?,
                            review_cycle_days = ?,
                            verified_by = ?,
                            verified_at = ?,
                            retrieval_applicability_notes = COALESCE(?, retrieval_applicability_notes),
                            updated_at = ?
                        WHERE knowledge_id = ?
                        """,
                        (
                            updated_at,
                            new_review_cycle_days,
                            reviewed_by,
                            updated_at,
                            review_notes,
                            updated_at,
                            knowledge_id,
                        ),
                    )
                else:
                    conn.execute(
                        """
                        UPDATE knowledge_items
                        SET verification_status = 'verified',
                            last_reviewed_at = ?,
                            verified_by = ?,
                            verified_at = ?,
                            retrieval_applicability_notes = COALESCE(?, retrieval_applicability_notes),
                            updated_at = ?
                        WHERE knowledge_id = ?
                        """,
                        (
                            updated_at,
                            reviewed_by,
                            updated_at,
                            review_notes,
                            updated_at,
                            knowledge_id,
                        ),
                    )
            return self.get_item_by_id(knowledge_id)
        finally:
            conn.close()

    # -------------------------------------------------------------------------
    # Verification Audit Trail Operations (Phase 5.2)
    # -------------------------------------------------------------------------
    def create_verification_audit(
        self,
        audit_id: str,
        entity_type: str,
        entity_id: str,
        action: str,
        actor: str,
        actor_role: str,
        is_test_audit: bool,
        notes: Optional[str],
        created_at: str,
    ) -> Dict[str, Any]:
        """Record an immutable verification, review, or rejection event in the audit log."""
        conn = get_connection(self.db_path)
        try:
            with conn:
                conn.execute(
                    """
                    INSERT INTO knowledge_verification_audit (
                        audit_id, entity_type, entity_id, action,
                        actor, actor_role, is_test_audit, notes, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        audit_id,
                        entity_type,
                        entity_id,
                        action,
                        actor,
                        actor_role,
                        1 if is_test_audit else 0,
                        notes,
                        created_at,
                    ),
                )
            return {
                "audit_id": audit_id,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "action": action,
                "actor": actor,
                "actor_role": actor_role,
                "is_test_audit": bool(is_test_audit),
                "notes": notes,
                "created_at": created_at,
            }
        finally:
            conn.close()

    def get_verification_audit_trail(self, entity_id: str) -> List[Dict[str, Any]]:
        """Retrieve complete chronological audit history for a knowledge item or source."""
        conn = get_connection(self.db_path)
        try:
            cursor = conn.execute(
                """
                SELECT audit_id, entity_type, entity_id, action,
                       actor, actor_role, is_test_audit, notes, created_at
                FROM knowledge_verification_audit
                WHERE entity_id = ?
                ORDER BY created_at ASC
                """,
                (entity_id,),
            )
            rows = cursor.fetchall()
            return [
                {
                    "audit_id": r["audit_id"],
                    "entity_type": r["entity_type"],
                    "entity_id": r["entity_id"],
                    "action": r["action"],
                    "actor": r["actor"],
                    "actor_role": r["actor_role"],
                    "is_test_audit": bool(r["is_test_audit"]),
                    "notes": r["notes"],
                    "created_at": r["created_at"],
                }
                for r in rows
            ]
        finally:
            conn.close()

    # -------------------------------------------------------------------------
    # Provenance Link Operations
    # -------------------------------------------------------------------------
    def link_item_source(
        self, item_id: str, source_id: str, reference_location: Optional[str], created_at: str
    ) -> bool:
        """Link a knowledge item to an authoritative publication source."""
        conn = get_connection(self.db_path)
        try:
            with conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO knowledge_item_sources (
                        item_id, source_id, reference_location, created_at
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (item_id, source_id, reference_location, created_at),
                )
            return True
        finally:
            conn.close()

    def get_sources_for_item(self, item_id: str) -> List[SourceProvenanceModel]:
        """Retrieve all source citations supporting a knowledge item."""
        conn = get_connection(self.db_path)
        try:
            cursor = conn.execute(
                """
                SELECT s.source_id, s.publisher, s.document_title,
                       s.source_url, s.source_type, s.authority_status,
                       s.published_at, s.reviewed_by, kis.reference_location
                FROM knowledge_item_sources kis
                JOIN knowledge_sources s ON kis.source_id = s.source_id
                WHERE kis.item_id = ?
                ORDER BY s.created_at ASC
                """,
                (item_id,),
            )
            rows = cursor.fetchall()
            return [
                SourceProvenanceModel(
                    source_id=r["source_id"],
                    publisher=r["publisher"],
                    document_title=r["document_title"],
                    source_url=r["source_url"],
                    source_type=r["source_type"],
                    authority_status=r["authority_status"],
                    published_at=r["published_at"],
                    reference_location=r["reference_location"],
                    reviewed_by=r["reviewed_by"] if "reviewed_by" in r.keys() else None,
                )
                for r in rows
            ]
        finally:
            conn.close()

    # -------------------------------------------------------------------------
    # Search & Retrieval (Phase 5.2 Strict Validity & Review Expiry Rules)
    # -------------------------------------------------------------------------
    def search_verified_items(
        self, filters: KnowledgeSearchFilterSchema, as_of_date_iso: str
    ) -> List[KnowledgeItemWithSourcesModel]:
        """
        Retrieve verified, currently applicable agricultural guidance records.

        Phase 5.2 Corrections:
        1. Static Reference Review Expiry:
           Permanent static references are ONLY eligible if last_reviewed_at IS NOT NULL
           AND date(substr(last_reviewed_at, 1, 10), '+' || review_cycle_days || ' days') >= as_of_date_iso.
           If review cycle has elapsed or review date is missing, item is excluded until re-reviewed.
        2. Time-Bound Advisory & Seasonal Guidance Validity:
           Must have applicable_until >= as_of_date_iso AND (applicable_from IS NULL OR applicable_from <= as_of_date_iso).
           Future-effective advisories (applicable_from > as_of_date_iso) are strictly excluded.
        3. Season & season-year awareness: Filters against target season/year.
        4. Excludes machine-translated unverified content.
        """
        conn = get_connection(self.db_path)
        try:
            clauses = [
                "k.verification_status = 'verified'",
                "k.translation_status != 'machine_translated_unverified'",
                # Strict validity clause (Phase 5.2 Review Expiry & Date Guard)
                """(
                    (
                        k.knowledge_type = 'static_reference'
                        AND k.is_permanent_reference = 1
                        AND k.last_reviewed_at IS NOT NULL
                        AND date(substr(k.last_reviewed_at, 1, 10), '+' || COALESCE(k.review_cycle_days, 365) || ' days') >= ?
                    )
                    OR
                    (
                        k.knowledge_type != 'static_reference'
                        AND k.applicable_until IS NOT NULL
                        AND k.applicable_until >= ?
                        AND (k.applicable_from IS NULL OR k.applicable_from <= ?)
                    )
                )""",
            ]
            params: List[Any] = [as_of_date_iso, as_of_date_iso, as_of_date_iso]

            # Knowledge type filter
            if filters.knowledge_type:
                clauses.append("k.knowledge_type = ?")
                params.append(filters.knowledge_type)

            # Geographic filtering
            if filters.state:
                clauses.append("k.state = ?")
                params.append(filters.state)

            if filters.district:
                clauses.append("(k.district IS NULL OR LOWER(k.district) = LOWER(?))")
                params.append(filters.district)

            if filters.mandal:
                clauses.append("(k.mandal IS NULL OR LOWER(k.mandal) = LOWER(?))")
                params.append(filters.mandal)

            if filters.village:
                clauses.append("(k.village IS NULL OR LOWER(k.village) = LOWER(?))")
                params.append(filters.village)

            # Agricultural domain filters
            if filters.category:
                clauses.append("k.category = ?")
                params.append(filters.category)

            if filters.crop_name:
                clauses.append("(k.crop_name IS NULL OR LOWER(k.crop_name) = LOWER(?))")
                params.append(filters.crop_name)

            if filters.crop_variety:
                clauses.append("(k.crop_variety IS NULL OR LOWER(k.crop_variety) = LOWER(?))")
                params.append(filters.crop_variety)

            if filters.crop_stage:
                clauses.append("(k.crop_stage IS NULL OR LOWER(k.crop_stage) = LOWER(?))")
                params.append(filters.crop_stage)

            if filters.season:
                clauses.append(
                    "(k.season IS NULL OR LOWER(k.season) = LOWER(?) OR LOWER(k.season) = 'year-round')"
                )
                params.append(filters.season)

            if filters.season_year:
                clauses.append("(k.season_year IS NULL OR k.season_year = ?)")
                params.append(filters.season_year)

            if filters.soil_type:
                clauses.append(
                    "(k.soil_type IS NULL OR LOWER(k.soil_type) LIKE '%' || LOWER(?) || '%')"
                )
                params.append(filters.soil_type)

            if filters.water_condition:
                clauses.append(
                    "(k.water_condition IS NULL OR LOWER(k.water_condition) LIKE '%' || LOWER(?) || '%')"
                )
                params.append(filters.water_condition)

            if filters.language_code:
                clauses.append("k.language_code = ?")
                params.append(filters.language_code)

            where_sql = " AND ".join(clauses)

            # Order by geographic specificity: village -> mandal -> district -> state
            query_sql = f"""
                SELECT k.*,
                       CASE
                           WHEN k.village IS NOT NULL THEN 4
                           WHEN k.mandal IS NOT NULL THEN 3
                           WHEN k.district IS NOT NULL THEN 2
                           ELSE 1
                       END as geo_specificity
                FROM knowledge_items k
                WHERE {where_sql}
                ORDER BY geo_specificity DESC, k.created_at DESC
            """

            cursor = conn.execute(query_sql, params)
            rows = cursor.fetchall()

            results: List[KnowledgeItemWithSourcesModel] = []
            for row in rows:
                item = self._row_to_item(row)
                sources = self.get_sources_for_item(item.knowledge_id)
                # Strict provenance rule: exclude any item that lacks linked approved sources
                approved_sources = [
                    s for s in sources if s.authority_status == "approved"
                ]
                if approved_sources:
                    results.append(
                        KnowledgeItemWithSourcesModel(item=item, sources=approved_sources)
                    )

            return results
        finally:
            conn.close()

    def _row_to_item(self, row: sqlite3.Row) -> KnowledgeItemModel:
        keys = row.keys()
        return KnowledgeItemModel(
            knowledge_id=row["knowledge_id"],
            category=row["category"],
            knowledge_type=row["knowledge_type"] if "knowledge_type" in keys else "seasonal_guidance",
            title=row["title"],
            content=row["content"],
            language_code=row["language_code"],
            translation_status=row["translation_status"],
            state=row["state"],
            district=row["district"],
            mandal=row["mandal"],
            village=row["village"],
            pin_code=row["pin_code"],
            crop_name=row["crop_name"],
            crop_variety=row["crop_variety"],
            crop_stage=row["crop_stage"],
            season=row["season"],
            season_year=row["season_year"] if "season_year" in keys else None,
            soil_type=row["soil_type"],
            water_condition=row["water_condition"],
            applicable_from=row["applicable_from"],
            applicable_until=row["applicable_until"],
            publication_date=row["publication_date"],
            is_permanent_reference=bool(row["is_permanent_reference"]) if "is_permanent_reference" in keys else False,
            review_cycle_days=row["review_cycle_days"] if "review_cycle_days" in keys else None,
            last_reviewed_at=row["last_reviewed_at"] if "last_reviewed_at" in keys else None,
            verification_status=row["verification_status"],
            verified_at=row["verified_at"],
            verified_by=row["verified_by"] if "verified_by" in keys else None,
            retrieval_applicability_notes=row["retrieval_applicability_notes"] if "retrieval_applicability_notes" in keys else None,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
