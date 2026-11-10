"""
PJTAU Agromet Advisory Bulletin PDF Extractor.
Extracts structured meteorological observations, forecasts, day-wise warnings,
and agricultural advisories while preserving provenance, spatial scope, and text quality.
Phase 6.3 - Automatic PJTAU Bulletin Ingestion.
"""

import logging
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Dict, Tuple, Any
from zoneinfo import ZoneInfo

import fitz  # PyMuPDF

from app.knowledge.pjtau.schemas import (
    PJTAUBulletinDocument,
    PJTAUPastWeather,
    PJTAUForecast,
    PJTAUWarning,
    PJTAUAgriculturalAdvice,
    ExtractionQuality,
    PJTAUBulletinLink,
)
from app.knowledge.season_calendar import TELANGANA_33_DISTRICTS, resolve_telangana_district

logger = logging.getLogger("krishivaani.pjtau.extractor")
KOLKATA_TZ = ZoneInfo("Asia/Kolkata")


class PJTAUBulletinExtractor:
    """
    Parses PJTAU GKMS Agricultural Weather Advisories from PDF documents.
    Performs boundary-aware text extraction, quality checks, and structured section parsing.
    """

    # Telugu broken character regex: consonant followed by whitespace and a dependent vowel or virama/anusvara
    TELUGU_BROKEN_CHAR_PATTERN = re.compile(r"[\u0c05-\u0c39]\s+[\u0c3e-\u0c56\u0c01-\u0c03]")

    def __init__(self, broken_telugu_threshold: int = 5):
        self.broken_telugu_threshold = broken_telugu_threshold

    def extract_from_file(
        self,
        pdf_path: Path,
        link_info: Optional[PJTAUBulletinLink] = None,
        checksum: str = "",
    ) -> PJTAUBulletinDocument:
        """
        Open and parse a PJTAU advisory bulletin PDF from disk.
        """
        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF file does not exist: {pdf_path}")

        file_bytes = pdf_path.read_bytes()
        return self.extract_from_bytes(file_bytes, pdf_path=pdf_path, link_info=link_info, checksum=checksum)

    def extract_from_bytes(
        self,
        pdf_bytes: bytes,
        pdf_path: Optional[Path] = None,
        link_info: Optional[PJTAUBulletinLink] = None,
        checksum: str = "",
    ) -> PJTAUBulletinDocument:
        """
        Parse raw PDF bytes into a structured PJTAUBulletinDocument.
        """
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        page_count = doc.page_count
        if page_count == 0:
            raise ValueError("PDF contains 0 pages.")

        page_texts: Dict[int, str] = {}
        for page_idx in range(page_count):
            page = doc.load_page(page_idx)
            page_texts[page_idx + 1] = page.get_text()

        doc.close()

        # Combine text for analysis
        full_text = "\n\n".join(f"--- PAGE {p} ---\n{t}" for p, t in page_texts.items())

        # Check Telugu Extraction Quality
        telugu_broken_matches = self.TELUGU_BROKEN_CHAR_PATTERN.findall(full_text)
        broken_telugu_count = len(telugu_broken_matches)

        if broken_telugu_count > self.broken_telugu_threshold:
            telugu_quality = ExtractionQuality.POOR
            ocr_recommended = True
            logger.warning(
                f"Telugu extraction shows {broken_telugu_count} broken character sequences. "
                "Marking Telugu quality as POOR and recommending OCR as future task."
            )
        else:
            telugu_quality = ExtractionQuality.GOOD
            ocr_recommended = False

        english_quality = ExtractionQuality.GOOD

        # Section A: Document Metadata
        metadata = self._extract_metadata(page_texts, link_info)

        # Section B: Past Weather
        past_weather = self._extract_past_weather(page_texts)

        # Section C: 5-Day Forecast
        forecast = self._extract_forecast(page_texts)

        # Section D: Day-wise Warnings
        warnings = self._extract_warnings(page_texts, metadata.get("validity_start_date"))

        # Section E: Agricultural Advisories
        advisories = self._extract_advisories(
            page_texts,
            valid_from=metadata.get("validity_start_date"),
            valid_until=metadata.get("validity_end_date"),
        )

        now_iso = datetime.now(KOLKATA_TZ).isoformat()

        return PJTAUBulletinDocument(
            archive_bulletin_number=link_info.archive_bulletin_number if link_info else metadata.get("pdf_bulletin_number", "UNKNOWN"),
            pdf_bulletin_number=metadata.get("pdf_bulletin_number"),
            archive_publication_date=link_info.archive_publication_date if link_info else metadata.get("pdf_issue_date", "1970-01-01"),
            pdf_issue_date=metadata.get("pdf_issue_date"),
            validity_start_date=metadata.get("validity_start_date"),
            validity_end_date=metadata.get("validity_end_date"),
            publisher="Professor Jayashankar Telangana Agricultural University",
            research_unit="Agro Climate Research Unit (ACRU), Rajendranagar",
            programme="Grameen Krishi Mausam Seva (GKMS)",
            meteorological_source=metadata.get("meteorological_source", "Meteorological Centre, Hyderabad / India Meteorological Department"),
            language="te-IN,en-IN",
            original_url=link_info.original_url if link_info else "",
            resolved_url=link_info.resolved_url if link_info else "",
            document_checksum=checksum,
            file_size_bytes=len(pdf_bytes),
            page_count=page_count,
            downloaded_at=now_iso,
            raw_pdf_path=str(pdf_path) if pdf_path else None,
            telugu_extraction_quality=telugu_quality,
            english_extraction_quality=english_quality,
            broken_telugu_characters_count=broken_telugu_count,
            ocr_recommended_as_future_task=ocr_recommended,
            past_weather=past_weather,
            forecast=forecast,
            warnings=warnings,
            advisories=advisories,
            page_texts=page_texts,
        )

    # -------------------------------------------------------------------------
    # Section A: Document Metadata Parsing
    # -------------------------------------------------------------------------
    def _extract_metadata(
        self,
        page_texts: Dict[int, str],
        link_info: Optional[PJTAUBulletinLink],
    ) -> Dict[str, Any]:
        """Extract bulletin number, issue date, validity range, and attribution."""
        pdf_bulletin_number: Optional[str] = None
        pdf_issue_date: Optional[str] = None
        validity_start: Optional[str] = None
        validity_end: Optional[str] = None
        meteorological_source = "Meteorological Centre, Hyderabad / India Meteorological Department"

        for page_num, text in page_texts.items():
            # Check English or Telugu bulletin header
            # E.g. "Bulletin No. XXXVII/88/2026" or "బులెటిన్ నెం. XXXVII/88/2026"
            b_match = re.search(r"(?:Bulletin\s*No\.?|బులెటిన్\s*నెం\.?)\s*([A-Z0-9/_\-]+)", text, re.IGNORECASE)
            if b_match and not pdf_bulletin_number:
                pdf_bulletin_number = b_match.group(1).strip()

            # Validity date range: E.g. "FROM DATE: 04.11.2026 ... TO 08.11.2026"
            # Or Telugu: "తేది: 04.11.2026 ... నుండి 08.11.2026 ... వరకు"
            v_match = re.search(
                r"(?:FROM\s*DATE:?|తేది:?)\s*([0-9]{1,2}[\./\-][0-9]{1,2}[\./\-][0-9]{2,4})"
                r"(?:[^\w\n]*\([^\)]*\))?\s*(?:TO|నుండి|న\s*ుండి)\s*"
                r"([0-9]{1,2}[\./\-][0-9]{1,2}[\./\-][0-9]{2,4})",
                text,
                re.IGNORECASE,
            )
            if v_match:
                if not validity_start:
                    validity_start = self._normalize_date_str(v_match.group(1))
                    pdf_issue_date = validity_start
                if not validity_end:
                    validity_end = self._normalize_date_str(v_match.group(2))

            # Meteorological attribution
            if "Meteorological Centre, Hyderabad" in text or "హైదరాబాద్ వాతావరణ కేంద్రం" in text:
                meteorological_source = "Meteorological Centre, Hyderabad / India Meteorological Department"

        return {
            "pdf_bulletin_number": pdf_bulletin_number,
            "pdf_issue_date": pdf_issue_date,
            "validity_start_date": validity_start,
            "validity_end_date": validity_end,
            "meteorological_source": meteorological_source,
        }

    # -------------------------------------------------------------------------
    # Section B: Past Weather Parsing
    # -------------------------------------------------------------------------
    def _extract_past_weather(self, page_texts: Dict[int, str]) -> Optional[PJTAUPastWeather]:
        """Extract observed weather over the past observation window."""
        for page_num, text in page_texts.items():
            # Look for English Section B
            match = re.search(
                r"Weather\s+details\s+of\s+past\s+(\d+)\s+days:\s*\n(.*?)(?=\n\s*(?:Weather\s+forecast|Warning|Weather\s+based)|$)",
                text,
                re.IGNORECASE | re.DOTALL,
            )
            if match:
                days_count = match.group(1)
                body = match.group(2).strip()

                # Extract rainfall description
                rain_desc = body
                rain_match = re.search(r"(During\s+last\s+.*?rains\s+occurred\s+at\s+[^.]+?\.)", body, re.IGNORECASE)
                if rain_match:
                    rain_desc = rain_match.group(1).strip()

                # Extract max/min temperatures
                max_temp = None
                min_temp = None
                temp_match = re.search(
                    r"maximum\s+and\s+minimum\s+temperatures\s+ranged\s+between\s+([0-9o\s\-\.\u00b0C]+)\s+and\s+([0-9o\s\-\.\u00b0C]+)",
                    body,
                    re.IGNORECASE,
                )
                if temp_match:
                    max_temp = temp_match.group(1).strip()
                    min_temp = temp_match.group(2).strip()

                return PJTAUPastWeather(
                    observation_period=f"During last {days_count} days",
                    rainfall_description=rain_desc,
                    max_temperature_c=max_temp,
                    min_temperature_c=min_temp,
                    geographical_scope="different parts of the State",
                    original_text=body,
                )

        return None

    # -------------------------------------------------------------------------
    # Section C: 5-Day Forecast Parsing
    # -------------------------------------------------------------------------
    def _extract_forecast(self, page_texts: Dict[int, str]) -> Optional[PJTAUForecast]:
        """Extract 5-day weather forecast outlook and synoptic patterns."""
        for page_num, text in page_texts.items():
            match = re.search(
                r"Weather\s+forecast\s+for\s+the\s+next\s+(\d+)\s+days\s*(\([^)]*\))?:\s*\n(.*?)(?=\n\s*(?:Warning:|Weather\s+based)|$)",
                text,
                re.IGNORECASE | re.DOTALL,
            )
            if match:
                days_count = int(match.group(1))
                period_note = match.group(2) or ""
                body = match.group(3).strip()

                # Extract temperatures
                max_temp = None
                min_temp = None
                temp_match = re.search(
                    r"maximum\s+and\s+minimum\s+temperatures\s+are\s+likely\s+to\s+range\s+between\s+([0-9o\s\-\.\u00b0C]+)\s+and\s+([0-9o\s\-\.\u00b0C]+)",
                    body,
                    re.IGNORECASE,
                )
                if temp_match:
                    max_temp = temp_match.group(1).strip()
                    min_temp = temp_match.group(2).strip()

                # Extract spatial distribution wording
                dist_patterns = []
                for phr in ["many places", "few places", "isolated places", "isolated place"]:
                    if phr in body.lower():
                        dist_patterns.append(phr)
                spatial_wording = ", ".join(dist_patterns) if dist_patterns else "State of Telangana"

                return PJTAUForecast(
                    forecast_period=f"next {days_count} days {period_note}".strip(),
                    forecast_days_count=days_count,
                    rainfall_description=body,
                    spatial_distribution_wording=spatial_wording,
                    max_temperature_c=max_temp,
                    min_temperature_c=min_temp,
                    original_text=body,
                )

        return None

    # -------------------------------------------------------------------------
    # Section D: Day-Wise Warning Parsing
    # -------------------------------------------------------------------------
    def _extract_warnings(
        self,
        page_texts: Dict[int, str],
        validity_start_date: Optional[str],
    ) -> List[PJTAUWarning]:
        """
        Extract day-wise weather warnings, explicitly named Telangana districts,
        rainfall severity, wind speeds, and 'remaining districts' coverage.
        """
        warnings: List[PJTAUWarning] = []

        for page_num, text in page_texts.items():
            # Check for English Warning block
            w_block_match = re.search(
                r"Warning:\s*\n(.*?)(?=\n\s*(?:Weather\s+based\s+Agro\s+Advisories|Principal\s+Scientist)|$)",
                text,
                re.IGNORECASE | re.DOTALL,
            )
            if not w_block_match:
                continue

            warning_text = w_block_match.group(1).strip()

            # Split by Day N: e.g. "Day 1:", "Day 2:", etc.
            day_splits = re.split(r"(Day\s+\d+:)", warning_text, flags=re.IGNORECASE)
            # day_splits will be ['', 'Day 1:', text_1, 'Day 2:', text_2]
            current_day_num: Optional[int] = None

            for part in day_splits:
                part_clean = part.strip()
                day_header_match = re.match(r"Day\s+(\d+):", part_clean, re.IGNORECASE)
                if day_header_match:
                    current_day_num = int(day_header_match.group(1))
                    continue

                if current_day_num is not None and part_clean:
                    parsed_warning = self._parse_single_day_warning(
                        day_number=current_day_num,
                        raw_text=part_clean,
                        validity_start_date=validity_start_date,
                        page_number=page_num,
                    )
                    warnings.append(parsed_warning)
                    current_day_num = None

        return warnings

    def _parse_single_day_warning(
        self,
        day_number: int,
        raw_text: str,
        validity_start_date: Optional[str],
        page_number: int,
    ) -> PJTAUWarning:
        """Parse warning text for a single day."""
        # Derive date if validity_start_date is available
        derived_date = None
        derivation_logic = None
        if validity_start_date:
            try:
                base_dt = datetime.strptime(validity_start_date, "%Y-%m-%d").date()
                target_dt = base_dt + timedelta(days=day_number - 1)
                derived_date = target_dt.isoformat()
                derivation_logic = (
                    f"Derived from bulletin validity start date {validity_start_date} + "
                    f"{day_number - 1} day(s) for Day {day_number}."
                )
            except ValueError:
                pass

        # Identify explicitly named Telangana districts
        explicit_districts = self._find_districts_in_text(raw_text)

        # Rainfall severity preservation
        severities = []
        if re.search(r"Extremely\s+Heavy\s+Rainfall", raw_text, re.IGNORECASE):
            severities.append("Extremely Heavy")
        if re.search(r"Heavy\s+to\s+Very\s+Heavy\s+Rainfall", raw_text, re.IGNORECASE):
            severities.append("Heavy to Very Heavy")
        elif re.search(r"Very\s+Heavy\s+Rainfall", raw_text, re.IGNORECASE):
            severities.append("Very Heavy")
        if re.search(r"(?<!Very\s)Heavy\s+Rainfall", raw_text, re.IGNORECASE):
            severities.append("Heavy")
        rainfall_severity = ", ".join(severities) if severities else None

        # Thunderstorm / Lightning
        thunderstorm = None
        if re.search(r"Thunderstorm\s+accompanied\s+(?:by|with)\s+Lightning", raw_text, re.IGNORECASE):
            thunderstorm = "Thunderstorm accompanied by Lightning"

        # Wind speed / gusts
        winds = None
        wind_match = re.search(r"((?:Squally|Gusty)\s+Winds\s+of\s+[0-9\-]+\s*kmph(?:\s*gusting\s*to\s*[0-9\-]+\s*kmph)?)", raw_text, re.IGNORECASE)
        if wind_match:
            winds = wind_match.group(1).strip()

        # Remaining districts scope
        remaining_scope = None
        if re.search(r"remaining\s+districts\s+of\s+Telangana", raw_text, re.IGNORECASE):
            rem_match = re.search(r"([^.]*remaining\s+districts\s+of\s+Telangana[^.]*)", raw_text, re.IGNORECASE)
            remaining_scope = " ".join(rem_match.group(1).split()).strip() if rem_match else "remaining districts of Telangana"

        # Spatial coverage wording (e.g. "at isolated places")
        spatial_wording = "at isolated places" if "isolated places" in raw_text.lower() else None

        return PJTAUWarning(
            day_number=day_number,
            derived_valid_date=derived_date,
            date_derivation_logic=derivation_logic,
            explicitly_named_districts=explicit_districts,
            rainfall_severity=rainfall_severity,
            thunderstorm_lightning=thunderstorm,
            wind_speed_gust=winds,
            remaining_districts_scope=remaining_scope,
            spatial_coverage_wording=spatial_wording,
            original_text=raw_text,
            page_number=page_number,
        )

    # -------------------------------------------------------------------------
    # Section E: Agricultural Advisories Parsing
    # -------------------------------------------------------------------------
    def _extract_advisories(
        self,
        page_texts: Dict[int, str],
        valid_from: Optional[str],
        valid_until: Optional[str],
    ) -> List[PJTAUAgriculturalAdvice]:
        """
        Extract individual recommendations from the 'Weather based Agro Advisories' section.
        Preserves crop name, weather trigger, recommended action, geographic scope, and safety instructions.
        """
        advisories: List[PJTAUAgriculturalAdvice] = []

        for page_num, text in page_texts.items():
            adv_match = re.search(
                r"Weather\s+based\s+Agro\s+Advisories\s*\n(.*?)(?=\n\s*Principal\s+Scientist|$)",
                text,
                re.IGNORECASE | re.DOTALL,
            )
            if not adv_match:
                continue

            section_text = adv_match.group(1).strip()
            # Split by bullet points: '•', '-', '*', or line starting with bullet
            raw_bullets = re.split(r"(?:^|\n)\s*[•\-\*]\s*", section_text)

            for bullet in raw_bullets:
                clean_bullet = " ".join(bullet.split()).strip()
                if not clean_bullet or len(clean_bullet) < 15:
                    continue

                advice = self._parse_single_advisory(
                    raw_text=clean_bullet,
                    valid_from=valid_from,
                    valid_until=valid_until,
                    page_number=page_num,
                )
                advisories.append(advice)

        return advisories

    def _parse_single_advisory(
        self,
        raw_text: str,
        valid_from: Optional[str],
        valid_until: Optional[str],
        page_number: int,
    ) -> PJTAUAgriculturalAdvice:
        """Parse an individual advisory recommendation."""
        lower = raw_text.lower()

        # Identify weather condition trigger
        trigger = None
        if "heavy rainfall forecast" in lower:
            trigger = "heavy rainfall forecast"
        elif "thunderstorm" in lower and "lightning" in lower:
            trigger = "thunderstorm accompanied with lightning forecast"
        elif "after cessation of rains" in lower:
            trigger = "after cessation of rains"

        # Identify crop / crop group
        crop = None
        stage = None
        if "already sown rabi crops" in lower:
            crop = "Rabi crops"
            stage = "already sown"
        elif "sowing of rabi crops" in lower:
            crop = "Rabi crops"
            stage = "sowing"
        elif "cotton kapas" in lower:
            crop = "Cotton"
            stage = "harvesting"
        elif "harvested produce" in lower:
            crop = "Harvested crops"
            stage = "post-harvest"
        elif "crops" in lower:
            crop = "General standing crops"

        # Safety instruction check
        is_safety = bool(
            "lightning" in lower
            or "electric poles" in lower
            or "water bodies" in lower
            or "shelter under trees" in lower
            or "cattle" in lower
        )

        # Geographic applicability
        geo_scope = "State of Telangana"
        if "above-mentioned districts" in lower:
            geo_scope = "above-mentioned districts (refer to warning district coverage)"

        return PJTAUAgriculturalAdvice(
            crop_or_group=crop,
            crop_stage=stage,
            weather_condition_trigger=trigger,
            recommended_action=raw_text,
            geographic_applicability=geo_scope,
            valid_from=valid_from,
            valid_until=valid_until,
            is_safety_instruction=is_safety,
            original_text=raw_text,
            page_number=page_number,
        )

    # -------------------------------------------------------------------------
    # Helper Utilities
    # -------------------------------------------------------------------------
    def _find_districts_in_text(self, text: str) -> List[str]:
        """Match and normalize Telangana district names mentioned in the text."""
        matched: List[str] = []
        seen: Set[str] = set()

        for d_def in TELANGANA_33_DISTRICTS:
            canonical = d_def.district_name
            # Search canonical name
            pattern = r"\b" + re.escape(canonical) + r"\b"
            if re.search(pattern, text, re.IGNORECASE):
                if canonical not in seen:
                    seen.add(canonical)
                    matched.append(canonical)
                continue

            # Search aliases
            for alias in d_def.aliases:
                alias_pattern = r"\b" + re.escape(alias) + r"\b"
                if re.search(alias_pattern, text, re.IGNORECASE):
                    if canonical not in seen:
                        seen.add(canonical)
                        matched.append(canonical)
                    break

            # Special case for compound spellings like "KomuramBheem Asifabad"
            if "asifabad" in canonical.lower() and re.search(r"kom[ua]ram\s*bheem\s*asifabad", text, re.IGNORECASE):
                if canonical not in seen:
                    seen.add(canonical)
                    matched.append(canonical)

        return matched

    @classmethod
    def _normalize_date_str(cls, date_str: str) -> Optional[str]:
        """Convert DD.MM.YYYY, DD-MM-YYYY, or DD/MM/YYYY into YYYY-MM-DD."""
        for sep in [".", "-", "/"]:
            if sep in date_str:
                parts = date_str.split(sep)
                if len(parts) == 3:
                    try:
                        d, m, y = int(parts[0]), int(parts[1]), int(parts[2])
                        if y < 100:
                            y += 2000
                        return f"{y:04d}-{m:02d}-{d:02d}"
                    except ValueError:
                        pass
        return None
