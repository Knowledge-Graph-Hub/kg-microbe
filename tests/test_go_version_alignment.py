"""Tests for the GO version-alignment gate and go.db build helper (#604)."""

import sqlite3
import subprocess as sp_module
from pathlib import Path

import pytest

from kg_microbe.utils import ontology_utils as ou
from tests.db_helpers import valid_db_bytes, write_semsql_db

_OWL = '<owl versionIRI rdf:resource="http://purl.obolibrary.org/obo/go/releases/{d}/go.owl"/>'
_JSON = '{{"meta":{{"basicPropertyValues":[{{"pred":"owl#versionInfo","val":"{d}"}}]}}}}'


def _write_go_pair(tmp_path: Path, owl_date: str, json_date: str) -> Path:
    """Write minimal go.owl / go.json with the given release stamps; return go.owl path."""
    (tmp_path / "go.owl").write_text(_OWL.format(d=owl_date), encoding="utf-8")
    (tmp_path / "go.json").write_text(_JSON.format(d=json_date), encoding="utf-8")
    return tmp_path / "go.owl"


def _make_go_db(tmp_path: Path, release, name: str = "go.db") -> str:
    """Write a minimal SemSQL-shaped go.db stamping obo:go.owl owl:versionInfo."""
    path = str(tmp_path / name)
    extra = []
    if release is not None:
        extra.append(
            (
                "INSERT INTO statements (subject, predicate, object, value) "
                "VALUES ('obo:go.owl', 'owl:versionInfo', NULL, ?)",
                (release,),
            )
        )
    write_semsql_db(path, extra_statements=extra)
    return path


def test_release_parsed_from_owl_versioniri(tmp_path):
    """The YYYY-MM-DD release is read from an OWL versionIRI."""
    (tmp_path / "go.owl").write_text(_OWL.format(d="2026-05-19"), encoding="utf-8")
    assert ou._obo_release_from_head(tmp_path / "go.owl") == "2026-05-19"


def test_release_parsed_from_obojson_versioninfo(tmp_path):
    """The release is read from an OBO-JSON versionInfo val (with intervening ","val":)."""
    (tmp_path / "go.json").write_text(_JSON.format(d="2026-05-19"), encoding="utf-8")
    assert ou._obo_release_from_head(tmp_path / "go.json") == "2026-05-19"


def test_release_none_when_unreadable(tmp_path):
    """A missing / unstamped file yields None (no crash)."""
    assert ou._obo_release_from_head(tmp_path / "nope.owl") is None
    (tmp_path / "blank.owl").write_text("no version here", encoding="utf-8")
    assert ou._obo_release_from_head(tmp_path / "blank.owl") is None


def test_release_parsed_from_obojson_meta_version_without_releases_segment(tmp_path):
    """
    ROBOT's OBO-JSON stashes the source OWL's versionIRI in `meta.version`.

    An ontology whose IRI omits the `releases/` segment (EC:
    `.../obo/eccode/DATE/eccode.owl`) falls through the `releases/` regex,
    the OWL-only `versionIRI` regex, and — if ROBOT did not synthesise a
    `versionInfo` basicPropertyValue for it — the `versionInfo` regex too.
    Without the `"version": "..."` fallback the reader returns None, the
    staleness check reports "not stale", `convert_to_json` skips regeneration
    even though ec.db has since realigned, and the release drift between the
    transform's node emission and the guarded lookup DB reopens.
    """
    (tmp_path / "ec.json").write_text(
        '{"graphs":[{"id":"http://purl.obolibrary.org/obo/eccode.owl",'
        '"meta":{"basicPropertyValues":['
        '{"pred":"http://www.geneontology.org/formats/oboInOwl#hasOBOFormatVersion","val":"1.2"}],'
        '"version":"http://purl.obolibrary.org/obo/eccode/2024-10-02/eccode.owl"}}]}',
        encoding="utf-8",
    )
    assert ou._obo_release_from_head(tmp_path / "ec.json") == "2024-10-02"


def test_aligned_versions_do_not_raise(tmp_path, monkeypatch):
    """Matching go.owl / go.json releases pass the gate silently."""
    owl = _write_go_pair(tmp_path, "2026-05-19", "2026-05-19")
    monkeypatch.setattr("kg_microbe.transform_utils.constants.GO_SOURCE", owl)
    ou.assert_go_version_alignment(strict=True)  # must not raise


