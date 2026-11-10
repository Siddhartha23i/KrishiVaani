"""
Service layer for PJTAU Research Station Ingestion, Persistence, Directory Queries,
and Safe Farmer-Facing Referrals.

Guarantees:
- Idempotent ingestion into existing SQLite database.
- Four distinct categories:
  Category A: Station directory and contacts (pjtau_station_contacts)
  Category B: Research-station profiles, mandated crops, and themes (pjtau_research_stations)
  Category C: Released varieties and developed technologies (pjtau_station_research_outputs)
  Category D: Outreach programmes and research projects (pjtau_station_projects_outreach)
- All new records enter review lifecycle in 'pending_verification' status.
- Safe referral logic: verified contacts return valid station numbers;
  unverified/conflicting/missing contacts return safe fallback referrals without inventing numbers.
"""

import json
import logging
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Union, Any

from app.db.database import get_connection, init_db
from app.knowledge.pjtau.station_schemas import (
    PJTAUZone,
    ContactRole,
    ContactStatus,
    DistrictMappingType,
    DistrictMappingRecord,
    ResearchOutputType,
    ProjectOutreachType,
    PJTAUStationContact,
    PJTAUResearchOutput,
    PJTAUProjectOutreach,
    PJTAUResearchStation,
    StationReferralResponse,
)
from app.knowledge.pjtau.station_data import (
    get_all_canonical_stations,
    SOURCE_LAST_UPDATED,
    RETRIEVED_AT,
    URL_NTZ,
    URL_CTZ,
    URL_STZ,
)

logger = logging.getLogger(__name__)

# Complete mapping of all 33 Telangana districts to primary research station IDs
TELANGANA_DISTRICT_TO_STATION: Dict[str, str] = {
    # Northern Telangana Zone (10 districts)
    "adilabad": "pjtau_stn_ars_adilabad",
    "kumuram bheem asifabad": "pjtau_stn_ars_adilabad",
    "komaram bheem asifabad": "pjtau_stn_ars_adilabad",
    "asifabad": "pjtau_stn_ars_adilabad",
    "mancherial": "pjtau_stn_ars_adilabad",
    "nirmal": "pjtau_stn_ars_mudhole",
    "karimnagar": "pjtau_stn_ars_karimnagar",
    "jagtial": "pjtau_stn_polasa_jagtial",
    "jagityal": "pjtau_stn_polasa_jagtial",
    "peddapalli": "pjtau_stn_ars_kunaram",
    "peddapally": "pjtau_stn_ars_kunaram",
    "rajanna sircilla": "pjtau_stn_polasa_jagtial",
    "sircilla": "pjtau_stn_polasa_jagtial",
    "nizamabad": "pjtau_stn_rsrrs_rudrur",
    "kamareddy": "pjtau_stn_rsrrs_rudrur",

    # Central Telangana Zone (11 districts)
    "warangal": "pjtau_stn_rars_warangal",
    "warangal urban": "pjtau_stn_rars_warangal",
    "warangal rural": "pjtau_stn_rars_warangal",
    "hanamkonda": "pjtau_stn_rars_warangal",
    "jangaon": "pjtau_stn_rars_warangal",
    "mahabubabad": "pjtau_stn_rars_warangal",
    "jayashankar bhupalpally": "pjtau_stn_rars_warangal",
    "bhupalpally": "pjtau_stn_rars_warangal",
    "mulugu": "pjtau_stn_rars_warangal",
    "khammam": "pjtau_stn_ars_madhira",
    "bhadradri kothagudem": "pjtau_stn_ars_madhira",
    "kothagudem": "pjtau_stn_ars_madhira",
    "siddipet": "pjtau_stn_ars_tornala",
    "medak": "pjtau_stn_ars_nathnaipally",
    "sangareddy": "pjtau_stn_ars_basanthpur",

    # Southern Telangana Zone (12 districts)
    "nagarkurnool": "pjtau_stn_rars_palem",
    "mahabubnagar": "pjtau_stn_rars_palem",
    "wanaparthy": "pjtau_stn_rars_palem",
    "jogulamba gadwal": "pjtau_stn_rars_palem",
    "gadwal": "pjtau_stn_rars_palem",
    "narayanpet": "pjtau_stn_rars_palem",
    "vikarabad": "pjtau_stn_ars_tandur",
    "rangareddy": "pjtau_stn_ars_tandur",
    "ranga reddy": "pjtau_stn_ars_tandur",
    "medchal-malkajgiri": "pjtau_stn_ars_tandur",
    "medchal malkajgiri": "pjtau_stn_ars_tandur",
    "medchal": "pjtau_stn_ars_tandur",
    "hyderabad": "pjtau_stn_ars_tandur",
    "nalgonda": "pjtau_stn_ars_kampasagar",
    "suryapet": "pjtau_stn_ars_kampasagar",
    "yadadri bhuvanagiri": "pjtau_stn_ars_kampasagar",
    "yadadri": "pjtau_stn_ars_kampasagar",
    "bhuvanagiri": "pjtau_stn_ars_kampasagar",
}

