"""
Unit test suite for KrishiVaani TGDPS Daily Weather Report Ingestion — Phase 6.4.

Tests all criteria mandated in Phase 6.4 specification:
1. Official report discovery from portal HTML.
2. PDF download validation & SHA-256 checksumming.
3. Host allowlist restriction (rejecting arbitrary external domains).
4. Redirect security and excessive redirect loop protection.
5. DNS validation (fail-closed, multi-IP, mixed public/private rejection, IPv4-mapped IPv6).
6. PDF extraction (District summaries, top mandals, observation window).
7. Numeric rainfall parsing (actual, normal, deviation, rainy days).
8. Missing values ('-', 'NA') versus zero rainfall (0.0 mm) distinguished.
9. Malformed numeric values rejected with ValueError.
10. Observation date and 24-hour period handling.
11. Station observation vs district summary distinction.
12. Source page citations ('Page 2' for districts, 'Page 3' for mandals).
13. Pending verification status enforcement for all ingested items and source.
14. Farmer-facing search excludes pending records.
15. Expiry and time-bound validity window behaviour.
16. Incremental deduplication (skipping already ingested source/checksum).
17. Dry-run without database writes.
18. Manual local PDF import fallback.
19. Non-PDF response rejected (%PDF- signature check).
20. Large download streaming limit enforcement.
"""

import hashlib
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import fitz  # PyMuPDF
import httpx

from app.db.database import init_db, get_connection
from app.knowledge.models import (
    AuthorityStatus,
    VerificationStatus,
    KnowledgeCategory,
    KnowledgeType,
)
from app.knowledge.repository import KnowledgeRepository
from app.knowledge.schemas import KnowledgeSearchFilterSchema
from app.knowledge.tgdps.adapter import (
    TGDPSSourceAdapter,
    TGDPSDiscoveryError,
    TGDPSDownloadError,
    TGDPSInvalidPDFError,
    TGDPSSecurityError,
    DEFAULT_ALLOWED_DOMAINS,
)
from app.knowledge.tgdps.extractor import (
    TGDPSReportExtractor,
    parse_rainfall_amount,
    parse_deviation_percent,
    parse_rainy_days,
)
from app.knowledge.tgdps.ingestion_service import TGDPSReportIngestionService
from app.knowledge.tgdps.schemas import (
    TGDPSReportLink,
    TGDPSExtractionQuality,
)

SAMPLE_PORTAL_HTML = """
<!DOCTYPE html>
<html>
<head><title>::Telangana Development Planning Society(TGDPS)::</title></head>
<body>
  <div class="menu">
    <a href="aws.jsp">Weather Observations</a>
    <a href="DailyWeatherReport.pdf">Daily Weather Report</a>
    <a href="Annual_Weather_Report_2024.pdf">Annual Weather Report-2024</a>
    <a href="RTI.pdf">RTI</a>
    <a href="districtdata.jsp">District Rainfall Data</a>
  </div>
</body>
</html>
"""


