"""
Agricultural Season Calendar, Regional Geographic Mappings, and Crop Provenance for KrishiVaani.
Phase 5.4 Crop Calendar Provenance & Geographic Separation Audit:
1. DES Telangana official statistical census season classification (Kharif: June-Sept; Rabi: Oct-March).
2. Summer/Zaid treated as an optional crop-planning / contingent cultivation period (April-May).
3. Clear separation of three distinct geographic concepts:
   a. Telangana Administrative Districts (33 revenue districts).
   b. PJTSAU Agro-Climatic Zones (Northern, Central, Southern - for agronomic suitability).
   c. IMD AMFU Operational Clusters (Hyderabad/Rajendranagar, Jagtial - 2 active AMFUs only; Warangal discontinued).
4. Rigorous crop sowing window evidence classification:
   - official_recommendation
   - research_observation
   - historical_reference
   - partially_supported
   - pending_verification
   - unverified
   - contradicted
   - rejected
   Only official verified recommendations may provide actionable sowing guidance.
5. Strict geographic scope enforcement: zone-specific recommendations are not extended state-wide.
6. Standardized season_year semantics (commencement year) with strictly future-bounded upcoming periods.
"""

from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Optional, Dict, List, Tuple

from app.knowledge.geography import (
    AmfuCoverageStatus,
    AmfuAssignmentType,
    DistrictAmfuAssignment,
    get_district_amfu_assignment,
)


# -----------------------------------------------------------------------------
# 1. Evidence Classification Hierarchy
# -----------------------------------------------------------------------------
class EvidenceStatus(str, Enum):
    """
    Provenance evidence classification hierarchy for agricultural calendar rules.
    Phase 5.4 expanded classification.
    Only OFFICIAL_RECOMMENDATION records may be used to provide actionable sowing guidance.
    """
    OFFICIAL_RECOMMENDATION = "official_recommendation"
    RESEARCH_OBSERVATION = "research_observation"
    HISTORICAL_REFERENCE = "historical_reference"
    PARTIALLY_SUPPORTED = "partially_supported"
    PENDING_VERIFICATION = "pending_verification"
    UNVERIFIED = "unverified"
    CONTRADICTED = "contradicted"
    REJECTED = "rejected"

    # Backward compatibility aliases
    VERIFIED_RECOMMENDATION = "verified_recommendation"
    VERIFIED_RESEARCH_OBSERVATION = "verified_research_observation"


# -----------------------------------------------------------------------------
# 2. Season Classification Definitions (DES Telangana & PJTSAU)
# -----------------------------------------------------------------------------
@dataclass(frozen=True)
class AgriculturalSeasonDefinition:
    """
    Administrative and statistical agricultural season definition.
    Kharif and Rabi are official DES agricultural census seasons.
    Summer/Zaid is an optional crop-planning / contingent cultivation period.
    """
    season_name: str
    start_month: int
    start_day: int
    end_month: int
    end_day: int
    telugu_name: str
    is_census_season: bool  # True for DES census seasons; False for optional planning periods
    description: str
    institutional_source: str
    document_citation: str


TELANGANA_OFFICIAL_SEASONS: List[AgriculturalSeasonDefinition] = [
    AgriculturalSeasonDefinition(
        season_name="Kharif",
        start_month=6,
        start_day=1,
        end_month=9,
        end_day=30,
        telugu_name="Vanakaalam",
        is_census_season=True,
        description=(
            "Primary Southwest Monsoon agricultural census season. "
            "Sowing period: June to September. Harvesting period: September to November."
        ),
        institutional_source="Directorate of Economics and Statistics (DES), Government of Telangana",
        document_citation="Season and Crop Report, Concepts and Definitions (Agricultural Statistics at a Glance)",
    ),
    AgriculturalSeasonDefinition(
        season_name="Rabi",
        start_month=10,
        start_day=1,
        end_month=3,
        end_day=31,
        telugu_name="Yasangi",
        is_census_season=True,
        description=(
            "Post-monsoon / Winter agricultural census season spanning across the new calendar year. "
            "Sowing period: October to March (concentrated Oct-Dec). Harvesting period: February to April."
        ),
        institutional_source="Directorate of Economics and Statistics (DES), Government of Telangana",
        document_citation="Season and Crop Report, Concepts and Definitions (Agricultural Statistics at a Glance)",
    ),
    AgriculturalSeasonDefinition(
        season_name="Summer",
        start_month=4,
        start_day=1,
        end_month=5,
        end_day=31,
        telugu_name="Edagaru / Zaid",
        is_census_season=False,
        description=(
            "Optional crop-planning and contingent cultivation period where assured borewell or canal "
            "irrigation exists. Distinct from the two primary DES statistical census seasons."
        ),
        institutional_source="Professor Jayashankar Telangana State Agricultural University (PJTSAU)",
        document_citation="PJTSAU Seasonal Crop Planning & Summer Contingency Guidelines",
    ),
]


# -----------------------------------------------------------------------------
# 3. Separate Geographic Frameworks (Administrative vs Agro-Climatic vs AMFU)
# -----------------------------------------------------------------------------
@dataclass(frozen=True)
class DistrictZoneMapping:
    """
    Administrative district with mappings to distinct geographic layers:
    - agro_climatic_zone: PJTSAU Agro-Climatic Zone (soil/climate suitability)
    - amfu_cluster: IMD Agromet Field Unit under GKMS (weather advisories)
    """
    district_name: str
    normalized_name: str
    district_code: str
    agro_climatic_zone: str       # PJTSAU Zone
    amfu_cluster: str             # IMD AMFU Operational Cluster
    supporting_source: str
    source_publication_date: str
    aliases: Tuple[str, ...] = ()
    amfu_coverage_status: str = "pending_verification"


_PJTSAU_SOURCE = (
    "PJTSAU Directorate of Research: Research Setup & Agro-Climatic Zones of Telangana State (2020/2023) "
    "and Govt. of Telangana Revenue (DA-CMRF) District Reorganization Gazette"
)
_SOURCE_DATE = "2023-08-01"

