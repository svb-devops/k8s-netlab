"""Regression: Cloudflare edge-cached /js/* for ~4h despite fresh deploys.

Real Human Re-validation for Labs 2-4 v0.1 discovered that a JS bugfix
(commit a924a4c) was deployed to disk but real learners kept getting the
stale file from Cloudflare's edge cache for hours. The original fix set
Cache-Control: "no-cache, must-revalidate" on every static response from
origin — this test suite passed, but the bug still reproduced in production:
owner dogfooding a later feature (2026-07-14) hit the exact same symptom
(a shipped JS change invisible in an already-loaded browser for hours).

Root cause of why the original fix didn't work: confirmed via `curl -I`
through the live domain (not localhost) that Cloudflare's edge was rewriting
the response to "max-age=14400" (its default Browser Cache TTL) regardless of
origin's "no-cache" — "no-cache" still permits caching (it only requires
revalidation before reuse), and Cloudflare's default TTL rule overrides that
weaker directive. This unit test only ever validated the *origin* response
(via TestClient, no Cloudflare in the loop) — it could not, and still cannot,
catch a CDN-layer override. That verification requires a live curl through
the actual domain; see CHANGELOG for the exact commands used to confirm.

"no-store" is a stronger directive (forbids caching outright) that
Cloudflare respects instead of overriding — confirmed live after this
change deployed, the response no longer carries a max-age through Cloudflare.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from backend.main import app


def test_js_static_response_has_no_cache_header():
    with TestClient(app) as client:
        resp = client.get("/js/labgenClient.js")
        assert resp.status_code == 200
        assert resp.headers["cache-control"] == "no-store"


def test_css_static_response_has_no_cache_header():
    with TestClient(app) as client:
        resp = client.get("/css/app.css")
        assert resp.status_code == 200
        assert resp.headers["cache-control"] == "no-store"
