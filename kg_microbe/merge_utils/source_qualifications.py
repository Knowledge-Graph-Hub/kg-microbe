"""Carry admitted source coverage limitations into every graph release artifact."""

import csv
import json
import shutil
from pathlib import Path

from kg_microbe.merge_utils.artifact_manifest import file_identity

QUALIFICATION_SUFFIX = "_mediadive_endpoint_outcomes.tsv"
STATES = {"nonempty", "explicit_empty", "unknown_unavailable"}


def selected_qualifications(admission, selected_paths):
    """Detach only admitted source/dependency qualifications before invoking KGX."""
    selected = {str(Path(path).resolve()) for path in selected_paths}
    values = getattr(admission, "source_qualifications", {}) if admission is not None else {}
    result = []
    for marker, entry in sorted(values.items()):
        record = json.loads(json.dumps(entry, allow_nan=False))
        if record.get("source") != "mediadive":
            raise ValueError("Unsupported admitted source qualification")
        if not record.get("graph_paths") or not isinstance(record.get("summary"), dict):
            raise ValueError("Incomplete admitted source qualification")
        record["participation"] = (
            "graph_input" if selected.intersection(record["graph_paths"]) else "admitted_dependency"
        )
        record["source_finalization"] = str(marker)
        result.append(record)
    if len(result) > 1:
        raise ValueError("Multiple MediaDive generations cannot share a release qualification")
    return result


def package_qualifications(records, output_dir, base):
    """Copy the required endpoint audit and preserve its scientific limitations."""
    members, expected, portable = [], {}, []
    for record in records:
        audit = record["audit"]
        source = Path(audit["path"])
        identity = file_identity(source)
        if any(identity[key] != audit[key] for key in ("bytes", "sha256")):
            raise ValueError("Admitted MediaDive endpoint audit changed before packaging")
        counts = dict.fromkeys(sorted(STATES), 0)
        endpoints = set()
        with source.open(encoding="utf-8", newline="") as stream:
            for row in csv.DictReader(stream, delimiter="\t", quoting=csv.QUOTE_NONE):
                if row.get("state") not in STATES or not row.get("endpoint") or row["endpoint"] in endpoints:
                    raise ValueError("Unresolved or duplicate endpoint in admitted MediaDive audit")
                endpoints.add(row["endpoint"])
                counts[row["state"]] += 1
        summary = record["summary"]
        if summary.get("association_coverage_complete") is not (counts["unknown_unavailable"] == 0):
            raise ValueError("MediaDive coverage qualification disagrees with endpoint outcomes")
        destination = Path(output_dir) / f"{base}{QUALIFICATION_SUFFIX}"
        if destination.exists():
            raise ValueError("MediaDive qualification destination already exists")
        shutil.copyfile(source, destination)
        if file_identity(destination) != identity:
            raise ValueError("MediaDive endpoint audit changed while copying")
        members.append(destination)
        expected[destination.name] = identity
        portable.append(
            {
                "source": record["source"],
                "participation": record["participation"],
                "generation": record["generation"],
                "summary": summary,
                "endpoint_state_counts": counts,
                "audit": {"name": destination.name, **identity},
                "interpretation": (
                    "Endpoint accounting is distinct from association completeness. "
                    "Unknown/unavailable endpoints support neither positive nor negative strain-growth assertions."
                ),
            }
        )
    return members, expected, portable
