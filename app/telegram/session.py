"""
Telegram Session and Consent Management Service — Phase 8.3.

Provides SQLite persistence for Telegram user sessions, explicit third-party
weather provider location-sharing consent, pending weather queries,
and localized location parameter extraction (village, mandal, district, PIN code).

Principles:
1. Keeps third-party weather-provider location sharing consent separate from
   consent to permanently save a farmer's full personal profile.
2. Persists consent and session state per Telegram user identity across restarts.
3. Does not mutate the core 'farmers' table, maintaining zero side-effects on
   unrelated knowledge base audit benchmarks.
4. Distinguishes affirmative consent, explicit rejection/withdrawal, and pending requests.
"""

import re
import time
import sqlite3
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple, Dict, Any

from app.core.config import settings
from app.services.location_service import (
    extract_pin_from_text,
    normalize_whitespace,
    normalize_indic_digits,
)
from app.knowledge.season_calendar import resolve_telangana_district

logger = logging.getLogger(__name__)

# Official 33 Telangana districts mapped from Telugu script to canonical English
TELANGANA_DISTRICTS_TE: Dict[str, str] = {
    "ఆదిలాబాద్": "Adilabad",
    "భద్రాద్రి కొత్తగూడెం": "Bhadradri Kothagudem",
    "కొత్తగూడెం": "Bhadradri Kothagudem",
    "హన్మకొండ": "Hanumakonda",
    "హనుమకొండ": "Hanumakonda",
    "హైదరాబాద్": "Hyderabad",
    "జగిత్యాల": "Jagtial",
    "జనగాం": "Jangaon",
    "జయశంకర్ భూపాలపల్లి": "Jayashankar Bhupalpally",
    "భూపాలపల్లి": "Jayashankar Bhupalpally",
    "జోగులాంబ గద్వాల": "Jogulamba Gadwal",
    "గద్వాల": "Jogulamba Gadwal",
    "కామారెడ్డి": "Kamareddy",
    "కరీంనగర్": "Karimnagar",
    "ఖమ్మం": "Khammam",
    "కొమరం భీమ్ ఆసిఫాబాద్": "Kumuram Bheem Asifabad",
    "ఆసిఫాబాద్": "Kumuram Bheem Asifabad",
    "మహబూబాబాద్": "Mahabubabad",
    "మహబూబ్ నగర్": "Mahabubnagar",
    "మహబూబ్‌నగర్": "Mahabubnagar",
    "పాలమూరు": "Mahabubnagar",
    "మంచిర్యాల": "Mancherial",
    "మెదక్": "Medak",
    "మేడ్చల్ మల్కాజ్ గిరి": "Medchal Malkajgiri",
    "మేడ్చల్": "Medchal Malkajgiri",
    "ములుగు": "Mulugu",
    "నాగర్ కర్నూల్": "Nagarkurnool",
    "నాగర్‌కర్నూల్": "Nagarkurnool",
    "నల్గొండ": "Nalgonda",
    "నారాయణపేట": "Narayanpet",
    "నిర్మల్": "Nirmal",
    "నిజామాబాద్": "Nizamabad",
    "పెద్దపల్లి": "Peddapalli",
    "రాజన్న సిరిసిల్ల": "Rajanna Sircilla",
    "సిరిసిల్ల": "Rajanna Sircilla",
    "రంగారెడ్డి": "Rangareddy",
    "సంగారెడ్డి": "Sangareddy",
    "సిద్దిపేట": "Siddipet",
    "సూర్యాపేట": "Suryapet",
    "వికారాబాద్": "Vikarabad",
    "వనపర్తి": "Wanaparthy",
    "వరంగల్": "Warangal",
    "వరంగల్ రూరల్": "Warangal",
    "వరంగల్ అర్బన్": "Hanumakonda",
    "యాదాద్రి భువనగిరి": "Yadadri Bhuvanagiri",
    "భువనగిరి": "Yadadri Bhuvanagiri",
}

# Explicit affirmative consent phrases (active whether awaiting consent or unprompted)
EXPLICIT_CONSENT_PHRASES = [
    "సమ్మతి ఇస్తున్నాను", "సమ్మతిస్తున్నాను", "నా సమ్మతి ఇస్తున్నాను",
    "సమ్మతి తెలుపుతున్నాను", "సమ్మతి తెలియజేస్తున్నాను", "సమ్మతి ఇస్తున్నా",
    "వాతావరణ సమ్మతి", "i consent", "i give consent", "consent given", "give consent",
]

