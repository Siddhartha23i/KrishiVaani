"""
SQLite database management for KrishiVaani.
Provides connection lifecycle, table initialization, and transaction management.
"""

import sqlite3
from pathlib import Path
from typing import Optional
from app.core.config import settings


def ensure_database_initialized(db_path: Optional[Path] = None) -> None:
    """
    Ensure the target SQLite database exists.
    If the target database is missing or 0 bytes, and an approved seed database
    exists at data_seed/krishivaani.db, safely copy the seed database and raw
    approved PDFs to the target directory.
    Never overwrites an existing non-empty database.
    """
    target = db_path or settings.DATABASE_PATH
    if target == Path(":memory:"):
        return

    if not target.exists() or target.stat().st_size == 0:
        seed_db = settings.BASE_DIR / "data_seed" / "krishivaani.db"
        if seed_db.exists() and seed_db.stat().st_size > 0:
            target.parent.mkdir(parents=True, exist_ok=True)
            import shutil
            shutil.copy2(str(seed_db), str(target))

    # Ensure raw knowledge PDF subdirectories exist and are seeded if missing
    for sub in ["pjtau", "tgdps"]:
        seed_sub = settings.BASE_DIR / "data_seed" / sub / "raw_pdfs"
        target_sub = settings.BASE_DIR / "data" / sub / "raw_pdfs"
        if seed_sub.exists() and not target_sub.exists():
            target_sub.mkdir(parents=True, exist_ok=True)
            import shutil
            for f in seed_sub.glob("*.pdf"):
                shutil.copy2(str(f), str(target_sub / f.name))


