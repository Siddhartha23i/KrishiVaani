"""
Geography module for KrishiVaani — Phase 5.4.1.
Three completely independent geographic systems:
1. Administrative: 33 Telangana districts (revenue classification)
2. PJTSAU Agro-Climatic Zones: 3 zones (soil/crop suitability)
3. IMD AMFU: Agromet Field Units for GKMS weather advisories

Phase 5.4.1 Corrections:
- Every district has its own independent meteorological mapping record.
- AMFU boundaries do NOT derive from PJTSAU agro-climatic zones or proximity.
- Assignment states: hyderabad, jagtial, joint_hyderabad_jagtial, unknown, pending_verification.
- Explicit bulletin citations preserved for each district, including discrepancy notes where
  districts appear in multiple bulletin series (e.g. post-DAMU reorganization).
- Only 2 active AMFUs: Hyderabad (ACRC Rajendranagar) and Jagtial (RARS Polasa).
- AMFU Warangal is NOT active; former DAMU Warangal and DAMU Wyra/Khammam are historical/discontinued.
- RARS Warangal remains a PJTSAU research station only.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional, List, Tuple, Dict

# Re-export planning safety policy
from app.knowledge.planning_safety import (
    SAFETY_RULE_FORECAST_ALONE_CANNOT_TRIGGER_ADVICE,
    REQUIRED_AGRONOMIC_CONTEXT_FACTORS,
    AdvisorySafetyEvaluationResult,
    AdvisorySafetyViolationError,
    AdvisoryTriggerSafetyPolicy,
)


# -------------------------------------------------------------------------
# 1. Administrative District Record
# -------------------------------------------------------------------------
@dataclass(frozen=True)
class AdministrativeDistrict:
    """
    Telangana revenue district as constituted after reorganization.
    Source: Government of Telangana Revenue Department Gazette.
    """
    district_name: str
    normalized_name: str
    district_code: str
    aliases: Tuple[str, ...]
    formation_date: str  # ISO date of district formation/reorganization
    source: str


# -------------------------------------------------------------------------
# 2. PJTSAU Agro-Climatic Zone Record
# -------------------------------------------------------------------------
@dataclass(frozen=True)
class PJTSAUAgroClimaticZone:
    """
    PJTSAU Agro-Climatic Zone for agronomic crop suitability.
    Completely separate from IMD AMFU weather advisory system.
    Source: PJTSAU Directorate of Research.
    """
    zone_name: str
    zone_abbreviation: str
    zonal_hq: str
    zonal_research_station: str
    districts: Tuple[str, ...]  # canonical district names
    source: str
    source_date: str


PJTSAU_AGRO_CLIMATIC_ZONES: List[PJTSAUAgroClimaticZone] = [
    PJTSAUAgroClimaticZone(
        zone_name="Northern Telangana Zone",
        zone_abbreviation="NTZ",
        zonal_hq="Jagtial",
        zonal_research_station="Regional Agricultural Research Station (RARS), Polasa, Jagtial",
        districts=(
            "Adilabad", "Kumuram Bheem Asifabad", "Mancherial", "Nirmal",
            "Nizamabad", "Kamareddy", "Karimnagar", "Jagtial", "Peddapalli",
            "Rajanna Sircilla",
        ),
        source="PJTSAU Directorate of Research: Research Setup & Agro-Climatic Zones of Telangana State",
        source_date="2023-08-01",
    ),
    PJTSAUAgroClimaticZone(
        zone_name="Central Telangana Zone",
        zone_abbreviation="CTZ",
        zonal_hq="Warangal",
        zonal_research_station="Regional Agricultural Research Station (RARS), Warangal",
        districts=(
            "Warangal", "Hanamkonda", "Jangaon", "Jayashankar Bhupalpally",
            "Mahabubabad", "Mulugu", "Siddipet", "Medak", "Sangareddy",
            "Khammam", "Bhadradri Kothagudem",
        ),
        source="PJTSAU Directorate of Research: Research Setup & Agro-Climatic Zones of Telangana State",
        source_date="2023-08-01",
    ),
    PJTSAUAgroClimaticZone(
        zone_name="Southern Telangana Zone",
        zone_abbreviation="STZ",
        zonal_hq="Nagarkurnool",
        zonal_research_station="Regional Agricultural Research Station (RARS), Palem, Nagarkurnool",
        districts=(
            "Mahabubnagar", "Nagarkurnool", "Wanaparthy", "Jogulamba Gadwal",
            "Narayanpet", "Nalgonda", "Suryapet", "Yadadri Bhuvanagiri",
            "Rangareddy", "Vikarabad", "Medchal-Malkajgiri", "Hyderabad",
        ),
        source="PJTSAU Directorate of Research: Research Setup & Agro-Climatic Zones of Telangana State",
        source_date="2023-08-01",
    ),
]


# -------------------------------------------------------------------------
# 3. IMD AMFU Operational Status & Host Institutions
# -------------------------------------------------------------------------
class AmfuStatus(str, Enum):
    ACTIVE = "active"
    DISCONTINUED = "discontinued"
    PENDING_VERIFICATION = "pending_verification"


@dataclass(frozen=True)
class IMDAmfuRecord:
    """
    IMD Agromet Field Unit (AMFU) under the GKMS (Gramin Krishi Mausam Sewa) scheme.
    Completely separate from PJTSAU agro-climatic zones.
    Only 2 active AMFUs are supported by evidence for Telangana.
    """
    amfu_name: str
    amfu_id: str
    host_institution: str
    location: str
    status: AmfuStatus
    status_since: str  # ISO date
    districts_served: Tuple[str, ...]  # explicitly assigned districts with verified single coverage
    evidence_note: str
    source: str


IMD_AMFU_RECORDS: List[IMDAmfuRecord] = [
    IMDAmfuRecord(
        amfu_name="AMFU Hyderabad",
        amfu_id="AMFU_HYD",
        host_institution="Agromet Research Centre (ACRC), PJTSAU, Rajendranagar, Hyderabad",
        location="Rajendranagar, Hyderabad",
        status=AmfuStatus.ACTIVE,
        status_since="2008-01-01",
        districts_served=(
            "Hyderabad", "Nagarkurnool", "Nalgonda", "Suryapet", "Yadadri Bhuvanagiri",
        ),
        evidence_note=(
            "ACRC PJTSAU Rajendranagar is an IMD-designated AMFU under GKMS. "
            "Explicit bulletin coverage confirmed for listed districts; also contributes to joint bulletins "
            "for Central Telangana districts."
        ),
        source="IMD GKMS / PJTSAU ACRC Rajendranagar public advisory bulletins",
    ),
    IMDAmfuRecord(
        amfu_name="AMFU Jagtial",
        amfu_id="AMFU_JGT",
        host_institution="Regional Agricultural Research Station (RARS), Polasa, Jagtial",
        location="Polasa, Jagtial, Telangana",
        status=AmfuStatus.ACTIVE,
        status_since="2008-01-01",
        districts_served=(
            "Jagtial", "Peddapalli",
        ),
        evidence_note=(
            "RARS Polasa, Jagtial is an IMD-designated AMFU under GKMS. "
            "Explicit bulletin coverage confirmed for listed districts; also contributes to joint/operational "
            "bulletins for Central and eastern districts."
        ),
        source="IMD GKMS / PJTSAU RARS Jagtial public advisory bulletins",
    ),
]

HISTORICAL_DAMU_RECORDS: List[IMDAmfuRecord] = [
    IMDAmfuRecord(
        amfu_name="DAMU Warangal (Historical)",
        amfu_id="DAMU_WGL_HIST",
        host_institution="Regional Agricultural Research Station (RARS), Warangal",
        location="Warangal, Telangana",
        status=AmfuStatus.DISCONTINUED,
        status_since="2024-03-01",
        districts_served=(),
        evidence_note=(
            "Former District Agromet Unit (DAMU) at RARS Warangal. "
            "Discontinued from 2024-03-01 per Ministry of Earth Sciences directive. "
            "NOT an active GKMS AMFU. RARS Warangal remains a PJTSAU research station only."
        ),
        source="Ministry of Earth Sciences / IMD circular on DAMU closure",
    ),
    IMDAmfuRecord(
        amfu_name="DAMU Wyra / Khammam (Historical)",
        amfu_id="DAMU_WYRA_HIST",
        host_institution="Krishi Vigyan Kendra (KVK), Wyra, Khammam",
        location="Wyra, Khammam, Telangana",
        status=AmfuStatus.DISCONTINUED,
        status_since="2024-03-01",
        districts_served=(),
        evidence_note=(
            "Former District Agromet Unit (DAMU) at KVK Wyra. "
            "Discontinued from 2024-03-01. Historical advisory record only."
        ),
        source="Ministry of Earth Sciences / IMD circular on DAMU closure",
    ),
]


# -------------------------------------------------------------------------
# 4. District-by-District Meteorological Mapping
# -------------------------------------------------------------------------
class AmfuAssignmentType(str, Enum):
    """
    Operational assignment states for each individual district under IMD GKMS:
    - hyderabad: Explicit coverage by AMFU Hyderabad (ACRC Rajendranagar)
    - jagtial: Explicit coverage by AMFU Jagtial (RARS Polasa)
    - joint_hyderabad_jagtial: Explicit joint coverage in state composite/regional bulletins
    - unknown: Genuinely undocumented or unmapped district
    - pending_verification: Assignment pending primary bulletin review
    """
    HYDERABAD = "hyderabad"
    JAGTIAL = "jagtial"
    JOINT_HYDERABAD_JAGTIAL = "joint_hyderabad_jagtial"
    UNKNOWN = "unknown"
    PENDING_VERIFICATION = "pending_verification"

    # Compatibility aliases for earlier Phase 5.4 assertions
    EXPLICIT_HYDERABAD = "hyderabad"
    EXPLICIT_JAGTIAL = "jagtial"


# Alias for backward-compatibility with earlier Phase 5.4 tests
AmfuCoverageStatus = AmfuAssignmentType


@dataclass(frozen=True)
class DistrictAmfuAssignment:
    """
    Individual district meteorological mapping record.
    Preserves exact supporting bulletin, dates, evidence classification,
    and discrepancy notes when districts appear in multiple bulletin series.
    """
    district_name: str
    district_code: str
    amfu_or_amfus: Tuple[str, ...]
    assignment_type: AmfuAssignmentType
    bulletin_source: str
    bulletin_date: Optional[str]
    source_url: Optional[str]
    last_verified_date: str
    evidence_classification: str
    discrepancy_notes: Optional[str] = None

    @property
    def amfu_coverage_status(self) -> str:
        """Backward-compatibility property returning assignment_type string."""
        return self.assignment_type.value

    @property
    def assigned_amfu_id(self) -> Optional[str]:
        """Backward-compatibility property."""
        if self.assignment_type == AmfuAssignmentType.HYDERABAD:
            return "AMFU_HYD"
        elif self.assignment_type == AmfuAssignmentType.JAGTIAL:
            return "AMFU_JGT"
        elif self.assignment_type == AmfuAssignmentType.JOINT_HYDERABAD_JAGTIAL:
            return "AMFU_HYD_JGT_JOINT"
        return None

    @property
    def evidence_note(self) -> str:
        """Backward-compatibility property."""
        note = f"{self.bulletin_source} ({self.evidence_classification})"
        if self.discrepancy_notes:
            note += f" [Discrepancy: {self.discrepancy_notes}]"
        return note


# -----------------------------------------------------------------------------
# Explicit District-by-District Assignments (All 33 Telangana Districts)
# Grounded strictly in documented IMD GKMS bulletin evidence
# -----------------------------------------------------------------------------
DISTRICT_AMFU_ASSIGNMENTS: Dict[str, DistrictAmfuAssignment] = {
    # -------------------------------------------------------------------------
    # A. Explicit Jagtial Assignments (2 districts)
    # -------------------------------------------------------------------------
    "Jagtial": DistrictAmfuAssignment(
        district_name="Jagtial",
        district_code="JGTL",
        amfu_or_amfus=("AMFU Jagtial",),
        assignment_type=AmfuAssignmentType.JAGTIAL,
        bulletin_source="IMD GKMS District Agromet Advisory Bulletin — Host Station AMFU Polasa, Jagtial",
        bulletin_date="2026-10-31",
        source_url=None,
        last_verified_date="2026-11-06",
        evidence_classification="official_recommendation",
        discrepancy_notes=None,
    ),
    "Peddapalli": DistrictAmfuAssignment(
        district_name="Peddapalli",
        district_code="PDPL",
        amfu_or_amfus=("AMFU Jagtial",),
        assignment_type=AmfuAssignmentType.JAGTIAL,
        bulletin_source="IMD GKMS District Agromet Advisory Bulletin for Peddapalli — AMFU Polasa, Jagtial (Bulletin No. 88/2026)",
        bulletin_date="2026-10-31",
        source_url=None,
        last_verified_date="2026-11-06",
        evidence_classification="official_recommendation",
        discrepancy_notes=None,
    ),

    # -------------------------------------------------------------------------
    # B. Explicit Hyderabad Assignments (5 districts)
    # -------------------------------------------------------------------------
    "Hyderabad": DistrictAmfuAssignment(
        district_name="Hyderabad",
        district_code="HYD",
        amfu_or_amfus=("AMFU Hyderabad",),
        assignment_type=AmfuAssignmentType.HYDERABAD,
        bulletin_source="IMD GKMS Agromet Advisory Bulletin — Host Station ACRC PJTSAU Rajendranagar, Hyderabad",
        bulletin_date="2026-10-31",
        source_url=None,
        last_verified_date="2026-11-06",
        evidence_classification="official_recommendation",
        discrepancy_notes=None,
    ),
    "Nagarkurnool": DistrictAmfuAssignment(
        district_name="Nagarkurnool",
        district_code="NGKL",
        amfu_or_amfus=("AMFU Hyderabad",),
        assignment_type=AmfuAssignmentType.HYDERABAD,
        bulletin_source="IMD GKMS Agromet Advisory Bulletin for Nagarkurnool — AMFU Hyderabad (ACRC Rajendranagar)",
        bulletin_date="2026-10-31",
        source_url=None,
        last_verified_date="2026-11-06",
        evidence_classification="official_recommendation",
        discrepancy_notes=None,
    ),
    "Nalgonda": DistrictAmfuAssignment(
        district_name="Nalgonda",
        district_code="NLG",
        amfu_or_amfus=("AMFU Hyderabad",),
        assignment_type=AmfuAssignmentType.HYDERABAD,
        bulletin_source="IMD GKMS Agromet Advisory Bulletin for Nalgonda — AMFU Hyderabad (ACRC Rajendranagar)",
        bulletin_date="2026-10-31",
        source_url=None,
        last_verified_date="2026-11-06",
        evidence_classification="official_recommendation",
        discrepancy_notes=None,
    ),
    "Suryapet": DistrictAmfuAssignment(
        district_name="Suryapet",
        district_code="SRPT",
        amfu_or_amfus=("AMFU Hyderabad",),
        assignment_type=AmfuAssignmentType.HYDERABAD,
        bulletin_source="IMD GKMS Agromet Advisory Bulletin for Suryapet — AMFU Hyderabad (ACRC Rajendranagar)",
        bulletin_date="2026-10-31",
        source_url=None,
        last_verified_date="2026-11-06",
        evidence_classification="official_recommendation",
        discrepancy_notes=None,
    ),
    "Yadadri Bhuvanagiri": DistrictAmfuAssignment(
        district_name="Yadadri Bhuvanagiri",
        district_code="YDB",
        amfu_or_amfus=("AMFU Hyderabad",),
        assignment_type=AmfuAssignmentType.HYDERABAD,
        bulletin_source="IMD GKMS Agromet Advisory Bulletin for Yadadri Bhuvanagiri — AMFU Hyderabad (ACRC Rajendranagar)",
        bulletin_date="2026-10-31",
        source_url=None,
        last_verified_date="2026-11-06",
        evidence_classification="official_recommendation",
        discrepancy_notes=None,
    ),

    # -------------------------------------------------------------------------
    # C. Joint Hyderabad / Jagtial Assignments & Documented Discrepancies (8 districts)
    # -------------------------------------------------------------------------
    "Jayashankar Bhupalpally": DistrictAmfuAssignment(
        district_name="Jayashankar Bhupalpally",
        district_code="JSB",
        amfu_or_amfus=("AMFU Jagtial", "AMFU Hyderabad"),
        assignment_type=AmfuAssignmentType.JOINT_HYDERABAD_JAGTIAL,
        bulletin_source="IMD GKMS Agromet Advisory Bulletin No. 88/2026 for Jayashankar Bhupalpally & State Composite GKMS Bulletin",
        bulletin_date="2026-10-31",
        source_url=None,
        last_verified_date="2026-11-06",
        evidence_classification="partially_supported",
        discrepancy_notes=(
            "Appears in AMFU Jagtial operational bulletin series and in joint State GKMS advisory issue. "
            "Source discrepancy preserved pending IMD zonal boundary gazette."
        ),
    ),
    "Mulugu": DistrictAmfuAssignment(
        district_name="Mulugu",
        district_code="MLG",
        amfu_or_amfus=("AMFU Jagtial", "AMFU Hyderabad"),
        assignment_type=AmfuAssignmentType.JOINT_HYDERABAD_JAGTIAL,
        bulletin_source="IMD GKMS Agromet Advisory Bulletin for Mulugu & State Composite GKMS Bulletin",
        bulletin_date="2026-10-31",
        source_url=None,
        last_verified_date="2026-11-06",
        evidence_classification="partially_supported",
        discrepancy_notes=(
            "Referenced under AMFU Jagtial operational coverage in post-DAMU reorganization as well as "
            "joint Hyderabad/Jagtial state bulletin."
        ),
    ),
    "Bhadradri Kothagudem": DistrictAmfuAssignment(
        district_name="Bhadradri Kothagudem",
        district_code="BDK",
        amfu_or_amfus=("AMFU Jagtial", "AMFU Hyderabad"),
        assignment_type=AmfuAssignmentType.JOINT_HYDERABAD_JAGTIAL,
        bulletin_source="IMD GKMS Agromet Advisory Bulletin for Bhadradri Kothagudem & Joint GKMS Composite Bulletin",
        bulletin_date="2026-10-31",
        source_url=None,
        last_verified_date="2026-11-06",
        evidence_classification="partially_supported",
        discrepancy_notes=(
            "Referenced under AMFU Jagtial bulletin series; also included in joint State GKMS composite advisories."
        ),
    ),
    "Khammam": DistrictAmfuAssignment(
        district_name="Khammam",
        district_code="KMM",
        amfu_or_amfus=("AMFU Jagtial", "AMFU Hyderabad"),
        assignment_type=AmfuAssignmentType.JOINT_HYDERABAD_JAGTIAL,
        bulletin_source="IMD GKMS Agromet Advisory Bulletin for Khammam (Post-DAMU Reorganization issue)",
        bulletin_date="2026-10-31",
        source_url=None,
        last_verified_date="2026-11-06",
        evidence_classification="partially_supported",
        discrepancy_notes=(
            "Former DAMU Wyra/Khammam discontinued 2024-03-01. Bulletin references appear under both "
            "AMFU Jagtial and joint Hyderabad/Jagtial state coverage."
        ),
    ),
    "Mahabubabad": DistrictAmfuAssignment(
        district_name="Mahabubabad",
        district_code="MHBD",
        amfu_or_amfus=("AMFU Jagtial", "AMFU Hyderabad"),
        assignment_type=AmfuAssignmentType.JOINT_HYDERABAD_JAGTIAL,
        bulletin_source="IMD GKMS Agromet Advisory Bulletin for Mahabubabad & Joint State GKMS Bulletin",
        bulletin_date="2026-10-31",
        source_url=None,
        last_verified_date="2026-11-06",
        evidence_classification="partially_supported",
        discrepancy_notes=(
            "Appears in AMFU Jagtial bulletin and joint State GKMS advisory. Discrepancy noted pending IMD gazette."
        ),
    ),
    "Hanamkonda": DistrictAmfuAssignment(
        district_name="Hanamkonda",
        district_code="HNK",
        amfu_or_amfus=("AMFU Hyderabad", "AMFU Jagtial"),
        assignment_type=AmfuAssignmentType.JOINT_HYDERABAD_JAGTIAL,
        bulletin_source="IMD GKMS State Composite Bulletin & Joint Agromet Advisory for Hanamkonda",
        bulletin_date="2026-10-31",
        source_url=None,
        last_verified_date="2026-11-06",
        evidence_classification="partially_supported",
        discrepancy_notes=(
            "Central Telangana district referenced in joint Hyderabad/Jagtial GKMS advisories following "
            "DAMU Warangal discontinuation."
        ),
    ),
    "Warangal": DistrictAmfuAssignment(
        district_name="Warangal",
        district_code="WGL",
        amfu_or_amfus=("AMFU Hyderabad", "AMFU Jagtial"),
        assignment_type=AmfuAssignmentType.JOINT_HYDERABAD_JAGTIAL,
        bulletin_source="IMD GKMS State Composite Bulletin & Joint Agromet Advisory for Warangal",
        bulletin_date="2026-10-31",
        source_url=None,
        last_verified_date="2026-11-06",
        evidence_classification="partially_supported",
        discrepancy_notes=(
            "Former DAMU Warangal discontinued 2024-03-01. IMD bulletins reference joint Hyderabad/Jagtial "
            "GKMS advisory coverage. Do not confuse with RARS Warangal research station."
        ),
    ),
    "Siddipet": DistrictAmfuAssignment(
        district_name="Siddipet",
        district_code="SDPT",
        amfu_or_amfus=("AMFU Hyderabad", "AMFU Jagtial"),
        assignment_type=AmfuAssignmentType.JOINT_HYDERABAD_JAGTIAL,
        bulletin_source="IMD GKMS Agromet Advisory Bulletin for Siddipet & Joint State GKMS Bulletin",
        bulletin_date="2026-10-31",
        source_url=None,
        last_verified_date="2026-11-06",
        evidence_classification="partially_supported",
        discrepancy_notes="Referenced in AMFU Hyderabad bulletins and joint State GKMS bulletins.",
    ),

    # -------------------------------------------------------------------------
    # D. Undocumented / Pending Verification Districts (18 districts)
    # Never derived from agro-climatic zone or proximity
    # -------------------------------------------------------------------------
    "Adilabad": DistrictAmfuAssignment(
        district_name="Adilabad",
        district_code="ADL",
        amfu_or_amfus=(),
        assignment_type=AmfuAssignmentType.PENDING_VERIFICATION,
        bulletin_source="Pending verification against primary IMD GKMS bulletin issue",
        bulletin_date=None,
        source_url=None,
        last_verified_date="2026-11-06",
        evidence_classification="pending_verification",
        discrepancy_notes="No explicit single-district primary bulletin reviewed in current audit. Not inferred from agro-climatic zone.",
    ),
    "Kumuram Bheem Asifabad": DistrictAmfuAssignment(
        district_name="Kumuram Bheem Asifabad",
        district_code="KBA",
        amfu_or_amfus=(),
        assignment_type=AmfuAssignmentType.PENDING_VERIFICATION,
        bulletin_source="Pending verification against primary IMD GKMS bulletin issue",
        bulletin_date=None,
        source_url=None,
        last_verified_date="2026-11-06",
        evidence_classification="pending_verification",
        discrepancy_notes="No explicit single-district primary bulletin reviewed in current audit. Not inferred from agro-climatic zone.",
    ),
    "Mancherial": DistrictAmfuAssignment(
        district_name="Mancherial",
        district_code="MNCL",
        amfu_or_amfus=(),
        assignment_type=AmfuAssignmentType.PENDING_VERIFICATION,
        bulletin_source="Pending verification against primary IMD GKMS bulletin issue",
        bulletin_date=None,
        source_url=None,
        last_verified_date="2026-11-06",
        evidence_classification="pending_verification",
        discrepancy_notes="No explicit single-district primary bulletin reviewed in current audit. Not inferred from agro-climatic zone.",
    ),
    "Nirmal": DistrictAmfuAssignment(
        district_name="Nirmal",
        district_code="NRML",
        amfu_or_amfus=(),
        assignment_type=AmfuAssignmentType.PENDING_VERIFICATION,
        bulletin_source="Pending verification against primary IMD GKMS bulletin issue",
        bulletin_date=None,
        source_url=None,
        last_verified_date="2026-11-06",
        evidence_classification="pending_verification",
        discrepancy_notes="No explicit single-district primary bulletin reviewed in current audit. Not inferred from agro-climatic zone.",
    ),
    "Nizamabad": DistrictAmfuAssignment(
        district_name="Nizamabad",
        district_code="NZB",
        amfu_or_amfus=(),
        assignment_type=AmfuAssignmentType.PENDING_VERIFICATION,
        bulletin_source="Pending verification against primary IMD GKMS bulletin issue",
        bulletin_date=None,
        source_url=None,
        last_verified_date="2026-11-06",
        evidence_classification="pending_verification",
        discrepancy_notes="No explicit single-district primary bulletin reviewed in current audit. Not inferred from agro-climatic zone.",
    ),
    "Kamareddy": DistrictAmfuAssignment(
        district_name="Kamareddy",
        district_code="KMR",
        amfu_or_amfus=(),
        assignment_type=AmfuAssignmentType.PENDING_VERIFICATION,
        bulletin_source="Pending verification against primary IMD GKMS bulletin issue",
        bulletin_date=None,
        source_url=None,
        last_verified_date="2026-11-06",
        evidence_classification="pending_verification",
        discrepancy_notes="No explicit single-district primary bulletin reviewed in current audit. Not inferred from agro-climatic zone.",
    ),
    "Karimnagar": DistrictAmfuAssignment(
        district_name="Karimnagar",
        district_code="KRMR",
        amfu_or_amfus=(),
        assignment_type=AmfuAssignmentType.PENDING_VERIFICATION,
        bulletin_source="Pending verification against primary IMD GKMS bulletin issue",
        bulletin_date=None,
        source_url=None,
        last_verified_date="2026-11-06",
        evidence_classification="pending_verification",
        discrepancy_notes="No explicit single-district primary bulletin reviewed in current audit. Not inferred from agro-climatic zone.",
    ),
    "Rajanna Sircilla": DistrictAmfuAssignment(
        district_name="Rajanna Sircilla",
        district_code="RJS",
        amfu_or_amfus=(),
        assignment_type=AmfuAssignmentType.PENDING_VERIFICATION,
        bulletin_source="Pending verification against primary IMD GKMS bulletin issue",
        bulletin_date=None,
        source_url=None,
        last_verified_date="2026-11-06",
        evidence_classification="pending_verification",
        discrepancy_notes="No explicit single-district primary bulletin reviewed in current audit. Not inferred from agro-climatic zone.",
    ),
    "Jangaon": DistrictAmfuAssignment(
        district_name="Jangaon",
        district_code="JGN",
        amfu_or_amfus=(),
        assignment_type=AmfuAssignmentType.PENDING_VERIFICATION,
        bulletin_source="Pending verification against primary IMD GKMS bulletin issue",
        bulletin_date=None,
        source_url=None,
        last_verified_date="2026-11-06",
        evidence_classification="pending_verification",
        discrepancy_notes="No explicit single-district primary bulletin reviewed in current audit. Not inferred from agro-climatic zone.",
    ),
    "Medak": DistrictAmfuAssignment(
        district_name="Medak",
        district_code="MDK",
        amfu_or_amfus=(),
        assignment_type=AmfuAssignmentType.PENDING_VERIFICATION,
        bulletin_source="Pending verification against primary IMD GKMS bulletin issue",
        bulletin_date=None,
        source_url=None,
        last_verified_date="2026-11-06",
        evidence_classification="pending_verification",
        discrepancy_notes="No explicit single-district primary bulletin reviewed in current audit. Not inferred from agro-climatic zone.",
    ),
    "Sangareddy": DistrictAmfuAssignment(
        district_name="Sangareddy",
        district_code="SGR",
        amfu_or_amfus=(),
        assignment_type=AmfuAssignmentType.PENDING_VERIFICATION,
        bulletin_source="Pending verification against primary IMD GKMS bulletin issue",
        bulletin_date=None,
        source_url=None,
        last_verified_date="2026-11-06",
        evidence_classification="pending_verification",
        discrepancy_notes="No explicit single-district primary bulletin reviewed in current audit. Not inferred from agro-climatic zone.",
    ),
    "Mahabubnagar": DistrictAmfuAssignment(
        district_name="Mahabubnagar",
        district_code="MBNR",
        amfu_or_amfus=(),
        assignment_type=AmfuAssignmentType.PENDING_VERIFICATION,
        bulletin_source="Pending verification against primary IMD GKMS bulletin issue",
        bulletin_date=None,
        source_url=None,
        last_verified_date="2026-11-06",
        evidence_classification="pending_verification",
        discrepancy_notes="No explicit single-district primary bulletin reviewed in current audit. Not inferred from agro-climatic zone.",
    ),
    "Wanaparthy": DistrictAmfuAssignment(
        district_name="Wanaparthy",
        district_code="WNPY",
        amfu_or_amfus=(),
        assignment_type=AmfuAssignmentType.PENDING_VERIFICATION,
        bulletin_source="Pending verification against primary IMD GKMS bulletin issue",
        bulletin_date=None,
        source_url=None,
        last_verified_date="2026-11-06",
        evidence_classification="pending_verification",
        discrepancy_notes="No explicit single-district primary bulletin reviewed in current audit. Not inferred from agro-climatic zone.",
    ),
    "Jogulamba Gadwal": DistrictAmfuAssignment(
        district_name="Jogulamba Gadwal",
        district_code="JGD",
        amfu_or_amfus=(),
        assignment_type=AmfuAssignmentType.PENDING_VERIFICATION,
        bulletin_source="Pending verification against primary IMD GKMS bulletin issue",
        bulletin_date=None,
        source_url=None,
        last_verified_date="2026-11-06",
        evidence_classification="pending_verification",
        discrepancy_notes="No explicit single-district primary bulletin reviewed in current audit. Not inferred from agro-climatic zone.",
    ),
    "Narayanpet": DistrictAmfuAssignment(
        district_name="Narayanpet",
        district_code="NYPT",
        amfu_or_amfus=(),
        assignment_type=AmfuAssignmentType.PENDING_VERIFICATION,
        bulletin_source="Pending verification against primary IMD GKMS bulletin issue",
        bulletin_date=None,
        source_url=None,
        last_verified_date="2026-11-06",
        evidence_classification="pending_verification",
        discrepancy_notes="No explicit single-district primary bulletin reviewed in current audit. Not inferred from agro-climatic zone.",
    ),
    "Rangareddy": DistrictAmfuAssignment(
        district_name="Rangareddy",
        district_code="RRD",
        amfu_or_amfus=(),
        assignment_type=AmfuAssignmentType.PENDING_VERIFICATION,
        bulletin_source="Pending verification against primary IMD GKMS bulletin issue",
        bulletin_date=None,
        source_url=None,
        last_verified_date="2026-11-06",
        evidence_classification="pending_verification",
        discrepancy_notes="No explicit single-district primary bulletin reviewed in current audit. Not inferred from agro-climatic zone.",
    ),
    "Vikarabad": DistrictAmfuAssignment(
        district_name="Vikarabad",
        district_code="VKBD",
        amfu_or_amfus=(),
        assignment_type=AmfuAssignmentType.PENDING_VERIFICATION,
        bulletin_source="Pending verification against primary IMD GKMS bulletin issue",
        bulletin_date=None,
        source_url=None,
        last_verified_date="2026-11-06",
        evidence_classification="pending_verification",
        discrepancy_notes="No explicit single-district primary bulletin reviewed in current audit. Not inferred from agro-climatic zone.",
    ),
    "Medchal-Malkajgiri": DistrictAmfuAssignment(
        district_name="Medchal-Malkajgiri",
        district_code="MDCL",
        amfu_or_amfus=(),
        assignment_type=AmfuAssignmentType.PENDING_VERIFICATION,
        bulletin_source="Pending verification against primary IMD GKMS bulletin issue",
        bulletin_date=None,
        source_url=None,
        last_verified_date="2026-11-06",
        evidence_classification="pending_verification",
        discrepancy_notes="No explicit single-district primary bulletin reviewed in current audit. Not inferred from agro-climatic zone.",
    ),
}


def get_district_amfu_assignment(district_name: str) -> DistrictAmfuAssignment:
    """
    Return the AMFU coverage assignment for an individual district.
    Returns pending_verification/unknown for districts not explicitly confirmed by primary evidence.
    Never infers from agro-climatic zone or proximity.
    """
    normalized = district_name.strip() if district_name else ""
    if normalized in DISTRICT_AMFU_ASSIGNMENTS:
        return DISTRICT_AMFU_ASSIGNMENTS[normalized]
    # Check case-insensitive match
    for name, record in DISTRICT_AMFU_ASSIGNMENTS.items():
        if name.lower() == normalized.lower():
            return record

    return DistrictAmfuAssignment(
        district_name=normalized or "Unknown",
        district_code="UNK",
        amfu_or_amfus=(),
        assignment_type=AmfuAssignmentType.UNKNOWN,
        bulletin_source="Unmapped district outside verified Telangana registry",
        bulletin_date=None,
        source_url=None,
        last_verified_date="2026-11-06",
        evidence_classification="unverified",
        discrepancy_notes="District not present in official 33 Telangana revenue districts registry.",
    )


def get_active_amfu_records() -> List[IMDAmfuRecord]:
    """Return only currently active IMD AMFU records."""
    return [a for a in IMD_AMFU_RECORDS if a.status == AmfuStatus.ACTIVE]


def get_historical_damu_records() -> List[IMDAmfuRecord]:
    """Return discontinued historical DAMU records (not active advisory units)."""
    return list(HISTORICAL_DAMU_RECORDS)


# -------------------------------------------------------------------------
# 5. Planning Horizons (decision-support models, NOT weather forecast horizons)
# -------------------------------------------------------------------------
class PlanningHorizon(str, Enum):
    """
    Agricultural planning horizons for KrishiVaani advisory retrieval.
    These are decision-support horizons, NOT meteorological forecast windows.
    Long-range horizons (31-60d) support strategic crop planning, not daily weather prediction.
    """
    SHORT_RANGE_1_7D = "1_7d"       # Immediate field operations (planting, spraying)
    EXTENDED_8_15D = "8_15d"        # Short-term planning (input procurement, irrigation)
    MEDIUM_30D = "16_30d"           # Crop stage planning (variety selection, fertilizer)
    SEASONAL_31_60D = "31_60d"      # Strategic crop planning (land prep, seed sourcing)


PLANNING_HORIZON_DESCRIPTIONS = {
    PlanningHorizon.SHORT_RANGE_1_7D: (
        "Immediate field operations horizon (1-7 days). "
        "Suitable for: sowing decisions, pesticide applications, harvest timing. "
        "Weather data: IMD district-level short-range forecast if available."
    ),
    PlanningHorizon.EXTENDED_8_15D: (
        "Extended planning horizon (8-15 days). "
        "Suitable for: input procurement, irrigation scheduling, field preparation. "
        "Weather data: IMD medium-range guidance; uncertainty increases beyond day 5."
    ),
    PlanningHorizon.MEDIUM_30D: (
        "Medium-term crop stage planning horizon (16-30 days). "
        "Suitable for: crop-stage advisory, fertilizer application timing, variety guidance. "
        "Weather data: Extended range outlooks; use with high uncertainty caution."
    ),
    PlanningHorizon.SEASONAL_31_60D: (
        "Strategic seasonal planning horizon (31-60 days). "
        "Suitable for: land preparation, seed/input sourcing, crop selection. "
        "Note: Deterministic daily weather forecasts at this horizon are not scientifically valid. "
        "Use seasonal normal patterns and strategic contingency planning only."
    ),
}


def get_planning_horizon_description(horizon: PlanningHorizon) -> str:
    """Return the description for a planning horizon."""
    return PLANNING_HORIZON_DESCRIPTIONS.get(horizon, "Unknown planning horizon.")


def classify_planning_horizon(days_ahead: int) -> PlanningHorizon:
    """Classify a number of days ahead into a planning horizon category."""
    if days_ahead <= 7:
        return PlanningHorizon.SHORT_RANGE_1_7D
    elif days_ahead <= 15:
        return PlanningHorizon.EXTENDED_8_15D
    elif days_ahead <= 30:
        return PlanningHorizon.MEDIUM_30D
    else:
        return PlanningHorizon.SEASONAL_31_60D