# Contextual affirmative terms: accepted ONLY when the session is actively awaiting consent
CONTEXTUAL_AFFIRMATIVE_TERMS = [
    "సమ్మతి", "సమ్మతమే", "ఒప్పుకుంటున్నాను", "అంగీకరిస్తున్నాను",
    "సరే", "సరే పర్వాలేదు", "అవును", "హా", "పర్మిషన్",
    "yes", "ok", "sure", "agree", "i agree", "allow", "yep",
]

# Negative consent keywords / patterns (rejection / withdrawal)
CONSENT_NEGATIVE_TERMS = [
    "సమ్మతి లేదు", "సమ్మతించను", "ఒప్పుకోను", "అంగీకరించను",
    "వద్దు", "లేదు", "వద్దండి", "తిరస్కరిస్తున్నాను", "తిరస్కరణ", "సమ్మతి రద్దు",
    "no", "i do not consent", "reject", "deny", "disagree", "stop", "cancel", "never",
]

# User location deletion request patterns
LOCATION_DELETION_PATTERNS = [
    "లొకేషన్ తొలగించండి", "నా వివరాలు తొలగించండి", "లొకేషన్ డిలీట్",
    "వివరాలు తొలగించు", "లొకేషన్ రద్దు చేయండి", "నా డేటా తొలగించండి",
    "/delete_location", "/clear_location", "/delete_data",
    "delete location", "clear location", "delete my location", "delete my data",
]

# Known external/non-Telangana place references that signal ambiguous/conflicting locations
EXTERNAL_NON_TELANGANA_PLACES = {
    "పిళ్ళాచ్చి", "పిల్లాచ్చి", "పొల్లాచ్చి", "pollachi", "pillachchi",
    "చెన్నై", "chennai", "మద్రాస్", "madras",
    "బెంగళూరు", "bangalore", "bengaluru",
    "విజయవాడ", "vijayawada", "గుంటూరు", "guntur",
    "వైజాగ్", "vizag", "విశాఖపట్నం", "visakhapatnam",
    "ముంబై", "mumbai", "బాంబే", "bombay",
    "ఢిల్లీ", "delhi", "న్యూఢిల్లీ", "new delhi",
    "కోల్‌కతా", "kolkata", "కలకత్తా", "calcutta",
    "కేరళ", "kerala", "కర్ణాటక", "karnataka", "తమిళనాడు", "tamil nadu", "ఆంధ్రప్రదేశ్", "andhra pradesh",
}

# Known mandals mapped to their canonical Telangana district to detect cross-district mismatch
KNOWN_MANDAL_DISTRICTS: Dict[str, str] = {
    "జెన్నారం": "Mancherial",
    "jannaram": "Mancherial",
    "కోదాడ": "Suryapet",
    "kodad": "Suryapet",
    "హుజూర్‌నగర్": "Suryapet",
    "హుజూర్ నగర్": "Suryapet",
    "huzurnagar": "Suryapet",
    "నర్సంపేట": "Warangal",
    "narsampet": "Warangal",
    "బోధన్": "Nizamabad",
    "bodhan": "Nizamabad",
    "ఆర్మూర్": "Nizamabad",
    "armur": "Nizamabad",
    "బాన్సువాడ": "Kamareddy",
    "banswada": "Kamareddy",
}


