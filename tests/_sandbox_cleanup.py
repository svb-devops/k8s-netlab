"""Keep the shared Linux sandbox root free of test residue.

Several Linux LabGen test modules must create real workspace directories under
the production-default sandbox root (``/tmp/labgen-linux-sandboxes``) because
``LinuxWorkspaceManager`` enforces that workspaces live under an allowlisted
root (see ``backend/labgen/linux_workspace.py`` ``_ALLOWED_SANDBOX_ROOTS``).
Those helpers historically left directories behind, polluting the exact path
that real learner / pilot sessions use and making any host-side residual scan
impossible to pass.

``purge_test_sandboxes`` removes ONLY directories whose names start with a known
test prefix. Real sessions are named with UUID4 ``session_id`` values and never
match these prefixes, so production / pilot residue is never touched.
"""
from __future__ import annotations

import os
import shutil

# Prefixes used exclusively by test helpers across the Linux LabGen test suite:
#   - "test-" / "test-ws-"  (terminal + rehearsal-bridge helpers)
#   - "learner-test-"        (learner-enablement helper)
#   - "pytest-"              (runtime-adapter-spike helper)
# Real session_ids are UUID4 and never begin with any of these literals.
TEST_SANDBOX_PREFIXES: tuple[str, ...] = (
    "test-",
    "learner-test-",
    "pytest-",
)

DEFAULT_SANDBOX_ROOT = "/tmp/labgen-linux-sandboxes"


def purge_test_sandboxes(
    root: str = DEFAULT_SANDBOX_ROOT,
    prefixes: tuple[str, ...] = TEST_SANDBOX_PREFIXES,
) -> int:
    """Remove test-prefixed workspace directories directly under ``root``.

    Only genuine directories (never symlinks) whose basename starts with one of
    ``prefixes`` are removed. Any other entry — including real UUID-named session
    workspaces — is preserved. Returns the number of directories removed.
    """
    if not os.path.isdir(root):
        return 0
    removed = 0
    for name in os.listdir(root):
        if not name.startswith(prefixes):
            continue
        path = os.path.join(root, name)
        # Never follow symlinks; only remove genuine directories.
        if os.path.islink(path) or not os.path.isdir(path):
            continue
        shutil.rmtree(path, ignore_errors=True)
        if not os.path.exists(path):
            removed += 1
    return removed
