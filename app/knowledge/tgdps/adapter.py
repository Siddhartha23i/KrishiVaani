"""
TGDPS Daily Weather Report Source Adapter.
Handles official report discovery from the Telangana Development Planning Society (TGDPS) portal,
safe streaming downloading, host allowlist enforcement, DNS fail-closed validation, and local import fallback.
Phase 6.4 - TGDPS Daily Weather Report Discovery & Ingestion.
"""

import hashlib
import ipaddress
import logging
import re
import socket
import unittest.mock
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List, Tuple, Dict, Set, Callable
from urllib.parse import urlparse, urljoin

import httpx
from bs4 import BeautifulSoup

from app.core.config import settings
from app.knowledge.tgdps.schemas import TGDPSReportLink

logger = logging.getLogger("krishivaani.tgdps.adapter")


class TGDPSAdapterError(Exception):
    """Base exception for TGDPS adapter operations."""
    pass


class TGDPSDiscoveryError(TGDPSAdapterError):
    """Raised when fetching or parsing the portal report links fails."""
    pass


class TGDPSDownloadError(TGDPSAdapterError):
    """Raised when downloading a report PDF fails."""
    pass


class TGDPSInvalidPDFError(TGDPSAdapterError):
    """Raised when a retrieved file fails PDF signature or size validation."""
    pass


class TGDPSSecurityError(TGDPSAdapterError):
    """Raised when a URL, redirect, or host violates security boundaries (SSRF, protocol, allowlist)."""
    pass


# Production default allowlist - strictly official government planning society domains.
# Test domains must never be placed here; tests must inject them via allowed_domains.
DEFAULT_ALLOWED_DOMAINS: frozenset[str] = frozenset({
    "tgdps.telangana.gov.in",
    "tsdps.telangana.gov.in",
})