def has_conflicting_locations(text: Optional[str]) -> bool:
    """
    Detect whether free-form text contains conflicting, contradictory, or ambiguous location references.
    Examples of conflicts:
    - Multiple distinct mandals mentioned (e.g., 'జెన్నారం మండలం, తోటపల్లి మండలం').
    - Multiple distinct districts mentioned (e.g., 'నిజామాబాద్' and 'వరంగల్').
    - Non-Telangana / external place names present (e.g., 'పిళ్ళాచ్చి' / 'Pollachi').
    - Known mandal belonging to a different district than the one mentioned (e.g. 'జెన్నారం' in Nizamabad query).
    """
    if not text:
        return False

    cleaned_text = normalize_whitespace(text) or ""
    cleaned_lower = cleaned_text.lower()

    # 1. External / non-Telangana place references
    for place in EXTERNAL_NON_TELANGANA_PLACES:
        if place in cleaned_lower:
            return True

    # 2. Check for multiple distinct mandals
    mandal_matches = re.findall(
        r"([A-Za-z\u0C00-\u0C7F]+)\s*(?:మండలం|మండలము|mandal)",
        cleaned_text,
        re.IGNORECASE,
    )
    stop_words = {
        "మా", "నా", "మీ", "మాది", "ఈ", "పేరు",
        "our", "my", "your", "the", "a", "an", "this", "that", "in", "at", "is", "lo", "లో",
    }
    extracted_mandals = []
    for cand in mandal_matches:
        cand_clean = cand.strip()
        if cand_clean.lower() not in stop_words and len(cand_clean) > 1:
            extracted_mandals.append(cand_clean.lower())

    if len(set(extracted_mandals)) > 1:
        return True

    # 3. Check for multiple distinct districts
    detected_districts = set()
    for te_dist, canonical_dist in TELANGANA_DISTRICTS_TE.items():
        if te_dist in cleaned_text:
            detected_districts.add(canonical_dist.lower())

    if len(detected_districts) > 1:
        return True

    # 4. Check for known mandal-district mismatch
    if detected_districts and extracted_mandals:
        for m in extracted_mandals:
            canonical_m_dist = KNOWN_MANDAL_DISTRICTS.get(m)
            if canonical_m_dist and canonical_m_dist.lower() not in detected_districts:
                return True

    return False


def _matches_term(term: str, cleaned_text: str) -> bool:
    """Helper to match a term with word boundary for ASCII or exact word/phrase for Indic."""
    if re.match(r"^[a-zA-Z0-9\s]+$", term):
        # ASCII term: enforce word boundaries so 'ok' does not match 'look', 'sure' does not match 'measure'
        pattern = r"\b" + re.escape(term.strip()) + r"\b"
        return bool(re.search(pattern, cleaned_text, re.IGNORECASE))
    else:
        # Indic term: exact phrase match or boundary
        return term in cleaned_text


def is_consent_grant(text: Optional[str], awaiting_consent: bool = False) -> bool:
    """
    Check if the text represents explicit affirmative consent.
    If awaiting_consent is False, ONLY unambiguous explicit phrases are accepted.
    Short contextual words ('సరే', 'అవును', 'ok', 'yes') are accepted ONLY when awaiting_consent is True.
    """
    if not text:
        return False
    cleaned = text.strip().lower()

    # If explicit negative terms are present, it is never an affirmative grant
    if any(_matches_term(neg, cleaned) for neg in CONSENT_NEGATIVE_TERMS):
        return False

    # 1. Unambiguous explicit phrases always accepted
    if any(_matches_term(phrase, cleaned) for phrase in EXPLICIT_CONSENT_PHRASES):
        return True

    # 2. Contextual terms accepted ONLY when actively awaiting consent
    if awaiting_consent:
        return any(_matches_term(term, cleaned) for term in CONTEXTUAL_AFFIRMATIVE_TERMS)

    return False


def is_consent_reject(text: Optional[str]) -> bool:
    """Check if the text represents explicit rejection or withdrawal of consent."""
    if not text:
        return False
    cleaned = text.strip().lower()
    return any(_matches_term(neg, cleaned) for neg in CONSENT_NEGATIVE_TERMS)


def is_location_deletion_request(text: Optional[str]) -> bool:
    """Check if the user is requesting deletion of their stored location details."""
    if not text:
        return False
    cleaned = text.strip().lower()
    return any(_matches_term(p, cleaned) for p in LOCATION_DELETION_PATTERNS)