# Complete directory of all 33 Telangana districts with referral mapping classification (Phase 7.7.2)
TELANGANA_DISTRICT_MAPPINGS: Dict[str, DistrictMappingRecord] = {
    # Northern Telangana Zone (10 districts)
    "Adilabad": DistrictMappingRecord(
        district="Adilabad",
        station_id="pjtau_stn_ars_adilabad",
        station_canonical_name="ARS Adilabad",
        mapping_type=DistrictMappingType.LOCATED_IN_DISTRICT,
        assignment_basis="Station physically located in the same district. Address: ARS Adilabad - 504 002. Does not imply exclusive statutory single-station jurisdiction.",
        source_url=URL_NTZ
    ),
    "Kumuram Bheem Asifabad": DistrictMappingRecord(
        district="Kumuram Bheem Asifabad",
        station_id="pjtau_stn_ars_adilabad",
        station_canonical_name="ARS Adilabad",
        mapping_type=DistrictMappingType.PROVISIONAL_DESIGNATED,
        assignment_basis="Provisional designated referral centre aligned with PJTAU Northern Telangana Zone; no authoritative jurisdiction document cited.",
        source_url=URL_NTZ
    ),
    "Mancherial": DistrictMappingRecord(
        district="Mancherial",
        station_id="pjtau_stn_ars_adilabad",
        station_canonical_name="ARS Adilabad",
        mapping_type=DistrictMappingType.PROVISIONAL_DESIGNATED,
        assignment_basis="Provisional designated referral centre aligned with PJTAU Northern Telangana Zone; no authoritative jurisdiction document cited.",
        source_url=URL_NTZ
    ),
    "Nirmal": DistrictMappingRecord(
        district="Nirmal",
        station_id="pjtau_stn_ars_mudhole",
        station_canonical_name="ARS Mudhole",
        mapping_type=DistrictMappingType.LOCATED_IN_DISTRICT,
        assignment_basis="Station physically located in the same district. Address: Mudhole - 504 102, Nirmal District. Does not imply exclusive statutory single-station jurisdiction.",
        source_url=URL_NTZ
    ),
    "Karimnagar": DistrictMappingRecord(
        district="Karimnagar",
        station_id="pjtau_stn_ars_karimnagar",
        station_canonical_name="ARS Karimnagar",
        mapping_type=DistrictMappingType.LOCATED_IN_DISTRICT,
        assignment_basis="Station physically located in the same district. Address: Karimnagar - 505 001. Does not imply exclusive statutory single-station jurisdiction.",
        source_url=URL_NTZ
    ),
    "Jagtial": DistrictMappingRecord(
        district="Jagtial",
        station_id="pjtau_stn_polasa_jagtial",
        station_canonical_name="RARS Polasa, Jagtial",
        mapping_type=DistrictMappingType.LOCATED_IN_DISTRICT,
        assignment_basis="Station physically located in the same district. Address: Polasa, Jagtial - 505 529. Does not imply exclusive statutory single-station jurisdiction.",
        source_url=URL_NTZ
    ),
    "Peddapalli": DistrictMappingRecord(
        district="Peddapalli",
        station_id="pjtau_stn_ars_kunaram",
        station_canonical_name="ARS Kunaram",
        mapping_type=DistrictMappingType.LOCATED_IN_DISTRICT,
        assignment_basis="Station physically located in the same district. Address: Kunaram, Peddapalli District. Does not imply exclusive statutory single-station jurisdiction.",
        source_url=URL_NTZ
    ),
    "Rajanna Sircilla": DistrictMappingRecord(
        district="Rajanna Sircilla",
        station_id="pjtau_stn_polasa_jagtial",
        station_canonical_name="RARS Polasa, Jagtial",
        mapping_type=DistrictMappingType.PROVISIONAL_DESIGNATED,
        assignment_basis="Provisional designated referral centre aligned with PJTAU Northern Telangana Zone; no authoritative jurisdiction document cited.",
        source_url=URL_NTZ
    ),
    "Nizamabad": DistrictMappingRecord(
        district="Nizamabad",
        station_id="pjtau_stn_rsrrs_rudrur",
        station_canonical_name="RS&RRS Rudrur",
        mapping_type=DistrictMappingType.LOCATED_IN_DISTRICT,
        assignment_basis="Station physically located in the same district. Address: Rudrur, Nizamabad District. Does not imply exclusive statutory single-station jurisdiction.",
        source_url=URL_NTZ
    ),
    "Kamareddy": DistrictMappingRecord(
        district="Kamareddy",
        station_id="pjtau_stn_rsrrs_rudrur",
        station_canonical_name="RS&RRS Rudrur",
        mapping_type=DistrictMappingType.PROVISIONAL_DESIGNATED,
        assignment_basis="Provisional designated referral centre aligned with PJTAU Northern Telangana Zone; no authoritative jurisdiction document cited.",
        source_url=URL_NTZ
    ),

    # Central Telangana Zone (11 districts)
    "Warangal": DistrictMappingRecord(
        district="Warangal",
        station_id="pjtau_stn_rars_warangal",
        station_canonical_name="RARS Warangal",
        mapping_type=DistrictMappingType.LOCATED_IN_DISTRICT,
        assignment_basis="Station physically located in the same district. Address: Warangal - 506 007. Does not imply exclusive statutory single-station jurisdiction.",
        source_url=URL_CTZ
    ),
    "Hanamkonda": DistrictMappingRecord(
        district="Hanamkonda",
        station_id="pjtau_stn_rars_warangal",
        station_canonical_name="RARS Warangal",
        mapping_type=DistrictMappingType.PROVISIONAL_DESIGNATED,
        assignment_basis="Provisional designated referral centre aligned with PJTAU Central Telangana Zone; no authoritative jurisdiction document cited.",
        source_url=URL_CTZ
    ),
    "Jangaon": DistrictMappingRecord(
        district="Jangaon",
        station_id="pjtau_stn_rars_warangal",
        station_canonical_name="RARS Warangal",
        mapping_type=DistrictMappingType.PROVISIONAL_DESIGNATED,
        assignment_basis="Provisional designated referral centre aligned with PJTAU Central Telangana Zone; no authoritative jurisdiction document cited.",
        source_url=URL_CTZ
    ),
    "Mahabubabad": DistrictMappingRecord(
        district="Mahabubabad",
        station_id="pjtau_stn_rars_warangal",
        station_canonical_name="RARS Warangal",
        mapping_type=DistrictMappingType.PROVISIONAL_DESIGNATED,
        assignment_basis="Provisional designated referral centre aligned with PJTAU Central Telangana Zone; no authoritative jurisdiction document cited.",
        source_url=URL_CTZ
    ),
    "Jayashankar Bhupalpally": DistrictMappingRecord(
        district="Jayashankar Bhupalpally",
        station_id="pjtau_stn_rars_warangal",
        station_canonical_name="RARS Warangal",
        mapping_type=DistrictMappingType.PROVISIONAL_DESIGNATED,
        assignment_basis="Provisional designated referral centre aligned with PJTAU Central Telangana Zone; no authoritative jurisdiction document cited.",
        source_url=URL_CTZ
    ),
    "Mulugu": DistrictMappingRecord(
        district="Mulugu",
        station_id="pjtau_stn_rars_warangal",
        station_canonical_name="RARS Warangal",
        mapping_type=DistrictMappingType.PROVISIONAL_DESIGNATED,
        assignment_basis="Provisional designated referral centre aligned with PJTAU Central Telangana Zone; no authoritative jurisdiction document cited.",
        source_url=URL_CTZ
    ),
    "Khammam": DistrictMappingRecord(
        district="Khammam",
        station_id="pjtau_stn_ars_madhira",
        station_canonical_name="ARS Madhira",
        mapping_type=DistrictMappingType.LOCATED_IN_DISTRICT,
        assignment_basis="Station physically located in the same district. Address: Madhira - 507 203, Khammam District. Does not imply exclusive statutory single-station jurisdiction.",
        source_url=URL_CTZ
    ),
    "Bhadradri Kothagudem": DistrictMappingRecord(
        district="Bhadradri Kothagudem",
        station_id="pjtau_stn_ars_madhira",
        station_canonical_name="ARS Madhira",
        mapping_type=DistrictMappingType.PROVISIONAL_DESIGNATED,
        assignment_basis="Provisional designated referral centre aligned with PJTAU Central Telangana Zone; no authoritative jurisdiction document cited.",
        source_url=URL_CTZ
    ),
    "Siddipet": DistrictMappingRecord(
        district="Siddipet",
        station_id="pjtau_stn_ars_tornala",
        station_canonical_name="ARS Tornala",
        mapping_type=DistrictMappingType.LOCATED_IN_DISTRICT,
        assignment_basis="Station physically located in the same district. Address: Tornala, Siddipet District. Does not imply exclusive statutory single-station jurisdiction.",
        source_url=URL_CTZ
    ),
    "Medak": DistrictMappingRecord(
        district="Medak",
        station_id="pjtau_stn_ars_nathnaipally",
        station_canonical_name="ARS Nathnaipally",
        mapping_type=DistrictMappingType.LOCATED_IN_DISTRICT,
        assignment_basis="Station physically located in the same district. Address: Nathnaipally, Narsapur, Medak District. Does not imply exclusive statutory single-station jurisdiction.",
        source_url=URL_CTZ
    ),
    "Sangareddy": DistrictMappingRecord(
        district="Sangareddy",
        station_id="pjtau_stn_ars_basanthpur",
        station_canonical_name="ARS Basanthpur",
        mapping_type=DistrictMappingType.LOCATED_IN_DISTRICT,
        assignment_basis="Station physically located in the same district. Address: Basanthpur, Sangareddy District. Does not imply exclusive statutory single-station jurisdiction.",
        source_url=URL_CTZ
    ),

    # Southern Telangana Zone (12 districts)
    "Nagarkurnool": DistrictMappingRecord(
        district="Nagarkurnool",
        station_id="pjtau_stn_rars_palem",
        station_canonical_name="RARS Palem",
        mapping_type=DistrictMappingType.LOCATED_IN_DISTRICT,
        assignment_basis="Station physically located in the same district. Address: Palem - 509 215, Nagarkurnool District. Does not imply exclusive statutory single-station jurisdiction.",
        source_url=URL_STZ
    ),
    "Mahabubnagar": DistrictMappingRecord(
        district="Mahabubnagar",
        station_id="pjtau_stn_rars_palem",
        station_canonical_name="RARS Palem",
        mapping_type=DistrictMappingType.PROVISIONAL_DESIGNATED,
        assignment_basis="Provisional designated referral centre aligned with PJTAU Southern Telangana Zone; no authoritative jurisdiction document cited.",
        source_url=URL_STZ
    ),
    "Wanaparthy": DistrictMappingRecord(
        district="Wanaparthy",
        station_id="pjtau_stn_rars_palem",
        station_canonical_name="RARS Palem",
        mapping_type=DistrictMappingType.PROVISIONAL_DESIGNATED,
        assignment_basis="Provisional designated referral centre aligned with PJTAU Southern Telangana Zone; no authoritative jurisdiction document cited.",
        source_url=URL_STZ
    ),
    "Jogulamba Gadwal": DistrictMappingRecord(
        district="Jogulamba Gadwal",
        station_id="pjtau_stn_rars_palem",
        station_canonical_name="RARS Palem",
        mapping_type=DistrictMappingType.PROVISIONAL_DESIGNATED,
        assignment_basis="Provisional designated referral centre aligned with PJTAU Southern Telangana Zone; no authoritative jurisdiction document cited.",
        source_url=URL_STZ
    ),
    "Narayanpet": DistrictMappingRecord(
        district="Narayanpet",
        station_id="pjtau_stn_rars_palem",
        station_canonical_name="RARS Palem",
        mapping_type=DistrictMappingType.PROVISIONAL_DESIGNATED,
        assignment_basis="Provisional designated referral centre aligned with PJTAU Southern Telangana Zone; no authoritative jurisdiction document cited.",
        source_url=URL_STZ
    ),
    "Vikarabad": DistrictMappingRecord(
        district="Vikarabad",
        station_id="pjtau_stn_ars_tandur",
        station_canonical_name="ARS Tandur",
        mapping_type=DistrictMappingType.LOCATED_IN_DISTRICT,
        assignment_basis="Station physically located in the same district. Address: Tandur - 501 141, Vikarabad District. Does not imply exclusive statutory single-station jurisdiction.",
        source_url=URL_STZ
    ),
    "Rangareddy": DistrictMappingRecord(
        district="Rangareddy",
        station_id="pjtau_stn_ars_tandur",
        station_canonical_name="ARS Tandur",
        mapping_type=DistrictMappingType.PROVISIONAL_DESIGNATED,
        assignment_basis="Provisional designated referral centre aligned with PJTAU Southern Telangana Zone; no authoritative jurisdiction document cited.",
        source_url=URL_STZ
    ),
    "Medchal-Malkajgiri": DistrictMappingRecord(
        district="Medchal-Malkajgiri",
        station_id="pjtau_stn_ars_tandur",
        station_canonical_name="ARS Tandur",
        mapping_type=DistrictMappingType.PROVISIONAL_DESIGNATED,
        assignment_basis="Provisional designated referral centre aligned with PJTAU Southern Telangana Zone; no authoritative jurisdiction document cited.",
        source_url=URL_STZ
    ),
    "Hyderabad": DistrictMappingRecord(
        district="Hyderabad",
        station_id="pjtau_stn_ars_tandur",
        station_canonical_name="ARS Tandur",
        mapping_type=DistrictMappingType.PROVISIONAL_DESIGNATED,
        assignment_basis="Provisional designated referral centre aligned with PJTAU Southern Telangana Zone; no authoritative jurisdiction document cited.",
        source_url=URL_STZ
    ),
    "Nalgonda": DistrictMappingRecord(
        district="Nalgonda",
        station_id="pjtau_stn_ars_kampasagar",
        station_canonical_name="ARS Kampasagar",
        mapping_type=DistrictMappingType.LOCATED_IN_DISTRICT,
        assignment_basis="Station physically located in the same district. Address: Kampasagar, Babusaipet, Nalgonda District. Does not imply exclusive statutory single-station jurisdiction.",
        source_url=URL_STZ
    ),
    "Suryapet": DistrictMappingRecord(
        district="Suryapet",
        station_id="pjtau_stn_ars_kampasagar",
        station_canonical_name="ARS Kampasagar",
        mapping_type=DistrictMappingType.PROVISIONAL_DESIGNATED,
        assignment_basis="Provisional designated referral centre aligned with PJTAU Southern Telangana Zone; no authoritative jurisdiction document cited.",
        source_url=URL_STZ
    ),
    "Yadadri Bhuvanagiri": DistrictMappingRecord(
        district="Yadadri Bhuvanagiri",
        station_id="pjtau_stn_ars_kampasagar",
        station_canonical_name="ARS Kampasagar",
        mapping_type=DistrictMappingType.PROVISIONAL_DESIGNATED,
        assignment_basis="Provisional designated referral centre aligned with PJTAU Southern Telangana Zone; no authoritative jurisdiction document cited.",
        source_url=URL_STZ
    ),
}