def test_mismatch_raises_in_strict_mode(tmp_path, monkeypatch):
    """Divergent go.owl / go.json releases fail loudly under strict."""
    owl = _write_go_pair(tmp_path, "2026-05-19", "2026-04-01")
    monkeypatch.setattr("kg_microbe.transform_utils.constants.GO_SOURCE", owl)
    with pytest.raises(ou.OntologyVersionMismatchError, match="GO source version mismatch"):
        ou.assert_go_version_alignment(strict=True)


def test_mismatch_warns_when_not_strict(tmp_path, monkeypatch, capsys):
    """Under strict=False a mismatch warns instead of raising."""
    owl = _write_go_pair(tmp_path, "2026-05-19", "2026-04-01")
    monkeypatch.setattr("kg_microbe.transform_utils.constants.GO_SOURCE", owl)
    ou.assert_go_version_alignment(strict=False)  # no raise
    assert "GO source version mismatch" in capsys.readouterr().out


def test_missing_source_is_a_noop(tmp_path, monkeypatch):
    """When a GO source can't be read, the gate is a no-op (can't judge)."""
    monkeypatch.setattr("kg_microbe.transform_utils.constants.GO_SOURCE", tmp_path / "absent.owl")
    ou.assert_go_version_alignment(strict=True)  # must not raise


def test_env_var_downgrades_default_to_warn(tmp_path, monkeypatch, capsys):
    """KG_GO_VERSION_CHECK=warn turns the default (strict) gate into a warning."""
    owl = _write_go_pair(tmp_path, "2026-05-19", "2026-04-01")
    monkeypatch.setattr("kg_microbe.transform_utils.constants.GO_SOURCE", owl)
    monkeypatch.setenv("KG_GO_VERSION_CHECK", "warn")
    ou.assert_go_version_alignment()  # strict=None → env says warn → must not raise
    assert "GO source version mismatch" in capsys.readouterr().out


def test_fix_node_categories_invokes_gate(tmp_path, monkeypatch):
    """The GO branch of _fix_node_categories actually calls the alignment gate."""
    import pandas as pd

    from kg_microbe.transform_utils.ontologies.ontologies_transform import OntologiesTransform

    called = {"gate": False}
    monkeypatch.setattr(
        "kg_microbe.utils.ontology_utils.assert_go_version_alignment",
        lambda *a, **k: called.__setitem__("gate", True),
    )
    # Stub the per-term lookup so the wiring test needs no real go.db.
    monkeypatch.setattr(
        "kg_microbe.utils.ontology_utils.get_go_category_by_aspect",
        lambda go_id, **k: "biolink:MolecularActivity",
    )
    nodes = tmp_path / "go_nodes.tsv"
    pd.DataFrame(
        [["GO:0004096", "biolink:BiologicalProcess", "catalase activity"]],
        columns=["id", "category", "name"],
    ).to_csv(nodes, sep="\t", index=False)

    t = OntologiesTransform.__new__(OntologiesTransform)
    t._fix_node_categories(nodes, "go")

    assert called["gate"] is True
    assert pd.read_csv(nodes, sep="\t").iloc[0]["category"] == "biolink:MolecularActivity"


def test_ensure_go_db_skips_build_when_valid(tmp_path, monkeypatch):
    """A go.db already above the min-size threshold is left as-is (no rebuild)."""
    # Shrink the threshold so the test writes a few bytes, not ~10 MB.
    monkeypatch.setattr(ou, "_GO_DB_MIN_SIZE", 8)
    # A real SQLite file, not filler bytes: the reuse path now also probes that
    # the DB actually opens, so a large-but-corrupt file is rebuilt rather than
    # handed to OAK to fail silently against.
    db = _make_go_db(tmp_path, None)
    # GO_SOURCE need not exist — the valid-db short-circuit returns before using it.
    assert ou._ensure_go_db(db)


def test_ensure_go_db_cannot_build_without_owl(tmp_path, monkeypatch, capsys):
    """A missing/empty go.db with no OWL source degrades gracefully (warn, False)."""
    monkeypatch.setattr("kg_microbe.transform_utils.constants.GO_SOURCE", tmp_path / "absent.owl")
    assert not ou._ensure_go_db(str(tmp_path / "go.db"))
    assert "missing" in capsys.readouterr().out


# --- fix 2 (#604): GO single source of truth -------------------------------


def test_derived_json_stale_when_releases_differ(tmp_path):
    """A go.json whose release differs from go.owl is reported stale."""
    owl = _write_go_pair(tmp_path, "2026-05-19", "2026-04-01")
    assert ou._derived_json_is_stale(owl, tmp_path / "go.json") is True


