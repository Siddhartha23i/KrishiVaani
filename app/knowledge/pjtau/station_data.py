"""
Canonical dataset for PJTAU Research Stations across Northern, Central, and Southern Telangana Zones.
Source of Truth:
- Northern Telangana Zone: https://pjtau.edu.in/north-telangana-zone/ (6 stations)
- Central Telangana Zone: https://pjtau.edu.in/central-telangana-zone/ (5 stations)
- Southern Telangana Zone: https://pjtau.edu.in/south-telangana-zone/ (3 stations)

Page displayed update date: 06/11/2026 (or 06-11-2026).
Actual retrieval timestamp: 2026-11-08.
"""

from typing import List
from app.knowledge.pjtau.station_schemas import (
    PJTAUZone,
    ContactRole,
    ContactStatus,
    ResearchOutputType,
    ProjectOutreachType,
    PJTAUStationContact,
    PJTAUResearchOutput,
    PJTAUProjectOutreach,
    PJTAUResearchStation,
)

SOURCE_LAST_UPDATED = "06/11/2026"
RETRIEVED_AT = "2026-11-08T13:00:00Z"

URL_NTZ = "https://pjtau.edu.in/north-telangana-zone/"
URL_CTZ = "https://pjtau.edu.in/central-telangana-zone/"
URL_STZ = "https://pjtau.edu.in/south-telangana-zone/"


