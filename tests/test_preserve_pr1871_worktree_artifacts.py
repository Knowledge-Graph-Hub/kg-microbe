"""Offline preservation/refusal canaries for PR #1871 (2026-11-19)."""

import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/adhoc/preserve_pr1871_worktree_artifacts_20261119.py"
SPEC = importlib.util.spec_from_file_location("preserve_pr1871", SCRIPT)
preserve = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(preserve)


@pytest.fixture
def checkout(tmp_path, monkeypatch):
    """Create only synthetic local files; permit ephemeral destinations in tests."""
    monkeypatch.setattr(preserve, "TEMPORARY_ROOTS", ())
    root = tmp_path.resolve() / "checkout"
    root.mkdir()
    preserve.git(root, "init", "-b", "verify-only")
    (root / ".gitignore").write_text("data/\ncache/\n.venv/\n")
    (root / "tracked.txt").write_text("tracked source\n")
    preserve.git(root, "add", ".gitignore", "tracked.txt")
    preserve.git(
        root,
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=fixture@example.invalid",
        "-c",
        "core.hooksPath=/dev/null",
        "commit",
        "--no-gpg-sign",
        "-m",
        "fixture",
    )
    return root


def plan(root):
    """Plan against this exact synthetic branch."""
    return preserve.make_plan(root, root.parent / "retained", preserve.state(root)["head"], "verify-only")


def test_real_canary_then_remaining_keeps_bytes_links_and_metadata(checkout):
    """Actual renames preserve metadata, hidden inputs and opaque external links."""
    root = checkout
    (root / "data").mkdir()
    (root / "data/.hidden").write_bytes(b"preserved hidden bytes")
    (root / "untracked").write_bytes(b"untracked bytes")
    outside = root.parent / "outside"
    outside.write_bytes(b"never followed or changed")
    (root / "opaque-link").symlink_to(outside)
    prepared = plan(root)
    original = json.dumps(prepared, sort_keys=True)
    dry = preserve.apply(prepared, "canary", dry_run=True)
    assert len(dry["selected"]) == 1
    assert not Path(prepared["destination"]).exists()
    first = preserve.apply(prepared, "canary")
    assert len(first["moved_this_run"]) == 1
    assert preserve.apply(prepared, "remaining")["status"] == "PRESERVED"
    assert preserve.apply(prepared, "remaining")["moved_this_run"] == []
    archive = Path(prepared["destination"])
    assert (archive / "payload/data/.hidden").read_bytes() == b"preserved hidden bytes"
    assert (archive / "payload/opaque-link").is_symlink()
    assert outside.read_bytes() == b"never followed or changed"
    assert preserve.candidates(root) == []
    assert (root / "tracked.txt").read_text() == "tracked source\n"
    assert json.dumps(prepared, sort_keys=True) == original


def test_requires_canary_and_refuses_input_drift(checkout):
    """A plan neither authorizes skipping the canary nor moving changed data."""
    (checkout / "untracked").write_text("before")
    prepared = plan(checkout)
    with pytest.raises(preserve.Refusal, match="canary"):
        preserve.apply(prepared, "remaining")
    (checkout / "untracked").write_text("changed size")
    with pytest.raises(preserve.Refusal, match="Metadata drift"):
        preserve.apply(prepared, "canary")
    assert (checkout / "untracked").exists()


def test_refuses_tracked_changes_nested_git_and_active_git(checkout):
    """Never relocate dirty tracked work or an unrecognized nested repository."""
    (checkout / "tracked.txt").write_text("changed")
    with pytest.raises(preserve.Refusal, match="not clean"):
        plan(checkout)
    (checkout / "tracked.txt").write_text("tracked source\n")
    # An empty .git directory is neither a repository nor a status candidate.
    # Use a real ignored nested repository containing uncommitted source work.
    nested = checkout / "data"
    nested.mkdir()
    preserve.git(nested, "init", "-b", "nested-fixture")
    (nested / "valuable.txt").write_text("uncommitted nested source\n")
    with pytest.raises(preserve.Refusal, match="Nested repository"):
        plan(checkout)
    (checkout / ".git/MERGE_HEAD").write_text("fixture")
    with pytest.raises(preserve.Refusal, match="Active Git"):
        plan(checkout)


def test_refuses_wrong_identity_existing_destination_and_symlink_parent(checkout):
    """Paths and exact Git identity must be independently checked."""
    head = preserve.state(checkout)["head"]
    with pytest.raises(preserve.Refusal, match="Unexpected HEAD"):
        preserve.make_plan(checkout, checkout.parent / "retained", "0" * 40, "verify-only")
    with pytest.raises(preserve.Refusal, match="inside worktree"):
        preserve.make_plan(checkout, checkout / "retained", head, "verify-only")
    destination = checkout.parent / "exists"
    destination.mkdir()
    with pytest.raises(preserve.Refusal, match="already exists"):
        preserve.make_plan(checkout, destination, head, "verify-only")
    link = checkout.parent / "alias"
    link.symlink_to(destination, target_is_directory=True)
    with pytest.raises(preserve.Refusal, match="Symlink"):
        preserve.make_plan(checkout, link / "retained", head, "verify-only")


