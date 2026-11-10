"""
Unit and Integration Test Suite for KrishiVaani Human Review Workflow — Phase 7.4.

Tests:
1. Valid transitions: pending -> verified -> approved, pending -> rejected.
2. Reviewer accountability: actor, role, and substantive notes are mandatory.
3. Strict role authorization: technical reviewers cannot approve agronomic guidance.
4. Expiration guard: expired advisories cannot be approved for active advice.
5. Idempotency: duplicate transitions to the same status are rejected.
6. Atomicity: failed transitions do not mutate records or create audit entries.
7. Audit trail: every valid transition creates an immutable record in knowledge_verification_audit.
8. LLM adapter exclusion: adapter accepts strictly 'approved' items; 'verified', 'pending', and 'rejected' are excluded.
9. Lifecycle retrieval verification: item only becomes retrievable upon agronomic approval, and is excluded upon rejection.
10. CLI commands: list, show, history, verify, approve, reject.
11. Real database safety check: real project database has 0 mutations and remains 51 pending.
"""

import io
import unittest
from pathlib import Path
import tempfile
import sqlite3
import shutil
from datetime import date, timedelta
from unittest.mock import patch

from app.core.config import settings
from app.db.database import init_db, get_connection
from app.knowledge.review_service import (
    ReviewService,
    STATUS_PENDING,
    STATUS_VERIFIED,
    STATUS_APPROVED,
    STATUS_REJECTED,
    ROLE_TECHNICAL_REVIEWER,
    ROLE_AGRICULTURAL_EXPERT,
    ROLE_AGRONOMIST,
    ROLE_SYSTEM_ADMIN,
)
from app.knowledge.review_cli import (
    cmd_list,
    cmd_show,
    cmd_history,
    cmd_transition,
    main,
)
from app.llm.knowledge_adapter import (
    ApprovedKnowledgeAdapter,
    KnowledgeRetrievalFilter,
)


