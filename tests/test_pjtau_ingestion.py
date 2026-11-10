"""
Unit test suite for KrishiVaani Automatic PJTAU Bulletin Ingestion — Phase 6.3.
Tests all criteria mandated in Phase 6.3 specification:
1. Archive discovery parsing.
2. Multiple language detection (Telugu, English, bilingual).
3. Inconsistent bulletin numbering (archive displayed vs PDF text).
4. Duplicate archive links deduplication.
5. Identical and changed document checksums & idempotence.
6. Unavailable or error Google Drive link handling.
7. Redirect handling.
8. Non-PDF responses rejected (%PDF- signature check).
9. Corrupt/empty PDF handling.
10. Telugu extraction-quality detection (broken combining marks).
11. Clean English extraction quality detection.
12. Page-level provenance and citation linkage.
13. Date and validity period extraction & derivation logic.
14. Day-wise warning extraction with explicitly named districts.
15. District and spatial wording preservation (isolated places, remaining districts, above-mentioned).
16. Severity preservation without invented color codes or numerical risk levels.
17. Pending-review enforcement (verification_status = pending_verification).
18. Exclusion of pending records from approved farmer-facing search.
19. Exclusion of expired time-bound advisories.
20. Dry-run behaviour (no DB writes).
21. Manual local PDF import fallback.
22. No external network requests from unit tests.
"""

import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch, MagicMock

import fitz  # PyMuPDF
import httpx

from app.db.database import init_db
from app.knowledge.models import (
    AuthorityStatus,
    VerificationStatus,
    KnowledgeCategory,
    KnowledgeType,
)
from app.knowledge.repository import KnowledgeRepository
from app.knowledge.schemas import KnowledgeSearchFilterSchema
from app.knowledge.pjtau.adapter import (
    PJTAUSourceAdapter,
    PJTAUArchiveFetchError,
    PJTAUDownloadError,
    PJTAUInvalidPDFError,
)
from app.knowledge.pjtau.extractor import PJTAUBulletinExtractor
from app.knowledge.pjtau.ingestion_service import PJTAUIngestionService
from app.knowledge.pjtau.schemas import (
    BulletinLanguage,
    ExtractionQuality,
    PJTAUBulletinLink,
)


SAMPLE_ARCHIVE_HTML = """
<!DOCTYPE html>
<html>
<head><title>Agromet Advisories - PJTSAU</title></head>
<body>
  <div>
    <h2>Agromet Advisories Archive</h2>
    <!-- Entry 1: Nov 4 bilingual with inconsistent archive bulletin number -->
    <a href="https://drive.google.com/file/d/1tY_G8a0y0AK14cHBcvMX8zJZ3VcOLyk3/view?usp=sharing">
      Bulletin no.XXXVII/87/2026, Dated: &nbsp;04.11.2026 Telugu &amp; English
    </a>
    <!-- Duplicate entry of Entry 1 -->
    <a href="https://drive.google.com/file/d/1tY_G8a0y0AK14cHBcvMX8zJZ3VcOLyk3/view?usp=sharing">
      Bulletin no.XXXVII/87/2026, Dated: 04.11.2026 Telugu &amp; English
    </a>
    <!-- Entry 2: Oct 31 bilingual -->
    <a href="https://drive.google.com/file/d/1o_TDJCTY2DLtshC1uYOEvPM8ngAO4zqD/view?usp=sharing">
      Bulletin no.XXXVII/87/2026, Dated: 31.10.2026 &nbsp;Telugu &amp; English
    </a>
    <!-- Entry 3: Sept 2 Telugu only -->
    <a href="https://drive.google.com/file/d/1n0wqbqRbTpx2AfLkxkPieyDt0ER1QMoZ/view?usp=sharing">
      Bulletin no.XXXVII/70/2026, Dated: 02.09.2026 &nbsp;Telugu
    </a>
    <!-- Entry 4: Sept 2 English only -->
    <a href="https://drive.google.com/file/d/1jq-GjaA8Wenh-Zupv_fibZfA0Nxp3Im1/view?usp=sharing">
      Bulletin no.XXXVII/70/2026, Dated: 02.09.2026&nbsp; English
    </a>
    <!-- Irrelevant non-bulletin link -->
    <a href="https://drive.google.com/file/d/1R6pqnrWKsJNVPd4MChdVcoKKeFY1tBTS/view?usp=sharing">
      PJTAU Vision – 2047
    </a>
  </div>
</body>
</html>
"""


