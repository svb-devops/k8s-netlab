"""
LabGen named-user invite registry — per-lab controlled invite allowlist.

Design (Controlled Micro Invite, see docs/labgen/LABGEN_CONTROLLED_INVITE_POLICY_v0.1.md):

  LABGEN_ENABLED_LAB_IDS alone is not sufficient to gate access — once a lab_id
  is in that set, ANY authenticated non-admin user is authorized (see
  learner_catalog.py HIGH-001 fix). This registry adds a second, orthogonal
  gate: a lab_id that appears as a key here additionally requires the acting
  username to be listed under it. A lab_id absent from the registry is NOT
  invite-gated — it falls back to the pre-existing LABGEN_ENABLED_LAB_IDS-only
  rule, so core courses (never added to this file) are completely unaffected.

Storage: data/labgen_invites.json (flock-based, same pattern as all other
data/*.json files — gitignored, admin-editable, read fresh on every call so
adding/removing an invite takes effect without a service restart).

Format:
    {"<lab_id>": ["username1", "username2"], ...}

Default (file missing or empty): no lab is invite-gated — safe-by-default,
matches the project's "默认关闭" requirement. No real usernames are ever
hardcoded in source.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List

from backend.storage_utils import safe_read_json

_DEFAULT_PATH = Path("data/labgen_invites.json")


class InviteRegistry:
    """Read-only, per-request-fresh view of data/labgen_invites.json."""

    def __init__(self, path: Path = _DEFAULT_PATH) -> None:
        self._path = path

    def _load(self) -> Dict[str, List[str]]:
        return safe_read_json(self._path, default={})

    def requires_invite(self, lab_id: str) -> bool:
        """True if lab_id is a key in the registry (invite-gated), regardless
        of whether its invite list is currently empty."""
        return lab_id in self._load()

    def is_invited(self, lab_id: str, username: str) -> bool:
        """True if username is listed under lab_id. False if the lab is not
        invite-gated at all — callers must check requires_invite() separately
        to distinguish 'not gated' from 'gated but not on the list'."""
        entry = self._load().get(lab_id, [])
        if not isinstance(entry, list):
            # Malformed value (e.g. a string) would otherwise degrade `in` to
            # substring matching instead of membership — fail closed.
            return False
        return username in entry
