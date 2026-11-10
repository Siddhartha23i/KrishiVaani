"""
Farmer repository for SQLite database operations.
Provides transactional CRUD operations using parameterized queries.
"""

import sqlite3
from pathlib import Path
from typing import Optional
from app.db.database import get_connection
from app.models.farmer import FarmerModel


class FarmerRepository:
    """
    Data access layer for Farmer entity.
    """

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path

    def _row_to_model(self, row: sqlite3.Row) -> FarmerModel:
        row_keys = row.keys()
        return FarmerModel(
            farmer_id=row["farmer_id"],
            whatsapp_user_id=row["whatsapp_user_id"],
            preferred_language=row["preferred_language"],
            village_name=row["village_name"],
            mandal_name=row["mandal_name"],
            district_name=row["district_name"],
            pin_code=row["pin_code"],
            latitude=row["latitude"],
            longitude=row["longitude"],
            location_source=row["location_source"],
            location_confirmed=bool(row["location_confirmed"]),
            consent_given=bool(row["consent_given"]),
            consent_given_at=row["consent_given_at"],
            weather_provider_sharing_consent=bool(row["weather_provider_sharing_consent"]) if "weather_provider_sharing_consent" in row_keys else False,
            weather_provider_sharing_consent_at=row["weather_provider_sharing_consent_at"] if "weather_provider_sharing_consent_at" in row_keys else None,
            weather_provider_disclosure_version=row["weather_provider_disclosure_version"] if "weather_provider_disclosure_version" in row_keys else None,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def create(self, farmer: FarmerModel) -> FarmerModel:
        """
        Insert a new farmer profile.
        Raises sqlite3.IntegrityError if whatsapp_user_id conflicts.
        """
        conn = get_connection(self.db_path)
        try:
            with conn:
                conn.execute(
                    """
                    INSERT INTO farmers (
                        farmer_id, whatsapp_user_id, preferred_language,
                        village_name, mandal_name, district_name, pin_code,
                        latitude, longitude, location_source,
                        location_confirmed, consent_given, consent_given_at,
                        weather_provider_sharing_consent, weather_provider_sharing_consent_at,
                        weather_provider_disclosure_version,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        farmer.farmer_id,
                        farmer.whatsapp_user_id,
                        farmer.preferred_language,
                        farmer.village_name,
                        farmer.mandal_name,
                        farmer.district_name,
                        farmer.pin_code,
                        farmer.latitude,
                        farmer.longitude,
                        farmer.location_source,
                        1 if farmer.location_confirmed else 0,
                        1 if farmer.consent_given else 0,
                        farmer.consent_given_at,
                        1 if farmer.weather_provider_sharing_consent else 0,
                        farmer.weather_provider_sharing_consent_at,
                        farmer.weather_provider_disclosure_version,
                        farmer.created_at,
                        farmer.updated_at,
                    ),
                )
            return farmer
        finally:
            conn.close()

    def get_by_id(self, farmer_id: str) -> Optional[FarmerModel]:
        """Fetch farmer profile by unique internal ID."""
        conn = get_connection(self.db_path)
        try:
            cursor = conn.execute(
                "SELECT * FROM farmers WHERE farmer_id = ?",
                (farmer_id,),
            )
            row = cursor.fetchone()
            return self._row_to_model(row) if row else None
        finally:
            conn.close()

    def get_by_whatsapp_id(self, whatsapp_user_id: str) -> Optional[FarmerModel]:
        """Fetch farmer profile by WhatsApp user identifier."""
        if not whatsapp_user_id:
            return None
        conn = get_connection(self.db_path)
        try:
            cursor = conn.execute(
                "SELECT * FROM farmers WHERE whatsapp_user_id = ?",
                (whatsapp_user_id,),
            )
            row = cursor.fetchone()
            return self._row_to_model(row) if row else None
        finally:
            conn.close()

    def update_location(
        self,
        farmer_id: str,
        village_name: Optional[str],
        mandal_name: Optional[str],
        district_name: Optional[str],
        pin_code: Optional[str],
        latitude: Optional[float],
        longitude: Optional[float],
        location_source: str,
        location_confirmed: bool,
        updated_at: str,
    ) -> Optional[FarmerModel]:
        """
        Update location fields for an existing farmer profile.
        """
        current = self.get_by_id(farmer_id)
        if not current:
            return None

        new_village = village_name if village_name is not None else current.village_name
        new_mandal = mandal_name if mandal_name is not None else current.mandal_name
        new_district = district_name if district_name is not None else current.district_name
        new_pin = pin_code if pin_code is not None else current.pin_code
        new_lat = latitude if latitude is not None else current.latitude
        new_lon = longitude if longitude is not None else current.longitude

        conn = get_connection(self.db_path)
        try:
            with conn:
                conn.execute(
                    """
                    UPDATE farmers
                    SET village_name = ?,
                        mandal_name = ?,
                        district_name = ?,
                        pin_code = ?,
                        latitude = ?,
                        longitude = ?,
                        location_source = ?,
                        location_confirmed = ?,
                        updated_at = ?
                    WHERE farmer_id = ?
                    """,
                    (
                        new_village,
                        new_mandal,
                        new_district,
                        new_pin,
                        new_lat,
                        new_lon,
                        location_source,
                        1 if location_confirmed else 0,
                        updated_at,
                        farmer_id,
                    ),
                )
            return self.get_by_id(farmer_id)
        finally:
            conn.close()

    def update_weather_sharing_consent(
        self,
        farmer_id: str,
        consent_given: bool,
        consent_at: Optional[str],
        disclosure_version: str,
        updated_at: str,
    ) -> Optional[FarmerModel]:
        """
        Record explicit consent decision for third-party weather provider location sharing.
        """
        current = self.get_by_id(farmer_id)
        if not current:
            return None

        conn = get_connection(self.db_path)
        try:
            with conn:
                conn.execute(
                    """
                    UPDATE farmers
                    SET weather_provider_sharing_consent = ?,
                        weather_provider_sharing_consent_at = ?,
                        weather_provider_disclosure_version = ?,
                        updated_at = ?
                    WHERE farmer_id = ?
                    """,
                    (
                        1 if consent_given else 0,
                        consent_at,
                        disclosure_version,
                        updated_at,
                        farmer_id,
                    ),
                )
            return self.get_by_id(farmer_id)
        finally:
            conn.close()

    def delete(self, farmer_id: str) -> bool:
        """
        Permanently remove a farmer's profile and associated personal data.
        Returns True if a record was deleted, False if not found.
        """
        conn = get_connection(self.db_path)
        try:
            with conn:
                cursor = conn.execute(
                    "DELETE FROM farmers WHERE farmer_id = ?",
                    (farmer_id,),
                )
                return cursor.rowcount > 0
        finally:
            conn.close()

