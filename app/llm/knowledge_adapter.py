"""
Approved Knowledge Retrieval Adapter for KrishiVaani — Phase 7.3.

Provides a strictly read-only data access layer that queries the SQLite knowledge database,
filters strictly for explicitly approved/verified records, enforces conservative geographic
and validity boundaries, and maps records to the Phase 7.2 ApprovedEvidenceItem schema.

CITATION LIMITATION:
The presence of a citation_id, source_id, and source_url documents database provenance
and publication origin only. It does NOT constitute programmatic semantic verification
that all generative text produced by downstream LLMs is factually accurate.
"""

import sqlite3
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any, Set
from datetime import datetime, date
from pydantic import BaseModel, Field, ConfigDict

from app.core.config import settings
from app.db.database import get_connection
from app.llm.schemas import ApprovedEvidenceItem
from app.knowledge.geography import PJTSAU_AGRO_CLIMATIC_ZONES, PJTSAUAgroClimaticZone

logger = logging.getLogger(__name__)

# Map normalized zone names and abbreviations to their canonical district sets
PJTSAU_ZONE_DISTRICT_MAP: Dict[str, Set[str]] = {}
for zone in PJTSAU_AGRO_CLIMATIC_ZONES:
    dist_set = {d.strip().lower() for d in zone.districts}
    PJTSAU_ZONE_DISTRICT_MAP[zone.zone_name.lower()] = dist_set
    PJTSAU_ZONE_DISTRICT_MAP[zone.zone_abbreviation.lower()] = dist_set


class KnowledgeRetrievalFilter(BaseModel):
    """Conservative query parameters for retrieving approved agricultural knowledge."""
    model_config = ConfigDict(extra="ignore")

    farmer_state: str = Field(default="Telangana", description="Farmer state")
    farmer_district: Optional[str] = Field(default=None, description="Farmer revenue district")
    farmer_mandal: Optional[str] = Field(default=None, description="Farmer mandal")
    farmer_village: Optional[str] = Field(default=None, description="Farmer village")
    crop_name: Optional[str] = Field(default=None, description="Crop name (e.g. Groundnut, Cotton)")
    crop_variety: Optional[str] = Field(default=None, description="Specific variety (e.g. TAG-24)")
    season: Optional[str] = Field(default=None, description="Season (e.g. Yasangi, Kharif)")
    season_year: Optional[int] = Field(default=None, description="Season calendar year (e.g. 2026)")
    category: Optional[str] = Field(default=None, description="Knowledge category (e.g. crop_management, pest_management)")
    knowledge_type: Optional[str] = Field(default=None, description="Knowledge type (e.g. seasonal_advisory, static_reference)")
    as_of_date: Optional[str] = Field(default=None, description="Evaluation date string YYYY-MM-DD (defaults to today)")
    max_items: int = Field(default=10, description="Maximum number of evidence items to return")


class EvidenceRetrievalResult(BaseModel):
    """Result container returning approved evidence items or an explicit abstention reason."""
    model_config = ConfigDict(extra="ignore")

    items: List[ApprovedEvidenceItem] = Field(default_factory=list)
    total_eligible: int = 0
    total_excluded_pending: int = 0
    total_excluded_verified: int = 0
    total_excluded_rejected: int = 0
    total_excluded_expired: int = 0
    total_excluded_geo_mismatch: int = 0
    abstention_reason: Optional[str] = None
    as_of_date: str
    retrieval_metadata: Dict[str, Any] = Field(default_factory=dict)


