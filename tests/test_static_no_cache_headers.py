"""Regression: Cloudflare edge-cached /js/* for ~4h despite fresh deploys.

Real Human Re-validation for Labs 2-4 v0.1 discovered that a JS bugfix
(commit a924a4c) was deployed to disk but real learners kept getting the
stale file from Cloudflare's edge cache for hours. The fix forces
revalidation via Cache-Control on every static response from origin.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from backend.main import app


def test_js_static_response_has_no_cache_header():
    with TestClient(app) as client:
        resp = client.get("/js/labgenClient.js")
        assert resp.status_code == 200
        assert resp.headers["cache-control"] == "no-cache, must-revalidate"


def test_css_static_response_has_no_cache_header():
    with TestClient(app) as client:
        resp = client.get("/css/app.css")
        assert resp.status_code == 200
        assert resp.headers["cache-control"] == "no-cache, must-revalidate"
