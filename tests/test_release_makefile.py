"""Safety checks for local release artifact creation and cleanup."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MAKEFILE = REPO_ROOT / "kg-microbe.Makefile"


def _make(tmp_path: Path, target: str) -> subprocess.CompletedProcess[str]:
    make = shutil.which("make")
    assert make is not None
    return subprocess.run(  # noqa: S603 - executable and target are test-controlled
        [make, "-f", str(MAKEFILE), target],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )


def test_generated_artifact_manifest_excludes_preexisting_archives(tmp_path: Path) -> None:
    """Only archives produced by this run may be uploaded or cleaned up."""
    source = tmp_path / "data" / "transformed" / "example"
    source.mkdir(parents=True)
    (source / "nodes.tsv").write_text("id\nexample:1\n", encoding="utf-8")
    unrelated = tmp_path / "unrelated.tar.gz"
    unrelated.write_bytes(b"keep me")

    result = _make(tmp_path, "generate-tarballs")
    assert result.returncode == 0, result.stderr
    manifest = (tmp_path / ".release-artifacts.txt").read_text(encoding="utf-8").splitlines()
    assert manifest == ["example.tar.gz"]
    assert unrelated.read_bytes() == b"keep me"


def test_cleanup_removes_only_manifested_archives(tmp_path: Path) -> None:
    """Cleanup must preserve archives unrelated to the current release run."""
    owned = tmp_path / "owned.tar.gz"
    unrelated = tmp_path / "unrelated.tar.gz"
    owned.write_bytes(b"owned")
    unrelated.write_bytes(b"keep me")
    (tmp_path / ".release-artifacts.txt").write_text("owned.tar.gz\n", encoding="utf-8")

    result = _make(tmp_path, "cleanup-release-artifacts")
    assert result.returncode == 0, result.stderr
    assert not owned.exists()
    assert unrelated.read_bytes() == b"keep me"
    assert not (tmp_path / ".release-artifacts.txt").exists()


def test_release_makefile_never_rewrites_git_remote_with_token() -> None:
    """Credentials must remain in gh's environment/keyring, not Git config."""
    contents = MAKEFILE.read_text(encoding="utf-8")
    assert "git remote set-url" not in contents
    assert "https://$(GH_TOKEN)@" not in contents
    assert "rm -f *.tar.gz" not in contents
