"""
Regression tests: POST /api/lab-drafts/generate must be admin-only.

Hardening rationale: the endpoint creates lab drafts in the repository and
dispatches to the configured generation port (currently fake; future: live LLM).
Allowing non-admin learners to call it violates the LabGen Phase 1 boundary:
LLM generation is admin-curated only; readers must never trigger draft creation.
"""

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.static


def _app():
    from backend.main import app
    return app


# ---------------------------------------------------------------------------
# A. Non-admin learner must be rejected with 403
# ---------------------------------------------------------------------------


class TestGenerateEndpointAdminOnly:
    def test_learner_is_rejected_403(self):
        """A regular learner must receive 403 — not 201 or 401."""
        from backend.auth_deps import get_current_user

        app = _app()
        saved = dict(app.dependency_overrides)
        app.dependency_overrides[get_current_user] = lambda: "learner01"
        try:
            client = TestClient(app, raise_server_exceptions=True)
            r = client.post(
                "/api/lab-drafts/generate",
                json={"user_prompt": "Deploy nginx"},
            )
            assert r.status_code == 403, (
                f"Expected 403 for non-admin learner, got {r.status_code}: {r.text}"
            )
        finally:
            app.dependency_overrides.clear()
            app.dependency_overrides.update(saved)

    def test_unauthenticated_is_rejected(self):
        """Request without session token must not reach generation logic."""
        app = _app()
        saved = dict(app.dependency_overrides)
        app.dependency_overrides.clear()
        try:
            client = TestClient(app, raise_server_exceptions=False)
            r = client.post(
                "/api/lab-drafts/generate",
                json={"user_prompt": "Deploy nginx"},
            )
            assert r.status_code in (401, 403), (
                f"Expected 401 or 403 for unauthenticated request, got {r.status_code}"
            )
        finally:
            app.dependency_overrides.clear()
            app.dependency_overrides.update(saved)

    def test_admin_receives_201(self):
        """Admin user must still be able to call the endpoint successfully."""
        from backend.auth_deps import get_current_user
        from backend.labgen.routes import require_admin_user

        app = _app()
        saved = dict(app.dependency_overrides)
        app.dependency_overrides[get_current_user] = lambda: "admin"
        app.dependency_overrides[require_admin_user] = lambda: "admin"
        try:
            client = TestClient(app, raise_server_exceptions=True)
            r = client.post(
                "/api/lab-drafts/generate",
                json={"user_prompt": "Deploy nginx and expose it"},
            )
            assert r.status_code == 201, (
                f"Expected 201 for admin user, got {r.status_code}: {r.text}"
            )
            body = r.json()
            assert body.get("draft_id") is not None
        finally:
            app.dependency_overrides.clear()
            app.dependency_overrides.update(saved)

    def test_learner_rejection_does_not_create_draft(self):
        """403 rejection must not result in any draft being written to the repository."""
        from backend.auth_deps import get_current_user
        from backend.labgen.routes import get_repository

        app = _app()
        saved = dict(app.dependency_overrides)

        from backend.labgen.repository import LabDraftRepository

        class _MemRepo(LabDraftRepository):
            def __init__(self):
                self._store = {}

            def create(self, draft):
                self._store[draft.lab_id] = draft
                return draft

            def get(self, lab_id):
                return self._store.get(lab_id)

            def list_all(self):
                return list(self._store.values())

            def update(self, lab_id, updates):
                pass

            def delete(self, lab_id):
                pass

            def append_review_diff(self, lab_id, diff):
                pass

            def list_diffs(self, lab_id):
                return []

        repo = _MemRepo()
        app.dependency_overrides[get_current_user] = lambda: "learner99"
        app.dependency_overrides[get_repository] = lambda: repo
        try:
            client = TestClient(app, raise_server_exceptions=True)
            r = client.post(
                "/api/lab-drafts/generate",
                json={"user_prompt": "I should not be able to create drafts"},
            )
            assert r.status_code == 403
            assert len(repo._store) == 0, "Draft must not have been written for non-admin"
        finally:
            app.dependency_overrides.clear()
            app.dependency_overrides.update(saved)