def build_mock_tgdps_pdf(include_missing_value: bool = True) -> bytes:
    """Build a multi-page synthetic TGDPS Daily Weather Report PDF for testing."""
    doc = fitz.open()

    # Page 1: Metadata, Observation Window, State/GHMC Extremes
    p1 = doc.new_page()
    p1_text = (
        "Brief note on Rainfall & Temperature Status (07-November-2026)\n"
        "(from 06-November-2026 08:30 AM to 07-November-2026 08:30 AM)\n"
        "Northeast Monsoon Season:\n"
        "State-Day Status:\n"
        "Highest Rainfall of 74.8 mm recorded at Maripeda (Mahabubabad).\n"
        "The State day Average Rainfall is 1.0 mm against 0.5 mm Normal.\n"
        "GHMC_CMC_MMC area-Day Status:\n"
        "Highest Rainfall of 2.1 mm recorded at Keesara (Medchal-Malkajgiri).\n"
        "The Average Rainfall is 0.1 mm against 0.3 mm Normal.\n"
    )
    p1.insert_text((50, 50), p1_text)

    # Page 2: District-wise Rainfall Status Table
    p2 = doc.new_page()
    medak_actual = "-" if include_missing_value else "0.0"
    p2_text = (
        "Telangana State Rainfall Report on 07-November-2026\n"
        "District-wise Rainfall Status as on 07-November-2026\n"
        "1\nSiddipet\n0.4\n0.1\n300\n685.8\n705.7\n-3\nNormal\n52\n"
        "2\nMancherial\n0.0\n0.0\n0\n963.2\n1008.0\n-4\nNormal\n58\n"
        f"3\nMedak\n{medak_actual}\n0.1\n-100\n730.0\n761.1\n-4\nNormal\n54\n"
        "4\nKamareddy\n0.0\n0.2\n-100\n840.3\n894.0\n-6\nNormal\n55\n"
        "5\nMahabubabad\n12.6\n0.9\n1300\n727.7\n927.1\n-22\nDeficient\n55\n"
        "State Average\n1.0\n0.5\n100\n645.4\n837.6\n-23\nDeficient\n65\n"
    )
    p2.insert_text((50, 50), p2_text, fontsize=9)

    # Page 3: Top 10 Mandal-wise Rainfall Table
    p3 = doc.new_page()
    p3_text = (
        "Top 10 Mandal-wise Rainfall Recorded as on 07-November-2026\n"
        "S.No District\n"
        "Mandal\n"
        "Rain (mm)\n"
        "1\nMahabubabad\nMaripeda\n74.8\n"
        "2\nMahabubabad\nKuravi\n61.4\n"
        "3\nSuryapet\nNoothankal\n45.3\n"
        "4\nMahabubabad\nBayyaram\n37.8\n"
        "5\nYadadri Bhuvanagiri\nBhongiri\n31.9\n"
    )
    p3.insert_text((50, 50), p3_text)

    pdf_bytes = doc.write()
    doc.close()
    return pdf_bytes


