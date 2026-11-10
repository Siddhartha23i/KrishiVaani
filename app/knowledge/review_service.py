"""
Human Evidence Review and Approval Service for KrishiVaani — Phase 7.4.

Provides auditable administrative operations to transition knowledge items
through explicit review states (pending_verification -> verified -> approved / rejected).
Enforces reviewer role authorization, prevents ungrounded promotions, prevents expired
advisories from becoming active advice, and maintains an application-level append-only audit trail.

AUDIT INTEGRITY & IMMUTABILITY LIMITATION:
Audit records in `knowledge_verification_audit` are append-only strictly by application-level
contract: ReviewService only executes INSERT statements and provides no update or delete operations.
However, the underlying SQLite database does not enforce database-level immutability (e.g. via
database triggers or read-only tablespaces). Any direct SQL connection with write access can modify
or delete audit rows. Database-level tamper-proofing is deferred to avoid risky database migrations.

IDENTITY & AUTHORIZATION LIMITATION:
Reviewer identity (`actor`) and role (`actor_role`) are self-asserted caller inputs.
Role checks are application-level safeguards against operational errors, NOT cryptographic
or third-party verified identity. The service is designed solely for trusted administrative use.

THIS IS AN ADMINISTRATIVE BACKEND TOOL, NOT A FARMER-FACING FEATURE.
"""

import sqlite3
import uuid
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime, timezone, date

from app.core.config import settings
from app.db.database import get_connection

logger = logging.getLogger(__name__)

# Valid verification statuses
STATUS_PENDING = "pending_verification"
STATUS_VERIFIED = "verified"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"

VALID_STATUSES = {STATUS_PENDING, STATUS_VERIFIED, STATUS_APPROVED, STATUS_REJECTED}

# Recognized reviewer roles
ROLE_TECHNICAL_REVIEWER = "technical_reviewer"
ROLE_AGRICULTURAL_EXPERT = "agricultural_expert"
ROLE_AGRONOMIST = "agronomist"
ROLE_SYSTEM_ADMIN = "system_administrator"

# STRICT AUTHORIZATION POLICY (Phase 7.4.1):
# Only qualified agricultural experts may approve farmer-facing agricultural recommendations.
# Technical reviewers and ordinary system administrators must not be able to approve agronomic
# advice merely by supplying a role name.
AUTHORIZED_APPROVAL_ROLES = {
    ROLE_AGRICULTURAL_EXPERT,
    ROLE_AGRONOMIST,
}

# Agronomic categories requiring qualified agricultural review
AGRONOMIC_CATEGORIES = {
    "crop_management",
    "plant_protection",
    "pest_management",
    "disease_management",
    "nutrient_management",
    "fertilizer",
    "irrigation_management",
    "varietal_selection",
    "seed_treatment",
    "harvest_management",
    "agricultural_advisory",
}


