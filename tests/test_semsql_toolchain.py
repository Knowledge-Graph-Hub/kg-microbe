"""Each SemSQL build records its toolchain, and a reused DB is compared with it (#1524)."""

import hashlib
import importlib.metadata
import os
import sys
from pathlib import Path

import pytest

from kg_microbe.utils import ontology_utils as ou
from kg_microbe.utils import semsql_toolchain as toolchain
from tests.db_helpers import FIXED_SEMSQL_TOOLCHAIN
from tests.test_go_version_alignment import _make_go_db, _write_go_pair


@pytest.fixture(autouse=True)
def _fresh_probe_cache(monkeypatch):
    """Give every test its own process-wide probe cache and warning set."""
    monkeypatch.setattr(ou, "_TOOLCHAIN_PROBES", {})
    monkeypatch.setattr(ou, "_TOOLCHAIN_WARNED", set())


def _sha(data: bytes) -> str:
    """Hash bytes the way the record does."""
    return hashlib.sha256(data).hexdigest()


def _tools(tmp_path: Path) -> dict:
    """Lay out a fake semsql, rdftab and relation-graph install on its own PATH, and a pinned robot.jar."""
    bin_dir, raw = tmp_path / "bin", tmp_path / "raw"
    bin_dir.mkdir()
    raw.mkdir()
    semsql = bin_dir / "semsql"
    semsql.write_text(f"#!{sys.executable}\nraise SystemExit(0)\n", encoding="utf-8")
    rdftab = bin_dir / "rdftab"
    rdftab.write_bytes(b"rdftab binary")
    install = tmp_path / "relation-graph-cli-2.3.2"
    (install / "bin").mkdir(parents=True)
    (install / "lib").mkdir()
    launcher = install / "bin" / "relation-graph"
    launcher.write_text("#!/bin/sh\n", encoding="utf-8")
    (install / "lib" / "org.geneontology.relation-graph-2.3.2.jar").write_bytes(b"relation-graph jar")
    (install / "lib" / "org.geneontology.whelk_2.13-1.1.2.jar").write_bytes(b"whelk jar")
    for path in (semsql, rdftab, launcher):
        path.chmod(0o755)
    (bin_dir / "relation-graph").symlink_to(launcher)
    (raw / "robot.jar").write_bytes(b"robot jar")
    return {"env": {"PATH": str(bin_dir)}, "raw": raw, "install": install}


def test_the_record_names_each_tool_by_version_or_digest(tmp_path):
    """Versions where a tool reports one, digests where it does not, and the relation-graph jars."""
    tools = _tools(tmp_path)
    record = toolchain.current_toolchain(tools["raw"], tools["env"])
    assert record["semsql"]["version"] == importlib.metadata.version("semsql")
    assert record["rdftab"]["sha256"] == _sha(b"rdftab binary")
    assert record["relation_graph"]["version"] == "2.3.2"
    assert record["relation_graph"]["path"] == str((tools["install"] / "bin" / "relation-graph").resolve())
    assert record["robot_jar_sha256"] == _sha(b"robot jar")
    assert toolchain.missing_tools(record) == []


def test_a_different_bundled_reasoner_is_a_different_relation_graph(tmp_path):
    """The jar digest covers Whelk, which decides what relation-graph entails."""
    tools = _tools(tmp_path)
    before = toolchain.current_toolchain(tools["raw"], tools["env"])
    (tools["install"] / "lib" / "org.geneontology.whelk_2.13-1.1.2.jar").write_bytes(b"another whelk")
    after = toolchain.current_toolchain(tools["raw"], tools["env"])
    assert after["relation_graph"]["version"] == "2.3.2"
    assert toolchain.differences(before, after) == [
        f"relation_graph: recorded {toolchain._comparable(before['relation_graph'])}, "
        f"now {toolchain._comparable(after['relation_graph'])}"
    ]


def test_missing_tools_are_named(tmp_path):
    """A machine without rdftab and relation-graph can neither build nor vouch for a DB."""
    record = toolchain.current_toolchain(tmp_path, {"PATH": str(tmp_path / "nothing-here")})
    assert toolchain.missing_tools(record) == ["semsql", "rdftab", "relation-graph", "the pinned robot.jar"]


