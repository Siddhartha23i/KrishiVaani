"""
Unit and integration tests for PJTAU Research Station Directory, Profiles,
Research Outputs, and Referral Logic (KrishiVaani Phase 7.7.1).
"""

import json
import sqlite3
import tempfile
from pathlib import Path
import pytest

from app.knowledge.pjtau.station_schemas import (
    PJTAUZone,
    ContactRole,
    ContactStatus,
    DistrictMappingType,
    DistrictMappingRecord,
    ResearchOutputType,
    ProjectOutreachType,
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
from app.knowledge.pjtau.station_service import (
    PJTAUStationService,
    TELANGANA_DISTRICT_TO_STATION,
    TELANGANA_DISTRICT_MAPPINGS,
)


@pytest.fixture
def temp_db_path(tmp_path: Path) -> Path:
    """Provides an isolated SQLite database path for testing."""
    return tmp_path / "test_pjtau_stations.db"


@pytest.fixture
def station_service(temp_db_path: Path) -> PJTAUStationService:
    """Provides a fresh PJTAUStationService instance with initialized tables."""
    return PJTAUStationService(temp_db_path)


class TestPJTAUStationData:
    """Tests for the canonical station data definitions."""

    def test_canonical_stations_count_and_distribution(self):
        """Verify exactly 14 canonical stations across the 3 agro-climatic zones."""
        stations = get_all_canonical_stations()
        assert len(stations) == 14

        ntz = [s for s in stations if s.pjtau_zone == PJTAUZone.NORTHERN_ZONE]
        ctz = [s for s in stations if s.pjtau_zone == PJTAUZone.CENTRAL_ZONE]
        stz = [s for s in stations if s.pjtau_zone == PJTAUZone.SOUTHERN_ZONE]

        assert len(ntz) == 6, f"Expected 6 NTZ stations, got {len(ntz)}"
        assert len(ctz) == 5, f"Expected 5 CTZ stations, got {len(ctz)}"
        assert len(stz) == 3, f"Expected 3 STZ stations, got {len(stz)}"

    def test_source_metadata_dates_preserved(self):
        """Verify both page displayed update date (06/11/2026) and actual retrieval date are preserved."""
        stations = get_all_canonical_stations()
        for stn in stations:
            assert stn.source_last_updated == "06/11/2026"
            assert "2026-11-08" in stn.retrieved_at
            assert stn.source_url in (URL_NTZ, URL_CTZ, URL_STZ)

    def test_14_selected_station_contacts(self):
        """Verify all 14 selected station-in-charge contacts match the owner-supplied PJTAU numbers."""
        expected_selected = {
            # Northern Telangana Zone
            "pjtau_stn_polasa_jagtial": "8332970384",
            "pjtau_stn_rsrrs_rudrur": "8333818205",
            "pjtau_stn_ars_adilabad": "8333818203",
            "pjtau_stn_ars_karimnagar": "8333818201",
            "pjtau_stn_ars_mudhole": "8332970250",
            "pjtau_stn_ars_kunaram": "8333818202",
            # Central Telangana Zone
            "pjtau_stn_rars_warangal": "8332970385",
            "pjtau_stn_ars_madhira": "8333818207",
            "pjtau_stn_ars_tornala": "8333818210",
            "pjtau_stn_ars_basanthpur": "8333818208",
            "pjtau_stn_ars_nathnaipally": "8333818209",
            # Southern Telangana Zone
            "pjtau_stn_rars_palem": "8332970257",
            "pjtau_stn_ars_tandur": "8332970254",
            "pjtau_stn_ars_kampasagar": None,
        }

        stations = get_all_canonical_stations()
        for stn in stations:
            assert stn.station_id in expected_selected
            expected_num = expected_selected[stn.station_id]

            # Find active referral contact
            active = next((c for c in stn.contacts if c.is_active_referral), None)
            assert active is not None, f"No active referral contact on {stn.station_id}"
            assert active.phone_number == expected_num, (
                f"Expected {expected_num} for {stn.station_id}, got {active.phone_number}"
            )

    def test_mudhole_conflict_and_selected_referral_contact(self):
        """Verify ARS Mudhole has canonical name 'ARS Mudhole', selected active contact 8332970250, and 2 preserved historical candidates."""
        stations = get_all_canonical_stations()
        mudhole = next(s for s in stations if s.station_id == "pjtau_stn_ars_mudhole")

        assert "ARS Mudhole" in mudhole.canonical_name
        assert any("Mudhol" in name for name in mudhole.alternate_names)
        assert len(mudhole.contacts) == 3

        # Active selected contact
        selected = next(c for c in mudhole.contacts if c.contact_id == "pjtau_con_mudhole_incharge_selected")
        assert selected.role == ContactRole.STATION_HEAD_INCHARGE
        assert selected.contact_status == ContactStatus.OWNER_SELECTED
        assert selected.contact_status != ContactStatus.INDEPENDENTLY_VERIFIED
        assert selected.phone_number == "8332970250"
        assert selected.is_active_referral is True
        assert "Sri A. Dinesh" in (selected.contact_name or "")
        assert "Scientist, ARS Mudhole" in (selected.designation or "")

        # Retained historical candidate 1: In-charge contact from RTI with conflict
        c1 = next(c for c in mudhole.contacts if c.contact_id == "pjtau_con_mudhole_ars_incharge")
        assert c1.role == ContactRole.STATION_HEAD_INCHARGE
        assert c1.contact_status == ContactStatus.NEEDS_CONFIRMATION
        assert c1.phone_number == "8333818204"
        assert c1.is_active_referral is False

        # Retained historical candidate 2: TRVK coordinator
        c2 = next(c for c in mudhole.contacts if c.contact_id == "pjtau_con_mudhole_trvk_coord")
        assert c2.role == ContactRole.TRVK_COORDINATOR
        assert c2.contact_status == ContactStatus.INDEPENDENTLY_VERIFIED
        assert c2.phone_number == "8332970250"
        assert c2.is_active_referral is False

    def test_adilabad_meteorological_observatory_details_separated(self):
        """Verify Adilabad met observatory details are cleanly separated from agro-climatic zone."""
        stations = get_all_canonical_stations()
        adb = next(s for s in stations if s.station_id == "pjtau_stn_ars_adilabad")

        assert adb.pjtau_zone == PJTAUZone.NORTHERN_ZONE
        assert adb.met_observatory_details is not None
        assert "Meteorological Observatory (class B-type)" in adb.met_observatory_details
        assert "Automatic weather station" in adb.met_observatory_details

    def test_palem_zone_and_descriptor_separation(self):
        """Verify RARS Palem zone is Southern Telangana Zone while 'Semi Arid' is agro_climatic_descriptor."""
        stations = get_all_canonical_stations()
        palem = next(s for s in stations if s.station_id == "pjtau_stn_rars_palem")

        assert palem.pjtau_zone == PJTAUZone.SOUTHERN_ZONE
        assert palem.agro_climatic_descriptor == "Semi Arid"

    def test_kampasagar_missing_phone_null_handling(self):
        """Verify ARS Kampasagar records missing phone as None without hallucinating."""
        stations = get_all_canonical_stations()
        kampa = next(s for s in stations if s.station_id == "pjtau_stn_ars_kampasagar")

        assert len(kampa.contacts) == 1
        con = kampa.contacts[0]
        assert con.phone_number is None
        assert con.official_email is None
        assert con.contact_status == ContactStatus.UNAVAILABLE
        assert con.is_active_referral is True

    def test_personal_email_filtering_policy(self):
        """Verify personal/yahoo/gmail emails are filtered out of official contact fields."""
        stations = get_all_canonical_stations()

        # Polasa (adr_jagtial@yahoo.com -> filtered to None)
        polasa = next(s for s in stations if s.station_id == "pjtau_stn_polasa_jagtial")
        for c in polasa.contacts:
            assert c.official_email is None

        # Warangal (adrwgl@pjtau.edu.in -> retained as official)
        warangal = next(s for s in stations if s.station_id == "pjtau_stn_rars_warangal")
        for c in warangal.contacts:
            assert c.official_email == "adrwgl@pjtau.edu.in"

        # Madhira (arsmadhira@pjtau.edu.in -> retained)
        madhira = next(s for s in stations if s.station_id == "pjtau_stn_ars_madhira")
        for c in madhira.contacts:
            assert c.official_email == "arsmadhira@pjtau.edu.in"

        # Tornala (ars.tornala@pjtau.edu.in -> retained)
        tornala = next(s for s in stations if s.station_id == "pjtau_stn_ars_tornala")
        for c in tornala.contacts:
            assert c.official_email == "ars.tornala@pjtau.edu.in"

        # Basanthpur (arsmedak@pjtau.edu.in -> retained)
        basanthpur = next(s for s in stations if s.station_id == "pjtau_stn_ars_basanthpur")
        for c in basanthpur.contacts:
            assert c.official_email == "arsmedak@pjtau.edu.in"

        # Nathnaipally (arsnathnaipally@pjtau.edu.in -> retained)
        nathnaipally = next(s for s in stations if s.station_id == "pjtau_stn_ars_nathnaipally")
        for c in nathnaipally.contacts:
            assert c.official_email == "arsnathnaipally@pjtau.edu.in"


class TestPJTAUStationIngestion:
    """Tests for database persistence, schema idempotency, and audit logging."""

    def test_ingestion_counts_and_persistence(self, station_service: PJTAUStationService):
        """Verify successful initial ingestion and accurate database row counts."""
        res = station_service.ingest_canonical_stations()

        assert res["stations_ingested"] == 14
        assert res["contacts_ingested"] == 40
        assert res["outputs_ingested"] == 40
        assert res["projects_ingested"] == 35

        # Verify rows in database
        conn = sqlite3.connect(station_service.db_path)
        cur = conn.cursor()

        cur.execute("SELECT COUNT(*) FROM pjtau_research_stations;")
        stn_count = cur.fetchone()[0]
        assert stn_count == 14

        cur.execute("SELECT COUNT(*) FROM pjtau_station_contacts;")
        con_count = cur.fetchone()[0]
        assert con_count == 40

        cur.execute("SELECT COUNT(*) FROM pjtau_station_research_outputs;")
        out_count = cur.fetchone()[0]
        assert out_count == 40

        cur.execute("SELECT COUNT(*) FROM pjtau_station_projects_outreach;")
        prj_count = cur.fetchone()[0]
        assert prj_count == 35

        # Verify source registration method
        station_service.register_pjtau_sources()
        cur.execute("SELECT COUNT(*) FROM knowledge_sources WHERE source_id LIKE 'src_pjtau_%_stations';")
        src_count = cur.fetchone()[0]
        assert src_count == 3

        conn.close()

    def test_ingestion_idempotency(self, station_service: PJTAUStationService):
        """Verify running ingestion multiple times does not duplicate records."""
        # First run
        station_service.ingest_canonical_stations()

        # Second run
        station_service.ingest_canonical_stations()

        conn = sqlite3.connect(station_service.db_path)
        cur = conn.cursor()

        cur.execute("SELECT COUNT(*) FROM pjtau_research_stations;")
        assert cur.fetchone()[0] == 14

        cur.execute("SELECT COUNT(*) FROM pjtau_station_contacts;")
        con_count_2 = cur.fetchone()[0]
        assert con_count_2 == 40

        cur.execute("SELECT COUNT(*) FROM pjtau_station_research_outputs;")
        out_count_2 = cur.fetchone()[0]
        assert out_count_2 == 40

        cur.execute("SELECT COUNT(*) FROM pjtau_station_projects_outreach;")
        prj_count_2 = cur.fetchone()[0]
        assert prj_count_2 == 35

        conn.close()

    def test_review_status_pending_verification_default(self, station_service: PJTAUStationService):
        """Verify all newly ingested records strictly enter review lifecycle in 'pending_verification' status."""
        station_service.ingest_canonical_stations()

        conn = sqlite3.connect(station_service.db_path)
        cur = conn.cursor()

        # All stations pending_verification
        cur.execute("SELECT COUNT(*) FROM pjtau_research_stations WHERE verification_status != 'pending_verification';")
        assert cur.fetchone()[0] == 0

        # All research outputs pending_verification
        cur.execute("SELECT COUNT(*) FROM pjtau_station_research_outputs WHERE verification_status != 'pending_verification';")
        assert cur.fetchone()[0] == 0

        # All projects pending_verification
        cur.execute("SELECT COUNT(*) FROM pjtau_station_projects_outreach WHERE verification_status != 'pending_verification';")
        assert cur.fetchone()[0] == 0

        # All sources pending_verification
        cur.execute("SELECT COUNT(*) FROM knowledge_sources WHERE source_id LIKE 'src_pjtau_%_stations' AND authority_status != 'pending_verification';")
        assert cur.fetchone()[0] == 0

        conn.close()

    def test_audit_records_created(self, station_service: PJTAUStationService):
        """Verify ingestion logs audit entries in knowledge_verification_audit when record_audit is True."""
        station_service.ingest_canonical_stations(record_audit=True)

        conn = sqlite3.connect(station_service.db_path)
        cur = conn.cursor()

        cur.execute("SELECT COUNT(*) FROM knowledge_verification_audit WHERE entity_type = 'pjtau_research_station';")
        audit_count = cur.fetchone()[0]
        assert audit_count == 14

        conn.close()


class TestPJTAUReferralService:
    """Tests for safe farmer-facing referral logic across districts and languages."""

    @pytest.fixture(autouse=True)
    def setup_service(self, station_service: PJTAUStationService):
        station_service.ingest_canonical_stations()

    def test_mudhole_referral_uses_selected_contact_8332970250(self, station_service: PJTAUStationService):
        """
        Verify that ARS Mudhole (Nirmal district) uses the owner-selected active contact
        8332970250 for Sri A. Dinesh, Scientist, without withholding.
        Status is strictly OWNER_SELECTED (not INDEPENDENTLY_VERIFIED).
        """
        res = station_service.format_station_referral("Nirmal", "English")

        assert not res.is_fallback
        assert res.status == ContactStatus.OWNER_SELECTED
        assert res.status != ContactStatus.INDEPENDENTLY_VERIFIED
        assert res.station_id == "pjtau_stn_ars_mudhole"
        assert res.contact_phone == "8332970250"
        assert "8332970250" in res.referral_text
        assert "Scientist, ARS Mudhole" in res.referral_text
        assert "Your designated PJTAU research station may be able to guide you: ARS Mudhole" in res.referral_text

    def test_mudhole_referral_telugu(self, station_service: PJTAUStationService):
        """Verify Mudhole referral in Telugu using designated non-authoritative terminology."""
        res = station_service.format_station_referral("Nirmal", "Telugu")

        assert not res.is_fallback
        assert res.status == ContactStatus.OWNER_SELECTED
        assert res.contact_phone == "8332970250"
        assert "మీ జిల్లాకు కేటాయించిన PJTAU పరిశోధనా కేంద్రం మీకు మార్గదర్శనం చేయగలదు: ARS Mudhole" in res.referral_text
        assert "8332970250" in res.referral_text

    def test_verified_station_referral_english(self, station_service: PJTAUStationService):
        """Verify successful referral with selected active contact in English using designated phrasing."""
        res = station_service.format_station_referral("Adilabad", "English")

        assert not res.is_fallback
        assert res.status == ContactStatus.OWNER_SELECTED
        assert res.station_id == "pjtau_stn_ars_adilabad"
        assert res.contact_phone == "8333818203"
        assert "Your designated PJTAU research station may be able to guide you: Agricultural Research Station, Adilabad" in res.referral_text
        assert "Adilabad" in res.referral_text

    def test_verified_station_referral_telugu(self, station_service: PJTAUStationService):
        """Verify successful referral with selected active contact in Telugu using designated phrasing."""
        res = station_service.format_station_referral("Warangal", "Telugu")

        assert not res.is_fallback
        assert res.status == ContactStatus.OWNER_SELECTED
        assert res.station_id == "pjtau_stn_rars_warangal"
        assert res.contact_phone == "8332970385"
        assert "మీ జిల్లాకు కేటాయించిన PJTAU పరిశోధనా కేంద్రం మీకు మార్గదర్శనం చేయగలదు: Regional Agricultural Research Station, Warangal" in res.referral_text

    def test_missing_kampasagar_phone_triggers_safe_fallback(self, station_service: PJTAUStationService):
        """
        Verify that ARS Kampasagar (Nalgonda district), having no listed phone on official station page,
        strictly returns a safe fallback referral using designated phrasing without inventing numbers.
        """
        res = station_service.format_station_referral("Nalgonda", "Telugu")

        assert res.is_fallback
        assert res.contact_phone is None
        assert "మీ జిల్లాకు కేటాయించిన PJTAU పరిశోధనా కేంద్రం Agricultural Research Station, Kampasagar" in res.referral_text
        assert "సంబంధించిన ఫోన్ సంప్రదింపు వివరాలు ప్రస్తుతం అందుబాటులో లేవు" in res.referral_text
        assert "దయచేసి మీ మండల వ్యవసాయ అధికారిని (AO) లేదా సమీప కృషి విజ్ఞాన కేంద్రాన్ని (KVK) సంప్రదించండి" in res.referral_text

    def test_missing_kampasagar_phone_english_fallback(self, station_service: PJTAUStationService):
        """Verify Kampasagar fallback in English."""
        res = station_service.format_station_referral("Nalgonda", "English")

        assert res.is_fallback
        assert res.contact_phone is None
        assert "Direct phone contact is currently unavailable for Agricultural Research Station, Kampasagar (Nalgonda District)" in res.referral_text
        assert "your designated PJTAU research station" in res.referral_text

    def test_unknown_district_triggers_safe_fallback(self, station_service: PJTAUStationService):
        """Verify non-existent district safely returns fallback guidance."""
        res = station_service.format_station_referral("UnknownDistrict", "English")

        assert res.is_fallback
        assert res.station_id is None
        assert res.contact_phone is None
        assert "Agricultural Officer (AO)" in res.referral_text

    def test_all_33_districts_map_to_valid_station(self, station_service: PJTAUStationService):
        """Verify that every one of Telangana's 33 districts maps to a valid designated station."""
        districts = [
            "Adilabad", "Kumuram Bheem Asifabad", "Mancherial", "Nirmal",
            "Karimnagar", "Jagtial", "Peddapalli", "Rajanna Sircilla",
            "Nizamabad", "Kamareddy", "Warangal", "Hanamkonda", "Jangaon",
            "Mahabubabad", "Jayashankar Bhupalpally", "Mulugu", "Khammam",
            "Bhadradri Kothagudem", "Siddipet", "Medak", "Sangareddy",
            "Nagarkurnool", "Mahabubnagar", "Wanaparthy", "Jogulamba Gadwal",
            "Narayanpet", "Vikarabad", "Rangareddy", "Medchal-Malkajgiri",
            "Hyderabad", "Nalgonda", "Suryapet", "Yadadri Bhuvanagiri"
        ]

        assert len(districts) == 33

        for dist in districts:
            stn = station_service.get_station_for_district(dist)
            assert stn is not None, f"District '{dist}' failed to map to a PJTAU research station"
            assert stn.station_id.startswith("pjtau_stn_")
            assert stn.canonical_name is not None

    def test_historical_contacts_preserved(self, station_service: PJTAUStationService):
        """Verify that historical and alternate contacts (landlines, alternate mobiles) are retained."""
        polasa = station_service.get_station_by_id("pjtau_stn_polasa_jagtial")
        assert polasa is not None
        assert len(polasa.contacts) == 3

        # Active selected
        selected = next(c for c in polasa.contacts if c.is_active_referral)
        assert selected.phone_number == "8332970384"

        # Retained landline
        landline = next(c for c in polasa.contacts if c.role == ContactRole.GENERAL_OFFICE)
        assert landline.phone_number == "08724-277281"
        assert landline.is_active_referral is False

        # Retained alternate mobile
        alt_mobile = next(c for c in polasa.contacts if c.contact_id == "pjtau_con_polasa_adr")
        assert alt_mobile.phone_number == "9989625211"
        assert alt_mobile.is_active_referral is False

    def test_district_mapping_classification_and_provenance(self, station_service: PJTAUStationService):
        """
        Verify Phase 7.7.2 district mapping classifications across all 33 Telangana districts:
        - Exactly 14 LOCATED_IN_DISTRICT
        - Exactly 19 PROVISIONAL_DESIGNATED
        - Exactly 0 OFFICIALLY_DOCUMENTED (no gazetted order or university statute exists)
        - None claim 'officially responsible'
        """
        mappings = station_service.get_all_district_mappings()
        assert len(mappings) == 33

        located = [m for m in mappings.values() if m.mapping_type == DistrictMappingType.LOCATED_IN_DISTRICT]
        provisional = [m for m in mappings.values() if m.mapping_type == DistrictMappingType.PROVISIONAL_DESIGNATED]
        official = [m for m in mappings.values() if m.mapping_type == DistrictMappingType.OFFICIALLY_DOCUMENTED]

        assert len(located) == 14, f"Expected 14 LOCATED_IN_DISTRICT, got {len(located)}"
        assert len(provisional) == 19, f"Expected 19 PROVISIONAL_DESIGNATED, got {len(provisional)}"
        assert len(official) == 0, f"Expected 0 OFFICIALLY_DOCUMENTED, got {len(official)}"

        # Check provenance details for host vs non-host
        nirmal_rec = station_service.get_district_mapping_record("Nirmal")
        assert nirmal_rec is not None
        assert nirmal_rec.mapping_type == DistrictMappingType.LOCATED_IN_DISTRICT
        assert nirmal_rec.station_id == "pjtau_stn_ars_mudhole"
        assert "physically located" in nirmal_rec.assignment_basis.lower()
        assert "exclusive statutory" in nirmal_rec.assignment_basis.lower()

        asifabad_rec = station_service.get_district_mapping_record("Kumuram Bheem Asifabad")
        assert asifabad_rec is not None
        assert asifabad_rec.mapping_type == DistrictMappingType.PROVISIONAL_DESIGNATED
        assert asifabad_rec.station_id == "pjtau_stn_ars_adilabad"
        assert "provisional designated" in asifabad_rec.assignment_basis.lower()
        assert "no authoritative jurisdiction document cited" in asifabad_rec.assignment_basis.lower()

        # Alias lookup
        asifabad_alias_rec = station_service.get_district_mapping_record("asifabad")
        assert asifabad_alias_rec is not None
        assert asifabad_alias_rec.station_id == "pjtau_stn_ars_adilabad"

        # Ensure no record claims "officially responsible"
        for rec in mappings.values():
            assert "officially responsible" not in rec.assignment_basis.lower()
            assert rec.source_url in (URL_NTZ, URL_CTZ, URL_STZ)

    def test_no_unsupported_claims_in_farmer_referrals(self, station_service: PJTAUStationService):
        """
        Verify farmer-facing referral responses across districts and languages:
        - NEVER claim a station is the 'nearest station' or 'nearest research station'
        - NEVER claim a station is 'officially responsible'
        - Uses designated wording: 'Your designated PJTAU research station may be able to guide you'
        """
        test_districts = ["Adilabad", "Nirmal", "Warangal", "Nalgonda", "Kumuram Bheem Asifabad", "Hyderabad"]

        for dist in test_districts:
            # English
            res_en = station_service.format_station_referral(dist, "English")
            assert "nearest research station" not in res_en.referral_text.lower()
            assert "nearest station" not in res_en.referral_text.lower()
            assert "officially responsible" not in res_en.referral_text.lower()
            if not res_en.is_fallback:
                assert "your designated pjtau research station may be able to guide you" in res_en.referral_text.lower()

            # Telugu
            res_te = station_service.format_station_referral(dist, "Telugu")
            assert "అధికారిక బాధ్యత" not in res_te.referral_text  # officially responsible
            if not res_te.is_fallback:
                assert "మీ జిల్లాకు కేటాయించిన pjtau పరిశోధనా కేంద్రం మీకు మార్గదర్శనం చేయగలదు" in res_te.referral_text.lower()
