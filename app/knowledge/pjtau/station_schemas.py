"""
Domain schemas and data contracts for PJTAU Research Station Directory,
Profiles, Research Outputs, and Projects.
Category A: Station directory and contacts
Category B: Research-station profiles, mandated crops, and research themes
Category C: Released varieties, research achievements, and technologies developed
Category D: Outreach programmes and research projects
"""

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Optional, List, Dict, Any


class PJTAUZone(str, Enum):
    """PJTAU Agro-Climatic Zones in Telangana."""
    NORTHERN_ZONE = "Northern Telangana Zone"
    CENTRAL_ZONE = "Central Telangana Zone"
    SOUTHERN_ZONE = "Southern Telangana Zone"


class ContactRole(str, Enum):
    """Functional role of the station contact."""
    STATION_HEAD_INCHARGE = "station_head_incharge"
    TRVK_COORDINATOR = "trvk_coordinator"
    GENERAL_OFFICE = "general_office"
    OTHER = "other"


class ContactStatus(str, Enum):
    """Validation status for contact information."""
    OWNER_SELECTED = "OWNER_SELECTED"                    # Selected by project owner from PJTAU station-page
    INDEPENDENTLY_VERIFIED = "INDEPENDENTLY_VERIFIED"    # Independently confirmed against a separate reliable source
    VERIFIED = "VERIFIED"                                # Alias / general verified
    NEEDS_CONFIRMATION = "NEEDS_CONFIRMATION"            # Conflicting sources, requires technical resolution
    UNAVAILABLE = "UNAVAILABLE"                          # Missing from source


class DistrictMappingType(str, Enum):
    """Classification of district-to-research-station referral assignments (Phase 7.7.2)."""
    LOCATED_IN_DISTRICT = "located_in_district"          # Station physically situated within the same district
    PROVISIONAL_DESIGNATED = "provisional_designated"    # Provisional designated referral centre (zone alignment)
    OFFICIALLY_DOCUMENTED = "officially_documented"      # Explicit official jurisdiction order only


@dataclass
class DistrictMappingRecord:
    """Provenance and classification of a district-to-station assignment."""
    district: str
    station_id: str
    station_canonical_name: str
    mapping_type: DistrictMappingType
    assignment_basis: str
    source_url: str

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["mapping_type"] = self.mapping_type.value
        return d


class ResearchOutputType(str, Enum):
    """Classification of research outputs (Category C)."""
    VARIETY_RELEASED = "variety_released"
    HYBRID_DEVELOPED = "hybrid_developed"
    TECHNOLOGY_DEVELOPED = "technology_developed"
    AWARD_RECOGNITION = "award_recognition"
    GENETIC_RESOURCE = "genetic_resource"


class ProjectOutreachType(str, Enum):
    """Classification of projects and outreach activities (Category D)."""
    RESEARCH_PROJECT = "research_project"
    OUTREACH_PROGRAMME = "outreach_programme"


@dataclass
class PJTAUStationContact:
    """Category A: Research station contact record."""
    contact_id: str
    station_id: str
    contact_name: Optional[str]
    designation: Optional[str]
    role: ContactRole
    phone_number: Optional[str]
    official_email: Optional[str]  # Only station-level official email, null for personal
    source_reference: str          # e.g. "PJTAU Zone Page", "RTI Directory"
    contact_status: ContactStatus = ContactStatus.VERIFIED
    is_active_referral: bool = False  # True for owner-selected PJTAU page contact used in referrals
    notes: Optional[str] = None
    created_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["role"] = self.role.value
        d["contact_status"] = self.contact_status.value
        d["is_active_referral"] = self.is_active_referral
        return d


@dataclass
class PJTAUResearchOutput:
    """Category C: Released varieties, research achievements, and developed technologies."""
    output_id: str
    station_id: str
    output_type: ResearchOutputType
    variety_or_technology_name: str
    description: str
    original_source_text: str
    crop_name: Optional[str] = None
    release_year: Optional[str] = None
    release_status: Optional[str] = None  # SVRC, CVRC, pre_released_culture, NBPGR, GI Tag, etc.
    verification_status: str = "pending_verification"
    created_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["output_type"] = self.output_type.value
        return d


@dataclass
class PJTAUProjectOutreach:
    """Category D: Outreach programmes and research projects."""
    item_id: str
    station_id: str
    item_type: ProjectOutreachType
    title: str
    original_source_text: str = ""
    funding_agency: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    is_till_date: bool = False  # Preserves literal "Till date" flag without assuming active
    published_duration_text: Optional[str] = None
    description: Optional[str] = None
    verification_status: str = "pending_verification"
    created_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["item_type"] = self.item_type.value
        return d


@dataclass
class PJTAUResearchStation:
    """
    Categories A & B: Canonical research station profile and directory.
    Stores canonical identity, zone, address, geographic coordinates,
    mandated crops, and research themes.
    """
    station_id: str
    canonical_name: str
    alternate_names: List[str]
    pjtau_zone: PJTAUZone
    address: str
    village: Optional[str]
    mandal: Optional[str]
    district: str
    pin_code: Optional[str]
    latitude: Optional[float]
    longitude: Optional[float]
    coordinates_original_text: Optional[str]
    mandated_crops: List[str]
    research_focus: Optional[str]
    research_themes: List[str]
    infrastructure_facilities: List[str]
    source_url: str
    source_last_updated: str     # Displayed update date on page: e.g. "06/11/2026"
    retrieved_at: str            # Timestamp when data was retrieved: e.g. "2026-11-08T..."
    agro_climatic_descriptor: Optional[str] = None  # e.g. "Semi Arid" for Palem
    met_observatory_details: Optional[str] = None   # e.g. Adilabad observatory specs
    established_year: Optional[str] = None
    total_area_acres: Optional[float] = None
    verification_status: str = "pending_verification"
    contacts: List[PJTAUStationContact] = field(default_factory=list)
    research_outputs: List[PJTAUResearchOutput] = field(default_factory=list)
    projects_and_outreach: List[PJTAUProjectOutreach] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["pjtau_zone"] = self.pjtau_zone.value
        d["contacts"] = [c.to_dict() for c in self.contacts]
        d["research_outputs"] = [o.to_dict() for o in self.research_outputs]
        d["projects_and_outreach"] = [p.to_dict() for p in self.projects_and_outreach]
        return d


@dataclass
class StationReferralResponse:
    """Safe farmer-facing referral response."""
    station_id: Optional[str]
    station_name: Optional[str]
    district: Optional[str]
    contact_phone: Optional[str]
    contact_name: Optional[str]
    contact_designation: Optional[str]
    referral_text: str
    is_fallback: bool
    status: ContactStatus
