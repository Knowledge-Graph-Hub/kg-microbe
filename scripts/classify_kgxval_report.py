#!/usr/bin/env python3
"""Write a separate finite KGXVal disposition report; never change the graph or input CSV."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kg_microbe.utils.kgm_validation_profile import DEFAULT_PROFILE, classify_kgxval_report  # noqa: E402


def main(argv=None):
    """Classify supplied evidence; exit 2 for review-required and 3 for unregistered cases."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE)
    parser.add_argument("--report-sha256")
    parser.add_argument("--require-reference-cohort", action="store_true")
    parser.add_argument("--graph-archive", type=Path, help="Explicit archive for historical graph-epoch binding")
    parser.add_argument("--output", required=True, type=Path, help="New report file, normally under data/")
    args = parser.parse_args(argv)
    if args.output.exists():
        parser.error("output already exists; keep each review attempt")
    report = classify_kgxval_report(
        args.report,
        profile_path=args.profile,
        expected_report_sha256=args.report_sha256,
        require_reference_cohort=args.require_reference_cohort,
        graph_archive_path=args.graph_archive,
    )
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, sort_keys=True, indent=2)
        stream.write("\n")
    print(f"{report['status']}: {report['csv_records']} CSV records / {report['distinct_diagnostics']} diagnostics")
    if report["unregistered_diagnostics"]:
        return 3
    return 2 if report["review_required_diagnostics"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
