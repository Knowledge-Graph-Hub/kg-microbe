"""Verify immutable-export pin provenance offline with tiny immutable source fixtures."""

import hashlib
import io
import json
import tarfile
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts import refresh_reviewed_mim as cli
from tests.test_mim_conservative_refresh import inputs as builder_inputs_fixture
from tests.test_mim_reviewed_release import bundle as release_bundle_fixture

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE = Path(__file__).parent / "resources/mim_commit_export.json"
inputs = builder_inputs_fixture
bundle = release_bundle_fixture


def _sha(data):
    """Hash fixed fixture bytes rather than reaching any external repository."""
    return hashlib.sha256(data).hexdigest()


def _write_pin(root, pin):
    """Write a test-owned pin under tmp_path."""
    path = root / cli.PIN_FILE
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(pin))


def _archive(path, pin, members, extra=None):
    """Assemble a bounded temporary tarball, optionally with one adversarial member."""
    prefix = "MediaIngredientMech-" + pin["source_commit"] + "/"
    with tarfile.open(path, "w:gz") as archive:
        for name, data in members.items():
            info = tarfile.TarInfo(prefix + name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
        if extra is not None:
            archive.addfile(extra)
    pin["source_archive"]["sha256"] = _sha(path.read_bytes())


@pytest.fixture
def export_fixture(tmp_path):
    """Provide source and artifact bytes, never actual scientific mapping approval."""
    data = {key: value.encode() for key, value in json.loads(FIXTURE.read_text()).items()}
    pin = cli.load_release_pin(REPO_ROOT)
    release = tmp_path / "release"
    release.mkdir()
    names = {
        "supported": "ingredient_mappings.sssom.tsv",
        "withheld": "withheld_mappings.sssom.tsv",
        "dispositions": "mapping-dispositions.tsv",
    }
    for key, name in names.items():
        (release / name).write_bytes(data[key])
    pin["files"] = {name: _sha(data[key]) for key, name in names.items()}
    pin["export_recipe"].update(lock_sha256=_sha(data["lock"]), workflow_sha256=_sha(data["workflow"]))
    manifest = {
        "files": pin["files"],
        "source_sssom": cli.SOURCE_SSSOM,
        "source_sha256": _sha(data["source_sssom"]),
        "review_sha256": _sha(data["review"]),
    }
    (release / "manifest.json").write_text(json.dumps(manifest))
    pin["manifest_sha256"] = _sha((release / "manifest.json").read_bytes())
    members = {
        cli.SOURCE_SSSOM: data["source_sssom"],
        cli.SOURCE_REVIEW: data["review"],
        "uv.lock": data["lock"],
        cli.SOURCE_WORKFLOW: data["workflow"],
    }
    archive = tmp_path / "source.tar.gz"
    _archive(archive, pin, members)
    _write_pin(tmp_path, pin)
    return pin, archive, release, members


def test_v2_checks_archived_source_and_manifest(export_fixture):
    """Verified archive members bind all artifact claims to the selected source."""
    pin, archive, release, members = export_fixture
    result = cli.validate_immutable_export(pin, archive, release)
    assert result["archive_members_sha256"] == {name: _sha(data) for name, data in members.items()}
    assert result["verification"] == "verified_archived_source_and_manifest_binding"


def test_legacy_v1_pin_is_still_supported(tmp_path):
    """Do not silently force existing immutable release-tag consumers onto v2."""
    pin = {
        "schema_version": 1,
        "release_tag": "mim-sssom-2026-09-21",
        "release_url": cli.UPSTREAM + "/releases/tag/mim-sssom-2026-09-21",
        "source_commit": "484082707b2a175cffebad3cbf46f3b39f66ca3d",
        "manifest_sha256": "cf883804354b5d4e9796e7e952a023b240ff951ed95372fb212c7afd47c65dcd",
        "mode": "candidate_only",
    }
    _write_pin(tmp_path, pin)
    assert cli.load_release_pin(tmp_path) == pin


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema_version", True),
        ("schema_version", 3),
        ("origin", "tag"),
        ("source_commit", "main"),
        ("mode", "production"),
        ("source_archive", {}),
        ("export_recipe", {}),
        ("files", {}),
        ("validation_run_url", "https://github.com/other/repo/actions/runs/1"),
        ("release_tag", "mim-sssom-2026-09-21"),
    ],
)
def test_v2_rejects_ambiguous_contract_fields(tmp_path, export_fixture, field, value):
    """Reject aliases, unknown fields, floating origins and hidden publication authority."""
    pin, _, _, _ = export_fixture
    pin[field] = value
    _write_pin(tmp_path, pin)
    with pytest.raises(ValueError):
        cli.load_release_pin(tmp_path)