def test_rename_never_replaces_existing_file(checkout):
    """Exercise the real OS exclusive-rename primitive."""
    source, target = checkout / "source", checkout / "target"
    source.write_text("source")
    target.write_text("retain target")
    with pytest.raises(FileExistsError):
        preserve.rename_exclusive(source, target)
    assert source.read_text() == "source"
    assert target.read_text() == "retain target"


def test_resume_after_rename_before_verified_receipt(checkout, monkeypatch):
    """A receipt failure retains the moved payload and permits verified resume."""
    (checkout / "untracked").write_text("preserve me")
    prepared = plan(checkout)
    original = preserve.save_new

    def interrupted(path, value):
        """Interrupt the acknowledgement after the actual artifact move."""
        if path.name.endswith("-verified.json"):
            raise OSError("simulated interrupted acknowledgement")
        original(path, value)

    monkeypatch.setattr(preserve, "save_new", interrupted)
    with pytest.raises(OSError, match="simulated"):
        preserve.apply(prepared, "canary")
    archive = Path(prepared["destination"])
    assert (archive / "payload/untracked").read_text() == "preserve me"
    assert list(archive.glob("*-failure.json"))
    monkeypatch.setattr(preserve, "save_new", original)
    assert preserve.apply(prepared, "remaining")["status"] == "PRESERVED"


def test_new_ignored_input_invalidates_plan(checkout):
    """Ignore rules cannot hide additions made after the inventory."""
    (checkout / "untracked").write_text("original")
    prepared = plan(checkout)
    (checkout / "data").mkdir()
    (checkout / "data/new").write_text("new ignored bytes")
    with pytest.raises(preserve.Refusal, match="Unplanned artifacts"):
        preserve.apply(prepared, "canary")


def test_source_recreated_after_real_rename_refuses_success(checkout, monkeypatch):
    """A writer recreating an ignored source leaves both copies intact (#1877)."""
    (checkout / "data").mkdir()
    (checkout / "data/original").write_text("original bytes")
    prepared = plan(checkout)
    original = preserve.rename_exclusive

    def recreate(source, target):
        """Recreate ignored source evidence immediately after a real rename."""
        original(source, target)
        source.mkdir()
        (source / "new").write_text("new writer bytes")

    monkeypatch.setattr(preserve, "rename_exclusive", recreate)
    with pytest.raises(preserve.Refusal, match="exactly one"):
        preserve.apply(prepared, "canary")
    archive = Path(prepared["destination"])
    assert (archive / "payload/data/original").read_text() == "original bytes"
    assert (checkout / "data/new").read_text() == "new writer bytes"
    assert list(archive.glob("*-final-failure.json"))
    assert not list(archive.glob("*-run.json"))


@pytest.mark.parametrize("change", ["ignored", "tracked", "branch", "retained"])
def test_final_reconciliation_refuses_late_changes(checkout, monkeypatch, change):
    """All sources, archived items and Git identity must still match (#1877)."""
    (checkout / "untracked").write_text("original bytes")
    prepared = plan(checkout)
    original = preserve.save_new
    archive = Path(prepared["destination"])

    def change_after_verification(path, value):
        """Inject drift after per-item verification but before completion."""
        original(path, value)
        if not path.name.endswith("-verified.json"):
            return
        if change == "ignored":
            (checkout / "data").mkdir()
            (checkout / "data/new").write_text("new ignored bytes")
        elif change == "tracked":
            (checkout / "tracked.txt").write_text("new tracked change")
        elif change == "branch":
            preserve.git(checkout, "switch", "-c", "changed-branch")
        else:
            (archive / "payload/untracked").write_text("changed retained bytes")

    monkeypatch.setattr(preserve, "save_new", change_after_verification)
    with pytest.raises(preserve.Refusal):
        preserve.apply(prepared, "canary")
    assert (archive / "payload/untracked").exists()
    assert list(archive.glob("*-final-failure.json"))
    assert not list(archive.glob("*-run.json"))


def test_noop_resume_reconciles_again_before_success(checkout, monkeypatch):
    """Even an already-moved resume must detect changes after its preflight."""
    (checkout / "untracked").write_text("original bytes")
    prepared = plan(checkout)
    preserve.apply(prepared, "canary")
    archive = Path(prepared["destination"])
    previous = set(archive.glob("*-run.json"))
    original = preserve.reconcile

    def change_after_preflight(*args):
        """Add ignored evidence between the two reconciliation passes."""
        result = original(*args)
        (checkout / "data").mkdir()
        (checkout / "data/new").write_text("late ignored bytes")
        return result

    monkeypatch.setattr(preserve, "reconcile", change_after_preflight)
    with pytest.raises(preserve.Refusal, match="Unplanned artifacts"):
        preserve.apply(prepared, "remaining")
    assert set(archive.glob("*-run.json")) == previous
    assert (checkout / "data/new").read_text() == "late ignored bytes"
    assert (archive / "payload/untracked").read_text() == "original bytes"