def test_derived_json_not_stale_when_aligned(tmp_path):
    """Matching releases are not stale (no needless reconversion)."""
    owl = _write_go_pair(tmp_path, "2026-05-19", "2026-05-19")
    assert ou._derived_json_is_stale(owl, tmp_path / "go.json") is False


def test_derived_json_unstamped_is_not_stale(tmp_path):
    """An unreadable/unstamped pair yields False (preserves convert-if-missing)."""
    (tmp_path / "go.owl").write_text("no version here", encoding="utf-8")
    assert ou._derived_json_is_stale(tmp_path / "go.owl", tmp_path / "missing.json") is False


def test_go_db_release_read_from_versioninfo(tmp_path):
    """_go_db_release reads owl:versionInfo off the obo:go.owl subject."""
    assert ou._go_db_release(_make_go_db(tmp_path, "2026-05-19")) == "2026-05-19"


def test_go_db_release_ignores_decoy_subject(tmp_path):
    """A version-shaped value on a non-ontology subject is ignored."""
    path = str(tmp_path / "go.db")
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE statements (subject TEXT, predicate TEXT, object TEXT, value TEXT)")
    conn.execute(
        "INSERT INTO statements (subject, predicate, value) VALUES ('GO:0008150', 'owl:versionInfo', '1999-01-01')"
    )
    conn.execute(
        "INSERT INTO statements (subject, predicate, value) VALUES ('obo:go.owl', 'owl:versionInfo', '2026-05-19')"
    )
    conn.commit()
    conn.close()
    assert ou._go_db_release(path) == "2026-05-19"


def test_go_db_release_none_when_absent_or_corrupt(tmp_path):
    """Missing stamp, missing file, and a non-sqlite file all yield None."""
    assert ou._go_db_release(_make_go_db(tmp_path, None)) is None
    assert ou._go_db_release(str(tmp_path / "nope.db")) is None
    corrupt = tmp_path / "corrupt.db"
    corrupt.write_text("not sqlite", encoding="utf-8")
    assert ou._go_db_release(str(corrupt)) is None


def test_ensure_go_db_keeps_aligned_db(tmp_path, monkeypatch):
    """A valid, release-aligned go.db is reused (no rebuild)."""
    monkeypatch.setattr(ou, "_GO_DB_MIN_SIZE", 8)
    monkeypatch.setattr(
        "kg_microbe.transform_utils.constants.GO_SOURCE",
        _write_go_pair(tmp_path, "2026-05-19", "2026-05-19"),
    )
    db = _make_go_db(tmp_path, "2026-05-19")
    assert ou._ensure_go_db(db)


def test_ensure_go_db_rebuilds_on_release_drift(tmp_path, monkeypatch, capsys):
    """
    A valid-size but release-drifted go.db is NOT short-circuited as usable.

    With ``semsql`` forced off, the drift path falls through to a build attempt
    and returns False — proving the stale db was rejected rather than reused.
    """
    monkeypatch.setattr(ou, "_GO_DB_MIN_SIZE", 8)
    monkeypatch.setattr(
        "kg_microbe.transform_utils.constants.GO_SOURCE",
        _write_go_pair(tmp_path, "2026-05-19", "2026-05-19"),
    )
    monkeypatch.setattr(ou.shutil, "which", lambda _cmd: None)  # no semsql → build can't run
    db = _make_go_db(tmp_path, "2026-01-01")  # drifted from go.owl (2026-05-19)
    assert not ou._ensure_go_db(db)
    assert "drifted" in capsys.readouterr().out


def test_go_db_release_reads_full_iri_subject(tmp_path):
    """The db-release read also matches the full-IRI ontology subject encoding."""
    path = str(tmp_path / "go.db")
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE statements (subject TEXT, predicate TEXT, object TEXT, value TEXT)")
    conn.execute(
        "INSERT INTO statements (subject, predicate, value) "
        "VALUES ('http://purl.obolibrary.org/obo/go.owl', 'owl:versionInfo', '2026-05-19')"
    )
    conn.commit()
    conn.close()
    assert ou._go_db_release(path) == "2026-05-19"