TELANGANA_33_DISTRICTS: List[DistrictZoneMapping] = [
    # Northern Telangana Zone (NTZ) - 10 Districts
    # PJTSAU Zonal HQ: Regional Agricultural Research Station (RARS), Polasa, Jagtial
    # IMD AMFU: Grounded in individual primary bulletin evidence
    DistrictZoneMapping(
        district_name="Adilabad",
        normalized_name="adilabad",
        district_code="ADL",
        agro_climatic_zone="Northern Telangana Zone",
        amfu_cluster="pending_verification",
        supporting_source=_PJTSAU_SOURCE,
        source_publication_date=_SOURCE_DATE,
        aliases=("adilabad",),
        amfu_coverage_status="pending_verification",
    ),
    DistrictZoneMapping(
        district_name="Kumuram Bheem Asifabad",
        normalized_name="kumuram bheem asifabad",
        district_code="KBA",
        agro_climatic_zone="Northern Telangana Zone",
        amfu_cluster="pending_verification",
        supporting_source=_PJTSAU_SOURCE,
        source_publication_date=_SOURCE_DATE,
        aliases=("asifabad", "komaram bheem", "komarambheem asifabad", "kb asifabad"),
        amfu_coverage_status="pending_verification",
    ),
    DistrictZoneMapping(
        district_name="Mancherial",
        normalized_name="mancherial",
        district_code="MNCL",
        agro_climatic_zone="Northern Telangana Zone",
        amfu_cluster="pending_verification",
        supporting_source=_PJTSAU_SOURCE,
        source_publication_date=_SOURCE_DATE,
        aliases=("mancherial",),
        amfu_coverage_status="pending_verification",
    ),
    DistrictZoneMapping(
        district_name="Nirmal",
        normalized_name="nirmal",
        district_code="NRML",
        agro_climatic_zone="Northern Telangana Zone",
        amfu_cluster="pending_verification",
        supporting_source=_PJTSAU_SOURCE,
        source_publication_date=_SOURCE_DATE,
        aliases=("nirmal",),
        amfu_coverage_status="pending_verification",
    ),
    DistrictZoneMapping(
        district_name="Nizamabad",
        normalized_name="nizamabad",
        district_code="NZB",
        agro_climatic_zone="Northern Telangana Zone",
        amfu_cluster="pending_verification",
        supporting_source=_PJTSAU_SOURCE,
        source_publication_date=_SOURCE_DATE,
        aliases=("nizamabad",),
        amfu_coverage_status="pending_verification",
    ),
    DistrictZoneMapping(
        district_name="Kamareddy",
        normalized_name="kamareddy",
        district_code="KMR",
        agro_climatic_zone="Northern Telangana Zone",
        amfu_cluster="pending_verification",
        supporting_source=_PJTSAU_SOURCE,
        source_publication_date=_SOURCE_DATE,
        aliases=("kamareddy",),
        amfu_coverage_status="pending_verification",
    ),
    DistrictZoneMapping(
        district_name="Karimnagar",
        normalized_name="karimnagar",
        district_code="KRMR",
        agro_climatic_zone="Northern Telangana Zone",
        amfu_cluster="pending_verification",
        supporting_source=_PJTSAU_SOURCE,
        source_publication_date=_SOURCE_DATE,
        aliases=("karimnagar",),
        amfu_coverage_status="pending_verification",
    ),
    DistrictZoneMapping(
        district_name="Jagtial",
        normalized_name="jagtial",
        district_code="JGTL",
        agro_climatic_zone="Northern Telangana Zone",
        amfu_cluster="AMFU Jagtial (RARS Polasa)",
        supporting_source=_PJTSAU_SOURCE,
        source_publication_date=_SOURCE_DATE,
        aliases=("jagtial",),
        amfu_coverage_status="jagtial",
    ),
    DistrictZoneMapping(
        district_name="Peddapalli",
        normalized_name="peddapalli",
        district_code="PDPL",
        agro_climatic_zone="Northern Telangana Zone",
        amfu_cluster="AMFU Jagtial (RARS Polasa)",
        supporting_source=_PJTSAU_SOURCE,
        source_publication_date=_SOURCE_DATE,
        aliases=("peddapalli",),
        amfu_coverage_status="jagtial",
    ),
    DistrictZoneMapping(
        district_name="Rajanna Sircilla",
        normalized_name="rajanna sircilla",
        district_code="RJS",
        agro_climatic_zone="Northern Telangana Zone",
        amfu_cluster="pending_verification",
        supporting_source=_PJTSAU_SOURCE,
        source_publication_date=_SOURCE_DATE,
        aliases=("sircilla", "rajanna", "rajanna siricilla"),
        amfu_coverage_status="pending_verification",
    ),

    # Central Telangana Zone (CTZ) - 11 Districts
    # PJTSAU Zonal HQ: Regional Agricultural Research Station (RARS), Warangal
    # IMD AMFU: Grounded in individual primary bulletin evidence
    DistrictZoneMapping(
        district_name="Warangal",
        normalized_name="warangal",
        district_code="WGL",
        agro_climatic_zone="Central Telangana Zone",
        amfu_cluster="Joint AMFU Hyderabad / AMFU Jagtial",
        supporting_source=_PJTSAU_SOURCE,
        source_publication_date=_SOURCE_DATE,
        aliases=("warangal rural", "warangal"),
        amfu_coverage_status="joint_hyderabad_jagtial",
    ),
    DistrictZoneMapping(
        district_name="Hanamkonda",
        normalized_name="hanamkonda",
        district_code="HNK",
        agro_climatic_zone="Central Telangana Zone",
        amfu_cluster="Joint AMFU Hyderabad / AMFU Jagtial",
        supporting_source=_PJTSAU_SOURCE,
        source_publication_date=_SOURCE_DATE,
        aliases=("warangal urban", "hanamkonda", "hanumakonda"),
        amfu_coverage_status="joint_hyderabad_jagtial",
    ),
    DistrictZoneMapping(
        district_name="Jangaon",
        normalized_name="jangaon",
        district_code="JGN",
        agro_climatic_zone="Central Telangana Zone",
        amfu_cluster="pending_verification",
        supporting_source=_PJTSAU_SOURCE,
        source_publication_date=_SOURCE_DATE,
        aliases=("jangaon", "jangaon district"),
        amfu_coverage_status="pending_verification",
    ),
    DistrictZoneMapping(
        district_name="Jayashankar Bhupalpally",
        normalized_name="jayashankar bhupalpally",
        district_code="JSB",
        agro_climatic_zone="Central Telangana Zone",
        amfu_cluster="Joint AMFU Hyderabad / AMFU Jagtial",
        supporting_source=_PJTSAU_SOURCE,
        source_publication_date=_SOURCE_DATE,
        aliases=("bhupalpally", "jayashankar", "js bhupalpally"),
        amfu_coverage_status="joint_hyderabad_jagtial",
    ),
    DistrictZoneMapping(
        district_name="Mahabubabad",
        normalized_name="mahabubabad",
        district_code="MHBD",
        agro_climatic_zone="Central Telangana Zone",
        amfu_cluster="Joint AMFU Hyderabad / AMFU Jagtial",
        supporting_source=_PJTSAU_SOURCE,
        source_publication_date=_SOURCE_DATE,
        aliases=("mahabubabad",),
        amfu_coverage_status="joint_hyderabad_jagtial",
    ),
    DistrictZoneMapping(
        district_name="Mulugu",
        normalized_name="mulugu",
        district_code="MLG",
        agro_climatic_zone="Central Telangana Zone",
        amfu_cluster="Joint AMFU Hyderabad / AMFU Jagtial",
        supporting_source=_PJTSAU_SOURCE,
        source_publication_date=_SOURCE_DATE,
        aliases=("mulugu",),
        amfu_coverage_status="joint_hyderabad_jagtial",
    ),
    DistrictZoneMapping(
        district_name="Siddipet",
        normalized_name="siddipet",
        district_code="SDPT",
        agro_climatic_zone="Central Telangana Zone",
        amfu_cluster="Joint AMFU Hyderabad / AMFU Jagtial",
        supporting_source=_PJTSAU_SOURCE,
        source_publication_date=_SOURCE_DATE,
        aliases=("siddipet",),
        amfu_coverage_status="joint_hyderabad_jagtial",
    ),
    DistrictZoneMapping(
        district_name="Medak",
        normalized_name="medak",
        district_code="MDK",
        agro_climatic_zone="Central Telangana Zone",
        amfu_cluster="pending_verification",
        supporting_source=_PJTSAU_SOURCE,
        source_publication_date=_SOURCE_DATE,
        aliases=("medak",),
        amfu_coverage_status="pending_verification",
    ),
    DistrictZoneMapping(
        district_name="Sangareddy",
        normalized_name="sangareddy",
        district_code="SGR",
        agro_climatic_zone="Central Telangana Zone",
        amfu_cluster="pending_verification",
        supporting_source=_PJTSAU_SOURCE,
        source_publication_date=_SOURCE_DATE,
        aliases=("sangareddy",),
        amfu_coverage_status="pending_verification",
    ),
    DistrictZoneMapping(
        district_name="Khammam",
        normalized_name="khammam",
        district_code="KMM",
        agro_climatic_zone="Central Telangana Zone",
        amfu_cluster="Joint AMFU Hyderabad / AMFU Jagtial",
        supporting_source=_PJTSAU_SOURCE,
        source_publication_date=_SOURCE_DATE,
        aliases=("khammam",),
        amfu_coverage_status="joint_hyderabad_jagtial",
    ),
    DistrictZoneMapping(
        district_name="Bhadradri Kothagudem",
        normalized_name="bhadradri kothagudem",
        district_code="BDK",
        agro_climatic_zone="Central Telangana Zone",
        amfu_cluster="Joint AMFU Hyderabad / AMFU Jagtial",
        supporting_source=_PJTSAU_SOURCE,
        source_publication_date=_SOURCE_DATE,
        aliases=("kothagudem", "bhadradri", "bhadradri-kothagudem"),
        amfu_coverage_status="joint_hyderabad_jagtial",
    ),

    # Southern Telangana Zone (STZ) - 12 Districts
    # PJTSAU Zonal HQ: Regional Agricultural Research Station (RARS), Palem, Nagarkurnool
    # IMD AMFU: Grounded in individual primary bulletin evidence
    DistrictZoneMapping(
        district_name="Mahabubnagar",
        normalized_name="mahabubnagar",
        district_code="MBNR",
        agro_climatic_zone="Southern Telangana Zone",
        amfu_cluster="pending_verification",
        supporting_source=_PJTSAU_SOURCE,
        source_publication_date=_SOURCE_DATE,
        aliases=("mahabubnagar", "palamuru"),
        amfu_coverage_status="pending_verification",
    ),
    DistrictZoneMapping(
        district_name="Nagarkurnool",
        normalized_name="nagarkurnool",
        district_code="NGKL",
        agro_climatic_zone="Southern Telangana Zone",
        amfu_cluster="AMFU Hyderabad (ACRC PJTSAU Rajendranagar)",
        supporting_source=_PJTSAU_SOURCE,
        source_publication_date=_SOURCE_DATE,
        aliases=("nagarkurnool", "palem"),
        amfu_coverage_status="hyderabad",
    ),
    DistrictZoneMapping(
        district_name="Wanaparthy",
        normalized_name="wanaparthy",
        district_code="WNPY",
        agro_climatic_zone="Southern Telangana Zone",
        amfu_cluster="pending_verification",
        supporting_source=_PJTSAU_SOURCE,
        source_publication_date=_SOURCE_DATE,
        aliases=("wanaparthy",),
        amfu_coverage_status="pending_verification",
    ),
    DistrictZoneMapping(
        district_name="Jogulamba Gadwal",
        normalized_name="jogulamba gadwal",
        district_code="JGD",
        agro_climatic_zone="Southern Telangana Zone",
        amfu_cluster="pending_verification",
        supporting_source=_PJTSAU_SOURCE,
        source_publication_date=_SOURCE_DATE,
        aliases=("gadwal", "jogulamba"),
        amfu_coverage_status="pending_verification",
    ),
    DistrictZoneMapping(
        district_name="Narayanpet",
        normalized_name="narayanpet",
        district_code="NYPT",
        agro_climatic_zone="Southern Telangana Zone",
        amfu_cluster="pending_verification",
        supporting_source=_PJTSAU_SOURCE,
        source_publication_date=_SOURCE_DATE,
        aliases=("narayanpet",),
        amfu_coverage_status="pending_verification",
    ),
    DistrictZoneMapping(
        district_name="Nalgonda",
        normalized_name="nalgonda",
        district_code="NLG",
        agro_climatic_zone="Southern Telangana Zone",
        amfu_cluster="AMFU Hyderabad (ACRC PJTSAU Rajendranagar)",
        supporting_source=_PJTSAU_SOURCE,
        source_publication_date=_SOURCE_DATE,
        aliases=("nalgonda",),
        amfu_coverage_status="hyderabad",
    ),
    DistrictZoneMapping(
        district_name="Suryapet",
        normalized_name="suryapet",
        district_code="SRPT",
        agro_climatic_zone="Southern Telangana Zone",
        amfu_cluster="AMFU Hyderabad (ACRC PJTSAU Rajendranagar)",
        supporting_source=_PJTSAU_SOURCE,
        source_publication_date=_SOURCE_DATE,
        aliases=("suryapet",),
        amfu_coverage_status="hyderabad",
    ),
    DistrictZoneMapping(
        district_name="Yadadri Bhuvanagiri",
        normalized_name="yadadri bhuvanagiri",
        district_code="YDB",
        agro_climatic_zone="Southern Telangana Zone",
        amfu_cluster="AMFU Hyderabad (ACRC PJTSAU Rajendranagar)",
        supporting_source=_PJTSAU_SOURCE,
        source_publication_date=_SOURCE_DATE,
        aliases=("bhongir", "yadadri", "bhuvanagiri"),
        amfu_coverage_status="hyderabad",
    ),
    DistrictZoneMapping(
        district_name="Rangareddy",
        normalized_name="rangareddy",
        district_code="RRD",
        agro_climatic_zone="Southern Telangana Zone",
        amfu_cluster="pending_verification",
        supporting_source=_PJTSAU_SOURCE,
        source_publication_date=_SOURCE_DATE,
        aliases=("ranga reddy", "rangareddy"),
        amfu_coverage_status="pending_verification",
    ),
    DistrictZoneMapping(
        district_name="Vikarabad",
        normalized_name="vikarabad",
        district_code="VKBD",
        agro_climatic_zone="Southern Telangana Zone",
        amfu_cluster="pending_verification",
        supporting_source=_PJTSAU_SOURCE,
        source_publication_date=_SOURCE_DATE,
        aliases=("vikarabad",),
        amfu_coverage_status="pending_verification",
    ),
    DistrictZoneMapping(
        district_name="Medchal-Malkajgiri",
        normalized_name="medchal-malkajgiri",
        district_code="MDCL",
        agro_climatic_zone="Southern Telangana Zone",
        amfu_cluster="pending_verification",
        supporting_source=_PJTSAU_SOURCE,
        source_publication_date=_SOURCE_DATE,
        aliases=("medchal", "malkajgiri", "medchal malkajgiri"),
        amfu_coverage_status="pending_verification",
    ),
    DistrictZoneMapping(
        district_name="Hyderabad",
        normalized_name="hyderabad",
        district_code="HYD",
        agro_climatic_zone="Southern Telangana Zone",
        amfu_cluster="AMFU Hyderabad (ACRC PJTSAU Rajendranagar)",
        supporting_source=_PJTSAU_SOURCE,
        source_publication_date=_SOURCE_DATE,
        aliases=("hyderabad",),
        amfu_coverage_status="hyderabad",
    ),
]

