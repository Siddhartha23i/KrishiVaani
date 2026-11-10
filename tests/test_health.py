"""
Automated tests for KrishiVaani FastAPI endpoints and entry point.
Uses Python's built-in unittest framework and FastAPI TestClient.
"""

import sys
from pathlib import Path
import unittest

# Ensure the project root is in sys.path when running tests directly
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from fastapi.testclient import TestClient
from app.main import app
import main as root_entrypoint


class TestKrishiVaaniEndpoints(unittest.TestCase):
    """
    Test suite for KrishiVaani foundational routes and configuration.
    """

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_root_endpoint_returns_200(self):
        """Test that GET / returns HTTP 200 and expected payload structure."""
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data.get("application"), "KrishiVaani")
        self.assertEqual(data.get("message"), "Backend is running!")
        self.assertIn("version", data)

    def test_health_endpoint_returns_200(self):
        """Test that GET /health returns HTTP 200."""
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)

    def test_health_endpoint_payload(self):
        """Test that GET /health returns healthy status and stage identifier."""
        response = self.client.get("/health")
        data = response.json()
        self.assertEqual(data.get("status"), "healthy")
        self.assertEqual(data.get("application"), "KrishiVaani")
        self.assertEqual(data.get("stage"), "backend-foundation")
        self.assertIn("version", data)

    def test_root_entrypoint_compatibility(self):
        """Test that root main.py exposes app properly for uvicorn main:app."""
        self.assertTrue(hasattr(root_entrypoint, "app"), "root main.py must expose 'app'")
        root_client = TestClient(root_entrypoint.app)
        response = root_client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json().get("status"), "healthy")


if __name__ == "__main__":
    unittest.main()

