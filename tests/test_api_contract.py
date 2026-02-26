"""Live API contract smoke tests for custard-tidbyt.

Verifies that the custard-calendar Worker API returns the shape that
culvers_fotd.star depends on. A failure here means the Worker API changed
in a way that would silently break the Tidbyt app.

Run:
    pip install pytest requests
    pytest tests/test_api_contract.py -v

These tests make real HTTP requests. They are integration/smoke tests, not
unit tests. Skip them in offline CI by setting SKIP_LIVE_API=1.
"""

from __future__ import annotations

import json
import os
import urllib.request

import pytest

WORKER_BASE = "https://custard.chriskaschner.com"
PRIORITY_SLUG = "mt-horeb"
# Use slug-format query: the Worker's search matches against the slug field directly.
# "mt horeb" with spaces does not match "mt. horeb" (city name has a period),
# but "mt-horeb" matches the slug field verbatim.
STORE_QUERY = "mt-horeb"

# Cloudflare blocks the default Python urllib user-agent; use a neutral one.
_HEADERS = {
    "Accept": "application/json",
    "User-Agent": "custard-tidbyt-smoke-test/1.0",
}

SKIP_LIVE = os.environ.get("SKIP_LIVE_API", "").strip() == "1"
skip_if_offline = pytest.mark.skipif(SKIP_LIVE, reason="SKIP_LIVE_API=1")


def _get(path: str) -> tuple[int, dict]:
    url = f"{WORKER_BASE}{path}"
    req = urllib.request.Request(url, headers=_HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, {}


# ---------------------------------------------------------------------------
# /api/v1/flavors
# ---------------------------------------------------------------------------

class TestFlavorsEndpoint:
    @skip_if_offline
    def test_returns_200(self):
        status, _ = _get(f"/api/v1/flavors?slug={PRIORITY_SLUG}")
        assert status == 200, f"Expected 200, got {status}"

    @skip_if_offline
    def test_has_flavors_array(self):
        _, body = _get(f"/api/v1/flavors?slug={PRIORITY_SLUG}")
        assert "flavors" in body, "Response missing 'flavors' key"
        assert isinstance(body["flavors"], list), "'flavors' must be a list"

    @skip_if_offline
    def test_flavors_have_required_fields(self):
        _, body = _get(f"/api/v1/flavors?slug={PRIORITY_SLUG}")
        flavors = body.get("flavors", [])
        assert len(flavors) > 0, "flavors array is empty"
        for i, f in enumerate(flavors):
            assert "title" in f, f"flavors[{i}] missing 'title'"
            assert "date" in f, f"flavors[{i}] missing 'date'"
            assert isinstance(f["title"], str) and f["title"], \
                f"flavors[{i}].title must be a non-empty string"
            assert isinstance(f["date"], str) and len(f["date"]) == 10, \
                f"flavors[{i}].date must be a YYYY-MM-DD string, got {f.get('date')!r}"

    @skip_if_offline
    def test_flavors_date_format(self):
        """Date must be ISO 8601 YYYY-MM-DD — what the Starlark app compares against."""
        _, body = _get(f"/api/v1/flavors?slug={PRIORITY_SLUG}")
        for i, f in enumerate(body.get("flavors", [])):
            date = f.get("date", "")
            parts = date.split("-")
            assert len(parts) == 3 and len(parts[0]) == 4, \
                f"flavors[{i}].date not YYYY-MM-DD: {date!r}"


# ---------------------------------------------------------------------------
# /api/v1/stores
# ---------------------------------------------------------------------------

class TestStoresEndpoint:
    @skip_if_offline
    def test_returns_200(self):
        status, _ = _get(f"/api/v1/stores?q={STORE_QUERY}")
        assert status == 200, f"Expected 200, got {status}"

    @skip_if_offline
    def test_has_stores_array(self):
        _, body = _get(f"/api/v1/stores?q={STORE_QUERY}")
        assert "stores" in body, "Response missing 'stores' key"
        assert isinstance(body["stores"], list), "'stores' must be a list"

    @skip_if_offline
    def test_stores_have_required_fields(self):
        _, body = _get(f"/api/v1/stores?q={STORE_QUERY}")
        stores = body.get("stores", [])
        assert len(stores) > 0, f"No stores returned for query '{STORE_QUERY}'"
        for i, s in enumerate(stores):
            assert "name" in s, f"stores[{i}] missing 'name'"
            assert "slug" in s, f"stores[{i}] missing 'slug'"
            assert isinstance(s["name"], str) and s["name"], \
                f"stores[{i}].name must be a non-empty string"
            assert isinstance(s["slug"], str) and s["slug"], \
                f"stores[{i}].slug must be a non-empty string"

    @skip_if_offline
    def test_mt_horeb_slug_present(self):
        """Sanity check: querying 'mt horeb' must return the canonical slug."""
        _, body = _get(f"/api/v1/stores?q={STORE_QUERY}")
        slugs = [s.get("slug", "") for s in body.get("stores", [])]
        assert PRIORITY_SLUG in slugs, \
            f"Expected '{PRIORITY_SLUG}' in results, got: {slugs}"


# ---------------------------------------------------------------------------
# API version header
# ---------------------------------------------------------------------------

class TestApiVersionHeader:
    @skip_if_offline
    def test_version_header_present(self):
        """Worker sets API-Version on v1 responses."""
        url = f"{WORKER_BASE}/api/v1/flavors?slug={PRIORITY_SLUG}"
        req = urllib.request.Request(url, headers=_HEADERS)
        with urllib.request.urlopen(req, timeout=15) as resp:
            version = resp.headers.get("API-Version", "")
            assert version, "API-Version header missing from /api/v1/ response"
            assert version == "1", \
                f"Expected API-Version '1', got {version!r}"