# Alias for backwards compatibility & concise import
TELANGANA_DISTRICTS: List[DistrictZoneMapping] = TELANGANA_33_DISTRICTS


def resolve_telangana_district(district_query: str) -> Optional[DistrictZoneMapping]:
    """
    Validate and match an input district name or alias against the official
    33 Telangana districts registry.
    Returns the canonical DistrictZoneMapping or None if unverified/outside Telangana.
    """
    if not district_query or not str(district_query).strip():
        return None

    q = str(district_query).strip().lower()

    for d in TELANGANA_33_DISTRICTS:
        if q == d.normalized_name or q == d.district_name.lower():
            return d
        if q == d.district_code.lower():
            return d
        if any(q == alias.lower() for alias in d.aliases):
            return d

    # Substring/partial matching when unambiguous
    candidates = []
    for d in TELANGANA_33_DISTRICTS:
        if q in d.normalized_name or q in d.district_name.lower():
            candidates.append(d)
        elif any(q in alias.lower() for alias in d.aliases):
            candidates.append(d)

    if len(candidates) == 1:
        return candidates[0]

    return None


# -----------------------------------------------------------------------------
# 4. Crop-Specific Sowing Windows (With Full Provenance & Evidence Classification)
# -----------------------------------------------------------------------------
@dataclass(frozen=True)
class CropSowingWindow:
    """
    Crop-specific recommended sowing window under regional agro-climatic conditions.
    Preserves full institutional source, publication year, document title, URL,
    exact supporting text, indicative window description, cultivation system,
    and evidence status.
    """
    crop_name: str
    season: str
    sowing_start_month: Optional[int] = None
    sowing_start_day: Optional[int] = None
    sowing_end_month: Optional[int] = None
    sowing_end_day: Optional[int] = None
    water_condition: str = ""
    soil_type: Optional[str] = None
    agro_climatic_zone: Optional[str] = None
    district: Optional[str] = None
    evidence_status: EvidenceStatus = EvidenceStatus.PENDING_VERIFICATION
    is_verified: bool = False
    is_current_recommendation: bool = True
    contingency_notes: str = ""
    source_organization: str = ""
    document_title: str = ""
    publication_year: int = 2024
    reference_location: str = ""
    source_url: Optional[str] = None
    supporting_text: str = ""
    last_verified_date: str = "2026-11-06"
    indicative_window_description: str = ""
    cultivation_system: Optional[str] = None
    actionable_sowing_start: Optional[str] = None
    actionable_sowing_end: Optional[str] = None


