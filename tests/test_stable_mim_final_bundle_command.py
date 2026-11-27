"""Isolated canary output and currentness controls without native prerequisites."""

from __future__ import annotations

import hashlib
import json
import unicodedata
from pathlib import Path
from types import SimpleNamespace

import pytest

from kg_microbe.utils.ingredient_bundle_contract import canonical_json
from kg_microbe.utils.stable_source_candidate import _Snapshots
from scripts import check_stable_mim_final_bundle as command


def digest(path):
    """Hash selected immutable test inputs."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def selection(tmp_path):
    """Create three distinct protected checkouts and an exact independent selection."""
    roots = [tmp_path / name for name in ("NativeRoot", "ProducerRoot", "KGRoot")]
    for root in roots:
        root.mkdir()
    path = tmp_path / "integration.json"
    path.write_bytes(canonical_json({"current_kgm": {"root": str(roots[2])}}))
    return SimpleNamespace(root=roots[0], producer=roots[1]), path, digest(path), roots


@pytest.mark.parametrize("index", range(3))
@pytest.mark.parametrize("alias", [False, True])
def test_protected_checkout_output_refused(selection, index, alias):
    """No selected checkout accepts new output, including a case spelling alias."""
    candidate, path, pin, roots = selection
    root = roots[index]
    if alias:
        root = root.with_name(root.name.swapcase())
    output = root / "new-output"
    with pytest.raises(ValueError, match="overlaps selected checkout"):
        command._output(candidate, path, pin, output)
    assert not output.exists()


def test_physical_unicode_alias_refused(selection, monkeypatch):
    """Exercise inode protection even on filesystems without Unicode equivalence."""
    candidate, path, pin, roots = selection
    alias = roots[0].with_name(unicodedata.normalize("NFD", "NativéRoot"))
    alias.mkdir()
    actual_stat = Path.stat

    def selected_identity(self, *args, **kwargs):
        """Model a distinct lexical spelling sharing a protected directory inode."""
        return actual_stat(roots[0] if self == alias else self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", selected_identity)
    with pytest.raises(ValueError, match="physically overlaps"):
        command._output(candidate, path, pin, alias / "new-output")
    assert not (alias / "new-output").exists()


def test_changed_selection_refused_before_output(selection, tmp_path):
    """A different protected root cannot be substituted after final admission."""
    candidate, path, pin, _ = selection
    path.write_text("{}\n")
    output = tmp_path / "new-output"
    with pytest.raises(ValueError, match="selection changed"):
        command._output(candidate, path, pin, output)
    assert not output.exists()


def test_symlink_output_parent_refused(selection, tmp_path):
    """A safe-looking alias is never an allowed canary parent."""
    candidate, path, pin, _ = selection
    alias = tmp_path / "alias"
    alias.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError, match="aliased canary output"):
        command._output(candidate, path, pin, alias / "new-output")


def test_distinct_new_output_allowed(selection, tmp_path):
    """The private sibling output is selected without creating it."""
    candidate, path, pin, _ = selection
    output = tmp_path / "new-output"
    assert command._output(candidate, path, pin, output) == output
    assert not output.exists()


@pytest.mark.parametrize("kind", ["bytes", "replacement", "extra"])
def test_persisted_candidate_remains_guarded(tmp_path, kind):
    """A reload's completion does not excuse later changes to persisted products."""
    output = tmp_path / "candidate"
    output.mkdir()
    product = output / "assertions.json"
    product.write_text("{}\n")
    manifest = output / "manifest.json"
    manifest.write_bytes(canonical_json({"files": {"assertions.json": digest(product)}}))
    snapshots = _Snapshots()
    command._persisted(output, digest(manifest), snapshots)
    if kind == "bytes":
        product.write_text('{"changed":true}\n')
    elif kind == "replacement":
        replacement = tmp_path / "replacement"
        replacement.write_bytes(product.read_bytes())
        replacement.replace(product)
    else:
        (output / "unselected").write_text("extra")
    with pytest.raises(ValueError, match="input changed|inventory"):
        snapshots.verify()


@pytest.mark.parametrize("kind", ["nodes.tsv", "edges.tsv", "candidate-projection.tar.gz"])
def test_generated_graph_drift_refused(tmp_path, monkeypatch, kind):
    """Mutation after archive readback cannot produce a successful canary result."""
    from kg_microbe.merge_utils import artifact_manifest

    candidate = SimpleNamespace(
        fingerprint="a" * 64,
        selection={"source_output": {"manifest_sha256": "b" * 64}},
        graph_rows=lambda: ([], []),
    )
    original = artifact_manifest.write_graph_archive

    def write_then_mutate(*args, **kwargs):
        """Change a verified loose TSV after the archive captures its original bytes."""
        original(*args, **kwargs)
        if kind != "candidate-projection.tar.gz":
            (tmp_path / kind).write_text("changed\n")

    def verify_then_mutate(*args):
        """Change the archive after its successful readback but before result creation."""
        if kind == "candidate-projection.tar.gz":
            (tmp_path / kind).write_bytes(b"changed after readback")

    candidate.verify_graph_rows = verify_then_mutate
    monkeypatch.setattr(artifact_manifest, "write_graph_archive", write_then_mutate)
    with pytest.raises(ValueError, match="input changed"):
        command._graph(candidate, tmp_path, _Snapshots())


def test_consumer_revision_and_origin_checks(monkeypatch):
    """A moved or dirty consumer cannot certify the selected execution head."""
    monkeypatch.setattr(command, "_head", lambda _: "a" * 40)
    monkeypatch.setattr(command, "_git", lambda *args: b"")
    assert command.checked_code("a" * 40) == Path(command.__file__).resolve().parents[1]
    with pytest.raises(ValueError, match="revision differs"):
        command.checked_code("b" * 40)
    monkeypatch.setattr(command, "_git", lambda *args: b" M scripts/changed.py")
    with pytest.raises(ValueError, match="tracked tree is dirty"):
        command.checked_code("a" * 40)


def test_canary_result_is_create_only(tmp_path):
    """An earlier receipt is preserved, never overwritten with a newer claim."""
    path = tmp_path / "result.json"
    command._write(path, {"production_authorized": False})
    with pytest.raises(FileExistsError):
        command._write(path, {"production_authorized": True})
    assert json.loads(path.read_bytes()) == {"production_authorized": False}