def _get_ntz_stations() -> List[PJTAUResearchStation]:
    """Northern Telangana Zone - 6 Research Stations."""
    stations: List[PJTAUResearchStation] = []

    # 1. RARS, Polasa (Jagtial)
    stn_polasa = PJTAUResearchStation(
        station_id="pjtau_stn_polasa_jagtial",
        canonical_name="Regional Agricultural Research Station, Polasa, Jagtial",
        alternate_names=["RARS, Polasa", "RARS Jagtial", "Regional Agricultural Research Station, Polasa"],
        pjtau_zone=PJTAUZone.NORTHERN_ZONE,
        address="Regional Agricultural Research Station, Polasa, Jagtial - 505 529, Telangana",
        village="Polasa",
        mandal="Jagtial",
        district="Jagtial",
        pin_code="505529",
        latitude=18.85,
        longitude=78.93,
        coordinates_original_text="Latitude: 18° 51' N, Longitude: 78° 56' E, Altitude: 243.34 m MSL",
        met_observatory_details=None,
        established_year="1989",
        total_area_acres=328.87,  # 133.09 ha
        mandated_crops=["Rice", "Sesamum", "Groundnut", "Redgram", "Safflower", "Turmeric", "Mango", "Soybean", "Maize"],
        research_focus="Breeding high-yielding varieties of rice, sesamum, and pulses; cost-effective cropping systems and farm mechanization for Northern Telangana.",
        research_themes=[
            "Crop improvement in rice, sesamum, and oilseeds",
            "Cropping systems research and resource conservation",
            "Integrated pest and disease management",
            "Farm mechanization and tool development",
            "Agro-meteorology and weather-based agro-advisories"
        ],
        infrastructure_facilities=[
            "Administrative building", "Laboratories (Agronomy, Entomology, Pathology, Soil Science)",
            "Agromet Observatory", "Seed processing plant", "Polyhouse and net houses", "Farmers training hall"
        ],
        source_url=URL_NTZ,
        source_last_updated=SOURCE_LAST_UPDATED,
        retrieved_at=RETRIEVED_AT,
        contacts=[
            PJTAUStationContact(
                contact_id="pjtau_con_polasa_incharge_selected",
                station_id="pjtau_stn_polasa_jagtial",
                contact_name="Associate Director of Research",
                designation="Associate Director of Research (ADR)",
                role=ContactRole.STATION_HEAD_INCHARGE,
                phone_number="8332970384",
                official_email=None,
                source_reference="PJTAU Northern Telangana Zone Page",
                contact_status=ContactStatus.OWNER_SELECTED,
                is_active_referral=True,
                notes="Owner-selected PJTAU station-page contact for active referral."
            ),
            PJTAUStationContact(
                contact_id="pjtau_con_polasa_adr",
                station_id="pjtau_stn_polasa_jagtial",
                contact_name="Associate Director of Research",
                designation="Associate Director of Research (ADR)",
                role=ContactRole.STATION_HEAD_INCHARGE,
                phone_number="9989625211",
                official_email=None,
                source_reference="PJTAU Northern Telangana Zone Page",
                contact_status=ContactStatus.VERIFIED,
                is_active_referral=False,
                notes="Retained alternate mobile contact."
            ),
            PJTAUStationContact(
                contact_id="pjtau_con_polasa_office",
                station_id="pjtau_stn_polasa_jagtial",
                contact_name="Office of ADR, RARS Polasa",
                designation="Office Landline",
                role=ContactRole.GENERAL_OFFICE,
                phone_number="08724-277281",
                official_email=None,
                source_reference="PJTAU Northern Telangana Zone Page",
                contact_status=ContactStatus.VERIFIED,
                is_active_referral=False,
                notes="Retained general office landline."
            )
        ],
        research_outputs=[
            PJTAUResearchOutput(
                output_id="pjtau_out_polasa_rice_jgl1798",
                station_id="pjtau_stn_polasa_jagtial",
                output_type=ResearchOutputType.VARIETY_RELEASED,
                crop_name="Rice",
                variety_or_technology_name="JGL 1798 (Jagruthi)",
                release_year="2003",
                release_status="SVRC",
                description="Short duration rice variety resistant to gall midge biotype 1 and tolerant to blast.",
                original_source_text="Rice variety JGL 1798 (Jagruthi) developed for Northern Telangana."
            ),
            PJTAUResearchOutput(
                output_id="pjtau_out_polasa_rice_telangana_sona",
                station_id="pjtau_stn_polasa_jagtial",
                output_type=ResearchOutputType.VARIETY_RELEASED,
                crop_name="Rice",
                variety_or_technology_name="JGL 24423 (Telangana Sona)",
                release_year="2015",
                release_status="CVRC",
                description="Super fine grain rice variety with low glycemic index (GI 51.5) and blast tolerance.",
                original_source_text="Rice variety JGL 24423 (Telangana Sona) - Low GI super fine grain variety."
            ),
            PJTAUResearchOutput(
                output_id="pjtau_out_polasa_sesamum_jcs1020",
                station_id="pjtau_stn_polasa_jagtial",
                output_type=ResearchOutputType.VARIETY_RELEASED,
                crop_name="Sesamum",
                variety_or_technology_name="JCS 1020",
                release_year="2016",
                release_status="CVRC",
                description="White seeded high yielding sesamum variety suitable for both Kharif and Summer seasons.",
                original_source_text="Sesamum variety JCS 1020 released by CVRC."
            ),
            PJTAUResearchOutput(
                output_id="pjtau_out_polasa_tech_drum_seeder",
                station_id="pjtau_stn_polasa_jagtial",
                output_type=ResearchOutputType.TECHNOLOGY_DEVELOPED,
                crop_name="Rice",
                variety_or_technology_name="Direct Seeded Rice Drum Seeder Technology",
                release_year="2010",
                release_status="Approved Technology",
                description="Resource conserving 8-row drum seeder for direct wet seeding of sprouted paddy in puddled soils.",
                original_source_text="Direct wet seeded rice drum seeder technology for labour saving."
            )
        ],
        projects_and_outreach=[
            PJTAUProjectOutreach(
                item_id="pjtau_proj_polasa_aicrp_rice",
                station_id="pjtau_stn_polasa_jagtial",
                item_type=ProjectOutreachType.RESEARCH_PROJECT,
                title="All India Coordinated Research Project on Rice",
                funding_agency="ICAR / PJTAU",
                start_date="1990",
                end_date=None,
                is_till_date=True,
                published_duration_text="1990 to Till date",
                description="Coordinated varietal evaluation, breeding, and pathology trials for rice."
            ),
            PJTAUProjectOutreach(
                item_id="pjtau_outr_polasa_daattc",
                station_id="pjtau_stn_polasa_jagtial",
                item_type=ProjectOutreachType.OUTREACH_PROGRAMME,
                title="DAATTC Jagtial Farmer Advisory and Diagnostic Field Services",
                funding_agency="PJTAU",
                start_date="1999",
                end_date=None,
                is_till_date=True,
                published_duration_text="Continuous",
                description="District agricultural advisory, transfer of technology, and farmer diagnostic field visits."
            )
        ]
    )
    stations.append(stn_polasa)

    # 2. RSRRS, Rudrur
    stn_rudrur = PJTAUResearchStation(
        station_id="pjtau_stn_rsrrs_rudrur",
        canonical_name="Regional Sugarcane and Rice Research Station, Rudrur",
        alternate_names=["RSRRS, Rudrur", "RSRRS Rudrur", "ARS Rudrur"],
        pjtau_zone=PJTAUZone.NORTHERN_ZONE,
        address="Regional Sugarcane and Rice Research Station, Rudrur - 503 188, Nizamabad District, Telangana",
        village="Rudrur",
        mandal="Kotagiri",
        district="Nizamabad",
        pin_code="503188",
        latitude=18.50,
        longitude=77.87,
        coordinates_original_text="Latitude: 18° 30' N, Longitude: 77° 52' E, Altitude: 375 m MSL",
        met_observatory_details=None,
        established_year="1931",
        total_area_acres=148.5,  # 60.1 ha
        mandated_crops=["Sugarcane", "Rice", "Soybean"],
        research_focus="Sugarcane varietal improvement, ratoon management, water conservation, and rice breeding for gall midge and salinity resistance in Nizamabad command areas.",
        research_themes=[
            "Sugarcane varietal breeding and seed nursery technologies",
            "Rice breeding for biotic stress (gall midge) and abiotic stress resistance",
            "Soybean varietal evaluation and crop diversification in rice-fallows",
            "Resource conservation technologies and water management"
        ],
        infrastructure_facilities=[
            "Administrative block", "Jaggery processing laboratory", "Soil and plant tissue testing lab",
            "Single bud sett nursery facility", "Farm mechanization shed"
        ],
        source_url=URL_NTZ,
        source_last_updated=SOURCE_LAST_UPDATED,
        retrieved_at=RETRIEVED_AT,
        contacts=[
            PJTAUStationContact(
                contact_id="pjtau_con_rudrur_incharge_selected",
                station_id="pjtau_stn_rsrrs_rudrur",
                contact_name="Principal Scientist (Sugarcane) & Head",
                designation="Principal Scientist (Sugarcane) & Head",
                role=ContactRole.STATION_HEAD_INCHARGE,
                phone_number="8333818205",
                official_email=None,
                source_reference="PJTAU Northern Telangana Zone Page",
                contact_status=ContactStatus.OWNER_SELECTED,
                is_active_referral=True,
                notes="Owner-selected PJTAU station-page contact for active referral."
            ),
            PJTAUStationContact(
                contact_id="pjtau_con_rudrur_head",
                station_id="pjtau_stn_rsrrs_rudrur",
                contact_name="Head / Principal Scientist",
                designation="Principal Scientist (Sugarcane) & Head",
                role=ContactRole.STATION_HEAD_INCHARGE,
                phone_number="08467-284227",
                official_email=None,
                source_reference="PJTAU Northern Telangana Zone Page",
                contact_status=ContactStatus.VERIFIED,
                is_active_referral=False,
                notes="Retained official station landline."
            ),
            PJTAUStationContact(
                contact_id="pjtau_con_rudrur_mobile",
                station_id="pjtau_stn_rsrrs_rudrur",
                contact_name="Station In-Charge Mobile",
                designation="Head of Station Mobile",
                role=ContactRole.STATION_HEAD_INCHARGE,
                phone_number="9440407736",
                official_email=None,
                source_reference="PJTAU Northern Telangana Zone Page",
                contact_status=ContactStatus.VERIFIED,
                is_active_referral=False,
                notes="Retained alternate station mobile contact."
            )
        ],
        research_outputs=[
            PJTAUResearchOutput(
                output_id="pjtau_out_rudrur_cane_cor8001",
                station_id="pjtau_stn_rsrrs_rudrur",
                output_type=ResearchOutputType.VARIETY_RELEASED,
                crop_name="Sugarcane",
                variety_or_technology_name="CoR 8001",
                release_year="1980",
                release_status="SVRC",
                description="High sugar and cane yielding early maturing sugarcane variety suited for Nizamabad region.",
                original_source_text="Sugarcane variety CoR 8001 released by RSRRS Rudrur."
            ),
            PJTAUResearchOutput(
                output_id="pjtau_out_rudrur_rice_rdr1010",
                station_id="pjtau_stn_rsrrs_rudrur",
                output_type=ResearchOutputType.VARIETY_RELEASED,
                crop_name="Rice",
                variety_or_technology_name="RDR 1010",
                release_year="2004",
                release_status="SVRC",
                description="Short duration (120 days) medium slender grain rice variety widely adopted in Telangana.",
                original_source_text="Rice variety RDR 1010 released for cultivation in Telangana."
            ),
            PJTAUResearchOutput(
                output_id="pjtau_out_rudrur_tech_budchip",
                station_id="pjtau_stn_rsrrs_rudrur",
                output_type=ResearchOutputType.TECHNOLOGY_DEVELOPED,
                crop_name="Sugarcane",
                variety_or_technology_name="Single Cane Budchip Sett Nursery Technique",
                release_year="2012",
                release_status="Approved Technology",
                description="Reduces sugarcane seed requirement by 80% using single budchips raised in protrays with coco-peat.",
                original_source_text="Single cane budchip settling technology for sugarcane cultivation."
            )
        ],
        projects_and_outreach=[
            PJTAUProjectOutreach(
                item_id="pjtau_proj_rudrur_aicrp_sugarcane",
                station_id="pjtau_stn_rsrrs_rudrur",
                item_type=ProjectOutreachType.RESEARCH_PROJECT,
                title="All India Coordinated Research Project on Sugarcane",
                funding_agency="ICAR / PJTAU",
                start_date="1971",
                end_date=None,
                is_till_date=True,
                published_duration_text="1971 to Till date",
                description="Sugarcane breeding, agronomy, pathology, and entomology multilocational trials."
            ),
            PJTAUProjectOutreach(
                item_id="pjtau_outr_rudrur_fld_budchip",
                station_id="pjtau_stn_rsrrs_rudrur",
                item_type=ProjectOutreachType.OUTREACH_PROGRAMME,
                title="Frontline Demonstrations on Sugarcane Budchip and Drip Fertigation",
                funding_agency="State Dept of Agriculture / PJTAU",
                start_date="2015",
                end_date=None,
                is_till_date=True,
                published_duration_text="Continuous",
                description="Field demonstrations and training on budchip nurseries and water saving techniques."
            )
        ]
    )
    stations.append(stn_rudrur)

    # 3. ARS, Adilabad
    stn_adilabad = PJTAUResearchStation(
        station_id="pjtau_stn_ars_adilabad",
        canonical_name="Agricultural Research Station, Adilabad",
        alternate_names=["ARS, Adilabad", "ARS Adilabad"],
        pjtau_zone=PJTAUZone.NORTHERN_ZONE,
        address="Agricultural Research Station, Adilabad - 504 002, Telangana",
        village="Adilabad",
        mandal="Adilabad Urban",
        district="Adilabad",
        pin_code="504002",
        latitude=19.65,
        longitude=78.53,
        coordinates_original_text="Latitude: 19° 39' N, Longitude: 78° 32' E, Altitude: 268.9 m MSL",
        met_observatory_details="Meteorological Observatory (class B-type) & Automatic weather station, Latitude :19’39’N, Longitude: 78’32’ E, Altitude: 268.9m MSL",
        established_year="1959",
        total_area_acres=70.42,  # 28.5 ha
        mandated_crops=["Cotton", "Soybean", "Chickpea"],
        research_focus="High Density Planting System (HDPS) in cotton, desi and American cotton breeding, and rainfed soybean-chickpea cropping systems for heavy black soils of Adilabad.",
        research_themes=[
            "Cotton breeding for high density planting and mechanical picking",
            "Soybean varietal improvement and integrated pest management (girdle beetle, spodoptera)",
            "Chickpea breeding and mechanical harvesting suitability",
            "Agro-meteorological observations and weather forecasts"
        ],
        infrastructure_facilities=[
            "Administrative block", "Cotton fiber testing laboratory", "Automatic Weather Station",
            "Class B Meteorological Observatory", "Seed storage godown"
        ],
        source_url=URL_NTZ,
        source_last_updated=SOURCE_LAST_UPDATED,
        retrieved_at=RETRIEVED_AT,
        contacts=[
            PJTAUStationContact(
                contact_id="pjtau_con_adilabad_incharge_selected",
                station_id="pjtau_stn_ars_adilabad",
                contact_name="Principal Scientist (Cotton) & Head",
                designation="Principal Scientist (Cotton) & Head",
                role=ContactRole.STATION_HEAD_INCHARGE,
                phone_number="8333818203",
                official_email=None,
                source_reference="PJTAU Northern Telangana Zone Page",
                contact_status=ContactStatus.OWNER_SELECTED,
                is_active_referral=True,
                notes="Owner-selected PJTAU station-page contact for active referral."
            ),
            PJTAUStationContact(
                contact_id="pjtau_con_adilabad_head",
                station_id="pjtau_stn_ars_adilabad",
                contact_name="Head / Principal Scientist",
                designation="Principal Scientist (Cotton) & Head",
                role=ContactRole.STATION_HEAD_INCHARGE,
                phone_number="08732-234202",
                official_email=None,
                source_reference="PJTAU Northern Telangana Zone Page",
                contact_status=ContactStatus.VERIFIED,
                is_active_referral=False,
                notes="Retained official station landline."
            ),
            PJTAUStationContact(
                contact_id="pjtau_con_adilabad_mobile",
                station_id="pjtau_stn_ars_adilabad",
                contact_name="Station Head Mobile",
                designation="Principal Scientist Mobile",
                role=ContactRole.STATION_HEAD_INCHARGE,
                phone_number="9493186259",
                official_email=None,
                source_reference="PJTAU Northern Telangana Zone Page",
                contact_status=ContactStatus.VERIFIED,
                is_active_referral=False,
                notes="Retained alternate mobile phone number."
            )
        ],
        research_outputs=[
            PJTAUResearchOutput(
                output_id="pjtau_out_adilabad_cotton_adb542",
                station_id="pjtau_stn_ars_adilabad",
                output_type=ResearchOutputType.VARIETY_RELEASED,
                crop_name="Cotton",
                variety_or_technology_name="ADB 542",
                release_year="2018",
                release_status="SVRC",
                description="High yielding compact American cotton variety bred specifically for High Density Planting System (HDPS).",
                original_source_text="Cotton variety ADB 542 developed for HDPS cultivation."
            ),
            PJTAUResearchOutput(
                output_id="pjtau_out_adilabad_cotton_basara",
                station_id="pjtau_stn_ars_adilabad",
                output_type=ResearchOutputType.VARIETY_RELEASED,
                crop_name="Cotton",
                variety_or_technology_name="Basara (ADB 39)",
                release_year="2012",
                release_status="SVRC",
                description="Medium staple cotton variety tolerant to sucking pests and suited for rainfed black soils.",
                original_source_text="Cotton variety Basara (ADB 39) released for Telangana rainfed black soils."
            ),
            PJTAUResearchOutput(
                output_id="pjtau_out_adilabad_tech_hdps_cotton",
                station_id="pjtau_stn_ars_adilabad",
                output_type=ResearchOutputType.TECHNOLOGY_DEVELOPED,
                crop_name="Cotton",
                variety_or_technology_name="HDPS Cotton Spacing (90x10 cm or 80x10 cm) with Mepiquat Chloride",
                release_year="2016",
                release_status="Approved Technology",
                description="High density planting package with 25,000 plants/acre and growth regulator sprays to synchronize boll bursting.",
                original_source_text="HDPS cotton package developed by ARS Adilabad."
            )
        ],
        projects_and_outreach=[
            PJTAUProjectOutreach(
                item_id="pjtau_proj_adilabad_aicrp_cotton",
                station_id="pjtau_stn_ars_adilabad",
                item_type=ProjectOutreachType.RESEARCH_PROJECT,
                title="All India Coordinated Research Project on Cotton",
                funding_agency="ICAR / PJTAU",
                start_date="1967",
                end_date=None,
                is_till_date=True,
                published_duration_text="1967 to Till date",
                description="National evaluation trials for cotton breeding, agronomy, and sucking pest management."
            ),
            PJTAUProjectOutreach(
                item_id="pjtau_outr_adilabad_tribal_cluster",
                station_id="pjtau_stn_ars_adilabad",
                item_type=ProjectOutreachType.OUTREACH_PROGRAMME,
                title="Tribal Village Cluster Farm Advisory and Input Demonstrations",
                funding_agency="TSP / ICAR",
                start_date="2014",
                end_date=None,
                is_till_date=True,
                published_duration_text="Continuous",
                description="Frontline demonstrations of improved seed varieties, farm implements, and soil testing for tribal farmers."
            )
        ]
    )
    stations.append(stn_adilabad)

    # 4. ARS, Karimnagar
    stn_karimnagar = PJTAUResearchStation(
        station_id="pjtau_stn_ars_karimnagar",
        canonical_name="Agricultural Research Station, Karimnagar",
        alternate_names=["ARS, Karimnagar", "ARS Karimnagar"],
        pjtau_zone=PJTAUZone.NORTHERN_ZONE,
        address="Agricultural Research Station, Karimnagar - 505 001, Telangana",
        village="Karimnagar",
        mandal="Karimnagar",
        district="Karimnagar",
        pin_code="505001",
        latitude=18.43,
        longitude=79.13,
        coordinates_original_text="Latitude: 18° 26' N, Longitude: 79° 08' E, Altitude: 265 m MSL",
        met_observatory_details=None,
        established_year="1972",
        total_area_acres=51.4,  # 20.8 ha
        mandated_crops=["Maize"],
        research_focus="Breeding single cross maize hybrids, specialty corn (sweet corn, pop corn), and integrated management of Fall Armyworm (FAW) and turcicum leaf blight.",
        research_themes=[
            "Single cross hybrid development in maize",
            "Specialty corn breeding (Sweet corn, Quality Protein Maize - QPM)",
            "Integrated Pest Management for Fall Armyworm (Spodoptera frugiperda)",
            "Nutrient and moisture conservation in maize-based cropping systems"
        ],
        infrastructure_facilities=[
            "Administrative building", "Maize breeding laboratory", "Seed drying and processing floor",
            "Pheromone trap monitoring unit"
        ],
        source_url=URL_NTZ,
        source_last_updated=SOURCE_LAST_UPDATED,
        retrieved_at=RETRIEVED_AT,
        contacts=[
            PJTAUStationContact(
                contact_id="pjtau_con_karimnagar_incharge_selected",
                station_id="pjtau_stn_ars_karimnagar",
                contact_name="Principal Scientist (Maize) & Head",
                designation="Principal Scientist (Maize) & Head",
                role=ContactRole.STATION_HEAD_INCHARGE,
                phone_number="8333818201",
                official_email=None,
                source_reference="PJTAU Northern Telangana Zone Page",
                contact_status=ContactStatus.OWNER_SELECTED,
                is_active_referral=True,
                notes="Owner-selected PJTAU station-page contact for active referral."
            ),
            PJTAUStationContact(
                contact_id="pjtau_con_karimnagar_head",
                station_id="pjtau_stn_ars_karimnagar",
                contact_name="Head / Principal Scientist (Maize)",
                designation="Principal Scientist (Maize) & Head",
                role=ContactRole.STATION_HEAD_INCHARGE,
                phone_number="0878-2278486",
                official_email=None,
                source_reference="PJTAU Northern Telangana Zone Page",
                contact_status=ContactStatus.VERIFIED,
                is_active_referral=False,
                notes="Retained official station landline."
            ),
            PJTAUStationContact(
                contact_id="pjtau_con_karimnagar_mobile",
                station_id="pjtau_stn_ars_karimnagar",
                contact_name="Station Head Mobile",
                designation="Principal Scientist Mobile",
                role=ContactRole.STATION_HEAD_INCHARGE,
                phone_number="9440939525",
                official_email=None,
                source_reference="PJTAU Northern Telangana Zone Page",
                contact_status=ContactStatus.VERIFIED,
                is_active_referral=False,
                notes="Retained alternate mobile phone number."
            )
        ],
        research_outputs=[
            PJTAUResearchOutput(
                output_id="pjtau_out_karimnagar_maize_kmh40101",
                station_id="pjtau_stn_ars_karimnagar",
                output_type=ResearchOutputType.VARIETY_RELEASED,
                crop_name="Maize",
                variety_or_technology_name="Karimnagar Makka 1 (KNMH 40101)",
                release_year="2014",
                release_status="SVRC",
                description="High yielding yellow single cross maize hybrid with resistance to turcicum leaf blight.",
                original_source_text="Maize hybrid Karimnagar Makka 1 (KNMH 40101) released by ARS Karimnagar."
            ),
            PJTAUResearchOutput(
                output_id="pjtau_out_karimnagar_tech_faw_ipm",
                station_id="pjtau_stn_ars_karimnagar",
                output_type=ResearchOutputType.TECHNOLOGY_DEVELOPED,
                crop_name="Maize",
                variety_or_technology_name="Integrated Fall Armyworm (FAW) Management Strategy",
                release_year="2019",
                release_status="Approved Technology",
                description="Pheromone trap monitoring, whorl application of sand-lime/neem seed kernel extract, and biocontrol using Trichogramma pretiosum.",
                original_source_text="FAW IPM package developed by ARS Karimnagar."
            )
        ],
        projects_and_outreach=[
            PJTAUProjectOutreach(
                item_id="pjtau_proj_karimnagar_aicrp_maize",
                station_id="pjtau_stn_ars_karimnagar",
                item_type=ProjectOutreachType.RESEARCH_PROJECT,
                title="All India Coordinated Research Project on Maize",
                funding_agency="ICAR / PJTAU",
                start_date="1972",
                end_date=None,
                is_till_date=True,
                published_duration_text="1972 to Till date",
                description="National coordinated trials on single cross hybrids, sweet corn, and FAW biocontrol."
            ),
            PJTAUProjectOutreach(
                item_id="pjtau_outr_karimnagar_seed_production",
                station_id="pjtau_stn_ars_karimnagar",
                item_type=ProjectOutreachType.OUTREACH_PROGRAMME,
                title="Maize Hybrid Foundation Seed Production and Farmer Training",
                funding_agency="PJTAU",
                start_date="2010",
                end_date=None,
                is_till_date=True,
                published_duration_text="Continuous",
                description="Production of parental line seeds and training farmers on maize hybrid seed production."
            )
        ]
    )
    stations.append(stn_karimnagar)

    # 5. ARS, Mudhole
    stn_mudhole = PJTAUResearchStation(
        station_id="pjtau_stn_ars_mudhole",
        canonical_name="ARS Mudhole",
        alternate_names=["Agricultural Research Station, Mudhole", "Mudhol", "ARS Mudhol"],
        pjtau_zone=PJTAUZone.NORTHERN_ZONE,
        address="Agricultural Research Station, Mudhole - 504 102, Nirmal District, Telangana",
        village="Mudhole",
        mandal="Mudhole",
        district="Nirmal",
        pin_code="504102",
        latitude=18.98,
        longitude=77.92,
        coordinates_original_text="Latitude: 18° 59' N, Longitude: 77° 55' E, Altitude: 345 m MSL",
        met_observatory_details=None,
        established_year="1951",
        total_area_acres=60.0,  # 24.28 ha
        mandated_crops=["Desi Cotton", "Redgram", "Soybean", "Chickpea", "Sesamum"],
        research_focus="Conservation and genetic improvement of Desi Cotton (Gossypium arboreum) for rainfed situations, drought tolerance, and pulse-oilseed intercropping.",
        research_themes=[
            "Breeding high-yielding Desi Cotton varieties with superior spinning quality",
            "Rainfed cropping systems in deep black soils",
            "Screening desi cotton germplasm for sucking pest and pink bollworm resistance",
            "Intercropping desi cotton with redgram and soybean"
        ],
        infrastructure_facilities=[
            "Administrative office", "Desi cotton germplasm repository", "Farm threshing floor",
            "Seed godown"
        ],
        source_url=URL_NTZ,
        source_last_updated=SOURCE_LAST_UPDATED,
        retrieved_at=RETRIEVED_AT,
        contacts=[
            # Active referral contact selected from official PJTAU station page
            PJTAUStationContact(
                contact_id="pjtau_con_mudhole_incharge_selected",
                station_id="pjtau_stn_ars_mudhole",
                contact_name="Sri A. Dinesh",
                designation="Scientist, ARS Mudhole",
                role=ContactRole.STATION_HEAD_INCHARGE,
                phone_number="8332970250",
                official_email=None,
                source_reference="PJTAU Northern Telangana Zone Page",
                contact_status=ContactStatus.OWNER_SELECTED,
                is_active_referral=True,
                notes="Owner-selected PJTAU station-page contact for active referral. Source conflict with RTI directory remains unresolved; independent second-source verification is pending."
            ),
            # Retained historical candidate 1 from RTI directory
            PJTAUStationContact(
                contact_id="pjtau_con_mudhole_ars_incharge",
                station_id="pjtau_stn_ars_mudhole",
                contact_name="Sri A. Dinesh / Station Head",
                designation="Scientist & Head (In-charge)",
                role=ContactRole.STATION_HEAD_INCHARGE,
                phone_number="8333818204",
                official_email=None,
                source_reference="PJTAU RTI Directory",
                contact_status=ContactStatus.NEEDS_CONFIRMATION,
                is_active_referral=False,
                notes="Historical RTI directory listing (8333818204) preserved."
            ),
            # Retained historical candidate 2: TRVK Coordinator
            PJTAUStationContact(
                contact_id="pjtau_con_mudhole_trvk_coord",
                station_id="pjtau_stn_ars_mudhole",
                contact_name="TRVK Coordinator, Mudhole",
                designation="Coordinator, TRVK",
                role=ContactRole.TRVK_COORDINATOR,
                phone_number="8332970250",
                official_email=None,
                source_reference="PJTAU RTI Directory",
                contact_status=ContactStatus.INDEPENDENTLY_VERIFIED,
                is_active_referral=False,
                notes="Independently verified TRVK coordinator contact from PJTAU RTI directory."
            )
        ],
        research_outputs=[
            PJTAUResearchOutput(
                output_id="pjtau_out_mudhole_cotton_gaorani6",
                station_id="pjtau_stn_ars_mudhole",
                output_type=ResearchOutputType.VARIETY_RELEASED,
                crop_name="Desi Cotton",
                variety_or_technology_name="Gaorani-6",
                release_year="1958",
                release_status="SVRC",
                description="Historic landmark desi cotton variety (Gossypium arboreum) known for high spinning counts (30s) and drought resilience.",
                original_source_text="Desi cotton variety Gaorani-6 preserved and improved at ARS Mudhole."
            ),
            PJTAUResearchOutput(
                output_id="pjtau_out_mudhole_cotton_saraswathi",
                station_id="pjtau_stn_ars_mudhole",
                output_type=ResearchOutputType.VARIETY_RELEASED,
                crop_name="Desi Cotton",
                variety_or_technology_name="Saraswathi (MDL 261)",
                release_year="1983",
                release_status="SVRC",
                description="High ginning outturn desi cotton variety suited for dryland farming in Nirmal and Adilabad.",
                original_source_text="Desi cotton variety Saraswathi (MDL 261) developed at ARS Mudhole."
            ),
            PJTAUResearchOutput(
                output_id="pjtau_out_mudhole_cotton_veena",
                station_id="pjtau_stn_ars_mudhole",
                output_type=ResearchOutputType.VARIETY_RELEASED,
                crop_name="Desi Cotton",
                variety_or_technology_name="Veena (MDL 1875)",
                release_year="2001",
                release_status="SVRC",
                description="Desi cotton variety resistant to sucking pests and tolerant to moisture stress.",
                original_source_text="Desi cotton culture MDL 1875 (Veena) released by SVRC."
            )
        ],
        projects_and_outreach=[
            PJTAUProjectOutreach(
                item_id="pjtau_proj_mudhole_aicrp_cotton",
                station_id="pjtau_stn_ars_mudhole",
                item_type=ProjectOutreachType.RESEARCH_PROJECT,
                title="All India Coordinated Research Project on Cotton (Voluntary Centre)",
                funding_agency="ICAR / PJTAU",
                start_date="1980",
                end_date=None,
                is_till_date=True,
                published_duration_text="1980 to Till date",
                description="Germplasm maintenance and multilocational evaluation of arboreum cotton."
            ),
            PJTAUProjectOutreach(
                item_id="pjtau_outr_mudhole_fld_desi_cotton",
                station_id="pjtau_stn_ars_mudhole",
                item_type=ProjectOutreachType.OUTREACH_PROGRAMME,
                title="Frontline Demonstrations on Desi Cotton and Intercropping",
                funding_agency="NFSM / PJTAU",
                start_date="2012",
                end_date=None,
                is_till_date=True,
                published_duration_text="Continuous",
                description="Demonstrating low-input organic desi cotton cultivation with redgram intercropping."
            )
        ]
    )
    stations.append(stn_mudhole)

    # 6. ARS, Kunaram
    stn_kunaram = PJTAUResearchStation(
        station_id="pjtau_stn_ars_kunaram",
        canonical_name="Agricultural Research Station, Kunaram",
        alternate_names=["ARS, Kunaram", "ARS Kunaram"],
        pjtau_zone=PJTAUZone.NORTHERN_ZONE,
        address="Agricultural Research Station, Kunaram, Peddapalli District - 505 172, Telangana",
        village="Kunaram",
        mandal="Anthergaon",
        district="Peddapalli",
        pin_code="505172",
        latitude=18.70,
        longitude=79.52,
        coordinates_original_text="Latitude: 18° 42' N, Longitude: 79° 31' E, Altitude: 169 m MSL",
        met_observatory_details=None,
        established_year="1985",
        total_area_acres=52.0,  # 21.04 ha
        mandated_crops=["Paddy"],
        research_focus="Breeding medium slender and short bold grain rice varieties suitable for Northern Telangana, resistance to gall midge (biotype 3) and blast, and direct seeded rice technologies.",
        research_themes=[
            "Rice varietal improvement for Northern Telangana conditions",
            "Screening rice genotypes for gall midge biotype 3 and blast tolerance",
            "Direct Wet Seeded Rice (drum seeder) and weed management protocols",
            "Soil fertility management in Godavari command area"
        ],
        infrastructure_facilities=[
            "Administrative block", "Rice breeding and seed testing lab", "Threshing and drying yard",
            "Seed warehouse"
        ],
        source_url=URL_NTZ,
        source_last_updated=SOURCE_LAST_UPDATED,
        retrieved_at=RETRIEVED_AT,
        contacts=[
            PJTAUStationContact(
                contact_id="pjtau_con_kunaram_incharge_selected",
                station_id="pjtau_stn_ars_kunaram",
                contact_name="Principal Scientist (Rice) & Head",
                designation="Principal Scientist (Rice) & Head",
                role=ContactRole.STATION_HEAD_INCHARGE,
                phone_number="8333818202",
                official_email=None,
                source_reference="PJTAU Northern Telangana Zone Page",
                contact_status=ContactStatus.OWNER_SELECTED,
                is_active_referral=True,
                notes="Owner-selected PJTAU station-page contact for active referral."
            ),
            PJTAUStationContact(
                contact_id="pjtau_con_kunaram_head",
                station_id="pjtau_stn_ars_kunaram",
                contact_name="Principal Scientist (Rice) & Head",
                designation="Principal Scientist (Rice) & Head",
                role=ContactRole.STATION_HEAD_INCHARGE,
                phone_number="08728-256244",
                official_email=None,
                source_reference="PJTAU Northern Telangana Zone Page",
                contact_status=ContactStatus.VERIFIED,
                is_active_referral=False,
                notes="Retained official station landline."
            ),
            PJTAUStationContact(
                contact_id="pjtau_con_kunaram_mobile",
                station_id="pjtau_stn_ars_kunaram",
                contact_name="Station Head Mobile",
                designation="Principal Scientist Mobile",
                role=ContactRole.STATION_HEAD_INCHARGE,
                phone_number="9440124611",
                official_email=None,
                source_reference="PJTAU Northern Telangana Zone Page",
                contact_status=ContactStatus.VERIFIED,
                is_active_referral=False,
                notes="Retained alternate mobile phone number."
            )
        ],
        research_outputs=[
            PJTAUResearchOutput(
                output_id="pjtau_out_kunaram_rice_knm118",
                station_id="pjtau_stn_ars_kunaram",
                output_type=ResearchOutputType.VARIETY_RELEASED,
                crop_name="Rice",
                variety_or_technology_name="Kunaram 118 (KNM 118)",
                release_year="2013",
                release_status="SVRC",
                description="Short duration (120 days) medium slender grain rice variety widely grown across Telangana for both Kharif and Rabi.",
                original_source_text="Rice variety Kunaram 118 (KNM 118) released for cultivation in Telangana."
            ),
            PJTAUResearchOutput(
                output_id="pjtau_out_kunaram_rice_knm1638",
                station_id="pjtau_stn_ars_kunaram",
                output_type=ResearchOutputType.VARIETY_RELEASED,
                crop_name="Rice",
                variety_or_technology_name="Kunaram Sannalu (KNM 1638)",
                release_year="2019",
                release_status="CVRC",
                description="Fine grain rice variety with high head rice recovery and tolerance to neck blast.",
                original_source_text="Rice variety Kunaram Sannalu (KNM 1638) notified by CVRC."
            ),
            PJTAUResearchOutput(
                output_id="pjtau_out_kunaram_tech_drum_seeding",
                station_id="pjtau_stn_ars_kunaram",
                output_type=ResearchOutputType.TECHNOLOGY_DEVELOPED,
                crop_name="Rice",
                variety_or_technology_name="Puddled Direct Seeded Rice with Pre-emergence Herbicide Protocol",
                release_year="2015",
                release_status="Approved Technology",
                description="Drum seeding protocol saving 25-30% irrigation water and reducing nursery raising labour costs.",
                original_source_text="Direct seeded drum seeder package developed by ARS Kunaram."
            )
        ],
        projects_and_outreach=[
            PJTAUProjectOutreach(
                item_id="pjtau_proj_kunaram_state_plan_rice",
                station_id="pjtau_stn_ars_kunaram",
                item_type=ProjectOutreachType.RESEARCH_PROJECT,
                title="State Plan Scheme on Rice Research for Northern Telangana",
                funding_agency="Govt of Telangana / PJTAU",
                start_date="1985",
                end_date=None,
                is_till_date=True,
                published_duration_text="1985 to Till date",
                description="Continuous varietal breeding, germplasm screening, and agronomy research in paddy."
            ),
            PJTAUProjectOutreach(
                item_id="pjtau_outr_kunaram_fld_knm_varieties",
                station_id="pjtau_stn_ars_kunaram",
                item_type=ProjectOutreachType.OUTREACH_PROGRAMME,
                title="Frontline Demonstrations and Seed Multiplication of KNM Rice Varieties",
                funding_agency="PJTAU Revolving Fund",
                start_date="2014",
                end_date=None,
                is_till_date=True,
                published_duration_text="Continuous",
                description="Breeder and foundation seed production of KNM 118 and KNM 1638 for Telangana farmers."
            )
        ]
    )
    stations.append(stn_kunaram)

    return stations


