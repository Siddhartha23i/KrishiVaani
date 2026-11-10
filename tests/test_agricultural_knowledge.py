"""
Automated test suite for Agricultural Knowledge Base (Phase 5 & 5.1).
Tests explicit knowledge types, review policy enforcement, strengthened verification gates,
temporal validity, calendar-aware seasonal resolution, and database preservation.
"""

import sys
import tempfile
import unittest
from datetime import datetime, date, timezone, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from fastapi.testclient import TestClient
from app.core.config import settings
from app.db.database import init_db, get_connection
from app.main import app
from app.knowledge.models import (
    AuthorityStatus,
    VerificationStatus,
    TranslationStatus,
    KnowledgeCategory,
    KnowledgeType,
)
from app.knowledge.schemas import KnowledgeSearchFilterSchema
from app.knowledge.service import (
    KnowledgeService,
    KnowledgeVerificationError,
    SourceProvenanceMissingError,
    IST_ZONE,
)
from app.knowledge.source_registry import SourceRegistry, SourceValidationError
from app.knowledge.season_calendar import (
    AgriculturalCalendar,
    CropSowingWindow,
    EvidenceStatus,
    DistrictZoneMapping,
    TELANGANA_33_DISTRICTS,
    TELANGANA_OFFICIAL_SEASONS,
)
from app.knowledge.geography import (
    AdministrativeDistrict,
    PJTSAUAgroClimaticZone,
    IMDAmfuRecord,
    AmfuStatus,
    AmfuCoverageStatus,
    AmfuAssignmentType,
    DistrictAmfuAssignment,
    PlanningHorizon,
    PJTSAU_AGRO_CLIMATIC_ZONES,
    IMD_AMFU_RECORDS,
    HISTORICAL_DAMU_RECORDS,
    DISTRICT_AMFU_ASSIGNMENTS,
    get_district_amfu_assignment,
    get_active_amfu_records,
    get_historical_damu_records,
    classify_planning_horizon,
    get_planning_horizon_description,
    SAFETY_RULE_FORECAST_ALONE_CANNOT_TRIGGER_ADVICE,
    REQUIRED_AGRONOMIC_CONTEXT_FACTORS,
    AdvisoryTriggerSafetyPolicy,
)


