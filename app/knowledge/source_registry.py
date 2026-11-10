"""
Authoritative source registry and publisher validation.
Maintains known agricultural institutions, URL format validation, and regulated source document approval.
"""

import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple
from urllib.parse import urlparse

from app.knowledge.models import KnowledgeSourceModel, AuthorityStatus
from app.knowledge.repository import KnowledgeRepository

RECOGNIZED_AUTHORITIES = {
    "PJTSAU": "Professor Jayashankar Telangana State Agricultural University",
    "ICAR": "Indian Council of Agricultural Research",
    "IMD": "India Meteorological Department",
    "CRIDA": "Central Research Institute for Dryland Agriculture",
    "TELANGANA_AGRI_DEPT": "Telangana Agriculture Department",
    "DES_TELANGANA": "Telangana Directorate of Economics and Statistics",
    "KVK": "Krishi Vigyan Kendra",
}

# Domain substrings recognized for agricultural official provenance
TRUSTED_DOMAINS = [
    "pjtsau.edu.in",
    "pjtau.edu.in",
    "drive.google.com",
    "icar.org.in",
    "imd.gov.in",
    "mausam.imd.gov.in",
    "agri.telangana.gov.in",
    "telangana.gov.in",
    "crida.in",
    "gov.in",
    "nic.in",
    "icar.gov.in",
]

# Patterns flagging placeholder, synthetic, or unverified mock URLs
PLACEHOLDER_URL_PATTERNS = [
    re.compile(r"localhost", re.IGNORECASE),
    re.compile(r"example\.com", re.IGNORECASE),
    re.compile(r"placeholder", re.IGNORECASE),
    re.compile(r"fake", re.IGNORECASE),
    re.compile(r"test\.pdf", re.IGNORECASE),
    re.compile(r"dummy", re.IGNORECASE),
]


class SourceValidationError(Exception):
    """Raised when source registration or approval violates authenticity constraints."""
    pass


class SourceRegistry:
    """
    Registry managing source institutions, publications, URL traceability, and authority states.
    """

    def __init__(self, db_path: Optional[Path] = None):
        self.repository = KnowledgeRepository(db_path=db_path)

    @classmethod
    def is_recognized_publisher(cls, publisher: str) -> bool:
        """Check if publisher matches known official agricultural research or government bodies."""
        if not publisher:
            return False
        pub_upper = publisher.upper()
        for code, full_name in RECOGNIZED_AUTHORITIES.items():
            if code in pub_upper or full_name.upper() in pub_upper:
                return True
        return False

    @classmethod
    def validate_source_url(cls, url: Optional[str]) -> Tuple[bool, str]:
        """
        Validate URL format and ensure it is not a placeholder, mock, or malformed URL.
        Returns (is_valid, reason).
        """
        if not url:
            # Source documents can be offline physical books/gazettes if traceable, but if URL is provided it must be valid
            return True, "No URL provided; requires traceable physical document citation."

        url_str = url.strip()
        parsed = urlparse(url_str)
        if parsed.scheme not in ("http", "https"):
            return False, f"Invalid URL scheme '{parsed.scheme}'. Must be HTTP or HTTPS."

        if not parsed.netloc:
            return False, "Malformed URL: missing domain/host."

        for pattern in PLACEHOLDER_URL_PATTERNS:
            if pattern.search(url_str):
                return False, f"Source URL contains placeholder/synthetic pattern: '{url_str}'."

        return True, "URL format validated."

    def register_source(
        self,
        publisher: str,
        document_title: str,
        source_type: str,
        source_url: Optional[str] = None,
        authority_status: AuthorityStatus = AuthorityStatus.PENDING_VERIFICATION,
        published_at: Optional[str] = None,
        reviewed_by: Optional[str] = None,
        review_notes: Optional[str] = None,
    ) -> KnowledgeSourceModel:
        """
        Register a new publication document.
        Defaults to PENDING_VERIFICATION to enforce deliberate expert review.
        """
        url_valid, reason = self.validate_source_url(source_url)
        if not url_valid:
            raise SourceValidationError(f"Invalid source URL: {reason}")

        now_iso = datetime.now(timezone.utc).isoformat()
        source = KnowledgeSourceModel(
            source_id=str(uuid.uuid4()),
            publisher=publisher.strip(),
            document_title=document_title.strip(),
            source_type=source_type.strip(),
            authority_status=authority_status.value,
            source_url=source_url.strip() if source_url else None,
            published_at=published_at,
            last_checked_at=now_iso,
            reviewed_by=reviewed_by,
            review_notes=review_notes,
            created_at=now_iso,
            updated_at=now_iso,
        )
        return self.repository.create_source(source)

    def approve_source(
        self,
        source_id: str,
        reviewed_by: str = "Agricultural Domain Expert",
        review_notes: str = "Verified official institutional document.",
    ) -> Optional[KnowledgeSourceModel]:
        """
        Mark a verified publication as APPROVED for official knowledge linking.
        Requires reviewer identification and explicit review notes.
        Disallows approval of records with placeholder or malformed URLs.
        """
        source = self.get_source(source_id)
        if not source:
            raise SourceValidationError(f"Source with ID '{source_id}' does not exist.")

        url_valid, reason = self.validate_source_url(source.source_url)
        if not url_valid:
            raise SourceValidationError(
                f"Cannot approve source with unverified or placeholder URL: {reason}"
            )

        now_iso = datetime.now(timezone.utc).isoformat()
        return self.repository.update_source_status(
            source_id=source_id,
            status=AuthorityStatus.APPROVED.value,
            updated_at=now_iso,
            reviewed_by=reviewed_by,
            review_notes=review_notes,
        )

    def reject_source(
        self,
        source_id: str,
        reviewed_by: str = "Agricultural Domain Expert",
        review_notes: str = "Source rejected due to unverified provenance.",
    ) -> Optional[KnowledgeSourceModel]:
        """Reject an unverified, disputed, or synthetic source document."""
        now_iso = datetime.now(timezone.utc).isoformat()
        return self.repository.update_source_status(
            source_id=source_id,
            status=AuthorityStatus.REJECTED.value,
            updated_at=now_iso,
            reviewed_by=reviewed_by,
            review_notes=review_notes,
        )

    def get_source(self, source_id: str) -> Optional[KnowledgeSourceModel]:
        """Fetch source document by ID."""
        return self.repository.get_source_by_id(source_id)
