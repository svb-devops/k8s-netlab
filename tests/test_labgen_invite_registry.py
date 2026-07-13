"""Tests for backend/labgen/invite_registry.py."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.labgen.invite_registry import InviteRegistry

pytestmark = pytest.mark.static


class TestInviteRegistry:
    def test_missing_file_requires_invite_false(self, tmp_path: Path) -> None:
        reg = InviteRegistry(path=tmp_path / "nonexistent.json")
        assert reg.requires_invite("any-lab") is False
        assert reg.is_invited("any-lab", "anyone") is False

    def test_empty_file_requires_invite_false(self, tmp_path: Path) -> None:
        p = tmp_path / "invites.json"
        p.write_text("{}")
        reg = InviteRegistry(path=p)
        assert reg.requires_invite("any-lab") is False

    def test_lab_in_registry_requires_invite_true(self, tmp_path: Path) -> None:
        p = tmp_path / "invites.json"
        p.write_text(json.dumps({"lab-1": ["alice"]}))
        reg = InviteRegistry(path=p)
        assert reg.requires_invite("lab-1") is True
        assert reg.requires_invite("lab-2") is False

    def test_lab_in_registry_with_empty_list_requires_invite_true(self, tmp_path: Path) -> None:
        """A key present with an empty list means invite-gated but nobody
        currently invited — everyone (except admin) is denied."""
        p = tmp_path / "invites.json"
        p.write_text(json.dumps({"lab-1": []}))
        reg = InviteRegistry(path=p)
        assert reg.requires_invite("lab-1") is True
        assert reg.is_invited("lab-1", "alice") is False

    def test_is_invited_true_for_listed_username(self, tmp_path: Path) -> None:
        p = tmp_path / "invites.json"
        p.write_text(json.dumps({"lab-1": ["alice", "bob"]}))
        reg = InviteRegistry(path=p)
        assert reg.is_invited("lab-1", "alice") is True
        assert reg.is_invited("lab-1", "bob") is True

    def test_is_invited_false_for_unlisted_username(self, tmp_path: Path) -> None:
        p = tmp_path / "invites.json"
        p.write_text(json.dumps({"lab-1": ["alice"]}))
        reg = InviteRegistry(path=p)
        assert reg.is_invited("lab-1", "stranger") is False

    def test_is_invited_false_for_lab_not_in_registry(self, tmp_path: Path) -> None:
        p = tmp_path / "invites.json"
        p.write_text(json.dumps({"lab-1": ["alice"]}))
        reg = InviteRegistry(path=p)
        assert reg.is_invited("lab-2", "alice") is False

    def test_read_is_fresh_each_call_no_caching(self, tmp_path: Path) -> None:
        """Editing the file must take effect on the next call without
        restarting the service — no in-memory caching."""
        p = tmp_path / "invites.json"
        p.write_text(json.dumps({}))
        reg = InviteRegistry(path=p)
        assert reg.requires_invite("lab-1") is False

        p.write_text(json.dumps({"lab-1": ["alice"]}))
        assert reg.requires_invite("lab-1") is True
        assert reg.is_invited("lab-1", "alice") is True