@pytest.mark.parametrize(
    "section,field,value",
    [
        ("source_archive", "url", "https://codeload.github.com/CultureBotAI/MediaIngredientMech/tar.gz/main"),
        ("source_archive", "sha256", "f" * 63),
        ("source_archive", "unknown", True),
        ("export_recipe", "id", "execute_anything"),
        ("export_recipe", "python_version", 3.13),
        ("export_recipe", "lock_sha256", ""),
        ("export_recipe", "workflow_sha256", None),
        ("files", "ingredient_mappings.sssom.tsv", "A" * 64),
        ("files", "../escape.tsv", "f" * 64),
    ],
)
def test_v2_rejects_nested_contract_drift(tmp_path, export_fixture, section, field, value):
    """Require exactly recognized recipe fields, member names and canonical digests."""
    pin, _, _, _ = export_fixture
    pin[section][field] = value
    _write_pin(tmp_path, pin)
    with pytest.raises(ValueError):
        cli.load_release_pin(tmp_path)


def test_duplicate_pin_keys_are_not_silently_overwritten(tmp_path):
    """Reject misleading duplicate values before version dispatch."""
    path = tmp_path / cli.PIN_FILE
    path.parent.mkdir()
    path.write_text('{"schema_version": 1, "schema_version": 2}')
    with pytest.raises(ValueError, match="Duplicate"):
        cli.load_release_pin(tmp_path)


@pytest.mark.parametrize("member", [cli.SOURCE_SSSOM, cli.SOURCE_REVIEW, "uv.lock", cli.SOURCE_WORKFLOW])
def test_archive_content_cannot_be_rehashed_away(export_fixture, member):
    """A valid archive digest cannot substitute for matching source/review/recipe files."""
    pin, archive, release, members = export_fixture
    members[member] += b"tampered\n"
    _archive(archive, pin, members)
    with pytest.raises(ValueError, match="disagrees"):
        cli.validate_immutable_export(pin, archive, release)


@pytest.mark.parametrize(
    "name,kind",
    [
        ("../escape", tarfile.REGTYPE),
        ("/absolute", tarfile.REGTYPE),
        ("other-commit/file", tarfile.REGTYPE),
        ("same-root-link", tarfile.SYMTYPE),
        ("same-root-link", tarfile.LNKTYPE),
        ("same-root-device", tarfile.CHRTYPE),
        ("same-root-duplicate", tarfile.REGTYPE),
    ],
)
def test_archive_safety_fails_before_extraction(export_fixture, name, kind):
    """Do not admit traversal, alternate roots, links, special files or duplicate names."""
    pin, archive, release, members = export_fixture
    prefix = "MediaIngredientMech-" + pin["source_commit"] + "/"
    if name.startswith("same-root"):
        name = prefix + (cli.SOURCE_REVIEW if name.endswith("duplicate") else "link")
    extra = tarfile.TarInfo(name)
    extra.type = kind
    extra.linkname = "/outside"
    _archive(archive, pin, members, extra)
    with pytest.raises(ValueError, match="Unsafe"):
        cli.validate_immutable_export(pin, archive, release)


@pytest.mark.parametrize("target", ["archive", "manifest", "member", "missing_review", "wrong_source_path"])
def test_unpinned_or_incomplete_export_is_rejected(export_fixture, target):
    """Require the exact downloaded bytes and all selected archived provenance files."""
    pin, archive, release, members = export_fixture
    if target == "archive":
        pin["source_archive"]["sha256"] = "0" * 64
    elif target == "manifest":
        pin["manifest_sha256"] = "0" * 64
    elif target == "member":
        (release / "ingredient_mappings.sssom.tsv").write_text("changed")
    elif target == "missing_review":
        del members[cli.SOURCE_REVIEW]
        _archive(archive, pin, members)
    else:
        path = release / "manifest.json"
        manifest = json.loads(path.read_text())
        manifest["source_sssom"] = "different.tsv"
        path.write_text(json.dumps(manifest))
        pin["manifest_sha256"] = _sha(path.read_bytes())
    with pytest.raises(ValueError):
        cli.validate_immutable_export(pin, archive, release)