def extract_location_from_text(
    text: Optional[str],
) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
    """
    Extract village, mandal, district, and PIN code from free-form text.
    Returns: (village, mandal, district, pin_code)
    If conflicting or ambiguous locations are detected, returns (None, None, None, None).
    """
    if not text:
        return None, None, None, None

    if has_conflicting_locations(text):
        logger.info("Conflicting or ambiguous locations detected in text: '%s'. Aborting extraction.", text)
        return None, None, None, None

    cleaned_text = normalize_whitespace(text) or ""

    # 1. PIN code
    pin_code, _ = extract_pin_from_text(cleaned_text)

    # 2. District
    district: Optional[str] = None
    # Check Telugu district map
    for te_dist, canonical_dist in TELANGANA_DISTRICTS_TE.items():
        if te_dist in cleaned_text:
            district = canonical_dist
            break

    # If not matched via Telugu names, try English regex & canonical registry
    if not district:
        m_dist = re.search(
            r"(?:జిల్లా|district)\s*[:\s-]?\s*([A-Za-z]+)|([A-Za-z]+)\s*(?:జిల్లా|district)",
            cleaned_text,
            re.IGNORECASE,
        )
        if m_dist:
            candidate = m_dist.group(1) or m_dist.group(2)
            resolved = resolve_telangana_district(candidate)
            if resolved:
                district = resolved.district_name

    # Check standalone English district names in text if still not found
    if not district:
        for word in cleaned_text.replace(",", " ").replace(".", " ").split():
            clean_word = word.strip().lower()
            if len(clean_word) < 4:
                continue
            resolved = resolve_telangana_district(clean_word)
            if resolved and (clean_word == resolved.district_name.lower() or clean_word == resolved.normalized_name):
                district = resolved.district_name
                break

    stop_words = {
        "మా", "నా", "మీ", "మాది", "ఈ", "పేరు",
        "our", "my", "your", "the", "a", "an", "this", "that", "in", "at", "is", "lo", "లో",
    }

    # 3. Mandal
    mandal: Optional[str] = None
    # Priority A: Postfix pattern 'కోదాడ మండలం' or 'Kodad mandal'
    m_man_post = re.search(
        r"([A-Za-z\u0C00-\u0C7F]+)\s*(?:మండలం|మండలము|mandal)",
        cleaned_text,
        re.IGNORECASE,
    )
    if m_man_post:
        cand = m_man_post.group(1).strip()
        if cand.lower() not in stop_words and len(cand) > 1:
            mandal = cand

    # Priority B: Explicit key-value or prefix pattern 'మండలం: కోదాడ' or 'mandal Kodad'
    if not mandal:
        m_man_pre = re.search(
            r"(?:మండలం|మండలము|mandal)\s*[:\s-]?\s*([A-Za-z\u0C00-\u0C7F]+)",
            cleaned_text,
            re.IGNORECASE,
        )
        if m_man_pre:
            cand = m_man_pre.group(1).strip()
            if cand.lower() not in stop_words and len(cand) > 1:
                mandal = cand

    # 4. Village
    village: Optional[str] = None
    # Priority A: Postfix pattern 'రామవరం గ్రామం' or 'Ramavaram village'
    m_vil_post = re.search(
        r"([A-Za-z\u0C00-\u0C7F]+)\s*(?:గ్రామం|గ్రామము|విలేజ్|village)",
        cleaned_text,
        re.IGNORECASE,
    )
    if m_vil_post:
        cand = m_vil_post.group(1).strip()
        if cand.lower() not in stop_words and len(cand) > 1:
            village = cand

    # Priority B: Explicit key-value prefix 'గ్రామం: రామవరం' or 'village: Ramavaram'
    if not village:
        m_vil_kv = re.search(
            r"(?:గ్రామం|గ్రామము|విలేజ్|ఊరు|village)\s*[:=-]\s*([A-Za-z\u0C00-\u0C7F]+)",
            cleaned_text,
            re.IGNORECASE,
        )
        if m_vil_kv:
            cand = m_vil_kv.group(1).strip()
            if cand.lower() not in stop_words and len(cand) > 1:
                village = cand

    # Priority C: Prefix pattern 'గ్రామం రామవరం' or 'village Ramavaram'
    if not village:
        m_vil_pre = re.search(
            r"(?:గ్రామం|గ్రామము|విలేజ్|ఊరు|village)\s+([A-Za-z\u0C00-\u0C7F]+)",
            cleaned_text,
            re.IGNORECASE,
        )
        if m_vil_pre:
            cand = m_vil_pre.group(1).strip()
            if cand.lower() not in stop_words and len(cand) > 1:
                village = cand

    return village, mandal, district, pin_code


LOCATION_EXPIRY_SECONDS = 1800  # 30 minutes


@dataclass
class TemporaryLocationContext:
    """In-memory temporary location context for the current weather interaction."""
    village: Optional[str] = None
    mandal: Optional[str] = None
    district: Optional[str] = None
    pin_code: Optional[str] = None
    created_at: float = 0.0