def _stub_go_transform(tmp_path, monkeypatch):
    """
    Build an OntologiesTransform whose post-conversion steps are stubbed out.

    Returns (transform, calls) where calls['convert'] counts convert_to_json
    invocations. convert_to_json is faked to write a fresh 2026-05-19 go.json
    (what ROBOT would produce from the new go.owl).
    """
    from kg_microbe.transform_utils.ontologies import ontologies_transform as tf_mod

    calls = {"convert": 0}

    def fake_convert(path, ont):
        """Stand in for ROBOT owl->json: count the call, write a fresh go.json."""
        calls["convert"] += 1
        (Path(path) / f"{ont}.json").write_text(_JSON.format(d="2026-05-19"), encoding="utf-8")

    monkeypatch.setattr(tf_mod, "convert_to_json", fake_convert)
    monkeypatch.setattr(tf_mod, "transform", lambda **k: None)
    t = tf_mod.OntologiesTransform.__new__(tf_mod.OntologiesTransform)
    t.input_base_dir = tmp_path
    t.output_dir = tmp_path
    monkeypatch.setattr(t, "_sanitize_obograph_synonyms", lambda p: None, raising=False)
    monkeypatch.setattr(t, "_drop_deprecated_terms", lambda p: None, raising=False)
    monkeypatch.setattr(t, "post_process", lambda n: None, raising=False)
    return t, calls


def test_stale_go_json_is_removed_and_reconverted(tmp_path, monkeypatch):
    """
    A stale go.json is unlinked then regenerated — convert_to_json won't overwrite it.

    Regression for the review finding: without the unlink, convert_to_json is a
    no-op on an existing (stale) file, so a refreshed go.owl would leave the old
    go.json in place instead of self-healing.
    """
    (tmp_path / "go.owl").write_text(_OWL.format(d="2026-05-19"), encoding="utf-8")
    (tmp_path / "go.json").write_text(_JSON.format(d="2026-04-01"), encoding="utf-8")  # stale
    t, calls = _stub_go_transform(tmp_path, monkeypatch)

    t.parse("go", tmp_path / "go.owl", "go")

    assert calls["convert"] == 1
    assert ou._obo_release_from_head(tmp_path / "go.json") == "2026-05-19"  # regenerated


def test_aligned_go_json_is_not_reconverted(tmp_path, monkeypatch):
    """An already-aligned go.json is reused (no needless ROBOT reconversion)."""
    (tmp_path / "go.owl").write_text(_OWL.format(d="2026-05-19"), encoding="utf-8")
    (tmp_path / "go.json").write_text(_JSON.format(d="2026-05-19"), encoding="utf-8")  # aligned
    t, calls = _stub_go_transform(tmp_path, monkeypatch)

    t.parse("go", tmp_path / "go.owl", "go")

    assert calls["convert"] == 0


# --- gaps named in the #633 review -----------------------------------------


def test_missing_json_is_not_stale_even_with_a_gz_sibling(tmp_path):
    """_read_head falls back to `<path>.gz`, so guard the missing-JSON case (F5)."""
    import gzip as gz

    owl = tmp_path / "x.owl"
    owl.write_text(_OWL.format(d="2026-05-19"), encoding="utf-8")
    with gz.open(tmp_path / "x.json.gz", "wt", encoding="utf-8") as f:
        f.write(_JSON.format(d="2026-04-01"))

    assert ou._derived_json_is_stale(owl, tmp_path / "x.json") is False


def test_go_gate_ignores_a_missing_json_with_a_gz_sibling(tmp_path, monkeypatch):
    """The GO gate defaults to strict, so it must not abort over a file nothing reads (F8)."""
    import gzip as gz

    owl = tmp_path / "go.owl"
    owl.write_text(_OWL.format(d="2026-05-19"), encoding="utf-8")
    with gz.open(tmp_path / "go.json.gz", "wt", encoding="utf-8") as f:
        f.write(_JSON.format(d="2026-04-01"))
    monkeypatch.setattr("kg_microbe.transform_utils.constants.GO_SOURCE", owl)

    ou.assert_go_version_alignment()  # must not raise


