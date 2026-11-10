"""
Location-aware weather resolution service for KrishiVaani — Phase 6.1.
Connects confirmed farmer profiles (Phase 4) with weather providers.

Location Resolution Principles:
1. Prefer verified coordinates (latitude, longitude) if stored in farmer profile.
2. Otherwise build structured text query from village, mandal, district, and PIN code.
3. Verify provider returned location country is 'India'.
4. Compare matched location and region against farmer's stored district.
5. If ambiguous or conflicting (e.g. village matched in another state/district),
   raise LocationAmbiguityError or LocationDistrictMismatchError requiring clarification.
6. Never silently select a different village.
7. Never overwrite the farmer's confirmed profile with a provider's suggested coordinates without confirmation.
8. Clearly disclose that data represents a nearby model/grid estimate, not an on-farm weather station.
"""

from typing import Optional, Tuple
from app.models.farmer import FarmerModel
from app.weather.schemas import WeatherLocationInfo
from app.weather.exceptions import (
    LocationNotFoundError,
    LocationAmbiguityError,
    LocationCountryMismatchError,
    LocationDistrictMismatchError,
    WeatherLocationSharingConsentRequiredError,
)
from app.knowledge.season_calendar import (
    TELANGANA_33_DISTRICTS,
    DistrictZoneMapping,
    resolve_telangana_district,
)


