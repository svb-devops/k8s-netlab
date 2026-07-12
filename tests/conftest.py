"""
Pytest configuration: load .env before any backend module is imported.

config.py reads env vars at module level, so env must be set first.
"""
import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

# Load .env BEFORE any backend module is imported
_env_file = Path(__file__).parent.parent / ".env"
if _env_file.exists():
    load_dotenv(_env_file, override=False)

# Tests must not depend on real secrets from the developer's .env — optional
# integrations default to "disabled" here; tests that specifically exercise
# an enabled integration patch backend.config.* explicitly.
os.environ["RESEND_API_KEY"] = ""


@pytest.fixture(autouse=True)
def _isolate_email_failure_log(tmp_path, monkeypatch):
    """Redirect backend.email_client's failure log to a per-test tmp path.

    Its default path (_FAILURE_LOG) points at the real production
    data/email_send_failures.json. Any test that exercises a
    send_verification_email failure branch without patching this
    explicitly would otherwise write real entries into production data —
    the same class of leak previously seen with RESEND_API_KEY (see git
    history around commit c9ffdfc/aa4c1ca).
    """
    import backend.email_client as _email_client
    monkeypatch.setattr(_email_client, "_FAILURE_LOG", tmp_path / "email_send_failures.json")