def get_connection(db_path: Optional[Path] = None) -> sqlite3.Connection:
    """
    Open and configure a SQLite connection.
    Ensures parent directory exists and configures row factory.
    """
    ensure_database_initialized(db_path)
    target = db_path or settings.DATABASE_PATH
    if target != Path(":memory:"):
        target.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(target))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db(db_path: Optional[Path] = None) -> None:
    """
    Initialize SQLite schema for KrishiVaani.
    Creates tables and indices if they do not exist.
    """
    conn = get_connection(db_path)
    try:
        with conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS farmers (
                    farmer_id TEXT PRIMARY KEY,
                    whatsapp_user_id TEXT UNIQUE,
                    preferred_language TEXT NOT NULL DEFAULT 'te-IN',
                    village_name TEXT NOT NULL,
                    mandal_name TEXT,
                    district_name TEXT,
                    pin_code TEXT NOT NULL,
                    latitude REAL,
                    longitude REAL,
                    location_source TEXT NOT NULL,
                    location_confirmed INTEGER NOT NULL DEFAULT 0,
                    consent_given INTEGER NOT NULL DEFAULT 0,
                    consent_given_at TEXT,
                    weather_provider_sharing_consent INTEGER NOT NULL DEFAULT 0,
                    weather_provider_sharing_consent_at TEXT,
                    weather_provider_disclosure_version TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_farmers_whatsapp_user_id ON farmers(whatsapp_user_id);"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_farmers_pin_code ON farmers(pin_code);"
            )

            # Safe migration for Phase 6.1.1 weather provider sharing consent columns
            try:
                col_cursor = conn.execute("PRAGMA table_info(farmers);")
                existing_cols = {col["name"] for col in col_cursor.fetchall()}
                if "weather_provider_sharing_consent" not in existing_cols:
                    conn.execute("ALTER TABLE farmers ADD COLUMN weather_provider_sharing_consent INTEGER NOT NULL DEFAULT 0;")
                if "weather_provider_sharing_consent_at" not in existing_cols:
                    conn.execute("ALTER TABLE farmers ADD COLUMN weather_provider_sharing_consent_at TEXT;")
                if "weather_provider_disclosure_version" not in existing_cols:
                    conn.execute("ALTER TABLE farmers ADD COLUMN weather_provider_disclosure_version TEXT;")
            except Exception:
                pass

            # Knowledge Base Schema (Phase 5 & 5.1)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS knowledge_sources (
                    source_id TEXT PRIMARY KEY,
                    publisher TEXT NOT NULL,
                    document_title TEXT NOT NULL,
                    source_url TEXT,
                    source_type TEXT NOT NULL,
                    authority_status TEXT NOT NULL DEFAULT 'pending_verification',
                    reviewed_by TEXT,
                    review_notes TEXT,
                    published_at TEXT,
                    last_checked_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_ks_publisher ON knowledge_sources(publisher);"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_ks_authority_status ON knowledge_sources(authority_status);"
            )

            conn.execute("""
                CREATE TABLE IF NOT EXISTS knowledge_items (
                    knowledge_id TEXT PRIMARY KEY,
                    category TEXT NOT NULL,
                    knowledge_type TEXT NOT NULL DEFAULT 'seasonal_guidance',
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    language_code TEXT NOT NULL DEFAULT 'te-IN',
                    translation_status TEXT NOT NULL DEFAULT 'original',
                    state TEXT NOT NULL DEFAULT 'Telangana',
                    district TEXT,
                    mandal TEXT,
                    village TEXT,
                    pin_code TEXT,
                    crop_name TEXT,
                    crop_variety TEXT,
                    crop_stage TEXT,
                    season TEXT,
                    season_year INTEGER,
                    soil_type TEXT,
                    water_condition TEXT,
                    applicable_from TEXT,
                    applicable_until TEXT,
                    publication_date TEXT,
                    is_permanent_reference INTEGER NOT NULL DEFAULT 0,
                    review_cycle_days INTEGER,
                    last_reviewed_at TEXT,
                    verification_status TEXT NOT NULL DEFAULT 'draft',
                    verified_at TEXT,
                    verified_by TEXT,
                    retrieval_applicability_notes TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
            """)
            # Apply safe column migrations for existing databases before creating new indices
            _migrate_knowledge_tables(conn)

            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_ki_category ON knowledge_items(category);"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_ki_type ON knowledge_items(knowledge_type);"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_ki_verification_status ON knowledge_items(verification_status);"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_ki_crop ON knowledge_items(crop_name);"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_ki_region ON knowledge_items(state, district, mandal);"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_ki_dates ON knowledge_items(applicable_from, applicable_until);"
            )

            conn.execute("""
                CREATE TABLE IF NOT EXISTS knowledge_item_sources (
                    item_id TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    reference_location TEXT,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (item_id, source_id),
                    FOREIGN KEY (item_id) REFERENCES knowledge_items(knowledge_id) ON DELETE CASCADE,
                    FOREIGN KEY (source_id) REFERENCES knowledge_sources(source_id) ON DELETE CASCADE
                );
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_kis_source ON knowledge_item_sources(source_id);"
            )

            # Verification Audit Trail (Phase 5.2)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS knowledge_verification_audit (
                    audit_id TEXT PRIMARY KEY,
                    entity_type TEXT NOT NULL,
                    entity_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    actor_role TEXT NOT NULL,
                    is_test_audit INTEGER NOT NULL DEFAULT 0,
                    notes TEXT,
                    created_at TEXT NOT NULL
                );
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_kva_entity ON knowledge_verification_audit(entity_id);"
            )

            # PJTAU Research Stations Canonical Schema (Phase 7.7)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS pjtau_research_stations (
                    station_id TEXT PRIMARY KEY,
                    canonical_name TEXT NOT NULL,
                    alternate_names TEXT,
                    pjtau_zone TEXT NOT NULL,
                    agro_climatic_descriptor TEXT,
                    address TEXT NOT NULL,
                    village TEXT,
                    mandal TEXT,
                    district TEXT NOT NULL,
                    pin_code TEXT,
                    latitude REAL,
                    longitude REAL,
                    coordinates_original_text TEXT,
                    met_observatory_details TEXT,
                    established_year TEXT,
                    total_area_acres REAL,
                    mandated_crops TEXT,
                    research_focus TEXT,
                    research_themes TEXT,
                    infrastructure_facilities TEXT,
                    source_url TEXT NOT NULL,
                    source_last_updated TEXT NOT NULL,
                    retrieved_at TEXT NOT NULL,
                    verification_status TEXT NOT NULL DEFAULT 'pending_verification',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_prs_zone ON pjtau_research_stations(pjtau_zone);"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_prs_district ON pjtau_research_stations(district);"
            )

            conn.execute("""
                CREATE TABLE IF NOT EXISTS pjtau_station_contacts (
                    contact_id TEXT PRIMARY KEY,
                    station_id TEXT NOT NULL,
                    contact_name TEXT,
                    designation TEXT,
                    role TEXT NOT NULL,
                    phone_number TEXT,
                    official_email TEXT,
                    source_reference TEXT NOT NULL,
                    contact_status TEXT NOT NULL DEFAULT 'VERIFIED',
                    is_active_referral INTEGER NOT NULL DEFAULT 0,
                    notes TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (station_id) REFERENCES pjtau_research_stations(station_id) ON DELETE CASCADE
                );
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_psc_station ON pjtau_station_contacts(station_id);"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_psc_status ON pjtau_station_contacts(contact_status);"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_psc_active ON pjtau_station_contacts(is_active_referral);"
            )

            conn.execute("""
                CREATE TABLE IF NOT EXISTS pjtau_station_research_outputs (
                    output_id TEXT PRIMARY KEY,
                    station_id TEXT NOT NULL,
                    output_type TEXT NOT NULL,
                    crop_name TEXT,
                    variety_or_technology_name TEXT NOT NULL,
                    release_year TEXT,
                    release_status TEXT,
                    description TEXT NOT NULL,
                    original_source_text TEXT NOT NULL,
                    verification_status TEXT NOT NULL DEFAULT 'pending_verification',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (station_id) REFERENCES pjtau_research_stations(station_id) ON DELETE CASCADE
                );
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_psro_station ON pjtau_station_research_outputs(station_id);"
            )

            conn.execute("""
                CREATE TABLE IF NOT EXISTS pjtau_station_projects_outreach (
                    item_id TEXT PRIMARY KEY,
                    station_id TEXT NOT NULL,
                    item_type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    funding_agency TEXT,
                    start_date TEXT,
                    end_date TEXT,
                    is_till_date INTEGER NOT NULL DEFAULT 0,
                    published_duration_text TEXT,
                    description TEXT,
                    original_source_text TEXT NOT NULL,
                    verification_status TEXT NOT NULL DEFAULT 'pending_verification',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (station_id) REFERENCES pjtau_research_stations(station_id) ON DELETE CASCADE
                );
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_pspo_station ON pjtau_station_projects_outreach(station_id);"
            )

            # WhatsApp Webhook Events Schema (Phase 8.1 Idempotency & Lifecycle)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS whatsapp_events (
                    wamid TEXT PRIMARY KEY,
                    sender_id TEXT NOT NULL,
                    message_type TEXT NOT NULL,
                    media_id TEXT,
                    status TEXT NOT NULL DEFAULT 'RECEIVED',
                    received_at TEXT NOT NULL,
                    processed_at TEXT,
                    error_message TEXT,
                    response_summary TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_we_sender ON whatsapp_events(sender_id);"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_we_status ON whatsapp_events(status);"
            )

            # Twilio Webhook Events Schema (Phase 8.2 Integration)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS twilio_events (
                    message_sid TEXT PRIMARY KEY,
                    account_sid TEXT,
                    from_number TEXT NOT NULL,
                    to_number TEXT NOT NULL,
                    message_type TEXT NOT NULL,
                    body TEXT,
                    media_url TEXT,
                    media_content_type TEXT,
                    status TEXT NOT NULL DEFAULT 'RECEIVED',
                    response_summary TEXT,
                    error_message TEXT,
                    received_at TEXT NOT NULL,
                    processed_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_te_from ON twilio_events(from_number);"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_te_status ON twilio_events(status);"
            )
    finally:
        conn.close()