def _get_ctz_stations() -> List[PJTAUResearchStation]:
    """Central Telangana Zone - 5 Research Stations."""
    stations: List[PJTAUResearchStation] = []

    # 7. RARS, Warangal
    stn_warangal = PJTAUResearchStation(
        station_id="pjtau_stn_rars_warangal",
        canonical_name="Regional Agricultural Research Station, Warangal",
        alternate_names=["RARS, Warangal", "RARS Warangal"],
        pjtau_zone=PJTAUZone.CENTRAL_ZONE,
        address="Regional Agricultural Research Station, Mulugu Road, Warangal - 506 007, Telangana",
        village="Warangal",
        mandal="Warangal",
        district="Warangal",
        pin_code="506007",
        latitude=17.98,
        longitude=79.60,
        coordinates_original_text="Latitude: 17° 59' N, Longitude: 79° 36' E, Altitude: 270 m MSL",
        met_observatory_details=None,
        established_year="1932",
        total_area_acres=336.55,  # 136.2 ha
        mandated_crops=["Rice", "Cotton", "Pulses", "Maize"],
        research_focus="Headquarters of Central Telangana Zone; breeding rice for gall midge and blast resistance, cotton improvement for HDPS, and pulse breeding for wilt resistance.",
        research_themes=[
            "Rice varietal improvement (super fine varieties, gall midge biotype resistance)",
            "Cotton breeding for high density planting and pink bollworm IPM",
            "Pulses improvement (Redgram, Greengram, Blackgram wilt and virus resistance)",
            "Natural farming, organic farming protocols, and resource conservation",
            "Agro-meteorology and medium range weather forecasting"
        ],
        infrastructure_facilities=[
            "Administrative complex", "Biotechnology & Plant Pathology labs", "Soil testing lab",
            "Automatic Weather Station", "Breeder seed processing unit", "Training auditorium"
        ],
        source_url=URL_CTZ,
        source_last_updated=SOURCE_LAST_UPDATED,
        retrieved_at=RETRIEVED_AT,
        contacts=[
            PJTAUStationContact(
                contact_id="pjtau_con_warangal_incharge_selected",
                station_id="pjtau_stn_rars_warangal",
                contact_name="Associate Director of Research",
                designation="Associate Director of Research (ADR)",
                role=ContactRole.STATION_HEAD_INCHARGE,
                phone_number="8332970385",
                official_email="adrwgl@pjtau.edu.in",
                source_reference="PJTAU Central Telangana Zone Page",
                contact_status=ContactStatus.OWNER_SELECTED,
                is_active_referral=True,
                notes="Owner-selected PJTAU station-page contact for active referral."
            ),
            PJTAUStationContact(
                contact_id="pjtau_con_warangal_adr",
                station_id="pjtau_stn_rars_warangal",
                contact_name="Associate Director of Research",
                designation="Associate Director of Research (ADR)",
                role=ContactRole.STATION_HEAD_INCHARGE,
                phone_number="0870-2521464",
                official_email="adrwgl@pjtau.edu.in",
                source_reference="PJTAU Central Telangana Zone Page",
                contact_status=ContactStatus.VERIFIED,
                is_active_referral=False,
                notes="Retained official station landline and PJTAU domain email."
            ),
            PJTAUStationContact(
                contact_id="pjtau_con_warangal_adr_mobile",
                station_id="pjtau_stn_rars_warangal",
                contact_name="ADR Mobile Contact",
                designation="Associate Director of Research Mobile",
                role=ContactRole.STATION_HEAD_INCHARGE,
                phone_number="9989625212",
                official_email="adrwgl@pjtau.edu.in",
                source_reference="PJTAU Central Telangana Zone Page",
                contact_status=ContactStatus.VERIFIED,
                is_active_referral=False,
                notes="Retained alternate mobile number."
            )
        ],
        research_outputs=[
            PJTAUResearchOutput(
                output_id="pjtau_out_warangal_rice_wgl14",
                station_id="pjtau_stn_rars_warangal",
                output_type=ResearchOutputType.VARIETY_RELEASED,
                crop_name="Rice",
                variety_or_technology_name="Warangal Sannalu (WGL 14)",
                release_year="1994",
                release_status="SVRC",
                description="Fine grain rice variety with resistance to gall midge biotype 1 and tolerance to blast.",
                original_source_text="Rice variety Warangal Sannalu (WGL 14) released by RARS Warangal."
            ),
            PJTAUResearchOutput(
                output_id="pjtau_out_warangal_rice_wgl1119",
                station_id="pjtau_stn_rars_warangal",
                output_type=ResearchOutputType.VARIETY_RELEASED,
                crop_name="Rice",
                variety_or_technology_name="Telangana Rice 1 (WGL 1119)",
                release_year="2020",
                release_status="CVRC",
                description="Medium slender grain rice variety with high head rice recovery and multiple pest tolerance.",
                original_source_text="Rice variety WGL 1119 notified by CVRC."
            ),
            PJTAUResearchOutput(
                output_id="pjtau_out_warangal_pulses_wrg97",
                station_id="pjtau_stn_rars_warangal",
                output_type=ResearchOutputType.VARIETY_RELEASED,
                crop_name="Redgram",
                variety_or_technology_name="WRG 97 (Hanuma)",
                release_year="2016",
                release_status="SVRC",
                description="Medium duration wilt resistant redgram variety with high yield potential in rainfed vertisols.",
                original_source_text="Redgram variety WRG 97 released by SVRC."
            ),
            PJTAUResearchOutput(
                output_id="pjtau_out_warangal_tech_pbw_ipm",
                station_id="pjtau_stn_rars_warangal",
                output_type=ResearchOutputType.TECHNOLOGY_DEVELOPED,
                crop_name="Cotton",
                variety_or_technology_name="Pink Bollworm IPM Module for Cotton",
                release_year="2018",
                release_status="Approved Technology",
                description="Pheromone trap installation at 45 DAS, mass trapping, and need-based botanicals/insecticides.",
                original_source_text="Pink bollworm IPM module developed by RARS Warangal."
            )
        ],
        projects_and_outreach=[
            PJTAUProjectOutreach(
                item_id="pjtau_proj_warangal_aicrp_rice",
                station_id="pjtau_stn_rars_warangal",
                item_type=ProjectOutreachType.RESEARCH_PROJECT,
                title="AICRP on Rice (Warangal Centre)",
                funding_agency="ICAR / PJTAU",
                start_date="1968",
                end_date=None,
                is_till_date=True,
                published_duration_text="1968 to Till date",
                description="Coordinated research on rice breeding, gall midge screening, and agronomy."
            ),
            PJTAUProjectOutreach(
                item_id="pjtau_proj_warangal_aicrp_cotton",
                station_id="pjtau_stn_rars_warangal",
                item_type=ProjectOutreachType.RESEARCH_PROJECT,
                title="AICRP on Cotton (Warangal Centre)",
                funding_agency="ICAR / PJTAU",
                start_date="1970",
                end_date=None,
                is_till_date=True,
                published_duration_text="1970 to Till date",
                description="Cotton breeding for high yield, fiber quality, and HDPS agronomy."
            ),
            PJTAUProjectOutreach(
                item_id="pjtau_proj_warangal_aicrp_pigeonpea",
                station_id="pjtau_stn_rars_warangal",
                item_type=ProjectOutreachType.RESEARCH_PROJECT,
                title="AICRP on Pigeonpea (Warangal Centre)",
                funding_agency="ICAR / PJTAU",
                start_date="1975",
                end_date=None,
                is_till_date=True,
                published_duration_text="1975 to Till date",
                description="Breeding for wilt and sterility mosaic resistance in redgram."
            ),
            PJTAUProjectOutreach(
                item_id="pjtau_proj_warangal_aicrp_mullarp",
                station_id="pjtau_stn_rars_warangal",
                item_type=ProjectOutreachType.RESEARCH_PROJECT,
                title="AICRP on MULLaRP (Mung, Urd, Lentil, Lathyrus, Rajmash, Pea)",
                funding_agency="ICAR / PJTAU",
                start_date="1982",
                end_date=None,
                is_till_date=True,
                published_duration_text="1982 to Till date",
                description="Research on greengram and blackgram varietal development and YMV resistance."
            ),
            PJTAUProjectOutreach(
                item_id="pjtau_outr_warangal_daattc",
                station_id="pjtau_stn_rars_warangal",
                item_type=ProjectOutreachType.OUTREACH_PROGRAMME,
                title="DAATTC Warangal Extension and Farmer Field Advisory",
                funding_agency="PJTAU",
                start_date="1998",
                end_date=None,
                is_till_date=True,
                published_duration_text="Continuous",
                description="District agricultural advisory, diagnostic visits, and weekly agromet advisory dissemination."
            )
        ]
    )
    stations.append(stn_warangal)

    # 8. ARS, Madhira
    stn_madhira = PJTAUResearchStation(
        station_id="pjtau_stn_ars_madhira",
        canonical_name="Agricultural Research Station, Madhira",
        alternate_names=["ARS, Madhira", "ARS Madhira"],
        pjtau_zone=PJTAUZone.CENTRAL_ZONE,
        address="Agricultural Research Station, Madhira, Khammam District - 507 203, Telangana",
        village="Madhira",
        mandal="Madhira",
        district="Khammam",
        pin_code="507203",
        latitude=16.92,
        longitude=80.37,
        coordinates_original_text="Latitude: 16° 55' N, Longitude: 80° 22' E, Altitude: 45 m MSL",
        met_observatory_details=None,
        established_year="1951",
        total_area_acres=89.95,  # 36.4 ha
        mandated_crops=["Pulses", "Cotton", "Rice"],
        research_focus="Pulses improvement for Central Telangana black soils; breeding Yellow Mosaic Virus (YMV) resistant varieties of greengram and blackgram; cotton agronomy.",
        research_themes=[
            "Greengram and blackgram breeding for high yield and YMV resistance",
            "Pulse-based intercropping systems in vertisols",
            "Management of excess moisture and drought in heavy black soils",
            "Quality breeder and foundation seed production in pulses"
        ],
        infrastructure_facilities=[
            "Administrative block", "Pulses quality and pathology lab", "Seed drying platform",
            "Seed warehouse"
        ],
        source_url=URL_CTZ,
        source_last_updated=SOURCE_LAST_UPDATED,
        retrieved_at=RETRIEVED_AT,
        contacts=[
            PJTAUStationContact(
                contact_id="pjtau_con_madhira_incharge_selected",
                station_id="pjtau_stn_ars_madhira",
                contact_name="Principal Scientist & Head",
                designation="Principal Scientist & Head",
                role=ContactRole.STATION_HEAD_INCHARGE,
                phone_number="8333818207",
                official_email="arsmadhira@pjtau.edu.in",
                source_reference="PJTAU Central Telangana Zone Page",
                contact_status=ContactStatus.OWNER_SELECTED,
                is_active_referral=True,
                notes="Owner-selected PJTAU station-page contact for active referral."
            ),
            PJTAUStationContact(
                contact_id="pjtau_con_madhira_head",
                station_id="pjtau_stn_ars_madhira",
                contact_name="Head / Principal Scientist",
                designation="Principal Scientist & Head",
                role=ContactRole.STATION_HEAD_INCHARGE,
                phone_number="08749-274225",
                official_email="arsmadhira@pjtau.edu.in",
                source_reference="PJTAU Central Telangana Zone Page",
                contact_status=ContactStatus.VERIFIED,
                is_active_referral=False,
                notes="Retained official station landline and PJTAU domain email."
            ),
            PJTAUStationContact(
                contact_id="pjtau_con_madhira_mobile",
                station_id="pjtau_stn_ars_madhira",
                contact_name="Station Head Mobile",
                designation="Principal Scientist Mobile",
                role=ContactRole.STATION_HEAD_INCHARGE,
                phone_number="9440618063",
                official_email="arsmadhira@pjtau.edu.in",
                source_reference="PJTAU Central Telangana Zone Page",
                contact_status=ContactStatus.VERIFIED,
                is_active_referral=False,
                notes="Retained alternate mobile number."
            )
        ],
        research_outputs=[
            PJTAUResearchOutput(
                output_id="pjtau_out_madhira_pulse_mgg295",
                station_id="pjtau_stn_ars_madhira",
                output_type=ResearchOutputType.VARIETY_RELEASED,
                crop_name="Greengram",
                variety_or_technology_name="Madhira Mung 1 (MGG 295)",
                release_year="1999",
                release_status="SVRC",
                description="High yielding greengram variety with moderate resistance to yellow mosaic virus.",
                original_source_text="Greengram variety MGG 295 released by ARS Madhira."
            ),
            PJTAUResearchOutput(
                output_id="pjtau_out_madhira_pulse_mgg348",
                station_id="pjtau_stn_ars_madhira",
                output_type=ResearchOutputType.VARIETY_RELEASED,
                crop_name="Greengram",
                variety_or_technology_name="MGG 348",
                release_year="2009",
                release_status="SVRC",
                description="YMV resistant greengram variety suited for Kharif and Rabi rice fallows.",
                original_source_text="Greengram variety MGG 348 released for cultivation."
            ),
            PJTAUResearchOutput(
                output_id="pjtau_out_madhira_pulse_mbg207",
                station_id="pjtau_stn_ars_madhira",
                output_type=ResearchOutputType.VARIETY_RELEASED,
                crop_name="Blackgram",
                variety_or_technology_name="Madhira Blackgram 1 (MBG 207)",
                release_year="2012",
                release_status="SVRC",
                description="Bold seeded blackgram variety with shiny black grains and powdery mildew tolerance.",
                original_source_text="Blackgram variety MBG 207 released by ARS Madhira."
            )
        ],
        projects_and_outreach=[
            PJTAUProjectOutreach(
                item_id="pjtau_proj_madhira_aicrp_mullarp",
                station_id="pjtau_stn_ars_madhira",
                item_type=ProjectOutreachType.RESEARCH_PROJECT,
                title="AICRP on MULLaRP (Voluntary Centre)",
                funding_agency="ICAR / PJTAU",
                start_date="1985",
                end_date=None,
                is_till_date=True,
                published_duration_text="1985 to Till date",
                description="Evaluation of national germplasm of greengram and blackgram."
            ),
            PJTAUProjectOutreach(
                item_id="pjtau_outr_madhira_tribal_sub_plan",
                station_id="pjtau_stn_ars_madhira",
                item_type=ProjectOutreachType.OUTREACH_PROGRAMME,
                title="Tribal Sub Plan Interventions in Khammam Agency Areas",
                funding_agency="TSP / ICAR",
                start_date="2014",
                end_date=None,
                is_till_date=True,
                published_duration_text="Continuous",
                description="Seed distribution of pulse varieties and farm machinery training for tribal farmers."
            )
        ]
    )
    stations.append(stn_madhira)

    # 9. ARS, Tornala
    stn_tornala = PJTAUResearchStation(
        station_id="pjtau_stn_ars_tornala",
        canonical_name="Agricultural Research Station, Tornala",
        alternate_names=["ARS, Tornala", "ARS Tornala"],
        pjtau_zone=PJTAUZone.CENTRAL_ZONE,
        address="Agricultural Research Station, Tornala, Siddipet District - 502 114, Telangana",
        village="Tornala",
        mandal="Siddipet Rural",
        district="Siddipet",
        pin_code="502114",
        latitude=18.10,
        longitude=78.87,
        coordinates_original_text="Latitude: 18° 06' N, Longitude: 78° 52' E, Altitude: 480 m MSL",
        met_observatory_details=None,
        established_year="1989",
        total_area_acres=82.04,  # 33.2 ha
        mandated_crops=["Sunflower", "Maize", "Cotton", "Pulses"],
        research_focus="Breeding sunflower hybrids for downy mildew and necrosis resistance; dryland agronomy and moisture conservation in light chalka soils of Siddipet.",
        research_themes=[
            "Sunflower hybrid breeding and parental line maintenance",
            "Maize and cotton agronomy in light textured rainfed soils",
            "Rainwater harvesting, farm pond management, and micro-irrigation",
            "Seed village concept and breeder seed production"
        ],
        infrastructure_facilities=[
            "Administrative block", "Sunflower seed testing lab", "Farm pond with lining",
            "Drip irrigation demonstration unit"
        ],
        source_url=URL_CTZ,
        source_last_updated=SOURCE_LAST_UPDATED,
        retrieved_at=RETRIEVED_AT,
        contacts=[
            PJTAUStationContact(
                contact_id="pjtau_con_tornala_incharge_selected",
                station_id="pjtau_stn_ars_tornala",
                contact_name="Principal Scientist & Head",
                designation="Principal Scientist & Head",
                role=ContactRole.STATION_HEAD_INCHARGE,
                phone_number="8333818210",
                official_email="ars.tornala@pjtau.edu.in",
                source_reference="PJTAU Central Telangana Zone Page",
                contact_status=ContactStatus.OWNER_SELECTED,
                is_active_referral=True,
                notes="Owner-selected PJTAU station-page contact for active referral."
            ),
            PJTAUStationContact(
                contact_id="pjtau_con_tornala_head",
                station_id="pjtau_stn_ars_tornala",
                contact_name="Head / Principal Scientist",
                designation="Principal Scientist & Head",
                role=ContactRole.STATION_HEAD_INCHARGE,
                phone_number="08457-250005",
                official_email="ars.tornala@pjtau.edu.in",
                source_reference="PJTAU Central Telangana Zone Page",
                contact_status=ContactStatus.VERIFIED,
                is_active_referral=False,
                notes="Retained official station landline and PJTAU domain email."
            ),
            PJTAUStationContact(
                contact_id="pjtau_con_tornala_mobile",
                station_id="pjtau_stn_ars_tornala",
                contact_name="Station Head Mobile",
                designation="Principal Scientist Mobile",
                role=ContactRole.STATION_HEAD_INCHARGE,
                phone_number="9849206260",
                official_email="ars.tornala@pjtau.edu.in",
                source_reference="PJTAU Central Telangana Zone Page",
                contact_status=ContactStatus.VERIFIED,
                is_active_referral=False,
                notes="Retained alternate mobile number."
            )
        ],
        research_outputs=[
            PJTAUResearchOutput(
                output_id="pjtau_out_tornala_sunflower_tsfc1",
                station_id="pjtau_stn_ars_tornala",
                output_type=ResearchOutputType.VARIETY_RELEASED,
                crop_name="Sunflower",
                variety_or_technology_name="TSFC 1",
                release_year="2018",
                release_status="SVRC",
                description="High yielding sunflower composite with high oil content and resistance to downy mildew.",
                original_source_text="Sunflower variety TSFC 1 released by ARS Tornala."
            ),
            PJTAUResearchOutput(
                output_id="pjtau_out_tornala_tech_moisture_cons",
                station_id="pjtau_stn_ars_tornala",
                output_type=ResearchOutputType.TECHNOLOGY_DEVELOPED,
                crop_name="Cotton",
                variety_or_technology_name="In-situ Moisture Conservation with Ridge and Furrow System",
                release_year="2016",
                release_status="Approved Technology",
                description="Conserves rainwater in light chalka soils and increases rainfed crop yield by 18-22%.",
                original_source_text="In-situ moisture conservation package developed by ARS Tornala."
            )
        ],
        projects_and_outreach=[
            PJTAUProjectOutreach(
                item_id="pjtau_proj_tornala_state_plan",
                station_id="pjtau_stn_ars_tornala",
                item_type=ProjectOutreachType.RESEARCH_PROJECT,
                title="State Plan Research Scheme on Sunflower and Dryland Crops",
                funding_agency="Govt of Telangana / PJTAU",
                start_date="1989",
                end_date=None,
                is_till_date=True,
                published_duration_text="1989 to Till date",
                description="Varietal screening and agronomy experiments on oilseeds and pulses."
            ),
            PJTAUProjectOutreach(
                item_id="pjtau_outr_tornala_seed_village",
                station_id="pjtau_stn_ars_tornala",
                item_type=ProjectOutreachType.OUTREACH_PROGRAMME,
                title="Seed Village Programme and Farmers Training",
                funding_agency="PJTAU",
                start_date="2012",
                end_date=None,
                is_till_date=True,
                published_duration_text="Continuous",
                description="Participatory seed production and field demonstration in Siddipet villages."
            )
        ]
    )
    stations.append(stn_tornala)

    # 10. ARS, Basanthpur
    stn_basanthpur = PJTAUResearchStation(
        station_id="pjtau_stn_ars_basanthpur",
        canonical_name="Agricultural Research Station, Basanthpur",
        alternate_names=["ARS, Basanthpur", "ARS Basanthpur", "ARS, Medak"],
        pjtau_zone=PJTAUZone.CENTRAL_ZONE,
        address="Agricultural Research Station, Basanthpur, Sangareddy District - 502 294, Telangana",
        village="Basanthpur",
        mandal="Nyalkal",
        district="Sangareddy",
        pin_code="502294",
        latitude=17.75,
        longitude=77.63,
        coordinates_original_text="Latitude: 17° 45' N, Longitude: 77° 38' E, Altitude: 540 m MSL",
        met_observatory_details=None,
        established_year="1979",
        total_area_acres=60.54,  # 24.5 ha
        mandated_crops=["Sugarcane", "Wheat"],
        research_focus="Sugarcane varietal evaluation for Telangana vertisols, budchip settling technology, and wheat agronomy for winter crop diversification.",
        research_themes=[
            "Sugarcane varietal evaluation and ratoon crop management",
            "Wheat varietal testing and winter cultivation in vertisols",
            "Single eye bud / budchip settling techniques in sugarcane",
            "Intercropping pulses and oilseeds in autumn sugarcane"
        ],
        infrastructure_facilities=[
            "Administrative building", "Budchip sett nursery shed", "Drip fertigation unit",
            "Farm equipment shed"
        ],
        source_url=URL_CTZ,
        source_last_updated=SOURCE_LAST_UPDATED,
        retrieved_at=RETRIEVED_AT,
        contacts=[
            PJTAUStationContact(
                contact_id="pjtau_con_basanthpur_incharge_selected",
                station_id="pjtau_stn_ars_basanthpur",
                contact_name="Scientist & Head",
                designation="Scientist & Head",
                role=ContactRole.STATION_HEAD_INCHARGE,
                phone_number="8333818208",
                official_email="arsmedak@pjtau.edu.in",
                source_reference="PJTAU Central Telangana Zone Page",
                contact_status=ContactStatus.OWNER_SELECTED,
                is_active_referral=True,
                notes="Owner-selected PJTAU station-page contact for active referral."
            ),
            PJTAUStationContact(
                contact_id="pjtau_con_basanthpur_head",
                station_id="pjtau_stn_ars_basanthpur",
                contact_name="Scientist & Head",
                designation="Scientist & Head",
                role=ContactRole.STATION_HEAD_INCHARGE,
                phone_number="08451-282218",
                official_email="arsmedak@pjtau.edu.in",
                source_reference="PJTAU Central Telangana Zone Page",
                contact_status=ContactStatus.VERIFIED,
                is_active_referral=False,
                notes="Retained official station landline and PJTAU domain email."
            ),
            PJTAUStationContact(
                contact_id="pjtau_con_basanthpur_mobile",
                station_id="pjtau_stn_ars_basanthpur",
                contact_name="Station Head Mobile",
                designation="Scientist & Head Mobile",
                role=ContactRole.STATION_HEAD_INCHARGE,
                phone_number="9440623697",
                official_email="arsmedak@pjtau.edu.in",
                source_reference="PJTAU Central Telangana Zone Page",
                contact_status=ContactStatus.VERIFIED,
                is_active_referral=False,
                notes="Retained alternate mobile number."
            )
        ],
        research_outputs=[
            PJTAUResearchOutput(
                output_id="pjtau_out_basanthpur_sugarcane_co86032",
                station_id="pjtau_stn_ars_basanthpur",
                output_type=ResearchOutputType.VARIETY_RELEASED,
                crop_name="Sugarcane",
                variety_or_technology_name="Co 86032 Adaptation Package",
                release_year="2005",
                release_status="Approved Variety Package",
                description="Production and ratoon management package for high sugar variety Co 86032 in Sangareddy command.",
                original_source_text="Sugarcane production package evaluated at ARS Basanthpur."
            ),
            PJTAUResearchOutput(
                output_id="pjtau_out_basanthpur_tech_budchip_sett",
                station_id="pjtau_stn_ars_basanthpur",
                output_type=ResearchOutputType.TECHNOLOGY_DEVELOPED,
                crop_name="Sugarcane",
                variety_or_technology_name="Budchip Sett Nursery and Wide Row Planting (5 feet)",
                release_year="2014",
                release_status="Approved Technology",
                description="Reduces seed cane from 3.5 tonnes to 0.75 tonnes per acre and enables mechanised weeding.",
                original_source_text="Budchip settling and wide row planting developed by ARS Basanthpur."
            )
        ],
        projects_and_outreach=[
            PJTAUProjectOutreach(
                item_id="pjtau_proj_basanthpur_state_sugarcane",
                station_id="pjtau_stn_ars_basanthpur",
                item_type=ProjectOutreachType.RESEARCH_PROJECT,
                title="State Plan Sugarcane Research Scheme",
                funding_agency="Govt of Telangana / PJTAU",
                start_date="1979",
                end_date=None,
                is_till_date=True,
                published_duration_text="1979 to Till date",
                description="Evaluation of sugarcane clones for sugar recovery and drought tolerance."
            ),
            PJTAUProjectOutreach(
                item_id="pjtau_outr_basanthpur_factory_liaison",
                station_id="pjtau_stn_ars_basanthpur",
                item_type=ProjectOutreachType.OUTREACH_PROGRAMME,
                title="Sugar Factory Farmers Liaison and Budchip Training",
                funding_agency="PJTAU / Sugar Mills",
                start_date="2011",
                end_date=None,
                is_till_date=True,
                published_duration_text="Continuous",
                description="Training cane growers attached to Nizam Sugar and local mills on nursery management."
            )
        ]
    )
    stations.append(stn_basanthpur)

    # 11. ARS, Nathnaipally
    stn_nathnaipally = PJTAUResearchStation(
        station_id="pjtau_stn_ars_nathnaipally",
        canonical_name="Agricultural Research Station, Nathnaipally",
        alternate_names=["ARS, Nathnaipally", "ARS Nathnaipally"],
        pjtau_zone=PJTAUZone.CENTRAL_ZONE,
        address="Agricultural Research Station, Nathnaipally, Medak District - 502 301, Telangana",
        village="Nathnaipally",
        mandal="Narsapur",
        district="Medak",
        pin_code="502301",
        latitude=17.73,
        longitude=78.23,
        coordinates_original_text="Latitude: 17° 44' N, Longitude: 78° 14' E, Altitude: 510 m MSL",
        met_observatory_details=None,
        established_year="1986",
        total_area_acres=56.34,  # 22.8 ha
        mandated_crops=["Dhaincha", "Sunhemp", "Agroforestry"],
        research_focus="Germplasm evaluation and seed production in green manure crops (Dhaincha, Sunhemp, Pillipesara), agroforestry models, and soil organic matter enrichment.",
        research_themes=[
            "Green manure germplasm collection, evaluation, and quality seed production",
            "Agroforestry models (Melia dubia, Teak, and Red Sanders based silvi-agriculture)",
            "Soil organic carbon improvement through green manuring",
            "Crop diversification in semi-arid soils of Medak"
        ],
        infrastructure_facilities=[
            "Administrative building", "Green manure seed processing unit", "Agroforestry demonstration plots",
            "Seed storage facility"
        ],
        source_url=URL_CTZ,
        source_last_updated=SOURCE_LAST_UPDATED,
        retrieved_at=RETRIEVED_AT,
        contacts=[
            PJTAUStationContact(
                contact_id="pjtau_con_nathnaipally_incharge_selected",
                station_id="pjtau_stn_ars_nathnaipally",
                contact_name="Scientist & Head",
                designation="Scientist & Head",
                role=ContactRole.STATION_HEAD_INCHARGE,
                phone_number="8333818209",
                official_email="arsnathnaipally@pjtau.edu.in",
                source_reference="PJTAU Central Telangana Zone Page",
                contact_status=ContactStatus.OWNER_SELECTED,
                is_active_referral=True,
                notes="Owner-selected PJTAU station-page contact for active referral."
            ),
            PJTAUStationContact(
                contact_id="pjtau_con_nathnaipally_head",
                station_id="pjtau_stn_ars_nathnaipally",
                contact_name="Scientist & Head",
                designation="Scientist & Head",
                role=ContactRole.STATION_HEAD_INCHARGE,
                phone_number="08452-243220",
                official_email="arsnathnaipally@pjtau.edu.in",
                source_reference="PJTAU Central Telangana Zone Page",
                contact_status=ContactStatus.VERIFIED,
                is_active_referral=False,
                notes="Retained official station landline and PJTAU domain email."
            ),
            PJTAUStationContact(
                contact_id="pjtau_con_nathnaipally_mobile",
                station_id="pjtau_stn_ars_nathnaipally",
                contact_name="Station Head Mobile",
                designation="Scientist & Head Mobile",
                role=ContactRole.STATION_HEAD_INCHARGE,
                phone_number="9440316521",
                official_email="arsnathnaipally@pjtau.edu.in",
                source_reference="PJTAU Central Telangana Zone Page",
                contact_status=ContactStatus.VERIFIED,
                is_active_referral=False,
                notes="Retained alternate mobile number."
            )
        ],
        research_outputs=[
            PJTAUResearchOutput(
                output_id="pjtau_out_nathnaipally_sunhemp_ntpsh11",
                station_id="pjtau_stn_ars_nathnaipally",
                output_type=ResearchOutputType.VARIETY_RELEASED,
                crop_name="Sunhemp",
                variety_or_technology_name="NTPSH 11 (Sunhemp Selection)",
                release_year="2016",
                release_status="Identified Culture",
                description="Fast-growing green manure sunhemp culture producing 18-22 tonnes/ha green biomass in 50 days.",
                original_source_text="Sunhemp culture NTPSH 11 developed at ARS Nathnaipally."
            ),
            PJTAUResearchOutput(
                output_id="pjtau_out_nathnaipally_dhaincha_ntpd13",
                station_id="pjtau_stn_ars_nathnaipally",
                output_type=ResearchOutputType.VARIETY_RELEASED,
                crop_name="Dhaincha",
                variety_or_technology_name="NTPD 13 (Dhaincha Selection)",
                release_year="2018",
                release_status="Identified Culture",
                description="High biomass and nitrogen-fixing dhaincha selection (Sesbania aculeata) tolerant to salinity.",
                original_source_text="Dhaincha culture NTPD 13 developed at ARS Nathnaipally."
            ),
            PJTAUResearchOutput(
                output_id="pjtau_out_nathnaipally_tech_agroforestry",
                station_id="pjtau_stn_ars_nathnaipally",
                output_type=ResearchOutputType.TECHNOLOGY_DEVELOPED,
                crop_name="Agroforestry",
                variety_or_technology_name="Melia dubia + Pulses Agroforestry System Package",
                release_year="2019",
                release_status="Approved Technology",
                description="Intercropping greengram/redgram in 3x3m Malabar Neem plantations during first 3 years for additional income.",
                original_source_text="Silvi-agri system package developed at ARS Nathnaipally."
            )
        ],
        projects_and_outreach=[
            PJTAUProjectOutreach(
                item_id="pjtau_proj_nathnaipally_green_manure",
                station_id="pjtau_stn_ars_nathnaipally",
                item_type=ProjectOutreachType.RESEARCH_PROJECT,
                title="State Green Manure Seed Production Mission Scheme",
                funding_agency="Govt of Telangana / PJTAU",
                start_date="2005",
                end_date=None,
                is_till_date=True,
                published_duration_text="2005 to Till date",
                description="Evaluation and multiplication of green manure germplasm for state-wide distribution."
            ),
            PJTAUProjectOutreach(
                item_id="pjtau_outr_nathnaipally_farmer_fld",
                station_id="pjtau_stn_ars_nathnaipally",
                item_type=ProjectOutreachType.OUTREACH_PROGRAMME,
                title="Farmer Demonstrations on In-situ Green Manuring for Soil Health",
                funding_agency="PJTAU",
                start_date="2015",
                end_date=None,
                is_till_date=True,
                published_duration_text="Continuous",
                description="Frontline demonstrations on dhaincha incorporation before paddy transplanting."
            )
        ]
    )
    stations.append(stn_nathnaipally)

    return stations


