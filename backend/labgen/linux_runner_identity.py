"""
Resolves and validates the unprivileged OS identity that Linux-domain learner
commands must execute as (LinuxCommandExecutor), instead of inheriting the
root-owned API process's own UID/GID.

Fail-closed: every failure mode raises RunnerIdentityError. There is no
fallback to root — callers (routes.get_linux_runtime_adapter()) must treat a
raised error as "Linux runtime unavailable," not "run as root instead."
"""

from __future__ import annotations

import grp
import os
import pwd
from dataclasses import dataclass


class RunnerIdentityError(RuntimeError):
    def __init__(self, reason: str, message: str) -> None:
        self.reason = reason
        super().__init__(message)


@dataclass(frozen=True)
class RunnerIdentity:
    username: str
    uid: int
    groupname: str
    gid: int


def resolve_runner_identity(username: str, groupname: str) -> RunnerIdentity:
    """Resolve `username`/`groupname` to a validated, non-root RunnerIdentity.

    Raises RunnerIdentityError (never falls back to UID/GID 0) if:
    - the user or group does not exist
    - the resolved UID or GID is 0
    - the user has any supplementary group membership beyond its primary group
    """
    try:
        pw = pwd.getpwnam(username)
    except KeyError as exc:
        raise RunnerIdentityError(
            "runner_user_missing",
            f"Linux sandbox runner user '{username}' does not exist. "
            "Run scripts/install-labgen-linux-runner.sh before enabling the Linux runtime.",
        ) from exc

    try:
        gr = grp.getgrnam(groupname)
    except KeyError as exc:
        raise RunnerIdentityError(
            "runner_group_missing",
            f"Linux sandbox runner group '{groupname}' does not exist.",
        ) from exc

    if pw.pw_uid == 0:
        raise RunnerIdentityError(
            "runner_uid_is_root",
            f"Linux sandbox runner user '{username}' resolved to UID 0 (root). Refusing to use it.",
        )
    if gr.gr_gid == 0:
        raise RunnerIdentityError(
            "runner_gid_is_root",
            f"Linux sandbox runner group '{groupname}' resolved to GID 0 (root). Refusing to use it.",
        )

    supplementary = sorted(g for g in os.getgrouplist(username, gr.gr_gid) if g != gr.gr_gid)
    if supplementary:
        raise RunnerIdentityError(
            "runner_has_supplementary_groups",
            f"Linux sandbox runner user '{username}' has unexpected supplementary "
            f"group memberships: {supplementary}. Refusing to use it.",
        )

    return RunnerIdentity(username=username, uid=pw.pw_uid, groupname=groupname, gid=gr.gr_gid)
