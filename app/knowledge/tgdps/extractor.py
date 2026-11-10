"""
TGDPS Daily Weather Report Extractor.
Extracts structured meteorological data from official TGDPS Daily Weather Report PDFs:
- Report publication date & 24-hour observation period (Page 1)
- State-wide & GHMC highest rainfall observations (Page 1)
- District-wise rainfall summaries with actual, normal, deviation, and rainy days (Page 2)
- Top 10 mandal/station rainfall observations (Page 3)
Phase 6.4 - TGDPS Daily Weather Report Discovery & Ingestion.
"""

import hashlib
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple

import fitz  # PyMuPDF

from app.knowledge.tgdps.schemas import (
    TGDPSDistrictRainfallRecord,
    TGDPSStationRainfallRecord,
    TGDPSReportDocument,
    TGDPSReportLink,
    TGDPSExtractionQuality,
)

logger = logging.getLogger("krishivaani.tgdps.extractor")

MONTH_MAP = {
    "january": 1, "jan": 1,
    "february": 2, "feb": 2,
    "march": 3, "mar": 3,
    "april": 4, "apr": 4,
    "may": 5,
    "june": 6, "jun": 6,
    "july": 7, "jul": 7,
    "august": 8, "aug": 8,
    "september": 9, "sep": 9, "sept": 9,
    "october": 10, "oct": 10,
    "november": 11, "nov": 11,
    "december": 12, "dec": 12,
}


def parse_rainfall_amount(val_str: Optional[str]) -> Optional[float]:
    """
    Parse rainfall amount string in millimeters.
    Distinguishes zero rainfall (0.0 mm) from missing/unavailable data ('-', 'NA', 'NR').
    Rejects malformed or negative numeric strings with ValueError.
    """
    if val_str is None:
        return None
    cleaned = val_str.strip()
    if not cleaned or cleaned in ("-", "NA", "N.A.", "NR", "N/A", "Nil", "nil", "null"):
        return None
    try:
        val = float(cleaned)
        if val < 0:
            raise ValueError(f"Rainfall amount cannot be negative: {val}")
        return val
    except ValueError as exc:
        raise ValueError(f"Malformed rainfall numeric value '{val_str}': {str(exc)}") from exc


def parse_deviation_percent(val_str: Optional[str]) -> Optional[float]:
    """Parse percentage deviation string (e.g. '300', '-100', '0', '-4%')."""
    if val_str is None:
        return None
    cleaned = val_str.strip().rstrip("%")
    if not cleaned or cleaned in ("-", "NA", "N.A.", "NR", "N/A", "null"):
        return None
    try:
        return float(cleaned)
    except ValueError as exc:
        raise ValueError(f"Malformed deviation numeric value '{val_str}': {str(exc)}") from exc


def parse_rainy_days(val_str: Optional[str]) -> Optional[int]:
    """Parse count of rainy days. Rejects negative or malformed values."""
    if val_str is None:
        return None
    cleaned = val_str.strip()
    if not cleaned or cleaned in ("-", "NA", "N.A.", "NR", "N/A", "null"):
        return None
    try:
        val = int(cleaned)
        if val < 0:
            raise ValueError(f"Rainy days count cannot be negative: {val}")
        return val
    except ValueError as exc:
        raise ValueError(f"Malformed rainy days count '{val_str}': {str(exc)}") from exc


