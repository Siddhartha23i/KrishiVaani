"""
Security test suite for PJTAU document discovery and download pipeline.
Phase 6.3.2 - PJTAU Ingestion Download Security Audit.
Phase 6.3.3 - Production Allowlist Cleanup & DNS/IP Validation Hardening.

Verifies:
1. Production allowlist rejects mock domains (example.com, short.link).
2. Test configuration explicitly allows mock domains via dependency injection.
3. Valid production hosts and legitimate subdomains are accepted.
4. Lookalike hostnames (pjtau.edu.in.attacker.com, fakegoogleusercontent.com) are rejected.
5. SSRF prevention for arbitrary external hosts.
6. Localhost and loopback address blocking.
7. Cloud instance metadata service (169.254.169.254) blocking.
8. RFC 1918 private IP address blocking.
9. Direct IP literals (both public and private) are rejected.
10. All DNS-resolved addresses are checked (not just the first).
11. Mixed public/private DNS results are rejected.
12. IPv4-mapped IPv6 private addresses are rejected (direct literal and via DNS).
13. DNS resolution failures fail closed (socket errors and empty results).
14. Non-standard network port blocking (SSRF port scanning).
15. Unexpected protocol rejection (file://, ftp://, gopher://).
16. Google Drive domain substring bypass prevention (evil-drive.google.com).
17. Redirect destinations validated; redirects to internal or unauthorized hosts blocked.
18. Redirect loop / excessive redirect limit enforcement (max 5 redirects).
19. Stream protection against excessively large downloads (Content-Length and chunk limit).
20. Content verification via magic bytes (%PDF-) rather than file extensions or MIME headers.
21. Legitimate PJTAU and Google Drive downloads operate securely.
22. Archive discovery filters non-HTTP(S) schemes.
"""

import socket
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

import httpx

from app.knowledge.pjtau.adapter import (
    PJTAUSourceAdapter,
    PJTAUSecurityError,
    PJTAUDownloadError,
    PJTAUInvalidPDFError,
    DEFAULT_ALLOWED_DOMAINS,
)
from app.knowledge.pjtau.schemas import PJTAUBulletinLink, BulletinLanguage


