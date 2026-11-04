"""Public NCBI admission retains the caller's selected raw-root locator (#1692)."""

import json
from pathlib import Path

import pytest

from kg_microbe.merge_utils import external_node_closure
from kg_microbe.merge_utils.source_admission import SourceAdmission
from kg_microbe.utils import source_finalization
from kg_microbe.utils.source_finalization import SourceFinalizationRequired, verify_finalized_source_files
from tests.test_declared_taxid_retirement import _authority, _published, _source


def _selected_source(tmp_path):
    """Select a lexical raw symlink while retaining its original authority directory."""
    source = _source(tmp_path)
    selected = source.input_base_dir
    first = selected.with_name("authority-a")
    selected.rename(first)
    selected.symlink_to(first, target_is_directory=True)
    return source, selected, first


def _replacement(first, *, same_bytes):
    """Prepare a distinct local target without modifying the original authority."""
    second = first.with_name("authority-b")
    second.mkdir()
    if same_bytes:
        (second / "taxdump.tar.gz").write_bytes((first / "taxdump.tar.gz").read_bytes())
    else:
        _authority(second, merged="10 | 20 |\n11 | 20 |\n")
    return second


def _retarget(selected, target):
    """Change only the selected symlink, preserving both authority targets."""
    selected.unlink()
    selected.symlink_to(target, target_is_directory=target.is_dir())


@pytest.mark.parametrize("relative", [False, True])
def test_unchanged_raw_root_symlink_admits_and_repeats(tmp_path, monkeypatch, relative):
    """Absolute and relative caller selections retain an absolute unresolved locator."""
    source, selected, first = _selected_source(tmp_path)
    if relative:
        monkeypatch.chdir(tmp_path)
        source.input_base_dir = Path("raw")
    report = source.finalize()
    assert report["raw_input_locator"] == str(selected.absolute())
    assert report["raw_input_directory"] == str(first.resolve())
    assert report["consumed_inputs"]["ncbi_taxonomy_authority"]["path"] == str((first / "taxdump.tar.gz").resolve())
    before = _published(source)
    verify_finalized_source_files([source.output_node_file, source.output_edge_file])
    assert source.finalize() == report
    assert _published(source) == before


@pytest.mark.parametrize("same_bytes", [False, True])
@pytest.mark.parametrize("locator", ["raw-root", "taxdump-file"])
def test_retargeted_ncbi_locator_rejects_without_changing_publication(tmp_path, same_bytes, locator):
    """A different root or archive target cannot reuse A's receipt even with identical bytes."""
    source, selected, first = _selected_source(tmp_path)
    if locator == "taxdump-file":
        selected = first / "taxdump.tar.gz"
        original = first / "original.tar.gz"
        selected.rename(original)
        selected.symlink_to(original)
    original_authority = (first / "taxdump.tar.gz").read_bytes()
    second = _replacement(first, same_bytes=same_bytes)
    source.finalize()
    before = _published(source)
    verify_finalized_source_files([source.output_node_file, source.output_edge_file])
    _retarget(selected, second if locator == "raw-root" else second / "taxdump.tar.gz")
    assert first.is_dir()
    unchanged = first / ("original.tar.gz" if locator == "taxdump-file" else "taxdump.tar.gz")
    assert unchanged.read_bytes() == original_authority
    for operation in (
        lambda: verify_finalized_source_files([source.output_node_file, source.output_edge_file]),
        source.finalize,
    ):
        with pytest.raises(SourceFinalizationRequired):
            operation()
        assert _published(source) == before


@pytest.mark.parametrize("same_bytes", [False, True])
def test_raw_root_retarget_during_public_admission_rejects(tmp_path, monkeypatch, same_bytes):
    """The public verifier retains lexical bindings until its final admission check."""
    source, selected, first = _selected_source(tmp_path)
    second = _replacement(first, same_bytes=same_bytes)
    report = source.finalize()
    before = _published(source)
    authority = Path(report["consumed_inputs"]["ncbi_taxonomy_authority"]["path"])
    original_authority = authority.read_bytes()
    original_capture = SourceAdmission.capture
    changed = False

    def capture_then_retarget(admission, path, **kwargs):
        """Move the selected root after A's exact authority bytes have been checked."""
        nonlocal changed
        result = original_capture(admission, path, **kwargs)
        if Path(path) == authority and not changed:
            _retarget(selected, second)
            changed = True
        return result

    monkeypatch.setattr(SourceAdmission, "capture", capture_then_retarget)
    with pytest.raises(SourceFinalizationRequired, match="locator changed"):
        verify_finalized_source_files([source.output_node_file, source.output_edge_file])
    assert changed
    assert authority.read_bytes() == original_authority
    assert _published(source) == before