@dataclass
class TelegramUserSession:
    """Represents the persisted session state and consent record for a Telegram user."""
    user_id: str
    weather_provider_sharing_consent: bool = False
    weather_provider_sharing_consent_at: Optional[str] = None
    weather_provider_disclosure_version: str = "v1.0"
    pending_weather_query: Optional[str] = None
    awaiting_consent: bool = False
    village_name: Optional[str] = None
    mandal_name: Optional[str] = None
    district_name: Optional[str] = None
    pin_code: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class TelegramSessionRepository:
    """
    SQLite persistence for Telegram user sessions and weather-provider consent.
    Guarantees isolation from the main 'farmers' table and location data minimisation (Phase 8.5).
    """

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or settings.DATABASE_PATH
        self._temp_locations: Dict[str, TemporaryLocationContext] = {}
        self._init_table()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=15.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_table(self) -> None:
        """Create table and perform Phase 8.5 safe migration to clear legacy SQLite location details."""
        conn = self._get_connection()
        try:
            with conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS telegram_user_consents (
                        telegram_user_id TEXT PRIMARY KEY,
                        weather_provider_sharing_consent INTEGER NOT NULL DEFAULT 0,
                        weather_provider_sharing_consent_at TEXT,
                        weather_provider_disclosure_version TEXT DEFAULT 'v1.0',
                        pending_weather_query TEXT,
                        awaiting_consent INTEGER NOT NULL DEFAULT 0,
                        village_name TEXT,
                        mandal_name TEXT,
                        district_name TEXT,
                        pin_code TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                """)
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_tg_user_id ON telegram_user_consents(telegram_user_id);"
                )
                # Phase 8.5 Safe Migration: Purge any legacy location data permanently stored in SQLite
                conn.execute("""
                    UPDATE telegram_user_consents
                    SET village_name = NULL,
                        mandal_name = NULL,
                        district_name = NULL,
                        pin_code = NULL
                    WHERE village_name IS NOT NULL
                       OR mandal_name IS NOT NULL
                       OR district_name IS NOT NULL
                       OR pin_code IS NOT NULL;
                """)
        finally:
            conn.close()

    def get_temp_location(
        self, user_id: str, current_time: Optional[float] = None
    ) -> Optional[TemporaryLocationContext]:
        """
        Retrieve active in-memory temporary location context for the Telegram user.
        Expires after 30 minutes (1800 seconds).
        """
        uid = str(user_id).strip()
        loc = self._temp_locations.get(uid)
        if not loc:
            return None
        now = current_time if current_time is not None else time.time()
        if (now - loc.created_at) > LOCATION_EXPIRY_SECONDS:
            self._temp_locations.pop(uid, None)
            return None
        return loc

    def clear_temp_location(self, user_id: str) -> None:
        """Clear temporary in-memory location context for a user."""
        uid = str(user_id).strip()
        self._temp_locations.pop(uid, None)

    def get_session(
        self, user_id: str, current_time: Optional[float] = None
    ) -> TelegramUserSession:
        """
        Retrieve existing session. Consent and pending queries are read from SQLite;
        location is read ONLY from temporary in-memory context (subject to 30-minute expiry).
        """
        uid = str(user_id).strip()
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM telegram_user_consents WHERE telegram_user_id = ?",
                (uid,),
            )
            row = cursor.fetchone()

            # Location is kept in temporary in-memory conversation context ONLY
            temp_loc = self.get_temp_location(uid, current_time=current_time)
            v = temp_loc.village if temp_loc else None
            m = temp_loc.mandal if temp_loc else None
            d = temp_loc.district if temp_loc else None
            p = temp_loc.pin_code if temp_loc else None

            if row:
                return TelegramUserSession(
                    user_id=row["telegram_user_id"],
                    weather_provider_sharing_consent=bool(row["weather_provider_sharing_consent"]),
                    weather_provider_sharing_consent_at=row["weather_provider_sharing_consent_at"],
                    weather_provider_disclosure_version=row["weather_provider_disclosure_version"] or "v1.0",
                    pending_weather_query=row["pending_weather_query"],
                    awaiting_consent=bool(row["awaiting_consent"]),
                    village_name=v,
                    mandal_name=m,
                    district_name=d,
                    pin_code=p,
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                )
            return TelegramUserSession(
                user_id=uid,
                village_name=v,
                mandal_name=m,
                district_name=d,
                pin_code=p,
            )
        finally:
            conn.close()

    def set_consent(
        self,
        user_id: str,
        consent_given: bool,
        disclosure_version: str = "v1.0",
    ) -> TelegramUserSession:
        """Record or update explicit weather-provider location sharing consent."""
        uid = str(user_id).strip()
        now_iso = datetime.now(timezone.utc).isoformat()
        consent_at = now_iso if consent_given else None

        conn = self._get_connection()
        try:
            with conn:
                conn.execute("""
                    INSERT INTO telegram_user_consents (
                        telegram_user_id,
                        weather_provider_sharing_consent,
                        weather_provider_sharing_consent_at,
                        weather_provider_disclosure_version,
                        awaiting_consent,
                        created_at,
                        updated_at
                    ) VALUES (?, ?, ?, ?, 0, ?, ?)
                    ON CONFLICT(telegram_user_id) DO UPDATE SET
                        weather_provider_sharing_consent = excluded.weather_provider_sharing_consent,
                        weather_provider_sharing_consent_at = excluded.weather_provider_sharing_consent_at,
                        weather_provider_disclosure_version = excluded.weather_provider_disclosure_version,
                        awaiting_consent = 0,
                        updated_at = excluded.updated_at
                """, (
                    uid,
                    1 if consent_given else 0,
                    consent_at,
                    disclosure_version,
                    now_iso,
                    now_iso,
                ))
            return self.get_session(uid)
        finally:
            conn.close()

    def set_pending_query(
        self,
        user_id: str,
        query: Optional[str],
        awaiting_consent: bool = True,
    ) -> None:
        """Store pending weather query and awaiting consent state."""
        uid = str(user_id).strip()
        now_iso = datetime.now(timezone.utc).isoformat()

        conn = self._get_connection()
        try:
            with conn:
                conn.execute("""
                    INSERT INTO telegram_user_consents (
                        telegram_user_id,
                        pending_weather_query,
                        awaiting_consent,
                        created_at,
                        updated_at
                    ) VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(telegram_user_id) DO UPDATE SET
                        pending_weather_query = excluded.pending_weather_query,
                        awaiting_consent = excluded.awaiting_consent,
                        updated_at = excluded.updated_at
                """, (
                    uid,
                    query,
                    1 if awaiting_consent else 0,
                    now_iso,
                    now_iso,
                ))
        finally:
            conn.close()

    def update_location(
        self,
        user_id: str,
        village: Optional[str] = None,
        mandal: Optional[str] = None,
        district: Optional[str] = None,
        pin_code: Optional[str] = None,
        current_time: Optional[float] = None,
    ) -> None:
        """
        Store or update location details in TEMPORARY IN-MEMORY context only (Phase 8.5).
        Never writes location details (village, mandal, district, pin_code) to persistent SQLite storage.
        """
        uid = str(user_id).strip()
        curr = self.get_temp_location(uid, current_time=current_time)
        new_village = village or (curr.village if curr else None)
        new_mandal = mandal or (curr.mandal if curr else None)
        new_district = district or (curr.district if curr else None)
        new_pin = pin_code or (curr.pin_code if curr else None)
        now = current_time if current_time is not None else time.time()

        self._temp_locations[uid] = TemporaryLocationContext(
            village=new_village,
            mandal=new_mandal,
            district=new_district,
            pin_code=new_pin,
            created_at=now,
        )

    def clear_pending_query(self, user_id: str) -> None:
        """Clear pending query and reset awaiting_consent flag."""
        uid = str(user_id).strip()
        now_iso = datetime.now(timezone.utc).isoformat()
        conn = self._get_connection()
        try:
            with conn:
                conn.execute("""
                    UPDATE telegram_user_consents
                    SET pending_weather_query = NULL,
                        awaiting_consent = 0,
                        updated_at = ?
                    WHERE telegram_user_id = ?
                """, (now_iso, uid))
        finally:
            conn.close()

    def clear_location(self, user_id: str) -> None:
        """
        Clear in-memory temporary location and any legacy SQLite location columns for the user.
        Preserves weather_provider_sharing_consent flag.
        """
        uid = str(user_id).strip()
        self.clear_temp_location(uid)
        now_iso = datetime.now(timezone.utc).isoformat()
        conn = self._get_connection()
        try:
            with conn:
                conn.execute("""
                    UPDATE telegram_user_consents
                    SET village_name = NULL,
                        mandal_name = NULL,
                        district_name = NULL,
                        pin_code = NULL,
                        updated_at = ?
                    WHERE telegram_user_id = ?
                """, (now_iso, uid))
        finally:
            conn.close()

    def delete_user_session(self, user_id: str) -> None:
        """Permanently delete user record from telegram_user_consents and clear temporary location."""
        uid = str(user_id).strip()
        self.clear_temp_location(uid)
        conn = self._get_connection()
        try:
            with conn:
                conn.execute(
                    "DELETE FROM telegram_user_consents WHERE telegram_user_id = ?",
                    (uid,),
                )
        finally:
            conn.close()