class TestAgriculturalKnowledgeSuite(unittest.TestCase):
    """
    Comprehensive verification suite for Phase 5.1 Agricultural Knowledge Base.
    """

    @classmethod
    def setUpClass(cls):
        # Create an isolated temporary SQLite database for testing
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.test_db_path = Path(cls.temp_dir.name) / "test_knowledge_51.db"
        cls.original_db_path = settings.DATABASE_PATH
        settings.DATABASE_PATH = cls.test_db_path

        # Initialize test database schema
        init_db(cls.test_db_path)
        cls.client = TestClient(app)
        cls.service = KnowledgeService(db_path=cls.test_db_path)
        cls.registry = SourceRegistry(db_path=cls.test_db_path)

    @classmethod
    def tearDownClass(cls):
        # Restore configuration and cleanup temporary database
        settings.DATABASE_PATH = cls.original_db_path
        cls.temp_dir.cleanup()

    def setUp(self):
        # Clean knowledge tables between tests for isolation
        conn = get_connection(self.test_db_path)
        with conn:
            conn.execute("DELETE FROM knowledge_verification_audit;")
            conn.execute("DELETE FROM knowledge_item_sources;")
            conn.execute("DELETE FROM knowledge_items;")
            conn.execute("DELETE FROM knowledge_sources;")
        conn.close()

    # -------------------------------------------------------------------------
    # Helper to register and approve a genuine test source
    # -------------------------------------------------------------------------
    def _create_approved_source(
        self,
        publisher="PJTSAU",
        doc_title="PJTSAU Zonal Guidelines 2026",
        url="https://pjtsau.edu.in/agronomy/crop-guidelines.pdf",
    ):
        src = self.registry.register_source(
            publisher=publisher,
            document_title=doc_title,
            source_type="advisory",
            source_url=url,
            authority_status=AuthorityStatus.APPROVED,
            reviewed_by="Dr. S. Reddy, Agronomist",
            review_notes="Verified against official university published bulletin.",
        )
        return src

    # -------------------------------------------------------------------------
    # 1. Static Reference with Review Policy (No fixed expiry needed)
    # -------------------------------------------------------------------------
    def test_01_static_reference_with_policy(self):
        """Static reference explicitly marked permanent with review cycle can be verified and retrieved."""
        src = self._create_approved_source()

        ingested = self.service.ingest_item(
            category=KnowledgeCategory.CROP_SELECTION,
            knowledge_type=KnowledgeType.STATIC_REFERENCE,
            title="Black Cotton Soil Moisture Profile",
            content="Deep black cotton soils have high clay content and high water holding capacity.",
            source_id=src.source_id,
            reference_location="Page 12, Chapter 2",
            is_permanent_reference=True,
            review_cycle_days=365,
            last_reviewed_at="2026-01-15T00:00:00Z",
            soil_type="Black cotton",
            state="Telangana",
        )

        verified = self.service.verify_item(
            ingested.item.knowledge_id,
            verified_by="Senior Soil Scientist",
        )
        self.assertEqual(verified.item.verification_status, VerificationStatus.VERIFIED.value)
        self.assertTrue(verified.item.is_permanent_reference)

        # Retrieval as-of any date should return static reference
        res = self.service.search_guidance(
            KnowledgeSearchFilterSchema(
                knowledge_type="static_reference",
                soil_type="Black cotton",
                as_of_date="2026-11-05",
            )
        )
        self.assertEqual(res.total_matches, 1)
        self.assertEqual(res.items[0].title, "Black Cotton Soil Moisture Profile")
        self.assertIn("Permanent reference", res.items[0].retrieval_applicability_explanation)

    # -------------------------------------------------------------------------
    # 2. Static Reference Without Permanent Classification Fails Verification
    # -------------------------------------------------------------------------
    def test_02_static_reference_without_classification_rejected(self):
        """Static reference item without is_permanent_reference=True fails verification."""
        src = self._create_approved_source()

        ingested = self.service.ingest_item(
            category=KnowledgeCategory.CROP_SELECTION,
            knowledge_type=KnowledgeType.STATIC_REFERENCE,
            title="Unclassified Soil Note",
            content="Soil notes.",
            source_id=src.source_id,
            reference_location="Page 5",
            is_permanent_reference=False,  # Not marked permanent
            state="Telangana",
        )

        with self.assertRaises(KnowledgeVerificationError) as ctx:
            self.service.verify_item(ingested.item.knowledge_id)
        self.assertIn("is_permanent_reference=true", str(ctx.exception).lower())

    # -------------------------------------------------------------------------
    # 3. Seasonal Guidance Without Season Fails Verification
    # -------------------------------------------------------------------------
    def test_03_seasonal_guidance_without_season_rejected(self):
        """Seasonal guidance missing season parameter fails verification."""
        src = self._create_approved_source()

        ingested = self.service.ingest_item(
            category=KnowledgeCategory.CROP_SELECTION,
            knowledge_type=KnowledgeType.SEASONAL_GUIDANCE,
            title="Unspecified Season Sowing",
            content="Sow seeds properly.",
            source_id=src.source_id,
            reference_location="Section 3",
            season=None,  # Missing season
            applicable_until="2026-12-31",
            state="Telangana",
        )

        with self.assertRaises(KnowledgeVerificationError) as ctx:
            self.service.verify_item(ingested.item.knowledge_id)
        self.assertIn("season applicability is mandatory", str(ctx.exception).lower())

    # -------------------------------------------------------------------------
    # 4. Seasonal Guidance Without Validity Boundary Fails Verification
    # -------------------------------------------------------------------------
    def test_04_seasonal_guidance_without_validity_rejected(self):
        """Seasonal guidance with applicable_until=None fails verification."""
        src = self._create_approved_source()

        ingested = self.service.ingest_item(
            category=KnowledgeCategory.CROP_SELECTION,
            knowledge_type=KnowledgeType.SEASONAL_GUIDANCE,
            title="Kharif Sowing Without Validity Expiry",
            content="Sow between June 15 and July 15.",
            source_id=src.source_id,
            reference_location="Table 1.1",
            season="Kharif",
            applicable_until=None,  # Missing expiry
            state="Telangana",
        )

        with self.assertRaises(KnowledgeVerificationError) as ctx:
            self.service.verify_item(ingested.item.knowledge_id)
        self.assertIn("validity expiry (applicable_until) is mandatory", str(ctx.exception).lower())

    # -------------------------------------------------------------------------
    # 5. Expired Seasonal Guidance Is Excluded from Retrieval
    # -------------------------------------------------------------------------
    def test_05_expired_seasonal_guidance_excluded(self):
        """Kharif sowing guidance with past applicable_until is excluded on Nov 5, 2026."""
        src = self._create_approved_source()

        ingested = self.service.ingest_item(
            category=KnowledgeCategory.CROP_SELECTION,
            knowledge_type=KnowledgeType.SEASONAL_GUIDANCE,
            title="Kharif Cotton Sowing Window",
            content="Sow cotton between June 15 and July 15.",
            source_id=src.source_id,
            reference_location="Page 14, Table 2.1",
            crop_name="Cotton",
            season="Kharif",
            season_year=2026,
            applicable_from="2026-06-15",
            applicable_until="2026-07-15",  # Expired in July
            state="Telangana",
        )
        self.service.verify_item(ingested.item.knowledge_id)

        # Query as of November 5, 2026
        res = self.service.search_guidance(
            KnowledgeSearchFilterSchema(
                crop_name="Cotton",
                season="Kharif",
                as_of_date="2026-11-05",
            )
        )
        self.assertEqual(res.total_matches, 0)
        self.assertEqual(res.items, [])

    # -------------------------------------------------------------------------
    # 6. Current Seasonal Guidance Is Retrievable
    # -------------------------------------------------------------------------
    def test_06_current_seasonal_guidance_retrievable(self):
        """Active Rabi season guidance is retrievable on Nov 5, 2026."""
        src = self._create_approved_source()

        ingested = self.service.ingest_item(
            category=KnowledgeCategory.CROP_SELECTION,
            knowledge_type=KnowledgeType.SEASONAL_GUIDANCE,
            title="Rabi Bengal Gram Sowing Window",
            content="Optimum sowing window for Yasangi/Rabi Bengal Gram is October 15 to November 15.",
            source_id=src.source_id,
            reference_location="Page 28, Section 4.2",
            crop_name="Bengal Gram",
            season="Rabi",
            season_year=2026,
            applicable_from="2026-10-15",
            applicable_until="2026-11-30",
            state="Telangana",
            district="Medchal-Malkajgiri",
        )
        self.service.verify_item(ingested.item.knowledge_id)

        # Query on Nov 5, 2026
        res = self.service.search_guidance(
            KnowledgeSearchFilterSchema(
                crop_name="Bengal Gram",
                district="Medchal-Malkajgiri",
                as_of_date="2026-11-05",
            )
        )
        self.assertEqual(res.total_matches, 1)
        self.assertEqual(res.items[0].crop_name, "Bengal Gram")
        self.assertEqual(res.items[0].season, "Rabi")

    # -------------------------------------------------------------------------
    # 7. Future Season Planning
    # -------------------------------------------------------------------------
    def test_07_future_season_planning(self):
        """Farmer planning ahead for upcoming Summer season during Rabi."""
        src = self._create_approved_source()

        ingested = self.service.ingest_item(
            category=KnowledgeCategory.CROP_SELECTION,
            knowledge_type=KnowledgeType.SEASONAL_GUIDANCE,
            title="Summer Groundnut Selection",
            content="TAG-24 groundnut recommended for irrigated summer conditions.",
            source_id=src.source_id,
            reference_location="Page 40",
            crop_name="Groundnut",
            season="Summer",
            season_year=2027,
            applicable_from="2027-01-01",
            applicable_until="2027-05-31",
            state="Telangana",
        )
        self.service.verify_item(ingested.item.knowledge_id)

        # Farmer queries upcoming planning horizon as of Nov 5, 2026
        calendar = AgriculturalCalendar("Telangana")
        target_season, target_year, needed, expl = calendar.resolve_planning_horizon(
            planning_horizon="upcoming",
            query_season=None,
            as_of_date=date(2026, 11, 5),
        )
        self.assertEqual(target_season, "Summer")
        self.assertFalse(needed)

    # -------------------------------------------------------------------------
    # 8. Time-Bound Advisory With Valid Expiry
    # -------------------------------------------------------------------------
    def test_08_time_bound_advisory_with_valid_expiry(self):
        """Short-term pest alert with valid expiry is retrievable."""
        src = self._create_approved_source(
            doc_title="PJTSAU Agromet Weather Bulletin",
            url="https://pjtsau.edu.in/bulletin/agromet-nov2026.pdf",
        )

        ingested = self.service.ingest_item(
            category=KnowledgeCategory.AGRICULTURAL_ADVISORY,
            knowledge_type=KnowledgeType.TIME_BOUND_ADVISORY,
            title="Fall Armyworm Alert in Rabi Maize",
            content="Scout maize whorls for fall armyworm larvae. Apply neem formulation if infestation is below ETL.",
            source_id=src.source_id,
            reference_location="Page 2, Advisory Note 1",
            crop_name="Maize",
            crop_stage="Vegetative",
            applicable_from="2026-11-01",
            applicable_until="2026-11-15",
            state="Telangana",
        )
        self.service.verify_item(ingested.item.knowledge_id)

        res = self.service.search_guidance(
            KnowledgeSearchFilterSchema(
                crop_name="Maize",
                as_of_date="2026-11-05",
            )
        )
        self.assertEqual(res.total_matches, 1)
        self.assertEqual(res.items[0].knowledge_type, "time_bound_advisory")

    # -------------------------------------------------------------------------
    # 9. Time-Bound Advisory Without Expiry Fails Verification
    # -------------------------------------------------------------------------
    def test_09_time_bound_advisory_without_expiry_rejected(self):
        """Time-bound advisory missing applicable_until fails verification."""
        src = self._create_approved_source()

        ingested = self.service.ingest_item(
            category=KnowledgeCategory.AGRICULTURAL_ADVISORY,
            knowledge_type=KnowledgeType.TIME_BOUND_ADVISORY,
            title="Indefinite Pest Alert",
            content="Pest attack alert.",
            source_id=src.source_id,
            reference_location="Page 1",
            applicable_until=None,  # Missing expiry
            state="Telangana",
        )

        with self.assertRaises(KnowledgeVerificationError) as ctx:
            self.service.verify_item(ingested.item.knowledge_id)
        self.assertIn("explicit validity expiry (applicable_until) is mandatory", str(ctx.exception).lower())

    # -------------------------------------------------------------------------
    # 10. Historical Advisory Exclusion
    # -------------------------------------------------------------------------
    def test_10_historical_advisory_exclusion(self):
        """Historical advisory that expired last week is excluded."""
        src = self._create_approved_source()

        ingested = self.service.ingest_item(
            category=KnowledgeCategory.AGRICULTURAL_ADVISORY,
            knowledge_type=KnowledgeType.TIME_BOUND_ADVISORY,
            title="Past Heavy Rain Warning",
            content="Drain excess water.",
            source_id=src.source_id,
            reference_location="Page 1",
            applicable_from="2026-10-20",
            applicable_until="2026-10-25",  # Expired in October
            state="Telangana",
        )
        self.service.verify_item(ingested.item.knowledge_id)

        res = self.service.search_guidance(
            KnowledgeSearchFilterSchema(
                category="agricultural_advisory",
                as_of_date="2026-11-05",
            )
        )
        self.assertEqual(res.total_matches, 0)

    # -------------------------------------------------------------------------
    # 11. Missing Publication Date Handling
    # -------------------------------------------------------------------------
    def test_11_missing_publication_date_handling(self):
        """Item without publication_date can be verified if valid expiry exists; metadata preserves None."""
        src = self._create_approved_source()

        ingested = self.service.ingest_item(
            category=KnowledgeCategory.CROP_MANAGEMENT,
            knowledge_type=KnowledgeType.TIME_BOUND_ADVISORY,
            title="Weed Management Notice",
            content="Hand weeding recommended within 30 days of sowing.",
            source_id=src.source_id,
            reference_location="Section 2.3",
            publication_date=None,  # Missing publication date
            applicable_from="2026-11-01",
            applicable_until="2026-11-30",
            state="Telangana",
        )
        verified = self.service.verify_item(ingested.item.knowledge_id)
        self.assertEqual(verified.item.verification_status, "verified")

        res = self.service.search_guidance(
            KnowledgeSearchFilterSchema(as_of_date="2026-11-05")
        )
        self.assertEqual(res.total_matches, 1)
        self.assertIsNone(res.items[0].publication_date)

    # -------------------------------------------------------------------------
    # 12. Missing Citation Location Fails Verification
    # -------------------------------------------------------------------------
    def test_12_missing_citation_location_rejected(self):
        """Item without meaningful reference_location fails verification."""
        src = self._create_approved_source()

        ingested = self.service.ingest_item(
            category=KnowledgeCategory.CROP_SELECTION,
            knowledge_type=KnowledgeType.STATIC_REFERENCE,
            title="Item Without Page Reference",
            content="Good farming practice.",
            source_id=src.source_id,
            reference_location=None,  # Missing citation location
            is_permanent_reference=True,
            review_cycle_days=365,
            state="Telangana",
        )

        with self.assertRaises(KnowledgeVerificationError) as ctx:
            self.service.verify_item(ingested.item.knowledge_id)
        self.assertIn("meaningful citation location", str(ctx.exception).lower())

    # -------------------------------------------------------------------------
    # 13. Unapproved Source Rejection
    # -------------------------------------------------------------------------
    def test_13_unapproved_source_rejected(self):
        """Item linked to a source with PENDING_VERIFICATION cannot be verified."""
        src = self.registry.register_source(
            publisher="PJTSAU",
            document_title="Unreviewed Working Draft",
            source_type="advisory",
            source_url="https://pjtsau.edu.in/draft.pdf",
            authority_status=AuthorityStatus.PENDING_VERIFICATION,
        )

        ingested = self.service.ingest_item(
            category=KnowledgeCategory.CROP_SELECTION,
            knowledge_type=KnowledgeType.STATIC_REFERENCE,
            title="Draft Guidance",
            content="Draft content.",
            source_id=src.source_id,
            reference_location="Page 1",
            is_permanent_reference=True,
            review_cycle_days=365,
            state="Telangana",
        )

        with self.assertRaises(KnowledgeVerificationError) as ctx:
            self.service.verify_item(ingested.item.knowledge_id)
        self.assertIn("none of its linked sources are approved", str(ctx.exception).lower())

    # -------------------------------------------------------------------------
    # 14. Placeholder or Malformed URL Rejected
    # -------------------------------------------------------------------------
    def test_14_placeholder_url_rejected(self):
        """Registering or approving a source with synthetic placeholder URL raises SourceValidationError."""
        with self.assertRaises(SourceValidationError) as ctx1:
            self.registry.register_source(
                publisher="PJTSAU",
                document_title="Placeholder Advisory",
                source_type="advisory",
                source_url="https://example.com/fake.pdf",
            )
        self.assertIn("placeholder/synthetic pattern", str(ctx1.exception).lower())

        with self.assertRaises(SourceValidationError) as ctx2:
            self.registry.register_source(
                publisher="PJTSAU",
                document_title="Malformed Advisory",
                source_type="advisory",
                source_url="ftp://invalid-scheme.pdf",
            )
        self.assertIn("invalid url scheme", str(ctx2.exception).lower())

    # -------------------------------------------------------------------------
    # 15. Source Timeout Not Proof of Nonexistence
    # -------------------------------------------------------------------------
    def test_15_source_timeout_not_proof_of_nonexistence(self):
        """Valid URL syntax is accepted even when offline; timeout does not discard registered source."""
        valid_offline_url = "https://pjtsau.edu.in/official-publications/package-of-practices-2026.pdf"
        src = self.registry.register_source(
            publisher="PJTSAU",
            document_title="Official Package of Practices",
            source_type="advisory",
            source_url=valid_offline_url,
            authority_status=AuthorityStatus.APPROVED,
            reviewed_by="Regional Verification Director",
            review_notes="Offline hardcopy copy verified; online PDF confirmed by university registrar.",
        )
        self.assertIsNotNone(src.source_id)
        self.assertEqual(src.authority_status, "approved")

    # -------------------------------------------------------------------------
    # 16. Rejected Translation Handling
    # -------------------------------------------------------------------------
    def test_16_rejected_translation_handling(self):
        """Item with translation_status=machine_translated_unverified fails verification."""
        src = self._create_approved_source()

        ingested = self.service.ingest_item(
            category=KnowledgeCategory.CROP_SELECTION,
            knowledge_type=KnowledgeType.STATIC_REFERENCE,
            title="యంత్ర అనువాద సలహా",
            content="Unverified machine translation content.",
            source_id=src.source_id,
            reference_location="Page 10",
            translation_status=TranslationStatus.MACHINE_UNVERIFIED,
            is_permanent_reference=True,
            review_cycle_days=365,
            state="Telangana",
        )

        with self.assertRaises(KnowledgeVerificationError) as ctx:
            self.service.verify_item(ingested.item.knowledge_id)
        self.assertIn("machine-translated unverified content", str(ctx.exception).lower())

    # -------------------------------------------------------------------------
    # 17. Geographic Applicability
    # -------------------------------------------------------------------------
    def test_17_geographic_applicability(self):
        """District-specific item prioritized over state-wide; other state excluded."""
        src = self._create_approved_source()

        # District-specific (Warangal)
        item_wgl = self.service.ingest_item(
            category=KnowledgeCategory.CROP_SELECTION,
            knowledge_type=KnowledgeType.TIME_BOUND_ADVISORY,
            title="Warangal Red Gram Sowing Advisory",
            content="Sowing advisory for Warangal zone.",
            source_id=src.source_id,
            reference_location="Page 4",
            applicable_from="2026-11-01",
            applicable_until="2026-11-30",
            state="Telangana",
            district="Warangal",
        )
        self.service.verify_item(item_wgl.item.knowledge_id)

        # State-wide (Telangana)
        item_ts = self.service.ingest_item(
            category=KnowledgeCategory.CROP_SELECTION,
            knowledge_type=KnowledgeType.TIME_BOUND_ADVISORY,
            title="Statewide Pulses Advisory",
            content="Statewide pulses advisory.",
            source_id=src.source_id,
            reference_location="Page 1",
            applicable_from="2026-11-01",
            applicable_until="2026-11-30",
            state="Telangana",
            district=None,
        )
        self.service.verify_item(item_ts.item.knowledge_id)

        # Out-of-state (Karnataka)
        item_ka = self.service.ingest_item(
            category=KnowledgeCategory.CROP_SELECTION,
            knowledge_type=KnowledgeType.TIME_BOUND_ADVISORY,
            title="Karnataka Pulses Advisory",
            content="Raichur pulses advisory.",
            source_id=src.source_id,
            reference_location="Page 2",
            applicable_from="2026-11-01",
            applicable_until="2026-11-30",
            state="Karnataka",
            district="Raichur",
        )
        self.service.verify_item(item_ka.item.knowledge_id)

        res = self.service.search_guidance(
            KnowledgeSearchFilterSchema(
                state="Telangana",
                district="Warangal",
                as_of_date="2026-11-05",
            )
        )
        self.assertEqual(res.total_matches, 2)
        titles = [i.title for i in res.items]
        self.assertEqual(titles[0], "Warangal Red Gram Sowing Advisory")
        self.assertEqual(titles[1], "Statewide Pulses Advisory")
        self.assertNotIn("Karnataka Pulses Advisory", titles)

    # -------------------------------------------------------------------------
    # 18. Current Date Handled in Asia/Kolkata (IST)
    # -------------------------------------------------------------------------
    def test_18_current_date_ist_handling(self):
        """Omitting as_of_date defaults to current date in Asia/Kolkata timezone."""
        src = self._create_approved_source()

        # Item valid today in IST
        today_ist = datetime.now(IST_ZONE).date()
        today_iso = today_ist.isoformat()
        future_iso = (today_ist + timedelta(days=10)).isoformat()

        item = self.service.ingest_item(
            category=KnowledgeCategory.CROP_MANAGEMENT,
            knowledge_type=KnowledgeType.TIME_BOUND_ADVISORY,
            title="Today Active Advisory",
            content="Active advisory for today.",
            source_id=src.source_id,
            reference_location="Page 1",
            applicable_from=today_iso,
            applicable_until=future_iso,
            state="Telangana",
        )
        self.service.verify_item(item.item.knowledge_id)

        # Call search without as_of_date
        res = self.service.search_guidance(
            KnowledgeSearchFilterSchema(category="crop_management")
        )
        self.assertEqual(res.total_matches, 1)
        self.assertEqual(res.as_of_date, today_iso)

    # -------------------------------------------------------------------------
    # 19. Existing Farmer Records Remain Intact
    # -------------------------------------------------------------------------
    def test_19_farmer_records_remain_intact(self):
        """Farmer profiles are completely unperturbed by Phase 5.1 knowledge operations."""
        create_res = self.client.post(
            "/api/v1/farmers",
            json={
                "village_name": "FarmerVillage",
                "pin_code": "500014",
                "location_confirmed": True,
                "consent_given": True,
            },
        )
        self.assertEqual(create_res.status_code, 201)
        farmer_id = create_res.json()["farmer_id"]

        get_res = self.client.get(f"/api/v1/farmers/{farmer_id}")
        self.assertEqual(get_res.status_code, 200)
        self.assertEqual(get_res.json()["village_name"], "FarmerVillage")

    # -------------------------------------------------------------------------
    # 20. Empty Search Returns Clear No-Information Result
    # -------------------------------------------------------------------------
    def test_20_empty_search_clear_message(self):
        """Search yielding zero matches returns total_matches=0 and explicit safe message."""
        res = self.service.search_guidance(
            KnowledgeSearchFilterSchema(
                crop_name="NonExistentCropXYZ",
                as_of_date="2026-11-05",
            )
        )
        self.assertEqual(res.total_matches, 0)
        self.assertEqual(res.items, [])
        self.assertIn("no verified agricultural guidance found", res.message.lower())

    # -------------------------------------------------------------------------
    # 21. Static Reference Excluded After Review Cycle Expires
    # -------------------------------------------------------------------------
    def test_21_static_reference_after_review_cycle_expires(self):
        """A static reference whose review cycle has elapsed is excluded until re-reviewed."""
        src = self._create_approved_source()

        # Ingest static reference reviewed 400 days ago with a 365-day review cycle
        ingested = self.service.ingest_item(
            category=KnowledgeCategory.CROP_SELECTION,
            knowledge_type=KnowledgeType.STATIC_REFERENCE,
            title="Expired Soil Fertility Baseline",
            content="Historical baseline of micronutrient status in red chalka soils.",
            source_id=src.source_id,
            reference_location="Page 40, Table 3",
            is_permanent_reference=True,
            review_cycle_days=365,
            last_reviewed_at="2025-01-01T00:00:00Z",
            soil_type="Red chalka",
            state="Telangana",
        )
        self.service.verify_item(ingested.item.knowledge_id)

        # Query as of Nov 5, 2026 (> 365 days past 2025-01-01)
        res = self.service.search_guidance(
            KnowledgeSearchFilterSchema(
                knowledge_type="static_reference",
                soil_type="Red chalka",
                as_of_date="2026-11-05",
            )
        )
        self.assertEqual(res.total_matches, 0)
        self.assertEqual(res.items, [])

    # -------------------------------------------------------------------------
    # 22. Static Reference with Missing Review Date Excluded
    # -------------------------------------------------------------------------
    def test_22_static_reference_missing_review_date_excluded(self):
        """A static reference without a review date must not silently bypass its review policy."""
        src = self._create_approved_source()

        # Ingest static reference without last_reviewed_at
        ingested = self.service.ingest_item(
            category=KnowledgeCategory.CROP_SELECTION,
            knowledge_type=KnowledgeType.STATIC_REFERENCE,
            title="Soil Texture Reference Without Review Date",
            content="Classification criteria for clay loam texture.",
            source_id=src.source_id,
            reference_location="Page 10",
            is_permanent_reference=True,
            review_cycle_days=365,
            last_reviewed_at=None,
            state="Telangana",
        )
        self.service.verify_item(ingested.item.knowledge_id)

        # Ensure last_reviewed_at is explicitly None in DB
        conn = get_connection(self.test_db_path)
        with conn:
            conn.execute(
                "UPDATE knowledge_items SET last_reviewed_at = NULL WHERE knowledge_id = ?",
                (ingested.item.knowledge_id,),
            )
        conn.close()

        res = self.service.search_guidance(
            KnowledgeSearchFilterSchema(
                knowledge_type="static_reference",
                as_of_date="2026-11-05",
            )
        )
        self.assertEqual(res.total_matches, 0)
        self.assertEqual(res.items, [])

    # -------------------------------------------------------------------------
    # 23. Static Reference Retrievable After Successful Re-Review
    # -------------------------------------------------------------------------
    def test_23_static_reference_after_successful_re_review(self):
        """A static reference due for review becomes active again after formal re-review."""
        src = self._create_approved_source()

        # Ingest expired static reference
        ingested = self.service.ingest_item(
            category=KnowledgeCategory.CROP_SELECTION,
            knowledge_type=KnowledgeType.STATIC_REFERENCE,
            title="Red Soil Deep Tillage Policy",
            content="Deep summer ploughing in red chalka soils increases infiltration.",
            source_id=src.source_id,
            reference_location="Page 25",
            is_permanent_reference=True,
            review_cycle_days=365,
            last_reviewed_at="2025-01-01T00:00:00Z",
            soil_type="Red chalka",
            state="Telangana",
        )
        self.service.verify_item(ingested.item.knowledge_id)

        # Confirm excluded before re-review
        res_before = self.service.search_guidance(
            KnowledgeSearchFilterSchema(
                knowledge_type="static_reference",
                soil_type="Red chalka",
                as_of_date="2026-11-05",
            )
        )
        self.assertEqual(res_before.total_matches, 0)

        # Perform formal re-review
        re_reviewed = self.service.re_review_item(
            knowledge_id=ingested.item.knowledge_id,
            reviewed_by="Dr. K. Rao, Senior Agronomist",
            review_notes="Annual re-certification: verified against PJTSAU 2026 Soil Management Guidelines.",
            new_review_cycle_days=365,
        )
        self.assertEqual(re_reviewed.item.verification_status, VerificationStatus.VERIFIED.value)
        self.assertEqual(re_reviewed.item.verified_by, "Dr. K. Rao, Senior Agronomist")

        # Query again as of Nov 5, 2026: now retrievable!
        res_after = self.service.search_guidance(
            KnowledgeSearchFilterSchema(
                knowledge_type="static_reference",
                soil_type="Red chalka",
                as_of_date="2026-11-05",
            )
        )
        self.assertEqual(res_after.total_matches, 1)
        self.assertEqual(res_after.items[0].title, "Red Soil Deep Tillage Policy")

    # -------------------------------------------------------------------------
    # 24. Future-Effective Advisory Exclusion
    # -------------------------------------------------------------------------
    def test_24_future_effective_advisory_exclusion(self):
        """Future-dated advisories cannot appear as active before their effective start date."""
        src = self._create_approved_source()

        # Ingest advisory effective Dec 1 to Dec 31, 2026
        item = self.service.ingest_item(
            category=KnowledgeCategory.CROP_MANAGEMENT,
            knowledge_type=KnowledgeType.TIME_BOUND_ADVISORY,
            title="Cold Wave Protection for Rabi Vegetables",
            content="Irrigate vegetable plots during evening hours to mitigate cold wave shock.",
            source_id=src.source_id,
            reference_location="Page 15",
            applicable_from="2026-12-01",
            applicable_until="2026-12-31",
            state="Telangana",
        )
        self.service.verify_item(item.item.knowledge_id)

        # Query on Nov 5, 2026 (before effective start date) -> excluded!
        res_early = self.service.search_guidance(
            KnowledgeSearchFilterSchema(
                knowledge_type="time_bound_advisory",
                as_of_date="2026-11-05",
            )
        )
        self.assertEqual(res_early.total_matches, 0)
        self.assertEqual(res_early.items, [])

        # Query on Dec 5, 2026 (during effective window) -> active!
        res_active = self.service.search_guidance(
            KnowledgeSearchFilterSchema(
                knowledge_type="time_bound_advisory",
                as_of_date="2026-12-05",
            )
        )
        self.assertEqual(res_active.total_matches, 1)
        self.assertEqual(res_active.items[0].title, "Cold Wave Protection for Rabi Vegetables")

    # -------------------------------------------------------------------------
    # 25. Current Valid Advisory Retrieval
    # -------------------------------------------------------------------------
    def test_25_current_valid_advisory_retrieval(self):
        """Current advisory where applicable_from <= as_of_date <= applicable_until is retrievable."""
        src = self._create_approved_source()

        item = self.service.ingest_item(
            category=KnowledgeCategory.CROP_MANAGEMENT,
            knowledge_type=KnowledgeType.TIME_BOUND_ADVISORY,
            title="November Rabi Pulse Sowing Alert",
            content="Complete sowing of Bengal Gram in Southern Telangana before Nov 15 for optimal yield.",
            source_id=src.source_id,
            reference_location="Advisory Section A",
            applicable_from="2026-11-01",
            applicable_until="2026-11-30",
            state="Telangana",
            district="Mahabubnagar",
        )
        self.service.verify_item(item.item.knowledge_id)

        res = self.service.search_guidance(
            KnowledgeSearchFilterSchema(
                knowledge_type="time_bound_advisory",
                district="Mahabubnagar",
                as_of_date="2026-11-05",
            )
        )
        self.assertEqual(res.total_matches, 1)
        self.assertEqual(res.items[0].title, "November Rabi Pulse Sowing Alert")

    # -------------------------------------------------------------------------
    # 26. Crop-Specific Sowing Window vs General Agricultural Season
    # -------------------------------------------------------------------------
    def test_26_crop_specific_sowing_window_vs_general_season(self):
        """Test distinction between broad DES administrative season and PJTSAU crop sowing window."""
        calendar = AgriculturalCalendar(state="Telangana")

        # Cotton (Kharif): Now PENDING_VERIFICATION — cannot return in_window=True
        # 1. During indicative period (July 1) — but pending, so returns False:
        in_win, win, expl = calendar.is_in_crop_sowing_window("Cotton", date(2026, 7, 1))
        self.assertFalse(in_win)
        self.assertIn("pending official verification", expl.lower())
        self.assertEqual(win.crop_name, "Cotton")

        # 2. Outside window but during Kharif (August 10):
        # General season is Kharif
        gen_season = calendar.resolve_general_season_for_date(date(2026, 8, 10))
        self.assertEqual(gen_season.season_name, "Kharif")
        # Crop-specific sowing window also returns False (pending)
        in_win_aug, _, expl_aug = calendar.is_in_crop_sowing_window("Cotton", date(2026, 8, 10))
        self.assertFalse(in_win_aug)

        # Bengal Gram (Rabi): Now PARTIALLY_SUPPORTED with agro_climatic_zone=None
        # 3. During indicative period (November 5) — partially_supported, so returns False:
        in_win_bg, _, expl_bg = calendar.is_in_crop_sowing_window("Bengal Gram", date(2026, 11, 5), district="Mahabubnagar")
        self.assertFalse(in_win_bg)
        self.assertIn("partially supported", expl_bg.lower())

        # 4. Outside window during Rabi (December 10):
        gen_season_dec = calendar.resolve_general_season_for_date(date(2026, 12, 10))
        self.assertEqual(gen_season_dec.season_name, "Rabi")
        in_win_dec, _, expl_dec = calendar.is_in_crop_sowing_window("Bengal Gram", date(2026, 12, 10))
        self.assertFalse(in_win_dec)

    # -------------------------------------------------------------------------
    # 27. Missing or Unsupported Calendar Source Information
    # -------------------------------------------------------------------------
    def test_27_missing_or_unsupported_calendar_source(self):
        """Unsupported state or crop without calendar citation is handled gracefully without crash."""
        cal_karnataka = AgriculturalCalendar(state="Karnataka")

        # Unsupported state returns None for general season
        gen_season = cal_karnataka.resolve_general_season_for_date(date(2026, 11, 5))
        self.assertIsNone(gen_season)

        # Unsupported crop returns clear explanation
        in_win, win, expl = cal_karnataka.is_in_crop_sowing_window("Quinoa", date(2026, 11, 5))
        self.assertFalse(in_win)
        self.assertIsNone(win)
        self.assertIn("No specific sowing window citation documented", expl)

        # Unsupported state planning horizon evaluation does not fail
        target_s, target_y, clarify, expl = cal_karnataka.resolve_planning_horizon(
            planning_horizon="current", query_season=None, as_of_date=date(2026, 11, 5)
        )
        self.assertFalse(clarify)
        self.assertIsNotNone(target_s)

    # -------------------------------------------------------------------------
    # 28. Reviewer Audit History Preservation & Accountability
    # -------------------------------------------------------------------------
    def test_28_reviewer_audit_history_preservation(self):
        """Preserves immutable audit trail distinguishing test verifiers from official verifiers."""
        src = self._create_approved_source()

        item = self.service.ingest_item(
            category=KnowledgeCategory.CROP_SELECTION,
            knowledge_type=KnowledgeType.STATIC_REFERENCE,
            title="Audit Trail Traceability Item",
            content="Test content for verification audit log.",
            source_id=src.source_id,
            reference_location="Page 1",
            is_permanent_reference=True,
            review_cycle_days=365,
            last_reviewed_at="2026-01-01T00:00:00Z",
            state="Telangana",
        )
        item_id = item.item.knowledge_id

        # 1. Initial verification by test reviewer
        self.service.verify_item(
            knowledge_id=item_id,
            verified_by="[TEST] Automated Test Suite Officer",
            notes="Automated test verification run.",
        )

        trail_1 = self.service.get_item_audit_trail(item_id)
        self.assertEqual(len(trail_1), 1)
        self.assertEqual(trail_1[0]["action"], "verified")
        self.assertEqual(trail_1[0]["actor"], "[TEST] Automated Test Suite Officer")
        self.assertTrue(trail_1[0]["is_test_audit"])
        self.assertEqual(trail_1[0]["actor_role"], "Test Reviewer")

        # 2. Subsequent re-review by official agronomist
        self.service.re_review_item(
            knowledge_id=item_id,
            reviewed_by="Dr. S. K. Sharma, PJTSAU Principal Agronomist",
            review_notes="Official annual recertification under PJTSAU protocol.",
            is_test=False,
        )

        trail_2 = self.service.get_item_audit_trail(item_id)
        self.assertEqual(len(trail_2), 2)
        # Event 1 preserved
        self.assertEqual(trail_2[0]["action"], "verified")
        self.assertTrue(trail_2[0]["is_test_audit"])
        # Event 2 recorded with official status
        self.assertEqual(trail_2[1]["action"], "re_reviewed")
        self.assertEqual(trail_2[1]["actor"], "Dr. S. K. Sharma, PJTSAU Principal Agronomist")
        self.assertFalse(trail_2[1]["is_test_audit"])
        self.assertEqual(trail_2[1]["actor_role"], "Agricultural Verification Officer")

        # 3. Test audit trail API endpoint
        api_res = self.client.get(f"/api/v1/knowledge/{item_id}/audit-trail")
        self.assertEqual(api_res.status_code, 200)
        api_data = api_res.json()
        self.assertEqual(len(api_data["audit_trail"]), 2)
        self.assertEqual(api_data["audit_trail"][0]["actor"], "[TEST] Automated Test Suite Officer")
        self.assertEqual(api_data["audit_trail"][1]["actor"], "Dr. S. K. Sharma, PJTSAU Principal Agronomist")

    # -------------------------------------------------------------------------
    # 29. DES Telangana Kharif & Rabi Classifications (Phase 5.3)
    # -------------------------------------------------------------------------
    def test_29_des_kharif_rabi_classifications(self):
        """DES Telangana defines Kharif and Rabi as official agricultural census seasons."""
        calendar = AgriculturalCalendar(state="Telangana")
        kharif = next(s for s in calendar.official_seasons if s.season_name == "Kharif")
        rabi = next(s for s in calendar.official_seasons if s.season_name == "Rabi")

        self.assertTrue(kharif.is_census_season)
        self.assertEqual(kharif.start_month, 6)
        self.assertEqual(kharif.end_month, 9)
        self.assertIn("Directorate of Economics and Statistics", kharif.institutional_source)

        self.assertTrue(rabi.is_census_season)
        self.assertEqual(rabi.start_month, 10)
        self.assertEqual(rabi.end_month, 3)
        self.assertIn("Directorate of Economics and Statistics", rabi.institutional_source)

    # -------------------------------------------------------------------------
    # 30. Summer / Zaid Distinction (Not a DES Census Season)
    # -------------------------------------------------------------------------
    def test_30_summer_zaid_distinction_not_des_census(self):
        """Summer/Zaid is an optional contingent planning period, not a DES statistical census season."""
        calendar = AgriculturalCalendar(state="Telangana")
        summer = next(s for s in calendar.official_seasons if s.season_name == "Summer")

        self.assertFalse(summer.is_census_season)
        self.assertEqual(summer.start_month, 4)
        self.assertEqual(summer.end_month, 5)
        self.assertIn("PJTSAU", summer.institutional_source)
        self.assertIn("Optional crop-planning", summer.description)

    # -------------------------------------------------------------------------
    # 31. Complete Official List of All 33 Telangana Districts
    # -------------------------------------------------------------------------
    def test_31_all_33_telangana_districts(self):
        """All 33 Telangana districts are present, uniquely identified, and mapped to zones."""
        calendar = AgriculturalCalendar(state="Telangana")
        all_districts = calendar.get_all_districts()

        self.assertEqual(len(all_districts), 33)
        names = {d.district_name for d in all_districts}
        codes = {d.district_code for d in all_districts}
        self.assertEqual(len(names), 33)
        self.assertEqual(len(codes), 33)

        for d in all_districts:
            info = calendar.get_district_info(d.district_name)
            self.assertIsNotNone(info)
            self.assertEqual(info.district_code, d.district_code)

    # -------------------------------------------------------------------------
    # 32. Missing or Unsupported District Handling
    # -------------------------------------------------------------------------
    def test_32_missing_unsupported_district_handling(self):
        """Unsupported districts return None without guessing."""
        calendar = AgriculturalCalendar(state="Telangana")
        self.assertIsNone(calendar.get_district_info("Bangalore"))
        self.assertIsNone(calendar.get_district_zone("Pune"))
        self.assertIsNone(calendar.get_district_zone(""))
        self.assertIsNone(calendar.get_district_zone(None))

    # -------------------------------------------------------------------------
    # 33. District-to-Zone Mapping and Alias Resolution
    # -------------------------------------------------------------------------
    def test_33_district_to_zone_mapping(self):
        """Districts map accurately to Northern (10), Central (11), and Southern (12) zones with alias support."""
        calendar = AgriculturalCalendar(state="Telangana")
        all_d = calendar.get_all_districts()

        ntz = [d for d in all_d if d.agro_climatic_zone == "Northern Telangana Zone"]
        ctz = [d for d in all_d if d.agro_climatic_zone == "Central Telangana Zone"]
        stz = [d for d in all_d if d.agro_climatic_zone == "Southern Telangana Zone"]

        self.assertEqual(len(ntz), 10)
        self.assertEqual(len(ctz), 11)
        self.assertEqual(len(stz), 12)

        # Alias mapping tests
        self.assertEqual(calendar.get_district_zone("Warangal Urban"), "Central Telangana Zone")
        self.assertEqual(calendar.get_district_zone("Warangal Rural"), "Central Telangana Zone")
        self.assertEqual(calendar.get_district_zone("Gadwal"), "Southern Telangana Zone")
        self.assertEqual(calendar.get_district_zone("Asifabad"), "Northern Telangana Zone")
        self.assertEqual(calendar.get_district_zone("Bhupalpally"), "Central Telangana Zone")
        self.assertEqual(calendar.get_district_zone("Kothagudem"), "Central Telangana Zone")
        self.assertEqual(calendar.get_district_zone("Sircilla"), "Northern Telangana Zone")

    # -------------------------------------------------------------------------
    # 34. Crop-Specific Sowing Windows Provenance
    # -------------------------------------------------------------------------
    def test_34_crop_specific_sowing_windows_provenance(self):
        """Crop windows preserve complete provenance: organization, publication year, document, and conditions."""
        calendar = AgriculturalCalendar(state="Telangana")
        crops = ["Cotton", "Red Gram", "Bengal Gram", "Rabi Maize", "Groundnut", "Summer Sesame"]

        for c in crops:
            window = calendar.get_crop_sowing_window(c)
            self.assertIsNotNone(window, f"Crop window missing for {c}")
            self.assertTrue(window.is_current_recommendation)
            self.assertGreaterEqual(window.publication_year, 2011)
            self.assertTrue(len(window.source_organization) > 0)
            self.assertTrue(len(window.document_title) > 0)
            self.assertTrue(len(window.reference_location) > 0)
            self.assertTrue(len(window.water_condition) > 0)
            self.assertIsNotNone(window.evidence_status)
            self.assertTrue(len(window.supporting_text) > 0)

    # -------------------------------------------------------------------------
    # 35. Missing Crop-Window Provenance
    # -------------------------------------------------------------------------
    def test_35_missing_crop_window_provenance(self):
        """Untraceable crop without calendar citation is flagged unavailable/unverified."""
        calendar = AgriculturalCalendar(state="Telangana")
        in_win, win, expl = calendar.is_in_crop_sowing_window("Quinoa", date(2026, 11, 5))
        self.assertFalse(in_win)
        self.assertIsNone(win)
        self.assertIn("No specific sowing window citation documented", expl)

    # -------------------------------------------------------------------------
    # 36. Historical Crop-Window Limitations
    # -------------------------------------------------------------------------
    def test_36_historical_crop_window_limitations(self):
        """Deprecated/historical or unconfirmed crop windows are rejected from active recommendation."""
        calendar = AgriculturalCalendar(state="Telangana")
        calendar.sowing_windows.append(
            CropSowingWindow(
                crop_name="LegacyCrop",
                season="Kharif",
                sowing_start_month=6,
                sowing_start_day=1,
                sowing_end_month=7,
                sowing_end_day=1,
                water_condition="Rainfed",
                soil_type=None,
                agro_climatic_zone=None,
                district=None,
                evidence_status=EvidenceStatus.HISTORICAL_REFERENCE,
                is_verified=False,
                is_current_recommendation=False,
                contingency_notes="Historical recommendation from 2005.",
                source_organization="Historic Agriculture Board",
                document_title="Old Handbook 2005",
                publication_year=2005,
                reference_location="Page 10",
                source_url=None,
                supporting_text="Historical record from 2005 handbook.",
                last_verified_date="2005-01-01",
            )
        )
        in_win, win, expl = calendar.is_in_crop_sowing_window("LegacyCrop", date(2026, 6, 15))
        self.assertFalse(in_win)
        self.assertIn("historical reference", expl.lower())

    # -------------------------------------------------------------------------
    # 37. Current Rabi 2026 Date Range
    # -------------------------------------------------------------------------
    def test_37_current_rabi_2026_date_range(self):
        """On Nov 5, 2026, current Rabi resolves to Oct 2026 – March 2027."""
        calendar = AgriculturalCalendar(state="Telangana")
        res = calendar.resolve_planning_horizon("current", None, date(2026, 11, 5))

        self.assertEqual(res.season, "Rabi")
        self.assertEqual(res.season_year, 2026)
        self.assertEqual(res.season_start_date, "2026-10-01")
        self.assertEqual(res.season_end_date, "2027-03-31")
        self.assertFalse(res.is_future_period)
        self.assertTrue(res.is_census_season)

    # -------------------------------------------------------------------------
    # 38. Upcoming Summer 2027 Date Range
    # -------------------------------------------------------------------------
    def test_38_upcoming_summer_2027_date_range(self):
        """On Nov 5, 2026, upcoming Summer resolves to April–May 2027 (strictly future)."""
        calendar = AgriculturalCalendar(state="Telangana")
        res = calendar.resolve_planning_horizon("upcoming_summer", None, date(2026, 11, 5))

        self.assertEqual(res.season, "Summer")
        self.assertEqual(res.season_year, 2027)
        self.assertEqual(res.season_start_date, "2027-04-01")
        self.assertEqual(res.season_end_date, "2027-05-31")
        self.assertTrue(res.is_future_period)
        self.assertFalse(res.is_census_season)
        self.assertGreater(date.fromisoformat(res.season_start_date), date(2026, 11, 5))

    # -------------------------------------------------------------------------
    # 39. Upcoming Kharif 2027 Planning
    # -------------------------------------------------------------------------
    def test_39_upcoming_kharif_2027_planning(self):
        """On Nov 5, 2026, querying Kharif resolves to Kharif 2027 (June–Sept 2027)."""
        calendar = AgriculturalCalendar(state="Telangana")
        res = calendar.resolve_planning_horizon(None, "Kharif", date(2026, 11, 5))

        self.assertEqual(res.season, "Kharif")
        self.assertEqual(res.season_year, 2027)
        self.assertEqual(res.season_start_date, "2027-06-01")
        self.assertEqual(res.season_end_date, "2027-09-30")
        self.assertTrue(res.is_future_period)
        self.assertTrue(res.is_census_season)
        self.assertGreater(date.fromisoformat(res.season_start_date), date(2026, 11, 5))

    # -------------------------------------------------------------------------
    # 40. Season-Year Consistency Across Calendar Boundaries
    # -------------------------------------------------------------------------
    def test_40_season_year_consistency(self):
        """season_year consistently represents the calendar year when the season commences."""
        calendar = AgriculturalCalendar(state="Telangana")

        # Kharif in July 2026 -> 2026
        k_res = calendar.resolve_planning_horizon("current", None, date(2026, 7, 15))
        self.assertEqual(k_res.season_year, 2026)
        self.assertEqual(k_res.season_start_date, "2026-06-01")

        # Rabi in Nov 2026 -> 2026
        r_nov = calendar.resolve_planning_horizon("current", None, date(2026, 11, 5))
        self.assertEqual(r_nov.season_year, 2026)
        self.assertEqual(r_nov.season_start_date, "2026-10-01")

        # Rabi in Jan 2027 (mid-season) -> 2026 (commenced in Oct 2026)
        r_jan = calendar.resolve_planning_horizon("current", None, date(2027, 1, 15))
        self.assertEqual(r_jan.season_year, 2026)
        self.assertEqual(r_jan.season_start_date, "2026-10-01")
        self.assertEqual(r_jan.season_end_date, "2027-03-31")

        # Summer in April 2027 -> 2027
        s_res = calendar.resolve_planning_horizon("current", None, date(2027, 4, 15))
        self.assertEqual(s_res.season_year, 2027)
        self.assertEqual(s_res.season_start_date, "2027-04-01")

    # -------------------------------------------------------------------------
    # 41. Genuine Source Evidence Required for Recommendation Eligibility (Phase 5.4)
    # -------------------------------------------------------------------------
    def test_41_genuine_source_evidence_required_for_recommendation(self):
        """All crop windows must have explicit evidence classification; pending verification windows cannot provide active guidance."""
        calendar = AgriculturalCalendar(state="Telangana")
        for w in calendar.sowing_windows:
            self.assertIsNotNone(w.evidence_status)
            self.assertTrue(len(w.source_organization) > 0)
            self.assertTrue(len(w.document_title) > 0)
            self.assertTrue(len(w.last_verified_date) > 0)
            self.assertTrue(len(w.supporting_text) > 0)

    # -------------------------------------------------------------------------
    # 42. Unsupported Crop-Window Citations Excluded
    # -------------------------------------------------------------------------
    def test_42_unsupported_crop_window_citations_excluded(self):
        """Unsupported or pending-verification crop windows are excluded from recommendations."""
        calendar = AgriculturalCalendar(state="Telangana")
        calendar.sowing_windows.append(
            CropSowingWindow(
                crop_name="PendingCrop",
                season="Kharif",
                sowing_start_month=6,
                sowing_start_day=1,
                sowing_end_month=7,
                sowing_end_day=1,
                water_condition="Rainfed",
                soil_type=None,
                agro_climatic_zone=None,
                district=None,
                evidence_status=EvidenceStatus.PENDING_VERIFICATION,
                is_verified=False,
                is_current_recommendation=True,
                contingency_notes="Pending official citation confirmation.",
                source_organization="Unknown Agency",
                document_title="Unconfirmed Draft",
                publication_year=2024,
                reference_location="Page 1",
                source_url=None,
                supporting_text="Pending verification text.",
                last_verified_date="2026-11-05",
            )
        )
        in_win, win, expl = calendar.is_in_crop_sowing_window("PendingCrop", date(2026, 6, 15))
        self.assertFalse(in_win)
        self.assertIn("pending official verification", expl.lower())

    # -------------------------------------------------------------------------
    # 43. Research Observations Not Treated as Official Recommendations
    # -------------------------------------------------------------------------
    def test_43_research_observations_not_treated_as_official_recommendations(self):
        """A research observation is excluded from providing actionable sowing guidance."""
        calendar = AgriculturalCalendar(state="Telangana")
        calendar.sowing_windows.append(
            CropSowingWindow(
                crop_name="ExperimentalBarley",
                season="Rabi",
                sowing_start_month=11,
                sowing_start_day=1,
                sowing_end_month=11,
                sowing_end_day=30,
                water_condition="Irrigated",
                soil_type="Loamy",
                agro_climatic_zone="Northern Telangana Zone",
                district=None,
                evidence_status=EvidenceStatus.RESEARCH_OBSERVATION,
                is_verified=True,
                is_current_recommendation=False,
                contingency_notes="Trial observation from research plot at RARS Jagtial.",
                source_organization="PJTSAU RARS Jagtial",
                document_title="Research Highlights 2023 - Barley Agronomy Trial",
                publication_year=2023,
                reference_location="Page 45",
                source_url="https://pjtsau.edu.in/research/trials-2023.pdf",
                supporting_text="Single-season trial showed Nov 1-30 sowing gave highest dry matter.",
                last_verified_date="2026-11-05",
            )
        )
        in_win, win, expl = calendar.is_in_crop_sowing_window("ExperimentalBarley", date(2026, 11, 15))
        self.assertFalse(in_win)
        self.assertIn("research observation", expl.lower())
        self.assertIn("cannot be provided as actionable sowing guidance", expl.lower())

    # -------------------------------------------------------------------------
    # 44. Historical References Distinguished From Current Guidance
    # -------------------------------------------------------------------------
    def test_44_historical_references_distinguished_from_current_guidance(self):
        """Historical references are distinguished and cannot be provided as active advice."""
        calendar = AgriculturalCalendar(state="Telangana")
        calendar.sowing_windows.append(
            CropSowingWindow(
                crop_name="HistoricSafflower",
                season="Rabi",
                sowing_start_month=10,
                sowing_start_day=1,
                sowing_end_month=10,
                sowing_end_day=31,
                water_condition="Rainfed",
                soil_type="Black",
                agro_climatic_zone=None,
                district=None,
                evidence_status=EvidenceStatus.HISTORICAL_REFERENCE,
                is_verified=True,
                is_current_recommendation=False,
                contingency_notes="Historical recommendation from 1998 handbook.",
                source_organization="Andhra Pradesh Agricultural University",
                document_title="Dryland Safflower Guidelines 1998",
                publication_year=1998,
                reference_location="Page 12",
                source_url=None,
                supporting_text="Historical sowing time for dryland safflower.",
                last_verified_date="1998-10-01",
            )
        )
        in_win, win, expl = calendar.is_in_crop_sowing_window("HistoricSafflower", date(2026, 10, 15))
        self.assertFalse(in_win)
        self.assertIn("historical reference", expl.lower())

    # -------------------------------------------------------------------------
    # 45. Geographic Scope Enforced
    # -------------------------------------------------------------------------
    def test_45_geographic_scope_enforced(self):
        """Zone-specific recommendations are strictly not extended to unsupported districts."""
        calendar = AgriculturalCalendar(state="Telangana")

        # Groundnut is verified specifically for Southern Telangana Zone
        in_win_stz, win_stz, expl_stz = calendar.is_in_crop_sowing_window(
            "Groundnut", date(2026, 11, 5), district="Mahabubnagar"
        )
        self.assertFalse(in_win_stz)
        self.assertIn("pending official verification", expl_stz.lower())

        in_win_ntz, win_ntz, expl_ntz = calendar.is_in_crop_sowing_window(
            "Groundnut", date(2026, 11, 5), district="Adilabad"
        )
        self.assertFalse(in_win_ntz)

        # Bengal Gram is now PARTIALLY_SUPPORTED with agro_climatic_zone=None (all zones)
        bg_in_win, bg_win, bg_expl = calendar.is_in_crop_sowing_window(
            "Bengal Gram", date(2026, 11, 5), district="Adilabad"
        )
        self.assertFalse(bg_in_win)
        self.assertIn("partially supported", bg_expl.lower())

    # -------------------------------------------------------------------------
    # 46. Agricultural Suitability and IMD AMFU Mappings Remain Separate
    # -------------------------------------------------------------------------
    def test_46_suitability_and_amfu_mappings_remain_separate(self):
        """PJTSAU Agro-Climatic Zones and IMD AMFU operational regions are distinct layers."""
        calendar = AgriculturalCalendar(state="Telangana")

        # Check district mappings expose both distinct fields
        for d in calendar.get_all_districts():
            self.assertTrue(len(d.agro_climatic_zone) > 0)
            self.assertTrue(len(d.amfu_cluster) > 0)
            self.assertIn("Telangana Zone", d.agro_climatic_zone)

        # Check distinct lookup methods
        zone_ad = calendar.get_district_zone("Adilabad")
        amfu_ad = calendar.get_district_amfu("Adilabad")
        self.assertEqual(zone_ad, "Northern Telangana Zone")
        self.assertEqual(amfu_ad, "pending_verification")

        # Explicit Jagtial district (Jagtial) AMFU is Jagtial
        zone_jgt = calendar.get_district_zone("Jagtial")
        amfu_jgt = calendar.get_district_amfu("Jagtial")
        self.assertEqual(zone_jgt, "Northern Telangana Zone")
        self.assertIn("Jagtial", amfu_jgt)

        # Central TZ district (Warangal) AMFU is Joint AMFU Hyderabad / AMFU Jagtial
        zone_wgl = calendar.get_district_zone("Warangal")
        amfu_wgl = calendar.get_district_amfu("Warangal")
        self.assertEqual(zone_wgl, "Central Telangana Zone")
        self.assertEqual(amfu_wgl, "Joint AMFU Hyderabad / AMFU Jagtial")

        # Southern TZ district (Hyderabad) AMFU is Hyderabad
        zone_hyd = calendar.get_district_zone("Hyderabad")
        amfu_hyd = calendar.get_district_amfu("Hyderabad")
        self.assertEqual(zone_hyd, "Southern Telangana Zone")
        self.assertIn("Hyderabad", amfu_hyd)

        # Verify zone membership counts remain correct
        stz_districts = calendar.get_districts_in_agro_climatic_zone("Southern Telangana Zone")
        self.assertEqual(len(stz_districts), 12)
        self.assertIn("Mahabubnagar", stz_districts)
        self.assertIn("Hyderabad", stz_districts)

    # -------------------------------------------------------------------------
    # 47. Three Geographic Systems Are Independent (Phase 5.4 Requirement 1)
    # -------------------------------------------------------------------------
    def test_47_three_geographic_systems_independent(self):
        """Administrative districts, PJTSAU zones, and IMD AMFUs are three separate systems."""
        calendar = AgriculturalCalendar(state="Telangana")
        self.assertEqual(len(calendar.get_all_districts()), 33)

        self.assertEqual(len(PJTSAU_AGRO_CLIMATIC_ZONES), 3)
        zone_names = {z.zone_name for z in PJTSAU_AGRO_CLIMATIC_ZONES}
        self.assertIn("Northern Telangana Zone", zone_names)
        self.assertIn("Central Telangana Zone", zone_names)
        self.assertIn("Southern Telangana Zone", zone_names)

        active = get_active_amfu_records()
        self.assertEqual(len(active), 2)

    # -------------------------------------------------------------------------
    # 48. All 33 Districts Are Represented (Phase 5.4 Requirement 2)
    # -------------------------------------------------------------------------
    def test_48_all_33_districts_represented(self):
        """All 33 Telangana districts are represented in administrative records."""
        calendar = AgriculturalCalendar(state="Telangana")
        districts = calendar.get_all_districts()
        self.assertEqual(len(districts), 33)

        ntz = [d for d in districts if d.agro_climatic_zone == "Northern Telangana Zone"]
        ctz = [d for d in districts if d.agro_climatic_zone == "Central Telangana Zone"]
        stz = [d for d in districts if d.agro_climatic_zone == "Southern Telangana Zone"]
        self.assertEqual(len(ntz) + len(ctz) + len(stz), 33)

    # -------------------------------------------------------------------------
    # 49. District Aliases Resolve Correctly (Phase 5.4 Requirement 3)
    # -------------------------------------------------------------------------
    def test_49_district_aliases_resolve_correctly(self):
        """Known district aliases resolve to their canonical district."""
        calendar = AgriculturalCalendar(state="Telangana")
        self.assertEqual(calendar.get_district_zone("Hanamkonda"), "Central Telangana Zone")
        self.assertEqual(calendar.get_district_zone("Warangal Urban"), "Central Telangana Zone")
        self.assertEqual(calendar.get_district_zone("hanumakonda"), "Central Telangana Zone")
        self.assertIsNotNone(calendar.get_district_zone("Jagtial"))
        self.assertEqual(calendar.get_district_zone("jagtial"), "Northern Telangana Zone")
        self.assertEqual(calendar.get_district_zone("Rangareddy"), "Southern Telangana Zone")
        self.assertEqual(calendar.get_district_zone("ranga reddy"), "Southern Telangana Zone")
        self.assertEqual(calendar.get_district_zone("Mahabubnagar"), "Southern Telangana Zone")
        self.assertEqual(calendar.get_district_zone("palamuru"), "Southern Telangana Zone")

    # -------------------------------------------------------------------------
    # 50. PJTSAU Zone Provenance Preserved (Phase 5.4 Requirement 4)
    # -------------------------------------------------------------------------
    def test_50_pjtsau_zone_provenance_preserved(self):
        """PJTSAU agro-climatic zones have source attribution and research station records."""
        for zone in PJTSAU_AGRO_CLIMATIC_ZONES:
            self.assertTrue(len(zone.source) > 0, f"Missing source for zone {zone.zone_name}")
            self.assertTrue(len(zone.zonal_research_station) > 0)
            self.assertTrue(len(zone.districts) > 0)
            self.assertIsNotNone(zone.source_date)

    # -------------------------------------------------------------------------
    # 51. AMFU Hyderabad Has Evidence-Linked Record (Phase 5.4 Requirement 5)
    # -------------------------------------------------------------------------
    def test_51_amfu_hyderabad_evidence_linked(self):
        """AMFU Hyderabad (ACRC Rajendranagar) has an active, evidence-linked record."""
        hyd = next((a for a in IMD_AMFU_RECORDS if a.amfu_id == "AMFU_HYD"), None)
        self.assertIsNotNone(hyd)
        self.assertEqual(hyd.status, AmfuStatus.ACTIVE)
        self.assertIn("Rajendranagar", hyd.host_institution)
        self.assertTrue(len(hyd.evidence_note) > 0)
        self.assertTrue(len(hyd.districts_served) > 0)

    # -------------------------------------------------------------------------
    # 52. AMFU Jagtial Has Evidence-Linked Record (Phase 5.4 Requirement 6)
    # -------------------------------------------------------------------------
    def test_52_amfu_jagtial_evidence_linked(self):
        """AMFU Jagtial (RARS Polasa) has an active, evidence-linked record."""
        jgt = next((a for a in IMD_AMFU_RECORDS if a.amfu_id == "AMFU_JGT"), None)
        self.assertIsNotNone(jgt)
        self.assertEqual(jgt.status, AmfuStatus.ACTIVE)
        self.assertIn("Jagtial", jgt.host_institution)
        self.assertTrue(len(jgt.evidence_note) > 0)
        self.assertTrue(len(jgt.districts_served) > 0)

    # -------------------------------------------------------------------------
    # 53. AMFU Warangal Is NOT Active (Phase 5.4 Requirement 7)
    # -------------------------------------------------------------------------
    def test_53_amfu_warangal_not_active(self):
        """AMFU Warangal is not an active GKMS advisory unit."""
        active_names = [a.amfu_name for a in get_active_amfu_records()]
        for name in active_names:
            self.assertNotIn("Warangal", name, f"AMFU Warangal should not be active, found: {name}")

        historical = get_historical_damu_records()
        warangal_hist = next((r for r in historical if "Warangal" in r.amfu_name), None)
        self.assertIsNotNone(warangal_hist, "Historical DAMU Warangal record should exist")
        self.assertEqual(warangal_hist.status, AmfuStatus.DISCONTINUED)

    # -------------------------------------------------------------------------
    # 54. Unmapped Districts Stay Unassigned (Phase 5.4 Requirement 8)
    # -------------------------------------------------------------------------
    def test_54_unmapped_districts_stay_unassigned(self):
        """Districts without explicit AMFU assignment are marked pending_verification, never inferred."""
        assignment = get_district_amfu_assignment("Warangal")
        self.assertNotEqual(assignment.amfu_coverage_status, AmfuCoverageStatus.EXPLICIT_HYDERABAD)
        self.assertNotEqual(assignment.amfu_coverage_status, AmfuCoverageStatus.EXPLICIT_JAGTIAL)

        unknown_assignment = get_district_amfu_assignment("NonExistentDistrict")
        self.assertIn(unknown_assignment.amfu_coverage_status, (AmfuAssignmentType.UNKNOWN.value, AmfuAssignmentType.PENDING_VERIFICATION.value))
        self.assertIsNone(unknown_assignment.assigned_amfu_id)

    # -------------------------------------------------------------------------
    # 55. Historical DAMUs Excluded from Active Advisory Retrieval (Phase 5.4 Requirement 9)
    # -------------------------------------------------------------------------
    def test_55_historical_damus_excluded_from_active_retrieval(self):
        """Historical DAMUs discontinued from 2024-03-01 are not included in active AMFU advisory retrieval."""
        active = get_active_amfu_records()
        historical = get_historical_damu_records()

        for a in active:
            self.assertEqual(a.status, AmfuStatus.ACTIVE)

        for h in historical:
            self.assertEqual(h.status, AmfuStatus.DISCONTINUED)
            self.assertLessEqual(h.status_since, "2024-12-31")

        active_ids = {a.amfu_id for a in active}
        historical_ids = {h.amfu_id for h in historical}
        self.assertEqual(len(active_ids & historical_ids), 0)

    # -------------------------------------------------------------------------
    # 56. Mandal Rainfall Distinguished From Village Forecasts (Phase 5.4 Requirement 10)
    # -------------------------------------------------------------------------
    def test_56_mandal_rainfall_distinguished_from_village_forecasts(self):
        """Mandal-level rainfall observation network is distinct from village-level forecast claims."""
        # Administrative boundaries maintain clear hierarchy: district -> mandal -> village
        calendar = AgriculturalCalendar(state="Telangana")
        all_districts = calendar.get_all_districts()
        self.assertEqual(len(all_districts), 33)
        # Verify that no district is assigned a mandal or village string as district_name
        for d in all_districts:
            self.assertFalse(d.district_name.endswith("Mandal"))
            self.assertFalse(d.district_name.endswith("Village"))

    # -------------------------------------------------------------------------
    # 57. DES Vanakalam/Yasangi Classification Separate From Sowing Windows (Phase 5.4 Requirement 11)
    # -------------------------------------------------------------------------
    def test_57_des_vanakalam_yasangi_separate_from_sowing_windows(self):
        """DES statistical season classification (Vanakalam/Yasangi) is separate from crop sowing windows."""
        calendar = AgriculturalCalendar(state="Telangana")
        census_seasons = [s for s in calendar.official_seasons if s.is_census_season]
        self.assertEqual(len(census_seasons), 2)
        season_names = {s.season_name for s in census_seasons}
        self.assertIn("Kharif", season_names)
        self.assertIn("Rabi", season_names)

        kharif = next(s for s in census_seasons if s.season_name == "Kharif")
        self.assertEqual(kharif.start_month, 6)
        self.assertEqual(kharif.end_month, 9)

        cotton = calendar.get_crop_sowing_window("Cotton")
        self.assertIsNotNone(cotton)
        self.assertEqual(cotton.season, "Kharif")
        self.assertNotEqual(cotton.sowing_end_month, kharif.end_month)

    # -------------------------------------------------------------------------
    # 58. Cotton Exact Dates Not Treated as Verified (Phase 5.4 Requirement 12)
    # -------------------------------------------------------------------------
    def test_58_cotton_exact_dates_not_verified(self):
        """Cotton sowing window dates are marked pending_verification and cannot give actionable guidance."""
        calendar = AgriculturalCalendar(state="Telangana")
        cotton = calendar.get_crop_sowing_window("Cotton")
        self.assertIsNotNone(cotton)
        self.assertEqual(cotton.evidence_status, EvidenceStatus.PENDING_VERIFICATION)
        self.assertFalse(cotton.is_verified)
        self.assertIsNone(cotton.source_url)

        in_win, _, expl = calendar.is_in_crop_sowing_window("Cotton", date(2026, 7, 1))
        self.assertFalse(in_win)
        self.assertIn("pending", expl.lower())

    # -------------------------------------------------------------------------
    # 59. Red Gram Exact Dates Not Treated as Verified (Phase 5.4 Requirement 13)
    # -------------------------------------------------------------------------
    def test_59_red_gram_exact_dates_not_verified(self):
        """Red Gram sowing window is marked pending_verification."""
        calendar = AgriculturalCalendar(state="Telangana")
        red_gram = calendar.get_crop_sowing_window("Red Gram")
        self.assertIsNotNone(red_gram)
        self.assertEqual(red_gram.evidence_status, EvidenceStatus.PENDING_VERIFICATION)
        self.assertFalse(red_gram.is_verified)
        self.assertIsNone(red_gram.source_url)

        in_win, _, expl = calendar.is_in_crop_sowing_window("Red Gram", date(2026, 6, 15))
        self.assertFalse(in_win)
        self.assertIn("pending", expl.lower())

    # -------------------------------------------------------------------------
    # 60. Chickpea (Bengal Gram) Northern Telangana Not Excluded (Phase 5.4 Requirement 14)
    # -------------------------------------------------------------------------
    def test_60_chickpea_northern_telangana_not_excluded(self):
        """Bengal Gram (chickpea) is not geographically restricted to Southern TZ; NTZ has ARS Adilabad mandate."""
        calendar = AgriculturalCalendar(state="Telangana")
        bg = calendar.get_crop_sowing_window("Bengal Gram")
        self.assertIsNotNone(bg)
        self.assertIsNone(bg.agro_climatic_zone, 
            "Bengal Gram should not be zone-restricted; NTZ (ARS Adilabad) also has chickpea mandate")
        self.assertTrue("Northern Telangana" in bg.contingency_notes or "NTZ" in bg.contingency_notes)

    # -------------------------------------------------------------------------
    # 61. Rabi Maize Southern Telangana Not Excluded (Phase 5.4 Requirement 15)
    # -------------------------------------------------------------------------
    def test_61_rabi_maize_southern_telangana_not_excluded(self):
        """Rabi Maize is not restricted to Northern TZ only; Southern TZ also grows Rabi Maize."""
        calendar = AgriculturalCalendar(state="Telangana")
        maize = calendar.get_crop_sowing_window("Rabi Maize")
        self.assertIsNotNone(maize)
        self.assertIsNone(maize.agro_climatic_zone,
            "Rabi Maize should not be restricted to NTZ only; Southern TZ also cultivates Rabi Maize")

    # -------------------------------------------------------------------------
    # 62. Groundnut Not Restricted to Sprinkler Only (Phase 5.4 Requirement 16)
    # -------------------------------------------------------------------------
    def test_62_groundnut_not_restricted_to_sprinkler_only(self):
        """Rabi Groundnut water condition includes drip, micro-sprinkler, and farm-pond irrigation."""
        calendar = AgriculturalCalendar(state="Telangana")
        gnt = calendar.get_crop_sowing_window("Groundnut")
        self.assertIsNotNone(gnt)
        wc_lower = gnt.water_condition.lower()
        self.assertIn("drip", wc_lower)
        self.assertNotIn("sprinkler only", wc_lower)

    # -------------------------------------------------------------------------
    # 63. Summer Sesame Has Appropriate Soil/Water Limits (Phase 5.4 Requirement 17)
    # -------------------------------------------------------------------------
    def test_63_summer_sesame_appropriate_limits(self):
        """Summer Sesame is restricted to light-soil irrigated pockets, not recommended state-wide."""
        calendar = AgriculturalCalendar(state="Telangana")
        sesame = calendar.get_crop_sowing_window("Summer Sesame")
        self.assertIsNotNone(sesame)
        self.assertIn("light", sesame.soil_type.lower())
        self.assertIn("irrigated", sesame.water_condition.lower())
        self.assertIsNotNone(sesame.agro_climatic_zone)
        self.assertEqual(sesame.evidence_status, EvidenceStatus.PENDING_VERIFICATION)

    # -------------------------------------------------------------------------
    # 64. Expired Advisories Cannot Be Used as Current Advice (Phase 5.4 Requirement 18)
    # -------------------------------------------------------------------------
    def test_64_expired_advisories_cannot_be_current(self):
        """Crop windows with is_current_recommendation=False are excluded from active guidance."""
        calendar = AgriculturalCalendar(state="Telangana")
        calendar.sowing_windows.append(
            CropSowingWindow(
                crop_name="DeprecatedCrop",
                season="Kharif",
                sowing_start_month=6, sowing_start_day=1,
                sowing_end_month=7, sowing_end_day=1,
                water_condition="Rainfed",
                soil_type=None, agro_climatic_zone=None, district=None,
                evidence_status=EvidenceStatus.OFFICIAL_RECOMMENDATION,
                is_verified=True,
                is_current_recommendation=False,
                contingency_notes="Deprecated recommendation.",
                source_organization="Historic Board",
                document_title="Old Handbook 2000",
                publication_year=2000,
                reference_location="Page 10",
                source_url=None,
                supporting_text="Deprecated recommendation from 2000.",
                last_verified_date="2000-01-01",
            )
        )
        in_win, win, expl = calendar.is_in_crop_sowing_window("DeprecatedCrop", date(2026, 6, 15))
        self.assertFalse(in_win)
        self.assertIn("historic/deprecated", expl.lower())

    # -------------------------------------------------------------------------
    # 65. Unsupported Crop-Window Constants Cannot Bypass Verification (Phase 5.4 Requirement 19)
    # -------------------------------------------------------------------------
    def test_65_unsupported_windows_cannot_bypass_verification(self):
        """Crop windows with PENDING_VERIFICATION or UNVERIFIED status are always excluded from active guidance."""
        calendar = AgriculturalCalendar(state="Telangana")
        test_cases = [
            ("Cotton", date(2026, 7, 1)),
            ("Red Gram", date(2026, 6, 15)),
            ("Bengal Gram", date(2026, 11, 5)),
            ("Rabi Maize", date(2026, 11, 1)),
            ("Groundnut", date(2026, 11, 1)),
            ("Summer Sesame", date(2026, 1, 20)),
        ]
        for crop, test_date in test_cases:
            in_win, win, expl = calendar.is_in_crop_sowing_window(crop, test_date)
            self.assertFalse(in_win, f"Crop '{crop}' should not return in_window=True (evidence not verified)")

    # -------------------------------------------------------------------------
    # 66. Four Planning Horizons Remain Distinct (Phase 5.4 Requirement 20)
    # -------------------------------------------------------------------------
    def test_66_four_planning_horizons_distinct(self):
        """Four planning horizons are distinct and cover different day ranges."""
        self.assertEqual(classify_planning_horizon(1), PlanningHorizon.SHORT_RANGE_1_7D)
        self.assertEqual(classify_planning_horizon(7), PlanningHorizon.SHORT_RANGE_1_7D)
        self.assertEqual(classify_planning_horizon(8), PlanningHorizon.EXTENDED_8_15D)
        self.assertEqual(classify_planning_horizon(15), PlanningHorizon.EXTENDED_8_15D)
        self.assertEqual(classify_planning_horizon(16), PlanningHorizon.MEDIUM_30D)
        self.assertEqual(classify_planning_horizon(30), PlanningHorizon.MEDIUM_30D)
        self.assertEqual(classify_planning_horizon(31), PlanningHorizon.SEASONAL_31_60D)
        self.assertEqual(classify_planning_horizon(60), PlanningHorizon.SEASONAL_31_60D)

        horizons = list(PlanningHorizon)
        self.assertEqual(len(horizons), 4)

    # -------------------------------------------------------------------------
    # 67. Long-Range Deterministic Daily Forecasts Not Fabricated (Phase 5.4 Requirement 21)
    # -------------------------------------------------------------------------
    def test_67_long_range_forecasts_not_fabricated(self):
        """The 31-60d planning horizon is explicitly marked as strategic planning, not daily weather forecast."""
        description = get_planning_horizon_description(PlanningHorizon.SEASONAL_31_60D)
        self.assertIn("not scientifically valid", description.lower())
        self.assertIn("strategic", description.lower())
        self.assertIn("deterministic daily weather forecasts", description.lower())

    # -------------------------------------------------------------------------
    # 68. Sources and Evidence Classifications Included in Retrieval Results (Phase 5.4 Requirement 22)
    # -------------------------------------------------------------------------
    def test_68_evidence_classification_in_retrieval_results(self):
        """Crop sowing window retrieval always includes evidence classification."""
        calendar = AgriculturalCalendar(state="Telangana")
        for crop in ["Cotton", "Red Gram", "Bengal Gram", "Rabi Maize", "Groundnut", "Summer Sesame"]:
            window = calendar.get_crop_sowing_window(crop)
            self.assertIsNotNone(window, f"Window missing for {crop}")
            self.assertIsNotNone(window.evidence_status, f"evidence_status missing for {crop}")
            self.assertTrue(len(window.supporting_text) > 0, f"supporting_text missing for {crop}")
            self.assertTrue(len(window.source_organization) > 0, f"source_organization missing for {crop}")

    # -------------------------------------------------------------------------
    # 69. AMFU Independent of PJTSAU Zones (Phase 5.4.1 Requirement 1)
    # -------------------------------------------------------------------------
    def test_69_amfu_independent_of_pjtsau_zones(self):
        """AMFU operational mapping is independent of PJTSAU agro-climatic zones across all districts."""
        calendar = AgriculturalCalendar(state="Telangana")

        # 1. Central TZ district with Joint AMFU assignment
        wgl_zone = calendar.get_district_zone("Warangal")
        wgl_assignment = get_district_amfu_assignment("Warangal")
        self.assertEqual(wgl_zone, "Central Telangana Zone")
        self.assertEqual(wgl_assignment.assignment_type, AmfuAssignmentType.JOINT_HYDERABAD_JAGTIAL)

        # 2. Northern TZ district with explicit AMFU Jagtial assignment
        pdpl_zone = calendar.get_district_zone("Peddapalli")
        pdpl_assignment = get_district_amfu_assignment("Peddapalli")
        self.assertEqual(pdpl_zone, "Northern Telangana Zone")
        self.assertEqual(pdpl_assignment.assignment_type, AmfuAssignmentType.JAGTIAL)

        # 3. Northern TZ district with pending_verification (proves zone is NOT blanket mapped)
        ad_zone = calendar.get_district_zone("Adilabad")
        ad_assignment = get_district_amfu_assignment("Adilabad")
        self.assertEqual(ad_zone, "Northern Telangana Zone")
        self.assertEqual(ad_assignment.assignment_type, AmfuAssignmentType.PENDING_VERIFICATION)

        # 4. Southern TZ district with explicit AMFU Hyderabad assignment
        nlg_zone = calendar.get_district_zone("Nalgonda")
        nlg_assignment = get_district_amfu_assignment("Nalgonda")
        self.assertEqual(nlg_zone, "Southern Telangana Zone")
        self.assertEqual(nlg_assignment.assignment_type, AmfuAssignmentType.HYDERABAD)

    # -------------------------------------------------------------------------
    # 70. Explicit Jagtial District Assignment (Phase 5.4.1 Requirement 2)
    # -------------------------------------------------------------------------
    def test_70_explicit_jagtial_district_assignment(self):
        """Jagtial and Peddapalli districts map explicitly to AMFU Jagtial."""
        for district in ["Jagtial", "Peddapalli"]:
            assignment = get_district_amfu_assignment(district)
            self.assertEqual(assignment.assignment_type, AmfuAssignmentType.JAGTIAL, f"Failed for {district}")
            self.assertIn("AMFU Jagtial", assignment.amfu_or_amfus)
            self.assertIsNotNone(assignment.bulletin_source)
            self.assertTrue(len(assignment.bulletin_source) > 0)
            self.assertEqual(assignment.evidence_classification, "official_recommendation")

    # -------------------------------------------------------------------------
    # 71. Explicit Hyderabad District Assignment (Phase 5.4.1 Requirement 3)
    # -------------------------------------------------------------------------
    def test_71_explicit_hyderabad_district_assignment(self):
        """Hyderabad, Nagarkurnool, Nalgonda, Suryapet, Yadadri Bhuvanagiri map explicitly to AMFU Hyderabad."""
        hyd_districts = ["Hyderabad", "Nagarkurnool", "Nalgonda", "Suryapet", "Yadadri Bhuvanagiri"]
        for district in hyd_districts:
            assignment = get_district_amfu_assignment(district)
            self.assertEqual(assignment.assignment_type, AmfuAssignmentType.HYDERABAD, f"Failed for {district}")
            self.assertIn("AMFU Hyderabad", assignment.amfu_or_amfus)
            self.assertIsNotNone(assignment.bulletin_source)
            self.assertTrue(len(assignment.bulletin_source) > 0)

    # -------------------------------------------------------------------------
    # 72. Joint Hyderabad/Jagtial Assignments (Phase 5.4.1 Requirement 4)
    # -------------------------------------------------------------------------
    def test_72_joint_hyderabad_jagtial_assignments(self):
        """Eight Central/Eastern districts map to Joint Hyderabad/Jagtial coverage."""
        joint_districts = [
            "Warangal", "Hanamkonda", "Jayashankar Bhupalpally",
            "Mahabubabad", "Mulugu", "Siddipet", "Khammam", "Bhadradri Kothagudem",
        ]
        for district in joint_districts:
            assignment = get_district_amfu_assignment(district)
            self.assertEqual(
                assignment.assignment_type,
                AmfuAssignmentType.JOINT_HYDERABAD_JAGTIAL,
                f"Failed for {district}",
            )
            self.assertIn("AMFU Hyderabad", assignment.amfu_or_amfus)
            self.assertIn("AMFU Jagtial", assignment.amfu_or_amfus)

    # -------------------------------------------------------------------------
    # 73. Conflicting or Overlapping Source Discrepancies (Phase 5.4.1 Requirement 5)
    # -------------------------------------------------------------------------
    def test_73_conflicting_or_overlapping_source_discrepancies(self):
        """Discrepancy notes are preserved for districts with joint, conflicting, or reorganization references."""
        joint_districts = [
            "Warangal", "Hanamkonda", "Jayashankar Bhupalpally",
            "Mahabubabad", "Mulugu", "Siddipet", "Khammam", "Bhadradri Kothagudem",
        ]
        for district in joint_districts:
            assignment = get_district_amfu_assignment(district)
            self.assertIsNotNone(assignment.discrepancy_notes, f"Missing discrepancy note for {district}")
            self.assertTrue(len(assignment.discrepancy_notes) > 10, f"Discrepancy note too short for {district}")

    # -------------------------------------------------------------------------
    # 74. Unknown Districts Remain Unassigned (Phase 5.4.1 Requirement 6)
    # -------------------------------------------------------------------------
    def test_74_unknown_districts_remain_unassigned(self):
        """An unmapped or unrecognized district returns unknown or pending_verification, never inferred AMFU."""
        assignment = get_district_amfu_assignment("NonExistentDistrict")
        self.assertIn(assignment.assignment_type, (AmfuAssignmentType.UNKNOWN, AmfuAssignmentType.PENDING_VERIFICATION))
        self.assertEqual(len(assignment.amfu_or_amfus), 0)
        self.assertIsNone(assignment.assigned_amfu_id)

    # -------------------------------------------------------------------------
    # 75. No Automatic Blanket Mapping (Phase 5.4.1 Requirement 7)
    # -------------------------------------------------------------------------
    def test_75_no_automatic_blanket_mapping(self):
        """Northern and Southern zones are NOT blanket-mapped; undocumented districts remain pending_verification."""
        # NTZ undocumented districts
        for d in ["Adilabad", "Kumuram Bheem Asifabad", "Mancherial", "Nirmal", "Nizamabad", "Kamareddy"]:
            assignment = get_district_amfu_assignment(d)
            self.assertEqual(
                assignment.assignment_type,
                AmfuAssignmentType.PENDING_VERIFICATION,
                f"NTZ district {d} should be pending_verification, not blanket-mapped to Jagtial",
            )

        # STZ undocumented districts
        for d in ["Mahabubnagar", "Wanaparthy", "Jogulamba Gadwal", "Narayanpet", "Rangareddy", "Vikarabad"]:
            assignment = get_district_amfu_assignment(d)
            self.assertEqual(
                assignment.assignment_type,
                AmfuAssignmentType.PENDING_VERIFICATION,
                f"STZ district {d} should be pending_verification, not blanket-mapped to Hyderabad",
            )

    # -------------------------------------------------------------------------
    # 76. AMFU Warangal Is NOT Active (Phase 5.4.1 Requirement 8)
    # -------------------------------------------------------------------------
    def test_76_amfu_warangal_not_active(self):
        """Active AMFU records include ONLY Hyderabad and Jagtial; Warangal is not an active AMFU."""
        active = get_active_amfu_records()
        self.assertEqual(len(active), 2)
        active_names = [a.amfu_name for a in active]
        self.assertIn("AMFU Hyderabad", active_names)
        self.assertIn("AMFU Jagtial", active_names)
        for name in active_names:
            self.assertNotIn("Warangal", name)

    # -------------------------------------------------------------------------
    # 77. RARS Warangal Is Valid Research Station Only (Phase 5.4.1 Requirement 9)
    # -------------------------------------------------------------------------
    def test_77_rars_warangal_valid_research_station(self):
        """RARS Warangal is documented as a PJTSAU research station only, not an active GKMS AMFU."""
        ctz = next(z for z in PJTSAU_AGRO_CLIMATIC_ZONES if z.zone_name == "Central Telangana Zone")
        self.assertIn("Regional Agricultural Research Station (RARS), Warangal", ctz.zonal_research_station)
        active_hosts = [a.host_institution for a in get_active_amfu_records()]
        for host in active_hosts:
            self.assertNotIn("RARS Warangal", host)

    # -------------------------------------------------------------------------
    # 78. DAMUs Remain Historical / Discontinued (Phase 5.4.1 Requirement 10)
    # -------------------------------------------------------------------------
    def test_78_damus_remain_historical(self):
        """Former DAMUs (Warangal, Wyra/Khammam) are marked historical/discontinued from 2024-03-01."""
        historical = get_historical_damu_records()
        self.assertTrue(len(historical) >= 2)
        warangal_damu = next((h for h in historical if "Warangal" in h.amfu_name), None)
        wyra_damu = next((h for h in historical if "Wyra" in h.amfu_name), None)

        self.assertIsNotNone(warangal_damu)
        self.assertEqual(warangal_damu.status, AmfuStatus.DISCONTINUED)
        self.assertEqual(warangal_damu.status_since, "2024-03-01")

        self.assertIsNotNone(wyra_damu)
        self.assertEqual(wyra_damu.status, AmfuStatus.DISCONTINUED)
        self.assertEqual(wyra_damu.status_since, "2024-03-01")

    # -------------------------------------------------------------------------
    # 79. No Unsupported Crop Dates in Actionable Retrieval (Phase 5.4.1 Requirement 11)
    # -------------------------------------------------------------------------
    def test_79_no_unsupported_crop_dates_in_actionable_retrieval(self):
        """All unverified crop windows have None for date boundaries and return in_window=False."""
        calendar = AgriculturalCalendar(state="Telangana")
        for crop_name in ["Cotton", "Red Gram", "Bengal Gram", "Rabi Maize", "Groundnut", "Summer Sesame"]:
            window = calendar.get_crop_sowing_window(crop_name)
            self.assertIsNotNone(window)
            self.assertIsNone(window.sowing_start_month, f"{crop_name} sowing_start_month should be None")
            self.assertIsNone(window.sowing_start_day, f"{crop_name} sowing_start_day should be None")
            self.assertIsNone(window.sowing_end_month, f"{crop_name} sowing_end_month should be None")
            self.assertIsNone(window.sowing_end_day, f"{crop_name} sowing_end_day should be None")
            self.assertTrue(len(window.indicative_window_description) > 0)

            # Actionable retrieval must return False
            in_win, _, expl = calendar.is_in_crop_sowing_window(crop_name, date(2026, 7, 1))
            self.assertFalse(in_win, f"{crop_name} should not be actionable")

    # -------------------------------------------------------------------------
    # 80. Cotton Exact Rainfall and Cutoff Unverified (Phase 5.4.1 Requirement 12)
    # -------------------------------------------------------------------------
    def test_80_cotton_exact_rainfall_and_cutoff_unverified(self):
        """Cotton documents monsoon onset, HDPS in red chalka soils, and identifies rainfall/cutoff as unverified."""
        calendar = AgriculturalCalendar(state="Telangana")
        cotton = calendar.get_crop_sowing_window("Cotton")
        self.assertIsNotNone(cotton)
        self.assertIn("monsoon", cotton.indicative_window_description.lower())
        self.assertIn("HDPS", cotton.cultivation_system)
        self.assertIn("red chalka", cotton.cultivation_system.lower())
        self.assertIn("50-60 mm", cotton.contingency_notes)
        self.assertIn("July 20", cotton.contingency_notes)
        self.assertIn("unverified research claims", cotton.contingency_notes.lower())

    # -------------------------------------------------------------------------
    # 81. Red Gram Exact Dates Unverified (Phase 5.4.1 Requirement 13)
    # -------------------------------------------------------------------------
    def test_81_red_gram_exact_dates_unverified(self):
        """Red Gram reflects monsoon onset across red/black soils; exact dates non-actionable."""
        calendar = AgriculturalCalendar(state="Telangana")
        rg = calendar.get_crop_sowing_window("Red Gram")
        self.assertIsNotNone(rg)
        self.assertIn("monsoon", rg.indicative_window_description.lower())
        self.assertIn("red chalka", rg.soil_type.lower())
        self.assertIn("black", rg.soil_type.lower())
        self.assertIsNone(rg.sowing_start_month)

    # -------------------------------------------------------------------------
    # 82. Bengal Gram Scope Consistent (Phase 5.4.1 Requirement 14)
    # -------------------------------------------------------------------------
    def test_82_bengal_gram_scope_consistent(self):
        """Bengal Gram restricted to deep black soils across NTZ, STZ, and CTZ; CRIDA 2011 noted; non-actionable."""
        calendar = AgriculturalCalendar(state="Telangana")
        bg = calendar.get_crop_sowing_window("Bengal Gram")
        self.assertIsNotNone(bg)
        self.assertIn("deep black", bg.soil_type.lower())
        self.assertEqual(bg.evidence_status, EvidenceStatus.PARTIALLY_SUPPORTED)
        self.assertIn("CRIDA 2011", bg.contingency_notes)
        self.assertIn("Adilabad", bg.contingency_notes)
        self.assertIsNone(bg.sowing_start_month)

    # -------------------------------------------------------------------------
    # 83. Rabi Maize Geographic Scope Evidence-Based (Phase 5.4.1 Requirement 15)
    # -------------------------------------------------------------------------
    def test_83_maize_geographic_scope_evidence_based(self):
        """Rabi Maize supported in NTZ, CTZ, and STZ with soil moisture requirement; non-actionable."""
        calendar = AgriculturalCalendar(state="Telangana")
        maize = calendar.get_crop_sowing_window("Rabi Maize")
        self.assertIsNotNone(maize)
        self.assertIn("Northern, Central, and Southern", maize.contingency_notes)
        self.assertIn("soil moisture", maize.water_condition.lower())
        self.assertIn("Expired October 2026", maize.contingency_notes)
        self.assertIsNone(maize.sowing_start_month)

    # -------------------------------------------------------------------------
    # 84. Groundnut Irrigation Options (Phase 5.4.1 Requirement 16)
    # -------------------------------------------------------------------------
    def test_84_groundnut_irrigation_options(self):
        """Groundnut documents multiple irrigation options; sprinkler-only rejected; non-actionable."""
        calendar = AgriculturalCalendar(state="Telangana")
        gnt = calendar.get_crop_sowing_window("Groundnut")
        self.assertIsNotNone(gnt)
        wc = gnt.water_condition.lower()
        self.assertIn("drip", wc)
        self.assertIn("micro-sprinkler", wc)
        self.assertIn("sprinkler", wc)
        self.assertIn("farm-pond", wc)
        self.assertIn("sprinkler-only is technically unjustified", gnt.contingency_notes.lower())
        self.assertIsNone(gnt.sowing_start_month)

    # -------------------------------------------------------------------------
    # 85. Summer Sesame Restricted (Phase 5.4.1 Requirement 17)
    # -------------------------------------------------------------------------
    def test_85_summer_sesame_restricted(self):
        """Summer Sesame restricted to light soils / irrigated command areas (SRSP Ayacut); statewide rejected."""
        calendar = AgriculturalCalendar(state="Telangana")
        sesame = calendar.get_crop_sowing_window("Summer Sesame")
        self.assertIsNotNone(sesame)
        self.assertIn("light textured", sesame.soil_type.lower())
        self.assertIn("SRSP Ayacut", sesame.contingency_notes)
        self.assertIn("NOT recommended statewide", sesame.contingency_notes)
        self.assertIsNone(sesame.sowing_start_month)

    # -------------------------------------------------------------------------
    # 86. Historical and Research Observations Non-Actionable (Phase 5.4.1 Requirement 18)
    # -------------------------------------------------------------------------
    def test_86_historical_and_research_observations_non_actionable(self):
        """Research observations and historical references return in_window=False."""
        calendar = AgriculturalCalendar(state="Telangana")
        calendar.sowing_windows.append(
            CropSowingWindow(
                crop_name="ResearchCrop",
                season="Kharif",
                evidence_status=EvidenceStatus.RESEARCH_OBSERVATION,
                is_verified=True,
                is_current_recommendation=True,
                indicative_window_description="Experimental observation",
            )
        )
        in_win, _, expl = calendar.is_in_crop_sowing_window("ResearchCrop", date(2026, 6, 15))
        self.assertFalse(in_win)
        self.assertIn("research observation", expl.lower())

    # -------------------------------------------------------------------------
    # 87. Original Source Provenance Retained (Phase 5.4.1 Requirement 19)
    # -------------------------------------------------------------------------
    def test_87_original_source_provenance_retained(self):
        """Genuine institutional documents, titles, and publication years are preserved."""
        calendar = AgriculturalCalendar(state="Telangana")
        for crop in ["Cotton", "Red Gram", "Bengal Gram", "Rabi Maize", "Groundnut", "Summer Sesame"]:
            w = calendar.get_crop_sowing_window(crop)
            self.assertIsNotNone(w)
            self.assertTrue(len(w.source_organization) > 0)
            self.assertTrue(len(w.document_title) > 0)
            self.assertIn(w.publication_year, (2011, 2023, 2024))
            self.assertIsNone(w.source_url)  # Fabricated URLs removed

    # -------------------------------------------------------------------------
    # 88. Weather Alone Cannot Trigger Agricultural Advice (Phase 5.4.1 Requirement 20)
    # -------------------------------------------------------------------------
    def test_88_weather_alone_cannot_trigger_agricultural_advice(self):
        """Planning safety rule enforces that a forecast alone cannot trigger agricultural advice."""
        # 1. Forecast alone with no agronomic context -> blocked
        res_blocked = AdvisoryTriggerSafetyPolicy.evaluate_trigger_safety(
            has_forecast=True,
            has_crop_and_stage=False,
            has_soil_water_conditions=False,
            has_valid_official_advisory=False,
        )
        self.assertFalse(res_blocked.is_safe_to_trigger)
        self.assertEqual(res_blocked.planning_guidance_level, "blocked")
        self.assertIn("SAFETY POLICY VIOLATION", res_blocked.safety_message)

        # 2. Forecast with adequate agronomic context -> permitted for operational field advice
        res_safe = AdvisoryTriggerSafetyPolicy.evaluate_trigger_safety(
            has_forecast=True,
            has_crop_and_stage=True,
            has_soil_water_conditions=True,
            has_valid_official_advisory=True,
            horizon_days=3,
        )
        self.assertTrue(res_safe.is_safe_to_trigger)
        self.assertEqual(res_safe.planning_guidance_level, "operational_field_advice")

    # -------------------------------------------------------------------------
    # 89. Strategic Horizons Restricted (Phase 5.4.1 Requirement 21)
    # -------------------------------------------------------------------------
    def test_89_strategic_horizons_restricted(self):
        """16-30d and 31-60d horizons are restricted to strategic and contingency planning."""
        res_medium = AdvisoryTriggerSafetyPolicy.evaluate_trigger_safety(
            has_forecast=True,
            has_crop_and_stage=True,
            has_soil_water_conditions=True,
            has_valid_official_advisory=True,
            horizon_days=20,
        )
        self.assertEqual(res_medium.planning_guidance_level, "strategic_planning_only")
        self.assertIn("strategic seasonal planning", res_medium.safety_message.lower())

        res_long = AdvisoryTriggerSafetyPolicy.evaluate_trigger_safety(
            has_forecast=True,
            has_crop_and_stage=True,
            has_soil_water_conditions=True,
            has_valid_official_advisory=True,
            horizon_days=45,
        )
        self.assertEqual(res_long.planning_guidance_level, "strategic_planning_only")
        self.assertIn("deterministic daily weather forecasts are not scientifically valid", res_long.safety_message.lower())


if __name__ == "__main__":
    unittest.main()