class TGDPSReportExtractor:
    """
    Robust extractor for TGDPS Daily Weather Report documents.
    Extracts district summaries and mandal AWS readings while enforcing
    strict provenance, page citation, and numeric integrity.
    """

    OFFICIAL_PUBLISHER = "Telangana Development Planning Society (TGDPS)"

    def extract_from_file(
        self,
        pdf_path: Path,
        link_info: Optional[TGDPSReportLink] = None,
        checksum: Optional[str] = None,
    ) -> TGDPSReportDocument:
        """Extract TGDPS report from a local PDF file."""
        if not pdf_path.exists() or not pdf_path.is_file():
            raise FileNotFoundError(f"TGDPS PDF file not found: {pdf_path}")
        pdf_bytes = pdf_path.read_bytes()
        return self.extract_from_bytes(pdf_bytes, link_info=link_info, checksum=checksum)

    def extract_from_bytes(
        self,
        pdf_bytes: bytes,
        link_info: Optional[TGDPSReportLink] = None,
        checksum: Optional[str] = None,
    ) -> TGDPSReportDocument:
        """Extract TGDPS report from in-memory PDF bytes."""
        if not pdf_bytes:
            raise ValueError("Provided PDF byte buffer is empty.")

        calculated_checksum = checksum or hashlib.sha256(pdf_bytes).hexdigest()

        try:
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        except Exception as exc:
            raise ValueError(f"Failed to parse PDF stream with PyMuPDF: {str(exc)}") from exc

        if doc.page_count == 0:
            raise ValueError("Parsed PDF document contains 0 pages.")

        pdf_metadata = dict(doc.metadata or {})
        raw_text_by_page: Dict[int, str] = {}
        for idx in range(doc.page_count):
            raw_text_by_page[idx + 1] = doc[idx].get_text()

        extraction_notes: List[str] = []

        # ---------------------------------------------------------------------
        # 1. Page 1: Metadata, Observation Window, State/GHMC Extremes
        # ---------------------------------------------------------------------
        p1_text = raw_text_by_page.get(1, "")
        report_date_iso = self._extract_report_date(p1_text)
        if not report_date_iso and link_info:
            report_date_iso = link_info.report_date

        if not report_date_iso:
            report_date_iso = "1970-01-01"
            extraction_notes.append("Warning: Could not extract report date from document; defaulted to 1970-01-01.")

        obs_period = self._extract_observation_period(p1_text, report_date_iso)

        # ---------------------------------------------------------------------
        # 2. Page 2: District-wise Rainfall Status Table (All 33 districts)
        # ---------------------------------------------------------------------
        district_summaries: List[TGDPSDistrictRainfallRecord] = []
        state_avg_actual: Optional[float] = None
        state_avg_normal: Optional[float] = None

        if doc.page_count >= 2:
            district_summaries, state_avg_actual, state_avg_normal = self._extract_district_rainfall_table(
                doc[1], report_date_iso, obs_period, extraction_notes
            )
        else:
            extraction_notes.append("Warning: Document has fewer than 2 pages; district rainfall table missing.")

        # If State Average not extracted from Page 2 footer, check Page 1 summary text
        if state_avg_actual is None or state_avg_normal is None:
            match_p1_avg = re.search(
                r"State\s*(?:day)?\s*Average\s*Rainfall\s*is\s*([0-9\.]+)\s*mm\s*against\s*([0-9\.]+)\s*mm\s*Normal",
                p1_text,
                re.IGNORECASE,
            )
            if match_p1_avg:
                if state_avg_actual is None:
                    state_avg_actual = parse_rainfall_amount(match_p1_avg.group(1))
                if state_avg_normal is None:
                    state_avg_normal = parse_rainfall_amount(match_p1_avg.group(2))

        # ---------------------------------------------------------------------
        # 3. Page 3: Top 10 Mandal-wise Rainfall Observations
        # ---------------------------------------------------------------------
        station_observations: List[TGDPSStationRainfallRecord] = []
        if doc.page_count >= 3:
            station_observations = self._extract_top_mandals_table(
                doc[2], report_date_iso, obs_period, extraction_notes
            )
        else:
            extraction_notes.append("Warning: Document has fewer than 3 pages; top mandal observations missing.")

        # Also extract state/GHMC highest observations from Page 1 if present
        page1_highest = self._extract_page1_highest_observations(
            p1_text, report_date_iso, obs_period, station_observations
        )
        station_observations.extend(page1_highest)

        # ---------------------------------------------------------------------
        # 4. Extraction Quality Assessment
        # ---------------------------------------------------------------------
        if len(district_summaries) >= 30 and len(station_observations) >= 5:
            quality = TGDPSExtractionQuality.GOOD
        elif len(district_summaries) > 0 or len(station_observations) > 0:
            quality = TGDPSExtractionQuality.POOR
            extraction_notes.append("Partial extraction: expected 33 districts and 10 mandal observations.")
        else:
            quality = TGDPSExtractionQuality.CORRUPT
            extraction_notes.append("Failed to extract both district table and mandal table.")

        doc.close()

        source_url = link_info.original_url if link_info else f"urn:tgdps:report:{calculated_checksum[:16]}"
        resolved_url = link_info.resolved_url if link_info else source_url
        title = f"TGDPS Daily Weather Report ({report_date_iso})"

        return TGDPSReportDocument(
            publisher=self.OFFICIAL_PUBLISHER,
            report_title=title,
            report_date=report_date_iso,
            observation_period=obs_period,
            source_url=source_url,
            resolved_url=resolved_url,
            document_checksum=calculated_checksum,
            extraction_quality=quality,
            district_summaries=district_summaries,
            station_observations=station_observations,
            state_average_rainfall_actual_mm=state_avg_actual,
            state_average_rainfall_normal_mm=state_avg_normal,
            pdf_metadata=pdf_metadata,
            raw_text_by_page=raw_text_by_page,
            extraction_notes=extraction_notes,
        )

    # -------------------------------------------------------------------------
    # Helper: Date and Observation Window
    # -------------------------------------------------------------------------
    def _extract_report_date(self, text: str) -> Optional[str]:
        """Extract publication/status date string and convert to ISO YYYY-MM-DD."""
        # Pattern 1: e.g. "Status (07-November-2026)" or "Report on 07-November-2026"
        match = re.search(r"(?:Status\s*\(|Report\s*(?:on|as\s*on)\s*)([0-9]{1,2}[\-\./][A-Za-z0-9]+[\-\./][0-9]{2,4})", text, re.IGNORECASE)
        if match:
            return self._normalize_date(match.group(1))

        # Pattern 2: Explicit date regex DD-Month-YYYY
        match_date = re.search(r"([0-9]{1,2})[\-]([A-Za-z]+)[\-]([0-9]{4})", text)
        if match_date:
            d, m_str, y = int(match_date.group(1)), match_date.group(2).lower(), int(match_date.group(3))
            m = MONTH_MAP.get(m_str)
            if m:
                return f"{y:04d}-{m:02d}-{d:02d}"

        return None

    def _extract_observation_period(self, text: str, report_date_iso: str) -> str:
        """Extract explicit 24-hour observation window (e.g. from 06-Nov 08:30 AM to 07-Nov 08:30 AM)."""
        match = re.search(r"\((from\s+[0-9]{1,2}\-[A-Za-z]+\-[0-9]{4}\s+[0-9]{1,2}:[0-9]{2}\s*[AP]M\s+to\s+[0-9]{1,2}\-[A-Za-z]+\-[0-9]{4}\s+[0-9]{1,2}:[0-9]{2}\s*[AP]M)\)", text, re.IGNORECASE)
        if match:
            return match.group(1).strip()

        # Fallback period description
        return f"24 hours ending 08:30 AM IST on {report_date_iso}"

    def _normalize_date(self, date_str: str) -> str:
        """Convert DD-Month-YYYY or DD.MM.YYYY to ISO YYYY-MM-DD."""
        clean = date_str.strip().replace(")", "").replace("(", "")
        for sep in ["-", ".", "/"]:
            if sep in clean:
                parts = clean.split(sep)
                if len(parts) == 3:
                    try:
                        d = int(parts[0])
                        y = int(parts[2])
                        if y < 100:
                            y += 2000
                        # Month could be word or int
                        m_part = parts[1].lower()
                        if m_part in MONTH_MAP:
                            m = MONTH_MAP[m_part]
                        else:
                            m = int(m_part)
                        return f"{y:04d}-{m:02d}-{d:02d}"
                    except (ValueError, KeyError):
                        pass
        return "1970-01-01"

    # -------------------------------------------------------------------------
    # Helper: Page 2 District Rainfall Table
    # -------------------------------------------------------------------------
    def _extract_district_rainfall_table(
        self,
        page: fitz.Page,
        report_date_iso: str,
        obs_period: str,
        notes: List[str],
    ) -> Tuple[List[TGDPSDistrictRainfallRecord], Optional[float], Optional[float]]:
        """
        Extract table of district-wise rainfall status on Page 2.
        Parses all 33 Telangana districts into structured TGDPSDistrictRainfallRecord items.
        """
        records: List[TGDPSDistrictRainfallRecord] = []
        state_avg_actual: Optional[float] = None
        state_avg_normal: Optional[float] = None

        # Extract State Average row from page text
        page_lines = [l.strip() for l in page.get_text().split("\n") if l.strip()]
        for idx, line in enumerate(page_lines):
            if "state average" in line.lower():
                try:
                    parts = [p.strip() for p in line.split() if re.match(r"^[\-]?[0-9]+(?:\.[0-9]+)?$", p.strip())]
                    if len(parts) >= 2:
                        state_avg_actual = parse_rainfall_amount(parts[0])
                        state_avg_normal = parse_rainfall_amount(parts[1])
                    else:
                        following_nums = []
                        for follow in page_lines[idx + 1:]:
                            if re.match(r"^[\-]?[0-9]+(?:\.[0-9]+)?$", follow):
                                following_nums.append(follow)
                                if len(following_nums) >= 2:
                                    break
                            elif following_nums:
                                break
                        if len(following_nums) >= 2:
                            state_avg_actual = parse_rainfall_amount(following_nums[0])
                            state_avg_normal = parse_rainfall_amount(following_nums[1])
                except Exception as exc:
                    notes.append(f"Could not parse state average rainfall: {exc}")
                break

        blocks = page.get_text("blocks")

        for b in blocks:
            raw_text = b[4].strip()
            lines = [l.strip() for l in raw_text.split("\n") if l.strip()]

            # Skip standalone State Average block in row-based PDFs
            if raw_text.strip().lower().startswith("state average"):
                continue

            # Check for a district row: starts with an integer S.No (1 to 33)
            # Typically 10 lines: [S.No, District, Actual, Normal, Dev%, CumActual, CumNormal, CumDev%, Status, RainyDays]
            if len(lines) >= 9 and lines[0].isdigit():
                s_no = int(lines[0])
                if not (1 <= s_no <= 35):
                    continue

                district_name = lines[1]
                # Reject if district name looks like a header
                if any(h in district_name.lower() for h in ["district", "s.no", "actual", "cumulative", "today"]):
                    continue

                try:
                    actual = parse_rainfall_amount(lines[2])
                    normal = parse_rainfall_amount(lines[3])
                    dev_pct = parse_deviation_percent(lines[4])
                    cum_actual = parse_rainfall_amount(lines[5])
                    cum_normal = parse_rainfall_amount(lines[6])
                    cum_dev_pct = parse_deviation_percent(lines[7])
                    status = lines[8]
                    rainy_days = parse_rainy_days(lines[9]) if len(lines) >= 10 else None

                    rec = TGDPSDistrictRainfallRecord(
                        district=district_name,
                        actual_rainfall_mm=actual,
                        normal_rainfall_mm=normal,
                        deviation_percent=dev_pct,
                        cumulative_actual_mm=cum_actual,
                        cumulative_normal_mm=cum_normal,
                        cumulative_deviation_percent=cum_dev_pct,
                        status=status,
                        rainy_days=rainy_days,
                        observation_date=report_date_iso,
                        observation_period=obs_period,
                        page_number=2,
                        raw_text=raw_text,
                    )
                    records.append(rec)
                except Exception as exc:
                    notes.append(f"Failed parsing district row '{raw_text}': {str(exc)}")

        # Fallback line-by-line parsing if block parser found fewer than 20 districts
        if len(records) < 20:
            notes.append("Block parsing found < 20 districts; attempting line-by-line fallback parsing.")
            records = self._fallback_district_line_parser(page.get_text(), report_date_iso, obs_period, notes)

        return records, state_avg_actual, state_avg_normal

    def _fallback_district_line_parser(
        self,
        full_text: str,
        report_date_iso: str,
        obs_period: str,
        notes: List[str],
    ) -> List[TGDPSDistrictRainfallRecord]:
        """Line-by-line sequential scanner fallback for district table."""
        records: List[TGDPSDistrictRainfallRecord] = []
        lines = [l.strip() for l in full_text.split("\n") if l.strip()]
        i = 0
        while i < len(lines):
            # Look for S.No digit matching expected next district
            if lines[i].isdigit() and 1 <= int(lines[i]) <= 33:
                s_no = int(lines[i])
                if i + 9 < len(lines):
                    district_name = lines[i + 1]
                    try:
                        actual = parse_rainfall_amount(lines[i + 2])
                        normal = parse_rainfall_amount(lines[i + 3])
                        dev_pct = parse_deviation_percent(lines[i + 4])
                        cum_actual = parse_rainfall_amount(lines[i + 5])
                        cum_normal = parse_rainfall_amount(lines[i + 6])
                        cum_dev_pct = parse_deviation_percent(lines[i + 7])
                        status = lines[i + 8]
                        rainy_days = parse_rainy_days(lines[i + 9])

                        rec = TGDPSDistrictRainfallRecord(
                            district=district_name,
                            actual_rainfall_mm=actual,
                            normal_rainfall_mm=normal,
                            deviation_percent=dev_pct,
                            cumulative_actual_mm=cum_actual,
                            cumulative_normal_mm=cum_normal,
                            cumulative_deviation_percent=cum_dev_pct,
                            status=status,
                            rainy_days=rainy_days,
                            observation_date=report_date_iso,
                            observation_period=obs_period,
                            page_number=2,
                            raw_text="\n".join(lines[i:i + 10]),
                        )
                        records.append(rec)
                        i += 10
                        continue
                    except Exception:
                        pass
            i += 1
        return records

    # -------------------------------------------------------------------------
    # Helper: Page 3 Top Mandal-wise Rainfall Table
    # -------------------------------------------------------------------------
    def _extract_top_mandals_table(
        self,
        page: fitz.Page,
        report_date_iso: str,
        obs_period: str,
        notes: List[str],
    ) -> List[TGDPSStationRainfallRecord]:
        """
        Extract 'Top 10 Mandal-wise Rainfall Recorded' table on Page 3.
        Maps each row to a TGDPSStationRainfallRecord.
        """
        records: List[TGDPSStationRainfallRecord] = []
        blocks = page.get_text("blocks")
        in_top10_section = False

        for b in blocks:
            raw_text = b[4].strip()
            if "top 10 mandal-wise rainfall recorded" in raw_text.lower():
                in_top10_section = True
                continue

            if in_top10_section:
                lines = [l.strip() for l in raw_text.split("\n") if l.strip()]
                # Table row structure: [Rank, District, Mandal, Rain(mm)]
                if len(lines) == 4 and lines[0].isdigit() and 1 <= int(lines[0]) <= 10:
                    rank = int(lines[0])
                    district = lines[1]
                    mandal = lines[2]
                    try:
                        rain_mm = parse_rainfall_amount(lines[3])
                        rec = TGDPSStationRainfallRecord(
                            station_or_mandal=mandal,
                            district=district,
                            rainfall_mm=rain_mm,
                            rainfall_unit="mm",
                            observation_date=report_date_iso,
                            observation_period=obs_period,
                            rank=rank,
                            page_number=3,
                            raw_text=raw_text,
                        )
                        records.append(rec)
                    except Exception as exc:
                        notes.append(f"Failed parsing top mandal row '{raw_text}': {str(exc)}")

        # Fallback line-by-line parsing if block parser found no top mandals
        if len(records) == 0:
            lines = [l.strip() for l in page.get_text().split("\n") if l.strip()]
            in_top10 = False
            i = 0
            while i < len(lines):
                if "top 10 mandal-wise rainfall recorded" in lines[i].lower():
                    in_top10 = True
                    i += 1
                    continue
                if in_top10 and lines[i].isdigit() and 1 <= int(lines[i]) <= 10:
                    rank = int(lines[i])
                    if i + 3 < len(lines):
                        dist = lines[i + 1]
                        mandal = lines[i + 2]
                        try:
                            rain_mm = parse_rainfall_amount(lines[i + 3])
                            rec = TGDPSStationRainfallRecord(
                                station_or_mandal=mandal,
                                district=dist,
                                rainfall_mm=rain_mm,
                                rainfall_unit="mm",
                                observation_date=report_date_iso,
                                observation_period=obs_period,
                                rank=rank,
                                page_number=3,
                                raw_text="\n".join(lines[i:i + 4]),
                            )
                            records.append(rec)
                            i += 4
                            continue
                        except Exception:
                            pass
                i += 1

        return records

    # -------------------------------------------------------------------------
    # Helper: Page 1 State & GHMC Highest Observations
    # -------------------------------------------------------------------------
    def _extract_page1_highest_observations(
        self,
        text: str,
        report_date_iso: str,
        obs_period: str,
        existing_mandals: List[TGDPSStationRainfallRecord],
    ) -> List[TGDPSStationRainfallRecord]:
        """
        Extract highest rainfall station readings mentioned in Page 1 narrative:
        - Highest State-Day reading (e.g. 74.8 mm at Maripeda, Mahabubabad)
        - Highest GHMC reading (e.g. 2.1 mm at Keesara, Medchal-Malkajgiri)
        """
        records: List[TGDPSStationRainfallRecord] = []
        existing_keys = {(r.station_or_mandal.lower(), r.district.lower()) for r in existing_mandals}

        # Pattern: Highest Rainfall of (VAL) mm recorded at (Mandal) ((District))
        matches = re.finditer(
            r"Highest\s+Rainfall\s+of\s+([0-9\.]+)\s*mm\s+recorded\s+at\s+([A-Za-z_\-]+)\s*\(([A-Za-z_\-\s]+)\)",
            text,
            re.IGNORECASE,
        )
        for m in matches:
            val_str, mandal_str, dist_str = m.group(1), m.group(2).strip(), m.group(3).strip()
            key = (mandal_str.lower(), dist_str.lower())
            if key in existing_keys:
                continue

            try:
                rain_val = parse_rainfall_amount(val_str)
                rec = TGDPSStationRainfallRecord(
                    station_or_mandal=mandal_str,
                    district=dist_str,
                    rainfall_mm=rain_val,
                    rainfall_unit="mm",
                    observation_date=report_date_iso,
                    observation_period=obs_period,
                    rank=None,
                    page_number=1,
                    raw_text=m.group(0),
                )
                records.append(rec)
                existing_keys.add(key)
            except Exception:
                pass

        return records
