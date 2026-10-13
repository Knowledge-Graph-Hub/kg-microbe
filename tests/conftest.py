"""Shared hermetic-test configuration for kg-microbe."""

from __future__ import annotations

import ipaddress
import os
import shutil
import socket
import subprocess
from pathlib import Path
from typing import Any

import pytest

TEST_RESOURCES = Path(__file__).resolve().parent / "resources"


@pytest.fixture
def local_source_schema(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    """
    Use real immutable schema inputs for tests that exercise strict source admission.

    KGX's environment overrides alone do not select transform fingerprint inputs.
    Point both readers at the same isolated copies without replacing fingerprint
    or validation functions, so missing/changed-schema checks remain meaningful.
    """
    from kg_microbe.merge_utils import source_freshness
    from kg_microbe.utils import transform_fingerprint

    schema_dir = tmp_path / "schema"
    schema_dir.mkdir()
    model = schema_dir / "biolink-model.yaml"
    predicate_map = schema_dir / "predicate_mapping.yaml"
    shutil.copyfile(TEST_RESOURCES / "biolink-model-minimal.yaml", model)
    shutil.copyfile(TEST_RESOURCES / "predicate_mapping_minimal.yaml", predicate_map)
    schema_files = (model, predicate_map)
    monkeypatch.setattr(transform_fingerprint, "SCHEMA_FILES", schema_files)
    monkeypatch.setattr(source_freshness, "SCHEMA_FILES", schema_files)
    monkeypatch.setenv("KG_MICROBE_BIOLINK_MODEL", str(model))
    monkeypatch.setenv("KG_MICROBE_BIOLINK_PREDICATE_MAP", str(predicate_map))
    return schema_files


def pytest_configure() -> None:
    """Point data-dependent unit tests at committed immutable fixtures."""
    os.environ.setdefault("KG_MICROBE_METPO_JSON", str(TEST_RESOURCES / "metpo_minimal.json"))
    os.environ.setdefault("KG_MICROBE_METPO_TEMPLATE_DIR", str(TEST_RESOURCES / "metpo_templates"))
    os.environ.setdefault("KG_MICROBE_BIOLINK_MODEL", str(TEST_RESOURCES / "biolink-model-minimal.yaml"))
    os.environ.setdefault(
        "KG_MICROBE_BIOLINK_PREDICATE_MAP",
        str(TEST_RESOURCES / "predicate_mapping_minimal.yaml"),
    )


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Skip explicitly marked live/local-service tests unless opted in."""
    run_integration = os.environ.get("KG_MICROBE_RUN_INTEGRATION", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }
    if run_integration:
        return
    skip = pytest.mark.skip(reason="integration test; set KG_MICROBE_RUN_INTEGRATION=1 to run")
    for item in items:
        if item.get_closest_marker("integration"):
            item.add_marker(skip)


def _is_loopback(host: Any) -> bool:
    """Return whether a socket destination is local to the test process."""
    if host in {"localhost", "localhost.localdomain"}:
        return True
    try:
        return ipaddress.ip_address(str(host)).is_loopback
    except ValueError:
        return False


@pytest.fixture(autouse=True)
def block_external_network(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest) -> None:
    """Reject external DNS/socket use in unit tests while allowing loopback servers."""
    if request.node.get_closest_marker("integration"):
        return

    real_getaddrinfo = socket.getaddrinfo
    real_connect = socket.socket.connect

    def guarded_getaddrinfo(host: Any, *args: Any, **kwargs: Any):
        """Resolve loopback hosts only, so a unit test cannot reach the network."""
        if not _is_loopback(host):
            raise RuntimeError(f"external network disabled in unit tests: {host}")
        return real_getaddrinfo(host, *args, **kwargs)

    def guarded_connect(sock: socket.socket, address: Any) -> Any:
        """Permit connections to loopback only, for the same reason."""
        host = address[0] if isinstance(address, tuple) else address
        if not _is_loopback(host):
            raise RuntimeError(f"external network disabled in unit tests: {host}")
        return real_connect(sock, address)

    monkeypatch.setattr(socket, "getaddrinfo", guarded_getaddrinfo)
    monkeypatch.setattr(socket.socket, "connect", guarded_connect)


def _tracked_stamps(root: Path) -> dict[str, tuple[int, int] | None]:
    """Size and mtime of every git-tracked file; empty outside a git checkout."""
    git = shutil.which("git")
    if git is None:
        return {}
    try:
        query = [git, "ls-files", "-z"]
        listing = subprocess.run(query, cwd=root, capture_output=True, check=True).stdout  # noqa: S603 - read-only
    except (OSError, subprocess.CalledProcessError):
        return {}
    stamps: dict[str, tuple[int, int] | None] = {}
    for name in listing.decode("utf-8").split("\0"):
        if not name:
            continue
        try:
            status = (root / name).lstat()
        except FileNotFoundError:
            stamps[name] = None
        else:
            stamps[name] = (status.st_size, status.st_mtime_ns)
    return stamps


@pytest.fixture(scope="session", autouse=True)
def tracked_files_unchanged():
    """
    Fail the session if any test wrote a git-tracked file.

    Tests write only under tmp_path. A real transform run once rewrote the tracked
    kg_microbe/transform_utils/ontologies/xrefs/mondo_xrefs.tsv on every suite
    run, and because later runs rewrote identical bytes, content checks could not
    see it. Size and mtime catch any write, including a byte-identical one.
    """
    root = Path(__file__).resolve().parents[1]
    before = _tracked_stamps(root)
    yield
    after = _tracked_stamps(root)
    changed = sorted(name for name in before if after.get(name) != before[name])
    if changed:
        pytest.fail(
            f"Tests modified {len(changed)} tracked file(s); write only under tmp_path: " + ", ".join(changed[:20]),
            pytrace=False,
        )


#: Where a transform built without an output directory writes. The CLI always passes an
#: output directory, so nothing but a test creates anything here.
_PACKAGE_DEFAULT_DATA = Path("kg_microbe") / "transform_utils" / "data"
#: Pipeline output folders. They count only when absent at the start of the session, so a
#: ``kg transform`` running in the same checkout cannot trip the guard below.
_PIPELINE_OUTPUT_DIRS = (Path("data") / "transformed", Path("data") / "merged")


def _output_paths(root: Path) -> frozenset[str]:
    """Every path under the package's default data folder, and each pipeline output folder present."""
    found = {folder.as_posix() for folder in _PIPELINE_OUTPUT_DIRS if (root / folder).exists()}
    package = root / _PACKAGE_DEFAULT_DATA
    if package.exists():
        found.add(_PACKAGE_DEFAULT_DATA.as_posix())
        found.update(path.relative_to(root).as_posix() for path in package.rglob("*"))
    return frozenset(found)


@pytest.fixture(scope="session", autouse=True)
def no_output_paths_created():
    """
    Fail the session if a test created transform output paths in the checkout.

    A transform's constructor creates its output folder. Tests that built one inside the
    checkout left empty folders that the tracked-file guard above cannot see, and two tests
    that read ``data/transformed`` then ran or skipped depending on what an earlier run had
    left (#1592).
    """
    root = Path(__file__).resolve().parents[1]
    before = _output_paths(root)
    yield
    created = sorted(_output_paths(root) - before)
    if created:
        pytest.fail(
            f"Tests created {len(created)} output path(s) in the checkout; write only under tmp_path: "
            + ", ".join(created[:20]),
            pytrace=False,
        )