def test_go_build_honours_the_semsql_opt_out(tmp_path, monkeypatch):
    """KG_SEMSQL_BUILD is generically named; it must gate GO too (F5)."""
    monkeypatch.setattr(ou, "_GO_DB_MIN_SIZE", 8)
    owl = tmp_path / "go.owl"
    owl.write_text(_OWL.format(d="2026-05-19"), encoding="utf-8")
    monkeypatch.setattr("kg_microbe.transform_utils.constants.GO_SOURCE", owl)
    db = tmp_path / "go.db"
    db.write_bytes(valid_db_bytes(pad=16))
    monkeypatch.setattr(ou, "_go_db_release", lambda _: "2026-01-01")  # drifted
    calls = []
    monkeypatch.setattr(ou.shutil, "which", lambda _: "/usr/bin/semsql")
    monkeypatch.setattr(ou.subprocess, "run", lambda cmd, **kw: calls.append(cmd))
    monkeypatch.setenv("KG_SEMSQL_BUILD", "off")

    assert ou._ensure_go_db(str(db))
    assert calls == [], "the opt-out must skip the GO build too"


def test_go_failed_build_restores_the_previous_db(tmp_path, monkeypatch):
    """GO was swept into the keep-aside fix but had no test for it."""
    import subprocess as sp

    monkeypatch.setattr(ou, "_GO_DB_MIN_SIZE", 8)
    owl = tmp_path / "go.owl"
    owl.write_text(_OWL.format(d="2026-05-19"), encoding="utf-8")
    monkeypatch.setattr("kg_microbe.transform_utils.constants.GO_SOURCE", owl)
    db = tmp_path / "go.db"
    db.write_bytes(valid_db_bytes(pad=16))
    original = db.read_bytes()
    monkeypatch.setattr(ou, "_go_db_release", lambda _: "2026-01-01")
    monkeypatch.setattr(ou.shutil, "which", lambda _: "/usr/bin/semsql")

    def boom(cmd, **kwargs):
        """Fail the build."""
        raise sp.CalledProcessError(1, cmd)

    monkeypatch.setattr(ou.subprocess, "run", boom)

    # The file is put back — a failed build must never cost the user their DB —
    # but GO passes reuse_on_failure=False, so the *verdict* is unusable: this
    # go.db drifted from go.owl and the rebuild that would realign it failed.
    # Reporting it usable is what silently miscategorises MF/CC as
    # BiologicalProcess, which is the whole reason GO's gate is strict.
    assert not ou._ensure_go_db(str(db))
    assert db.read_bytes() == original, "the previous go.db must be restored"
    assert not (tmp_path / "go.db.prev").exists()


def _drifted_go_db(tmp_path, monkeypatch):
    """Set up a size-valid go.db whose release has drifted from go.owl."""
    monkeypatch.setattr(ou, "_GO_DB_MIN_SIZE", 8)
    owl = tmp_path / "go.owl"
    owl.write_text(_OWL.format(d="2026-05-19"), encoding="utf-8")
    monkeypatch.setattr("kg_microbe.transform_utils.constants.GO_SOURCE", owl)
    db = tmp_path / "go.db"
    db.write_bytes(valid_db_bytes(pad=16))
    monkeypatch.setattr(ou, "_go_db_release", lambda _: "2026-01-01")
    monkeypatch.setattr(ou.shutil, "which", lambda _: "/usr/bin/semsql")
    return db


def test_go_short_build_output_is_refused_not_reused(tmp_path, monkeypatch):
    """
    `semsql` exiting 0 with a short file must not resurrect the drifted go.db.

    reuse_on_failure=False used to cover only the preflight exits (no semsql,
    missing OWL), so both post-build failure paths restored the drifted DB and
    reported usable=True — handing _ensure_and_gate exactly the DB GO's strict
    policy exists to reject.
    """
    db = _drifted_go_db(tmp_path, monkeypatch)
    original = db.read_bytes()

    def short_build(cmd, **kwargs):
        """Exit 0 having written an undersized DB."""
        db.write_bytes(b"x")

    monkeypatch.setattr(ou.subprocess, "run", short_build)

    assert not ou._ensure_go_db(str(db)), "a drifted go.db must not survive a failed rebuild"
    assert db.read_bytes() == original, "the previous go.db must still be restored on disk"


def test_non_go_ontology_still_reuses_after_a_failed_build(tmp_path, monkeypatch):
    """
    reuse_on_failure=True is the default and must be unchanged.

    Only GO demands the rebuild; for the others a restored DB after a failed
    build is still reported usable, so a transient build failure does not take
    the whole pipeline down.
    """
    monkeypatch.setattr(ou.shutil, "which", lambda _: "/usr/bin/semsql")
    owl = tmp_path / "ec.owl"
    owl.write_text("<owl/>", encoding="utf-8")
    db = tmp_path / "ec.db"
    db.write_bytes(valid_db_bytes(pad=64))

    def boom(cmd, **kwargs):
        """Fail the build."""
        raise sp_module.CalledProcessError(1, cmd)

    monkeypatch.setattr(ou.subprocess, "run", boom)

    result = ou._build_semsql_db(owl, str(db), 8, "EC", "note")
    assert result.usable and not result.built