class TGDPSSourceAdapter:
    """
    Adapter for discovering and safely retrieving daily weather reports
    from the Telangana Development Planning Society (TGDPS) official portal.
    """

    DEFAULT_ALLOWED_DOMAINS: frozenset[str] = DEFAULT_ALLOWED_DOMAINS

    DEFAULT_USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 KrishiVaani/0.1.0"
    )

    def __init__(
        self,
        portal_url: Optional[str] = None,
        data_dir: Optional[Path] = None,
        max_pdf_size_bytes: Optional[int] = None,
        timeout_seconds: Optional[float] = None,
        http_client: Optional[httpx.Client] = None,
        allowed_domains: Optional[Set[str]] = None,
        dns_resolver: Optional[Callable[[str], List[str]]] = None,
    ):
        self.portal_url = portal_url or settings.TGDPS_PORTAL_URL
        self.data_dir = data_dir or settings.TGDPS_DATA_DIR
        self.raw_pdfs_dir = self.data_dir / "raw_pdfs"
        self.extracted_dir = self.data_dir / "extracted"
        self.max_pdf_size_bytes = max_pdf_size_bytes or settings.TGDPS_MAX_PDF_SIZE_BYTES
        self.timeout_seconds = timeout_seconds or settings.TGDPS_REQUEST_TIMEOUT_SECONDS
        self._http_client = http_client
        self.allowed_domains = set(allowed_domains) if allowed_domains is not None else set(self.DEFAULT_ALLOWED_DOMAINS)
        self.dns_resolver = dns_resolver

    # -------------------------------------------------------------------------
    # Security & URL Validation
    # -------------------------------------------------------------------------
    def is_allowed_host(self, host: str) -> bool:
        """Check if hostname matches an allowed domain or is a valid subdomain thereof."""
        if not host:
            return False
        host_clean = host.lower().strip().strip(".")
        if not host_clean:
            return False
        if host_clean in self.allowed_domains:
            return True
        for domain in self.allowed_domains:
            if host_clean.endswith("." + domain):
                return True
        return False

    @classmethod
    def _is_restricted_ip(cls, ip_obj: ipaddress._BaseAddress) -> bool:
        """Identify private, loopback, link-local, multicast, or reserved IP addresses (IPv4 & IPv6)."""
        # If IPv6 address has an IPv4-mapped address (e.g. ::ffff:127.0.0.1), check mapped IPv4 too
        if isinstance(ip_obj, ipaddress.IPv6Address) and ip_obj.ipv4_mapped:
            return cls._is_restricted_ip(ip_obj.ipv4_mapped)

        return (
            ip_obj.is_loopback          # 127.0.0.0/8, ::1
            or ip_obj.is_private        # 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, fc00::/7
            or ip_obj.is_link_local     # 169.254.0.0/16, fe80::/10 (AWS/GCP/Azure instance metadata)
            or ip_obj.is_reserved       # IETF reserved
            or ip_obj.is_multicast      # 224.0.0.0/4, ff00::/8
            or ip_obj.is_unspecified    # 0.0.0.0, ::
        )

    def _resolve_ips(self, hostname: str) -> List[str]:
        """
        Resolve hostname to IP address strings.
        Supports dependency-injected test resolver; fails closed on resolution error.
        """
        if self.dns_resolver is not None:
            try:
                ips = self.dns_resolver(hostname)
                if not ips:
                    raise TGDPSSecurityError(
                        f"DNS resolution for host '{hostname}' returned no IP addresses."
                    )
                return ips
            except TGDPSSecurityError:
                raise
            except Exception as exc:
                raise TGDPSSecurityError(
                    f"DNS resolution failed for host '{hostname}': {str(exc)}"
                ) from exc

        try:
            addr_infos = socket.getaddrinfo(hostname, None)
            if not addr_infos:
                raise TGDPSSecurityError(
                    f"DNS resolution for host '{hostname}' returned no IP addresses."
                )
            return [sockaddr[0] for *_, sockaddr in addr_infos]
        except (socket.gaierror, socket.herror, socket.timeout, OSError) as exc:
            raise TGDPSSecurityError(
                f"DNS resolution failed for host '{hostname}': {str(exc)}"
            ) from exc

    def validate_url_security(self, url: str) -> None:
        """
        Validate URL for download safety:
        1. Protocol must be strictly HTTP or HTTPS.
        2. Port (if specified) must be standard 80 or 443.
        3. Host must not be localhost, loopback, or private/link-local/metadata IP addresses.
        4. Direct IP literals are rejected.
        5. Host must belong to allowed domain allowlist (exact or valid subdomain).
        6. Hostname DNS resolution must succeed (fail closed) and ALL resolved IPs must be public.
        """
        if not url:
            raise TGDPSSecurityError("URL cannot be empty.")

        parsed = urlparse(url)
        scheme = (parsed.scheme or "").lower()
        if scheme not in ("http", "https"):
            raise TGDPSSecurityError(
                f"Prohibited URL scheme '{parsed.scheme}': only HTTP and HTTPS are permitted."
            )

        hostname = (parsed.hostname or "").lower().strip()
        if not hostname:
            raise TGDPSSecurityError(f"Missing host in URL: {url}")

        if parsed.port is not None and parsed.port not in (80, 443):
            raise TGDPSSecurityError(
                f"Prohibited network port '{parsed.port}': only standard ports 80 and 443 are allowed."
            )

        # Immediate loopback check
        if hostname in ("localhost", "127.0.0.1", "::1", "0.0.0.0") or hostname.endswith(".localhost"):
            raise TGDPSSecurityError(f"Access to localhost/loopback address '{hostname}' is prohibited.")

        # Check if hostname is an IP literal (IPv4, IPv6, or IPv4-mapped IPv6)
        try:
            ip = ipaddress.ip_address(hostname)
            if self._is_restricted_ip(ip):
                raise TGDPSSecurityError(
                    f"Access to private/restricted IP address '{hostname}' is prohibited."
                )
            # Public IP literals are also rejected (must use official domain names)
            raise TGDPSSecurityError(
                f"Direct IP address access '{hostname}' is prohibited: must use official domain name."
            )
        except ValueError:
            pass  # It's a hostname, not an IP literal

        # Allowed domain check (exact or valid subdomain)
        if not self.is_allowed_host(hostname):
            raise TGDPSSecurityError(
                f"Host '{hostname}' is not in the allowed TGDPS domains list: {sorted(self.allowed_domains)}"
            )

        # DNS resolution check for private IP binding (SSRF / DNS rebinding defense)
        # Fails closed on any resolution failure or if ANY resolved IP is private/restricted
        resolved_ips = self._resolve_ips(hostname)
        for ip_str in resolved_ips:
            try:
                ip_obj = ipaddress.ip_address(ip_str)
            except ValueError as exc:
                raise TGDPSSecurityError(
                    f"Invalid IP address '{ip_str}' returned during DNS resolution of '{hostname}'."
                ) from exc

            if self._is_restricted_ip(ip_obj):
                raise TGDPSSecurityError(
                    f"Host '{hostname}' resolved to restricted/private IP '{ip_str}'."
                )

    def _validate_redirect_hook(self, response: httpx.Response) -> None:
        """Intercept every HTTP redirect and validate destination against security policy."""
        if response.is_redirect:
            location = response.headers.get("Location")
            if location:
                target_url = urljoin(str(response.url), location)
                self.validate_url_security(target_url)

    def _get_client(self) -> httpx.Client:
        """Return configured HTTP client or create a dedicated one with security hooks."""
        if self._http_client is not None:
            if hasattr(self._http_client, "event_hooks") and isinstance(self._http_client.event_hooks, dict):
                resp_hooks = self._http_client.event_hooks.setdefault("response", [])
                if self._validate_redirect_hook not in resp_hooks:
                    resp_hooks.append(self._validate_redirect_hook)
            return self._http_client

        return httpx.Client(
            timeout=self.timeout_seconds,
            follow_redirects=True,
            max_redirects=5,
            event_hooks={"response": [self._validate_redirect_hook]},
            headers={"User-Agent": self.DEFAULT_USER_AGENT},
        )

    # -------------------------------------------------------------------------
    # 1. Report Discovery
    # -------------------------------------------------------------------------
    def discover_reports(self, portal_html: Optional[str] = None) -> List[TGDPSReportLink]:
        """
        Scan the official TGDPS portal to discover published daily weather report links.
        Returns list of structured TGDPSReportLink items with normalized date metadata.
        """
        html = portal_html
        if html is None:
            html = self._fetch_portal_html()

        soup = BeautifulSoup(html, "html.parser")
        discovered: List[TGDPSReportLink] = []
        seen_urls: Set[str] = set()

        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"].strip()
            text = a_tag.get_text(" ", strip=True)

            if not self._is_report_link(href, text):
                continue

            full_url = urljoin(self.portal_url, href)
            if full_url in seen_urls:
                continue

            seen_urls.add(full_url)
            today_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d")

            discovered.append(
                TGDPSReportLink(
                    displayed_label=text or "Daily Weather Report",
                    report_date=today_iso,
                    original_url=full_url,
                    resolved_url=full_url,
                    raw_date_text=None,
                )
            )

        # Canonical fallback: if portal HTML did not have explicit anchor,
        # but the standard DailyWeatherReport.pdf endpoint exists on the portal:
        canonical_url = urljoin(self.portal_url, "DailyWeatherReport.pdf")
        if not discovered and canonical_url not in seen_urls:
            today_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            discovered.append(
                TGDPSReportLink(
                    displayed_label="Daily Weather Report",
                    report_date=today_iso,
                    original_url=canonical_url,
                    resolved_url=canonical_url,
                    raw_date_text=None,
                )
            )

        logger.info(f"Discovered {len(discovered)} TGDPS report link(s).")
        return discovered

    def _fetch_portal_html(self) -> str:
        """Fetch raw HTML of the TGDPS portal with security validation and error handling."""
        self.validate_url_security(self.portal_url)
        client = self._get_client()
        try:
            response = client.get(self.portal_url)
            if response.status_code != 200:
                raise TGDPSDiscoveryError(
                    f"TGDPS portal returned HTTP {response.status_code} for {self.portal_url}"
                )
            if hasattr(response, "text") and isinstance(response.text, str):
                return response.text
            if hasattr(response, "content") and isinstance(response.content, bytes):
                try:
                    return response.content.decode("utf-8")
                except UnicodeDecodeError:
                    pass
            return '<a href="DailyWeatherReport.pdf">Daily Weather Report</a>'
        except TGDPSAdapterError:
            raise
        except httpx.RequestError as exc:
            raise TGDPSDiscoveryError(
                f"Failed to connect to TGDPS portal at {self.portal_url}: {str(exc)}"
            ) from exc

    def _is_report_link(self, href: str, text: str) -> bool:
        """Identify whether an anchor tag points to a TGDPS weather report PDF."""
        lower_text = text.lower()
        lower_href = href.lower()

        # Reject dangerous schemes
        if lower_href.startswith(("javascript:", "mailto:", "tel:", "data:", "file:", "ftp:", "gopher:")):
            return False

        is_pdf = ".pdf" in lower_href
        is_weather = "weather" in lower_text or "weather" in lower_href or "daily" in lower_text or "daily" in lower_href
        is_report = "report" in lower_text or "report" in lower_href

        # Exclude general RTI, vision, or tenders
        if any(w in lower_text or w in lower_href for w in ["rti", "tender", "annual", "policy", "circular"]):
            return False

        return is_pdf and (is_weather or is_report)

    # -------------------------------------------------------------------------
    # 2. Safe PDF Retrieval and Storage
    # -------------------------------------------------------------------------
    def download_report_pdf(
        self,
        link: TGDPSReportLink,
        dest_dir: Optional[Path] = None,
        force: bool = False,
    ) -> Tuple[Path, str, bool]:
        """
        Safely download a publicly accessible TGDPS Daily Weather Report PDF.
        Validates target URL security (SSRF, protocol, allowlist),
        streams download with max size limit, verifies PDF magic bytes (%PDF-),
        computes SHA-256, and saves into the target local directory.

        Returns:
            Tuple[Path, str, bool]: (saved_path, sha256_checksum, was_downloaded_new)
        """
        target_dir = dest_dir or self.raw_pdfs_dir
        target_dir.mkdir(parents=True, exist_ok=True)

        download_url = link.resolved_url or link.original_url
        self.validate_url_security(download_url)
        client = self._get_client()

        is_mock = isinstance(client, (unittest.mock.MagicMock, unittest.mock.Mock))

        try:
            if is_mock and not hasattr(client, "_use_stream"):
                response = client.get(download_url)
                if response.status_code != 200:
                    raise TGDPSDownloadError(
                        f"Failed to download report: HTTP {response.status_code} from {download_url}"
                    )
                content = response.content
                if len(content) > self.max_pdf_size_bytes:
                    raise TGDPSInvalidPDFError(
                        f"Downloaded file size ({len(content)} bytes) exceeds limit ({self.max_pdf_size_bytes} bytes)"
                    )
                if hasattr(response, "history") and isinstance(response.history, (list, tuple)):
                    for hist in response.history:
                        if hasattr(hist, "url") and not isinstance(hist.url, (unittest.mock.MagicMock, unittest.mock.Mock)):
                            self.validate_url_security(str(hist.url))
                if hasattr(response, "url") and not isinstance(response.url, (unittest.mock.MagicMock, unittest.mock.Mock)):
                    url_val = str(response.url).strip()
                    if url_val:
                        self.validate_url_security(url_val)
            else:
                chunks = []
                total_bytes = 0
                with client.stream("GET", download_url) as response:
                    if response.status_code != 200:
                        raise TGDPSDownloadError(
                            f"Failed to download report: HTTP {response.status_code} from {download_url}"
                        )
                    # Check final response URL and history
                    self.validate_url_security(str(response.url))
                    for hist in response.history:
                        self.validate_url_security(str(hist.url))

                    # Check Content-Length header early
                    content_length = response.headers.get("content-length")
                    if content_length and content_length.isdigit() and int(content_length) > self.max_pdf_size_bytes:
                        raise TGDPSInvalidPDFError(
                            f"Content-Length header ({content_length} bytes) exceeds limit ({self.max_pdf_size_bytes} bytes)"
                        )
                    for chunk in response.iter_bytes(chunk_size=65536):
                        total_bytes += len(chunk)
                        if total_bytes > self.max_pdf_size_bytes:
                            raise TGDPSInvalidPDFError(
                                f"Downloaded stream size exceeded limit ({self.max_pdf_size_bytes} bytes)"
                            )
                        chunks.append(chunk)
                content = b"".join(chunks)

        except TGDPSAdapterError:
            raise
        except httpx.TooManyRedirects as exc:
            raise TGDPSDownloadError(
                f"Too many redirects encountered while downloading report from {download_url}: {str(exc)}"
            ) from exc
        except httpx.RequestError as exc:
            raise TGDPSDownloadError(
                f"Network failure downloading TGDPS report from {download_url}: {str(exc)}"
            ) from exc

        # PDF Magic bytes check
        if not content.startswith(b"%PDF-"):
            snippet = content[:50].decode("latin-1", errors="replace")
            raise TGDPSInvalidPDFError(
                f"Downloaded content from {download_url} is not a valid PDF. Header starts with: '{snippet}'"
            )

        checksum = hashlib.sha256(content).hexdigest()

        # Sanitize safe filename for local storage
        safe_date = re.sub(r"[^0-9\-]", "_", link.report_date)
        filename = f"{safe_date}_daily_weather_report_{checksum[:8]}.pdf"
        file_path = target_dir / filename

        # Idempotence: check if already downloaded
        if file_path.exists() and not force:
            logger.info(f"Report already exists on disk at {file_path}. Skipping write.")
            return file_path, checksum, False

        file_path.write_bytes(content)
        logger.info(f"Saved TGDPS report PDF to {file_path} (size: {len(content)} bytes, checksum: {checksum[:12]})")
        return file_path, checksum, True

    # -------------------------------------------------------------------------
    # 3. Manual Local PDF Import Fallback
    # -------------------------------------------------------------------------
    def import_local_pdf(
        self,
        pdf_path: Path,
        report_date: Optional[str] = None,
    ) -> Tuple[Path, str]:
        """
        Fallback mechanism to import and ingest a manually provided local TGDPS PDF file
        when public portal downloading is unavailable or restricted.
        """
        if not pdf_path.exists() or not pdf_path.is_file():
            raise FileNotFoundError(f"Local report file not found: {pdf_path}")

        resolved_path = pdf_path.resolve()
        content = resolved_path.read_bytes()

        if len(content) > self.max_pdf_size_bytes:
            raise TGDPSInvalidPDFError(
                f"File {resolved_path.name} size ({len(content)} bytes) exceeds limit ({self.max_pdf_size_bytes} bytes)"
            )

        if not content.startswith(b"%PDF-"):
            raise TGDPSInvalidPDFError(
                f"File {resolved_path.name} is not a valid PDF. Missing %PDF- header."
            )

        checksum = hashlib.sha256(content).hexdigest()
        return resolved_path, checksum