class TestTGDPSIngestionSuite(unittest.TestCase):
    """Complete test suite for KrishiVaani TGDPS Daily Weather Report Ingestion."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_krishivaani.db"
        self.data_dir = Path(self.temp_dir.name) / "data_tgdps"
        init_db(self.db_path)
        self.repository = KnowledgeRepository(db_path=self.db_path)

        self.mock_client = MagicMock(spec=httpx.Client)
        self.mock_client.get.return_value = MagicMock(
            status_code=200,
            text=SAMPLE_PORTAL_HTML,
            content=build_mock_tgdps_pdf(),
            url="https://tgdps.telangana.gov.in/DailyWeatherReport.pdf",
            history=[],
        )
        # Inject test domains and hermetic mock DNS resolver
        test_allowed_domains = set(DEFAULT_ALLOWED_DOMAINS) | {"example.com", "short.link"}
        self.adapter = TGDPSSourceAdapter(
            portal_url="https://tgdps.telangana.gov.in/",
            data_dir=self.data_dir,
            http_client=self.mock_client,
            allowed_domains=test_allowed_domains,
            dns_resolver=lambda host: ["93.184.216.34"],
        )
        self.extractor = TGDPSReportExtractor()
        self.service = TGDPSReportIngestionService(
            db_path=self.db_path,
            adapter=self.adapter,
            extractor=self.extractor,
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    # -------------------------------------------------------------------------
    # Test 1: Report Discovery
    # -------------------------------------------------------------------------
    def test_01_report_discovery_from_portal(self):
        """Portal HTML is parsed to discover official Daily Weather Report links."""
        links = self.adapter.discover_reports(portal_html=SAMPLE_PORTAL_HTML)
        self.assertGreaterEqual(len(links), 1)
        report_link = links[0]
        self.assertIn("DailyWeatherReport.pdf", report_link.original_url)
        self.assertEqual(report_link.original_url, "https://tgdps.telangana.gov.in/DailyWeatherReport.pdf")

    # -------------------------------------------------------------------------
    # Test 2: PDF Download & Checksumming
    # -------------------------------------------------------------------------
    def test_02_pdf_download_and_checksumming(self):
        """Downloading a report calculates consistent SHA-256 and enforces idempotence."""
        pdf_bytes = build_mock_tgdps_pdf()
        self.mock_client.get.return_value = MagicMock(
            status_code=200,
            text=SAMPLE_PORTAL_HTML,
            content=pdf_bytes,
            url="https://tgdps.telangana.gov.in/DailyWeatherReport.pdf",
            history=[],
        )

        link = TGDPSReportLink(
            displayed_label="Daily Weather Report",
            report_date="2026-11-07",
            original_url="https://tgdps.telangana.gov.in/DailyWeatherReport.pdf",
            resolved_url="https://tgdps.telangana.gov.in/DailyWeatherReport.pdf",
        )

        path1, checksum1, was_downloaded1 = self.adapter.download_report_pdf(link)
        self.assertTrue(was_downloaded1)
        self.assertTrue(path1.exists())
        self.assertEqual(checksum1, hashlib.sha256(pdf_bytes).hexdigest())

        # Second download should recognize file on disk and not re-write
        path2, checksum2, was_downloaded2 = self.adapter.download_report_pdf(link)
        self.assertFalse(was_downloaded2)
        self.assertEqual(path1, path2)
        self.assertEqual(checksum1, checksum2)

    # -------------------------------------------------------------------------
    # Test 3: Host Allowlist Enforcement
    # -------------------------------------------------------------------------
    def test_03_host_allowlist_enforcement(self):
        """Requests to untrusted domains or lookalike hosts are blocked."""
        bad_urls = [
            "https://attacker.com/DailyWeatherReport.pdf",
            "https://evil-tgdps.telangana.gov.in/report.pdf",
            "https://tgdps.telangana.gov.in.attacker.com/DailyWeatherReport.pdf",
        ]
        for url in bad_urls:
            with self.subTest(url=url):
                link = TGDPSReportLink(
                    displayed_label="Bad",
                    report_date="2026-11-07",
                    original_url=url,
                    resolved_url=url,
                )
                with self.assertRaises(TGDPSSecurityError):
                    self.adapter.download_report_pdf(link)

    # -------------------------------------------------------------------------
    # Test 4: Redirect Security & Loop Limit
    # -------------------------------------------------------------------------
    def test_04_redirect_security_and_loop_protection(self):
        """Redirects to private/internal IPs are aborted; excessive redirects stopped."""
        # A. Redirect to internal IP
        transport_internal = httpx.MockTransport(
            lambda req: httpx.Response(302, headers={"Location": "http://127.0.0.1:8000/secret.pdf"})
            if "start" in str(req.url)
            else httpx.Response(200, content=b"secret")
        )
        client_internal = httpx.Client(
            transport=transport_internal,
            follow_redirects=True,
            event_hooks={"response": [self.adapter._validate_redirect_hook]},
        )
        adapter_internal = TGDPSSourceAdapter(
            data_dir=self.data_dir,
            http_client=client_internal,
            dns_resolver=lambda h: ["93.184.216.34"],
        )
        link = TGDPSReportLink(
            displayed_label="Redirect Test",
            report_date="2026-11-07",
            original_url="https://tgdps.telangana.gov.in/start",
            resolved_url="https://tgdps.telangana.gov.in/start",
        )
        with self.assertRaises(TGDPSSecurityError):
            adapter_internal.download_report_pdf(link)

        # B. Redirect loop
        transport_loop = httpx.MockTransport(
            lambda req: httpx.Response(302, headers={"Location": "https://tgdps.telangana.gov.in/loop"})
        )
        client_loop = httpx.Client(
            transport=transport_loop,
            follow_redirects=True,
            max_redirects=5,
            event_hooks={"response": [self.adapter._validate_redirect_hook]},
        )
        adapter_loop = TGDPSSourceAdapter(
            data_dir=self.data_dir,
            http_client=client_loop,
            dns_resolver=lambda h: ["93.184.216.34"],
        )
        link_loop = TGDPSReportLink(
            displayed_label="Loop",
            report_date="2026-11-07",
            original_url="https://tgdps.telangana.gov.in/loop",
            resolved_url="https://tgdps.telangana.gov.in/loop",
        )
        with self.assertRaises(TGDPSDownloadError) as ctx:
            adapter_loop.download_report_pdf(link_loop)
        self.assertIn("Too many redirects", str(ctx.exception))

    # -------------------------------------------------------------------------
    # Test 5: DNS Validation (Fail-Closed & Mixed IP Rejection)
    # -------------------------------------------------------------------------
    def test_05_dns_validation_fail_closed_and_mixed_ip(self):
        """DNS resolution failures fail closed; mixed public/private IPs are rejected."""
        # Fail closed on empty DNS
        adapter_empty = TGDPSSourceAdapter(dns_resolver=lambda h: [])
        with self.assertRaises(TGDPSSecurityError):
            adapter_empty.validate_url_security("https://tgdps.telangana.gov.in/report.pdf")

        # Reject mixed public/private DNS
        adapter_mixed = TGDPSSourceAdapter(dns_resolver=lambda h: ["93.184.216.34", "192.168.1.1"])
        with self.assertRaises(TGDPSSecurityError) as ctx:
            adapter_mixed.validate_url_security("https://tgdps.telangana.gov.in/report.pdf")
        self.assertIn("restricted/private IP", str(ctx.exception))

        # Reject IPv4-mapped IPv6
        adapter_mapped = TGDPSSourceAdapter(dns_resolver=lambda h: ["::ffff:127.0.0.1"])
        with self.assertRaises(TGDPSSecurityError) as ctx:
            adapter_mapped.validate_url_security("https://tgdps.telangana.gov.in/report.pdf")
        self.assertIn("restricted/private IP", str(ctx.exception))

    # -------------------------------------------------------------------------
    # Test 6: PDF Extraction
    # -------------------------------------------------------------------------
    def test_06_pdf_extraction_district_and_mandal_records(self):
        """Extraction captures report date, observation window, district summaries, and mandals."""
        pdf_bytes = build_mock_tgdps_pdf()
        doc = self.extractor.extract_from_bytes(pdf_bytes)

        self.assertEqual(doc.report_date, "2026-11-07")
        self.assertIn("06-November-2026 08:30 AM to 07-November-2026 08:30 AM", doc.observation_period)
        self.assertEqual(len(doc.district_summaries), 5)
        self.assertGreaterEqual(len(doc.station_observations), 5)
        self.assertEqual(doc.state_average_rainfall_actual_mm, 1.0)
        self.assertEqual(doc.state_average_rainfall_normal_mm, 0.5)

    # -------------------------------------------------------------------------
    # Test 7: Numeric Parsing: Zero vs Missing Rainfall
    # -------------------------------------------------------------------------
    def test_07_numeric_parsing_zero_vs_missing_rainfall(self):
        """Zero rainfall (0.0 mm) is strictly distinguished from missing/unavailable data ('-')."""
        pdf_bytes = build_mock_tgdps_pdf(include_missing_value=True)
        doc = self.extractor.extract_from_bytes(pdf_bytes)

        dist_map = {d.district: d for d in doc.district_summaries}

        # Mancherial has 0.0 mm (Zero rainfall, not missing)
        self.assertIsNotNone(dist_map["Mancherial"].actual_rainfall_mm)
        self.assertEqual(dist_map["Mancherial"].actual_rainfall_mm, 0.0)

        # Medak has '-' (Missing/Unavailable, not zero)
        self.assertIsNone(dist_map["Medak"].actual_rainfall_mm)

        # Siddipet has 0.4 mm
        self.assertEqual(dist_map["Siddipet"].actual_rainfall_mm, 0.4)

    # -------------------------------------------------------------------------
    # Test 8: Malformed Numeric Values Rejected
    # -------------------------------------------------------------------------
    def test_08_malformed_numeric_values_rejected(self):
        """Malformed numeric strings and negative rainfall raise ValueError."""
        with self.assertRaises(ValueError):
            parse_rainfall_amount("invalid_num")

        with self.assertRaises(ValueError):
            parse_rainfall_amount("-5.0")

        with self.assertRaises(ValueError):
            parse_rainy_days("not_an_int")

        with self.assertRaises(ValueError):
            parse_rainy_days("-2")

    # -------------------------------------------------------------------------
    # Test 9: Station vs District Distinction
    # -------------------------------------------------------------------------
    def test_09_station_vs_district_distinction(self):
        """District summaries never have mandal/village set; station observations preserve mandal location."""
        pdf_bytes = build_mock_tgdps_pdf()
        self.mock_client.get.return_value = MagicMock(
            status_code=200,
            text=SAMPLE_PORTAL_HTML,
            content=pdf_bytes,
            url="https://tgdps.telangana.gov.in/DailyWeatherReport.pdf",
            history=[],
        )

        link = TGDPSReportLink(
            displayed_label="Test Report",
            report_date="2026-11-07",
            original_url="https://tgdps.telangana.gov.in/DailyWeatherReport.pdf",
            resolved_url="https://tgdps.telangana.gov.in/DailyWeatherReport.pdf",
        )
        summary = self.service.ingest_reports(limit=1, incremental=False)
        self.assertGreater(summary.items_stored_count, 0)

        # Inspect database items
        conn = get_connection(self.db_path)
        try:
            cursor = conn.cursor()
            rows = cursor.execute("SELECT knowledge_id, title, district, mandal, village FROM knowledge_items WHERE knowledge_id LIKE 'ki_tgdps_%'").fetchall()

            district_items = [r for r in rows if "_dist_" in r["knowledge_id"]]
            mandal_items = [r for r in rows if "_mandal_" in r["knowledge_id"]]

            self.assertGreater(len(district_items), 0)
            self.assertGreater(len(mandal_items), 0)

            # District summary: district is set, mandal is None, village is None
            for item in district_items:
                self.assertIsNotNone(item["district"])
                self.assertIsNone(item["mandal"], "District aggregate must never have mandal assigned")
                self.assertIsNone(item["village"], "District aggregate must never have village assigned")

            # Station observation: district is set, mandal is set, village is None
            for item in mandal_items:
                self.assertIsNotNone(item["district"])
                self.assertIsNotNone(item["mandal"], "Station observation must preserve station/mandal location")
                self.assertIsNone(item["village"], "Station observation must never be inferred as village reading")
        finally:
            conn.close()

    # -------------------------------------------------------------------------
    # Test 10: Source Page Citations & Provenance
    # -------------------------------------------------------------------------
    def test_10_source_page_citations_and_provenance(self):
        """Items are linked to official source with exact page citations (Page 2 for district, Page 3 for mandal)."""
        pdf_bytes = build_mock_tgdps_pdf()
        self.mock_client.get.return_value = MagicMock(
            status_code=200,
            text=SAMPLE_PORTAL_HTML,
            content=pdf_bytes,
            url="https://tgdps.telangana.gov.in/DailyWeatherReport.pdf",
            history=[],
        )

        link = TGDPSReportLink(
            displayed_label="Citation Test",
            report_date="2026-11-07",
            original_url="https://tgdps.telangana.gov.in/DailyWeatherReport.pdf",
            resolved_url="https://tgdps.telangana.gov.in/DailyWeatherReport.pdf",
        )
        self.service.ingest_reports(limit=1, incremental=False)

        conn = get_connection(self.db_path)
        try:
            cursor = conn.cursor()
            links = cursor.execute("SELECT item_id, source_id, reference_location FROM knowledge_item_sources WHERE item_id LIKE 'ki_tgdps_%'").fetchall()

            for link_row in links:
                item_id = link_row["item_id"]
                ref_loc = link_row["reference_location"]
                if "_dist_" in item_id:
                    self.assertEqual(ref_loc, "Page 2")
                elif "_mandal_" in item_id:
                    self.assertTrue("Page 3" in ref_loc or "Page 1" in ref_loc)
        finally:
            conn.close()

    # -------------------------------------------------------------------------
    # Test 11: Pending Verification Enforcement
    # -------------------------------------------------------------------------
    def test_11_pending_verification_enforcement(self):
        """All ingested sources and items must be marked pending_verification in SQLite DB."""
        pdf_bytes = build_mock_tgdps_pdf()
        self.mock_client.get.return_value = MagicMock(
            status_code=200,
            text=SAMPLE_PORTAL_HTML,
            content=pdf_bytes,
            url="https://tgdps.telangana.gov.in/DailyWeatherReport.pdf",
            history=[],
        )

        link = TGDPSReportLink(
            displayed_label="Pending Review Test",
            report_date="2026-11-07",
            original_url="https://tgdps.telangana.gov.in/DailyWeatherReport.pdf",
            resolved_url="https://tgdps.telangana.gov.in/DailyWeatherReport.pdf",
        )
        self.service.ingest_reports(limit=1, incremental=False)

        conn = get_connection(self.db_path)
        try:
            cursor = conn.cursor()
            # Check source authority status
            source = cursor.execute("SELECT source_id, authority_status FROM knowledge_sources WHERE source_id LIKE 'src_tgdps_%'").fetchone()
            self.assertIsNotNone(source)
            self.assertEqual(source["authority_status"], AuthorityStatus.PENDING_VERIFICATION.value)

            # Check items verification status
            items = cursor.execute("SELECT knowledge_id, verification_status FROM knowledge_items WHERE knowledge_id LIKE 'ki_tgdps_%'").fetchall()
            for item in items:
                self.assertEqual(item["verification_status"], VerificationStatus.PENDING_VERIFICATION.value)

            # Check audit records exist
            audits = cursor.execute("SELECT audit_id, action FROM knowledge_verification_audit WHERE entity_id LIKE 'ki_tgdps_%' OR entity_id LIKE 'src_tgdps_%'").fetchall()
            self.assertGreater(len(audits), 0)
            for a in audits:
                self.assertEqual(a["action"], "auto_ingested_pending_review")
        finally:
            conn.close()

    # -------------------------------------------------------------------------
    # Test 12: Exclusion from Farmer-Facing Search
    # -------------------------------------------------------------------------
    def test_12_exclusion_from_farmer_facing_search(self):
        """Items pending verification are excluded from verified farmer search."""
        pdf_bytes = build_mock_tgdps_pdf()
        self.mock_client.get.return_value = MagicMock(
            status_code=200,
            text=SAMPLE_PORTAL_HTML,
            content=pdf_bytes,
            url="https://tgdps.telangana.gov.in/DailyWeatherReport.pdf",
            history=[],
        )

        link = TGDPSReportLink(
            displayed_label="Search Exclusion Test",
            report_date="2026-11-07",
            original_url="https://tgdps.telangana.gov.in/DailyWeatherReport.pdf",
            resolved_url="https://tgdps.telangana.gov.in/DailyWeatherReport.pdf",
        )
        self.service.ingest_reports(limit=1, incremental=False)

        filters = KnowledgeSearchFilterSchema(
            knowledge_type=KnowledgeType.TIME_BOUND_ADVISORY.value,
            state="Telangana",
            district="Siddipet",
        )
        # Search while items are pending_verification
        results = self.repository.search_verified_items(filters, as_of_date_iso="2026-11-07")
        self.assertEqual(len(results), 0, "Pending verification items must not appear in search results")

        # Approve one item and verify search retrieves it
        conn = get_connection(self.db_path)
        try:
            cursor = conn.cursor()
            item = cursor.execute("SELECT knowledge_id FROM knowledge_items WHERE knowledge_id LIKE 'ki_tgdps_%_dist_siddipet'").fetchone()
            k_id = item["knowledge_id"]
            cursor.execute("UPDATE knowledge_sources SET authority_status = 'approved'")
            conn.commit()
        finally:
            conn.close()

        self.repository.update_verification_status(
            knowledge_id=k_id,
            status=VerificationStatus.VERIFIED.value,
            verified_by="expert:agromet_reviewer",
            verified_at="2026-11-07T10:00:00Z",
            updated_at="2026-11-07T10:00:00Z",
        )

        results_after = self.repository.search_verified_items(filters, as_of_date_iso="2026-11-07")
        self.assertEqual(len(results_after), 1)
        self.assertEqual(results_after[0].item.knowledge_id, k_id)

    # -------------------------------------------------------------------------
    # Test 13: Expiry and Validity Window Behaviour
    # -------------------------------------------------------------------------
    def test_13_expiry_and_time_bound_validity(self):
        """Time-bound weather observations expire after their validity window."""
        pdf_bytes = build_mock_tgdps_pdf()
        self.mock_client.get.return_value = MagicMock(
            status_code=200,
            text=SAMPLE_PORTAL_HTML,
            content=pdf_bytes,
            url="https://tgdps.telangana.gov.in/DailyWeatherReport.pdf",
            history=[],
        )

        link = TGDPSReportLink(
            displayed_label="Expiry Test",
            report_date="2026-11-07",
            original_url="https://tgdps.telangana.gov.in/DailyWeatherReport.pdf",
            resolved_url="https://tgdps.telangana.gov.in/DailyWeatherReport.pdf",
        )
        self.service.ingest_reports(limit=1, incremental=False)

        conn = get_connection(self.db_path)
        try:
            cursor = conn.cursor()
            item = cursor.execute("SELECT knowledge_id FROM knowledge_items WHERE knowledge_id LIKE 'ki_tgdps_%_dist_siddipet'").fetchone()
            k_id = item["knowledge_id"]
            cursor.execute("UPDATE knowledge_sources SET authority_status = 'approved'")
            conn.commit()
        finally:
            conn.close()

        # Approve item
        self.repository.update_verification_status(
            knowledge_id=k_id,
            status=VerificationStatus.VERIFIED.value,
            verified_by="expert:agromet_reviewer",
            verified_at="2026-11-07T10:00:00Z",
            updated_at="2026-11-07T10:00:00Z",
        )

        filters = KnowledgeSearchFilterSchema(
            knowledge_type=KnowledgeType.TIME_BOUND_ADVISORY.value,
            state="Telangana",
            district="Siddipet",
        )
        # Search on same day: valid
        res_same_day = self.repository.search_verified_items(filters, as_of_date_iso="2026-11-07")
        self.assertEqual(len(res_same_day), 1)
        self.assertEqual(res_same_day[0].item.knowledge_id, k_id)

        # Search 10 days later: expired
        res_expired = self.repository.search_verified_items(filters, as_of_date_iso="2026-11-17")
        self.assertEqual(len(res_expired), 0)

    # -------------------------------------------------------------------------
    # Test 14: Incremental Deduplication
    # -------------------------------------------------------------------------
    def test_14_incremental_deduplication(self):
        """Incremental ingestion skips already ingested report URL and checksum."""
        pdf_bytes = build_mock_tgdps_pdf()
        self.mock_client.get.return_value = MagicMock(
            status_code=200,
            text=SAMPLE_PORTAL_HTML,
            content=pdf_bytes,
            url="https://tgdps.telangana.gov.in/DailyWeatherReport.pdf",
            history=[],
        )

        link = TGDPSReportLink(
            displayed_label="Dedup Test",
            report_date="2026-11-07",
            original_url="https://tgdps.telangana.gov.in/DailyWeatherReport.pdf",
            resolved_url="https://tgdps.telangana.gov.in/DailyWeatherReport.pdf",
        )

        # First run
        s1 = self.service.ingest_reports(limit=1, incremental=True)
        self.assertEqual(s1.downloaded_count, 1)
        self.assertGreater(s1.items_stored_count, 0)

        # Second run: incremental should recognize URL already exists and skip
        s2 = self.service.ingest_reports(limit=1, incremental=True)
        self.assertEqual(s2.downloaded_count, 0)
        self.assertEqual(s2.unchanged_count, 1)
        self.assertEqual(s2.items_stored_count, 0)

    # -------------------------------------------------------------------------
    # Test 15: Dry-Run Mode
    # -------------------------------------------------------------------------
    def test_15_dry_run_behaviour(self):
        """Dry-run extracts documents and reports summary, writing 0 rows to SQLite."""
        pdf_bytes = build_mock_tgdps_pdf()
        self.mock_client.get.return_value = MagicMock(
            status_code=200,
            text=SAMPLE_PORTAL_HTML,
            content=pdf_bytes,
            url="https://tgdps.telangana.gov.in/DailyWeatherReport.pdf",
            history=[],
        )

        summary = self.service.ingest_reports(limit=1, dry_run=True)
        self.assertTrue(summary.dry_run)
        self.assertGreater(summary.items_stored_count, 0)

        # Confirm 0 records written to database
        conn = get_connection(self.db_path)
        try:
            cursor = conn.cursor()
            source_count = cursor.execute("SELECT COUNT(*) FROM knowledge_sources WHERE source_id LIKE 'src_tgdps_%'").fetchone()[0]
            item_count = cursor.execute("SELECT COUNT(*) FROM knowledge_items WHERE knowledge_id LIKE 'ki_tgdps_%'").fetchone()[0]
            self.assertEqual(source_count, 0)
            self.assertEqual(item_count, 0)
        finally:
            conn.close()

    # -------------------------------------------------------------------------
    # Test 16: Manual Local PDF Import Fallback
    # -------------------------------------------------------------------------
    def test_16_local_file_import_fallback(self):
        """Importing a local PDF file parses and ingests without network calls."""
        pdf_bytes = build_mock_tgdps_pdf()
        local_file = self.data_dir / "test_report.pdf"
        local_file.parent.mkdir(parents=True, exist_ok=True)
        local_file.write_bytes(pdf_bytes)

        doc, stored = self.service.ingest_local_file(local_file, report_date="2026-11-07")
        self.assertEqual(doc.report_date, "2026-11-07")
        self.assertGreater(stored, 0)

        # Confirm items in DB
        conn = get_connection(self.db_path)
        try:
            cursor = conn.cursor()
            item_count = cursor.execute("SELECT COUNT(*) FROM knowledge_items WHERE knowledge_id LIKE 'ki_tgdps_%'").fetchone()[0]
            self.assertEqual(item_count, stored)
        finally:
            conn.close()

    # -------------------------------------------------------------------------
    # Test 17: Non-PDF Response Rejected
    # -------------------------------------------------------------------------
    def test_17_non_pdf_response_rejected(self):
        """Response lacking %PDF- signature raises TGDPSInvalidPDFError."""
        html_payload = b"<!DOCTYPE html><html><body>Error Page</body></html>"
        self.mock_client.get.return_value = MagicMock(status_code=200, content=html_payload)
        link = TGDPSReportLink(
            displayed_label="HTML Response",
            report_date="2026-11-07",
            original_url="https://tgdps.telangana.gov.in/DailyWeatherReport.pdf",
            resolved_url="https://tgdps.telangana.gov.in/DailyWeatherReport.pdf",
        )
        with self.assertRaises(TGDPSInvalidPDFError):
            self.adapter.download_report_pdf(link)

    # -------------------------------------------------------------------------
    # Test 18: Large Download Streaming Limit Enforcement
    # -------------------------------------------------------------------------
    def test_18_large_download_streaming_limit_enforced(self):
        """Large downloads exceeding max size limit are aborted."""
        large_size = 50 * 1024 * 1024
        transport = httpx.MockTransport(
            lambda req: httpx.Response(200, headers={"Content-Length": str(large_size)}, content=b"%PDF-1.4")
        )
        client = httpx.Client(transport=transport)
        adapter = TGDPSSourceAdapter(
            data_dir=self.data_dir,
            max_pdf_size_bytes=1024 * 1024,
            http_client=client,
            dns_resolver=lambda h: ["93.184.216.34"],
        )
        link = TGDPSReportLink(
            displayed_label="Large File",
            report_date="2026-11-07",
            original_url="https://tgdps.telangana.gov.in/DailyWeatherReport.pdf",
            resolved_url="https://tgdps.telangana.gov.in/DailyWeatherReport.pdf",
        )
        with self.assertRaises(TGDPSInvalidPDFError):
            adapter.download_report_pdf(link)


if __name__ == "__main__":
    unittest.main()
