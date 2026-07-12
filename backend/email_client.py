"""
K8S NetLab - Resend transactional email client.

Sends registration verification codes via Resend when RESEND_API_KEY is set.
Falls back gracefully (returns False) when unconfigured or unreachable —
callers must not let a broken/unset email provider block registration.
"""

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

from backend import config
from backend.storage_utils import safe_update_json

logger = logging.getLogger(__name__)

_RESEND_URL = "https://api.resend.com/emails"
_FAILURE_LOG = Path(__file__).parent.parent / "data" / "email_send_failures.json"
_FAILURE_RETENTION_HOURS = 24


def _record_failure(reason: str) -> None:
    """Persist a send failure so /api/health can surface it as an admin alert.

    Best-effort — a broken failure log must not raise into the caller.
    """
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=_FAILURE_RETENTION_HOURS)

    def _update(data: dict) -> dict:
        failures = data.get("failures", [])
        kept = []
        for entry in failures:
            try:
                ts = datetime.fromisoformat(entry["timestamp"])
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
            except (KeyError, ValueError, TypeError):
                continue
            if ts >= cutoff:
                kept.append(entry)
        kept.append({"timestamp": now.isoformat(), "reason": reason})
        data["failures"] = kept
        return data

    try:
        safe_update_json(_FAILURE_LOG, _update)
    except Exception as exc:
        logger.warning("Failed to record email send failure: %s", exc)


async def send_verification_email(to_email: str, code: str) -> bool:
    """
    Send a registration verification code email via Resend.

    Returns True on success, False if unconfigured, unreachable, or rejected.
    Never raises — a broken email provider must not break registration.
    """
    if not config.RESEND_API_KEY:
        return False

    payload = {
        "from": config.RESEND_FROM_EMAIL,
        "to": [to_email],
        "subject": "K8S NetLab 注册验证码",
        "html": (
            f"<p>您的验证码是：<strong>{code}</strong></p>"
            "<p>验证码 15 分钟内有效，请勿泄露给他人。</p>"
        ),
    }
    headers = {
        "Authorization": f"Bearer {config.RESEND_API_KEY}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(_RESEND_URL, headers=headers, json=payload)
    except Exception as exc:
        logger.warning("Resend email send failed (to=%s): %s", to_email, exc)
        _record_failure(f"network_error: {exc}")
        return False

    if resp.status_code not in (200, 201):
        logger.warning("Resend email send: HTTP %s (to=%s)", resp.status_code, to_email)
        _record_failure(f"http_{resp.status_code}")
        return False

    return True
