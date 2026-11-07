"""
Preserve and compare the exact October baseline for the approved 2026-11-05 rebuild.

Only ``preserve`` copies the three named original artifacts into new task evidence.
``compare`` streams graph counts and attribution distributions, and reuses the existing
MediaDive ingredient coverage checker without updating its committed baseline.
These descriptive differences do not grant source, scientific or release admission.
"""

import argparse
import codecs
import csv
import gzip
import json
import shutil
import subprocess
import sys
import tarfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ORIGINAL = ROOT.parent / "kg-microbe"
EVIDENCE = ROOT / "data/rebuild-evidence/20261105"
BASELINE = EVIDENCE / "october-baseline"
FILES = (
    "data/transformed/mediadive/edges.tsv",
    "data/merged/merged-kg.tar.gz",
    "merged_graph_stats.yaml",
)
ATTRIBUTION = ("provided_by", "primary_knowledge_source", "knowledge_source")


def require(condition, message):
    """Reject incomplete preservation or ambiguous comparison inputs."""
    if not condition:
        raise ValueError(message)


def unlinked(path):
    """Reject symbolic links in an artifact's entire lexical locator."""
    path = Path(path).absolute()
    require(not any(item.is_symlink() for item in (path, *path.parents)), f"Linked locator: {path}")
    return path.resolve()