class TestPJTAUSecurityAudit(unittest.TestCase):
    """Rigorous defensive security test suite for PJTAU document retrieval."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.temp_dir.name)
        # Standard adapter for tests with hermetic mock DNS resolver returning safe public IP
        self.adapter = PJTAUSourceAdapter(
            data_dir=self.data_dir,
            max_pdf_size_bytes=1024 * 1024,  # 1 MB for testing
            dns_resolver=lambda host: ["93.184.216.34"],
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def _make_link(self, url: str) -> PJTAUBulletinLink:
        """Helper to create a PJTAUBulletinLink for testing."""
        return PJTAUBulletinLink(
            displayed_label="Security Test Bulletin",
            archive_bulletin_number="SEC/01/2026",
            archive_publication_date="2026-11-04",
            language=BulletinLanguage.BILINGUAL,
            original_url=url,
            resolved_url=url,
        )

    # -------------------------------------------------------------------------
    # 1. Production Allowlist & Separation of Test Domains
    # -------------------------------------------------------------------------
    def test_production_allowlist_contains_only_official_domains(self):
        """Production default allowlist contains strictly official university and Google Drive domains."""
        expected_production_domains = {
            "pjtau.edu.in",
            "pjtsau.edu.in",
            "drive.google.com",
            "docs.google.com",
            "googleusercontent.com",
        }
        self.assertEqual(DEFAULT_ALLOWED_DOMAINS, frozenset(expected_production_domains))
        self.assertNotIn("example.com", DEFAULT_ALLOWED_DOMAINS)
        self.assertNotIn("short.link", DEFAULT_ALLOWED_DOMAINS)
        self.assertNotIn("google.com", DEFAULT_ALLOWED_DOMAINS)

    def test_production_allowlist_rejects_mock_domains(self):
        """Default production adapter instance strictly rejects mock/test domains."""
        default_prod_adapter = PJTAUSourceAdapter(data_dir=self.data_dir)
        mock_domain_urls = [
            "https://example.com/test.pdf",
            "https://sub.example.com/advisory.pdf",
            "https://short.link/123",
        ]
        for url in mock_domain_urls:
            with self.subTest(url=url):
                link = self._make_link(url)
                with self.assertRaises(PJTAUSecurityError) as ctx:
                    default_prod_adapter.download_bulletin_pdf(link)
                self.assertIn("not in the allowed PJTAU domains list", str(ctx.exception))

    def test_test_configuration_can_explicitly_inject_mock_domains(self):
        """Test harness can inject test domains via dependency injection without modifying production defaults."""
        test_injected_domains = set(DEFAULT_ALLOWED_DOMAINS) | {"example.com", "short.link"}
        test_adapter = PJTAUSourceAdapter(
            data_dir=self.data_dir,
            allowed_domains=test_injected_domains,
            dns_resolver=lambda h: ["93.184.216.34"],
        )
        # Should validate successfully with injected allowed_domains
        test_adapter.validate_url_security("https://example.com/advisory.pdf")
        test_adapter.validate_url_security("https://short.link/bulletin1")

    # -------------------------------------------------------------------------
    # 2. Domain Boundary & Lookalike Hostname Rejection
    # -------------------------------------------------------------------------
    def test_valid_production_hosts_and_subdomains_accepted(self):
        """Valid production domains and legitimate subdomains pass allowlist check."""
        valid_production_urls = [
            "https://pjtau.edu.in/agromet/bulletin.pdf",
            "https://agromet.pjtau.edu.in/bulletin.pdf",
            "https://pjtsau.edu.in/bulletin.pdf",
            "https://drive.google.com/uc?export=download&id=123",
            "https://docs.google.com/document/d/123",
            "https://doc-0k-6s-docs.googleusercontent.com/download",
        ]
        for url in valid_production_urls:
            with self.subTest(url=url):
                # Should not raise
                self.adapter.validate_url_security(url)

    def test_lookalike_hostnames_rejected(self):
        """Lookalike and suffix-spoofed hostnames must be rejected."""
        lookalike_urls = [
            "https://pjtau.edu.in.attacker.com/advisory.pdf",
            "https://pjtsau.edu.in.phishing.org/bulletin.pdf",
            "https://fakegoogleusercontent.com/bulletin.pdf",
            "https://evilgoogleusercontent.com/bulletin.pdf",
            "https://evil-drive.google.com/bulletin.pdf",
            "https://drive.google.com.attacker.com/bulletin.pdf",
        ]
        for url in lookalike_urls:
            with self.subTest(url=url):
                link = self._make_link(url)
                with self.assertRaises(PJTAUSecurityError) as ctx:
                    self.adapter.download_bulletin_pdf(link)
                self.assertIn("not in the allowed PJTAU domains list", str(ctx.exception))

    # -------------------------------------------------------------------------
    # 3. Arbitrary External Host / SSRF Protection
    # -------------------------------------------------------------------------
    def test_arbitrary_untrusted_host_blocked(self):
        """Discovered URLs on untrusted external domains must be rejected."""
        untrusted_urls = [
            "http://attacker.com/malicious.pdf",
            "https://evil-hacker.org/bulletin.pdf",
            "https://sub.attacker.net/advisory.pdf",
        ]
        for url in untrusted_urls:
            with self.subTest(url=url):
                link = self._make_link(url)
                with self.assertRaises(PJTAUSecurityError) as ctx:
                    self.adapter.download_bulletin_pdf(link)
                self.assertIn("not in the allowed PJTAU domains list", str(ctx.exception))

    # -------------------------------------------------------------------------
    # 4. Localhost and Loopback Protection
    # -------------------------------------------------------------------------
    def test_localhost_and_loopback_blocked(self):
        """Access to localhost and loopback IPv4/IPv6 addresses must be rejected immediately."""
        loopback_urls = [
            "http://localhost/secret.pdf",
            "http://localhost:80/secret.pdf",
            "http://127.0.0.1/bulletin.pdf",
            "http://127.0.0.1:80/bulletin.pdf",
            "http://0.0.0.0/bulletin.pdf",
            "http://[::1]/bulletin.pdf",
            "http://test.localhost/bulletin.pdf",
        ]
        for url in loopback_urls:
            with self.subTest(url=url):
                link = self._make_link(url)
                with self.assertRaises(PJTAUSecurityError) as ctx:
                    self.adapter.download_bulletin_pdf(link)
                self.assertTrue(
                    "loopback" in str(ctx.exception).lower() or "prohibited" in str(ctx.exception).lower()
                )

    # -------------------------------------------------------------------------
    # 5. Cloud Instance Metadata Link-Local Protection (169.254.169.254)
    # -------------------------------------------------------------------------
    def test_cloud_metadata_link_local_ip_blocked(self):
        """Access to AWS/GCP/Azure link-local metadata IP 169.254.169.254 must be blocked."""
        metadata_urls = [
            "http://169.254.169.254/latest/meta-data/",
            "http://169.254.169.254/computeMetadata/v1/",
            "http://169.254.1.1/advisory.pdf",
        ]
        for url in metadata_urls:
            with self.subTest(url=url):
                link = self._make_link(url)
                with self.assertRaises(PJTAUSecurityError) as ctx:
                    self.adapter.download_bulletin_pdf(link)
                self.assertTrue(
                    "private/restricted" in str(ctx.exception).lower() or "prohibited" in str(ctx.exception).lower()
                )

    # -------------------------------------------------------------------------
    # 6. RFC 1918 Private IP Protection
    # -------------------------------------------------------------------------
    def test_private_rfc1918_ips_blocked(self):
        """Access to private internal network IPs (10.x, 172.16.x, 192.168.x) must be blocked."""
        private_urls = [
            "http://10.0.0.1/bulletin.pdf",
            "http://172.16.0.5/bulletin.pdf",
            "http://192.168.1.100/bulletin.pdf",
        ]
        for url in private_urls:
            with self.subTest(url=url):
                link = self._make_link(url)
                with self.assertRaises(PJTAUSecurityError) as ctx:
                    self.adapter.download_bulletin_pdf(link)
                self.assertTrue(
                    "private/restricted" in str(ctx.exception).lower() or "prohibited" in str(ctx.exception).lower()
                )

    # -------------------------------------------------------------------------
    # 7. Direct IP Literal URLs Prohibited
    # -------------------------------------------------------------------------
    def test_direct_public_ip_literals_prohibited(self):
        """Direct public IP literals are prohibited even if public; must use domain name."""
        public_ip_urls = [
            "http://8.8.8.8/advisory.pdf",
            "https://1.1.1.1/bulletin.pdf",
        ]
        for url in public_ip_urls:
            with self.subTest(url=url):
                link = self._make_link(url)
                with self.assertRaises(PJTAUSecurityError) as ctx:
                    self.adapter.download_bulletin_pdf(link)
                self.assertIn("Direct IP address access", str(ctx.exception))

    # -------------------------------------------------------------------------
    # 8. DNS Resolution: Multi-Address & Mixed Public/Private Validation
    # -------------------------------------------------------------------------
    def test_all_dns_resolved_addresses_checked(self):
        """Every DNS-resolved IP address is checked, accepting only when all are public."""
        multi_ip_adapter = PJTAUSourceAdapter(
            data_dir=self.data_dir,
            dns_resolver=lambda h: ["93.184.216.34", "104.20.23.154"],
        )
        # Passes because both resolved IPs are public
        multi_ip_adapter.validate_url_security("https://pjtau.edu.in/bulletin.pdf")

    def test_mixed_public_private_dns_results_rejected(self):
        """If a host resolves to a mix of public and private IPs, the request is rejected."""
        mixed_adapter = PJTAUSourceAdapter(
            data_dir=self.data_dir,
            dns_resolver=lambda h: ["93.184.216.34", "192.168.1.50"],
        )
        with self.assertRaises(PJTAUSecurityError) as ctx:
            mixed_adapter.validate_url_security("https://pjtau.edu.in/bulletin.pdf")
        self.assertIn("resolved to restricted/private IP '192.168.1.50'", str(ctx.exception))

        # Test private IP as first record
        mixed_adapter_first = PJTAUSourceAdapter(
            data_dir=self.data_dir,
            dns_resolver=lambda h: ["10.0.0.1", "93.184.216.34"],
        )
        with self.assertRaises(PJTAUSecurityError) as ctx:
            mixed_adapter_first.validate_url_security("https://pjtau.edu.in/bulletin.pdf")
        self.assertIn("resolved to restricted/private IP '10.0.0.1'", str(ctx.exception))

    # -------------------------------------------------------------------------
    # 9. IPv4-Mapped IPv6 Private Address Validation
    # -------------------------------------------------------------------------
    def test_ipv4_mapped_ipv6_private_addresses_rejected(self):
        """IPv4-mapped IPv6 addresses targeting loopback or private networks are rejected."""
        # A. Direct IPv4-mapped IPv6 literals
        mapped_literal_urls = [
            "http://[::ffff:127.0.0.1]/secret.pdf",
            "http://[::ffff:192.168.1.1]/secret.pdf",
            "http://[::ffff:169.254.169.254]/meta.pdf",
            "http://[::ffff:10.0.0.1]/advisory.pdf",
        ]
        for url in mapped_literal_urls:
            with self.subTest(url=url):
                link = self._make_link(url)
                with self.assertRaises(PJTAUSecurityError) as ctx:
                    self.adapter.download_bulletin_pdf(link)
                self.assertIn("private/restricted", str(ctx.exception).lower())

        # B. IPv4-mapped IPv6 returned via DNS
        mapped_dns_adapter = PJTAUSourceAdapter(
            data_dir=self.data_dir,
            dns_resolver=lambda h: ["::ffff:127.0.0.1"],
        )
        with self.assertRaises(PJTAUSecurityError) as ctx:
            mapped_dns_adapter.validate_url_security("https://pjtau.edu.in/bulletin.pdf")
        self.assertIn("resolved to restricted/private IP '::ffff:127.0.0.1'", str(ctx.exception))

    # -------------------------------------------------------------------------
    # 10. DNS Resolution Fail-Closed Behavior
    # -------------------------------------------------------------------------
    def test_dns_resolution_failure_fails_closed(self):
        """DNS resolution failures (socket.gaierror or empty records) fail closed."""
        def failing_resolver(hostname: str):
            raise socket.gaierror(-2, "Name or service not known")

        fail_adapter = PJTAUSourceAdapter(
            data_dir=self.data_dir,
            dns_resolver=failing_resolver,
        )
        with self.assertRaises(PJTAUSecurityError) as ctx:
            fail_adapter.validate_url_security("https://pjtau.edu.in/bulletin.pdf")
        self.assertIn("DNS resolution failed for host 'pjtau.edu.in'", str(ctx.exception))

        # Empty DNS results
        empty_dns_adapter = PJTAUSourceAdapter(
            data_dir=self.data_dir,
            dns_resolver=lambda h: [],
        )
        with self.assertRaises(PJTAUSecurityError) as ctx:
            empty_dns_adapter.validate_url_security("https://pjtau.edu.in/bulletin.pdf")
        self.assertIn("returned no IP addresses", str(ctx.exception))

    # -------------------------------------------------------------------------
    # 11. Non-Standard Port Restriction (SSRF Port Scanning)
    # -------------------------------------------------------------------------
    def test_non_standard_ports_blocked(self):
        """Requests to non-standard ports (e.g. 22 SSH, 3306 MySQL, 8080) must be rejected."""
        non_standard_port_urls = [
            "http://pjtau.edu.in:22/advisory.pdf",
            "http://pjtau.edu.in:3306/advisory.pdf",
            "https://pjtau.edu.in:8080/advisory.pdf",
        ]
        for url in non_standard_port_urls:
            with self.subTest(url=url):
                link = self._make_link(url)
                with self.assertRaises(PJTAUSecurityError) as ctx:
                    self.adapter.download_bulletin_pdf(link)
                self.assertIn("Prohibited network port", str(ctx.exception))

    # -------------------------------------------------------------------------
    # 12. Unexpected Protocols (file://, ftp://, gopher://)
    # -------------------------------------------------------------------------
    def test_prohibited_protocols_blocked(self):
        """Non-HTTP(S) schemes such as file://, ftp://, gopher:// must be rejected."""
        bad_scheme_urls = [
            "file:///etc/passwd",
            "file:///C:/Windows/win.ini",
            "ftp://pjtau.edu.in/advisory.pdf",
            "gopher://pjtau.edu.in/",
        ]
        for url in bad_scheme_urls:
            with self.subTest(url=url):
                link = self._make_link(url)
                with self.assertRaises(PJTAUSecurityError) as ctx:
                    self.adapter.download_bulletin_pdf(link)
                self.assertIn("Prohibited URL scheme", str(ctx.exception))

    # -------------------------------------------------------------------------
    # 13. Substring Bypass on Google Drive Domain
    # -------------------------------------------------------------------------
    def test_google_drive_substring_domain_bypass_prevented(self):
        """Domains with drive.google.com as a substring or suffix (e.g. evil-drive.google.com) must be rejected."""
        spoofed_urls = [
            "https://evil-drive.google.com/file/d/12345/view",
            "https://drive.google.com.attacker.com/file/d/12345/view",
            "https://notdrive.google.com/uc?export=download&id=12345",
        ]
        for url in spoofed_urls:
            with self.subTest(url=url):
                resolved = PJTAUSourceAdapter.resolve_download_url(url)
                self.assertEqual(resolved, url)

                link = self._make_link(url)
                with self.assertRaises(PJTAUSecurityError):
                    self.adapter.download_bulletin_pdf(link)

    # -------------------------------------------------------------------------
    # 14. Redirect Destination Validation
    # -------------------------------------------------------------------------
    def test_redirect_to_private_ip_or_untrusted_host_blocked(self):
        """HTTP redirects to private IPs or unauthorized hosts must be aborted mid-flight."""
        # Scenario A: Redirect from allowed host to 127.0.0.1
        transport_localhost = httpx.MockTransport(
            lambda req: httpx.Response(302, headers={"Location": "http://127.0.0.1:8000/secret.pdf"})
            if "start" in str(req.url)
            else httpx.Response(200, content=b"forbidden")
        )
        client_a = httpx.Client(
            transport=transport_localhost,
            follow_redirects=True,
            event_hooks={"response": [self.adapter._validate_redirect_hook]},
        )
        adapter_a = PJTAUSourceAdapter(
            data_dir=self.data_dir,
            http_client=client_a,
            dns_resolver=lambda h: ["93.184.216.34"],
        )
        link_a = self._make_link("https://pjtau.edu.in/start")
        with self.assertRaises(PJTAUSecurityError) as ctx:
            adapter_a.download_bulletin_pdf(link_a)
        self.assertTrue("loopback" in str(ctx.exception).lower() or "prohibited" in str(ctx.exception).lower())

        # Scenario B: Redirect to AWS metadata IP 169.254.169.254
        transport_meta = httpx.MockTransport(
            lambda req: httpx.Response(302, headers={"Location": "http://169.254.169.254/latest/meta-data"})
            if "meta_start" in str(req.url)
            else httpx.Response(200, content=b"meta")
        )
        client_b = httpx.Client(
            transport=transport_meta,
            follow_redirects=True,
            event_hooks={"response": [self.adapter._validate_redirect_hook]},
        )
        adapter_b = PJTAUSourceAdapter(
            data_dir=self.data_dir,
            http_client=client_b,
            dns_resolver=lambda h: ["93.184.216.34"],
        )
        link_b = self._make_link("https://pjtau.edu.in/meta_start")
        with self.assertRaises(PJTAUSecurityError) as ctx:
            adapter_b.download_bulletin_pdf(link_b)
        self.assertTrue("private/restricted" in str(ctx.exception).lower() or "prohibited" in str(ctx.exception).lower())

        # Scenario C: Redirect to untrusted external attacker domain
        transport_attacker = httpx.MockTransport(
            lambda req: httpx.Response(302, headers={"Location": "https://attacker.com/malicious.pdf"})
            if "redirect_ext" in str(req.url)
            else httpx.Response(200, content=b"attacker")
        )
        client_c = httpx.Client(
            transport=transport_attacker,
            follow_redirects=True,
            event_hooks={"response": [self.adapter._validate_redirect_hook]},
        )
        adapter_c = PJTAUSourceAdapter(
            data_dir=self.data_dir,
            http_client=client_c,
            dns_resolver=lambda h: ["93.184.216.34"],
        )
        link_c = self._make_link("https://pjtau.edu.in/redirect_ext")
        with self.assertRaises(PJTAUSecurityError) as ctx:
            adapter_c.download_bulletin_pdf(link_c)
        self.assertIn("not in the allowed PJTAU domains list", str(ctx.exception))

    # -------------------------------------------------------------------------
    # 15. Redirect Loop / Excessive Redirect Protection
    # -------------------------------------------------------------------------
    def test_redirect_loop_exhaustion_stopped(self):
        """Redirect chains exceeding 5 hops must be stopped with an explicit error."""
        transport_loop = httpx.MockTransport(
            lambda req: httpx.Response(302, headers={"Location": "https://pjtau.edu.in/loop"})
        )
        client_loop = httpx.Client(
            transport=transport_loop,
            follow_redirects=True,
            max_redirects=5,
            event_hooks={"response": [self.adapter._validate_redirect_hook]},
        )
        adapter_loop = PJTAUSourceAdapter(
            data_dir=self.data_dir,
            http_client=client_loop,
            dns_resolver=lambda h: ["93.184.216.34"],
        )
        link_loop = self._make_link("https://pjtau.edu.in/loop")

        with self.assertRaises(PJTAUDownloadError) as ctx:
            adapter_loop.download_bulletin_pdf(link_loop)
        self.assertIn("Too many redirects", str(ctx.exception))

    # -------------------------------------------------------------------------
    # 16. Large Download DoS Protection (Streaming & Early Header Abort)
    # -------------------------------------------------------------------------
    def test_large_download_aborted_via_content_length(self):
        """Responses advertising Content-Length beyond limit are aborted immediately without downloading body."""
        large_size = 50 * 1024 * 1024  # 50 MB (limit is 1 MB)
        transport = httpx.MockTransport(
            lambda req: httpx.Response(
                200,
                headers={"Content-Length": str(large_size)},
                content=b"%PDF-1.4 header",
            )
        )
        client = httpx.Client(transport=transport)
        adapter = PJTAUSourceAdapter(
            data_dir=self.data_dir,
            max_pdf_size_bytes=1024 * 1024,
            http_client=client,
            dns_resolver=lambda h: ["93.184.216.34"],
        )
        link = self._make_link("https://pjtau.edu.in/large_bulletin.pdf")

        with self.assertRaises(PJTAUInvalidPDFError) as ctx:
            adapter.download_bulletin_pdf(link)
        self.assertIn("Content-Length header", str(ctx.exception))

    def test_large_download_stream_aborted_mid_stream(self):
        """Chunked responses without Content-Length exceeding max_pdf_size_bytes mid-stream are terminated."""
        chunk_data = b"X" * 65536  # 64 KB chunk
        # Generate 20 chunks = 1.3 MB (limit is 1 MB) without Content-Length header (chunked transfer)
        def chunked_handler(req):
            resp = httpx.Response(200, content=chunk_data * 20)
            del resp.headers["content-length"]
            return resp

        transport = httpx.MockTransport(chunked_handler)
        client = httpx.Client(transport=transport)
        adapter = PJTAUSourceAdapter(
            data_dir=self.data_dir,
            max_pdf_size_bytes=1024 * 1024,
            http_client=client,
            dns_resolver=lambda h: ["93.184.216.34"],
        )
        link = self._make_link("https://pjtau.edu.in/stream_oversize.pdf")

        with self.assertRaises(PJTAUInvalidPDFError) as ctx:
            adapter.download_bulletin_pdf(link)
        self.assertIn("stream size exceeded limit", str(ctx.exception))

    # -------------------------------------------------------------------------
    # 17. Content Verification Beyond File Extensions
    # -------------------------------------------------------------------------
    def test_html_error_page_with_pdf_extension_rejected(self):
        """HTML error response disguised as .pdf must fail %PDF- magic bytes check."""
        html_payload = b"<!DOCTYPE html><html><body><h1>404 File Not Found</h1></body></html>"
        transport = httpx.MockTransport(
            lambda req: httpx.Response(200, headers={"Content-Type": "application/pdf"}, content=html_payload)
        )
        client = httpx.Client(transport=transport)
        adapter = PJTAUSourceAdapter(
            data_dir=self.data_dir,
            http_client=client,
            dns_resolver=lambda h: ["93.184.216.34"],
        )
        link = self._make_link("https://pjtau.edu.in/advisory.pdf")

        with self.assertRaises(PJTAUInvalidPDFError) as ctx:
            adapter.download_bulletin_pdf(link)
        self.assertIn("not a valid PDF", str(ctx.exception))

    # -------------------------------------------------------------------------
    # 18. Legitimate Download Operation
    # -------------------------------------------------------------------------
    def test_legitimate_pjtau_and_drive_urls_succeed(self):
        """Legitimate PJTAU bulletin PDF downloads pass all security checks and succeed."""
        valid_pdf = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>%%EOF"
        transport = httpx.MockTransport(
            lambda req: httpx.Response(200, content=valid_pdf)
        )
        client = httpx.Client(transport=transport)
        adapter = PJTAUSourceAdapter(
            data_dir=self.data_dir,
            http_client=client,
            dns_resolver=lambda h: ["93.184.216.34"],
        )

        link_pjtau = PJTAUBulletinLink(
            displayed_label="PJTAU Bulletin",
            archive_bulletin_number="SEC/01/2026",
            archive_publication_date="2026-11-04",
            language=BulletinLanguage.BILINGUAL,
            original_url="https://pjtau.edu.in/bulletin_nov4.pdf",
            resolved_url="https://pjtau.edu.in/bulletin_nov4.pdf",
        )
        path, checksum, downloaded = adapter.download_bulletin_pdf(link_pjtau)
        self.assertTrue(downloaded)
        self.assertTrue(path.exists())

        link_drive = PJTAUBulletinLink(
            displayed_label="Drive Bulletin",
            archive_bulletin_number="SEC/02/2026",
            archive_publication_date="2026-11-04",
            language=BulletinLanguage.BILINGUAL,
            original_url="https://drive.google.com/uc?export=download&id=abc12345",
            resolved_url="https://drive.google.com/uc?export=download&id=abc12345",
        )
        path2, checksum2, downloaded2 = adapter.download_bulletin_pdf(link_drive)
        self.assertTrue(downloaded2)
        self.assertTrue(path2.exists())

    # -------------------------------------------------------------------------
    # 19. Discovery Protocol Filtering
    # -------------------------------------------------------------------------
    def test_discovery_filters_non_http_schemes(self):
        """Archive discovery cleanly skips dangerous links like javascript:, file:, or tel:."""
        malicious_html = """
        <html><body>
          <a href="javascript:alert(1)">Bulletin advisory 04.11.2026.pdf</a>
          <a href="file:///etc/passwd#bulletin.pdf">Bulletin advisory 04.11.2026</a>
          <a href="mailto:admin@pjtau.edu.in">Advisory bulletin question</a>
          <a href="https://pjtau.edu.in/legit_bulletin.pdf">Bulletin no.XXXVII/87/2026, Dated: 04.11.2026</a>
        </body></html>
        """
        discovered = self.adapter.discover_bulletins(archive_html=malicious_html)
        self.assertEqual(len(discovered), 1)
        self.assertEqual(discovered[0].original_url, "https://pjtau.edu.in/legit_bulletin.pdf")


if __name__ == "__main__":
    unittest.main()