def _migrate_knowledge_tables(conn: sqlite3.Connection) -> None:
    """
    Safely adds Phase 5.1 columns to existing tables without modifying or resetting data.
    """
    # 1. Migrate knowledge_items
    cur = conn.execute("PRAGMA table_info(knowledge_items);")
    item_cols = {r["name"] for r in cur.fetchall()}
    if item_cols:
        item_additions = {
            "knowledge_type": "TEXT NOT NULL DEFAULT 'seasonal_guidance'",
            "season_year": "INTEGER",
            "is_permanent_reference": "INTEGER NOT NULL DEFAULT 0",
            "review_cycle_days": "INTEGER",
            "last_reviewed_at": "TEXT",
            "verified_by": "TEXT",
            "retrieval_applicability_notes": "TEXT",
        }
        for col_name, col_def in item_additions.items():
            if col_name not in item_cols:
                conn.execute(f"ALTER TABLE knowledge_items ADD COLUMN {col_name} {col_def};")

    # 2. Migrate knowledge_sources
    cur = conn.execute("PRAGMA table_info(knowledge_sources);")
    source_cols = {r["name"] for r in cur.fetchall()}
    if source_cols:
        source_additions = {
            "reviewed_by": "TEXT",
            "review_notes": "TEXT",
        }
        for col_name, col_def in source_additions.items():
            if col_name not in source_cols:
                conn.execute(f"ALTER TABLE knowledge_sources ADD COLUMN {col_name} {col_def};")

    # 3. Migrate pjtau_station_contacts (Phase 7.7.1)
    cur = conn.execute("PRAGMA table_info(pjtau_station_contacts);")
    psc_cols = {r["name"] for r in cur.fetchall()}
    if psc_cols and "is_active_referral" not in psc_cols:
        conn.execute("ALTER TABLE pjtau_station_contacts ADD COLUMN is_active_referral INTEGER NOT NULL DEFAULT 0;")