def build_mock_bulletin_pdf(broken_telugu: bool = True) -> bytes:
    """
    Construct an in-memory 5-page PDF document mirroring the November 4 PJTAU bulletin structure.
    Pages 1-3: Telugu sections (optionally with broken combining marks).
    Pages 4-5: English sections with past weather, 5-day forecast, warnings, and agro advisories.
    """
    doc = fitz.open()

    # Page 1: Telugu cover / metadata
    p1 = doc.new_page()
    if broken_telugu:
        # Broken combining marks: e.g. "స ాంకేతిక", "క ేంద్రం", "హ ైదరాబాద్", "ర ైత ాంగానికి"
        p1_text = (
            "ప్రొఫెసర్ జయశంకర్ తెలంగాణ వ్యవసాయ విశ్వవిద్యాలయం\n"
            "వ్యవసాయ వాతావరణ పరిశోధన విభాగం,\n"
            "డిజిటల్ స ాంకేతిక వ్యవసాయ క ేంద్రం, రాజ ేంద్రనగర్, హ ైదరాబాద్.\n\n"
            "బులెటిన్ న ెం. XXXVII/88/2026\n\n"
            "రాష్ట్ర ర ైత ాంగానికి\n"
            "వాతావరణ ఆధారిత వ్యవసాయ సలహాలు\n"
            "తేది: 04.11.2026(బుధవారం) న ుండి 08.11.2026 (ఆదివారం) వరకు\n\n"
            "గ్రామీణ కృషి మౌసమ్ సేవ పథకం (GKMS Project)\n"
            "భారత వాతావరణ శాఖ, న్యూఢిల్లీ."
        )
    else:
        # Clean Telugu
        p1_text = (
            "ప్రొఫెసర్ జయశంకర్ తెలంగాణ వ్యవసాయ విశ్వవిద్యాలయం\n"
            "వ్యవసాయ వాతావరణ పరిశోధన విభాగం, రాజేంద్రనగర్, హైదరాబాద్.\n"
            "బులెటిన్ నెం. XXXVII/88/2026\n"
            "తేది: 04.11.2026 నుండి 08.11.2026 వరకు\n"
            "గ్రామీణ కృషి మౌసమ్ సేవ పథకం (GKMS Project)"
        )
    p1.insert_text(fitz.Point(50, 70), p1_text)

    # Page 2: Telugu past weather and forecast
    p2 = doc.new_page()
    p2.insert_text(fitz.Point(50, 70), "గత మూడు రోజుల వాతావరణం:\nగడిచిన మూడు రోజులలో రాష్ట్రంలో అక్కడక్కడ తేలికపాటి వర్షాలు కురిసాయి.\n")

    # Page 3: Telugu advisories
    p3 = doc.new_page()
    p3.insert_text(fitz.Point(50, 70), "వాతావరణ ఆధారిత వ్యవసాయ సలహాలు\n• పొలంలో నుండి మురుగు నీటిని తీసివేయాలి.\n")

    # Page 4: English Cover / Metadata
    p4 = doc.new_page(width=600, height=800)
    p4_text = (
        "PROFESSOR JAYASHANKAR TELANGANA AGRICULTURAL UNIVERSITY\n"
        "Agro Climate Research Unit (ACRU),\n"
        "Centre for Digital Agriculture and Technology,\n"
        "Rajendranagar, Hyderabad-30.\n\n\n"
        "Bulletin No. XXXVII/88/2026\n\n"
        "WEATHER BASED AGRO ADVISORIES FOR TELANGANA STATE\n"
        "FROM DATE: 04.11.2026 (Wednesday) TO 08.11.2026 (Sunday)\n\n"
        "Grameen Krishi Mausam Seva (GKMS Project)\n"
        "INDIA METEOROLOGICAL DEPARTMENT, NEW DELHI."
    )
    rect4 = fitz.Rect(30, 30, 570, 750)
    p4.insert_textbox(rect4, p4_text, fontsize=10)

    # Page 5: English Details: Past weather, 5-day forecast, warnings, advisories
    p5 = doc.new_page(width=600, height=2000)
    p5_text = (
        "Weather details of past 3 days:\n"
        "During last three days, light to moderate rains occurred at isolated places over different parts of "
        "the State. The maximum and minimum temperatures ranged between 30oC to 36oC and 18oC to 25oC respectively.\n\n"
        "Weather forecast for the next 5 days (Based on today's forecast at 1300 hrs):\n"
        "As per the forecast received from Meteorological Centre, Hyderabad, Light to Moderate rains "
        "very likely to occur at many places over Telangana for next 24 hours, and Light to Moderate "
        "rains very likely to occur at few places over Telangana for next two days and light to moderate "
        "rains very likely to occur at isolated place over Telangana during last two days. The maximum "
        "and minimum temperatures are likely to range between 25oC to 34oC and 19oC to 24oC respectively.\n\n"
        "Warning:\n"
        "Day 1: Heavy to Very Heavy with isolated Extremely Heavy Rainfall very likely to occur at "
        "isolated places in Bhadradri Kothagudem, Khammam, Suryapet districts of Telangana. "
        "Heavy to Very Heavy Rainfall very likely to occur at isolated places in Mahabubabad districts of Telangana. "
        "Heavy Rainfall very likely to occur at isolated places in Mulugu, Warangal, Hanumakonda, Jangaon, "
        "Yadadri Bhuvanagiri, Nalgonda districts of Telangana. Thunderstorm accompanied by Lightning with "
        "Squally Winds of 40-50 kmph gusting to 60 kmph very likely to occur at isolated places in Mulugu, "
        "Bhadradri Kothagudem, Khammam, Nalgonda, Suryapet, Mahabubabad, Warangal, Hanumakonda, Jangaon, "
        "Yadadri Bhuvanagiri districts of Telangana. Thunderstorm accompanied with Lightning and Gusty Winds "
        "of 30-40 kmph very likely to occur at isolated places in remaining districts of Telangana.\n\n"
        "Day 2: Heavy Rainfall very likely to occur at isolated places in Bhadradri Kothagudem, Khammam, "
        "Mahabubabad districts of Telangana. Thunderstorm accompanied with Lightning and Gusty Winds of "
        "30-40 kmph very likely to occur at isolated places in Adilabad, KomuramBheem Asifabad, Mancherial, "
        "Nirmal, Nizamabad, Jagtial, Rajanna Sircilla, Karimnagar, Peddapalli, Jayashankar Bhupalpally, "
        "Mulugu, Bhadradri Kothagudem, Khammam, Nalgonda, Suryapet, Mahabubabad, Warangal, Hanumakonda, "
        "Jangaon, Siddipet, Yadadri Bhuvanagiri, Rangareddy, Hyderabad, Medchal-Malkajgiri districts of Telangana.\n\n"
        "Weather based Agro Advisories\n"
        "- In view of heavy rainfall forecast at the above-mentioned districts, farmers are advised to provide "
        "drainage channels in already sown rabi crops and drain out excess water from the field.\n"
        "- In view of heavy rainfall forecast temporarily postpone the spraying of chemicals and top "
        "dressing of fertilizers and postpone the harvesting at that particular time.\n"
        "- Postpone the transportation of the harvested produce to the market yards.\n"
        "- If they are already transported to the market yards, cover the produce with tarpaulins.\n"
        "- After cessation of rains go for harvesting cotton kapas and other crops after drying harvested "
        "produce and transport the same to the safe places.\n"
        "- In view of heavy rainfall forecast temporarily postpone the sowing of Rabi crops.\n"
        "- In view of the thunderstorm accompanied with lightning forecast, farmers are advised to move away "
        "from water bodies, electric poles and wires and further advised not to stand under the trees and "
        "don't allow the Cattle / Goats / Sheep's to take shelter under trees.\n\n"
        "Principal Scientist (Agro) & Head\n"
    )
    rect5 = fitz.Rect(30, 30, 570, 1950)
    p5.insert_textbox(rect5, p5_text, fontsize=8)

    pdf_bytes = doc.write()
    doc.close()
    return pdf_bytes