class PJTAUStationService:
    """Service for managing PJTAU research stations, directory contacts, and referrals."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path
        self._ensure_initialized()

    def _ensure_initialized(self) -> None:
        """Ensure core tables and station tables exist."""
        init_db(self.db_path)

    def register_pjtau_sources(self) -> None:
        """
        Register or update canonical PJTAU zone sources in knowledge_sources.
        All sources enter with authority_status = 'pending_verification'.
        """
        sources = [
            (
                "src_pjtau_ntz_stations",
                "Professor Jayashankar Telangana Agricultural University",
                "PJTAU Northern Telangana Zone Research Stations Directory and Profiles",
                URL_NTZ,
                "official_portal",
                "pending_verification",
                "2026-11-06",
                RETRIEVED_AT,
                "Canonical directory and station profiles for 6 stations in Northern Telangana Zone. Displayed page update date: 06/11/2026. Retrieved on 2026-11-08."
            ),
            (
                "src_pjtau_ctz_stations",
                "Professor Jayashankar Telangana Agricultural University",
                "PJTAU Central Telangana Zone Research Stations Directory and Profiles",
                URL_CTZ,
                "official_portal",
                "pending_verification",
                "2026-11-06",
                RETRIEVED_AT,
                "Canonical directory and station profiles for 5 stations in Central Telangana Zone. Displayed page update date: 06/11/2026. Retrieved on 2026-11-08."
            ),
            (
                "src_pjtau_stz_stations",
                "Professor Jayashankar Telangana Agricultural University",
                "PJTAU Southern Telangana Zone Research Stations Directory and Profiles",
                URL_STZ,
                "official_portal",
                "pending_verification",
                "2026-11-06",
                RETRIEVED_AT,
                "Canonical directory and station profiles for 3 stations in Southern Telangana Zone. Displayed page update date: 06/11/2026. Retrieved on 2026-11-08."
            )
        ]

        conn = get_connection(self.db_path)
        try:
            with conn:
                for s_id, pub, title, url, s_type, auth_stat, pub_at, ret_at, notes in sources:
                    conn.execute("""
                        INSERT INTO knowledge_sources (
                            source_id, publisher, document_title, source_url, source_type,
                            authority_status, published_at, last_checked_at, created_at, updated_at,
                            reviewed_by, review_notes
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)
                        ON CONFLICT(source_id) DO UPDATE SET
                            document_title = excluded.document_title,
                            source_url = excluded.source_url,
                            last_checked_at = excluded.last_checked_at,
                            updated_at = excluded.updated_at,
                            review_notes = excluded.review_notes;
                    """, (s_id, pub, title, url, s_type, auth_stat, pub_at, ret_at, ret_at, ret_at, notes))
        finally:
            conn.close()

    def ingest_canonical_stations(
        self, register_sources: bool = False, record_audit: bool = False
    ) -> Dict[str, int]:
        """
        Idempotently ingests all 14 canonical PJTAU research stations, contacts,
        research outputs, and projects. All records enter in 'pending_verification'.

        If register_sources is True, also registers the 3 zone URLs in knowledge_sources.
        If record_audit is True, logs ingestion actions into knowledge_verification_audit.
        """
        if register_sources:
            self.register_pjtau_sources()
        stations = get_all_canonical_stations()

        now_iso = datetime.now(timezone.utc).isoformat()
        stations_count = 0
        contacts_count = 0
        outputs_count = 0
        projects_count = 0

        conn = get_connection(self.db_path)
        try:
            with conn:
                for stn in stations:
                    # 1. Ingest Station Profile (Category B)
                    conn.execute("""
                        INSERT INTO pjtau_research_stations (
                            station_id, canonical_name, alternate_names, pjtau_zone,
                            agro_climatic_descriptor, address, village, mandal, district,
                            pin_code, latitude, longitude, coordinates_original_text,
                            met_observatory_details, established_year, total_area_acres,
                            mandated_crops, research_focus, research_themes,
                            infrastructure_facilities, source_url, source_last_updated,
                            retrieved_at, verification_status, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(station_id) DO UPDATE SET
                            canonical_name = excluded.canonical_name,
                            alternate_names = excluded.alternate_names,
                            pjtau_zone = excluded.pjtau_zone,
                            agro_climatic_descriptor = excluded.agro_climatic_descriptor,
                            address = excluded.address,
                            village = excluded.village,
                            mandal = excluded.mandal,
                            district = excluded.district,
                            pin_code = excluded.pin_code,
                            latitude = excluded.latitude,
                            longitude = excluded.longitude,
                            coordinates_original_text = excluded.coordinates_original_text,
                            met_observatory_details = excluded.met_observatory_details,
                            established_year = excluded.established_year,
                            total_area_acres = excluded.total_area_acres,
                            mandated_crops = excluded.mandated_crops,
                            research_focus = excluded.research_focus,
                            research_themes = excluded.research_themes,
                            infrastructure_facilities = excluded.infrastructure_facilities,
                            source_url = excluded.source_url,
                            source_last_updated = excluded.source_last_updated,
                            retrieved_at = excluded.retrieved_at,
                            updated_at = excluded.updated_at;
                    """, (
                        stn.station_id,
                        stn.canonical_name,
                        json.dumps(stn.alternate_names),
                        stn.pjtau_zone.value,
                        stn.agro_climatic_descriptor,
                        stn.address,
                        stn.village,
                        stn.mandal,
                        stn.district,
                        stn.pin_code,
                        stn.latitude,
                        stn.longitude,
                        stn.coordinates_original_text,
                        stn.met_observatory_details,
                        stn.established_year,
                        stn.total_area_acres,
                        json.dumps(stn.mandated_crops),
                        stn.research_focus,
                        json.dumps(stn.research_themes),
                        json.dumps(stn.infrastructure_facilities),
                        stn.source_url,
                        stn.source_last_updated,
                        stn.retrieved_at,
                        "pending_verification",
                        now_iso,
                        now_iso
                    ))
                    stations_count += 1

                    # Audit Station Ingestion (when explicitly enabled)
                    if record_audit:
                        conn.execute("""
                            INSERT OR IGNORE INTO knowledge_verification_audit (
                                audit_id, entity_type, entity_id, action, actor,
                                actor_role, is_test_audit, notes, created_at
                            ) VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?);
                        """, (
                            f"audit_stn_{stn.station_id}",
                            "pjtau_research_station",
                            stn.station_id,
                            "ingest",
                            "pjtau_station_ingestion_service",
                            "system_ingestion",
                            f"Ingested canonical station {stn.canonical_name} ({stn.pjtau_zone.value})",
                            now_iso
                        ))

                    # 2. Ingest Contacts (Category A)
                    for con in stn.contacts:
                        conn.execute("""
                            INSERT INTO pjtau_station_contacts (
                                contact_id, station_id, contact_name, designation,
                                role, phone_number, official_email, source_reference,
                                contact_status, is_active_referral, notes, created_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            ON CONFLICT(contact_id) DO UPDATE SET
                                contact_name = excluded.contact_name,
                                designation = excluded.designation,
                                role = excluded.role,
                                phone_number = excluded.phone_number,
                                official_email = excluded.official_email,
                                source_reference = excluded.source_reference,
                                contact_status = excluded.contact_status,
                                is_active_referral = excluded.is_active_referral,
                                notes = excluded.notes;
                        """, (
                            con.contact_id,
                            con.station_id,
                            con.contact_name,
                            con.designation,
                            con.role.value,
                            con.phone_number,
                            con.official_email,
                            con.source_reference,
                            con.contact_status.value,
                            1 if con.is_active_referral else 0,
                            con.notes,
                            now_iso
                        ))
                        contacts_count += 1

                    # 3. Ingest Research Outputs (Category C)
                    for out in stn.research_outputs:
                        conn.execute("""
                            INSERT INTO pjtau_station_research_outputs (
                                output_id, station_id, output_type, crop_name,
                                variety_or_technology_name, release_year, release_status,
                                description, original_source_text, verification_status,
                                created_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            ON CONFLICT(output_id) DO UPDATE SET
                                output_type = excluded.output_type,
                                crop_name = excluded.crop_name,
                                variety_or_technology_name = excluded.variety_or_technology_name,
                                release_year = excluded.release_year,
                                release_status = excluded.release_status,
                                description = excluded.description,
                                original_source_text = excluded.original_source_text;
                        """, (
                            out.output_id,
                            out.station_id,
                            out.output_type.value,
                            out.crop_name,
                            out.variety_or_technology_name,
                            out.release_year,
                            out.release_status,
                            out.description,
                            out.original_source_text,
                            "pending_verification",
                            now_iso
                        ))
                        outputs_count += 1

                    # 4. Ingest Projects and Outreach (Category D)
                    for prj in stn.projects_and_outreach:
                        conn.execute("""
                            INSERT INTO pjtau_station_projects_outreach (
                                item_id, station_id, item_type, title, funding_agency,
                                start_date, end_date, is_till_date, published_duration_text,
                                description, original_source_text, verification_status,
                                created_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            ON CONFLICT(item_id) DO UPDATE SET
                                item_type = excluded.item_type,
                                title = excluded.title,
                                funding_agency = excluded.funding_agency,
                                start_date = excluded.start_date,
                                end_date = excluded.end_date,
                                is_till_date = excluded.is_till_date,
                                published_duration_text = excluded.published_duration_text,
                                description = excluded.description,
                                original_source_text = excluded.original_source_text;
                        """, (
                            prj.item_id,
                            prj.station_id,
                            prj.item_type.value,
                            prj.title,
                            prj.funding_agency,
                            prj.start_date,
                            prj.end_date,
                            1 if prj.is_till_date else 0,
                            prj.published_duration_text,
                            prj.description,
                            prj.original_source_text,
                            "pending_verification",
                            now_iso
                        ))
                        projects_count += 1

            logger.info(
                "PJTAU Station Ingestion successful: %d stations, %d contacts, %d outputs, %d projects.",
                stations_count, contacts_count, outputs_count, projects_count
            )
        finally:
            conn.close()

        return {
            "stations_ingested": stations_count,
            "contacts_ingested": contacts_count,
            "outputs_ingested": outputs_count,
            "projects_ingested": projects_count,
        }

    def get_station_by_id(self, station_id: str) -> Optional[PJTAUResearchStation]:
        """Fetch a canonical station by its ID along with contacts, outputs, and projects."""
        conn = get_connection(self.db_path)
        try:
            row = conn.execute(
                "SELECT * FROM pjtau_research_stations WHERE station_id = ?;",
                (station_id,)
            ).fetchone()

            if not row:
                return None

            # Fetch contacts
            contact_rows = conn.execute(
                "SELECT * FROM pjtau_station_contacts WHERE station_id = ? ORDER BY role;",
                (station_id,)
            ).fetchall()
            contacts = [
                PJTAUStationContact(
                    contact_id=cr["contact_id"],
                    station_id=cr["station_id"],
                    contact_name=cr["contact_name"],
                    designation=cr["designation"],
                    role=ContactRole(cr["role"]),
                    phone_number=cr["phone_number"],
                    official_email=cr["official_email"],
                    source_reference=cr["source_reference"],
                    contact_status=ContactStatus(cr["contact_status"]),
                    is_active_referral=bool(cr["is_active_referral"]) if "is_active_referral" in cr.keys() else False,
                    notes=cr["notes"],
                    created_at=cr["created_at"]
                )
                for cr in contact_rows
            ]

            # Fetch research outputs
            output_rows = conn.execute(
                "SELECT * FROM pjtau_station_research_outputs WHERE station_id = ?;",
                (station_id,)
            ).fetchall()
            outputs = [
                PJTAUResearchOutput(
                    output_id=orr["output_id"],
                    station_id=orr["station_id"],
                    output_type=ResearchOutputType(orr["output_type"]),
                    crop_name=orr["crop_name"],
                    variety_or_technology_name=orr["variety_or_technology_name"],
                    release_year=orr["release_year"],
                    release_status=orr["release_status"],
                    description=orr["description"],
                    original_source_text=orr["original_source_text"],
                    verification_status=orr["verification_status"],
                    created_at=orr["created_at"]
                )
                for orr in output_rows
            ]

            # Fetch projects and outreach
            project_rows = conn.execute(
                "SELECT * FROM pjtau_station_projects_outreach WHERE station_id = ?;",
                (station_id,)
            ).fetchall()
            projects = [
                PJTAUProjectOutreach(
                    item_id=pr["item_id"],
                    station_id=pr["station_id"],
                    item_type=ProjectOutreachType(pr["item_type"]),
                    title=pr["title"],
                    funding_agency=pr["funding_agency"],
                    start_date=pr["start_date"],
                    end_date=pr["end_date"],
                    is_till_date=bool(pr["is_till_date"]),
                    published_duration_text=pr["published_duration_text"],
                    description=pr["description"],
                    original_source_text=pr["original_source_text"],
                    verification_status=pr["verification_status"],
                    created_at=pr["created_at"]
                )
                for pr in project_rows
            ]

            return PJTAUResearchStation(
                station_id=row["station_id"],
                canonical_name=row["canonical_name"],
                alternate_names=json.loads(row["alternate_names"] or "[]"),
                pjtau_zone=PJTAUZone(row["pjtau_zone"]),
                address=row["address"],
                village=row["village"],
                mandal=row["mandal"],
                district=row["district"],
                pin_code=row["pin_code"],
                latitude=row["latitude"],
                longitude=row["longitude"],
                coordinates_original_text=row["coordinates_original_text"],
                met_observatory_details=row["met_observatory_details"],
                established_year=row["established_year"],
                total_area_acres=row["total_area_acres"],
                mandated_crops=json.loads(row["mandated_crops"] or "[]"),
                research_focus=row["research_focus"],
                research_themes=json.loads(row["research_themes"] or "[]"),
                infrastructure_facilities=json.loads(row["infrastructure_facilities"] or "[]"),
                source_url=row["source_url"],
                source_last_updated=row["source_last_updated"],
                retrieved_at=row["retrieved_at"],
                agro_climatic_descriptor=row["agro_climatic_descriptor"],
                verification_status=row["verification_status"],
                contacts=contacts,
                research_outputs=outputs,
                projects_and_outreach=projects,
                created_at=row["created_at"],
                updated_at=row["updated_at"]
            )
        finally:
            conn.close()

    def get_stations_by_zone(self, zone: Union[str, PJTAUZone]) -> List[PJTAUResearchStation]:
        """Fetch all stations within an agro-climatic zone."""
        zone_val = zone.value if isinstance(zone, PJTAUZone) else str(zone)
        conn = get_connection(self.db_path)
        try:
            rows = conn.execute(
                "SELECT station_id FROM pjtau_research_stations WHERE pjtau_zone = ? ORDER BY canonical_name;",
                (zone_val,)
            ).fetchall()
            stations: List[PJTAUResearchStation] = []
            for r in rows:
                stn = self.get_station_by_id(r["station_id"])
                if stn:
                    stations.append(stn)
            return stations
        finally:
            conn.close()

    def get_station_for_district(self, district_name: str) -> Optional[PJTAUResearchStation]:
        """
        Map a farmer district name to its corresponding primary PJTAU research station.
        Matches case-insensitively and handles common variations.
        """
        if not district_name:
            return None

        clean_dist = district_name.strip().lower()
        # Direct lookup
        station_id = TELANGANA_DISTRICT_TO_STATION.get(clean_dist)

        # Fallback: substring matching if exact match not found
        if not station_id:
            for dist_key, stn_id in TELANGANA_DISTRICT_TO_STATION.items():
                if dist_key in clean_dist or clean_dist in dist_key:
                    station_id = stn_id
                    break

        if station_id:
            return self.get_station_by_id(station_id)

        # Direct database query by district column
        conn = get_connection(self.db_path)
        try:
            row = conn.execute(
                "SELECT station_id FROM pjtau_research_stations WHERE LOWER(district) = ? LIMIT 1;",
                (clean_dist,)
            ).fetchone()
            if row:
                return self.get_station_by_id(row["station_id"])
        finally:
            conn.close()

        return None

    def get_district_mapping_record(self, district_name: str) -> Optional[DistrictMappingRecord]:
        """
        Lookup the district mapping provenance record for a given district.
        Handles case insensitivity and common aliases.
        """
        if not district_name:
            return None
        clean = district_name.strip().lower()

        # Direct match in TELANGANA_DISTRICT_MAPPINGS
        for dist, record in TELANGANA_DISTRICT_MAPPINGS.items():
            if dist.lower() == clean:
                return record

        # Match alias dictionary
        alias_map = {
            "asifabad": "Kumuram Bheem Asifabad",
            "komaram bheem asifabad": "Kumuram Bheem Asifabad",
            "jagityal": "Jagtial",
            "peddapally": "Peddapalli",
            "sircilla": "Rajanna Sircilla",
            "warangal urban": "Warangal",
            "warangal rural": "Warangal",
            "bhupalpally": "Jayashankar Bhupalpally",
            "kothagudem": "Bhadradri Kothagudem",
            "gadwal": "Jogulamba Gadwal",
            "ranga reddy": "Rangareddy",
            "medchal": "Medchal-Malkajgiri",
            "medchal malkajgiri": "Medchal-Malkajgiri",
            "yadadri": "Yadadri Bhuvanagiri",
            "bhuvanagiri": "Yadadri Bhuvanagiri",
        }
        canonical_name = alias_map.get(clean)
        if canonical_name and canonical_name in TELANGANA_DISTRICT_MAPPINGS:
            return TELANGANA_DISTRICT_MAPPINGS[canonical_name]

        # Substring fallback
        for dist, record in TELANGANA_DISTRICT_MAPPINGS.items():
            if dist.lower() in clean or clean in dist.lower():
                return record

        return None

    def get_all_district_mappings(self) -> Dict[str, DistrictMappingRecord]:
        """Returns the complete mapping dictionary of all 33 Telangana districts."""
        return dict(TELANGANA_DISTRICT_MAPPINGS)

    def format_station_referral(
        self, district_name: str, language: str = "Telugu"
    ) -> StationReferralResponse:
        """
        Generates a farmer-facing research station referral response.

        Guarantees:
        - If the station has an active verified/owner-selected contact with a valid phone number:
          returns structured referral with station name, contact details, and phone.
        - If contact is unverified, conflicting (NEEDS_CONFIRMATION), or missing (None):
          returns the safe fallback referral without inventing numbers or contact names.
        - Wording strictly follows non-authoritative designated terminology:
          "Your designated PJTAU research station may be able to guide you: [station name]... Please contact [role/name] at Phone: [phone]."
          Does not claim "nearest station" or "officially responsible".
        """
        lang = (language or "Telugu").strip().lower()
        is_telugu = "telugu" in lang
        is_hindi = "hindi" in lang

        stn = self.get_station_for_district(district_name)

        if not stn:
            # District not recognized - safe fallback
            if is_telugu:
                text = "క్షమించండి, మీ జిల్లాకు సంబంధించిన అధికారిక పరిశోధనా కేంద్ర సమాచారం అందుబాటులో లేదు. దయచేసి మీ స్థానిక మండల వ్యవసాయ అధికారిని (AO) లేదా సమీప కృషి విజ్ఞాన కేంద్రాన్ని (KVK) సంప్రదించండి."
            elif is_hindi:
                text = "क्षमा करें, आपके जिले के लिए अनुसंधान केंद्र की जानकारी उपलब्ध नहीं है। कृपया अपने स्थानीय कृषि अधिकारी (AO) या कृषि विज्ञान केंद्र (KVK) से संपर्क करें।"
            else:
                text = "PJTAU research station information is not available for this district. Please contact your local Agricultural Officer (AO) or nearest Krishi Vigyan Kendra (KVK) for guidance."

            return StationReferralResponse(
                station_id=None,
                station_name=None,
                district=district_name,
                contact_phone=None,
                contact_name=None,
                contact_designation=None,
                referral_text=text,
                is_fallback=True,
                status=ContactStatus.UNAVAILABLE
            )

        # 1. Look for active referral contact (owner-selected or independently verified with valid phone)
        valid_statuses = (
            ContactStatus.OWNER_SELECTED,
            ContactStatus.INDEPENDENTLY_VERIFIED,
            ContactStatus.VERIFIED,
        )
        active_contact = next(
            (c for c in stn.contacts if c.is_active_referral and c.contact_status in valid_statuses and c.phone_number),
            None
        )

        # 2. Fallback to any verified contact with valid phone number if active_contact not explicitly set
        if not active_contact:
            for con in stn.contacts:
                if con.contact_status in valid_statuses and con.phone_number:
                    if con.role in (ContactRole.STATION_HEAD_INCHARGE, ContactRole.GENERAL_OFFICE):
                        active_contact = con
                        break
                    elif not active_contact:
                        active_contact = con

        # If verified / owner-selected active contact exists and has phone:
        if active_contact and active_contact.phone_number:
            role_desc = active_contact.designation or active_contact.contact_name or "స్టేషన్ ఇన్-ఛార్జ్"
            phone = active_contact.phone_number

            if is_telugu:
                text = (
                    f"మీ జిల్లాకు కేటాయించిన PJTAU పరిశోధనా కేంద్రం మీకు మార్గదర్శనం చేయగలదు: "
                    f"{stn.canonical_name} ({stn.district} జిల్లా). "
                    f"దయచేసి {role_desc} గారిని ఫోన్: {phone} ద్వారా సంప్రదించండి."
                )
            elif is_hindi:
                text = (
                    f"आपके जिले के लिए नामित PJTAU अनुसंधान केंद्र आपका मार्गदर्शन कर सकता है: "
                    f"{stn.canonical_name} ({stn.district} जिला)। "
                    f"कृपया {role_desc} से फोन: {phone} पर संपर्क करें।"
                )
            else:
                text = (
                    f"Your designated PJTAU research station may be able to guide you: "
                    f"{stn.canonical_name} ({stn.district} District). "
                    f"Please contact {role_desc} at Phone: {phone}."
                )

            return StationReferralResponse(
                station_id=stn.station_id,
                station_name=stn.canonical_name,
                district=stn.district,
                contact_phone=phone,
                contact_name=active_contact.contact_name,
                contact_designation=active_contact.designation,
                referral_text=text,
                is_fallback=False,
                status=active_contact.contact_status
            )

        # Station found, but contact is unavailable / unverified (e.g. Kampasagar)
        if is_telugu:
            text = (
                f"మీ జిల్లాకు కేటాయించిన PJTAU పరిశోధనా కేంద్రం {stn.canonical_name} ({stn.district} జిల్లా) కు "
                f"సంబంధించిన ఫోన్ సంప్రదింపు వివరాలు ప్రస్తుతం అందుబాటులో లేవు. "
                f"దయచేసి మీ మండల వ్యవసాయ అధికారిని (AO) లేదా సమీప కృషి విజ్ఞాన కేంద్రాన్ని (KVK) సంప్రదించండి."
            )
        elif is_hindi:
            text = (
                f"आपके जिले के लिए नामित PJTAU अनुसंधान केंद्र {stn.canonical_name} ({stn.district} जिला) के लिए "
                f"सीधा फोन संपर्क वर्तमान में उपलब्ध नहीं है। "
                f"कृपया अपने स्थानीय कृषि अधिकारी (AO) या कृषि विज्ञान केंद्र (KVK) से संपर्क करें।"
            )
        else:
            text = (
                f"Direct phone contact is currently unavailable for {stn.canonical_name} ({stn.district} District), "
                f"your designated PJTAU research station. "
                f"Please contact your local Agricultural Officer (AO) or nearest Krishi Vigyan Kendra (KVK) for guidance."
            )

        return StationReferralResponse(
            station_id=stn.station_id,
            station_name=stn.canonical_name,
            district=stn.district,
            contact_phone=None,
            contact_name=None,
            contact_designation=None,
            referral_text=text,
            is_fallback=True,
            status=ContactStatus.UNAVAILABLE
        )
