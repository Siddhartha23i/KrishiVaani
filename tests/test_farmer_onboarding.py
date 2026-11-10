"""
Automated test suite for Farmer Onboarding and Location Management (Phase 4).
Tests location preview, normalization, validation, consent enforcement,
profile CRUD operations, and privacy compliance.
"""

import sys
import tempfile
import unittest
from pathlib import Path

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from fastapi.testclient import TestClient
from app.core.config import settings
from app.db.database import init_db, get_connection
from app.main import app
from app.services.location_service import (
    LocationService,
    normalize_and_validate_pin,
    normalize_indic_digits,
)
from app.schemas.farmer import LocationPreviewRequest


class TestFarmerOnboardingSuite(unittest.TestCase):
    """
    Comprehensive test suite for Phase 4 functionality.
    """

    @classmethod
    def setUpClass(cls):
        # Create an isolated temporary SQLite database for testing
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.test_db_path = Path(cls.temp_dir.name) / "test_krishivaani.db"
        cls.original_db_path = settings.DATABASE_PATH
        settings.DATABASE_PATH = cls.test_db_path

        # Initialize test database schema
        init_db(cls.test_db_path)
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        # Restore configuration and cleanup temporary database
        settings.DATABASE_PATH = cls.original_db_path
        cls.temp_dir.cleanup()

    def setUp(self):
        # Clean the farmers table before each test for complete test isolation
        conn = get_connection(self.test_db_path)
        with conn:
            conn.execute("DELETE FROM farmers;")
        conn.close()

    # -------------------------------------------------------------------------
    # 1. Valid village and PIN input
    # -------------------------------------------------------------------------
    def test_01_valid_village_and_pin_input(self):
        """Test preview with valid village and 6-digit PIN code."""
        payload = {
            "village_name": "Kompally",
            "pin_code": "500014",
            "mandal_name": "Medchal",
            "district_name": "Medchal-Malkajgiri",
            "preferred_language": "te-IN",
        }
        response = self.client.post("/api/v1/farmers/onboarding/preview", json=payload)
        self.assertEqual(response.status_code, 200)
        data = response.json()

        self.assertTrue(data["pin_valid"])
        self.assertEqual(data["missing_fields"], [])
        self.assertFalse(data["clarification_required"])
        self.assertTrue(data["ready_for_confirmation"])
        self.assertEqual(data["interpreted_location"]["village_name"], "Kompally")
        self.assertEqual(data["interpreted_location"]["pin_code"], "500014")
        self.assertIn("Kompally", data["location_summary"])

    # -------------------------------------------------------------------------
    # 2. Invalid PIN format
    # -------------------------------------------------------------------------
    def test_02_invalid_pin_format(self):
        """Test that invalid PIN codes (wrong length, non-digits, starting with 0) are rejected."""
        # 5 digits
        norm, valid = normalize_and_validate_pin("50001")
        self.assertFalse(valid)

        # Starts with 0
        norm, valid = normalize_and_validate_pin("012345")
        self.assertFalse(valid)

        # Non-digits
        norm, valid = normalize_and_validate_pin("50001A")
        self.assertFalse(valid)

        # Via API preview
        response = self.client.post(
            "/api/v1/farmers/onboarding/preview",
            json={"village_name": "Kompally", "pin_code": "50001"},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data["pin_valid"])
        self.assertTrue(data["clarification_required"])
        self.assertFalse(data["ready_for_confirmation"])

    # -------------------------------------------------------------------------
    # 3. Missing village information
    # -------------------------------------------------------------------------
    def test_03_missing_village_information(self):
        """Test preview when village name is missing."""
        response = self.client.post(
            "/api/v1/farmers/onboarding/preview",
            json={"pin_code": "500014"},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("village_name", data["missing_fields"])
        self.assertTrue(data["clarification_required"])
        self.assertFalse(data["ready_for_confirmation"])

    # -------------------------------------------------------------------------
    # 4. Missing PIN with insufficient other location details
    # -------------------------------------------------------------------------
    def test_04_missing_pin_insufficient_location(self):
        """Test preview when PIN code is missing and no transcript provides it."""
        response = self.client.post(
            "/api/v1/farmers/onboarding/preview",
            json={"village_name": "Kompally"},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("pin_code", data["missing_fields"])
        self.assertTrue(data["clarification_required"])
        self.assertFalse(data["ready_for_confirmation"])

    # -------------------------------------------------------------------------
    # 5. Telugu numeral normalization
    # -------------------------------------------------------------------------
    def test_05_telugu_numeral_normalization(self):
        """Test Telugu (and Devanagari) numeral conversion to ASCII PIN code."""
        # Telugu numerals: ౫౦౦౦౧౪ -> 500014
        telugu_pin = "౫౦౦౦౧౪"
        normalized = normalize_indic_digits(telugu_pin)
        self.assertEqual(normalized, "500014")

        norm, valid = normalize_and_validate_pin(telugu_pin)
        self.assertTrue(valid)
        self.assertEqual(norm, "500014")

        # In preview payload with space: "౫౦౦ ౦౧౪"
        response = self.client.post(
            "/api/v1/farmers/onboarding/preview",
            json={"village_name": "Kompally", "pin_code": "౫౦౦ ౦౧౪"},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["pin_valid"])
        self.assertEqual(data["interpreted_location"]["pin_code"], "500014")
        self.assertTrue(data["ready_for_confirmation"])

    # -------------------------------------------------------------------------
    # 6. Preview does not persist farmer data
    # -------------------------------------------------------------------------
    def test_06_preview_does_not_persist_data(self):
        """Confirm that preview requests do NOT write anything to the database."""
        response = self.client.post(
            "/api/v1/farmers/onboarding/preview",
            json={"village_name": "Kompally", "pin_code": "500014"},
        )
        self.assertEqual(response.status_code, 200)

        conn = get_connection(self.test_db_path)
        cursor = conn.execute("SELECT COUNT(*) FROM farmers")
        count = cursor.fetchone()[0]
        conn.close()
        self.assertEqual(count, 0, "Preview must not persist any data.")

    # -------------------------------------------------------------------------
    # 7. Profile creation with explicit consent
    # -------------------------------------------------------------------------
    def test_07_profile_creation_with_consent(self):
        """Test successful profile creation when location is confirmed and consent is given."""
        payload = {
            "whatsapp_user_id": "+919876543210",
            "preferred_language": "te-IN",
            "village_name": "Kompally",
            "mandal_name": "Medchal",
            "district_name": "Medchal-Malkajgiri",
            "pin_code": "500014",
            "location_source": "voice_transcript",
            "location_confirmed": True,
            "consent_given": True,
        }
        response = self.client.post("/api/v1/farmers", json=payload)
        self.assertEqual(response.status_code, 201)
        data = response.json()

        self.assertIn("farmer_id", data)
        self.assertEqual(data["village_name"], "Kompally")
        self.assertEqual(data["pin_code"], "500014")
        self.assertTrue(data["location_confirmed"])
        self.assertTrue(data["consent_given"])
        self.assertIsNotNone(data["consent_given_at"])

        # Verify record exists in SQLite
        conn = get_connection(self.test_db_path)
        cursor = conn.execute("SELECT * FROM farmers WHERE farmer_id = ?", (data["farmer_id"],))
        row = cursor.fetchone()
        conn.close()
        self.assertIsNotNone(row)
        self.assertEqual(row["village_name"], "Kompally")

    # -------------------------------------------------------------------------
    # 8. Profile creation without consent is rejected
    # -------------------------------------------------------------------------
    def test_08_profile_creation_without_consent_rejected(self):
        """Test that profile creation fails if consent_given is False."""
        payload = {
            "village_name": "Kompally",
            "pin_code": "500014",
            "location_confirmed": True,
            "consent_given": False,
        }
        response = self.client.post("/api/v1/farmers", json=payload)
        self.assertEqual(response.status_code, 400)
        self.assertIn("consent is required", response.json()["detail"].lower())

    # -------------------------------------------------------------------------
    # 9. Profile creation without location confirmation is rejected
    # -------------------------------------------------------------------------
    def test_09_profile_creation_without_confirmation_rejected(self):
        """Test that profile creation fails if location_confirmed is False."""
        payload = {
            "village_name": "Kompally",
            "pin_code": "500014",
            "location_confirmed": False,
            "consent_given": True,
        }
        response = self.client.post("/api/v1/farmers", json=payload)
        self.assertEqual(response.status_code, 400)
        self.assertIn("must confirm", response.json()["detail"].lower())

    # -------------------------------------------------------------------------
    # 10. Farmer profile retrieval
    # -------------------------------------------------------------------------
    def test_10_farmer_profile_retrieval(self):
        """Test GET /api/v1/farmers/{farmer_id} retrieves accurate data."""
        # Create profile
        create_res = self.client.post(
            "/api/v1/farmers",
            json={
                "village_name": "Gajwel",
                "pin_code": "502278",
                "location_confirmed": True,
                "consent_given": True,
            },
        )
        self.assertEqual(create_res.status_code, 201)
        farmer_id = create_res.json()["farmer_id"]

        # Fetch profile
        get_res = self.client.get(f"/api/v1/farmers/{farmer_id}")
        self.assertEqual(get_res.status_code, 200)
        self.assertEqual(get_res.json()["village_name"], "Gajwel")
        self.assertEqual(get_res.json()["pin_code"], "502278")

    # -------------------------------------------------------------------------
    # 11. Farmer location update
    # -------------------------------------------------------------------------
    def test_11_farmer_location_update(self):
        """Test PATCH /api/v1/farmers/{farmer_id}/location updates location fields."""
        # Create profile
        create_res = self.client.post(
            "/api/v1/farmers",
            json={
                "village_name": "OldVillage",
                "pin_code": "500001",
                "location_confirmed": True,
                "consent_given": True,
            },
        )
        farmer_id = create_res.json()["farmer_id"]
        original_created_at = create_res.json()["created_at"]

        # Update location
        update_res = self.client.patch(
            f"/api/v1/farmers/{farmer_id}/location",
            json={
                "village_name": "NewVillage",
                "pin_code": "500014",
                "location_confirmed": True,
            },
        )
        self.assertEqual(update_res.status_code, 200)
        updated_data = update_res.json()
        self.assertEqual(updated_data["village_name"], "NewVillage")
        self.assertEqual(updated_data["pin_code"], "500014")
        self.assertEqual(updated_data["created_at"], original_created_at)

    # -------------------------------------------------------------------------
    # 12. Duplicate WhatsApp identifier handling
    # -------------------------------------------------------------------------
    def test_12_duplicate_whatsapp_id_handling(self):
        """Test that registering a duplicate WhatsApp ID returns HTTP 409 Conflict."""
        payload1 = {
            "whatsapp_user_id": "+919999988888",
            "village_name": "VillageOne",
            "pin_code": "500014",
            "location_confirmed": True,
            "consent_given": True,
        }
        res1 = self.client.post("/api/v1/farmers", json=payload1)
        self.assertEqual(res1.status_code, 201)

        # Attempt to insert identical WhatsApp ID
        payload2 = {
            "whatsapp_user_id": "+919999988888",
            "village_name": "VillageTwo",
            "pin_code": "500020",
            "location_confirmed": True,
            "consent_given": True,
        }
        res2 = self.client.post("/api/v1/farmers", json=payload2)
        self.assertEqual(res2.status_code, 409)
        self.assertIn("already exists", res2.json()["detail"].lower())

    # -------------------------------------------------------------------------
    # 13. Farmer profile deletion
    # -------------------------------------------------------------------------
    def test_13_farmer_profile_deletion(self):
        """Test privacy-compliant deletion of a farmer profile."""
        create_res = self.client.post(
            "/api/v1/farmers",
            json={
                "village_name": "TemporaryVillage",
                "pin_code": "500014",
                "location_confirmed": True,
                "consent_given": True,
            },
        )
        farmer_id = create_res.json()["farmer_id"]

        # Delete profile
        delete_res = self.client.delete(f"/api/v1/farmers/{farmer_id}")
        self.assertEqual(delete_res.status_code, 200)

        # Confirm subsequent GET returns 404
        get_res = self.client.get(f"/api/v1/farmers/{farmer_id}")
        self.assertEqual(get_res.status_code, 404)

        # Confirm non-existent delete returns 404
        delete_again = self.client.delete(f"/api/v1/farmers/{farmer_id}")
        self.assertEqual(delete_again.status_code, 404)

    # -------------------------------------------------------------------------
    # 14. Existing root and health endpoints still pass
    # -------------------------------------------------------------------------
    def test_14_existing_endpoints_pass(self):
        """Confirm that Phase 3 foundational endpoints remain fully functional."""
        root_res = self.client.get("/")
        self.assertEqual(root_res.status_code, 200)
        self.assertEqual(root_res.json()["application"], "KrishiVaani")

        health_res = self.client.get("/health")
        self.assertEqual(health_res.status_code, 200)
        self.assertEqual(health_res.json()["status"], "healthy")


if __name__ == "__main__":
    unittest.main()

