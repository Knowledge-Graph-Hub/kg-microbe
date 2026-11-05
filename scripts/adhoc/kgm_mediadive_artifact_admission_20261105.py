"""
Read-only qualification gate for the approved 2026-11-05 MediaDive graph release.

The production source freshness gate replays the selected sources and dependencies.
The production artifact inspector streams every archived member. This extra gate
binds the portable endpoint audit and coverage qualification to that fresh admission;
it neither changes graph assertions nor writes producer or historical receipts.
"""

import argparse
import codecs
import csv
import gzip
import json
import re
import sys
import tarfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = Path("data/rebuild-evidence/20261105/mediadive-resolution-1734")
EXPECTED_ENDPOINTS = 6688
EXPECTED_UNKNOWNS = 632


def require(condition, message):
    """Reject a missing or contradictory publication prerequisite."""
    if not condition:
        raise ValueError(message)


def same(left, right):
    """Require exact JSON types rather than Python boolean/integer equality."""
    return json.dumps(left, sort_keys=True, allow_nan=False) == json.dumps(right, sort_keys=True, allow_nan=False)


def audit_rows(stream):
    """Read only the finite endpoint audit, preserving unique canonical endpoint identities."""
    from kg_microbe.transform_utils.mediadive.endpoint_consumer import HEADER
    from kg_microbe.transform_utils.mediadive.endpoint_outcomes import BASE_URL, STATES

    reader = csv.DictReader(stream, delimiter="\t", quoting=csv.QUOTE_NONE)
    require(tuple(reader.fieldnames or ()) == HEADER, "Unexpected endpoint audit header")
    rows = {}
    for row in reader:
        require(len(rows) < EXPECTED_ENDPOINTS, "Extra endpoint audit rows")
        require(
            set(row) == set(HEADER) and all(isinstance(value, str) for value in row.values()),
            "Malformed audit row",
        )
        url, key = row["endpoint"], row["requested_id"]
        require(re.fullmatch(r"[A-Za-z0-9._-]+", key), "Invalid requested medium ID")
        require(
            url in {BASE_URL + kind + "/" + key for kind in ("medium", "medium-strains")},
            "Wrong endpoint URL",
        )
        require(url not in rows, "Duplicate endpoint audit URL")
        require(row["state"] in STATES, "Unknown endpoint state")
        require(
            all(re.fullmatch(r"[0-9a-f]{64}", row[field]) for field in ("observation_id", "body_sha256")),
            "Missing endpoint evidence identity",
        )
        require(bool(row["observed_at"]), "Missing observation time")
        rows[url] = row
    return rows