class ReviewService:
    """
    Administrative service managing the human review and audit lifecycle of agricultural knowledge.
    Guarantees that no status transition occurs without reviewer accountability and application-level
    append-only audit recording.
    """

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or settings.DATABASE_PATH

    def list_records(
        self,
        status: Optional[str] = None,
        category: Optional[str] = None,
        district: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """
        List knowledge records with source, category, title, geography, and dates.
        """
        conn = get_connection(self.db_path)
        try:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            query = """
                SELECT k.knowledge_id, k.category, k.knowledge_type, k.title,
                       k.state, k.district, k.mandal, k.village,
                       k.crop_name, k.season, k.applicable_from, k.applicable_until,
                       k.verification_status, k.verified_at, k.verified_by,
                       k.created_at,
                       s.source_id, s.publisher, s.document_title, s.source_url,
                       kis.reference_location
                FROM knowledge_items k
                LEFT JOIN knowledge_item_sources kis ON k.knowledge_id = kis.item_id
                LEFT JOIN knowledge_sources s ON kis.source_id = s.source_id
                WHERE 1=1
            """
            params: List[Any] = []

            if status:
                query += " AND LOWER(k.verification_status) = LOWER(?)"
                params.append(status)

            if category:
                query += " AND LOWER(k.category) = LOWER(?)"
                params.append(category)

            if district:
                query += " AND LOWER(k.district) = LOWER(?)"
                params.append(district)

            query += " ORDER BY k.created_at DESC, k.knowledge_id ASC LIMIT ? OFFSET ?"
            params.extend([limit, offset])

            cursor.execute(query, params)
            rows = cursor.fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_record_detail(self, knowledge_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve complete record detail including source URL, reference location,
        extracted content, and full chronological verification audit history.
        """
        conn = get_connection(self.db_path)
        try:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            query = """
                SELECT k.*,
                       s.source_id, s.publisher, s.document_title, s.source_url,
                       s.source_type, s.authority_status, s.published_at as source_published_at,
                       kis.reference_location
                FROM knowledge_items k
                LEFT JOIN knowledge_item_sources kis ON k.knowledge_id = kis.item_id
                LEFT JOIN knowledge_sources s ON kis.source_id = s.source_id
                WHERE k.knowledge_id = ?
            """
            cursor.execute(query, (knowledge_id,))
            row = cursor.fetchone()
            if not row:
                return None

            record = dict(row)
            record["audit_history"] = self.get_audit_history(knowledge_id)
            return record
        finally:
            conn.close()

    def get_audit_history(self, entity_id: str) -> List[Dict[str, Any]]:
        """Retrieve complete chronological audit history for a knowledge item."""
        conn = get_connection(self.db_path)
        try:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute(
                """
                SELECT audit_id, entity_type, entity_id, action,
                       actor, actor_role, is_test_audit, notes, created_at
                FROM knowledge_verification_audit
                WHERE entity_id = ?
                ORDER BY created_at ASC, audit_id ASC
                """,
                (entity_id,),
            )
            return [dict(r) for r in cursor.fetchall()]
        finally:
            conn.close()

    def transition_status(
        self,
        knowledge_id: str,
        new_status: str,
        actor: str,
        actor_role: str,
        notes: str,
        is_test_audit: bool = False,
    ) -> Dict[str, Any]:
        """
        Transition verification status of a knowledge item with strict validation,
        authorization checks, and immutable audit recording.

        Args:
            knowledge_id: The ID of the knowledge item to transition.
            new_status: Target status ('verified', 'approved', 'rejected').
            actor: Reviewer identifier (e.g. 'dr_ramana_pjtau', 'qa_siddharth').
            actor_role: Reviewer role (e.g. 'agricultural_expert', 'technical_reviewer').
            notes: Mandatory review explanation or rejection rationale.
            is_test_audit: Flag indicating test-run audit events.

        Returns:
            Dict containing transition summary, updated item, and generated audit record.

        Raises:
            ValueError: On invalid parameters, missing reviewer/notes, expired advisory approval,
                        or duplicate/redundant status transitions.
            PermissionError: When an unauthorized role attempts agronomic approval.
        """
        # 1. Parameter presence validation
        if not knowledge_id or not knowledge_id.strip():
            raise ValueError("Knowledge item ID must be provided.")

        clean_status = (new_status or "").strip().lower()
        if clean_status not in VALID_STATUSES or clean_status == STATUS_PENDING:
            raise ValueError(
                f"Invalid target status '{new_status}'. Allowed review targets: {sorted([STATUS_VERIFIED, STATUS_APPROVED, STATUS_REJECTED])}"
            )

        clean_actor = (actor or "").strip()
        if not clean_actor:
            raise ValueError("Reviewer identifier (actor) is required for accountability.")

        clean_role = (actor_role or "").strip().lower()
        if not clean_role:
            raise ValueError("Reviewer role (actor_role) is required.")

        clean_notes = (notes or "").strip()
        if not clean_notes or len(clean_notes) < 3:
            raise ValueError("Meaningful review notes (at least 3 characters) are required.")

        if clean_status == STATUS_REJECTED and len(clean_notes) < 5:
            raise ValueError("A clear, substantive rejection reason (at least 5 characters) is required when rejecting evidence.")

        # 2. Fetch current record
        conn = get_connection(self.db_path)
        try:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute("SELECT * FROM knowledge_items WHERE knowledge_id = ?", (knowledge_id,))
            current_row = cursor.fetchone()
            if not current_row:
                raise ValueError(f"Knowledge item '{knowledge_id}' does not exist.")

            current_status = (current_row["verification_status"] or "").lower()
            category = (current_row["category"] or "").lower()
            applicable_until = current_row["applicable_until"]
            is_permanent = bool(current_row["is_permanent_reference"])
            k_type = (current_row["knowledge_type"] or "").lower()

            # 3. Idempotency & Redundancy Check
            if current_status == clean_status:
                raise ValueError(
                    f"Item '{knowledge_id}' is already in status '{clean_status}'. Duplicate transition rejected."
                )

            # 4. State Machine Transition Validation
            # Direct promotion to approved requires item to be verified first
            if clean_status == STATUS_APPROVED:
                if current_status == STATUS_PENDING:
                    raise ValueError(
                        f"Item '{knowledge_id}' is currently 'pending_verification'. "
                        "Technical verification must be completed ('verified') before agronomic approval."
                    )
                if current_status == STATUS_REJECTED:
                    raise ValueError(
                        f"Item '{knowledge_id}' is currently 'rejected'. "
                        "Ungrounded status promotion is disallowed; item must be re-verified ('verified') before approval."
                    )

            # 5. Reviewer Role Authorization Checks
            if clean_status == STATUS_APPROVED:
                # Check role authorization for agronomic advice
                if clean_role not in AUTHORIZED_APPROVAL_ROLES:
                    if category in AGRONOMIC_CATEGORIES:
                        raise PermissionError(
                            f"Role '{clean_role}' is not authorized to approve agricultural recommendations. "
                            f"Agricultural guidance requires qualified agronomic review ({sorted(AUTHORIZED_APPROVAL_ROLES)})."
                        )
                    else:
                        raise PermissionError(
                            f"Role '{clean_role}' is not authorized to approve farmer-facing knowledge items. "
                            f"Farmer-facing approval requires qualified agronomic review ({sorted(AUTHORIZED_APPROVAL_ROLES)})."
                        )

                # 6. Expiration Check: Expired advisories cannot be approved as active advice
                if applicable_until and not is_permanent and k_type != "static_reference":
                    try:
                        exp_date = datetime.strptime(applicable_until[:10], "%Y-%m-%d").date()
                        if exp_date < date.today():
                            raise ValueError(
                                f"Cannot approve expired advisory '{knowledge_id}'. It expired on {applicable_until}. "
                                "Expired evidence cannot be approved for active farmer-facing advice."
                            )
                    except ValueError as e:
                        if "Cannot approve expired" in str(e):
                            raise
                        # Malformed date
                        raise ValueError(
                            f"Cannot approve advisory '{knowledge_id}' with malformed applicable_until date '{applicable_until}'."
                        )

            # 6. Execute atomic status update and audit creation
            now_iso = datetime.now(timezone.utc).isoformat()
            audit_id = f"aud_rev_{uuid.uuid4().hex[:12]}"
            action_name = f"status_transition_{current_status}_to_{clean_status}"

            with conn:
                # Update knowledge_items
                conn.execute(
                    """
                    UPDATE knowledge_items
                    SET verification_status = ?,
                        verified_at = ?,
                        verified_by = ?,
                        retrieval_applicability_notes = ?,
                        updated_at = ?
                    WHERE knowledge_id = ?
                    """,
                    (
                        clean_status,
                        now_iso,
                        f"{clean_role}:{clean_actor}",
                        clean_notes,
                        now_iso,
                        knowledge_id,
                    ),
                )

                # Record append-only verification audit event (application-level contract)
                conn.execute(
                    """
                    INSERT INTO knowledge_verification_audit (
                        audit_id, entity_type, entity_id, action,
                        actor, actor_role, is_test_audit, notes, created_at
                    ) VALUES (?, 'knowledge_item', ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        audit_id,
                        knowledge_id,
                        action_name,
                        clean_actor,
                        clean_role,
                        1 if is_test_audit else 0,
                        clean_notes,
                        now_iso,
                    ),
                )

            logger.info(
                "Knowledge item '%s' transitioned from '%s' to '%s' by %s (%s). Audit: %s",
                knowledge_id, current_status, clean_status, clean_actor, clean_role, audit_id
            )

            return {
                "knowledge_id": knowledge_id,
                "previous_status": current_status,
                "new_status": clean_status,
                "verified_by": f"{clean_role}:{clean_actor}",
                "verified_at": now_iso,
                "audit_id": audit_id,
                "action": action_name,
                "notes": clean_notes,
            }

        finally:
            conn.close()