class ApprovedKnowledgeAdapter:
    """
    Read-only adapter for retrieving verified agricultural knowledge from SQLite.
    Never creates, modifies, approves, or deletes database records.
    """

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or settings.DATABASE_PATH

    def get_database_status_summary(self) -> Dict[str, Any]:
        """
        Inspect the database status distribution without mutating any records.
        Returns exact counts of sources, items, links, audit records, and verification statuses.
        """
        conn = get_connection(self.db_path)
        try:
            cursor = conn.cursor()
            
            # Count sources
            cursor.execute("SELECT count(*) FROM knowledge_sources")
            sources_count = cursor.fetchone()[0]

            # Count items
            cursor.execute("SELECT count(*) FROM knowledge_items")
            items_count = cursor.fetchone()[0]

            # Count links
            cursor.execute("SELECT count(*) FROM knowledge_item_sources")
            links_count = cursor.fetchone()[0]

            # Count audits
            cursor.execute("SELECT count(*) FROM knowledge_verification_audit")
            audits_count = cursor.fetchone()[0]

            # Count farmers
            cursor.execute("SELECT count(*) FROM farmers")
            farmers_count = cursor.fetchone()[0]

            # Group by verification status
            cursor.execute(
                "SELECT verification_status, count(*) FROM knowledge_items GROUP BY verification_status"
            )
            status_counts = dict(cursor.fetchall())

            return {
                "sources_count": sources_count,
                "items_count": items_count,
                "links_count": links_count,
                "audits_count": audits_count,
                "farmers_count": farmers_count,
                "status_distribution": status_counts,
                "approved_count": status_counts.get("approved", 0),
                "verified_count": status_counts.get("verified", 0),
                "pending_count": status_counts.get("pending_verification", 0) + status_counts.get("pending", 0),
                "rejected_count": status_counts.get("rejected", 0),
            }
        finally:
            conn.close()

    def retrieve_approved_evidence(
        self, filters: KnowledgeRetrievalFilter
    ) -> EvidenceRetrievalResult:
        """
        Retrieve approved, non-expired, geographically compatible evidence.
        Accepts ONLY records with verification_status = 'approved'.
        'verified', 'pending_verification', and 'rejected' are strictly excluded.
        Returns empty evidence collection with explicit abstention reason when zero eligible records exist.
        """
        as_of = self._parse_iso_date(filters.as_of_date) or date.today()
        as_of_iso = as_of.isoformat()

        # Gather baseline audit counts
        db_summary = self.get_database_status_summary()
        total_in_db = db_summary["items_count"]
        approved_in_db = db_summary["approved_count"]
        verified_in_db = db_summary["verified_count"]
        pending_in_db = db_summary["pending_count"]
        rejected_in_db = db_summary["rejected_count"]

        # Fast path: If zero approved records exist in the entire database, abstain immediately
        if approved_in_db == 0:
            logger.info("Database contains 0 approved items (all %d items are pending/verified/unapproved).", total_in_db)
            return EvidenceRetrievalResult(
                items=[],
                total_eligible=0,
                total_excluded_pending=pending_in_db,
                total_excluded_verified=verified_in_db,
                total_excluded_rejected=rejected_in_db,
                total_excluded_expired=0,
                total_excluded_geo_mismatch=0,
                abstention_reason=(
                    f"NO_APPROVED_EVIDENCE: All {total_in_db} knowledge items in the database are currently "
                    f"not approved for LLM use (pending_verification={pending_in_db}, verified={verified_in_db}, rejected={rejected_in_db}). "
                    f"Zero approved evidence exists. Assistant must abstain from factual agricultural recommendations."
                ),
                as_of_date=as_of_iso,
                retrieval_metadata={
                    "total_in_db": total_in_db,
                    "approved_in_db": 0,
                    "verified_in_db": verified_in_db,
                    "pending_in_db": pending_in_db,
                },
            )

        # Build conservative read-only SQL query for approved records
        conn = get_connection(self.db_path)
        try:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # Base query joining item, source links, and source metadata - ONLY 'approved' allowed
            query = """
                SELECT k.knowledge_id, k.category, k.knowledge_type, k.title, k.content,
                       k.language_code, k.state, k.district, k.mandal, k.village,
                       k.crop_name, k.crop_variety, k.crop_stage, k.season, k.season_year,
                       k.applicable_from, k.applicable_until, k.is_permanent_reference,
                       k.review_cycle_days, k.last_reviewed_at, k.verification_status,
                       k.retrieval_applicability_notes,
                       s.source_id, s.source_type, s.source_url, s.published_at,
                       kis.reference_location
                FROM knowledge_items k
                LEFT JOIN knowledge_item_sources kis ON k.knowledge_id = kis.item_id
                LEFT JOIN knowledge_sources s ON kis.source_id = s.source_id
                WHERE LOWER(k.verification_status) = 'approved'
            """
            params: List[Any] = []

            # 1. State filter
            if filters.farmer_state:
                query += " AND LOWER(k.state) = LOWER(?)"
                params.append(filters.farmer_state)

            # 2. Category & Knowledge Type filters
            if filters.category:
                query += " AND LOWER(k.category) = LOWER(?)"
                params.append(filters.category)

            if filters.knowledge_type:
                query += " AND LOWER(k.knowledge_type) = LOWER(?)"
                params.append(filters.knowledge_type)

            # 3. Crop Name filter
            if filters.crop_name:
                query += " AND (k.crop_name IS NULL OR LOWER(k.crop_name) = LOWER(?))"
                params.append(filters.crop_name)

            # 4. Season filter
            if filters.season:
                query += " AND (k.season IS NULL OR LOWER(k.season) = LOWER(?) OR LOWER(k.season) = 'year-round')"
                params.append(filters.season)

            cursor.execute(query, params)
            candidate_rows = cursor.fetchall()

            # Process candidates under strict Python-level conservative rules
            eligible_items: List[ApprovedEvidenceItem] = []
            excluded_expired = 0
            excluded_geo = 0

            for row in candidate_rows:
                # Check expiration rule
                is_expired, exp_reason = self._is_record_expired(row, as_of)
                if is_expired:
                    excluded_expired += 1
                    logger.debug("Excluded expired item '%s': %s", row["knowledge_id"], exp_reason)
                    continue

                # Check geography rule
                geo_matches, geo_reason, zone_name = self._matches_geography(row, filters)
                if not geo_matches:
                    excluded_geo += 1
                    logger.debug("Excluded geographically mismatched item '%s': %s", row["knowledge_id"], geo_reason)
                    continue

                # Convert to ApprovedEvidenceItem preserving full provenance
                evidence_item = ApprovedEvidenceItem(
                    evidence_id=row["knowledge_id"],
                    source_id=row["source_id"] or "UNKNOWN_SOURCE",
                    source_type=row["source_type"] or "OFFICIAL_PUBLICATION",
                    title=row["title"],
                    content=row["content"],
                    verification_status=row["verification_status"].upper(),
                    state=row["state"] or "Telangana",
                    district=row["district"],
                    mandal=row["mandal"],
                    village=row["village"],
                    crop_name=row["crop_name"],
                    season=row["season"],
                    valid_from=row["applicable_from"],
                    valid_until=row["applicable_until"],
                    is_expired=False,
                    source_url=row["source_url"],
                    source_date=row["published_at"],
                    reference_location=row["reference_location"],
                    citation_id=f"CITE-{row['knowledge_id']}-{row['source_id'] or 'SRC'}",
                    agro_climatic_zone=zone_name,
                    category=row["category"],
                    knowledge_type=row["knowledge_type"],
                )
                eligible_items.append(evidence_item)

                if len(eligible_items) >= filters.max_items:
                    break

            # If zero items eligible after filtering
            abstention_reason = None
            if not eligible_items:
                reasons = []
                if excluded_expired > 0:
                    reasons.append(f"{excluded_expired} items expired as of {as_of_iso}")
                if excluded_geo > 0:
                    reasons.append(f"{excluded_geo} items geographically mismatched")
                reason_detail = ", ".join(reasons) if reasons else "No approved records matched agricultural criteria"
                abstention_reason = f"NO_MATCHING_EVIDENCE: {reason_detail}."

            return EvidenceRetrievalResult(
                items=eligible_items,
                total_eligible=len(eligible_items),
                total_excluded_pending=pending_in_db,
                total_excluded_verified=verified_in_db,
                total_excluded_rejected=rejected_in_db,
                total_excluded_expired=excluded_expired,
                total_excluded_geo_mismatch=excluded_geo,
                abstention_reason=abstention_reason,
                as_of_date=as_of_iso,
                retrieval_metadata={
                    "total_candidates_examined": len(candidate_rows),
                    "approved_in_db": approved_in_db,
                },
            )

        finally:
            conn.close()

    def _is_record_expired(self, row: sqlite3.Row, as_of: date) -> tuple[bool, str]:
        """
        Conservatively evaluate expiration. Missing or malformed validity dates are treated as expired/invalid.
        """
        k_type = (row["knowledge_type"] or "").lower()
        is_perm = bool(row["is_permanent_reference"])

        # Static permanent reference check
        if k_type == "static_reference" or is_perm:
            last_rev_str = row["last_reviewed_at"]
            if not last_rev_str:
                return True, "Permanent reference missing last_reviewed_at timestamp."
            last_rev_date = self._parse_iso_date(last_rev_str)
            if not last_rev_date:
                return True, "Permanent reference has unparseable last_reviewed_at."
            
            cycle_days = row["review_cycle_days"] or 365
            days_since_review = (as_of - last_rev_date).days
            if days_since_review > cycle_days:
                return True, f"Review cycle elapsed ({days_since_review} days > {cycle_days} days limit)."
            return False, "Active permanent reference within review cycle."

        # Time-bound advisory check
        until_str = row["applicable_until"]
        if not until_str:
            return True, "Time-bound advisory missing applicable_until date."
        until_date = self._parse_iso_date(until_str)
        if not until_date:
            return True, "Time-bound advisory has malformed applicable_until date."
        if until_date < as_of:
            return True, f"Advisory validity expired on {until_str} (as of {as_of.isoformat()})."

        # Check future effective date
        from_str = row["applicable_from"]
        if from_str:
            from_date = self._parse_iso_date(from_str)
            if from_date and from_date > as_of:
                return True, f"Future effective advisory starting on {from_str}."

        return False, "Valid active advisory."

    def _matches_geography(
        self, row: sqlite3.Row, filters: KnowledgeRetrievalFilter
    ) -> tuple[bool, str, Optional[str]]:
        """
        Enforce conservative geographic matching rules:
        - PJTAU agro-climatic zones and revenue districts are NOT interchangeable.
        - Village match cannot be inferred from district source.
        - Unknown geography does NOT silently match district-specific advice.
        """
        item_district = (row["district"] or "").strip()
        item_mandal = (row["mandal"] or "").strip()
        item_village = (row["village"] or "").strip()
        notes = (row["retrieval_applicability_notes"] or "") + " " + (row["title"] or "")

        # Check if item mentions an agro-climatic zone in title or notes
        detected_zone = None
        for z_key in PJTSAU_ZONE_DISTRICT_MAP:
            if z_key in notes.lower():
                detected_zone = z_key
                break

        # Case 1: Farmer geography is unknown (district is None or empty)
        if not filters.farmer_district:
            # District-specific advice CANNOT match when farmer district is unknown
            if item_district:
                return False, f"Item is specific to district '{item_district}', but farmer district is unknown.", detected_zone
            # If item is statewide (district IS NULL)
            return True, "Statewide guidance matches unknown farmer district.", detected_zone

        farmer_dist_clean = filters.farmer_district.strip().lower()

        # Case 2: Item is explicitly district-specific
        if item_district:
            if item_district.lower() != farmer_dist_clean:
                return False, f"District mismatch: item is for '{item_district}', farmer is in '{filters.farmer_district}'.", detected_zone
            
            # Mandal check if item specifies a mandal
            if item_mandal and filters.farmer_mandal:
                if item_mandal.lower() != filters.farmer_mandal.strip().lower():
                    return False, f"Mandal mismatch: item is for '{item_mandal}', farmer is in '{filters.farmer_mandal}'.", detected_zone
            elif item_mandal and not filters.farmer_mandal:
                # Item is mandal-specific, but farmer mandal is unknown
                return False, f"Item is specific to mandal '{item_mandal}', but farmer mandal is unknown.", detected_zone

            # Village check
            if item_village and filters.farmer_village:
                if item_village.lower() != filters.farmer_village.strip().lower():
                    return False, f"Village mismatch: item is for '{item_village}', farmer is in '{filters.farmer_village}'.", detected_zone

            return True, "Direct administrative district match.", detected_zone

        # Case 3: Item has no administrative district, but belongs to an agro-climatic zone
        if detected_zone:
            allowed_districts = PJTSAU_ZONE_DISTRICT_MAP.get(detected_zone, set())
            if farmer_dist_clean not in allowed_districts:
                return False, f"Zone mismatch: '{filters.farmer_district}' does not belong to PJTSAU '{detected_zone}'.", detected_zone
            return True, f"Farmer district belongs to PJTSAU agro-climatic zone '{detected_zone}'.", detected_zone

        # Case 4: Item is general statewide guidance (district IS NULL, no zonal restriction)
        return True, "Statewide advisory applies across Telangana.", None

    @staticmethod
    def _parse_iso_date(date_str: Optional[str]) -> Optional[date]:
        """Safely parse YYYY-MM-DD date string."""
        if not date_str:
            return None
        try:
            return datetime.strptime(date_str.strip()[:10], "%Y-%m-%d").date()
        except Exception:
            return None

