"""Tests for the GO version-alignment gate and go.db build helper (#604)."""

from pathlib import Path

import pytest

from kg_microbe.utils import ontology_utils as ou

_OWL = '<owl versionIRI rdf:resource="http://purl.obolibrary.org/obo/go/releases/{d}/go.owl"/>'
_JSON = '{{"meta":{{"basicPropertyValues":[{{"pred":"owl#versionInfo","val":"{d}"}}]}}}}'


def _write_go_pair(tmp_path: Path, owl_date: str, json_date: str) -> Path:
    """Write minimal go.owl / go.json with the given release stamps; return go.owl path."""
    (tmp_path / "go.owl").write_text(_OWL.format(d=owl_date), encoding="utf-8")
    (tmp_path / "go.json").write_text(_JSON.format(d=json_date), encoding="utf-8")
    return tmp_path / "go.owl"


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


def test_aligned_versions_do_not_raise(tmp_path, monkeypatch):
    """Matching go.owl / go.json releases pass the gate silently."""
    owl = _write_go_pair(tmp_path, "2026-05-19", "2026-05-19")
    monkeypatch.setattr("kg_microbe.transform_utils.constants.GO_SOURCE", owl)
    ou.assert_go_version_alignment(strict=True)  # must not raise


def test_mismatch_raises_in_strict_mode(tmp_path, monkeypatch):
    """Divergent go.owl / go.json releases fail loudly under strict."""
    owl = _write_go_pair(tmp_path, "2026-05-19", "2026-04-01")
    monkeypatch.setattr("kg_microbe.transform_utils.constants.GO_SOURCE", owl)
    with pytest.raises(RuntimeError, match="GO source version mismatch"):
        ou.assert_go_version_alignment(strict=True)


def test_mismatch_warns_when_not_strict(tmp_path, monkeypatch, capsys):
    """Under strict=False a mismatch warns instead of raising."""
    owl = _write_go_pair(tmp_path, "2026-05-19", "2026-04-01")
    monkeypatch.setattr("kg_microbe.transform_utils.constants.GO_SOURCE", owl)
    ou.assert_go_version_alignment(strict=False)  # no raise
    assert "GO source version mismatch" in capsys.readouterr().out


def test_missing_source_is_a_noop(tmp_path, monkeypatch):
    """When a GO source can't be read, the gate is a no-op (can't judge)."""
    monkeypatch.setattr(
        "kg_microbe.transform_utils.constants.GO_SOURCE", tmp_path / "absent.owl"
    )
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
    db = tmp_path / "go.db"
    db.write_bytes(b"0" * 16)
    # GO_SOURCE need not exist — the valid-db short-circuit returns before using it.
    assert ou._ensure_go_db(str(db)) is True


def test_ensure_go_db_cannot_build_without_owl(tmp_path, monkeypatch, capsys):
    """A missing/empty go.db with no OWL source degrades gracefully (warn, False)."""
    monkeypatch.setattr(
        "kg_microbe.transform_utils.constants.GO_SOURCE", tmp_path / "absent.owl"
    )
    assert ou._ensure_go_db(str(tmp_path / "go.db")) is False
    assert "missing" in capsys.readouterr().out