def test_paths_and_java_do_not_make_two_toolchains_different():
    """The same tools installed elsewhere, under another Java, built the same DB."""
    moved = {**FIXED_SEMSQL_TOOLCHAIN, "java": "another java"}
    moved["rdftab"] = {**FIXED_SEMSQL_TOOLCHAIN["rdftab"], "path": "/elsewhere/rdftab"}
    assert toolchain.differences(FIXED_SEMSQL_TOOLCHAIN, moved) == []


def test_a_missing_or_old_record_is_a_difference():
    """A DB built before #1524, or by an older record format, cannot be vouched for."""
    assert toolchain.differences(None, FIXED_SEMSQL_TOOLCHAIN) == [
        "it has no toolchain record (it predates #1524 or was built elsewhere)"
    ]
    assert "version 0" in toolchain.differences({**FIXED_SEMSQL_TOOLCHAIN, "version": 0}, FIXED_SEMSQL_TOOLCHAIN)[0]


def test_records_round_trip_beside_the_db(tmp_path):
    """Written atomically beside the DB, read back, and discarded when it no longer applies."""
    db = tmp_path / "go.db"
    toolchain.write_record(db, FIXED_SEMSQL_TOOLCHAIN)
    assert toolchain.record_path(db) == tmp_path / "go.db.toolchain.json"
    assert toolchain.read_record(db) == FIXED_SEMSQL_TOOLCHAIN
    toolchain.discard_record(db)
    assert toolchain.read_record(db) is None
    toolchain.discard_record(db)


def _aligned_go_db(tmp_path, monkeypatch, current) -> str:
    """Write a servable go.db at the release go.owl declares, with ``current`` as this machine's toolchain."""
    monkeypatch.setattr(ou, "_GO_DB_MIN_SIZE", 8)
    monkeypatch.setattr(
        "kg_microbe.transform_utils.constants.GO_SOURCE", _write_go_pair(tmp_path, "2026-05-19", "2026-05-19")
    )
    monkeypatch.setattr(ou, "current_toolchain", lambda raw_dir, env: dict(current))
    monkeypatch.delenv("KG_SEMSQL_BUILD", raising=False)
    return _make_go_db(tmp_path, "2026-05-19")


def _no_build(*args, **kwargs):
    """Fail the test if a build is attempted."""
    raise AssertionError("no build was expected")


def test_go_built_by_this_toolchain_is_reused(tmp_path, monkeypatch):
    """A matching record means the same release from the same toolchain: no rebuild."""
    db = _aligned_go_db(tmp_path, monkeypatch, FIXED_SEMSQL_TOOLCHAIN)
    toolchain.write_record(db, FIXED_SEMSQL_TOOLCHAIN)
    monkeypatch.setattr(ou, "_build_semsql_db", _no_build)
    assert ou._ensure_go_db(db) == ou.DbEnsureResult(True)


def test_go_with_no_record_is_rebuilt_strictly(tmp_path, monkeypatch, capsys):
    """GO's restriction policy depends on relation-graph, so an unvouched go.db is rebuilt."""
    db = _aligned_go_db(tmp_path, monkeypatch, FIXED_SEMSQL_TOOLCHAIN)
    calls = []
    monkeypatch.setattr(ou, "_build_semsql_db", lambda *args, **kwargs: calls.append(kwargs) or ou.DbEnsureResult(True))
    assert ou._ensure_go_db(db)
    assert calls and calls[0]["strict_toolchain"] is True
    assert "it has no toolchain record" in capsys.readouterr().out


def test_go_that_cannot_be_rebuilt_here_is_refused(tmp_path, monkeypatch, capsys):
    """Without rdftab and relation-graph, an unvouched go.db is not used, and the message says why."""
    current = {**FIXED_SEMSQL_TOOLCHAIN, "rdftab": None, "relation_graph": None}
    db = _aligned_go_db(tmp_path, monkeypatch, current)
    monkeypatch.setattr(ou, "_build_semsql_db", _no_build)
    assert ou._ensure_go_db(db) == ou.DbEnsureResult(False)
    out = capsys.readouterr().out
    assert "lacks rdftab, relation-graph" in out and "KG_SEMSQL_BUILD=off" in out


def test_go_opt_out_reuses_the_prebuilt_db(tmp_path, monkeypatch):
    """KG_SEMSQL_BUILD=off accepts the prebuilt go.db and its toolchain, as it always has."""
    db = _aligned_go_db(tmp_path, monkeypatch, {**FIXED_SEMSQL_TOOLCHAIN, "rdftab": None})
    monkeypatch.setenv("KG_SEMSQL_BUILD", "off")
    monkeypatch.setattr(ou, "_build_semsql_db", _no_build)
    assert ou._ensure_go_db(db)