def test_go_wrong_release_build_is_refused_not_served(tmp_path, monkeypatch):
    """
    A clean build that produces the previous release is a failed build under GO.

    `_build_confirmed` covers schema, size, content and identity, but not the
    *release* the build produced. semsql could exit 0 having read a stale plain
    OWL beside a refreshed .gz, land a complete database at the old release,
    and satisfy every acceptance check — after which `_report_release_shortfall`
    warned and the previous DB was discarded, and the transform ran against
    exactly the drifted database GO's `reuse_on_failure=False` policy exists to
    reject. Every MF/CC term the new release added would default to
    BiologicalProcess.
    """
    monkeypatch.setattr(ou, "_GO_DB_MIN_SIZE", 8)
    owl = tmp_path / "go.owl"
    owl.write_text(_OWL.format(d="2026-05-19"), encoding="utf-8")
    monkeypatch.setattr("kg_microbe.transform_utils.constants.GO_SOURCE", owl)
    db_path = tmp_path / "go.db"
    # Existing (drifted) DB at the old release — this is what a strict rebuild
    # is being demanded to replace.
    _make_go_db(tmp_path, "2026-01-01")
    previous_bytes = db_path.read_bytes()
    monkeypatch.setattr(ou.shutil, "which", lambda _: "/usr/bin/semsql")

    def build_at_the_wrong_release(cmd, **kwargs):
        """Semsql exits clean but produces a database still stamped 2026-01-01."""
        _make_go_db(Path(kwargs["cwd"]), "2026-01-01")

    monkeypatch.setattr(ou.subprocess, "run", build_at_the_wrong_release)

    assert not ou._ensure_go_db(str(db_path)), (
        "a build that produced the wrong release must not slip past reuse_on_failure=False"
    )
    assert db_path.read_bytes() == previous_bytes, "the previous drifted go.db must be restored on disk, not discarded"
    assert not (tmp_path / "go.db.prev").exists(), "and .prev must not be left orphaned"


def test_lenient_ontology_still_serves_a_wrong_release_build(tmp_path, monkeypatch):
    """
    Lenient callers keep the warn-and-accept behaviour.

    ChEBI / NCBITaxon / EC pass `reuse_on_failure=True` — a mismatched release
    is worth a warning but does not warrant refusing the pipeline. The strict
    exit added for GO must not spill over onto them.
    """
    monkeypatch.setattr(ou.shutil, "which", lambda _: "/usr/bin/semsql")
    monkeypatch.setattr(ou, "_GO_DB_MIN_SIZE", 8)
    owl = tmp_path / "go.owl"
    owl.write_text(_OWL.format(d="2026-05-19"), encoding="utf-8")
    db_path = tmp_path / "go.db"
    _make_go_db(tmp_path, "2026-01-01")

    def build_at_the_wrong_release(cmd, **kwargs):
        """Clean build; still at the old release."""
        _make_go_db(Path(kwargs["cwd"]), "2026-01-01")

    monkeypatch.setattr(ou.subprocess, "run", build_at_the_wrong_release)

    result = ou._build_semsql_db(
        owl,
        str(db_path),
        8,
        "GO",
        "n",
        reuse_on_failure=True,
        ontology="go",
        expected_release="2026-05-19",
    )
    assert result.usable and result.built, "a lenient caller must still take the build"
    assert not (tmp_path / "go.db.prev").exists(), (
        "the .prev is discarded on a served build — the strict-reject exit must not run for lenient callers"
    )


