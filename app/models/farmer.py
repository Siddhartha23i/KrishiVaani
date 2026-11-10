"""
Domain model representing a Farmer entity in KrishiVaani.
"""

from dataclasses import dataclass, asdict
from typing import Optional


@dataclass
class FarmerModel:
    """
    Core farmer profile entity.
    Stores personal and location data strictly upon explicit farmer consent.
    """
    farmer_id: str
    preferred_language: str
    village_name: str
    pin_code: str
    location_source: str
    created_at: str
    updated_at: str
    whatsapp_user_id: Optional[str] = None
    mandal_name: Optional[str] = None
    district_name: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    location_confirmed: bool = False
    consent_given: bool = False
    consent_given_at: Optional[str] = None
    # Phase 6.1.1: Separate consent for third-party weather provider location sharing
    weather_provider_sharing_consent: bool = False
    weather_provider_sharing_consent_at: Optional[str] = None
    weather_provider_disclosure_version: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert model instance to dictionary."""
        return asdict(self)