def _get_stz_stations() -> List[PJTAUResearchStation]:
    """Southern Telangana Zone - 3 Research Stations."""
    stations: List[PJTAUResearchStation] = []

    # 12. RARS, Palem
    stn_palem = PJTAUResearchStation(
        station_id="pjtau_stn_rars_palem",
        canonical_name="Regional Agricultural Research Station, Palem",
        alternate_names=["RARS, Palem", "RARS Palem"],
        pjtau_zone=PJTAUZone.SOUTHERN_ZONE,
        agro_climatic_descriptor="Semi Arid",  # Preserved separately from PJTAUZone!
        address="Regional Agricultural Research Station, Palem, Nagarkurnool District - 509 215, Telangana",
        village="Palem",
        mandal="Bijinepally",
        district="Nagarkurnool",
        pin_code="509215",
        latitude=16.52,
        longitude=78.25,
        coordinates_original_text="Latitude: 16° 31' N, Longitude: 78° 15' E, Altitude: 460 m MSL",
        met_observatory_details=None,
        established_year="1965",
        total_area_acres=258.22,  # 104.5 ha
        mandated_crops=["Sorghum", "Groundnut", "Castor", "Small Millets", "Redgram"],
        research_focus="Headquarters of Southern Telangana Zone; breeding dryland crops (sorghum, castor, groundnut, millets), drought management, and integrated pest/disease management in semi-arid vertisols and alfisols.",
        research_themes=[
            "Kharif and Rabi grain/fodder sorghum breeding and shoot fly resistance",
            "Castor breeding for high yield and botrytis gray rot tolerance",
            "Groundnut breeding for drought tolerance and foliar diseases resistance",
            "Small millets (foxtail millet, finger millet) improvement for dryland resilience",
            "Integrated Dryland Farming Systems and agromet advisories"
        ],
        infrastructure_facilities=[
            "Administrative complex", "Crop breeding and pathology labs", "Bio-control agent production unit",
            "Automatic Weather Station", "Modern seed processing plant (1 tonne/hr)", "Farmers training hostel"
        ],
        source_url=URL_STZ,
        source_last_updated=SOURCE_LAST_UPDATED,
        retrieved_at=RETRIEVED_AT,
        contacts=[
            PJTAUStationContact(
                contact_id="pjtau_con_palem_incharge_selected",
                station_id="pjtau_stn_rars_palem",
                contact_name="Associate Director of Research",
                designation="Associate Director of Research (ADR)",
                role=ContactRole.STATION_HEAD_INCHARGE,
                phone_number="8332970257",
                official_email=None,
                source_reference="PJTAU Southern Telangana Zone Page",
                contact_status=ContactStatus.OWNER_SELECTED,
                is_active_referral=True,
                notes="Owner-selected PJTAU station-page contact for active referral."
            ),
            PJTAUStationContact(
                contact_id="pjtau_con_palem_adr",
                station_id="pjtau_stn_rars_palem",
                contact_name="Associate Director of Research",
                designation="Associate Director of Research (ADR)",
                role=ContactRole.STATION_HEAD_INCHARGE,
                phone_number="08540-228646",
                official_email=None,
                source_reference="PJTAU Southern Telangana Zone Page",
                contact_status=ContactStatus.VERIFIED,
                is_active_referral=False,
                notes="Retained official station landline."
            ),
            PJTAUStationContact(
                contact_id="pjtau_con_palem_adr_mobile",
                station_id="pjtau_stn_rars_palem",
                contact_name="ADR Mobile Contact",
                designation="Associate Director of Research Mobile",
                role=ContactRole.STATION_HEAD_INCHARGE,
                phone_number="9989625213",
                official_email=None,
                source_reference="PJTAU Southern Telangana Zone Page",
                contact_status=ContactStatus.VERIFIED,
                is_active_referral=False,
                notes="Retained alternate mobile number."
            )
        ],
        research_outputs=[
            PJTAUResearchOutput(
                output_id="pjtau_out_palem_sorghum_psv16",
                station_id="pjtau_stn_rars_palem",
                output_type=ResearchOutputType.VARIETY_RELEASED,
                crop_name="Sorghum",
                variety_or_technology_name="Palem Jowar 1 (PSV 16)",
                release_year="1998",
                release_status="SVRC",
                description="Dual purpose grain and fodder sorghum variety tolerant to shoot fly and grain mold.",
                original_source_text="Sorghum variety Palem Jowar 1 (PSV 16) released by RARS Palem."
            ),
            PJTAUResearchOutput(
                output_id="pjtau_out_palem_castor_pch111",
                station_id="pjtau_stn_rars_palem",
                output_type=ResearchOutputType.VARIETY_RELEASED,
                crop_name="Castor",
                variety_or_technology_name="Palem Castor Hybrid 111 (PCH 111)",
                release_year="2013",
                release_status="CVRC",
                description="High yielding pistillate line castor hybrid with resistance to wilt and tolerance to botrytis.",
                original_source_text="Castor hybrid PCH 111 notified by CVRC."
            ),
            PJTAUResearchOutput(
                output_id="pjtau_out_palem_tech_botrytis_castor",
                station_id="pjtau_stn_rars_palem",
                output_type=ResearchOutputType.TECHNOLOGY_DEVELOPED,
                crop_name="Castor",
                variety_or_technology_name="Weather-Based Botrytis Management Protocol in Castor",
                release_year="2016",
                release_status="Approved Technology",
                description="Prophylactic spray of propiconazole based on RH > 90% and rainy spell alerts from agromet observatory.",
                original_source_text="Botrytis forecasting and spray schedule developed by RARS Palem."
            )
        ],
        projects_and_outreach=[
            PJTAUProjectOutreach(
                item_id="pjtau_proj_palem_aicrp_sorghum",
                station_id="pjtau_stn_rars_palem",
                item_type=ProjectOutreachType.RESEARCH_PROJECT,
                title="AICRP on Sorghum (Palem Centre)",
                funding_agency="ICAR / PJTAU",
                start_date="1970",
                end_date=None,
                is_till_date=True,
                published_duration_text="1970 to Till date",
                description="Multi-environment testing of kharif and rabi grain and sweet sorghum lines."
            ),
            PJTAUProjectOutreach(
                item_id="pjtau_proj_palem_aicrp_castor",
                station_id="pjtau_stn_rars_palem",
                item_type=ProjectOutreachType.RESEARCH_PROJECT,
                title="AICRP on Castor (Palem Centre)",
                funding_agency="ICAR / PJTAU",
                start_date="1972",
                end_date=None,
                is_till_date=True,
                published_duration_text="1972 to Till date",
                description="National coordinated trials on castor hybrids, pistillate line breeding, and botrytis control."
            ),
            PJTAUProjectOutreach(
                item_id="pjtau_proj_palem_aicrp_millets",
                station_id="pjtau_stn_rars_palem",
                item_type=ProjectOutreachType.RESEARCH_PROJECT,
                title="AICRP on Small Millets (Palem Centre)",
                funding_agency="ICAR / PJTAU",
                start_date="1982",
                end_date=None,
                is_till_date=True,
                published_duration_text="1982 to Till date",
                description="Screening and agronomic optimization of foxtail millet, proso millet, and finger millet."
            ),
            PJTAUProjectOutreach(
                item_id="pjtau_proj_palem_aicrpda",
                station_id="pjtau_stn_rars_palem",
                item_type=ProjectOutreachType.RESEARCH_PROJECT,
                title="AICRP on Dryland Agriculture (AICRPDA Palem)",
                funding_agency="ICAR / PJTAU",
                start_date="1978",
                end_date=None,
                is_till_date=True,
                published_duration_text="1978 to Till date",
                description="Research on rainfed farming systems, contingency crop planning, and runoff recycling."
            ),
            PJTAUProjectOutreach(
                item_id="pjtau_outr_palem_daattc_kvk",
                station_id="pjtau_stn_rars_palem",
                item_type=ProjectOutreachType.OUTREACH_PROGRAMME,
                title="DAATTC & KVK Palem Farmer Outreach and Agro-Advisories",
                funding_agency="ICAR / PJTAU",
                start_date="1995",
                end_date=None,
                is_till_date=True,
                published_duration_text="Continuous",
                description="Vocational farmer training, frontline demonstrations, and farmer mobile advisories."
            )
        ]
    )
    stations.append(stn_palem)

    # 13. ARS, Tandur
    stn_tandur = PJTAUResearchStation(
        station_id="pjtau_stn_ars_tandur",
        canonical_name="Agricultural Research Station, Tandur",
        alternate_names=["ARS, Tandur", "ARS Tandur"],
        pjtau_zone=PJTAUZone.SOUTHERN_ZONE,
        address="Agricultural Research Station, Tandur, Vikarabad District - 501 141, Telangana",
        village="Tandur",
        mandal="Tandur",
        district="Vikarabad",
        pin_code="501141",
        latitude=17.25,
        longitude=77.58,
        coordinates_original_text="Latitude: 17° 15' N, Longitude: 77° 35' E, Altitude: 485 m MSL",
        met_observatory_details=None,
        established_year="1981",
        total_area_acres=95.38,  # 38.6 ha
        mandated_crops=["Redgram", "Safflower", "Sorghum", "Chickpea"],
        research_focus="Landmark research center for Tandur Redgram (Geographical Indication - GI Tag registered); safflower breeding for high oil content; rabi sorghum and chickpea in deep black soils.",
        research_themes=[
            "Tandur Redgram improvement and GI certification maintenance",
            "Safflower breeding for high oil yield and aphid tolerance",
            "Chickpea varietal evaluation for mechanical harvesting",
            "Rainfed vertisol soil and water conservation techniques"
        ],
        infrastructure_facilities=[
            "Administrative building", "Pigeonpea quality and cooking testing lab", "Seed processing yard",
            "GI Tag demonstration cell"
        ],
        source_url=URL_STZ,
        source_last_updated=SOURCE_LAST_UPDATED,
        retrieved_at=RETRIEVED_AT,
        contacts=[
            PJTAUStationContact(
                contact_id="pjtau_con_tandur_incharge_selected",
                station_id="pjtau_stn_ars_tandur",
                contact_name="Principal Scientist & Head",
                designation="Principal Scientist & Head",
                role=ContactRole.STATION_HEAD_INCHARGE,
                phone_number="8332970254",
                official_email=None,
                source_reference="PJTAU Southern Telangana Zone Page",
                contact_status=ContactStatus.OWNER_SELECTED,
                is_active_referral=True,
                notes="Owner-selected PJTAU station-page contact for active referral."
            ),
            PJTAUStationContact(
                contact_id="pjtau_con_tandur_head",
                station_id="pjtau_stn_ars_tandur",
                contact_name="Head / Principal Scientist",
                designation="Principal Scientist & Head",
                role=ContactRole.STATION_HEAD_INCHARGE,
                phone_number="08411-272023",
                official_email=None,
                source_reference="PJTAU Southern Telangana Zone Page",
                contact_status=ContactStatus.VERIFIED,
                is_active_referral=False,
                notes="Retained official station landline."
            ),
            PJTAUStationContact(
                contact_id="pjtau_con_tandur_mobile",
                station_id="pjtau_stn_ars_tandur",
                contact_name="Station Head Mobile",
                designation="Principal Scientist Mobile",
                role=ContactRole.STATION_HEAD_INCHARGE,
                phone_number="9440474684",
                official_email=None,
                source_reference="PJTAU Southern Telangana Zone Page",
                contact_status=ContactStatus.VERIFIED,
                is_active_referral=False,
                notes="Retained alternate mobile number."
            )
        ],
        research_outputs=[
            PJTAUResearchOutput(
                output_id="pjtau_out_tandur_redgram_prg176",
                station_id="pjtau_stn_ars_tandur",
                output_type=ResearchOutputType.VARIETY_RELEASED,
                crop_name="Redgram",
                variety_or_technology_name="Pushkala (PRG 176)",
                release_year="2014",
                release_status="SVRC",
                description="High yielding medium duration redgram variety with wilt resistance and excellent cooking quality.",
                original_source_text="Redgram variety Pushkala (PRG 176) released by ARS Tandur."
            ),
            PJTAUResearchOutput(
                output_id="pjtau_out_tandur_redgram_gi_tag",
                station_id="pjtau_stn_ars_tandur",
                output_type=ResearchOutputType.AWARD_RECOGNITION,
                crop_name="Redgram",
                variety_or_technology_name="Tandur Redgram Geographical Indication (GI Tag No. 705)",
                release_year="2022",
                release_status="GI Tag Registered",
                description="Official Geographical Indication registration recognizing unique high protein (22-24%) and taste qualities of redgram grown in Tandur black soils.",
                original_source_text="Tandur Redgram granted Geographical Indication (GI) Tag under ARS Tandur facilitation."
            ),
            PJTAUResearchOutput(
                output_id="pjtau_out_tandur_safflower_tsf1",
                station_id="pjtau_stn_ars_tandur",
                output_type=ResearchOutputType.VARIETY_RELEASED,
                crop_name="Safflower",
                variety_or_technology_name="TSF 1",
                release_year="2016",
                release_status="SVRC",
                description="High oil yielding spineless/low-spininess safflower variety suited for rainfed black vertisols.",
                original_source_text="Safflower variety TSF 1 released by ARS Tandur."
            )
        ],
        projects_and_outreach=[
            PJTAUProjectOutreach(
                item_id="pjtau_proj_tandur_aicrp_pigeonpea",
                station_id="pjtau_stn_ars_tandur",
                item_type=ProjectOutreachType.RESEARCH_PROJECT,
                title="AICRP on Pigeonpea (Tandur Voluntary Centre)",
                funding_agency="ICAR / PJTAU",
                start_date="1983",
                end_date=None,
                is_till_date=True,
                published_duration_text="1983 to Till date",
                description="Evaluation of medium and long duration redgram hybrids and wilt screening."
            ),
            PJTAUProjectOutreach(
                item_id="pjtau_proj_tandur_aicrp_safflower",
                station_id="pjtau_stn_ars_tandur",
                item_type=ProjectOutreachType.RESEARCH_PROJECT,
                title="AICRP on Safflower (Tandur Centre)",
                funding_agency="ICAR / PJTAU",
                start_date="1985",
                end_date=None,
                is_till_date=True,
                published_duration_text="1985 to Till date",
                description="National coordinated safflower varietal trials and aphid management."
            ),
            PJTAUProjectOutreach(
                item_id="pjtau_outr_tandur_gi_farmer_producer",
                station_id="pjtau_stn_ars_tandur",
                item_type=ProjectOutreachType.OUTREACH_PROGRAMME,
                title="Tandur Redgram GI Producer Group Facilitation and FLD",
                funding_agency="NABARD / PJTAU",
                start_date="2020",
                end_date=None,
                is_till_date=True,
                published_duration_text="Continuous",
                description="Organizing farmer producer groups and demonstrating pure seed production of Tandur redgram."
            )
        ]
    )
    stations.append(stn_tandur)

    # 14. ARS, Kampasagar
    stn_kampasagar = PJTAUResearchStation(
        station_id="pjtau_stn_ars_kampasagar",
        canonical_name="Agricultural Research Station, Kampasagar",
        alternate_names=["ARS, Kampasagar", "ARS Kampasagar"],
        pjtau_zone=PJTAUZone.SOUTHERN_ZONE,
        address="Agricultural Research Station, Kampasagar, Nalgonda District - 508 207, Telangana",
        village="Kampasagar",
        mandal="Tripuraram",
        district="Nalgonda",
        pin_code="508207",
        latitude=16.85,
        longitude=79.55,
        coordinates_original_text="Latitude: 16° 51' N, Longitude: 79° 33' E, Altitude: 140 m MSL",
        met_observatory_details=None,
        established_year="1979",
        total_area_acres=104.03,  # 42.1 ha
        mandated_crops=["Paddy"],
        research_focus="Rice improvement for Nagarjuna Sagar Project (NSP) Left Canal command area, managing salinity and alkalinity in canal command soils, and direct seeded rice technologies.",
        research_themes=[
            "Rice varietal improvement for NSP command area",
            "Reclamation and nutrient management in saline-alkali vertisols",
            "Direct wet seeding and dry seeding in canal command situations",
            "Cropping systems in rice fallows with pulses and green manures"
        ],
        infrastructure_facilities=[
            "Administrative building", "Soil and water testing lab", "Canal irrigation sluice system",
            "Seed warehouse and drying yard"
        ],
        source_url=URL_STZ,
        source_last_updated=SOURCE_LAST_UPDATED,
        retrieved_at=RETRIEVED_AT,
        contacts=[
            # Phone is UNAVAILABLE on the official zone page; preserved as None to prevent hallucinations
            PJTAUStationContact(
                contact_id="pjtau_con_kampasagar_head",
                station_id="pjtau_stn_ars_kampasagar",
                contact_name="Station In-Charge",
                designation="Scientist & Head (In-charge)",
                role=ContactRole.STATION_HEAD_INCHARGE,
                phone_number=None,
                official_email=None,
                source_reference="PJTAU Southern Telangana Zone Page",
                contact_status=ContactStatus.UNAVAILABLE,
                is_active_referral=True,
                notes="No station contact number provided on PJTAU station pages. Preserved as unavailable."
            )
        ],
        research_outputs=[
            PJTAUResearchOutput(
                output_id="pjtau_out_kampasagar_rice_kps2874",
                station_id="pjtau_stn_ars_kampasagar",
                output_type=ResearchOutputType.VARIETY_RELEASED,
                crop_name="Rice",
                variety_or_technology_name="KPS 2874",
                release_year="2012",
                release_status="Identified Culture",
                description="Salinity tolerant medium duration rice culture suitable for canal command saline pockets.",
                original_source_text="Rice culture KPS 2874 developed at ARS Kampasagar."
            ),
            PJTAUResearchOutput(
                output_id="pjtau_out_kampasagar_tech_saline_reclamation",
                station_id="pjtau_stn_ars_kampasagar",
                output_type=ResearchOutputType.TECHNOLOGY_DEVELOPED,
                crop_name="Rice",
                variety_or_technology_name="Gypsum Application and Green Manure Reclamation for NSP Command Vertisols",
                release_year="2015",
                release_status="Approved Technology",
                description="Soil reclamation protocol combining gypsum based on soil test with dhaincha green manuring for NSP canal soils.",
                original_source_text="Canal command saline soil reclamation protocol developed at ARS Kampasagar."
            )
        ],
        projects_and_outreach=[
            PJTAUProjectOutreach(
                item_id="pjtau_proj_kampasagar_state_rice",
                station_id="pjtau_stn_ars_kampasagar",
                item_type=ProjectOutreachType.RESEARCH_PROJECT,
                title="State Plan Scheme on Rice Research for Canal Command Area",
                funding_agency="Govt of Telangana / PJTAU",
                start_date="1979",
                end_date=None,
                is_till_date=True,
                published_duration_text="1979 to Till date",
                description="Continuous varietal testing and water management trials in NSP Left Canal command."
            ),
            PJTAUProjectOutreach(
                item_id="pjtau_outr_kampasagar_kvk_collaboration",
                station_id="pjtau_stn_ars_kampasagar",
                item_type=ProjectOutreachType.OUTREACH_PROGRAMME,
                title="KVK Kampasagar Collaborative Farmer Field Schools and FLD",
                funding_agency="PJTAU / ICAR",
                start_date="2014",
                end_date=None,
                is_till_date=True,
                published_duration_text="Continuous",
                description="Demonstrating water saving rice cultivation and direct seeding to canal farmers."
            )
        ]
    )
    stations.append(stn_kampasagar)

    return stations


def get_all_canonical_stations() -> List[PJTAUResearchStation]:
    """
    Returns the complete list of all 14 canonical PJTAU Research Stations
    across Northern (6), Central (5), and Southern (3) Telangana Zones.
    """
    all_stations: List[PJTAUResearchStation] = []
    all_stations.extend(_get_ntz_stations())
    all_stations.extend(_get_ctz_stations())
    all_stations.extend(_get_stz_stations())
    return all_stations