PJTSAU_VERIFIED_CROP_WINDOWS: List[CropSowingWindow] = [
    # 1. Cotton (Kharif)
    CropSowingWindow(
        crop_name="Cotton",
        season="Kharif",
        sowing_start_month=None,
        sowing_start_day=None,
        sowing_end_month=None,
        sowing_end_day=None,
        water_condition="Rainfed and Irrigated cotton ecosystems",
        soil_type="Deep black cotton soils (Vertisols) and red sandy loam / chalka soils",
        agro_climatic_zone=None,  # Cultivated across Northern, Central, and Southern zones
        district=None,
        evidence_status=EvidenceStatus.PENDING_VERIFICATION,
        is_verified=False,
        is_current_recommendation=True,
        contingency_notes=(
            "Cotton sowing in Telangana is tied to southwest monsoon onset (broadly June to early/mid-July). "
            "Cultivated in deep black soils and red chalka soils; HDPS is documented in red chalka soils under "
            "high-density closer spacing. Sowing triggers such as 50-60 mm rainfall and arbitrary calendar cutoffs "
            "like July 20 are unverified research claims not validated as blanket recommendations in primary official "
            "university advisories. Exact calendar dates are non-actionable until verified against current PJTSAU Vyavasaya Panchangam."
        ),
        source_organization="Professor Jayashankar Telangana State Agricultural University (PJTSAU)",
        document_title="PJTSAU Vyavasaya Panchangam (Vanakaalam) — Cotton Production Technology",
        publication_year=2024,
        reference_location="Cotton Production Technology section — exact page pending primary audit",
        source_url=None,
        supporting_text=(
            "Cotton is a major Kharif crop in Telangana sown with monsoon onset (broadly June to early/mid-July) "
            "in black and red chalka soils. HDPS is documented in red soils. Unverified claims regarding 50-60mm rainfall trigger "
            "and July 20 cutoff removed from actionable guidance. Exact dates non-actionable."
        ),
        last_verified_date="2026-11-06",
        indicative_window_description="Broad monsoon-onset period (broadly June to early/mid-July)",
        cultivation_system="Standard spacing; High-Density Planting System (HDPS) supported in red chalka soils under specific closer spacing",
        actionable_sowing_start=None,
        actionable_sowing_end=None,
    ),

    # 2. Red Gram (Kharif)
    CropSowingWindow(
        crop_name="Red Gram",
        season="Kharif",
        sowing_start_month=None,
        sowing_start_day=None,
        sowing_end_month=None,
        sowing_end_day=None,
        water_condition="Rainfed",
        soil_type="Red chalka and black soils",
        agro_climatic_zone=None,  # Northern, Central, and Southern zones
        district=None,
        evidence_status=EvidenceStatus.PENDING_VERIFICATION,
        is_verified=False,
        is_current_recommendation=True,
        contingency_notes=(
            "Red Gram (Pigeonpea) is sown with southwest monsoon onset (broadly June to early July) across "
            "red chalka and black soils in Northern, Central, and Southern Telangana zones. Cultivated as a sole "
            "crop and in intercropping systems (e.g., Cotton + Red Gram, Soybean + Red Gram). Exact calendar "
            "boundaries (e.g. June 1 - July 15) are unverified in primary sources and non-actionable."
        ),
        source_organization="Professor Jayashankar Telangana State Agricultural University (PJTSAU)",
        document_title="PJTSAU Pulses Production Guidelines — Red Gram Management",
        publication_year=2024,
        reference_location="Red Gram Kharif package of practices — pending primary document audit",
        source_url=None,
        supporting_text=(
            "Red Gram is sown with monsoon onset in Telangana across red and black soils in all zones. "
            "Broad June to early July sowing window is agronomically recognized; exact calendar dates remain non-actionable "
            "pending official verification."
        ),
        last_verified_date="2026-11-06",
        indicative_window_description="Broad monsoon-onset period (broadly June to early July)",
        cultivation_system="Sole crop and intercropping system (e.g. Cotton+Redgram, Soybean+Redgram)",
        actionable_sowing_start=None,
        actionable_sowing_end=None,
    ),

    # 3. Bengal Gram (Rabi) - Sown across black soils in multiple zones
    CropSowingWindow(
        crop_name="Bengal Gram",
        season="Rabi",
        sowing_start_month=None,
        sowing_start_day=None,
        sowing_end_month=None,
        sowing_end_day=None,
        water_condition="Conserved Moisture / Rainfed",
        soil_type="Deep black cotton soils (Vertisols)",
        agro_climatic_zone=None,  # NTZ (ARS Adilabad), STZ, and CTZ black soils; not universal statewide
        district=None,
        evidence_status=EvidenceStatus.PARTIALLY_SUPPORTED,
        is_verified=False,
        is_current_recommendation=True,
        contingency_notes=(
            "Bengal Gram (Chickpea) cultivation is restricted to deep black soils with conserved soil moisture "
            "across Northern Telangana Zone (ARS Adilabad mandate area), Southern Telangana Zone, and Central Telangana Zone. "
            "It is NOT universally recommended statewide across all soil types. October last week to November first week "
            "sowing is cited in ICAR-CRIDA 2011 district contingency contexts, but represents contingency/research experiment "
            "timing rather than an unconstrained official blanket recommendation. Exact Oct 15 - Nov 15 dates are non-actionable."
        ),
        source_organization="ICAR-CRIDA",
        document_title="District Crop Contingency Plans for Telangana Districts (ICAR-CRIDA, 2011 edition)",
        publication_year=2011,
        reference_location="Rabi Chickpea / Contingency cropping sections",
        source_url=None,
        supporting_text=(
            "ICAR-CRIDA 2011 contingency plans cite post-monsoon chickpea sowing on conserved moisture in deep black soils. "
            "Cultivated in NTZ (ARS Adilabad), STZ, and CTZ deep black soils, not statewide across all soils. Exact dates non-actionable."
        ),
        last_verified_date="2026-11-06",
        indicative_window_description="Post-monsoon indicative period (broadly late October to early November in deep black soils with conserved moisture)",
        cultivation_system="Residual moisture / rainfed post-monsoon cropping",
        actionable_sowing_start=None,
        actionable_sowing_end=None,
    ),

    # 4. Rabi Maize (Rabi) - Multi-zone cultivation under irrigation
    CropSowingWindow(
        crop_name="Rabi Maize",
        season="Rabi",
        sowing_start_month=None,
        sowing_start_day=None,
        sowing_end_month=None,
        sowing_end_day=None,
        water_condition="Irrigated (adequate workable soil moisture mandatory before sowing)",
        soil_type="Well-drained light-to-medium loams and medium black soils (avoid waterlogged soils)",
        agro_climatic_zone=None,  # Cultivated across NTZ, CTZ, and STZ under irrigation; not restricted to NTZ alone
        district=None,
        evidence_status=EvidenceStatus.PENDING_VERIFICATION,
        is_verified=False,
        is_current_recommendation=True,
        contingency_notes=(
            "Rabi Maize is grown across Northern, Central, and Southern Telangana zones under irrigation. "
            "Sowing is strictly dependent on soil moisture status. Expired October 2026 real-time advisories must not "
            "be reused as static calendar recommendations. Exact Oct 15 - Nov 15 dates are non-actionable pending official "
            "university panchangam verification."
        ),
        source_organization="Professor Jayashankar Telangana State Agricultural University (PJTSAU)",
        document_title="PJTSAU Yasangi Guidelines — Coarse Cereals / Rabi Maize Technology",
        publication_year=2023,
        reference_location="Rabi Maize Package of Practices — pending primary document audit",
        source_url=None,
        supporting_text=(
            "Rabi Maize is cultivated across NTZ, CTZ, and STZ with irrigation, conditional on adequate soil moisture. "
            "Real-time advisories from past seasons are not permanent static calendar rules. Exact dates non-actionable."
        ),
        last_verified_date="2026-11-06",
        indicative_window_description="Rabi indicative period (broadly late October to mid-November, conditional on workable soil moisture)",
        cultivation_system="Irrigated intensive cereal system",
        actionable_sowing_start=None,
        actionable_sowing_end=None,
    ),

    # 5. Groundnut (Rabi / Yasangi) - Specific to Southern Zone
    CropSowingWindow(
        crop_name="Groundnut",
        season="Rabi",
        sowing_start_month=None,
        sowing_start_day=None,
        sowing_end_month=None,
        sowing_end_day=None,
        water_condition="Assured Irrigation (drip with fertigation, micro-sprinkler, sprinkler, or farm-pond systems)",
        soil_type="Red sandy loam / Chalka soils with good drainage",
        agro_climatic_zone="Southern Telangana Zone",
        district=None,
        evidence_status=EvidenceStatus.PENDING_VERIFICATION,
        is_verified=False,
        is_current_recommendation=True,
        contingency_notes=(
            "Rabi Groundnut in Southern Telangana Zone (STZ) is grown on red chalka soils under assured irrigation. "
            "Multiple irrigation methods are agronomically valid including drip irrigation with fertigation, micro-sprinklers, "
            "conventional sprinklers, and farm-pond systems; restricting to sprinkler-only is technically unjustified. "
            "Exact Oct 15 - Nov 15 calendar dates are non-actionable pending official PJTSAU verification."
        ),
        source_organization="Professor Jayashankar Telangana State Agricultural University (PJTSAU)",
        document_title="PJTSAU Oilseeds Technology — Yasangi Groundnut",
        publication_year=2023,
        reference_location="Yasangi Groundnut Management section — pending primary audit",
        source_url=None,
        supporting_text=(
            "Rabi Groundnut in Southern Telangana is grown on red chalka soils under assured irrigation (drip/fertigation, "
            "micro-sprinkler, sprinkler, farm ponds). Sprinkler-only restriction rejected. Exact dates non-actionable."
        ),
        last_verified_date="2026-11-06",
        indicative_window_description="Rabi indicative period (broadly late October to mid-November under assured irrigation)",
        cultivation_system="Irrigated oilseed production",
        actionable_sowing_start=None,
        actionable_sowing_end=None,
    ),

    # 6. Summer Sesame (Summer / Late Yasangi)
    CropSowingWindow(
        crop_name="Summer Sesame",
        season="Summer",
        sowing_start_month=None,
        sowing_start_day=None,
        sowing_end_month=None,
        sowing_end_day=None,
        water_condition="Irrigated (assured canal/SRSP ayacut or borewell irrigation)",
        soil_type="Light textured soils / sandy loams in irrigated pockets",
        agro_climatic_zone="Northern Telangana Zone",  # Primarily RARS Jagtial SRSP ayacut area and STZ light soils
        district=None,
        evidence_status=EvidenceStatus.PENDING_VERIFICATION,
        is_verified=False,
        is_current_recommendation=True,
        contingency_notes=(
            "Summer Sesame is restricted to light-textured soils in specific irrigated pockets, primarily RARS Jagtial "
            "SRSP Ayacut in NTZ and suitable light soils in STZ. It is NOT recommended statewide. "
            "Exact Jan 15 - Feb 15 dates are non-actionable pending official primary verification."
        ),
        source_organization="Professor Jayashankar Telangana State Agricultural University (PJTSAU) — RARS Jagtial",
        document_title="PJTSAU Package of Practices for Summer Sesame",
        publication_year=2023,
        reference_location="Summer Til Production Technology — pending primary audit",
        source_url=None,
        supporting_text=(
            "Summer Sesame is restricted to light-soil irrigated command areas (e.g. SRSP Ayacut under RARS Jagtial in NTZ "
            "and suitable STZ pockets). Statewide recommendation rejected. Exact dates non-actionable."
        ),
        last_verified_date="2026-11-06",
        indicative_window_description="Summer indicative period (broadly January to early February in command areas and light soils)",
        cultivation_system="Post-paddy / summer residual irrigated cultivation",
        actionable_sowing_start=None,
        actionable_sowing_end=None,
    ),
]


