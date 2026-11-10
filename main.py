"""
KrishiVaani - Compatibility Entry Point.

Preserves compatibility with standard command:
    python -m uvicorn main:app --reload --host 127.0.0.1 --port 8000

The core application factory and modular architecture reside inside the `app/` package.
"""

from app.main import app

__all__ = ["app"]