def save(path, value):
    """Create a new evidence record without replacing any previous record."""
    path = unlinked(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")


def preserve(original=ORIGINAL, baseline=BASELINE):
    """Copy only the three exact originals, with independent inodes and full before/after guards."""
    from kg_microbe.merge_utils.source_admission import SourceAdmission

    original, baseline = unlinked(original), unlinked(baseline)
    require(original.is_dir() and not original.is_relative_to(ROOT), "Wrong original checkout")
    require(baseline.is_relative_to(EVIDENCE), "Baseline must remain in rebuild evidence")
    guard = SourceAdmission()
    helper = {"path": str(Path(__file__).resolve()), **guard.capture(Path(__file__).resolve())}
    expected = {relative: guard.capture(unlinked(original / relative)) for relative in FILES}
    baseline.mkdir(parents=True, exist_ok=False)
    record = {
        "schema_version": 1,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "status": "preserving",
        "helper": helper,
        "files": {},
    }
    try:
        for relative in FILES:
            source, target = original / relative, baseline / "original" / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            unlinked(target.parent)
            with source.open("rb") as incoming, target.open("xb") as outgoing:
                shutil.copyfileobj(incoming, outgoing, length=1024 * 1024)
            actual = guard.capture(unlinked(target))
            require(actual == expected[relative], f"Copied bytes differ: {relative}")
            require(target.stat().st_nlink == 1, f"Baseline copy has shared links: {relative}")
            require(
                (source.stat().st_dev, source.stat().st_ino) != (target.stat().st_dev, target.stat().st_ino),
                f"Baseline copy shares original inode: {relative}",
            )
            record["files"][relative] = {
                "original": {"path": str(source), **expected[relative]},
                "copy": {"path": str(target), **actual},
            }
        guard.verify()
        record["status"] = "preserved"
        save(baseline / "preservation.json", record)
    except BaseException as error:
        record.update(status="failed", error=f"{type(error).__name__}: {error}")
        save(baseline / "preservation-failed.json", record)
        raise
    return record


def baseline_inputs(guard, original=ORIGINAL, baseline=BASELINE):
    """Require both independent copies and exact original locators to retain preserved bytes."""
    record = guard.read_json(unlinked(baseline / "preservation.json"))
    require(
        record.get("status") == "preserved" and set(record.get("files", {})) == set(FILES),
        "Incomplete October preservation",
    )
    paths = {}
    for relative in FILES:
        entry = record["files"][relative]
        for kind, path in (("original", original / relative), ("copy", baseline / "original" / relative)):
            path = unlinked(path)
            require(entry[kind]["path"] == str(path), f"Preserved {kind} locator differs: {relative}")
            require(
                guard.capture(path) == {key: entry[kind][key] for key in ("bytes", "sha256")},
                f"Preserved {kind} changed: {relative}",
            )
        copy, source = baseline / "original" / relative, original / relative
        require(
            copy.stat().st_nlink == 1
            and (copy.stat().st_dev, copy.stat().st_ino) != (source.stat().st_dev, source.stat().st_ino),
            f"Baseline copy lost independence: {relative}",
        )
        paths[relative] = copy
    return paths


def distribution(stream, kind):
    """Count literal TSV rows and distinct pipe-separated memberships without retaining graph rows."""
    reader = csv.DictReader(codecs.iterdecode(stream, "utf-8"), delimiter="\t", quoting=csv.QUOTE_NONE)
    header = reader.fieldnames or []
    required = {"id", "category"} if kind == "nodes" else {"subject", "predicate", "object"}
    require(required <= set(header) and len(set(header)) == len(header), f"Malformed {kind} header")
    primary = "category" if kind == "nodes" else "predicate"
    fields = [primary, *(field for field in ATTRIBUTION if field in header)]
    counts = {field: Counter() for field in fields}
    missing = Counter()
    total = 0
    for row in reader:
        require(
            set(row) == set(header) and all(isinstance(value, str) for value in row.values()), f"Ragged {kind} TSV row"
        )
        total += 1
        for field in fields:
            values = set(row[field].split("|")) - {""} if field != "predicate" else {row[field]} - {""}
            if not values:
                missing[field] += 1
            counts[field].update(values)
    return {
        "rows": total,
        "header": header,
        "field_memberships": {field: dict(values) for field, values in counts.items()},
        "missing_field_rows": dict(missing),
        "absent_attribution_columns": [field for field in ATTRIBUTION if field not in header],
    }


def archive_counts(path, guard, *, legacy=False):
    """Reuse production integrity inspection, then stream the actual node/edge members."""
    from kg_microbe.utils.postprocess_artifacts import inspect_artifact

    path = unlinked(path)
    expected = guard.capture(path)
    status = inspect_artifact(path)
    require(status.status in ({"ok", "unverified"} if legacy else {"ok"}), status.detail)
    require(status.archive_sha256 == expected["sha256"], "Archive changed during integrity inspection")
    chosen = {}
    for kind in ("nodes", "edges"):
        matches = [name for name in status.members if name.endswith("_" + kind + ".tsv")]
        require(len(matches) == 1, f"Ambiguous archive {kind} member")
        chosen[matches[0]] = kind
    graphs = {}
    with gzip.open(path, "rb") as compressed:
        with tarfile.open(fileobj=compressed, mode="r|") as archive:
            for member in archive:
                if member.name in chosen:
                    kind = chosen[member.name]
                    with archive.extractfile(member) as stream:
                        graphs[kind] = distribution(stream, kind)
                    require(
                        graphs[kind]["rows"] == status.members[member.name]["rows"],
                        f"Physical/parsed row count differs: {member.name}",
                    )
                    graphs[kind]["member"] = {"name": member.name, **status.members[member.name]}
        while compressed.read(1024 * 1024):
            pass
    require(set(graphs) == {"nodes", "edges"}, "Missing streamed graph pair")
    return {
        "path": str(path),
        **expected,
        "integrity_status": status.status,
        "integrity_detail": status.detail,
        "graphs": graphs,
    }


def deltas(previous, current):
    """Retain every changed key, including additions and removals."""
    return {
        key: {
            "old": previous.get(key, 0),
            "new": current.get(key, 0),
            "delta": current.get(key, 0) - previous.get(key, 0),
        }
        for key in sorted(set(previous) | set(current))
        if previous.get(key, 0) != current.get(key, 0)
    }


def compare(*, original=ORIGINAL, baseline=BASELINE):
    """Compare actual artifacts while keeping every read bound through the completed report."""
    import yaml

    from kg_microbe.merge_utils.source_admission import SourceAdmission
    from scripts import mediadive_coverage_check as coverage

    guard = SourceAdmission()
    guard.capture(Path(__file__).resolve())
    old = baseline_inputs(guard, original=original, baseline=baseline)
    new = {relative: unlinked(ROOT / relative) for relative in FILES}
    for path in new.values():
        guard.capture(path)
    checker = ROOT / "scripts/mediadive_coverage_check.py"
    require(Path(coverage.__file__).resolve() == checker, "Wrong coverage checker module origin")
    guard.capture(checker)
    guard.capture(ROOT / "scripts/mediadive_coverage_baseline.json")
    before = archive_counts(old[FILES[1]], guard, legacy=True)
    after = archive_counts(new[FILES[1]], guard)
    ingredients = {"old": coverage.ingredient_counts(old[FILES[0]]), "new": coverage.ingredient_counts(new[FILES[0]])}
    command = [
        str(ROOT / ".venv/bin/python"),
        "-B",
        str(checker),
        "--edges",
        str(new[FILES[0]]),
        "--compare",
        str(old[FILES[0]]),
        "--tolerance",
        "5",
    ]
    checked = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)  # noqa: S603 - exact local read-only checker, no shell
    previous_total, current_total = (sum(ingredients[label].values()) for label in ("old", "new"))
    percentage = 100 * (current_total - previous_total) / previous_total
    expected_exit = int(abs(percentage) > 5)
    expected_text = "FAIL: coverage " if expected_exit else "OK: within "
    require(
        checked.returncode == expected_exit and not checked.stderr and expected_text in checked.stdout,
        "Coverage checker did not complete with its documented comparison result",
    )
    graphs = {}
    for kind in ("nodes", "edges"):
        a, b = before["graphs"][kind], after["graphs"][kind]
        fields = set(a["field_memberships"]) | set(b["field_memberships"])
        graphs[kind] = {
            "old_rows": a["rows"],
            "new_rows": b["rows"],
            "row_delta": b["rows"] - a["rows"],
            "field_membership_deltas": {
                field: deltas(a["field_memberships"].get(field, {}), b["field_memberships"].get(field, {}))
                for field in sorted(fields)
            },
            "missing_field_row_deltas": deltas(a["missing_field_rows"], b["missing_field_rows"]),
        }
    reported_stats = {}
    for label, path in (("old", old[FILES[2]]), ("new", new[FILES[2]])):
        require(path.stat().st_size <= 2 * 1024 * 1024, "Stats metadata exceeds bounded limit")
        payload = yaml.safe_load(guard.capture(path, retain=True))
        reported_stats[label] = {
            "path": str(path),
            **guard.capture(path),
            "reported_nodes": payload.get("node_stats", {}).get("total_nodes"),
            "reported_edges": payload.get("edge_stats", {}).get("total_edges"),
        }
    guard.verify()
    return {
        "status": "compared",
        "old_archive": before,
        "new_archive": after,
        "graph_deltas": graphs,
        "ingredient_counts": ingredients,
        "ingredient_deltas": deltas(ingredients["old"], ingredients["new"]),
        "ingredient_summary": {
            "old_total": previous_total,
            "new_total": current_total,
            "delta": current_total - previous_total,
            "percentage_change": percentage,
            "old_solution_count": len(ingredients["old"]),
            "new_solution_count": len(ingredients["new"]),
        },
        "coverage_checker": {
            "command": command,
            "exit_code": checked.returncode,
            "within_five_percent_tolerance": checked.returncode == 0,
            "stdout": checked.stdout,
            "stderr": checked.stderr,
            "identity": guard.capture(checker),
        },
        "reported_stats_not_admission": reported_stats,
        "inputs": {str(path): value for path, value in guard.identities.items()},
        "interpretation": (
            "Descriptive actual-row comparison only. Source attribution counts are not source completeness. "
            "Category/source multi-values count distinct pipe-separated memberships per row; predicates retain "
            "literal values. The existing ingredient checker normalizes solution prefixes and excludes nested "
            "solution references. Coverage movement in either direction requires review, and passing tolerance "
            "grants no semantic admission. Original stats and legacy manifest absence are historical evidence; "
            "current production admission and archive qualification gates remain authoritative."
        ),
    }