# -----------------------------------------------------------------------------
# 5. Season Planning Horizon Resolution Result
# -----------------------------------------------------------------------------
@dataclass
class SeasonResolutionResult:
    """
    Standardized, explicit season-resolution result for KrishiVaani.
    Semantics:
    - season_year represents the calendar year in which the specified season commences.
    - season_start_date and season_end_date provide ISO date boundaries.
    - is_future_period indicates whether the resolved period starts strictly after as_of_date.
    - is_census_season indicates whether the period is an official DES agricultural census season.
    """
    season: str
    season_year: int
    season_start_date: str
    season_end_date: str
    planning_horizon: str
    is_future_period: bool
    is_census_season: bool
    clarification_required: bool
    explanation: str

    def __iter__(self):
        """Preserves backward-compatible tuple unpacking: target_season, target_year, clarify, explanation"""
        return iter((self.season, self.season_year, self.clarification_required, self.explanation))


# -----------------------------------------------------------------------------
# 6. Agricultural Calendar Engine
# -----------------------------------------------------------------------------
class AgriculturalCalendar:
    """
    Configurable agricultural season and regional calendar engine.
    Maintains strict separation between:
    1. Statistical census season classification (DES Telangana: Kharif & Rabi).
    2. Optional crop-planning periods (Summer / Edagaru).
    3. Official 33 Telangana districts.
    4. PJTSAU Agro-Climatic Zones (agricultural suitability).
    5. IMD AMFU Operational Clusters (GKMS meteorological weather advisory bulletins).
    6. Verified crop-specific sowing windows with strict evidence classification.
    """

    def __init__(self, state: str = "Telangana"):
        self.state = state
        self.is_supported_state = (state.strip().lower() == "telangana")
        self.official_seasons: List[AgriculturalSeasonDefinition] = (
            TELANGANA_OFFICIAL_SEASONS if self.is_supported_state else []
        )
        self.districts: List[DistrictZoneMapping] = (
            TELANGANA_33_DISTRICTS if self.is_supported_state else []
        )
        self.sowing_windows: List[CropSowingWindow] = (
            list(PJTSAU_VERIFIED_CROP_WINDOWS) if self.is_supported_state else []
        )

    # -------------------------------------------------------------------------
    # District, Zone & AMFU Cluster Methods (Separate Geographic Frameworks)
    # -------------------------------------------------------------------------
    def get_all_districts(self) -> List[DistrictZoneMapping]:
        """Return all officially mapped districts for the state (33 for Telangana)."""
        return list(self.districts)

    def get_district_info(self, district: Optional[str]) -> Optional[DistrictZoneMapping]:
        """
        Lookup official district metadata by normalized name or recognized alias.
        Returns None for unsupported or missing districts (no guessing).
        """
        if not district or not district.strip():
            return None
        target = district.strip().lower()
        for d in self.districts:
            if d.normalized_name == target or target in d.aliases or d.district_name.lower() == target:
                return d
        return None

    def get_district_zone(self, district: Optional[str]) -> Optional[str]:
        """
        Resolve PJTSAU Agro-Climatic Zone (agricultural suitability) for a district.
        Returns None if district is unknown or outside Telangana.
        """
        info = self.get_district_info(district)
        return info.agro_climatic_zone if info else None

    def get_district_amfu(self, district: Optional[str]) -> Optional[str]:
        """
        Resolve IMD Agromet Field Unit (AMFU) operational weather bulletin cluster for a district.
        Maintains separation from PJTSAU agricultural suitability zones.
        """
        info = self.get_district_info(district)
        return info.amfu_cluster if info else None

    def get_district_amfu_assignment(self, district: Optional[str]) -> Optional[DistrictAmfuAssignment]:
        """
        Resolve individual district meteorological mapping record under IMD GKMS.
        Maintains separation from PJTSAU agricultural suitability zones.
        """
        if not district:
            return None
        info = self.get_district_info(district)
        if not info:
            return None
        return get_district_amfu_assignment(info.district_name)

    def get_districts_in_agro_climatic_zone(self, zone_name: str) -> List[str]:
        """Retrieve list of district names belonging to a specified PJTSAU agro-climatic zone."""
        clean_z = zone_name.strip().lower()
        return [
            d.district_name
            for d in self.districts
            if d.agro_climatic_zone.lower() == clean_z
        ]

    def get_districts_in_amfu_cluster(self, amfu_name: str) -> List[str]:
        """Retrieve list of district names served by a specified IMD AMFU operational cluster."""
        clean_a = amfu_name.strip().lower()
        return [
            d.district_name
            for d in self.districts
            if clean_a in d.amfu_cluster.lower()
        ]

    # -------------------------------------------------------------------------
    # General Season Methods
    # -------------------------------------------------------------------------
    def resolve_general_season_for_date(
        self, target_date: date
    ) -> Optional[AgriculturalSeasonDefinition]:
        """
        Determine which agricultural season or planning period covers the given date.
        - Kharif: June 1 to September 30 (DES Census Season)
        - Rabi: October 1 to March 31 (DES Census Season)
        - Summer: April 1 to May 31 (Optional Crop Planning Period)
        """
        if not self.is_supported_state:
            return None

        m, d = target_date.month, target_date.day
        for s in self.official_seasons:
            if s.start_month <= s.end_month:
                if (m > s.start_month or (m == s.start_month and d >= s.start_day)) and \
                   (m < s.end_month or (m == s.end_month and d <= s.end_day)):
                    return s
            else:
                # Wrap-around season (Rabi: October to March)
                in_late_year = (m > s.start_month) or (m == s.start_month and d >= s.start_day)
                in_early_year = (m < s.end_month) or (m == s.end_month and d <= s.end_day)
                if in_late_year or in_early_year:
                    return s
        return None

    # -------------------------------------------------------------------------
    # Crop Sowing Window Methods (With Geographic Scope & Evidence Enforcement)
    # -------------------------------------------------------------------------
    def get_crop_sowing_window(
        self,
        crop_name: str,
        season: Optional[str] = None,
        district: Optional[str] = None,
    ) -> Optional[CropSowingWindow]:
        """
        Lookup crop sowing window matching crop, season, and district agro-climatic zone.
        Returns None if no matching citation exists.
        """
        if not self.is_supported_state or not crop_name:
            return None

        crop_clean = crop_name.strip().lower()
        district_zone = self.get_district_zone(district)

        matched: List[CropSowingWindow] = []
        for w in self.sowing_windows:
            if w.crop_name.lower() == crop_clean:
                if season and w.season.lower() != season.strip().lower():
                    continue
                matched.append(w)

        if not matched:
            return None

        # Prioritize zone-specific window if available
        if district_zone:
            for w in matched:
                if w.agro_climatic_zone and w.agro_climatic_zone.lower() == district_zone.lower():
                    return w

        return matched[0]

    def is_in_crop_sowing_window(
        self,
        crop_name: str,
        target_date: date,
        district: Optional[str] = None,
        season: Optional[str] = None,
    ) -> Tuple[bool, Optional[CropSowingWindow], str]:
        """
        Evaluate if target_date falls within the crop's official verified sowing window.
        Enforces:
        1. Only EvidenceStatus.VERIFIED_RECOMMENDATION records can return in_window=True.
        2. Research observations, historical references, and unverified records are excluded.
        3. Geographic scope: zone-specific recommendations are strictly enforced and not
           extended to unsupported districts.
        Returns: (in_window, window_record, explanation)
        """
        window = self.get_crop_sowing_window(crop_name=crop_name, season=season, district=district)
        if not window:
            return (
                False,
                None,
                f"No specific sowing window citation documented for crop '{crop_name}' in calendar database.",
            )

        # Gate A: Evidence Classification Check (Only verified recommendations are actionable)
        ACTIONABLE_STATUSES = {
            EvidenceStatus.OFFICIAL_RECOMMENDATION,
            EvidenceStatus.VERIFIED_RECOMMENDATION,
        }
        if window.evidence_status not in ACTIONABLE_STATUSES:
            if window.evidence_status in (
                EvidenceStatus.RESEARCH_OBSERVATION,
                EvidenceStatus.VERIFIED_RESEARCH_OBSERVATION,
            ):
                return (
                    False,
                    window,
                    f"Citation for '{crop_name}' is classified as a research observation (not an official "
                    f"university recommendation) and cannot be provided as actionable sowing guidance.",
                )
            elif window.evidence_status == EvidenceStatus.HISTORICAL_REFERENCE:
                return (
                    False,
                    window,
                    f"Citation for '{crop_name}' is classified as a historical reference and cannot be provided "
                    f"as a current recommendation.",
                )
            elif window.evidence_status == EvidenceStatus.PENDING_VERIFICATION:
                return (
                    False,
                    window,
                    f"Crop sowing window for '{crop_name}' is pending official verification.",
                )
            elif window.evidence_status == EvidenceStatus.PARTIALLY_SUPPORTED:
                return (
                    False,
                    window,
                    f"Crop sowing window for '{crop_name}' is partially supported but not fully verified for official guidance.",
                )
            else:
                return (
                    False,
                    window,
                    f"Crop sowing citation for '{crop_name}' is rejected or unsupported.",
                )

        if not window.is_current_recommendation:
            return (
                False,
                window,
                f"Crop sowing recommendation for '{crop_name}' is marked historic/deprecated "
                f"by {window.source_organization}. Current recommendation is unavailable.",
            )

        # Gate B: Geographic Scope Enforcement
        if window.agro_climatic_zone and district:
            dist_zone = self.get_district_zone(district)
            if dist_zone and dist_zone.lower() != window.agro_climatic_zone.lower():
                return (
                    False,
                    window,
                    f"Crop sowing recommendation for '{crop_name}' is specifically verified for "
                    f"'{window.agro_climatic_zone}', but district '{district}' belongs to '{dist_zone}'. "
                    "Recommendation cannot be extended beyond its verified geographic scope.",
                )

        # Gate C: Temporal Calendar Window Evaluation (Exact Dates Verification Gate)
        if (
            window.sowing_start_month is None or window.sowing_start_day is None or
            window.sowing_end_month is None or window.sowing_end_day is None
        ):
            return (
                False,
                window,
                f"Crop '{crop_name}' has indicative guidance ({window.indicative_window_description}), "
                f"but exact calendar sowing dates are not officially verified and cannot be provided as actionable guidance.",
            )

        m, d = target_date.month, target_date.day
        in_window = False

        if window.sowing_start_month <= window.sowing_end_month:
            in_window = (
                (m > window.sowing_start_month or (m == window.sowing_start_month and d >= window.sowing_start_day)) and
                (m < window.sowing_end_month or (m == window.sowing_end_month and d <= window.sowing_end_day))
            )
        else:
            in_late_year = (m > window.sowing_start_month) or (m == window.sowing_start_month and d >= window.sowing_start_day)
            in_early_year = (m < window.sowing_end_month) or (m == window.sowing_end_month and d <= window.sowing_end_day)
            in_window = in_late_year or in_early_year

        date_str = target_date.isoformat()
        citation_str = (
            f"Source: {window.source_organization} ({window.document_title}, "
            f"{window.publication_year}, {window.reference_location}). "
            f"Condition: {window.water_condition}"
            + (f", Soil: {window.soil_type}" if window.soil_type else "")
            + (f", Zone: {window.agro_climatic_zone}" if window.agro_climatic_zone else "")
        )

        if in_window:
            expl = (
                f"Date {date_str} is within the official sowing window ({window.sowing_start_month}/{window.sowing_start_day} "
                f"to {window.sowing_end_month}/{window.sowing_end_day}) for {window.crop_name} ({window.season}). "
                f"{citation_str}."
            )
        else:
            expl = (
                f"Date {date_str} is outside the recommended sowing window ({window.sowing_start_month}/{window.sowing_start_day} "
                f"to {window.sowing_end_month}/{window.sowing_end_day}) for {window.crop_name} ({window.season}). "
                f"{citation_str}."
            )

        return in_window, window, expl

    # -------------------------------------------------------------------------
    # Planning Horizon & Season-Year Semantics (Phase 5.3 & 5.4)
    # -------------------------------------------------------------------------
    def resolve_planning_horizon(
        self,
        planning_horizon: Optional[str],
        query_season: Optional[str],
        as_of_date: date,
        district: Optional[str] = None,
    ) -> SeasonResolutionResult:
        """
        Evaluate seasonal planning intent with strict season_year semantics.
        Definition: season_year is the calendar year in which the specified season commences.
        Guarantees that an upcoming season occurs strictly after as_of_date.

        Supports distinctions:
        - "current" / None: Active season covering as_of_date.
        - "upcoming" / "next": Next consecutive period in the agricultural cycle.
        - "upcoming_summer" / "summer": Explicitly targets upcoming Summer/Zaid contingent planning.
        - "upcoming_kharif" / "kharif": Explicitly targets upcoming main Kharif season.
        - query_season (e.g. "Kharif"): Targets specific season with correct upcoming year if in future.
        """
        if not self.is_supported_state:
            return SeasonResolutionResult(
                season=query_season or "General",
                season_year=as_of_date.year,
                season_start_date=as_of_date.isoformat(),
                season_end_date=as_of_date.isoformat(),
                planning_horizon=planning_horizon or "unsupported_state",
                is_future_period=False,
                is_census_season=False,
                clarification_required=False,
                explanation=f"State '{self.state}' is outside the verified Telangana regional calendar coverage.",
            )

        m = as_of_date.month
        y = as_of_date.year
        zone = self.get_district_zone(district)
        zone_str = f" in {zone}" if zone else ""

        # 1. Determine active season on as_of_date
        if 6 <= m <= 9:
            active_season = "Kharif"
            active_year = y
            active_start = f"{y}-06-01"
            active_end = f"{y}-09-30"
            active_is_census = True
        elif m >= 10:
            active_season = "Rabi"
            active_year = y  # Commenced Oct y
            active_start = f"{y}-10-01"
            active_end = f"{y+1}-03-31"  # Crosses into next calendar year
            active_is_census = True
        elif 1 <= m <= 3:
            active_season = "Rabi"
            active_year = y - 1  # Commenced Oct of prior year
            active_start = f"{y-1}-10-01"
            active_end = f"{y}-03-31"
            active_is_census = True
        else:  # 4 <= m <= 5
            active_season = "Summer"
            active_year = y
            active_start = f"{y}-04-01"
            active_end = f"{y}-05-31"
            active_is_census = False

        # 2. Case A: Farmer explicitly specified a season name (e.g. "Kharif", "Rabi", "Summer")
        if query_season:
            clean_s = query_season.strip().capitalize()
            if clean_s == active_season:
                # Active season query
                return SeasonResolutionResult(
                    season=active_season,
                    season_year=active_year,
                    season_start_date=active_start,
                    season_end_date=active_end,
                    planning_horizon="explicit_current",
                    is_future_period=False,
                    is_census_season=active_is_census,
                    clarification_required=False,
                    explanation=(
                        f"Active {active_season} season ({active_start} to {active_end}){zone_str}. "
                        f"Season start year: {active_year}."
                    ),
                )
            else:
                # Future season requested
                if clean_s == "Kharif":
                    tgt_y = y if (m < 6) else y + 1
                    s_start = f"{tgt_y}-06-01"
                    s_end = f"{tgt_y}-09-30"
                    return SeasonResolutionResult(
                        season="Kharif",
                        season_year=tgt_y,
                        season_start_date=s_start,
                        season_end_date=s_end,
                        planning_horizon="explicit_future_kharif",
                        is_future_period=True,
                        is_census_season=True,
                        clarification_required=False,
                        explanation=f"Upcoming planned Kharif season: {s_start} to {s_end}{zone_str}. Season start year: {tgt_y}.",
                    )
                elif clean_s == "Rabi":
                    tgt_y = y if (m < 10) else y + 1
                    s_start = f"{tgt_y}-10-01"
                    s_end = f"{tgt_y+1}-03-31"
                    return SeasonResolutionResult(
                        season="Rabi",
                        season_year=tgt_y,
                        season_start_date=s_start,
                        season_end_date=s_end,
                        planning_horizon="explicit_future_rabi",
                        is_future_period=True,
                        is_census_season=True,
                        clarification_required=False,
                        explanation=f"Upcoming planned Rabi season: {s_start} to {s_end}{zone_str}. Season start year: {tgt_y}.",
                    )
                elif clean_s in ("Summer", "Zaid"):
                    tgt_y = y if (m < 4) else y + 1
                    s_start = f"{tgt_y}-04-01"
                    s_end = f"{tgt_y}-05-31"
                    return SeasonResolutionResult(
                        season="Summer",
                        season_year=tgt_y,
                        season_start_date=s_start,
                        season_end_date=s_end,
                        planning_horizon="explicit_future_summer",
                        is_future_period=True,
                        is_census_season=False,
                        clarification_required=False,
                        explanation=(
                            f"Upcoming optional Summer/Zaid cultivation period: {s_start} to {s_end}{zone_str}. "
                            f"Season year: {tgt_y} (Assured irrigation required)."
                        ),
                    )

        # 3. Case B: Current season
        if planning_horizon in ("current", None):
            return SeasonResolutionResult(
                season=active_season,
                season_year=active_year,
                season_start_date=active_start,
                season_end_date=active_end,
                planning_horizon="current",
                is_future_period=False,
                is_census_season=active_is_census,
                clarification_required=False,
                explanation=(
                    f"Active agricultural period on {as_of_date.isoformat()} in Telangana{zone_str} is "
                    f"{active_season} ({active_start} to {active_end}). Commenced in year {active_year}."
                ),
            )

        # 4. Case C: Specific upcoming distinctions
        # Case C1: Upcoming Summer cultivation specifically
        if planning_horizon in ("upcoming_summer", "summer"):
            tgt_y = y if (m < 4) else y + 1
            s_start = f"{tgt_y}-04-01"
            s_end = f"{tgt_y}-05-31"
            return SeasonResolutionResult(
                season="Summer",
                season_year=tgt_y,
                season_start_date=s_start,
                season_end_date=s_end,
                planning_horizon="upcoming_summer",
                is_future_period=True,
                is_census_season=False,
                clarification_required=False,
                explanation=(
                    f"Upcoming Summer/Zaid cultivation period: {s_start} to {s_end}{zone_str}. "
                    f"Season year: {tgt_y}. Note: Summer is an optional crop-planning period requiring assured irrigation."
                ),
            )

        # Case C2: Upcoming Kharif main season specifically
        if planning_horizon in ("upcoming_kharif", "kharif", "next_main_season"):
            tgt_y = y if (m < 6) else y + 1
            s_start = f"{tgt_y}-06-01"
            s_end = f"{tgt_y}-09-30"
            return SeasonResolutionResult(
                season="Kharif",
                season_year=tgt_y,
                season_start_date=s_start,
                season_end_date=s_end,
                planning_horizon="upcoming_kharif",
                is_future_period=True,
                is_census_season=True,
                clarification_required=False,
                explanation=(
                    f"Next main Kharif agricultural census season: {s_start} to {s_end}{zone_str}. "
                    f"Season start year: {tgt_y}. Source: DES Telangana."
                ),
            )

        # Case C3: General "upcoming" / "next" in consecutive sequence
        if planning_horizon in ("upcoming", "next"):
            if active_season == "Kharif":
                # Next is Rabi
                s_start = f"{y}-10-01"
                s_end = f"{y+1}-03-31"
                return SeasonResolutionResult(
                    season="Rabi",
                    season_year=y,
                    season_start_date=s_start,
                    season_end_date=s_end,
                    planning_horizon="upcoming",
                    is_future_period=True,
                    is_census_season=True,
                    clarification_required=False,
                    explanation=f"Upcoming season following Kharif is Rabi ({s_start} to {s_end}){zone_str}.",
                )
            elif active_season == "Rabi":
                # Next is Summer optional planning period
                tgt_y = y + 1 if m >= 10 else y
                s_start = f"{tgt_y}-04-01"
                s_end = f"{tgt_y}-05-31"
                return SeasonResolutionResult(
                    season="Summer",
                    season_year=tgt_y,
                    season_start_date=s_start,
                    season_end_date=s_end,
                    planning_horizon="upcoming",
                    is_future_period=True,
                    is_census_season=False,
                    clarification_required=False,
                    explanation=(
                        f"Upcoming period following Rabi is Summer ({s_start} to {s_end}){zone_str}. "
                        f"Season year: {tgt_y} (Optional contingent period under assured irrigation)."
                    ),
                )
            else:  # Active is Summer
                # Next is Kharif
                s_start = f"{y}-06-01"
                s_end = f"{y}-09-30"
                return SeasonResolutionResult(
                    season="Kharif",
                    season_year=y,
                    season_start_date=s_start,
                    season_end_date=s_end,
                    planning_horizon="upcoming",
                    is_future_period=True,
                    is_census_season=True,
                    clarification_required=False,
                    explanation=f"Upcoming season following Summer is Kharif ({s_start} to {s_end}){zone_str}.",
                )

        # Ambiguous planning intent
        return SeasonResolutionResult(
            season="Unknown",
            season_year=y,
            season_start_date="",
            season_end_date="",
            planning_horizon=planning_horizon or "ambiguous",
            is_future_period=False,
            is_census_season=False,
            clarification_required=True,
            explanation=f"Intended agricultural season or planning horizon '{planning_horizon}' could not be determined. Please specify season.",
        )