def test_other_dbs_only_warn_once(tmp_path, monkeypatch, capsys):
    """ChEBI, NCBITaxon and EC take hours to rebuild: an unvouched DB is used, with one warning."""
    monkeypatch.setattr(ou, "current_toolchain", lambda raw_dir, env: dict(FIXED_SEMSQL_TOOLCHAIN))
    monkeypatch.delenv("KG_SEMSQL_BUILD", raising=False)
    db = str(tmp_path / "chebi.db")
    probes = []
    monkeypatch.setattr(
        ou, "current_toolchain", lambda raw_dir, env: probes.append(raw_dir) or dict(FIXED_SEMSQL_TOOLCHAIN)
    )
    ou._warn_on_toolchain_drift(db, None)
    ou._warn_on_toolchain_drift(db, None)
    ou._warn_on_toolchain_drift(str(tmp_path / "ncbitaxon.db"), None)
    assert capsys.readouterr().out.count("which this toolchain did not build") == 2
    assert len(probes) == 1, "one probe per raw directory and PATH in a process"


def _build_setup(tmp_path, monkeypatch, result):
    """Run _build_semsql_db with semsql present and the build itself replaced by ``result``."""
    owl = tmp_path / "go.owl"
    owl.write_text("owl", encoding="utf-8")
    real_which = ou.shutil.which
    monkeypatch.setattr(
        ou.shutil, "which", lambda name, *a, **k: "/fake/semsql" if name == "semsql" else real_which(name, *a, **k)
    )
    monkeypatch.setattr(ou, "current_toolchain", lambda raw_dir, env: dict(FIXED_SEMSQL_TOOLCHAIN))
    monkeypatch.delenv("KG_SEMSQL_BUILD", raising=False)
    runs = []
    monkeypatch.setattr(ou, "_run_semsql_build", lambda *args, **kwargs: runs.append(args) or result)
    return owl, str(tmp_path / "go.db"), runs


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        (ou.DbEnsureResult(True, built=True), FIXED_SEMSQL_TOOLCHAIN),
        (ou.DbEnsureResult(False, built=True), None),
    ],
)
def test_a_build_records_its_toolchain_or_drops_a_stale_record(tmp_path, monkeypatch, result, expected):
    """A usable new DB gets the record of what built it; an unusable new DB keeps no old record."""
    owl, db, _ = _build_setup(tmp_path, monkeypatch, result)
    toolchain.write_record(db, {**FIXED_SEMSQL_TOOLCHAIN, "java": "the old build"})
    ou._build_semsql_db(owl, db, 8, "GO", "cheap", ontology="go")
    assert toolchain.read_record(db) == expected


def test_a_failed_build_keeps_the_restored_dbs_record(tmp_path, monkeypatch):
    """When the old DB is put back, its record still describes it."""
    owl, db, _ = _build_setup(tmp_path, monkeypatch, ou.DbEnsureResult(True))
    old = {**FIXED_SEMSQL_TOOLCHAIN, "java": "the old build"}
    toolchain.write_record(db, old)
    ou._build_semsql_db(owl, db, 8, "GO", "cheap", ontology="go")
    assert toolchain.read_record(db) == old


@pytest.mark.parametrize(("strict", "builds"), [(True, 1), (False, 0)])
def test_strict_go_does_not_coalesce_on_another_toolchains_db(tmp_path, monkeypatch, strict, builds):
    """'Another process already built this release' counts for GO only if this toolchain built it."""
    owl, db, runs = _build_setup(tmp_path, monkeypatch, ou.DbEnsureResult(True, built=True))
    monkeypatch.setattr(ou, "_GO_DB_MIN_SIZE", 8)
    _make_go_db(tmp_path, "2026-05-19")
    toolchain.write_record(db, {**FIXED_SEMSQL_TOOLCHAIN, "rdftab": {"path": "/x", "sha256": "f" * 64}})
    ou._build_semsql_db(
        owl, db, 8, "GO", "cheap", ontology="go", expected_release="2026-05-19", strict_toolchain=strict
    )
    assert len(runs) == builds


def test_the_production_probe_uses_the_process_path():
    """Production passes os.environ; the lookup then takes shutil.which's own default path."""
    record = toolchain.current_toolchain(Path("/nonexistent-raw"), os.environ)
    assert set(record) == {"version", "semsql", "rdftab", "relation_graph", "robot_jar_sha256", "java"}
