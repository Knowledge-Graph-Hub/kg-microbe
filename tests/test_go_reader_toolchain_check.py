"""Readers that open go.db directly refuse one this toolchain did not build, without rebuilding it (#1641)."""

import pytest

from kg_microbe.utils import ontology_utils as ou
from kg_microbe.utils.semsql_toolchain import write_record
from tests.db_helpers import FIXED_SEMSQL_TOOLCHAIN, write_single_ontology_db

pytestmark = pytest.mark.semsql_toolchain_check


@pytest.fixture
def toolchain(monkeypatch):
    """Probe a fixed, complete toolchain instead of this machine's."""
    monkeypatch.setattr(ou, "current_toolchain", lambda raw_dir, env: dict(FIXED_SEMSQL_TOOLCHAIN))
    monkeypatch.setattr(ou, "_TOOLCHAIN_PROBES", {})
    monkeypatch.setattr(ou, "_TOOLCHAIN_WARNED", set())
    monkeypatch.delenv("KG_SEMSQL_BUILD", raising=False)


def _no_build(*args, **kwargs):
    """Fail if a reader tries to build."""
    raise AssertionError("a reader must not build a SemSQL DB")


def test_a_go_db_this_toolchain_built_is_read(tmp_path, toolchain, monkeypatch):
    """A matching record is all a reader needs."""
    db = write_single_ontology_db(tmp_path / "go.db", "go")
    write_record(db, FIXED_SEMSQL_TOOLCHAIN)
    monkeypatch.setattr(ou, "_build_semsql_db", _no_build)
    ou.check_reused_semsql_db(db, tmp_path, strict=True)


def test_a_go_db_with_no_record_is_refused_not_rebuilt(tmp_path, toolchain, monkeypatch):
    """`kg transform -s upa` or rhea_mappings alone used to read it unchecked."""
    db = write_single_ontology_db(tmp_path / "go.db", "go")
    monkeypatch.setattr(ou, "_build_semsql_db", _no_build)
    with pytest.raises(ou.OntologyDbUnavailableError, match="kg transform -s go") as info:
        ou.check_reused_semsql_db(db, tmp_path, strict=True)
    assert "no toolchain record" in str(info.value)


def test_a_go_db_another_toolchain_built_is_refused(tmp_path, toolchain):
    """A record naming another relation-graph does not vouch here."""
    db = write_single_ontology_db(tmp_path / "go.db", "go")
    other = {**FIXED_SEMSQL_TOOLCHAIN, "relation_graph": {"path": "/x", "version": "2.3.1", "sha256": "9" * 64}}
    write_record(db, other)
    with pytest.raises(ou.OntologyDbUnavailableError, match="relation"):
        ou.check_reused_semsql_db(db, tmp_path, strict=True)


def test_other_dbs_only_warn_once(tmp_path, toolchain, capsys):
    """chebi.db and ec.db take hours to rebuild; a reader reports and reads them, as the build path does."""
    db = write_single_ontology_db(tmp_path / "ec.db", "ec")
    ou.check_reused_semsql_db(db, tmp_path, strict=False)
    ou.check_reused_semsql_db(db, tmp_path, strict=False)
    assert capsys.readouterr().out.count("which this toolchain did not build") == 1


def test_the_opt_out_accepts_any_go_db(tmp_path, toolchain, monkeypatch):
    """KG_SEMSQL_BUILD=off accepts prebuilt DBs and their toolchain, for readers too."""
    monkeypatch.setenv("KG_SEMSQL_BUILD", "off")
    db = write_single_ontology_db(tmp_path / "go.db", "go")
    ou.check_reused_semsql_db(db, tmp_path, strict=True)


def test_upa_refuses_a_go_db_with_no_record(tmp_path, monkeypatch, toolchain):
    """The UPA producer reads go.db directly; it now refuses one no toolchain record vouches for."""
    from tests.upa_route_fixtures import run_upa

    with pytest.raises(ou.OntologyDbUnavailableError, match="was not built by this machine's toolchain"):
        run_upa(tmp_path, monkeypatch)


def test_rhea_labels_refuse_a_go_db_with_no_record(tmp_path, toolchain):
    """Rhea's label lookup reads go.db directly; it refuses it, and only warns for chebi.db and ec.db."""
    from kg_microbe.transform_utils.rhea_mappings.label_inputs import external_label_lookup
    from kg_microbe.transform_utils.transform import Transform
    from tests.rhea_fixtures import stage_rhea_label_databases

    raw = tmp_path / "raw"
    stage_rhea_label_databases(raw)
    transform = Transform("rhea_mappings", raw, tmp_path / "out")
    with pytest.raises(ou.OntologyDbUnavailableError, match="go.db was not built"):
        with external_label_lookup(transform):
            pass