def test_unreadable_release_is_refused_by_strict_caller(tmp_path, monkeypatch):
    """
    An unreadable release stamp must not fail open under a strict caller.

    `_report_release_shortfall` used to return False both when the release
    matched and when the reader returned None (transient SQLite lock,
    unstamped DB, corrupt row). That conflated "matched" with "unverifiable"
    and let a strict caller (GO) serve a rebuild whose delivered release we
    could not confirm — silently miscategorising every MF/CC term the new
    release added as BiologicalProcess if the build had in fact produced the
    previous release. The retry helper distinguishes "match" from "unknown"
    and, on an unresolved unknown for a strict caller, treats it as a
    rejectable mismatch.
    """
    monkeypatch.setattr(ou, "_GO_DB_MIN_SIZE", 8)
    owl = tmp_path / "go.owl"
    owl.write_text(_OWL.format(d="2026-07-31"), encoding="utf-8")
    db_path = tmp_path / "go.db"  # fresh — no existing DB, so build runs
    monkeypatch.setattr(ou.shutil, "which", lambda _: "/usr/bin/semsql")

    def build(cmd, **kwargs):
        """Complete build; release stamp unreadable (simulated below)."""
        _make_go_db(Path(kwargs["cwd"]), "2026-01-01")

    monkeypatch.setattr(ou.subprocess, "run", build)
    # Reader returns None for every call — the stamp cannot be read at all,
    # even after retry (transient lock that never clears within the retry
    # budget, or an unstamped build). This is the exact fail-open shape.
    monkeypatch.setattr(ou, "_go_db_release", lambda _: None)
    # No-op sleep to keep the retry fast in tests.
    monkeypatch.setattr(ou.time, "sleep", lambda _: None)

    result = ou._build_semsql_db(
        owl,
        str(db_path),
        8,
        "GO",
        "n",
        reuse_on_failure=False,
        ontology="go",
        expected_release="2026-07-31",
    )
    assert not result.usable, "an unverifiable release must not slip past reuse_on_failure=False — unknown ≠ match"


def test_rejected_fresh_artifact_does_not_survive_to_the_next_run(tmp_path, monkeypatch):
    """
    A strict rejection with no `.prev` must not leave the DB on disk for reuse.

    `_reject_on_release_shortfall` restores whatever `_clear_build_target`
    displaced — but on a fresh build there is nothing to displace, so
    `_restore_build_target` is a no-op and the just-rejected DB stays at
    `db_path`. On the rerun, `_ensure_go_db`'s reuse fast-path finds it
    servable, cannot read the stamp (same reason it was rejected first
    time), and its rule "an unreadable stamp never forces a rebuild"
    treats it as up-to-date — silently serving the rejected DB. If that
    DB in fact holds the previous GO release, every MF/CC term the new
    release added defaults to BiologicalProcess.
    """
    monkeypatch.setattr(ou, "_GO_DB_MIN_SIZE", 8)
    owl = tmp_path / "go.owl"
    owl.write_text(_OWL.format(d="2026-07-31"), encoding="utf-8")
    monkeypatch.setattr("kg_microbe.transform_utils.constants.GO_SOURCE", owl)
    db_path = tmp_path / "go.db"  # fresh — no prior DB
    monkeypatch.setattr(ou.shutil, "which", lambda _: "/usr/bin/semsql")

    build_calls = []

    def build(cmd, **kwargs):
        """Simulate `semsql make` producing a complete-but-wrong-release DB."""
        build_calls.append(cmd)
        _make_go_db(Path(kwargs["cwd"]), "2026-01-01")

    monkeypatch.setattr(ou.subprocess, "run", build)
    # Stamp reader always None: retries exhausted, strict caller rejects.
    monkeypatch.setattr(ou, "_go_db_release", lambda _: None)
    monkeypatch.setattr(ou.time, "sleep", lambda _: None)

    first = ou._ensure_go_db(str(db_path))
    assert not first, "first call must reject an unverifiable-release build"
    assert not db_path.exists(), (
        "the rejected fresh artifact must be removed — else the next run's reuse "
        "gate serves it despite the just-emitted rejection"
    )

    second = ou._ensure_go_db(str(db_path))
    assert not second, "second call must not accept the previously-rejected artifact"
    assert len(build_calls) == 2, (
        "both calls must attempt to rebuild — the second one is not a shortcut "
        "past the strict gate on a leftover artifact"
    )


def test_unreadable_release_still_served_by_lenient_caller(tmp_path, monkeypatch):
    """
    Lenient callers must not be dragged into the strict-reject path.

    ChEBI / NCBITaxon / EC accept an unverifiable release with a warning —
    they explicitly `reuse_on_failure=True`. The strict retry-then-refuse
    added for GO must not spill over onto them.
    """
    monkeypatch.setattr(ou, "_GO_DB_MIN_SIZE", 8)
    owl = tmp_path / "go.owl"
    owl.write_text(_OWL.format(d="2026-07-31"), encoding="utf-8")
    db_path = tmp_path / "go.db"
    monkeypatch.setattr(ou.shutil, "which", lambda _: "/usr/bin/semsql")

    def build(cmd, **kwargs):
        """Simulate a `semsql make` that produces a wrong-release DB."""
        _make_go_db(Path(kwargs["cwd"]), "2026-01-01")

    monkeypatch.setattr(ou.subprocess, "run", build)
    monkeypatch.setattr(ou, "_go_db_release", lambda _: None)
    monkeypatch.setattr(ou.time, "sleep", lambda _: None)

    result = ou._build_semsql_db(
        owl,
        str(db_path),
        8,
        "GO",
        "n",
        reuse_on_failure=True,
        ontology="go",
        expected_release="2026-07-31",
    )
    assert result.usable and result.built, "a lenient caller keeps an unverifiable-release build"


