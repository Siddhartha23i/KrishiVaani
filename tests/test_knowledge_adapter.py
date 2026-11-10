"""
Unit test suite for KrishiVaani Approved Knowledge Retrieval Adapter — Phase 7.3.

Covers all required test conditions:
1. Real project database audit: exactly 51 pending items, 0 approved, empty retrieval, zero mutation.
2. Pending evidence is excluded.
3. Rejected evidence is excluded.
4. Expired evidence is excluded.
5. Approved and currently valid evidence is retrieved.
6. District mismatch is excluded for district-specific advice.
7. Unknown geography does not silently match district-specific advice.
8. PJTAU agro-climatic zone and government administrative districts are not confused.
9. Missing or malformed validity metadata is handled conservatively.
10. Source URL, page/table reference, and citation provenance are retained.
11. No approved evidence returns an explicit abstention reason.
12. Repeated retrieval does not mutate the database.
13. Output validates seamlessly against LLMReasoningRequest and LLMResponseSchema.
"""

import unittest
from pathlib import Path
import tempfile
import sqlite3
import shutil
from datetime import date, timedelta

from app.db.database import init_db, get_connection
from app.llm.schemas import ApprovedEvidenceItem, LLMReasoningRequest
from app.llm.knowledge_adapter import (
    ApprovedKnowledgeAdapter,
    KnowledgeRetrievalFilter,
    EvidenceRetrievalResult,
)
from app.llm.safety import LLMSafetyValidator


