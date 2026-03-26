"""Tests for SSRF prevention in URL ingestion (Phase 0.1)."""

from __future__ import annotations

import pytest

from palaia.ingest import SSRFError, _validate_url


class TestBlockedSchemes:
    """URLs with non-HTTP(S) schemes must be rejected."""

    def test_file_scheme_blocked(self):
        with pytest.raises(SSRFError, match="scheme.*file.*not allowed"):
            _validate_url("file:///etc/passwd")

    def test_ftp_scheme_blocked(self):
        with pytest.raises(SSRFError, match="scheme.*ftp.*not allowed"):
            _validate_url("ftp://example.com/file.txt")

    def test_gopher_scheme_blocked(self):
        with pytest.raises(SSRFError, match="not allowed"):
            _validate_url("gopher://evil.com")

    def test_data_scheme_blocked(self):
        with pytest.raises(SSRFError, match="not allowed"):
            _validate_url("data:text/plain,hello")

    def test_javascript_scheme_blocked(self):
        with pytest.raises(SSRFError, match="not allowed"):
            _validate_url("javascript:alert(1)")


class TestBlockedIPs:
    """Private, loopback, and link-local IPs must be rejected."""

    def test_loopback_blocked(self):
        with pytest.raises(SSRFError, match="blocked address"):
            _validate_url("http://127.0.0.1/")

    def test_loopback_localhost_blocked(self):
        with pytest.raises(SSRFError, match="blocked address"):
            _validate_url("http://localhost/")

    def test_rfc1918_10_blocked(self):
        with pytest.raises(SSRFError, match="blocked address"):
            _validate_url("http://10.0.0.1/")

    def test_rfc1918_172_blocked(self):
        with pytest.raises(SSRFError, match="blocked address"):
            _validate_url("http://172.16.0.1/")

    def test_rfc1918_192_blocked(self):
        with pytest.raises(SSRFError, match="blocked address"):
            _validate_url("http://192.168.1.1/")

    def test_cloud_metadata_blocked(self):
        """AWS/GCP/Azure metadata endpoint must be blocked."""
        with pytest.raises(SSRFError, match="blocked address"):
            _validate_url("http://169.254.169.254/latest/meta-data/")

    def test_link_local_blocked(self):
        with pytest.raises(SSRFError, match="blocked address"):
            _validate_url("http://169.254.1.1/")


class TestAllowedURLs:
    """Public HTTPS URLs must pass validation."""

    def test_https_public_url_allowed(self):
        # Should not raise — public URL
        _validate_url("https://example.com/page.html")

    def test_http_public_url_allowed(self):
        _validate_url("http://example.com/page.html")


class TestAllowPrivateOverride:
    """allow_private=True should bypass IP checks."""

    def test_loopback_allowed_with_flag(self):
        # Should not raise with allow_private=True
        _validate_url("http://127.0.0.1/", allow_private=True)

    def test_private_ip_allowed_with_flag(self):
        _validate_url("http://192.168.1.1/", allow_private=True)

    def test_file_scheme_still_blocked(self):
        """Even with allow_private, file:// must be blocked."""
        with pytest.raises(SSRFError, match="not allowed"):
            _validate_url("file:///etc/passwd", allow_private=True)


class TestEdgeCases:
    """Edge cases in URL validation."""

    def test_no_hostname_rejected(self):
        with pytest.raises(SSRFError, match="no hostname"):
            _validate_url("http://")

    def test_unresolvable_hostname(self):
        with pytest.raises(SSRFError, match="Cannot resolve"):
            _validate_url("http://this-domain-does-not-exist-xyzzy.invalid/")