def qualification_check(manifest, members, rows, admitted, selected_paths):
    """Compare actual archive facts with the independently revalidated producer qualification."""
    from kg_microbe.merge_utils.source_qualifications import QUALIFICATION_SUFFIX
    from kg_microbe.transform_utils.mediadive.endpoint_outcomes import BASE_URL, STATES

    require(admitted.get("source") == "mediadive", "Wrong admitted qualification source")
    portable = manifest.get("provenance", {}).get("source_qualifications")
    require(
        isinstance(portable, list) and len(portable) == 1,
        "Missing or ambiguous portable source qualification",
    )
    published = portable[0]
    require(
        isinstance(published, dict) and published.get("source") == "mediadive",
        "Wrong published qualification source",
    )
    selected = {str(Path(path).resolve()) for path in selected_paths}
    require(bool(admitted.get("graph_paths")), "Admission lacks producer graph identities")
    participation = "graph_input" if selected.intersection(admitted["graph_paths"]) else "admitted_dependency"
    require(
        published.get("participation") == participation,
        "Selected/dependency participation mismatch",
    )
    for key in ("generation", "summary"):
        require(
            same(published.get(key), admitted.get(key)),
            f"Published {key} differs from current source admission",
        )
    summary, generation = admitted["summary"], admitted["generation"]
    require(
        same(generation.get("qualification"), summary),
        "Generation and admission summary disagree",
    )
    require(
        summary.get("endpoint_accounting_complete") is True,
        "Endpoint accounting is incomplete",
    )
    require(summary.get("recipe_coverage_complete") is True, "Recipe coverage is incomplete")
    require(
        summary.get("association_coverage_complete") is False,
        "Unknown associations were described as complete",
    )
    require(
        summary.get("policy_applied") is True and summary.get("admissible") is True,
        "Finite reviewed unknown policy was not admitted",
    )
    require(
        same(summary.get("unresolved_endpoints"), []),
        "Unresolved endpoint evidence remains",
    )
    for field, expected in (
        ("catalogue_count", EXPECTED_ENDPOINTS // 2),
        ("expected_endpoint_count", EXPECTED_ENDPOINTS),
        ("association_endpoint_count", EXPECTED_ENDPOINTS // 2),
    ):
        require(
            type(summary.get(field)) is int and summary[field] == expected,
            f"Wrong {field}",
        )
    require(
        len(rows) == EXPECTED_ENDPOINTS,
        "Endpoint audit does not cover exactly 6688 URLs",
    )
    counts = Counter(row["state"] for row in rows.values())
    expected = {state: counts[state] for state in sorted(STATES)}
    require(
        counts["unknown_unavailable"] == EXPECTED_UNKNOWNS,
        "Unknown endpoint cohort differs from reviewed 632",
    )
    require(
        all(counts[state] == 0 for state in ("transport_error", "malformed", "missing_evidence")),
        "Unresolved endpoint rows were published",
    )
    require(
        same(summary.get("state_counts"), expected),
        "Summary state counts differ from actual endpoint rows",
    )
    require(
        same(
            published.get("endpoint_state_counts"),
            {state: counts[state] for state in ("nonempty", "explicit_empty", "unknown_unavailable")},
        ),
        "Portable endpoint state counts disagree",
    )
    details, strains = set(), set()
    unknown = []
    for url, row in rows.items():
        if url.startswith(BASE_URL + "medium/"):
            require(
                row["state"] == "nonempty",
                "Recipe endpoint lacks positive native evidence",
            )
            details.add(row["requested_id"])
        else:
            strains.add(row["requested_id"])
        if row["state"] == "unknown_unavailable":
            unknown.append(url)
    require(
        details == strains and len(details) == EXPECTED_ENDPOINTS // 2,
        "Missing, extra or unpaired catalogue endpoints",
    )
    require(
        same(summary.get("unknown_endpoints"), sorted(unknown)),
        "Unknown URL cohort differs from source admission",
    )
    nodes = [name for name in members if name.endswith("_nodes.tsv")]
    require(len(nodes) == 1, "Ambiguous archived graph identity")
    audit_name = nodes[0][: -len("_nodes.tsv")] + QUALIFICATION_SUFFIX
    identity = members.get(audit_name)
    require(
        isinstance(identity, dict) and identity.get("rows") == EXPECTED_ENDPOINTS,
        "Missing endpoint audit member or wrong row count",
    )
    require(
        same(published.get("audit"), {"name": audit_name, **identity}),
        "Portable audit identity differs from manifest",
    )
    require(
        same(
            {key: identity[key] for key in ("bytes", "sha256")},
            {key: admitted["audit"][key] for key in ("bytes", "sha256")},
        ),
        "Archived endpoint audit differs from admitted native evidence",
    )
    policy, curated = generation.get("policy"), generation.get("curated_policy")
    require(
        isinstance(policy, dict) and isinstance(curated, dict),
        "Missing generation/current curated policy identities",
    )
    require(
        same(
            {key: policy.get(key) for key in ("bytes", "sha256")},
            {key: curated.get(key) for key in ("bytes", "sha256")},
        ),
        "Generation unknown policy differs from current reviewed policy",
    )
    return {
        "participation": participation,
        "endpoint_count": len(rows),
        "state_counts": expected,
        "generation": generation,
        "summary": summary,
        "audit": published["audit"],
    }


def archive_metadata(path, audit_name):
    """Stream an archive again for bounded metadata and endpoint rows; never load graph TSVs."""
    from kg_microbe.transform_utils.mediadive.endpoint_outcomes import strict_json
    from kg_microbe.utils.postprocess_artifacts import MAX_METADATA_BYTES

    manifest, rows = None, None
    with gzip.open(path, "rb") as compressed:
        with tarfile.open(fileobj=compressed, mode="r|") as archive:
            for member in archive:
                if member.name == "manifest.json":
                    with archive.extractfile(member) as stream:
                        payload = stream.read(MAX_METADATA_BYTES + 1)
                    require(
                        len(payload) <= MAX_METADATA_BYTES,
                        "Archive metadata exceeds the bounded limit",
                    )
                    manifest = strict_json(payload)
                elif member.name == audit_name:
                    with archive.extractfile(member) as stream:
                        rows = audit_rows(codecs.iterdecode(stream, "utf-8"))
        while compressed.read(1024 * 1024):
            pass
    require(
        isinstance(manifest, dict) and rows is not None,
        "Archive lacks required qualification evidence",
    )
    return manifest, rows


def verify(config_path, archive_path):
    """Use the actual production admission and artifact integrity APIs, with no bypass switches."""
    from kg_microbe.merge_utils.merge_kg import _source_filename_at_original_location
    from kg_microbe.merge_utils.source_admission import SourceAdmission
    from kg_microbe.merge_utils.source_freshness import verify_source_freshness
    from kg_microbe.merge_utils.source_qualifications import QUALIFICATION_SUFFIX
    from kg_microbe.utils.postprocess_artifacts import inspect_artifact
    from scripts.adhoc.kgm_rebuild_admission_20261105 import read_config

    admission = SourceAdmission()
    config_identity = admission.capture(config_path)
    config = read_config(config_path)
    configured = config["merged_graph"]["source"]
    names = list(configured)
    selected = []
    for name in names:
        filenames = configured[name]["input"]["filename"]
        if isinstance(filenames, str):
            filenames = [filenames]
        selected.extend(Path(_source_filename_at_original_location(value, config_path.parent)) for value in filenames)
    require(bool(selected), "No selected graph inputs")
    admission = verify_source_freshness(selected, admission=admission)
    qualifications = getattr(admission, "source_qualifications", {})
    require(
        len(qualifications) == 1,
        "Fresh admission lacks one unambiguous MediaDive qualification",
    )
    admitted = next(iter(qualifications.values()))
    archive_identity = admission.capture(archive_path)
    artifact = inspect_artifact(archive_path)
    require(artifact.status == "ok", artifact.detail)
    require(
        artifact.archive_sha256 == archive_identity["sha256"],
        "Archive changed during integrity inspection",
    )
    nodes = [name for name in artifact.members if name.endswith("_nodes.tsv")]
    require(len(nodes) == 1, "Ambiguous graph pair")
    audit_name = nodes[0][: -len("_nodes.tsv")] + QUALIFICATION_SUFFIX
    manifest, rows = archive_metadata(archive_path, audit_name)
    require(
        same(manifest.get("members"), artifact.members),
        "Archive metadata changed after integrity inspection",
    )
    provenance = manifest.get("provenance", {})
    require(
        same(
            provenance.get("merge_config"),
            {"name": config_path.name, "sha256": config_identity["sha256"]},
        ),
        "Archive was made with another merge config",
    )
    require(
        same(
            provenance.get("source_finalization"),
            {"required": True, "diagnostic_opt_out": False},
        ),
        "Archive lacks production source admission",
    )
    result = qualification_check(manifest, artifact.members, rows, admitted, selected)
    admission.verify()
    return {
        "selected_sources": names,
        "selected_graph_paths": [str(path) for path in selected],
        "config": {"path": str(config_path), **config_identity},
        "archive": {
            "path": str(archive_path),
            **archive_identity,
            "members": artifact.members,
        },
        "qualification": result,
        "admitted_file_count": len(admission.identities),
    }


def main(argv=None):
    """Save only a new task receipt after checking the actual completed artifact."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--merge-config", type=Path, default=Path("merge.yaml"))
    parser.add_argument("--archive", type=Path, default=Path("data/merged/merged-kg.tar.gz"))
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args(argv)
    result = {"checked_at": datetime.now(timezone.utc).isoformat(), "root": str(ROOT)}
    try:
        require(Path.cwd().resolve() == ROOT, "Run only from this helper's owned worktree")
        sys.path.insert(0, str(ROOT))
        import kg_microbe

        require(
            Path(kg_microbe.__file__).resolve().parent.parent == ROOT,
            "Wrong production module origin",
        )
        config, archive, receipt = (path.resolve() for path in (args.merge_config, args.archive, args.receipt))
        require(
            receipt.is_relative_to(ROOT / EVIDENCE),
            "Receipt must be new resolution evidence",
        )
        require(
            archive.is_relative_to(ROOT / "data") and archive.name.endswith(".tar.gz"),
            "Select an owned graph archive",
        )
        from scripts.adhoc.kgm_rebuild_admission_20261105 import (
            normalized_config,
            read_config,
        )

        require(
            same(
                normalized_config(read_config(config)),
                normalized_config(read_config(ROOT / "merge.yaml")),
            ),
            "The final release gate requires the complete canonical merge scope",
        )
        result["verification"] = verify(config, archive)
        result["status"] = "pass"
    except Exception as error:  # noqa: BLE001 - retain failed admission, never bypass it
        result.update(status="fail", error=f"{type(error).__name__}: {error}")
    receipt = args.receipt.resolve()
    require(
        receipt.is_relative_to(ROOT / EVIDENCE),
        "Receipt must be new resolution evidence",
    )
    receipt.parent.mkdir(parents=True, exist_ok=True)
    with receipt.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return int(result["status"] != "pass")


if __name__ == "__main__":
    raise SystemExit(main())