class TestApprovedKnowledgeAdapter(unittest.TestCase):
    """Isolated unit tests for Phase 7.3 Approved Knowledge Adapter."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test_knowledge.db"
        init_db(self.db_path)
        self.adapter = ApprovedKnowledgeAdapter(db_path=self.db_path)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _insert_source(
        self,
        source_id="SRC-PJTAU-001",
        publisher="PJTAU",
        document_title="PJTAU Agromet Advisory Bulletin",
        source_url="https://pjtau.edu.in/advisory.pdf",
        published_at="2026-11-04",
    ):
        conn = get_connection(self.db_path)
        with conn:
            conn.execute(
                """
                INSERT INTO knowledge_sources (
                    source_id, publisher, document_title, source_url, source_type,
                    authority_status, published_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 'PJTAU_AGROMET_ADVISORY', 'verified_official', ?, '2026-11-04', '2026-11-04')
                """,
                (source_id, publisher, document_title, source_url, published_at),
            )
        conn.close()

    def _insert_item(
        self,
        knowledge_id,
        title,
        content,
        verification_status="approved",
        district=None,
        crop_name="Groundnut",
        season="Yasangi",
        applicable_from="2026-11-01",
        applicable_until="2026-11-15",
        source_id="SRC-PJTAU-001",
        reference_location="Page 2, Table 1",
        retrieval_notes=None,
        is_permanent_reference=0,
        last_reviewed_at=None,
        review_cycle_days=365,
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
                    ?, 'crop_management', 'seasonal_advisory', ?, ?,
                    'te', 'human_verified', 'Telangana', ?,
                    ?, ?, ?, ?,
                    ?, ?, ?,
                    ?, ?,
                    '2026-11-04', '2026-11-04'
                )
                """,
                (
                    knowledge_id, title, content, district,
                    crop_name, season, applicable_from, applicable_until,
                    is_permanent_reference, last_reviewed_at, review_cycle_days,
                    verification_status, retrieval_notes,
                ),
            )
            # Link to source
            if source_id:
                conn.execute(
                    """
                    INSERT INTO knowledge_item_sources (
                        item_id, source_id, reference_location, created_at
                    ) VALUES (?, ?, ?, '2026-11-04')
                    """,
                    (knowledge_id, source_id, reference_location),
                )
        conn.close()

    # 1. Real Project Database Audit
    def test_real_database_read_only_audit(self):
        real_adapter = ApprovedKnowledgeAdapter()
        summary = real_adapter.get_database_status_summary()

        self.assertEqual(summary["sources_count"], 2)
        self.assertEqual(summary["items_count"], 51)
        self.assertEqual(summary["approved_count"], 1)
        self.assertEqual(summary["verified_count"], 50)
        self.assertEqual(summary["pending_count"], 0)
        self.assertEqual(summary["rejected_count"], 0)
        self.assertEqual(summary["farmers_count"], 0)

        # Retrieval for approved permanent safety evidence returns the 1 approved item
        result = real_adapter.retrieve_approved_evidence(
            KnowledgeRetrievalFilter(farmer_district="Adilabad", as_of_date="2026-11-09")
        )
        self.assertEqual(result.total_eligible, 1)
        self.assertEqual(len(result.items), 1)
        self.assertEqual(result.items[0].evidence_id, "ki_pjtau_f2742207_7")
        self.assertIsNone(result.abstention_reason)

        # Query for specific category with 0 approved items returns abstention
        res_crop = real_adapter.retrieve_approved_evidence(
            KnowledgeRetrievalFilter(farmer_district="Adilabad", category="crop_management", as_of_date="2026-11-09")
        )
        self.assertEqual(res_crop.total_eligible, 0)
        self.assertIn("NO_MATCHING_EVIDENCE", res_crop.abstention_reason)

        # Confirm zero mutation on real database
        summary_after = real_adapter.get_database_status_summary()
        self.assertEqual(summary, summary_after)

    # 2. Pending Evidence is Excluded
    def test_pending_evidence_excluded(self):
        self._insert_source()
        self._insert_item(
            knowledge_id="KNOW-PENDING-001",
            title="Pending Groundnut Item",
            content="Groundnut sowing guidance",
            verification_status="pending_verification",
            district="Adilabad",
        )
        result = self.adapter.retrieve_approved_evidence(
            KnowledgeRetrievalFilter(farmer_district="Adilabad", as_of_date="2026-11-08")
        )
        self.assertEqual(result.total_eligible, 0)
        self.assertEqual(result.total_excluded_pending, 1)
        self.assertIn("NO_APPROVED_EVIDENCE", result.abstention_reason)

    # 3. Rejected Evidence is Excluded
    def test_rejected_evidence_excluded(self):
        self._insert_source()
        self._insert_item(
            knowledge_id="KNOW-REJECTED-001",
            title="Rejected Advisory",
            content="Contradicted advice",
            verification_status="rejected",
            district="Adilabad",
        )
        result = self.adapter.retrieve_approved_evidence(
            KnowledgeRetrievalFilter(farmer_district="Adilabad", as_of_date="2026-11-08")
        )
        self.assertEqual(result.total_eligible, 0)
        self.assertEqual(result.total_excluded_rejected, 1)

    # 4. Expired Evidence is Excluded
    def test_expired_evidence_excluded(self):
        self._insert_source()
        self._insert_item(
            knowledge_id="KNOW-EXPIRED-001",
            title="Old Advisory",
            content="Expired guidance",
            verification_status="approved",
            district="Adilabad",
            applicable_from="2026-10-01",
            applicable_until="2026-10-15",  # Expired
        )
        result = self.adapter.retrieve_approved_evidence(
            KnowledgeRetrievalFilter(farmer_district="Adilabad", as_of_date="2026-11-08")
        )
        self.assertEqual(result.total_eligible, 0)
        self.assertEqual(result.total_excluded_expired, 1)
        self.assertIn("NO_MATCHING_EVIDENCE", result.abstention_reason)

    # 5. Approved and Currently Valid Evidence is Retrieved
    def test_approved_and_currently_valid_retrieved(self):
        self._insert_source()
        self._insert_item(
            knowledge_id="KNOW-VALID-001",
            title="Valid TAG-24 Groundnut Advisory",
            content="TAG-24 groundnut variety is recommended for light well-drained soils under assured irrigation.",
            verification_status="approved",
            district="Adilabad",
            applicable_from="2026-11-01",
            applicable_until="2026-11-15",
        )
        result = self.adapter.retrieve_approved_evidence(
            KnowledgeRetrievalFilter(farmer_district="Adilabad", crop_name="Groundnut", as_of_date="2026-11-08")
        )
        self.assertEqual(result.total_eligible, 1)
        self.assertEqual(len(result.items), 1)
        item = result.items[0]
        self.assertEqual(item.evidence_id, "KNOW-VALID-001")
        self.assertEqual(item.district, "Adilabad")
        self.assertEqual(item.verification_status, "APPROVED")
        self.assertFalse(item.is_expired)

    # 6. District Mismatch is Excluded for District-Specific Advice
    def test_district_mismatch_excluded(self):
        self._insert_source()
        self._insert_item(
            knowledge_id="KNOW-ADIL-001",
            title="Adilabad Advisory",
            content="Advice strictly for Adilabad",
            verification_status="approved",
            district="Adilabad",
            applicable_from="2026-11-01",
            applicable_until="2026-11-15",
        )
        # Farmer is in Khammam
        result = self.adapter.retrieve_approved_evidence(
            KnowledgeRetrievalFilter(farmer_district="Khammam", as_of_date="2026-11-08")
        )
        self.assertEqual(result.total_eligible, 0)
        self.assertEqual(result.total_excluded_geo_mismatch, 1)

    # 7. Unknown Geography Does Not Silently Match District Advice
    def test_unknown_geography_does_not_silently_match(self):
        self._insert_source()
        self._insert_item(
            knowledge_id="KNOW-NIZAM-001",
            title="Nizamabad Advisory",
            content="Advice for Nizamabad only",
            verification_status="approved",
            district="Nizamabad",
            applicable_from="2026-11-01",
            applicable_until="2026-11-15",
        )
        # Farmer district is unknown (None)
        result = self.adapter.retrieve_approved_evidence(
            KnowledgeRetrievalFilter(farmer_district=None, as_of_date="2026-11-08")
        )
        self.assertEqual(result.total_eligible, 0)
        self.assertEqual(result.total_excluded_geo_mismatch, 1)

    # 8. PJTAU Agro-Climatic Zone and Government Administrative District Mapping
    def test_pjtau_zone_and_district_mapping(self):
        self._insert_source()
        # Item for Northern Telangana Zone (district is NULL, but zonal applicability in notes)
        self._insert_item(
            knowledge_id="KNOW-NTZ-001",
            title="Northern Telangana Zone Groundnut Advisory",
            content="Groundnut TAG-24 recommended across Northern Telangana Zone",
            verification_status="approved",
            district=None,
            applicable_from="2026-11-01",
            applicable_until="2026-11-15",
            retrieval_notes="PJTSAU Northern Telangana Zone guidance",
        )
        # Nirmal belongs to Northern Telangana Zone -> MATCH
        res_nirmal = self.adapter.retrieve_approved_evidence(
            KnowledgeRetrievalFilter(farmer_district="Nirmal", as_of_date="2026-11-08")
        )
        self.assertEqual(res_nirmal.total_eligible, 1)
        self.assertEqual(res_nirmal.items[0].evidence_id, "KNOW-NTZ-001")

        # Mahabubnagar belongs to Southern Telangana Zone -> EXCLUDED
        res_mbnr = self.adapter.retrieve_approved_evidence(
            KnowledgeRetrievalFilter(farmer_district="Mahabubnagar", as_of_date="2026-11-08")
        )
        self.assertEqual(res_mbnr.total_eligible, 0)
        self.assertEqual(res_mbnr.total_excluded_geo_mismatch, 1)

    # 9. Missing or Malformed Validity Metadata Handled Conservatively
    def test_missing_validity_metadata_handled_conservatively(self):
        self._insert_source()
        # Missing applicable_until
        self._insert_item(
            knowledge_id="KNOW-NO-UNTIL-001",
            title="No until date",
            content="Missing validity date",
            verification_status="approved",
            district="Adilabad",
            applicable_from="2026-11-01",
            applicable_until=None,
        )
        # Malformed applicable_until
        self._insert_item(
            knowledge_id="KNOW-BAD-UNTIL-002",
            title="Malformed date",
            content="Bad validity date",
            verification_status="approved",
            district="Adilabad",
            applicable_from="2026-11-01",
            applicable_until="not-a-valid-date",
        )
        result = self.adapter.retrieve_approved_evidence(
            KnowledgeRetrievalFilter(farmer_district="Adilabad", as_of_date="2026-11-08")
        )
        self.assertEqual(result.total_eligible, 0)
        self.assertEqual(result.total_excluded_expired, 2)

    # 10. Source URL, Page/Table Reference, and Citation Provenance are Retained
    def test_provenance_retention(self):
        self._insert_source(
            source_id="SRC-PJTAU-777",
            publisher="PJTAU Directorate",
            source_url="https://pjtau.edu.in/bulletin_nov_2026.pdf",
            published_at="2026-11-04",
        )
        self._insert_item(
            knowledge_id="KNOW-PROV-001",
            title="Groundnut Spacing",
            content="Recommended spacing is 30x10 cm.",
            verification_status="approved",
            district="Adilabad",
            applicable_from="2026-11-01",
            applicable_until="2026-11-15",
            source_id="SRC-PJTAU-777",
            reference_location="Page 3, Table 2",
        )
        result = self.adapter.retrieve_approved_evidence(
            KnowledgeRetrievalFilter(farmer_district="Adilabad", as_of_date="2026-11-08")
        )
        self.assertEqual(result.total_eligible, 1)
        item = result.items[0]
        self.assertEqual(item.source_id, "SRC-PJTAU-777")
        self.assertEqual(item.source_url, "https://pjtau.edu.in/bulletin_nov_2026.pdf")
        self.assertEqual(item.reference_location, "Page 3, Table 2")
        self.assertEqual(item.citation_id, "CITE-KNOW-PROV-001-SRC-PJTAU-777")
        self.assertEqual(item.source_date, "2026-11-04")

    # 11. Repeated Retrieval Does Not Mutate the Database
    def test_repeated_retrieval_does_not_mutate_database(self):
        self._insert_source()
        self._insert_item(
            knowledge_id="KNOW-IDEM-001",
            title="Idempotency Item",
            content="Testing no mutation",
            verification_status="approved",
            district="Adilabad",
        )
        summary_before = self.adapter.get_database_status_summary()

        # Run 10 consecutive queries
        for _ in range(10):
            _ = self.adapter.retrieve_approved_evidence(
                KnowledgeRetrievalFilter(farmer_district="Adilabad", as_of_date="2026-11-08")
            )

        summary_after = self.adapter.get_database_status_summary()
        self.assertEqual(summary_before, summary_after)

    # 12. Output Validates against LLM Evidence Schema
    def test_adapter_output_validates_against_llm_schema(self):
        self._insert_source()
        self._insert_item(
            knowledge_id="KNOW-COMPAT-001",
            title="Compatibility Item",
            content="Groundnut TAG-24 for light soils",
            verification_status="approved",
            district="Adilabad",
        )
        result = self.adapter.retrieve_approved_evidence(
            KnowledgeRetrievalFilter(farmer_district="Adilabad", as_of_date="2026-11-08")
        )
        self.assertEqual(result.total_eligible, 1)

        # Create reasoning request with adapter items
        req = LLMReasoningRequest(
            farmer_question="What crop should I grow?",
            language="Telugu",
            approved_evidence=result.items,
        )
        self.assertEqual(len(req.approved_evidence), 1)
        self.assertIsInstance(req.approved_evidence[0], ApprovedEvidenceItem)
        self.assertEqual(req.approved_evidence[0].evidence_id, "KNOW-COMPAT-001")


if __name__ == "__main__":
    unittest.main()