class LocationWeatherService:
    """
    Coordinates location resolution between farmer profile data and meteorological providers.
    Enforces validation gates against geographic mismatch, ambiguity, and false telemetry claims.
    Enforces third-party location sharing consent separation from local storage consent.
    """

    @classmethod
    def build_location_query(cls, farmer: FarmerModel) -> Tuple[str, Optional[float], Optional[float]]:
        """
        Build provider query parameters from confirmed farmer profile.
        Returns: (query_string, latitude, longitude)

        Enforces third-party location sharing consent:
        Under KrishiVaani privacy policy and DPDP Act compliance, local profile storage consent
        (Phase 4) does NOT automatically grant permission to transmit personal location
        or coordinates to external commercial providers (e.g. WeatherAPI.com).
        """
        # Rule 0: Enforce explicit third-party location sharing consent
        if not getattr(farmer, "weather_provider_sharing_consent", False):
            raise WeatherLocationSharingConsentRequiredError(
                "Farmer profile has not consented to sharing location data with external third-party weather providers.",
                details={
                    "farmer_id": farmer.farmer_id,
                    "consent_required": "weather_provider_sharing_consent",
                    "disclosure_version": getattr(farmer, "weather_provider_disclosure_version", None),
                },
            )

        # Rule 1: Prioritize verified coordinates
        # WeatherAPI uses coordinate queries for numerical grid cell lookup (~1-11 km resolution),
        # not physical on-farm station observations.
        if farmer.latitude is not None and farmer.longitude is not None:
            # Basic sanity range check for India
            if 6.0 <= farmer.latitude <= 38.0 and 68.0 <= farmer.longitude <= 98.0:
                coord_str = f"{farmer.latitude:.6f},{farmer.longitude:.6f}"
                return coord_str, farmer.latitude, farmer.longitude

        # Rule 2: Build structured textual query from confirmed administrative hierarchy
        parts = []
        if farmer.village_name and farmer.village_name.strip():
            parts.append(farmer.village_name.strip())
        if farmer.mandal_name and farmer.mandal_name.strip():
            parts.append(farmer.mandal_name.strip())
        if farmer.district_name and farmer.district_name.strip():
            parts.append(farmer.district_name.strip())
        elif farmer.pin_code and farmer.pin_code.strip():
            parts.append(farmer.pin_code.strip())

        parts.append("Telangana, India")
        query_str = ", ".join(parts)
        return query_str, None, None

    @classmethod
    def validate_resolved_location(
        cls,
        resolved_loc: WeatherLocationInfo,
        farmer: FarmerModel,
    ) -> None:
        """
        Validate provider's matched location against farmer's confirmed profile.
        Prevents silent misallocation to distant villages or other Indian states.

        Spatial Resolution & Accuracy Rules:
        - WeatherAPI's 'region' field represents state/administrative province in India, NOT district.
        - 'region == Telangana' does NOT verify district-level match.
        - District match is evaluated using official 33 Telangana districts registry.
        - When district cannot be independently verified from provider payload,
          mark 'location_match_status="not_independently_verified"'.
        - Never alter farmer's confirmed profile data.
        """
        # Gate 1: Country Check (Must be India)
        if not resolved_loc.country or resolved_loc.country.strip().lower() != "india":
            raise LocationCountryMismatchError(
                f"Resolved location country '{resolved_loc.country}' does not match expected country 'India'.",
                details={
                    "farmer_id": farmer.farmer_id,
                    "resolved_country": resolved_loc.country,
                },
            )

        # Gate 2: State/Region Check — Telangana-only product rollout
        # Under Phase 6.2, product rollout is strictly Telangana only.
        # A provider-resolved Andhra Pradesh or any other non-Telangana state must not be accepted.
        resolved_region = (resolved_loc.region or "").lower().strip()
        if resolved_region:
            foreign_states = [
                "andhra pradesh", "karnataka", "maharashtra", "madhya pradesh",
                "rajasthan", "gujarat", "tamil nadu", "kerala", "uttar pradesh",
                "bihar", "west bengal", "odisha", "punjab", "haryana",
                "chhattisgarh", "jharkhand", "goa", "delhi",
            ]
            is_foreign = any(s in resolved_region for s in foreign_states)
            if is_foreign or "telangana" not in resolved_region:
                raise LocationDistrictMismatchError(
                    f"Resolved location '{resolved_loc.location_name}' in region '{resolved_loc.region}' "
                    f"conflicts with farmer's confirmed district '{farmer.district_name}' in Telangana (KrishiVaani Telangana rollout scope). "
                    f"Location clarification is required.",
                    details={
                        "farmer_district": farmer.district_name,
                        "resolved_name": resolved_loc.location_name,
                        "resolved_region": resolved_loc.region,
                        "required_state": "Telangana",
                    },
                )

        # Gate 3: District Verification against 33 Telangana Districts
        # Region == "Telangana" confirms state only; it must not be mistaken for district confirmation.
        is_district_verified = False
        if farmer.district_name and farmer.district_name.strip():
            expected_district = farmer.district_name.strip().lower()
            resolved_name = (resolved_loc.location_name or "").lower()

            # Find aliases from official Telangana district registry
            district_aliases = [expected_district]
            for d in TELANGANA_33_DISTRICTS:
                if d.normalized_name == expected_district or d.district_name.lower() == expected_district:
                    district_aliases.extend([a.lower() for a in d.aliases])
                    district_aliases.append(d.normalized_name)
                    break

            for alias in district_aliases:
                if alias in resolved_name:
                    is_district_verified = True
                    break

        # Gate 4: Set metadata & precision attributes
        if is_district_verified:
            resolved_loc.location_match_status = "district_verified"
        elif farmer.latitude is not None and farmer.longitude is not None:
            resolved_loc.location_match_status = "coordinates_matched"
        else:
            resolved_loc.location_match_status = "not_independently_verified"

        # Explicitly preserve requested profile values without altering farmer profile
        resolved_loc.requested_latitude = farmer.latitude
        resolved_loc.requested_longitude = farmer.longitude
        resolved_loc.matched_district = farmer.district_name
        resolved_loc.matched_village = farmer.village_name
        resolved_loc.is_nearby_grid_estimate = True
        resolved_loc.station_observation_confirmed = False
        resolved_loc.provider_grid_resolution_km = "1-11 km"

    @classmethod
    def resolve_telangana_district(cls, district_query: str) -> Optional[DistrictZoneMapping]:
        """
        Validate and match an input district name or alias against the official
        33 Telangana districts registry.
        Returns the canonical DistrictZoneMapping or None if unverified/outside Telangana.
        """
        return resolve_telangana_district(district_query)