def main(argv=None):
    """Run only the explicitly selected preservation or descriptive comparison action."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("preserve", "compare"))
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--original-checkout", type=Path, help="Explicit preserved comparison checkout.")
    parser.add_argument(
        "--baseline-directory", type=Path, help="New/existing preservation directory under task evidence."
    )
    args = parser.parse_args(argv)
    require(Path.cwd().resolve() == ROOT, "Run from the owned helper worktree")
    receipt = unlinked(args.receipt)
    require(receipt.is_relative_to(EVIDENCE) and not receipt.exists(), "Use a new task evidence receipt")
    require(bool(args.original_checkout) == bool(args.baseline_directory), "Supply both explicit baseline locators")
    original = unlinked(args.original_checkout or ORIGINAL)
    baseline = unlinked(args.baseline_directory or BASELINE)
    require(original.is_dir() and not original.is_relative_to(ROOT), "Wrong original comparison checkout")
    require(baseline.is_relative_to(EVIDENCE), "Baseline must remain in rebuild evidence")
    require(receipt != baseline / "preservation.json", "Preservation manifest is reserved")
    sys.path.insert(0, str(ROOT))
    result = {"command": args.command, "checked_at": datetime.now(timezone.utc).isoformat(), "root": str(ROOT)}
    try:
        result["result"] = (
            preserve(original=original, baseline=baseline)
            if args.command == "preserve"
            else compare(original=original, baseline=baseline)
        )
        result["status"] = result["result"]["status"]
    except (Exception, SystemExit) as error:  # noqa: BLE001 - preserve failures without accepting or restamping inputs
        result.update(status="failed", error=f"{type(error).__name__}: {error}")
    save(receipt, result)
    print(
        json.dumps({"status": result["status"], "receipt": str(receipt), "error": result.get("error")}, sort_keys=True)
    )
    return int(result["status"] == "failed")


if __name__ == "__main__":
    raise SystemExit(main())