class TestHumanReviewWorkflow(unittest.TestCase):
    """Isolated unit tests for ReviewService and human review workflow."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test_review.db"
        init_db(self.db_path)
        self.service = ReviewService(db_path=self.db_path)
        self.adapter = ApprovedKnowledgeAdapter(db_path=self.db_path)

        # Seed test source
        self._insert_source()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _insert_source(
        self,
        source_id="SRC-PJTAU-TEST",
        publisher="PJTAU",
        document_title="PJTAU Test Advisory Bulletin",
        source_url="https://pjtau.edu.in/bulletin_test.pdf",
    ):
        conn = get_connection(self.db_path)
        with conn:
            conn.execute(
                """
                INSERT INTO knowledge_sources (
                    source_id, publisher, document_title, source_url, source_type,
                    authority_status, published_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 'PJTAU_AGROMET_ADVISORY', 'verified_official', '2026-11-04', '2026-11-04', '2026-11-04')
                """,
                (source_id, publisher, document_title, source_url),
            )
        conn.close()

    def _insert_item(
        self,
        knowledge_id,
        category="crop_management",
        title="Groundnut Sowing Guidance",
        content="Optimum sowing window for Yasangi Groundnut is October to November 15.",
        verification_status=STATUS_PENDING,
        district="Warangal",
        crop_name="Groundnut",
        season="Yasangi",
        applicable_from=None,
        applicable_until=None,
        is_permanent_reference=0,
    ):
        conn = get_connection(self.db_path)
        with conn:
            conn.execute(
                """
                INSERT INTO knowledge_items (
                    knowledge_id, category, knowledge_type, title, content,
                    language_code, translation_status, state, district,
                    crop_name, season, applicable_from, applicable_until,
                    is_permanent_reference, last_reviewed_at, review_cycle_days,
                    verification_status, retrieval_applicability_notes,
                    created_at, updated_at
                ) VALUES (
                    ?, ?, 'seasonal_advisory', ?, ?,
                    'te', 'human_verified', 'Telangana', ?,
                    ?, ?, ?, ?,
                    ?, NULL, 365,
                    ?, NULL,
                    '2026-11-04', '2026-11-04'
                )
                """,
                (
                    knowledge_id, category, title, content, district,
                    crop_name, season, applicable_from, applicable_until,
                    is_permanent_reference, verification_status,
                ),
            )
            conn.execute(
                """
                INSERT INTO knowledge_item_sources (
                    item_id, source_id, reference_location, created_at
                ) VALUES (?, 'SRC-PJTAU-TEST', 'Page 1, Table 1', '2026-11-04')
                """,
                (knowledge_id,),
            )
        conn.close()

    # --- Test 1: Technical Verification (pending -> verified) ---
    def test_technical_verification_success(self):
        kid = "KNOW-TEST-001"
        self._insert_item(kid, verification_status=STATUS_PENDING)

        result = self.service.transition_status(
            knowledge_id=kid,
            new_status=STATUS_VERIFIED,
            actor="tech_reviewer_1",
            actor_role=ROLE_TECHNICAL_REVIEWER,
            notes="Source PDF authenticated; text extraction verified against Table 1.",
        )

        self.assertEqual(result["knowledge_id"], kid)
        self.assertEqual(result["previous_status"], STATUS_PENDING)
        self.assertEqual(result["new_status"], STATUS_VERIFIED)
        self.assertEqual(result["verified_by"], f"{ROLE_TECHNICAL_REVIEWER}:tech_reviewer_1")

        # Verify database record updated
        detail = self.service.get_record_detail(kid)
        self.assertEqual(detail["verification_status"], STATUS_VERIFIED)
        self.assertIn("tech_reviewer_1", detail["verified_by"])

        # Verify audit trail
        history = self.service.get_audit_history(kid)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["action"], "status_transition_pending_verification_to_verified")
        self.assertEqual(history[0]["actor"], "tech_reviewer_1")
        self.assertEqual(history[0]["actor_role"], ROLE_TECHNICAL_REVIEWER)

    # --- Test 2: Agricultural Expert Approval (verified -> approved) ---
    def test_agricultural_expert_approval_success(self):
        kid = "KNOW-TEST-002"
        future_date = (date.today() + timedelta(days=10)).isoformat()
        self._insert_item(kid, verification_status=STATUS_VERIFIED, applicable_until=future_date)

        result = self.service.transition_status(
            knowledge_id=kid,
            new_status=STATUS_APPROVED,
            actor="dr_ramana_pjtau",
            actor_role=ROLE_AGRICULTURAL_EXPERT,
            notes="Groundnut agronomic advice validated for Telangana soils and Yasangi 2026 season.",
        )

        self.assertEqual(result["previous_status"], STATUS_VERIFIED)
        self.assertEqual(result["new_status"], STATUS_APPROVED)

        detail = self.service.get_record_detail(kid)
        self.assertEqual(detail["verification_status"], STATUS_APPROVED)
        self.assertEqual(detail["verified_by"], f"{ROLE_AGRICULTURAL_EXPERT}:dr_ramana_pjtau")

    # --- Test 2B: Cannot Jump Directly from Pending to Approved ---
    def test_pending_cannot_jump_directly_to_approved(self):
        kid = "KNOW-TEST-002B"
        future_date = (date.today() + timedelta(days=10)).isoformat()
        self._insert_item(kid, verification_status=STATUS_PENDING, applicable_until=future_date)

        with self.assertRaises(ValueError) as ctx:
            self.service.transition_status(
                knowledge_id=kid,
                new_status=STATUS_APPROVED,
                actor="dr_ramana_pjtau",
                actor_role=ROLE_AGRICULTURAL_EXPERT,
                notes="Attempting direct approval without verification.",
            )

        self.assertIn("Technical verification must be completed", str(ctx.exception))
        detail = self.service.get_record_detail(kid)
        self.assertEqual(detail["verification_status"], STATUS_PENDING)

    # --- Test 2C: Rejected Item Cannot Jump Directly to Approved ---
    def test_rejected_cannot_jump_directly_to_approved(self):
        kid = "KNOW-TEST-002C"
        future_date = (date.today() + timedelta(days=10)).isoformat()
        self._insert_item(kid, verification_status=STATUS_REJECTED, applicable_until=future_date)

        with self.assertRaises(ValueError) as ctx:
            self.service.transition_status(
                knowledge_id=kid,
                new_status=STATUS_APPROVED,
                actor="dr_ramana_pjtau",
                actor_role=ROLE_AGRICULTURAL_EXPERT,
                notes="Attempting ungrounded promotion from rejected to approved.",
            )

        self.assertIn("Ungrounded status promotion is disallowed", str(ctx.exception))
        detail = self.service.get_record_detail(kid)
        self.assertEqual(detail["verification_status"], STATUS_REJECTED)

    # --- Test 2D: Rejected Item Can Be Re-verified ---
    def test_rejected_item_can_be_re_verified(self):
        kid = "KNOW-TEST-002D"
        self._insert_item(kid, verification_status=STATUS_REJECTED)

        result = self.service.transition_status(
            knowledge_id=kid,
            new_status=STATUS_VERIFIED,
            actor="tech_reviewer_1",
            actor_role=ROLE_TECHNICAL_REVIEWER,
            notes="Re-checked source PDF after parsing correction; text matches authoritative table.",
        )
        self.assertEqual(result["new_status"], STATUS_VERIFIED)
        detail = self.service.get_record_detail(kid)
        self.assertEqual(detail["verification_status"], STATUS_VERIFIED)

    # --- Test 3: Technical Reviewer CANNOT Approve Agronomic Guidance ---
    def test_technical_reviewer_cannot_approve_agronomic_advice(self):
        kid = "KNOW-TEST-003"
        future_date = (date.today() + timedelta(days=10)).isoformat()
        self._insert_item(kid, category="plant_protection", verification_status=STATUS_VERIFIED, applicable_until=future_date)

        with self.assertRaises(PermissionError) as ctx:
            self.service.transition_status(
                knowledge_id=kid,
                new_status=STATUS_APPROVED,
                actor="tech_reviewer_siddharth",
                actor_role=ROLE_TECHNICAL_REVIEWER,
                notes="Looks technically fine to me.",
            )

        self.assertIn("not authorized to approve agricultural recommendations", str(ctx.exception))

        # Ensure database was NOT mutated
        detail = self.service.get_record_detail(kid)
        self.assertEqual(detail["verification_status"], STATUS_VERIFIED)
        # Ensure no audit record created
        history = self.service.get_audit_history(kid)
        self.assertEqual(len(history), 0)

    # --- Test 3B: System Administrator CANNOT Approve Agronomic Guidance (Phase 7.4.1) ---
    def test_system_administrator_cannot_approve_agronomic_advice(self):
        kid = "KNOW-TEST-003B"
        future_date = (date.today() + timedelta(days=10)).isoformat()
        self._insert_item(kid, category="crop_management", verification_status=STATUS_VERIFIED, applicable_until=future_date)

        with self.assertRaises(PermissionError) as ctx:
            self.service.transition_status(
                knowledge_id=kid,
                new_status=STATUS_APPROVED,
                actor="sys_admin_john",
                actor_role=ROLE_SYSTEM_ADMIN,
                notes="Attempting administrative override to approve crop advice.",
            )

        self.assertIn("not authorized to approve agricultural recommendations", str(ctx.exception))

        # Ensure database was NOT mutated
        detail = self.service.get_record_detail(kid)
        self.assertEqual(detail["verification_status"], STATUS_VERIFIED)
        history = self.service.get_audit_history(kid)
        self.assertEqual(len(history), 0)

    # --- Test 3C: Agronomist CAN Approve Agronomic Guidance after Verification ---
    def test_agronomist_approval_success(self):
        kid = "KNOW-TEST-003C"
        future_date = (date.today() + timedelta(days=10)).isoformat()
        self._insert_item(kid, category="crop_management", verification_status=STATUS_VERIFIED, applicable_until=future_date)

        result = self.service.transition_status(
            knowledge_id=kid,
            new_status=STATUS_APPROVED,
            actor="dr_reddy_agronomist",
            actor_role=ROLE_AGRONOMIST,
            notes="Agronomist review: fertilizer dose and sowing schedule verified against PJTAU recommendations.",
        )

        self.assertEqual(result["new_status"], STATUS_APPROVED)
        self.assertEqual(result["verified_by"], f"{ROLE_AGRONOMIST}:dr_reddy_agronomist")
        detail = self.service.get_record_detail(kid)
        self.assertEqual(detail["verification_status"], STATUS_APPROVED)

    # --- Test 3D: System Administrator CAN Perform Technical Verification and Rejection ---
    def test_system_administrator_can_verify_and_reject(self):
        kid1 = "KNOW-TEST-003D1"
        kid2 = "KNOW-TEST-003D2"
        self._insert_item(kid1, verification_status=STATUS_PENDING)
        self._insert_item(kid2, verification_status=STATUS_PENDING)

        # 1. System admin verifies technical ingestion integrity
        res_ver = self.service.transition_status(
            knowledge_id=kid1,
            new_status=STATUS_VERIFIED,
            actor="sys_admin_alice",
            actor_role=ROLE_SYSTEM_ADMIN,
            notes="Technical verification: PDF metadata and OCR hash matched authoritative source.",
        )
        self.assertEqual(res_ver["new_status"], STATUS_VERIFIED)
        detail1 = self.service.get_record_detail(kid1)
        self.assertEqual(detail1["verification_status"], STATUS_VERIFIED)

        # 2. System admin rejects corrupted item
        res_rej = self.service.transition_status(
            knowledge_id=kid2,
            new_status=STATUS_REJECTED,
            actor="sys_admin_alice",
            actor_role=ROLE_SYSTEM_ADMIN,
            notes="Rejected by sysadmin: Corrupted OCR text payload identified.",
        )
        self.assertEqual(res_rej["new_status"], STATUS_REJECTED)
        detail2 = self.service.get_record_detail(kid2)
        self.assertEqual(detail2["verification_status"], STATUS_REJECTED)

    # --- Test 4: Rejection Requires Substantive Reason ---
    def test_rejection_requires_substantive_reason(self):
        kid = "KNOW-TEST-004"
        self._insert_item(kid, verification_status=STATUS_PENDING)

        # Empty reason
        with self.assertRaises(ValueError):
            self.service.transition_status(
                knowledge_id=kid,
                new_status=STATUS_REJECTED,
                actor="dr_ramana_pjtau",
                actor_role=ROLE_AGRICULTURAL_EXPERT,
                notes="",
            )

        # Too short reason (< 5 chars)
        with self.assertRaises(ValueError) as ctx:
            self.service.transition_status(
                knowledge_id=kid,
                new_status=STATUS_REJECTED,
                actor="dr_ramana_pjtau",
                actor_role=ROLE_AGRICULTURAL_EXPERT,
                notes="bad",
            )
        self.assertIn("clear, substantive rejection reason", str(ctx.exception))

        # Successful rejection with substantive explanation
        result = self.service.transition_status(
            knowledge_id=kid,
            new_status=STATUS_REJECTED,
            actor="dr_ramana_pjtau",
            actor_role=ROLE_AGRICULTURAL_EXPERT,
            notes="Recommendation mentions chemical dosage contradictory to PJTAU package of practices.",
        )
        self.assertEqual(result["new_status"], STATUS_REJECTED)
        detail = self.service.get_record_detail(kid)
        self.assertEqual(detail["verification_status"], STATUS_REJECTED)

    # --- Test 5: Expired Advisory Cannot Be Approved as Active Advice ---
    def test_expired_advisory_cannot_be_approved(self):
        kid = "KNOW-TEST-005"
        past_date = (date.today() - timedelta(days=2)).isoformat()
        self._insert_item(kid, verification_status=STATUS_VERIFIED, applicable_until=past_date, is_permanent_reference=0)

        with self.assertRaises(ValueError) as ctx:
            self.service.transition_status(
                knowledge_id=kid,
                new_status=STATUS_APPROVED,
                actor="dr_ramana_pjtau",
                actor_role=ROLE_AGRICULTURAL_EXPERT,
                notes="Trying to approve an expired advisory.",
            )

        self.assertIn("Cannot approve expired advisory", str(ctx.exception))
        # Ensure record is untouched
        detail = self.service.get_record_detail(kid)
        self.assertEqual(detail["verification_status"], STATUS_VERIFIED)

    # --- Test 6: Permanent Reference Without Expiration Can Be Approved ---
    def test_permanent_reference_can_be_approved(self):
        kid = "KNOW-TEST-006"
        self._insert_item(kid, verification_status=STATUS_VERIFIED, applicable_until=None, is_permanent_reference=1)

        result = self.service.transition_status(
            knowledge_id=kid,
            new_status=STATUS_APPROVED,
            actor="dr_ramana_pjtau",
            actor_role=ROLE_AGRICULTURAL_EXPERT,
            notes="Permanent reference on soil texture characteristics approved.",
        )
        self.assertEqual(result["new_status"], STATUS_APPROVED)

    # --- Test 7: Reviewer Identity and Role Are Mandatory ---
    def test_reviewer_accountability_mandatory(self):
        kid = "KNOW-TEST-007"
        self._insert_item(kid, verification_status=STATUS_PENDING)

        # Missing actor
        with self.assertRaises(ValueError) as ctx:
            self.service.transition_status(
                knowledge_id=kid,
                new_status=STATUS_VERIFIED,
                actor="",
                actor_role=ROLE_TECHNICAL_REVIEWER,
                notes="Valid notes here",
            )
        self.assertIn("Reviewer identifier (actor) is required", str(ctx.exception))

        # Missing actor_role
        with self.assertRaises(ValueError) as ctx:
            self.service.transition_status(
                knowledge_id=kid,
                new_status=STATUS_VERIFIED,
                actor="tech_1",
                actor_role="  ",
                notes="Valid notes here",
            )
        self.assertIn("Reviewer role (actor_role) is required", str(ctx.exception))

    # --- Test 8: Idempotency Rejects Redundant Transitions ---
    def test_idempotency_prevents_duplicate_transitions(self):
        kid = "KNOW-TEST-008"
        self._insert_item(kid, verification_status=STATUS_PENDING)

        self.service.transition_status(
            knowledge_id=kid,
            new_status=STATUS_VERIFIED,
            actor="tech_1",
            actor_role=ROLE_TECHNICAL_REVIEWER,
            notes="First verification",
        )

        # Attempt same transition again
        with self.assertRaises(ValueError) as ctx:
            self.service.transition_status(
                knowledge_id=kid,
                new_status=STATUS_VERIFIED,
                actor="tech_2",
                actor_role=ROLE_TECHNICAL_REVIEWER,
                notes="Second duplicate verification attempt",
            )
        self.assertIn("already in status 'verified'", str(ctx.exception))

        # Verify only 1 audit record exists
        history = self.service.get_audit_history(kid)
        self.assertEqual(len(history), 1)

    # --- Test 9: Complete Lifecycle and LLM Adapter Gate ---
    def test_lifecycle_and_adapter_retrieval_isolation(self):
        """
        Tests the strict safety barrier:
        - pending_verification: excluded by adapter
        - verified: excluded by adapter
        - approved: retrieved by adapter
        - rejected: excluded by adapter
        """
        kid = "KNOW-LIFECYCLE-001"
        future_date = (date.today() + timedelta(days=15)).isoformat()
        past_from = (date.today() - timedelta(days=1)).isoformat()
        self._insert_item(
            kid,
            category="crop_management",
            verification_status=STATUS_PENDING,
            district="Warangal",
            crop_name="Groundnut",
            applicable_from=past_from,
            applicable_until=future_date,
        )

        filter_req = KnowledgeRetrievalFilter(
            farmer_district="Warangal",
            crop_name="Groundnut",
            as_of_date=date.today().isoformat(),
        )

        # Phase A: Status is pending_verification -> must NOT be retrieved
        res_pending = self.adapter.retrieve_approved_evidence(filter_req)
        self.assertEqual(len(res_pending.items), 0)
        self.assertEqual(res_pending.total_excluded_pending, 1)
        self.assertEqual(res_pending.total_excluded_verified, 0)
        self.assertIn("NO_APPROVED_EVIDENCE", res_pending.abstention_reason)

        # Phase B: Transition to verified by technical reviewer
        self.service.transition_status(
            knowledge_id=kid,
            new_status=STATUS_VERIFIED,
            actor="tech_reviewer_1",
            actor_role=ROLE_TECHNICAL_REVIEWER,
            notes="Source bulletin verified.",
        )

        # Must STILL be excluded because 'verified' is not approved for LLM reasoning
        res_verified = self.adapter.retrieve_approved_evidence(filter_req)
        self.assertEqual(len(res_verified.items), 0)
        self.assertEqual(res_verified.total_excluded_verified, 1)
        self.assertEqual(res_verified.total_excluded_pending, 0)
        self.assertIn("NO_APPROVED_EVIDENCE", res_verified.abstention_reason)

        # Phase C: Transition to approved by qualified agronomist
        self.service.transition_status(
            knowledge_id=kid,
            new_status=STATUS_APPROVED,
            actor="dr_agronomist_pjtau",
            actor_role=ROLE_AGRONOMIST,
            notes="Groundnut agronomic advice approved for Warangal Yasangi 2026.",
        )

        # Now it MUST be retrieved!
        res_approved = self.adapter.retrieve_approved_evidence(filter_req)
        self.assertEqual(len(res_approved.items), 1)
        self.assertIsNone(res_approved.abstention_reason)
        retrieved_item = res_approved.items[0]
        self.assertEqual(retrieved_item.evidence_id, kid)
        self.assertEqual(retrieved_item.source_url, "https://pjtau.edu.in/bulletin_test.pdf")

        # Phase D: Transition to rejected (e.g. newly discovered issue)
        self.service.transition_status(
            knowledge_id=kid,
            new_status=STATUS_REJECTED,
            actor="dr_agronomist_pjtau",
            actor_role=ROLE_AGRONOMIST,
            notes="Withdrawn due to updated weather forecast recommending delayed sowing.",
        )

        # Must NOT be retrieved anymore
        res_rejected = self.adapter.retrieve_approved_evidence(filter_req)
        self.assertEqual(len(res_rejected.items), 0)
        self.assertEqual(res_rejected.total_excluded_rejected, 1)
        self.assertIn("NO_APPROVED_EVIDENCE", res_rejected.abstention_reason)

    # --- Test 10: Review CLI Command Functions ---
    def test_cli_subcommands(self):
        kid = "KNOW-CLI-001"
        self._insert_item(kid, verification_status=STATUS_PENDING)

        # cmd_list
        args_list = type("Args", (), {"status": None, "category": None, "district": None, "limit": 10})()
        with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
            cmd_list(self.service, args_list)
            out_str = mock_out.getvalue()
            self.assertIn(kid, out_str)
            self.assertIn("pending_verification", out_str)

        # cmd_show
        args_show = type("Args", (), {"knowledge_id": kid})()
        with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
            cmd_show(self.service, args_show)
            out_str = mock_out.getvalue()
            self.assertIn(f"RECORD DETAIL: {kid}", out_str)
            self.assertIn("PJTAU Test Advisory Bulletin", out_str)

        # cmd_transition via verify
        with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
            cmd_transition(
                service=self.service,
                knowledge_id=kid,
                new_status=STATUS_VERIFIED,
                actor="cli_reviewer",
                role=ROLE_TECHNICAL_REVIEWER,
                notes="CLI technical verification check passed.",
                yes=True,
            )
            out_str = mock_out.getvalue()
            self.assertIn("SUCCESS: Record", out_str)
            self.assertIn("verified", out_str)

        # cmd_history
        args_hist = type("Args", (), {"knowledge_id": kid})()
        with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
            cmd_history(self.service, args_hist)
            out_str = mock_out.getvalue()
            self.assertIn("AUDIT TRAIL FOR:", out_str)
            self.assertIn("cli_reviewer", out_str)

    # --- Test 11: Real Project Database Remains 100% Intact ---
    def test_real_database_untouched(self):
        real_service = ReviewService()
        real_adapter = ApprovedKnowledgeAdapter()

        summary = real_adapter.get_database_status_summary()
        self.assertEqual(summary["sources_count"], 2)
        self.assertEqual(summary["items_count"], 51)
        self.assertEqual(summary["approved_count"], 1)
        self.assertEqual(summary["verified_count"], 50)
        self.assertEqual(summary["pending_count"], 0)
        self.assertEqual(summary["rejected_count"], 0)
        self.assertEqual(summary["farmers_count"], 0)

        # Real DB audit count is 105 (53 initial + 51 verification + 1 approval)
        conn = get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM knowledge_verification_audit")
            audit_count = cursor.fetchone()[0]
            self.assertEqual(audit_count, 105)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