def test_transient_stamp_lock_resolves_on_retry_and_serves(tmp_path, monkeypatch):
    """
    A transient stamp read failure must not reject a build whose release is fine.

    The strict-caller retry exists to survive a momentary SQLite lock on the
    release read — the same reason `_servable_db` retries schema and identity.
    If the retry eventually reads the expected release, the build is served
    normally.
    """
    monkeypatch.setattr(ou, "_GO_DB_MIN_SIZE", 8)
    owl = tmp_path / "go.owl"
    owl.write_text(_OWL.format(d="2026-07-31"), encoding="utf-8")
    db_path = tmp_path / "go.db"
    monkeypatch.setattr(ou.shutil, "which", lambda _: "/usr/bin/semsql")

    def build(cmd, **kwargs):
        """Complete GO build at the expected release."""
        _make_go_db(Path(kwargs["cwd"]), "2026-07-31")

    monkeypatch.setattr(ou.subprocess, "run", build)

    # First stamp read returns None (locked); subsequent reads succeed.
    calls = {"n": 0}
    real_release = ou._go_db_release

    def flaky_reader(path):
        """First stamp read is locked (None); later reads succeed."""
        calls["n"] += 1
        if calls["n"] == 1:
            return None
        return real_release(path)

    monkeypatch.setattr(ou, "_go_db_release", flaky_reader)
    monkeypatch.setattr(ou.time, "sleep", lambda _: None)

    result = ou._build_semsql_db(
        owl,
        str(db_path),
        8,
        "GO",
        "n",
        reuse_on_failure=False,
        ontology="go",
        expected_release="2026-07-31",
    )
    assert result.usable and result.built, "a stamp read that recovers on retry must let the build serve"
    assert calls["n"] >= 2, "the retry must have run at least once"


def test_wrong_release_via_recovered_servability_is_also_refused(tmp_path, monkeypatch):
    """
    The confirmed=None → recovered-servability path must gate on release too.

    `_build_confirmed` returns tri-state: True/False/None. Round 23 tightened
    the True branch to honour reuse_on_failure=False on a wrong-release build,
    but the None branch (`_has_semsql_schema` couldn't be established, usually
    because a SQLite lock made the probe transient) recovered by returning
    `usable=_servable_db(...)` — a predicate that says nothing about the
    release stamp. So a build that produced the previous GO release, where
    the initial schema probe happened to hit a lock, was still served from
    that recovery exit — silently miscategorising every MF/CC term the new
    release added as BiologicalProcess.
    """
    monkeypatch.setattr(ou, "_GO_DB_MIN_SIZE", 8)
    owl = tmp_path / "go.owl"
    owl.write_text(_OWL.format(d="2026-05-19"), encoding="utf-8")
    monkeypatch.setattr("kg_microbe.transform_utils.constants.GO_SOURCE", owl)
    db_path = tmp_path / "go.db"
    _make_go_db(tmp_path, "2026-01-01")
    previous_bytes = db_path.read_bytes()
    monkeypatch.setattr(ou.shutil, "which", lambda _: "/usr/bin/semsql")

    def build_at_the_wrong_release(cmd, **kwargs):
        """Clean build; still at the old release."""
        _make_go_db(Path(kwargs["cwd"]), "2026-01-01")

    monkeypatch.setattr(ou.subprocess, "run", build_at_the_wrong_release)
    # Force the confirmed=None branch: schema probe indeterminate under lock.
    monkeypatch.setattr(ou, "_build_confirmed", lambda *a, **k: None)

    assert not ou._ensure_go_db(str(db_path)), (
        "a wrong-release build must not slip past the strict gate through the recovery exit either"
    )
    assert db_path.read_bytes() == previous_bytes, "the previous drifted go.db must be restored on disk"
    assert not (tmp_path / "go.db.prev").exists(), "and .prev must not be left orphaned"