def test_archive_required_before_builder_or_output(tmp_path, export_fixture):
    """Missing provenance must fail before output publication or candidate construction."""
    _, _, release, _ = export_fixture
    with patch("scripts.mim_conservative_refresh.build_conservative_candidate") as builder:
        with pytest.raises(ValueError, match="--source-archive"):
            cli.build_candidate(
                repo_root=tmp_path,
                data_root=tmp_path / "data",
                release_directory=release,
                output_directory=tmp_path / "candidate",
            )
    builder.assert_not_called()
    assert not (tmp_path / "candidate").exists()


def test_verified_inputs_reach_atomic_builder(tmp_path, export_fixture):
    """The builder receives original hashes and the exact verified pin rather than unbound metadata."""
    pin, archive, release, _ = export_fixture
    with patch("scripts.mim_conservative_refresh.build_conservative_candidate", return_value="result") as builder:
        result = cli.build_candidate(
            repo_root=tmp_path,
            data_root=tmp_path / "data",
            release_directory=release,
            output_directory=tmp_path / "candidate",
            source_archive=archive,
        )
    assert result == "result"
    arguments = builder.call_args.kwargs
    assert arguments["upstream_provenance"]["pin"] == pin
    assert arguments["provenance_inputs"][archive] == pin["source_archive"]["sha256"]
    assert arguments["provenance_inputs"][tmp_path / cli.PIN_FILE] == _sha((tmp_path / cli.PIN_FILE).read_bytes())


def test_builder_retains_bound_provenance_in_atomic_report(inputs, tmp_path):
    """Successful construction preserves the pin snapshot and its verified file hash."""
    from scripts import mim_conservative_refresh as builder

    provenance_file = tmp_path / "verified-provenance.json"
    provenance_file.write_text('{"reviewed": true}')
    digest = _sha(provenance_file.read_bytes())
    proof = {"origin": "offline-test-fixture", "verification": "verified_archived_source_and_manifest_binding"}
    result = builder.build_conservative_candidate(
        **inputs, provenance_inputs={provenance_file: digest}, upstream_provenance=proof
    )
    assert result.report["upstream_provenance"] == proof
    assert result.report["input_sha256"][str(provenance_file)] == digest
    assert json.loads(result.report_path.read_text())["upstream_provenance"] == proof
    assert any("scientific review is not repeated" in item for item in result.report["limitations"])
    assert not any("Source/review hashes are publisher claims" in item for item in result.report["limitations"])


@pytest.mark.parametrize("during_build", [False, True])
def test_changed_provenance_never_publishes_candidate(inputs, tmp_path, monkeypatch, during_build):
    """A correct manifest cannot mask a changed pin/archive before or during construction."""
    from scripts import mim_conservative_refresh as builder

    provenance_file = tmp_path / "verified-provenance.json"
    provenance_file.write_text('{"reviewed": true}')
    digest = _sha(provenance_file.read_bytes())
    if during_build:
        validate = builder._validate_output

        def change_provenance(*args):
            """Simulate an external input change after output validation but before publication."""
            validate(*args)
            provenance_file.write_text("changed after validation")

        monkeypatch.setattr(builder, "_validate_output", change_provenance)
    else:
        provenance_file.write_text("changed before construction")
    with pytest.raises(ValueError, match="changed"):
        builder.build_conservative_candidate(
            **inputs, provenance_inputs={provenance_file: digest}, upstream_provenance={"origin": "test"}
        )
    assert not inputs["output_directory"].exists()


@pytest.mark.parametrize("target", ["archive", "manifest", "product", "release_directory"])
def test_provenance_inputs_cannot_be_symbolic_links(export_fixture, tmp_path, target):
    """Refuse link substitution even when the linked bytes have the expected hashes."""
    pin, archive, release, _ = export_fixture
    if target == "archive":
        linked = tmp_path / "linked.tar.gz"
        linked.symlink_to(archive)
        archive = linked
    elif target == "release_directory":
        linked = tmp_path / "linked-release"
        linked.symlink_to(release, target_is_directory=True)
        release = linked
    else:
        path = release / ("manifest.json" if target == "manifest" else "ingredient_mappings.sssom.tsv")
        real = path.with_suffix(".real")
        path.rename(real)
        path.symlink_to(real)
    with pytest.raises(ValueError, match="unsafe"):
        cli.validate_immutable_export(pin, archive, release)
