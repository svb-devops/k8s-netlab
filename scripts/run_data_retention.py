#!/usr/bin/env python3
"""run_data_retention.py — CLI entrypoint for DataRetentionService, scheduled
via the k8s-netlab-data-retention systemd timer (see
docs/ops/LIMITED_AVAILABILITY_OPERATING_MODE_v1.0.md).

Defaults to dry-run — pass --execute to actually archive records. Prints a
before/after report and exits non-zero on any archival error so the caller
(systemd, or a human) can tell the run failed without parsing prose output.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.labgen.data_retention import DataRetentionService  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually archive records. Without this flag, runs in dry-run mode (report only, no mutation).",
    )
    args = parser.parse_args()

    svc = DataRetentionService()

    before = svc.report()
    print("=== Before ===")
    print(f"lab_drafts: {before.lab_drafts}")
    print(f"lab_review_diffs: {before.lab_review_diffs}")
    print(f"llm_audit_log: {before.llm_audit_log}")
    print(f"lab_runtime_audit: {before.lab_runtime_audit}")
    print(f"protected_records: {len(before.protected_records)}")

    result = svc.run(dry_run=not args.execute)
    print()
    print(f"=== Run (dry_run={result.dry_run}) ===")
    print(f"lab_drafts_archived: {result.lab_drafts_archived}")
    print(f"lab_review_diffs_archived: {result.lab_review_diffs_archived}")
    print(f"llm_audit_entries_archived: {result.llm_audit_entries_archived}")
    print(f"lab_runtime_entries_archived: {result.lab_runtime_entries_archived}")
    print(f"archive_paths: {result.archive_paths}")

    if result.errors:
        print()
        print("=== Errors ===", file=sys.stderr)
        for err in result.errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    if not args.execute:
        print()
        print("(dry-run — no records were actually archived; pass --execute to apply)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