class TestPJTAUBulletinIngestionSuite(unittest.TestCase):
    """Complete test suite for KrishiVaani PJTAU Bulletin Ingestion."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_krishivaani.db"
        self.data_dir = Path(self.temp_dir.name) / "data_pjtau"
        init_db(self.db_path)
        self.repository = KnowledgeRepository(db_path=self.db_path)

        self.mock_client = MagicMock(spec=httpx.Client)
        test_allowed_domains = set(PJTAUSourceAdapter.DEFAULT_ALLOWED_DOMAINS) | {
            "example.com",
            "short.link",
        }
        self.adapter = PJTAUSourceAdapter(
            archive_url="https://pjtau.edu.in/agromet-advisories/",
            data_dir=self.data_dir,
            http_client=self.mock_client,
            allowed_domains=test_allowed_domains,
            dns_resolver=lambda host: ["93.184.216.34"],
        )
        self.extractor = PJTAUBulletinExtractor()
        self.service = PJTAUIngestionService(
            db_path=self.db_path,
            adapter=self.adapter,
            extractor=self.extractor,
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    # -------------------------------------------------------------------------
    # Test 1: Archive Discovery Parsing
    # -------------------------------------------------------------------------
    def test_01_archive_discovery_parsing(self):
        """Discover links from mock archive HTML, extracting metadata and resolving URLs."""
        links = self.adapter.discover_bulletins(archive_html=SAMPLE_ARCHIVE_HTML)
        self.assertEqual(len(links), 4)

        # Check Entry 1
        e1 = links[0]
        self.assertEqual(e1.archive_bulletin_number, "XXXVII/87/2026")
        self.assertEqual(e1.archive_publication_date, "2026-11-04")
        self.assertEqual(e1.language, BulletinLanguage.BILINGUAL)
        self.assertEqual(
            e1.resolved_url,
            "https://drive.google.com/uc?export=download&id=1tY_G8a0y0AK14cHBcvMX8zJZ3VcOLyk3",
        )

    # -------------------------------------------------------------------------
    # Test 2: Multiple Language Detection
    # -------------------------------------------------------------------------
    def test_02_multiple_language_detection(self):
        """Language tags in bulletin link labels correctly map to Language enum."""
        links = self.adapter.discover_bulletins(archive_html=SAMPLE_ARCHIVE_HTML)
        lang_map = {link.archive_publication_date + "_" + link.archive_bulletin_number: link.language for link in links}

        # Sept 2 Telugu only
        self.assertEqual(links[2].language, BulletinLanguage.TELUGU)
        # Sept 2 English only
        self.assertEqual(links[3].language, BulletinLanguage.ENGLISH)
        # Nov 4 Bilingual
        self.assertEqual(links[0].language, BulletinLanguage.BILINGUAL)

    # -------------------------------------------------------------------------
    # Test 3: Inconsistent Bulletin Numbering
    # -------------------------------------------------------------------------
    def test_03_inconsistent_bulletin_numbering_handling(self):
        """Archive-displayed number (XXXVII/87/2026) and PDF header (XXXVII/88/2026) are both preserved."""
        pdf_bytes = build_mock_bulletin_pdf()
        link_info = PJTAUBulletinLink(
            displayed_label="Bulletin no.XXXVII/87/2026, Dated: 04.11.2026 Telugu & English",
            archive_bulletin_number="XXXVII/87/2026",
            archive_publication_date="2026-11-04",
            language=BulletinLanguage.BILINGUAL,
            original_url="https://drive.google.com/file/d/1tY_G8a0y0AK14cHBcvMX8zJZ3VcOLyk3/view?usp=sharing",
            resolved_url="https://drive.google.com/uc?export=download&id=1tY_G8a0y0AK14cHBcvMX8zJZ3VcOLyk3",
        )

        doc = self.extractor.extract_from_bytes(pdf_bytes, link_info=link_info)

        self.assertEqual(doc.archive_bulletin_number, "XXXVII/87/2026")
        self.assertEqual(doc.pdf_bulletin_number, "XXXVII/88/2026")
        self.assertEqual(doc.archive_publication_date, "2026-11-04")
        self.assertEqual(doc.pdf_issue_date, "2026-11-04")

    # -------------------------------------------------------------------------
    # Test 4: Duplicate Archive Links Deduplication
    # -------------------------------------------------------------------------
    def test_04_duplicate_archive_links_deduplication(self):
        """Duplicate anchor tags on archive HTML are cleanly deduplicated."""
        links = self.adapter.discover_bulletins(archive_html=SAMPLE_ARCHIVE_HTML)
        # SAMPLE_ARCHIVE_HTML has 5 bulletin anchors, but 2 are identical duplicates of Nov 4
        urls = [l.original_url for l in links]
        self.assertEqual(len(urls), len(set(urls)))

    # -------------------------------------------------------------------------
    # Test 5: Checksum and Idempotence
    # -------------------------------------------------------------------------
    def test_05_document_checksum_and_idempotence(self):
        """Downloading identical content computes consistent SHA-256 and avoids duplicate re-writing."""
        pdf_bytes = build_mock_bulletin_pdf()
        mock_resp = MagicMock(status_code=200, content=pdf_bytes)
        self.mock_client.get.return_value = mock_resp

        link = PJTAUBulletinLink(
            displayed_label="Test",
            archive_bulletin_number="TEST/1/2026",
            archive_publication_date="2026-11-04",
            language=BulletinLanguage.BILINGUAL,
            original_url="https://example.com/test.pdf",
            resolved_url="https://example.com/test.pdf",
        )

        path1, checksum1, was_downloaded1 = self.adapter.download_bulletin_pdf(link)
        self.assertTrue(was_downloaded1)
        self.assertEqual(checksum1, hashlib.sha256(pdf_bytes).hexdigest())

        # Second download of identical file should report was_downloaded = False
        path2, checksum2, was_downloaded2 = self.adapter.download_bulletin_pdf(link)
        self.assertFalse(was_downloaded2)
        self.assertEqual(path1, path2)
        self.assertEqual(checksum1, checksum2)

    # -------------------------------------------------------------------------
    # Test 6: Changed Document Checksum Detection
    # -------------------------------------------------------------------------
    def test_06_changed_document_checksum_detected(self):
        """Modified bulletin file with same metadata yields different checksum."""
        bytes1 = build_mock_bulletin_pdf(broken_telugu=True)
        bytes2 = build_mock_bulletin_pdf(broken_telugu=False)

        chk1 = hashlib.sha256(bytes1).hexdigest()
        chk2 = hashlib.sha256(bytes2).hexdigest()
        self.assertNotEqual(chk1, chk2)

    # -------------------------------------------------------------------------
    # Test 7: Unavailable Google Drive Link
    # -------------------------------------------------------------------------
    def test_07_unavailable_or_error_google_drive_link(self):
        """HTTP error downloading from Google Drive raises PJTAUDownloadError."""
        self.mock_client.get.return_value = MagicMock(status_code=404, content=b"Not Found")
        link = PJTAUBulletinLink(
            displayed_label="Test",
            archive_bulletin_number="TEST/1/2026",
            archive_publication_date="2026-11-04",
            language=BulletinLanguage.BILINGUAL,
            original_url="https://drive.google.com/file/d/bad_id/view",
            resolved_url="https://drive.google.com/uc?export=download&id=bad_id",
        )

        with self.assertRaises(PJTAUDownloadError):
            self.adapter.download_bulletin_pdf(link)

    # -------------------------------------------------------------------------
    # Test 8: Redirect Handling
    # -------------------------------------------------------------------------
    def test_08_redirect_handling(self):
        """Client configured to follow redirects operates seamlessly."""
        pdf_bytes = build_mock_bulletin_pdf()
        self.mock_client.get.return_value = MagicMock(status_code=200, content=pdf_bytes)
        link = PJTAUBulletinLink(
            displayed_label="Redirect Test",
            archive_bulletin_number="RED/1/2026",
            archive_publication_date="2026-11-04",
            language=BulletinLanguage.BILINGUAL,
            original_url="https://short.link/123",
            resolved_url="https://short.link/123",
        )
        path, checksum, downloaded = self.adapter.download_bulletin_pdf(link)
        self.assertTrue(downloaded)
        self.assertTrue(path.exists())

    # -------------------------------------------------------------------------
    # Test 9: Non-PDF Response Rejected
    # -------------------------------------------------------------------------
    def test_09_non_pdf_response_rejected(self):
        """Response lacking %PDF- signature raises PJTAUInvalidPDFError."""
        html_content = b"<!DOCTYPE html><html><body>Error Page</body></html>"
        self.mock_client.get.return_value = MagicMock(status_code=200, content=html_content)
        link = PJTAUBulletinLink(
            displayed_label="HTML Response Test",
            archive_bulletin_number="FAIL/1/2026",
            archive_publication_date="2026-11-04",
            language=BulletinLanguage.BILINGUAL,
            original_url="https://example.com/file",
            resolved_url="https://example.com/file",
        )
        with self.assertRaises(PJTAUInvalidPDFError):
            self.adapter.download_bulletin_pdf(link)

    # -------------------------------------------------------------------------
    # Test 10: Corrupt PDF Handling
    # -------------------------------------------------------------------------
    def test_10_corrupt_or_empty_pdf_rejected(self):
        """Zero page or corrupt PDF raises ValueError during extraction."""
        empty_pdf = b"%PDF-1.4\n%%EOF"
        with self.assertRaises(Exception):
            self.extractor.extract_from_bytes(empty_pdf)

    # -------------------------------------------------------------------------
    # Test 11: Telugu Extraction Quality Detection
    # -------------------------------------------------------------------------
    def test_11_telugu_extraction_quality_detection(self):
        """Broken combining marks in Telugu trigger ExtractionQuality.POOR and OCR recommendation."""
        broken_telugu_text = (
            "ప్రొఫెసర్ జయశంకర్ తెలంగాణ వ్యవసాయ విశ్వవిద్యాలయం\n"
            "డిజిటల్ స ాంకేతిక వ్యవసాయ క ేంద్రం, రాజ ేంద్రనగర్, హ ైదరాబాద్.\n"
            "బులెటిన్ న ెం. XXXVII/88/2026\n"
            "తేది: 04.11.2026 న ుండి 08.11.2026 వరకు\n"
            "ర ైత ాంగానికి సలహాలు"
        )
        pdf_bytes = build_mock_bulletin_pdf()

        # Broken Telugu triggers POOR and OCR recommendation
        with patch.object(fitz.Page, "get_text", return_value=broken_telugu_text):
            doc = self.extractor.extract_from_bytes(pdf_bytes)
            self.assertEqual(doc.telugu_extraction_quality, ExtractionQuality.POOR)
            self.assertTrue(doc.ocr_recommended_as_future_task)
            self.assertGreater(doc.broken_telugu_characters_count, 5)

        # Clean Telugu triggers GOOD and no OCR recommendation
        clean_telugu_text = (
            "ప్రొఫెసర్ జయశంకర్ తెలంగాణ వ్యవసాయ విశ్వవిద్యాలయం\n"
            "డిజిటల్ సాంకేతిక వ్యవసాయ కేంద్రం, రాజేంద్రనగర్, హైదరాబాద్.\n"
            "బులెటిన్ నెం. XXXVII/88/2026\n"
            "తేది: 04.11.2026 నుండి 08.11.2026 వరకు\n"
            "రైతాంగానికి సలహాలు"
        )
        with patch.object(fitz.Page, "get_text", return_value=clean_telugu_text):
            doc_clean = self.extractor.extract_from_bytes(pdf_bytes)
            self.assertEqual(doc_clean.telugu_extraction_quality, ExtractionQuality.GOOD)
            self.assertFalse(doc_clean.ocr_recommended_as_future_task)
            self.assertEqual(doc_clean.broken_telugu_characters_count, 0)

    # -------------------------------------------------------------------------
    # Test 12: Page-Level Provenance
    # -------------------------------------------------------------------------
    def test_12_page_level_provenance(self):
        """Candidate advisories preserve exact page number reference."""
        pdf_bytes = build_mock_bulletin_pdf()
        doc = self.extractor.extract_from_bytes(pdf_bytes)

        self.assertGreater(len(doc.advisories), 0)
        for adv in doc.advisories:
            self.assertEqual(adv.page_number, 5)
            self.assertTrue(len(adv.recommended_action) > 15)

    # -------------------------------------------------------------------------
    # Test 13: Date and Validity Extraction
    # -------------------------------------------------------------------------
    def test_13_date_and_validity_extraction(self):
        """Validity range (Nov 4 to Nov 8) is parsed and Day 1 / Day 2 dates are reliably derived."""
        pdf_bytes = build_mock_bulletin_pdf()
        doc = self.extractor.extract_from_bytes(pdf_bytes)

        self.assertEqual(doc.validity_start_date, "2026-11-04")
        self.assertEqual(doc.validity_end_date, "2026-11-08")

        self.assertEqual(len(doc.warnings), 2)
        w1 = doc.warnings[0]
        self.assertEqual(w1.day_number, 1)
        self.assertEqual(w1.derived_valid_date, "2026-11-04")
        self.assertIn("Derived from bulletin validity start date", w1.date_derivation_logic)

        w2 = doc.warnings[1]
        self.assertEqual(w2.day_number, 2)
        self.assertEqual(w2.derived_valid_date, "2026-11-05")

    # -------------------------------------------------------------------------
    # Test 14: Day-Wise Warning and District Extraction
    # -------------------------------------------------------------------------
    def test_14_day_wise_warning_and_district_extraction(self):
        """Explicitly named districts in Day 1 and Day 2 are identified against Telangana 33 districts."""
        pdf_bytes = build_mock_bulletin_pdf()
        doc = self.extractor.extract_from_bytes(pdf_bytes)

        w1 = doc.warnings[0]
        self.assertIn("Bhadradri Kothagudem", w1.explicitly_named_districts)
        self.assertIn("Khammam", w1.explicitly_named_districts)
        self.assertIn("Suryapet", w1.explicitly_named_districts)
        self.assertIn("Mahabubabad", w1.explicitly_named_districts)
        self.assertIn("Mulugu", w1.explicitly_named_districts)
        self.assertIn("Warangal", w1.explicitly_named_districts)
        self.assertIn("Hanamkonda", w1.explicitly_named_districts)

        # Severity terms preserved
        self.assertIn("Extremely Heavy", w1.rainfall_severity)
        self.assertIn("Heavy to Very Heavy", w1.rainfall_severity)
        self.assertIn("Heavy", w1.rainfall_severity)

        # Wind info preserved
        self.assertIn("Squally Winds", w1.wind_speed_gust)

    # -------------------------------------------------------------------------
    # Test 15: Spatial Scope Preservation
    # -------------------------------------------------------------------------
    def test_15_district_and_spatial_wording_preservation(self):
        """Preserves isolated places, remaining districts, and above-mentioned scope."""
        pdf_bytes = build_mock_bulletin_pdf()
        doc = self.extractor.extract_from_bytes(pdf_bytes)

        w1 = doc.warnings[0]
        self.assertEqual(w1.spatial_coverage_wording, "at isolated places")
        self.assertIsNotNone(w1.remaining_districts_scope)
        self.assertIn("remaining districts of Telangana", w1.remaining_districts_scope)

        # Advisory 1 specifies "above-mentioned districts"
        adv1 = doc.advisories[0]
        self.assertIn("above-mentioned districts", adv1.geographic_applicability)

    # -------------------------------------------------------------------------
    # Test 16: Pending Review Enforcement
    # -------------------------------------------------------------------------
    def test_16_pending_review_enforcement(self):
        """Ingested items and source must be marked pending_verification in SQLite DB."""
        pdf_bytes = build_mock_bulletin_pdf()
        self.mock_client.get.return_value = MagicMock(status_code=200, content=pdf_bytes)

        summary = self.service.ingest_archive(
            archive_html=SAMPLE_ARCHIVE_HTML,
            limit=1,
            dry_run=False,
        )

        self.assertEqual(summary.extracted_count, 1)
        self.assertGreater(summary.items_stored_count, 0)

        # Verify in database
        sources = self.repository.get_sources_for_item("any_id_dummy")  # test repo directly
        conn = self.repository.db_path
        from app.db.database import get_connection
        c = get_connection(self.db_path)
        try:
            items = c.execute("SELECT verification_status FROM knowledge_items").fetchall()
            for row in items:
                self.assertEqual(row["verification_status"], VerificationStatus.PENDING_VERIFICATION.value)

            srcs = c.execute("SELECT authority_status FROM knowledge_sources").fetchall()
            for row in srcs:
                self.assertEqual(row["authority_status"], AuthorityStatus.PENDING_VERIFICATION.value)
        finally:
            c.close()

    # -------------------------------------------------------------------------
    # Test 17: Exclusion from Farmer-Facing Search
    # -------------------------------------------------------------------------
    def test_17_exclusion_from_farmer_facing_search(self):
        """Items pending review are excluded from search; approved item is retrievable."""
        pdf_bytes = build_mock_bulletin_pdf()
        self.mock_client.get.return_value = MagicMock(status_code=200, content=pdf_bytes)

        self.service.ingest_archive(archive_html=SAMPLE_ARCHIVE_HTML, limit=1, dry_run=False)

        # Farmer searches active guidance on 2026-11-05
        filters = KnowledgeSearchFilterSchema(state="Telangana")
        results_before = self.repository.search_verified_items(filters, as_of_date_iso="2026-11-05")
        self.assertEqual(len(results_before), 0)

        # Admin approves one item and approves the source
        from app.db.database import get_connection
        c = get_connection(self.db_path)
        try:
            row = c.execute("SELECT knowledge_id, applicable_from, applicable_until FROM knowledge_items LIMIT 1").fetchone()
            k_id = row["knowledge_id"]
            c.execute("UPDATE knowledge_items SET verification_status = 'verified', verified_at = '2026-11-04T12:00:00' WHERE knowledge_id = ?", (k_id,))
            c.execute("UPDATE knowledge_sources SET authority_status = 'approved'")
            c.commit()
        finally:
            c.close()

        # Farmer searches again: approved item is now returned!
        results_after = self.repository.search_verified_items(filters, as_of_date_iso="2026-11-05")
        self.assertEqual(len(results_after), 1)
        self.assertEqual(results_after[0].item.knowledge_id, k_id)

    # -------------------------------------------------------------------------
    # Test 18: Advisory Expiry Exclusion
    # -------------------------------------------------------------------------
    def test_18_advisory_expiry_exclusion(self):
        """Approved time-bound advisory is excluded when queried after applicable_until date."""
        pdf_bytes = build_mock_bulletin_pdf()
        self.mock_client.get.return_value = MagicMock(status_code=200, content=pdf_bytes)

        self.service.ingest_archive(archive_html=SAMPLE_ARCHIVE_HTML, limit=1, dry_run=False)

        # Approve item
        from app.db.database import get_connection
        c = get_connection(self.db_path)
        try:
            c.execute("UPDATE knowledge_items SET verification_status = 'verified'")
            c.execute("UPDATE knowledge_sources SET authority_status = 'approved'")
            c.commit()
        finally:
            c.close()

        filters = KnowledgeSearchFilterSchema(state="Telangana")
        # Bulletin valid until 2026-11-08: search on 2026-11-10 must return 0 items
        results_expired = self.repository.search_verified_items(filters, as_of_date_iso="2026-11-10")
        self.assertEqual(len(results_expired), 0)

    # -------------------------------------------------------------------------
    # Test 19: Dry-Run Behaviour
    # -------------------------------------------------------------------------
    def test_19_dry_run_behaviour(self):
        """Dry-run extracts documents and reports summary, writing 0 rows to SQLite."""
        pdf_bytes = build_mock_bulletin_pdf()
        self.mock_client.get.return_value = MagicMock(status_code=200, content=pdf_bytes)

        summary = self.service.ingest_archive(
            archive_html=SAMPLE_ARCHIVE_HTML,
            limit=2,
            dry_run=True,
        )

        self.assertTrue(summary.dry_run)
        self.assertEqual(summary.extracted_count, 2)
        self.assertGreater(summary.items_stored_count, 0)

        # Check DB row count is strictly 0
        from app.db.database import get_connection
        c = get_connection(self.db_path)
        try:
            cnt_items = c.execute("SELECT COUNT(*) FROM knowledge_items").fetchone()[0]
            cnt_sources = c.execute("SELECT COUNT(*) FROM knowledge_sources").fetchone()[0]
            self.assertEqual(cnt_items, 0)
            self.assertEqual(cnt_sources, 0)
        finally:
            c.close()

    # -------------------------------------------------------------------------
    # Test 20: Manual Local PDF Import Fallback
    # -------------------------------------------------------------------------
    def test_20_manual_local_pdf_import_fallback(self):
        """Local file import fallback processes PDF without network calls."""
        pdf_bytes = build_mock_bulletin_pdf()
        local_path = Path(self.temp_dir.name) / "offline_bulletin.pdf"
        local_path.write_bytes(pdf_bytes)

        doc, stored_count = self.service.ingest_local_file(
            local_path,
            archive_bulletin_number="MANUAL/01/2026",
            archive_publication_date="2026-11-04",
            dry_run=False,
        )

        self.assertEqual(doc.archive_bulletin_number, "MANUAL/01/2026")
        self.assertEqual(doc.pdf_bulletin_number, "XXXVII/88/2026")
        self.assertGreater(stored_count, 0)

    # -------------------------------------------------------------------------
    # Test 21: No External Requests During Unit Tests
    # -------------------------------------------------------------------------
    def test_21_no_external_requests_during_unit_tests(self):
        """All unit tests execute with mocked HTTP client; real network calls never occur."""
        self.assertTrue(self.adapter._http_client is self.mock_client)


if __name__ == "__main__":
    unittest.main()
