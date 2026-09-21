"""Read-only postprocess reporting binds artifact and review claims to exact content."""

import hashlib
import importlib.util
import io
import json
import os
import sys
import tarfile
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "resources"


def _archive(path, *, manifest=True, damage=None):
    """Create immutable fixture payloads in a small archive, with explicit corrupt variants."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payloads = {f"graph_{kind}.tsv": (FIXTURES / f"postprocess_{kind}.tsv").read_bytes() for kind in ("nodes", "edges")}
    members = {
        name: {"sha256": hashlib.sha256(value).hexdigest(), "bytes": len(value), "rows": 1}
        for name, value in payloads.items()
    }
    if damage == "hash":
        members["graph_edges.tsv"]["sha256"] = "0" * 64
    if damage == "count":
        members["graph_edges.tsv"]["rows"] = 2
    if damage == "missing_member":
        payloads.pop("graph_edges.tsv")
    if manifest:
        payloads["manifest.json"] = json.dumps({"manifest_version": 1, "members": members}).encode()
    if damage == "bad_manifest":
        payloads["manifest.json"] = b"{broken"
    if damage == "unsafe":
        payloads["../outside"] = b"unsafe"
    with tarfile.open(path, "w:gz") as archive:
        for name, value in payloads.items():
            info = tarfile.TarInfo(name)
            info.size = len(value)
            archive.addfile(info, io.BytesIO(value))
        if damage == "duplicate":
            info = tarfile.TarInfo("graph_nodes.tsv")
            info.size = len(payloads[info.name])
            archive.addfile(info, io.BytesIO(payloads[info.name]))
        if damage == "symlink":
            info = tarfile.TarInfo("linked.tsv")
            info.type = tarfile.SYMTYPE
            info.linkname = "graph_nodes.tsv"
            archive.addfile(info)
    return path


@pytest.mark.parametrize("relative", ["data/merged/merged-kg.tar.gz", "data/merged/20260920/merged-kg.tar.gz"])
def test_root_and_dated_archive_only_discovery(tmp_path, relative):
    """Archive-only products are discoverable independently of their parent directory layout."""
    from kg_microbe.utils.postprocess_artifacts import inspect_artifact, select_artifact

    archive = _archive(tmp_path / relative)
    assert select_artifact(tmp_path) == archive
    result = inspect_artifact(archive)
    assert result.status == "ok"
    assert result.archive_sha256 == hashlib.sha256(archive.read_bytes()).hexdigest()
    assert result.members["graph_edges.tsv"]["rows"] == 1
    assert not (archive.parent / "graph_edges.tsv").exists()


@pytest.mark.parametrize(
    "damage", ["hash", "count", "missing_member", "bad_manifest", "unsafe", "duplicate", "symlink"]
)
def test_invalid_archives_never_appear_verified(tmp_path, damage):
    """Malformed containers or manifest identities fail closed."""
    from kg_microbe.utils.postprocess_artifacts import inspect_artifact

    archive = _archive(tmp_path / "variant.tar.gz", damage=damage)
    assert inspect_artifact(archive).status == "invalid"


def test_legacy_and_missing_archives_are_distinct(tmp_path):
    """Absent integrity evidence differs from a missing or corrupt graph container."""
    from kg_microbe.utils.postprocess_artifacts import inspect_artifact

    assert inspect_artifact(_archive(tmp_path / "legacy.tar.gz", manifest=False)).status == "unverified"
    assert inspect_artifact(tmp_path / "missing.tar.gz").status == "missing"
    (tmp_path / "broken.tar.gz").write_bytes(b"not tar")
    assert inspect_artifact(tmp_path / "broken.tar.gz").status == "invalid"
    trailer = _archive(tmp_path / "bad-crc.tar.gz")
    value = bytearray(trailer.read_bytes())
    value[-8] ^= 1
    trailer.write_bytes(value)
    assert inspect_artifact(trailer).status == "invalid"


def test_ambiguous_siblings_require_explicit_selection(tmp_path):
    """A directory containing several releases cannot silently choose the wrong sibling."""
    from kg_microbe.utils.postprocess_artifacts import select_artifact

    first = _archive(tmp_path / "data/merged/merged-kg.tar.gz")
    _archive(first.parent / "merged-kg-old.tar.gz")
    with pytest.raises(ValueError, match="Ambiguous"):
        select_artifact(tmp_path)
    assert select_artifact(tmp_path, archive=first) == first


def test_explicit_relocated_archive_wins_over_old_loose_pair(tmp_path):
    """Explicit identity selection ignores unrelated obsolete loose graph files."""
    from kg_microbe.utils.postprocess_artifacts import inspect_artifact, select_artifact

    archive = _archive(tmp_path / "relocated" / "custom.tar.gz")
    for kind in ("nodes", "edges"):
        (archive.parent / f"merged-kg_{kind}.tsv").write_bytes(b"old")
    assert select_artifact(tmp_path, archive=archive) == archive
    assert inspect_artifact(archive).status == "ok"


def test_loose_manifest_checks_content_not_same_mtime(tmp_path):
    """Exact member hashes detect mutations even when timestamps are deliberately preserved."""
    from kg_microbe.merge_utils.artifact_manifest import write_loose_manifest
    from kg_microbe.utils.postprocess_artifacts import inspect_artifact

    paths = []
    for kind in ("nodes", "edges"):
        path = tmp_path / f"graph_{kind}.tsv"
        path.write_bytes((FIXTURES / f"postprocess_{kind}.tsv").read_bytes())
        paths.append(path)
    manifest = tmp_path / "graph_manifest.json"
    write_loose_manifest(manifest, paths)
    assert inspect_artifact(manifest).status == "ok"
    stat = paths[1].stat()
    paths[1].write_bytes(paths[1].read_bytes().replace(b"fixture:1", b"fixture:2"))
    os.utime(paths[1], ns=(stat.st_atime_ns, stat.st_mtime_ns))
    assert inspect_artifact(manifest).status == "invalid"
    paths[1].unlink()
    assert inspect_artifact(manifest).status == "invalid"


def test_review_receipt_requires_exact_archive_and_report_identity(tmp_path):
    """Matching prose alone cannot pass; a receipt binds both artifact and final report bytes."""
    from kg_microbe.utils.postprocess_artifacts import inspect_artifact, review_status

    artifact = inspect_artifact(_archive(tmp_path / "graph.tar.gz"))
    review = tmp_path / "reviews"
    review.mkdir()
    report = review / "REVIEW.md"
    report.write_text(f"Review of {artifact.archive_sha256}: unresolved defects remain.\n")
    assert review_status("kg-model-review", artifact, tmp_path, [review])[0] == "unverified"
    report.write_text("Full-scope modeling review completed with pass verdict.\n")
    receipt = {
        "receipt_version": 1,
        "archive_sha256": artifact.archive_sha256,
        "skill": "kg-model-review",
        "verdict": "pass",
        "scope": "full",
        "report": report.name,
        "report_sha256": hashlib.sha256(report.read_bytes()).hexdigest(),
    }
    receipt_path = review / "kg-model-review.receipt.json"
    receipt_path.write_text(json.dumps(receipt))
    assert review_status("kg-model-review", artifact, tmp_path, [review])[0] == "ok"
    report.write_text("changed same report\n")
    assert review_status("kg-model-review", artifact, tmp_path, [review])[0] != "ok"
    receipt["archive_sha256"] = "0" * 64
    receipt_path.write_text(json.dumps(receipt))
    assert review_status("kg-model-review", artifact, tmp_path, [review])[0] != "ok"


@pytest.mark.parametrize("scope,verdict,expected", [("partial", "pass", "unverified"), ("full", "fail", "invalid")])
def test_review_receipt_never_promotes_partial_or_failed_review(tmp_path, scope, verdict, expected):
    """A matching hash is insufficient when the explicit scope or verdict is not passing."""
    from kg_microbe.utils.postprocess_artifacts import inspect_artifact, review_status

    artifact = inspect_artifact(_archive(tmp_path / "graph.tar.gz"))
    report = tmp_path / "REVIEW.md"
    report.write_text("Review evidence\n")
    receipt = {
        "receipt_version": 1,
        "skill": "kg-path-review",
        "archive_sha256": artifact.archive_sha256,
        "scope": scope,
        "verdict": verdict,
        "report": report.name,
        "report_sha256": hashlib.sha256(report.read_bytes()).hexdigest(),
    }
    (tmp_path / "path.receipt.json").write_text(json.dumps(receipt))
    assert review_status("kg-path-review", artifact, tmp_path, [tmp_path])[0] == expected


def _reporter():
    """Import the skill script without invoking its CLI or changing cwd."""
    path = Path(__file__).parents[1] / ".claude/skills/kg-postprocess-report/kg_postprocess_report.py"
    spec = importlib.util.spec_from_file_location("postprocess_report_test", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_markdown_review_evidence_is_skill_specific(tmp_path):
    """An unrelated hash-matching report must not stand in for the requested skill review."""
    from kg_microbe.utils.postprocess_artifacts import inspect_artifact, review_status

    artifact = inspect_artifact(_archive(tmp_path / "graph.tar.gz"))
    review = tmp_path / "reviews"
    review.mkdir()
    (review / "KGXVAL_REVIEW.md").write_text(artifact.archive_sha256)
    assert review_status("kg-path-review", artifact, tmp_path, [review])[0] == "missing"
    for kind in ("model", "path"):
        name = f"{kind.upper()}_REVIEW.md"
        (review / name).write_text(artifact.archive_sha256)
        status, detail = review_status(f"kg-{kind}-review", artifact, tmp_path, [review])
        assert status == "unverified"
        assert name in detail


@pytest.mark.parametrize("skill", ["kg-model-review", "kg-path-review"])
def test_dated_markdown_inside_skill_review_directory_is_discovered(tmp_path, skill):
    """The corresponding skill directory identifies reports even when filenames contain only dates."""
    from kg_microbe.utils.postprocess_artifacts import inspect_artifact, review_status

    artifact = inspect_artifact(_archive(tmp_path / "graph.tar.gz"))
    review = tmp_path / ".claude" / "skills" / skill / "reviews"
    review.mkdir(parents=True)
    report = review / "20260920.md"
    report.write_text(artifact.archive_sha256)
    status, detail = review_status(skill, artifact, tmp_path)
    assert status == "unverified"
    assert str(report) in detail


def test_generic_missing_outputs_and_timestamp_only_status_are_honest(tmp_path):
    """Incomplete output sets and unverified timestamp hints remain release blockers."""
    module = _reporter()
    (tmp_path / "input").write_text("input")
    (tmp_path / "first").write_text("output")
    operation = module.Operation(
        "fixture",
        "post-merge",
        "Fixture",
        "Purpose",
        "command",
        inputs=["input"],
        outputs=["first", "missing"],
        severity="blocker",
    )
    assert module.evaluate(operation, tmp_path)[0] == "missing"
    operation.outputs = ["first"]
    status = module.evaluate(operation, tmp_path)
    assert status[0] == "unverified"
    rendered = module.render([operation], {"fixture": status}, tmp_path, None, tmp_path)
    assert "All release-blocker" not in rendered
