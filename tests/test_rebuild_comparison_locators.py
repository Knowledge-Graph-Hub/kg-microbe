"""Keep explicit preserved graph comparisons inside their declared evidence boundary."""

import json
from pathlib import Path

import pytest

from scripts.adhoc import kgm_rebuild_comparison_20261105 as comparison


@pytest.fixture
def located(tmp_path, monkeypatch):
    """Create separate source and evidence roots without any production artifacts."""
    root = tmp_path / "owned"
    original = tmp_path / "original"
    evidence = root / "data/evidence"
    evidence.mkdir(parents=True)
    original.mkdir()
    for relative in comparison.FILES:
        source = original / relative
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes((relative + "\nimmutable fixture\n").encode())
    monkeypatch.setattr(comparison, "ROOT", root)
    monkeypatch.setattr(comparison, "EVIDENCE", evidence)
    monkeypatch.setattr(comparison, "ORIGINAL", original)
    monkeypatch.setattr(comparison, "BASELINE", evidence / "default")
    monkeypatch.chdir(root)
    # main adds its selected root; restore the interpreter path after this test.
    monkeypatch.setattr(comparison.sys, "path", list(comparison.sys.path))
    return root, original, evidence


def _arguments(original, baseline, receipt):
    """Choose the actual preserve CLI without invoking any graph validator."""
    return [
        "preserve",
        "--original-checkout",
        str(original),
        "--baseline-directory",
        str(baseline),
        "--receipt",
        str(receipt),
    ]


def test_dot_dot_cannot_escape_preservation_boundary(located):
    """Reject lexical ancestry that resolves outside the declared evidence directory."""
    _, original, evidence = located
    escaped = evidence / ".." / "outside"
    with pytest.raises(ValueError, match="Baseline must remain"):
        comparison.main(_arguments(original, escaped, evidence / "receipt.json"))
    assert not escaped.exists()
    assert not (evidence / "receipt.json").exists()


def test_aliased_owned_checkout_cannot_be_original(located):
    """Reject the owned checkout even when its supplied locator contains dot-dot."""
    root, _, evidence = located
    aliased = root / ".." / root.name
    with pytest.raises(ValueError, match="Wrong original comparison checkout"):
        comparison.main(_arguments(aliased, evidence / "copy", evidence / "receipt.json"))
    assert not (evidence / "copy").exists()


def test_linked_receipt_is_checked_before_normalization(located):
    """A linked receipt ancestor must not be erased before the no-link check."""
    _, original, evidence = located
    target = evidence / "target"
    target.mkdir()
    link = evidence / "linked"
    link.symlink_to(target, target_is_directory=True)
    with pytest.raises(ValueError, match="Linked locator"):
        comparison.main(_arguments(original, evidence / "copy", link / "receipt.json"))
    assert not (target / "receipt.json").exists()
    assert not (evidence / "copy").exists()


def test_aliased_reserved_manifest_is_refused(located):
    """The preservation manifest stays reserved after both locators normalize."""
    _, original, evidence = located
    baseline = evidence / "unused" / ".." / "copy"
    with pytest.raises(ValueError, match="Preservation manifest is reserved"):
        comparison.main(_arguments(original, baseline, evidence / "copy/preservation.json"))
    assert not (evidence / "copy").exists()


@pytest.mark.parametrize("explicit", [False, True])
def test_preservation_defaults_and_explicit_locators_keep_independent_bytes(located, explicit):
    """Real preservation binds exact copied bytes and refuses replacement on reuse."""
    _, original, evidence = located
    baseline = evidence / ("copy" if explicit else "default")
    receipt = evidence / "receipt.json"
    arguments = _arguments(original, baseline, receipt) if explicit else ["preserve", "--receipt", str(receipt)]
    assert comparison.main(arguments) == 0
    record = json.loads(receipt.read_text())
    assert record["status"] == "preserved"
    assert set(record["result"]["files"]) == set(comparison.FILES)
    for relative in comparison.FILES:
        source = original / relative
        copy = baseline / "original" / relative
        assert copy.read_bytes() == source.read_bytes()
        assert copy.stat().st_ino != source.stat().st_ino
        assert copy.stat().st_nlink == 1
        assert Path(record["result"]["files"][relative]["copy"]["path"]) == copy
    with pytest.raises(ValueError, match="new task evidence receipt"):
        comparison.main(arguments)