@pytest.mark.parametrize(
    "damage", ["missing", "relative", "empty", "null", "nonexistent", "file", "wrong-locator", "wrong-resolved"]
)
def test_ncbi_receipt_requires_original_absolute_raw_locator(tmp_path, damage):
    """Persisted resolved paths and valid hashes cannot substitute for a missing lexical selection."""
    source, selected, first = _selected_source(tmp_path)
    report = source.finalize()
    if damage == "missing":
        del report["raw_input_locator"]
    elif damage == "relative":
        report["raw_input_locator"] = selected.name
    elif damage == "empty":
        report["raw_input_locator"] = ""
    elif damage == "null":
        report["raw_input_locator"] = None
    elif damage == "nonexistent":
        report["raw_input_locator"] = str(tmp_path / "missing")
    elif damage == "file":
        report["raw_input_locator"] = str(first / "taxdump.tar.gz")
    else:
        second = _replacement(first, same_bytes=True)
        key = "raw_input_locator" if damage == "wrong-locator" else "raw_input_directory"
        report[key] = str(second.resolve())
    (source.output_dir / "source_finalization.json").write_text(json.dumps(report))
    before = _published(source)
    with pytest.raises(SourceFinalizationRequired):
        verify_finalized_source_files([source.output_node_file, source.output_edge_file])
    assert _published(source) == before


def _shared_archive_root(first):
    """Select the exact same archive through another, independently identifiable raw root."""
    second = first.with_name("authority-b")
    second.mkdir()
    (second / "taxdump.tar.gz").symlink_to(first / "taxdump.tar.gz")
    assert second.resolve() != first.resolve()
    assert (second / "taxdump.tar.gz").resolve() == (first / "taxdump.tar.gz").resolve()
    return second


@pytest.mark.parametrize("relative", [False, True])
def test_unchanged_raw_root_with_shared_archive_admits(tmp_path, monkeypatch, relative):
    """Sharing an archive is valid until the selected raw root changes."""
    source, selected, first = _selected_source(tmp_path)
    second = _shared_archive_root(first)
    if relative:
        monkeypatch.chdir(tmp_path)
        source.input_base_dir = Path("raw")
    report = source.finalize()
    assert report["raw_input_locator"] == str(selected.absolute())
    assert report["raw_input_directory"] == str(first.resolve())
    before = _published(source)
    verify_finalized_source_files([source.output_node_file, source.output_edge_file])
    assert source.finalize() == report
    assert _published(source) == before
    _retarget(selected, second)
    with pytest.raises(SourceFinalizationRequired, match="authority directory"):
        verify_finalized_source_files([source.output_node_file, source.output_edge_file])
    assert _published(source) == before


@pytest.mark.parametrize("prior_publication", [False, True])
@pytest.mark.parametrize("timing", ["during-parse", "before-publish", "publication-audit"])
def test_initial_finalization_keeps_raw_root_bound_through_publication(
    tmp_path, monkeypatch, prior_publication, timing
):
    """A shared archive cannot hide a raw-root retarget during parsing or publication."""
    source, selected, first = _selected_source(tmp_path)
    second = _shared_archive_root(first)
    archive = first / "taxdump.tar.gz"
    original_authority = archive.read_bytes()
    if prior_publication:
        source.finalize()
    before = _published(source)
    parse = external_node_closure.load_taxid_retirements
    publish = source_finalization._publish_finalization
    verify_audits = source_finalization.verify_producer_audits
    changed = False
    publishing = False

    def retarget():
        """Change only the root while preserving the resolved archive and its original bytes."""
        nonlocal changed
        assert not changed
        _retarget(selected, second)
        changed = True
        assert (selected / "taxdump.tar.gz").resolve() == archive.resolve()

    def parse_then_retarget(*args, **kwargs):
        """Change the selection after the original authority has actually been parsed."""
        result = parse(*args, **kwargs)
        if timing == "during-parse":
            retarget()
        return result

    def publish_after_retarget(transform, prepared):
        """Exercise the boundary after a complete staging report has been prepared."""
        nonlocal publishing
        publishing = True
        assert prepared[3]["raw_input_directory"] == str(first.resolve())
        assert prepared[3]["raw_input_locator"] == str(selected.absolute())
        if timing == "before-publish":
            retarget()
        return publish(transform, prepared)

    def verify_audits_then_retarget(transform, **kwargs):
        """Change the root during the last publication check, before any graph replacement."""
        result = verify_audits(transform, **kwargs)
        if timing == "publication-audit" and publishing and kwargs.get("output_dir") is not None:
            retarget()
        return result

    monkeypatch.setattr(external_node_closure, "load_taxid_retirements", parse_then_retarget)
    monkeypatch.setattr(source_finalization, "_publish_finalization", publish_after_retarget)
    monkeypatch.setattr(source_finalization, "verify_producer_audits", verify_audits_then_retarget)
    with pytest.raises(SourceFinalizationRequired, match="raw-root locator changed"):
        source.finalize(fresh_run=prior_publication)
    assert changed
    assert archive.read_bytes() == original_authority
    assert _published(source) == before
