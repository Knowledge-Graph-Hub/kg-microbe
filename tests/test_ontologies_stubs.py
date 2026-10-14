"""Tests for the OntologiesStubsTransform."""

from __future__ import annotations

import csv
import gzip
import sqlite3
import zipfile
from pathlib import Path
from typing import Dict, List, Set

import pytest
from sqlalchemy.exc import OperationalError

from kg_microbe.transform_utils.constants import (
    MICRO_IMPORT_MODULES,
    MICRO_IMPORTS_DIR,
    PO_IMPORT_MODULES,
    PO_IMPORTS_DIR,
    PO_VERSION_IRI,
)
from kg_microbe.transform_utils.ontologies_stubs import ontologies_stubs_transform as stubs_module
from kg_microbe.transform_utils.ontologies_stubs.ontologies_stubs_transform import (
    STUB_ONTOLOGY_SOURCES,
    OntologiesStubsTransform,
    _curie_to_iris,
    _declared_imports,
    _iri_to_curie,
    _retag_curie,
    _sanitize,
    _write_import_catalog,
)
from kg_microbe.utils import robot_utils
from kg_microbe.utils.isolation_source_mapping_utils import (
    STUB_ONTOLOGY_CATEGORY,
    STUB_ONTOLOGY_PREFIXES,
)
from kg_microbe.utils.ontology_utils import OntologyDbUnavailableError
from kg_microbe.utils.robot_utils import ROBOT_JAXP_LIMITS
from kg_microbe.utils.stub_curie_collection import collect_stub_curies

REPO_ROOT = Path(__file__).resolve().parents[1]
SQLITE_HEADER = b"SQLite format 3\x00"
# The head of the pinned MicrO.owl (MICRO_COMMIT): its DOCTYPE, namespaces and
# 20 owl:imports, without the ontology annotations.
MICRO_OWL_HEADER = REPO_ROOT / "tests" / "resources" / "micro" / "micro_owl_header.owl"
# The head of the pinned po.owl (PO_RELEASE): its namespaces, versionIRI, two
# owl:imports and ontology annotations.
PO_OWL_HEADER = REPO_ROOT / "tests" / "resources" / "po" / "po_owl_header.owl"
# Each pinned source: its ontology file, imports directory, header and pinned modules.
PINNED_IMPORTS = {
    "PO": ("po.owl", PO_IMPORTS_DIR, PO_OWL_HEADER, PO_IMPORT_MODULES),
    "MICRO": ("micro.owl", MICRO_IMPORTS_DIR, MICRO_OWL_HEADER, MICRO_IMPORT_MODULES),
}
# The concrete settings that keep a catalog run offline, spelled out rather than
# compared with the constant, so trimming the constant cannot pass unnoticed.
OFFLINE_FLAGS = (
    "-Dhttps.proxyHost=127.0.0.1",
    "-Dhttp.proxyHost=127.0.0.1",
    "-Dhttp.nonProxyHosts=",
    "-DsocksProxyHost=127.0.0.1",
)


# ---------------------------------------------------------------------------
# In-memory fakes
# ---------------------------------------------------------------------------


class _FakeAdapter:
    """Minimal stand-in for an OAK SemSQL adapter — enough for the stub transform."""

    def __init__(self, store: Dict[str, Dict]):
        """Wrap an in-memory ``{curie: {label, aliases, xrefs}}`` map."""
        self._store = store

    def label(self, curie: str):
        """Return the stored label for ``curie`` (``""`` if unknown)."""
        return self._store.get(curie, {}).get("label", "")

    def entity_aliases(self, curie: str):
        """Return the stored aliases list for ``curie``."""
        return list(self._store.get(curie, {}).get("aliases", []))

    def entity_metadata_map(self, curie: str):
        """Return OAK-shaped xrefs and any additional annotation properties."""
        xrefs = list(self._store.get(curie, {}).get("xrefs", []))
        metadata = dict(self._store.get(curie, {}).get("metadata", {}))
        if xrefs:
            metadata["oio:hasDbXref"] = xrefs
        return metadata

    def outgoing_relationships(self, curie: str, predicates=None):
        """Return explicitly stored parents for the hierarchy export tests."""
        return [("rdfs:subClassOf", parent) for parent in self._store.get(curie, {}).get("parents", [])]


class _StubbedTransform(OntologiesStubsTransform):
    """Subclass that swaps in an in-memory adapter so semsql tests don't touch DBs on disk."""

    def __init__(
        self,
        *,
        adapters: Dict[str, _FakeAdapter],
        curies: Dict[str, Set[str]],
        input_dir: Path,
        output_dir: Path,
    ):
        """Wire fake adapters and a pre-seeded CURIE set; skip filesystem CURIE discovery."""
        super().__init__(input_dir=input_dir, output_dir=output_dir)
        self._fake_adapters = adapters
        self._fake_curies = curies

    def _open_adapter(self, prefix, db_path):  # noqa: D401 — override
        """Return the injected fake adapter for ``prefix`` (None if not stubbed)."""
        return self._fake_adapters.get(prefix)

    def run(self, data_file=None, **kwargs):  # noqa: D401 — override
        """Run only the semsql branch against the injected fake adapters + CURIE set."""
        # Bypass collect_stub_curies (we inject a curated set instead). Only the
        # semsql branch is exercised here — the owl_mireot branch is covered
        # via dedicated unit tests below.
        for prefix, curies in self._fake_curies.items():
            cfg = STUB_ONTOLOGY_SOURCES.get(prefix)
            if cfg is None or cfg.get("source_type", "semsql") != "semsql":
                continue
            output_file = self.output_dir / f"{prefix.lower()}_nodes.tsv"
            self._write_stub_nodes_from_semsql(
                prefix=prefix,
                curies=sorted(curies),
                db_path=self.input_base_dir / cfg["db_filename"],
                knowledge_source=cfg["knowledge_source"],
                output_file=output_file,
            )


def _read_tsv(path: Path) -> List[Dict[str, str]]:
    with path.open("r", encoding="utf-8") as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


# ---------------------------------------------------------------------------
# Static / config tests
# ---------------------------------------------------------------------------


def test_stub_ontology_sources_subset_of_stub_prefixes():
    """Every prefix the new transform handles must be a recognized stub prefix."""
    assert set(STUB_ONTOLOGY_SOURCES.keys()).issubset(STUB_ONTOLOGY_PREFIXES)


def test_stub_ontology_sources_covers_ncit_mesh_bto_po_micro():
    """
    Cover the five prefixes that need full metadata-enriched stub emission.

    NCIT and mesh were added in the initial commit; BTO was added after the
    MIM 2026-05-18 republish brought in `BTO:0004304 cell lysate`, doubling
    the BTO footprint and crossing the "worth a SemSQL fetch" threshold;
    PO and MICRO were promoted from full-ontology loading to the per-CURIE
    stub path shortly after, then upgraded again to ``owl_mireot`` so they
    also carry the ancestor chain (with biolink:subclass_of edges) under a
    curated upper term.
    """
    assert set(STUB_ONTOLOGY_SOURCES.keys()) == {"NCIT", "mesh", "BTO", "PO", "MICRO"}


def test_semsql_sources_use_db_files():
    """BTO uses the label-only SemSQL adapter against a .db file (mesh moved off this path)."""
    for prefix in ("BTO",):
        cfg = STUB_ONTOLOGY_SOURCES[prefix]
        # source_type may be absent (defaults to semsql) or explicit "semsql".
        assert cfg.get("source_type", "semsql") == "semsql"
        assert cfg["db_filename"].endswith(".db")


def test_mesh_uses_nt_rdf_source():
    """The mesh entry must read the NLM N-Triples RDF (bbop-sqlite mesh.db strips C-record relations)."""
    cfg = STUB_ONTOLOGY_SOURCES["mesh"]
    assert cfg["source_type"] == "mesh_nt_rdf"
    assert cfg["nt_filename"].endswith(".nt.gz")
    assert cfg["nt_filename"].startswith("mesh")


def test_owl_mireot_sources_carry_owl_and_upper_term():
    """PO and MICRO must dispatch to ROBOT MIREOT against a downloaded OWL under a curated root."""
    for prefix, expected_owl, expected_upper in (
        ("PO", "po.owl", "PO:0025131"),
        ("MICRO", "micro.owl", "MICRO:0000031"),
    ):
        cfg = STUB_ONTOLOGY_SOURCES[prefix]
        assert cfg["source_type"] == "owl_mireot"
        assert cfg["owl_filename"] == expected_owl
        assert cfg["upper_term"] == expected_upper


def test_ncit_semsql_mireot_carries_multi_upper_terms():
    """NCIT must walk SemSQL ancestors under multiple curated upper-terms."""
    cfg = STUB_ONTOLOGY_SOURCES["NCIT"]
    assert cfg["source_type"] == "semsql_mireot"
    assert cfg["db_filename"] == "ncit.db"
    uppers = cfg["upper_terms"]
    assert isinstance(uppers, list) and len(uppers) >= 5
    # Every upper-term is a well-formed NCIT CURIE.
    assert all(u.startswith("NCIT:") for u in uppers)
    # The bulk-carrier upper-term must be present — covers ~48/73 stubs.
    assert "NCIT:C1908" in uppers  # Drug, Food, Chemical or Biomedical Material


# ---------------------------------------------------------------------------
# Transform behaviour with in-memory adapter (semsql branch)
# ---------------------------------------------------------------------------


def test_transform_writes_label_synonyms_xrefs(tmp_path):
    """A CURIE with full metadata in the fake adapter must round-trip into the TSV."""
    # Use BTO, which stays on the label-only semsql path that this helper exercises.
    # (NCIT moved to semsql_mireot and writes both nodes + edges via a different path.)
    adapters = {
        "BTO": _FakeAdapter(
            {
                "BTO:0003114": {
                    "label": "wound fluid",
                    "aliases": ["wound exudate", "exudate"],
                    "xrefs": ["MESH:D015159", "wikipedia:Wound_fluid"],
                },
            }
        ),
    }
    curies = {"BTO": {"BTO:0003114"}}
    t = _StubbedTransform(adapters=adapters, curies=curies, input_dir=tmp_path / "in", output_dir=tmp_path / "out")
    (tmp_path / "in").mkdir()
    t.run()
    rows = _read_tsv(tmp_path / "out" / "ontologies_stubs" / "bto_nodes.tsv")
    assert len(rows) == 1
    row = rows[0]
    assert row["id"] == "BTO:0003114"
    assert row["category"] == STUB_ONTOLOGY_CATEGORY
    assert row["name"] == "wound fluid"
    assert "wound exudate" in row["synonym"].split("|")
    assert "MESH:D015159" in row["xref"].split("|")


@pytest.mark.parametrize(
    "predicate",
    ["NCIT:P210", "http://ncicb.nci.nih.gov/xml/owl/EVS/Thesaurus.owl#P210"],
)
def test_ncit_cas_annotations_reach_node_xrefs_without_identity_edges(tmp_path, monkeypatch, predicate):
    """Keep source CAS annotations on the original nodes, separate from equivalence."""
    fixtures = _read_tsv(REPO_ROOT / "tests/resources/ontologies_stubs/ncit_cas_annotations.tsv")
    parent = "NCIT:C1908"
    records = {
        row["id"]: {
            "label": row["name"],
            "metadata": {predicate: [row["cas_rn"]]},
            "parents": [parent],
        }
        for row in fixtures
    }
    records[parent] = {"label": "Drug, Food, Chemical or Biomedical Material"}
    adapter = _FakeAdapter(records)
    transform = OntologiesStubsTransform(input_dir=tmp_path / "in", output_dir=tmp_path / "out")
    monkeypatch.setattr(transform, "_open_adapter", lambda prefix, path: adapter)
    transform._write_stub_module_from_semsql_walk(
        prefix="NCIT",
        curies=[row["id"] for row in fixtures],
        db_path=tmp_path / "unused.db",
        upper_terms=[parent],
        knowledge_source="infores:ncit",
    )
    nodes = {row["id"]: row for row in _read_tsv(transform.output_dir / "ncit_nodes.tsv")}
    assert set(nodes) == set(records)
    for row in fixtures:
        node = nodes[row["id"]]
        assert node["xref"] == f"cas:{row['cas_rn']}"
        assert node["name"] == row["name"]
        assert node["same_as"] == ""
    assert nodes[parent]["xref"] == ""
    assert "cas:8048-52-0" not in nodes["NCIT:C76253"]["xref"].split("|")
    edges = _read_tsv(transform.output_dir / "ncit_edges.tsv")
    assert len(edges) == len(fixtures)
    assert {row["predicate"] for row in edges} == {"biolink:subclass_of"}
    assert {row["object"] for row in edges} == {parent}


@pytest.mark.parametrize("value", ["2650-88-3", "00123-45-6", "187235376", "cas:187235-37-6", "", None, 123])
def test_invalid_cas_annotation_does_not_become_xref(tmp_path, value):
    """Malformed or checksum-invalid registry values stay out of exported CAS xrefs."""
    adapter = _FakeAdapter({"NCIT:example": {"metadata": {"NCIT:P210": [value]}}})
    transform = OntologiesStubsTransform(input_dir=tmp_path / "in", output_dir=tmp_path / "out")
    assert transform._fetch_metadata(adapter, "NCIT:example")[2] == []


def test_transform_falls_back_to_curie_when_label_missing(tmp_path):
    """Missing label must NOT produce an empty `name` cell — fall back to the CURIE."""
    adapters = {"BTO": _FakeAdapter({})}  # adapter knows nothing
    curies = {"BTO": {"BTO:9999999"}}
    t = _StubbedTransform(adapters=adapters, curies=curies, input_dir=tmp_path / "in", output_dir=tmp_path / "out")
    (tmp_path / "in").mkdir()
    t.run()
    rows = _read_tsv(tmp_path / "out" / "ontologies_stubs" / "bto_nodes.tsv")
    assert len(rows) == 1
    assert rows[0]["name"] == "BTO:9999999"  # falls back to the CURIE itself


#: The two shapes a failed SemSQL read takes: raised by sqlite3 directly, or wrapped by SQLAlchemy.
_DATABASE_ERRORS = {
    "sqlite3": lambda: sqlite3.OperationalError("disk I/O error"),
    "sqlalchemy": lambda: OperationalError("SELECT 1", {}, sqlite3.OperationalError("disk I/O error")),
}


def _unreadable(error):
    """Build a lookup that fails as SemSQL does once its database file has been replaced."""

    def lookup(*args, **kwargs):
        """Raise the database error."""
        raise error

    return lookup


@pytest.mark.parametrize("make_error", list(_DATABASE_ERRORS.values()), ids=list(_DATABASE_ERRORS))
@pytest.mark.parametrize("method", ["label", "entity_aliases", "entity_metadata_map"])
def test_a_database_error_aborts_instead_of_naming_stubs_by_identifier(tmp_path, monkeypatch, method, make_error):
    """
    A database error is the ontology becoming unreadable, not a term it lacks (#1604).

    Absorbed per term, a bto.db replaced during the run wrote every stub with its
    identifier as its name, and the run exited 0.
    """
    error = make_error()
    adapter = _FakeAdapter({"BTO:0003114": {"label": "wound fluid"}})
    monkeypatch.setattr(adapter, method, _unreadable(error))
    t = _StubbedTransform(
        adapters={"BTO": adapter},
        curies={"BTO": {"BTO:0003114"}},
        input_dir=tmp_path / "in",
        output_dir=tmp_path / "out",
    )
    (tmp_path / "in").mkdir()
    with pytest.raises(OntologyDbUnavailableError) as raised:
        t.run()
    assert raised.value.__cause__ is error
    assert t._consumed_input_error == f"{type(error).__name__}: {error}"
    assert not (tmp_path / "out" / "ontologies_stubs" / "bto_nodes.tsv").exists()


def test_a_memory_error_is_re_raised_unchanged(tmp_path, monkeypatch):
    """SQLite running out of memory is not a missing term either, but it is not a database failure to report."""
    error = MemoryError()
    adapter = _FakeAdapter({"BTO:0003114": {"label": "wound fluid"}})
    monkeypatch.setattr(adapter, "label", _unreadable(error))
    t = _StubbedTransform(
        adapters={"BTO": adapter},
        curies={"BTO": {"BTO:0003114"}},
        input_dir=tmp_path / "in",
        output_dir=tmp_path / "out",
    )
    (tmp_path / "in").mkdir()
    with pytest.raises(MemoryError) as raised:
        t.run()
    assert raised.value is error
    assert t._consumed_input_error == "MemoryError: "
    assert not (tmp_path / "out" / "ontologies_stubs" / "bto_nodes.tsv").exists()


@pytest.mark.parametrize("make_error", list(_DATABASE_ERRORS.values()), ids=list(_DATABASE_ERRORS))
def test_a_database_error_in_the_hierarchy_walk_aborts(tmp_path, monkeypatch, make_error):
    """The subclass walk refuses a database error the same way, for a term outside the reviewed categories."""
    error = make_error()
    adapter = _FakeAdapter({"NCIT:C2000": {"label": "child", "parents": ["NCIT:C1000"]}})
    monkeypatch.setattr(adapter, "outgoing_relationships", _unreadable(error))
    t = _StubbedTransform(adapters={"NCIT": adapter}, curies={}, input_dir=tmp_path / "in", output_dir=tmp_path / "out")
    (tmp_path / "in").mkdir()
    with pytest.raises(OntologyDbUnavailableError) as raised:
        t._write_stub_module_from_semsql_walk(
            prefix="NCIT",
            curies=["NCIT:C2000"],
            db_path=tmp_path / "in" / "ncit.db",
            upper_terms=["NCIT:C1000"],
            knowledge_source="infores:ncit",
        )
    assert raised.value.__cause__ is error
    assert t._consumed_input_error == f"{type(error).__name__}: {error}"
    assert not list((tmp_path / "out" / "ontologies_stubs").glob("ncit_*.tsv"))


def _not_semsql(path):
    """Write a valid SQLite file that holds no SemSQL tables."""
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE unrelated (x)")
    connection.close()


@pytest.mark.parametrize(
    "damage",
    [lambda path: path.write_bytes(b"not a database " * 1000), _not_semsql],
    ids=["garbage", "not-semsql"],
)
def test_a_damaged_database_stops_the_run_through_real_oak(tmp_path, damage):
    """
    Nothing is injected: a damaged bto.db reaches real OAK, and its errors are not missing terms.

    Before #1604 each lookup's error was absorbed, so every stub was named by its identifier.
    """
    raw = tmp_path / "raw"
    raw.mkdir()
    damage(raw / "bto.db")
    transform = OntologiesStubsTransform(input_dir=raw, output_dir=tmp_path / "out")
    output = transform.output_dir / "bto_nodes.tsv"
    with pytest.raises(OntologyDbUnavailableError, match="BTO:0003114") as raised:
        transform._write_stub_nodes_from_semsql(
            prefix="BTO",
            curies=["BTO:0003114"],
            db_path=raw / "bto.db",
            knowledge_source="infores:bto",
            output_file=output,
        )
    assert "bto.db" in str(raised.value)
    assert transform._consumed_input_error
    assert not output.exists()


def test_a_lookup_error_that_is_not_a_database_error_still_falls_back(tmp_path, monkeypatch):
    """Only database errors abort; any other lookup error keeps the identifier fallback, as before #1604."""
    adapter = _FakeAdapter({})
    monkeypatch.setattr(adapter, "label", _unreadable(ValueError("not a term this adapter can read")))
    t = _StubbedTransform(
        adapters={"BTO": adapter},
        curies={"BTO": {"BTO:9999999"}},
        input_dir=tmp_path / "in",
        output_dir=tmp_path / "out",
    )
    (tmp_path / "in").mkdir()
    t.run()
    rows = _read_tsv(tmp_path / "out" / "ontologies_stubs" / "bto_nodes.tsv")
    assert [row["name"] for row in rows] == ["BTO:9999999"]


def test_transform_writes_empty_tsv_when_no_curies(tmp_path):
    """No CURIEs → empty file with header (so merge.yaml's filename declaration is satisfied)."""
    adapters = {"BTO": _FakeAdapter({})}
    curies = {"BTO": set()}
    t = _StubbedTransform(adapters=adapters, curies=curies, input_dir=tmp_path / "in", output_dir=tmp_path / "out")
    (tmp_path / "in").mkdir()
    t.run()
    out = tmp_path / "out" / "ontologies_stubs"
    assert (out / "bto_nodes.tsv").is_file()
    assert _read_tsv(out / "bto_nodes.tsv") == []


def test_transform_synonym_does_not_duplicate_label(tmp_path):
    """If an alias equals the label, drop it from the synonym set (keep them disjoint)."""
    adapters = {
        "BTO": _FakeAdapter(
            {
                "BTO:0003114": {
                    "label": "wound fluid",
                    "aliases": ["wound fluid", "wound exudate"],
                    "xrefs": [],
                },
            }
        ),
    }
    curies = {"BTO": {"BTO:0003114"}}
    t = _StubbedTransform(adapters=adapters, curies=curies, input_dir=tmp_path / "in", output_dir=tmp_path / "out")
    (tmp_path / "in").mkdir()
    t.run()
    rows = _read_tsv(tmp_path / "out" / "ontologies_stubs" / "bto_nodes.tsv")
    assert rows[0]["name"] == "wound fluid"
    assert rows[0]["synonym"] == "wound exudate"


def test_transform_raises_when_db_missing(tmp_path):
    """SemSQL prefix with neither .db nor .db.gz fails loudly with a SemSQL-specific message."""
    transform = OntologiesStubsTransform(
        input_dir=tmp_path / "raw",  # empty
        output_dir=tmp_path / "out",
    )
    (tmp_path / "raw").mkdir()
    with pytest.raises(FileNotFoundError, match="SemSQL DB.*ncit.db"):
        transform._write_stub_nodes_from_semsql(
            prefix="NCIT",
            curies=["NCIT:C29298"],
            db_path=tmp_path / "raw" / "ncit.db",
            knowledge_source="infores:ncit",
            output_file=tmp_path / "out" / "ncit_nodes.tsv",
        )


def test_transform_raises_when_mireot_owl_missing(tmp_path):
    """owl_mireot prefix with no OWL on disk fails with a MIREOT-specific message."""
    transform = OntologiesStubsTransform(
        input_dir=tmp_path / "raw",  # empty
        output_dir=tmp_path / "out",
    )
    (tmp_path / "raw").mkdir()
    with pytest.raises(FileNotFoundError, match="MIREOT extraction.*micro.owl"):
        transform._write_stub_module_from_mireot(
            prefix="MICRO",
            curies=["MICRO:0000082"],
            owl_path=tmp_path / "raw" / "micro.owl",
            upper_term="MICRO:0000031",
            knowledge_source="infores:micro",
            imports_dir=tmp_path / "raw" / MICRO_IMPORTS_DIR,
        )


def test_mireot_intermediate_is_rdfxml_not_functional_syntax(tmp_path, monkeypatch):
    """
    ROBOT cannot re-read the `.ofn` it writes for this content (#986).

    Once the MICRO module carried literals with embedded newlines and a
    trademark sign, every OWLAPI parser rejected ROBOT's own functional-syntax
    output and the convert step died with INVALID ONTOLOGY FILE ERROR. RDF/XML
    round-trips the same module, so the extract must be written as `.owl` and
    the convert must read that same file.
    """
    import subprocess

    calls = []

    def fake_run(cmd, check, env=None):
        """Capture the ROBOT command without launching it."""
        calls.append(list(cmd))
        return None

    monkeypatch.setattr(robot_utils, "_java_runs", lambda: True)
    monkeypatch.setattr(subprocess, "run", fake_run)
    _pinned_robot(tmp_path / "raw")
    transform = OntologiesStubsTransform(input_dir=tmp_path / "raw", output_dir=tmp_path / "out")
    transform.output_dir.mkdir(parents=True, exist_ok=True)
    stale = transform.output_dir / "micro_mireot_module.ofn"
    stale.write_text("Ontology()\n", encoding="utf-8")
    module_json = transform._run_mireot_extract(
        prefix="MICRO",
        lower_curies=["MICRO:0000082"],
        upper_curie="MICRO:0000031",
        owl_path=tmp_path / "raw" / "micro.owl",
        imports_dir=None,
    )
    extract, convert = calls
    # The pinned ROBOT from the raw directory, not whatever `robot` is on PATH.
    assert extract[:2] == convert[:2] == ["bash", str(tmp_path / "raw" / "robot")]
    assert extract[2] == "extract"
    written = extract[extract.index("--output") + 1]
    assert written.endswith("_mireot_module.owl"), written
    assert not written.endswith(".ofn")
    assert convert[2] == "convert"
    assert convert[convert.index("--input") + 1] == written
    assert convert[convert.index("--output") + 1] == str(module_json)
    assert module_json.suffix == ".json"
    # The superseded intermediate does not linger beside the new one (#988).
    assert not stale.exists()


def test_mireot_robot_calls_carry_the_jaxp_limits(tmp_path, monkeypatch):
    """
    Temurin 27 rejected MicrO's ChEBI import at the 100,000-byte entity limit.

    Both ROBOT calls must run with the JVM options from robot_utils, so the
    transform does not depend on each machine's JDK defaults or shell setup.
    """
    import subprocess

    envs = []

    def fake_run(cmd, check, env=None):
        """Capture the environment each ROBOT call receives."""
        envs.append(env)
        return None

    for name in ("ROBOT_JAVA_ARGS", "JAVA_TOOL_OPTIONS", "JDK_JAVA_OPTIONS"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(robot_utils, "_java_runs", lambda: True)
    monkeypatch.setattr(subprocess, "run", fake_run)
    _pinned_robot(tmp_path / "raw")
    transform = OntologiesStubsTransform(input_dir=tmp_path / "raw", output_dir=tmp_path / "out")
    transform.output_dir.mkdir(parents=True, exist_ok=True)
    transform._run_mireot_extract(
        prefix="MICRO",
        lower_curies=["MICRO:0000082"],
        upper_curie="MICRO:0000031",
        owl_path=tmp_path / "raw" / "micro.owl",
        imports_dir=None,
    )
    assert len(envs) == 2
    for env in envs:
        for name, value in ROBOT_JAXP_LIMITS:
            assert f"-D{name}={value}" in env["ROBOT_JAVA_ARGS"]
        # Offline mode comes with the catalog: no imports_dir, no proxy flags.
        assert not any(flag in env["ROBOT_JAVA_ARGS"] for flag in OFFLINE_FLAGS)


def _pinned_robot(raw_dir: Path) -> None:
    """Lay out the pinned ROBOT under ``raw_dir``, as `kg download -t tools` does."""
    raw_dir.mkdir(parents=True, exist_ok=True)
    (raw_dir / "robot").write_text("#!/bin/sh\n", encoding="utf-8")
    zipfile.ZipFile(raw_dir / "robot.jar", "w").close()


def test_missing_pinned_robot_is_a_prerequisite_failure(tmp_path, monkeypatch):
    """
    Without ROBOT the source used to fail mid-batch, after the ontologies transform.

    The check is for the pinned copy in the raw directory that `kg download`
    provides and the run uses, not for a `robot` on PATH.
    """
    monkeypatch.setattr(robot_utils, "_java_runs", lambda: True)
    _pinned_imports(tmp_path)
    (problem,) = OntologiesStubsTransform.missing_prerequisites(tmp_path)
    assert problem.startswith(f"pinned ROBOT missing from {tmp_path}: robot, robot.jar")
    _pinned_robot(tmp_path)
    assert OntologiesStubsTransform.missing_prerequisites(tmp_path) == []


def test_missing_java_is_a_prerequisite_failure(tmp_path, monkeypatch):
    """The ROBOT wrapper execs `java`; a host without one fails every ROBOT call."""
    _pinned_robot(tmp_path)
    _pinned_imports(tmp_path)
    monkeypatch.setattr(robot_utils, "_java_runs", lambda: False)
    assert OntologiesStubsTransform.missing_prerequisites(tmp_path) == [
        "java on PATH does not run (no JDK installed?); ROBOT needs one."
    ]


def _pinned_imports(raw_dir: Path) -> None:
    """
    Lay out every pinned ontology and its import modules under ``raw_dir``, as `kg download` does.

    Also an unpacked ``ncit.db``, which the preflight checks for its SQLite header.
    """
    for owl_name, imports_name, header, modules in PINNED_IMPORTS.values():
        (raw_dir / imports_name).mkdir(parents=True)
        (raw_dir / owl_name).write_text(header.read_text(encoding="utf-8"), encoding="utf-8")
        for name in modules:
            (raw_dir / imports_name / name).write_text("<rdf:RDF/>", encoding="utf-8")
    (raw_dir / "ncit.db").write_bytes(SQLITE_HEADER)


def test_a_stale_ncit_db_fails_the_stubs_preflight(tmp_path, monkeypatch):
    """
    An ncit.db older than its archive is refused, since ontologies_stubs reads it as it is (#1536).

    `kg download -i -t stubs` brings a new ncit.db.gz and leaves the old ncit.db in place.
    """
    monkeypatch.setattr(robot_utils, "_java_runs", lambda: True)
    _pinned_robot(tmp_path)
    _pinned_imports(tmp_path)
    (tmp_path / "ncit.db.gz").write_bytes(gzip.compress(SQLITE_HEADER + b" a newer release"))
    (problem,) = OntologiesStubsTransform.missing_prerequisites(tmp_path)
    assert "is not the copy of the ncit.db.gz beside it" in problem


def test_a_damaged_archive_beside_its_database_is_not_unpacked(tmp_path, monkeypatch):
    """An interrupted re-download of bto.db.gz leaves the bto.db already there in use (#1545)."""
    import oaklib

    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "bto.db").write_bytes(b"the database already unpacked")
    (raw / "bto.db.gz").write_bytes(b"\x1f\x8b an interrupted download")
    opened = []
    monkeypatch.setattr(oaklib, "get_adapter", lambda locator: opened.append(locator) or "adapter")
    transform = OntologiesStubsTransform(input_dir=raw, output_dir=tmp_path / "out")
    assert transform._open_adapter("BTO", raw / "bto.db") == "adapter"
    assert opened == [f"sqlite:{raw / 'bto.db'}"]
    assert (raw / "bto.db").read_bytes() == b"the database already unpacked"


def test_the_pinned_micro_owl_imports_exactly_the_pinned_modules():
    """
    Preflight checks the pinned list while the run maps what micro.owl declares.

    Checked against the real file's import lines, so the constant cannot
    drift from the ontology it was written for.
    """
    declared = [iri.rsplit("/", 1)[-1] for iri in _declared_imports(MICRO_OWL_HEADER)]
    assert sorted(declared) == sorted(MICRO_IMPORT_MODULES)
    assert len(declared) == 20


def test_the_pinned_po_owl_imports_exactly_the_pinned_modules():
    """The same check for po.owl, whose header also names the release it was cut from."""
    declared = [iri.rsplit("/", 1)[-1] for iri in _declared_imports(PO_OWL_HEADER)]
    assert sorted(declared) == sorted(PO_IMPORT_MODULES)
    version_iri = f'<owl:versionIRI rdf:resource="{PO_VERSION_IRI}"/>'
    assert version_iri in PO_OWL_HEADER.read_text(encoding="utf-8")


@pytest.mark.parametrize("prefix", sorted(PINNED_IMPORTS))
def test_imports_that_disagree_with_the_pin_fail_preflight(tmp_path, monkeypatch, prefix):
    """An import a new pin adds would otherwise pass preflight and fail only after the ontologies source."""
    monkeypatch.setattr(robot_utils, "_java_runs", lambda: True)
    _pinned_robot(tmp_path)
    _pinned_imports(tmp_path)
    owl = tmp_path / PINNED_IMPORTS[prefix][0]
    extra = '        <owl:imports rdf:resource="https://example.org/branch/NEW_imports.owl"/>\n    </owl:Ontology>'
    owl.write_text(owl.read_text(encoding="utf-8").replace("    </owl:Ontology>", extra), encoding="utf-8")
    (problem,) = OntologiesStubsTransform.missing_prerequisites(tmp_path)
    assert problem.startswith(f"{prefix} imports and pin disagree")
    assert "NEW_imports.owl" in problem


@pytest.mark.parametrize("prefix", sorted(PINNED_IMPORTS))
def test_a_missing_pinned_ontology_fails_preflight(tmp_path, monkeypatch, prefix):
    """Without the ontology there is nothing to check the imports against, and the run would fail late."""
    monkeypatch.setattr(robot_utils, "_java_runs", lambda: True)
    _pinned_robot(tmp_path)
    _pinned_imports(tmp_path)
    (tmp_path / PINNED_IMPORTS[prefix][0]).unlink()
    (problem,) = OntologiesStubsTransform.missing_prerequisites(tmp_path)
    assert problem.startswith(f"{prefix} ontology missing")


@pytest.mark.parametrize(
    "replacement, found",
    [
        ('<owl:versionIRI rdf:resource="http://purl.obolibrary.org/obo/po/releases/2025-10-31/po.owl"/>', "2025-10-31"),
        ("", "versionIRI none"),
    ],
)
def test_a_po_owl_from_another_release_fails_preflight(tmp_path, monkeypatch, replacement, found):
    """
    An older release imports the same two modules, so only its versionIRI tells it apart.

    `kg download` leaves a po.owl it has no record of in place, and then records
    the pinned URL against it; the stub hierarchy would be built from it silently.
    """
    monkeypatch.setattr(robot_utils, "_java_runs", lambda: True)
    _pinned_robot(tmp_path)
    _pinned_imports(tmp_path)
    owl = tmp_path / "po.owl"
    pinned = f'<owl:versionIRI rdf:resource="{PO_VERSION_IRI}"/>'
    owl.write_text(owl.read_text(encoding="utf-8").replace(pinned, replacement), encoding="utf-8")
    (problem,) = OntologiesStubsTransform.missing_prerequisites(tmp_path)
    assert problem.startswith("PO ontology is not the pinned release")
    assert found in problem
    assert PO_VERSION_IRI in problem
    assert "kg download -t ontologies" in problem


@pytest.mark.parametrize(
    "prefix, absent, present",
    [("MICRO", "ChEBI_imports.owl", "GO_imports.owl"), ("PO", "ro_import.owl", "ncbitaxon_import.owl")],
)
def test_a_missing_pinned_import_is_a_prerequisite_failure(tmp_path, monkeypatch, prefix, absent, present):
    """
    The imports are no longer fetched, so an absent module must stop the batch up front.

    Every machine that downloaded data before the pin lacks them; finding out
    after the ontologies source would cost hours.
    """
    monkeypatch.setattr(robot_utils, "_java_runs", lambda: True)
    _pinned_robot(tmp_path)
    _pinned_imports(tmp_path)
    (tmp_path / PINNED_IMPORTS[prefix][1] / absent).unlink()
    (problem,) = OntologiesStubsTransform.missing_prerequisites(tmp_path)
    assert problem.startswith(f"{prefix} import modules missing")
    assert absent in problem
    assert present not in problem


_TWO_IMPORTS = """<?xml version="1.0"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" xmlns:owl="http://www.w3.org/2002/07/owl#">
    <owl:Ontology rdf:about="http://example.org/m.owl">
        <owl:imports rdf:resource="https://example.org/branch/A_imports.owl"/>
        <owl:imports rdf:resource="https://example.org/branch/B_imports.owl"/>
    </owl:Ontology>
</rdf:RDF>
"""


def test_import_catalog_maps_every_import_to_its_local_copy(tmp_path):
    """The catalog is what keeps ROBOT from fetching MicrO's imports from a moving branch."""
    owl = tmp_path / "m.owl"
    owl.write_text(_TWO_IMPORTS, encoding="utf-8")
    imports_dir = tmp_path / "imports"
    imports_dir.mkdir()
    for name in ("A_imports.owl", "B_imports.owl"):
        (imports_dir / name).write_text("<rdf:RDF/>", encoding="utf-8")
    catalog = _write_import_catalog(owl, imports_dir, tmp_path / "catalog-v001.xml")
    text = catalog.read_text(encoding="utf-8")
    for name in ("A", "B"):
        iri = f"https://example.org/branch/{name}_imports.owl"
        local = (imports_dir / f"{name}_imports.owl").resolve().as_uri()
        assert f'<uri name="{iri}" uri="{local}"/>' in text


def test_an_import_with_no_local_copy_raises_instead_of_being_fetched(tmp_path):
    """Falling back to the network would reintroduce exactly the unpinned fetch the catalog removes."""
    owl = tmp_path / "m.owl"
    owl.write_text(_TWO_IMPORTS, encoding="utf-8")
    imports_dir = tmp_path / "imports"
    imports_dir.mkdir()
    (imports_dir / "A_imports.owl").write_text("<rdf:RDF/>", encoding="utf-8")
    with pytest.raises(FileNotFoundError, match="B_imports.owl"):
        _write_import_catalog(owl, imports_dir, tmp_path / "catalog-v001.xml")
    assert not (tmp_path / "catalog-v001.xml").exists()


@pytest.mark.parametrize(
    "body",
    [
        # Nested form: the rdf:resource pattern does not see it.
        '<rdf:RDF><owl:Ontology><owl:imports><owl:Ontology rdf:about="https://x/A.owl"/></owl:imports>'
        "</owl:Ontology></rdf:RDF>",
        # Entity-spelled IRI: the catalog name would not match what OWLAPI requests.
        '<rdf:RDF><owl:Ontology><owl:imports rdf:resource="&obo;A.owl"/></owl:Ontology></rdf:RDF>',
        # Not RDF/XML at all: imports cannot be enumerated.
        "Ontology(<https://x/m.owl> Import(<https://x/A.owl>))",
        # OWL bound to another prefix: the owl: pattern would see no imports at all.
        '<rdf:RDF xmlns:o="http://www.w3.org/2002/07/owl#"><o:Ontology><o:imports rdf:resource="https://x/A.owl"/>'
        "</o:Ontology></rdf:RDF>",
        # OWL as the default namespace.
        '<rdf:RDF xmlns="http://www.w3.org/2002/07/owl#"><Ontology><imports rdf:resource="https://x/A.owl"/>'
        "</Ontology></rdf:RDF>",
        # Relative to xml:base: OWLAPI requests the resolved IRI, never the bare name.
        '<rdf:RDF xml:base="https://x/base/"><owl:Ontology><owl:imports rdf:resource="A.owl"/>'
        "</owl:Ontology></rdf:RDF>",
    ],
)
def test_imports_that_cannot_be_enumerated_are_refused(tmp_path, body):
    """An import this helper cannot read would be fetched live by ROBOT; refuse rather than guess."""
    owl = tmp_path / "m.owl"
    owl.write_text(body, encoding="utf-8")
    (tmp_path / "imports").mkdir()
    (tmp_path / "imports" / "A.owl").write_text("<rdf:RDF/>", encoding="utf-8")
    with pytest.raises(ValueError):
        _write_import_catalog(owl, tmp_path / "imports", tmp_path / "catalog-v001.xml")


def test_micro_extract_runs_with_the_catalog(tmp_path, monkeypatch):
    """MICRO's extract must name the catalog, or OWLAPI goes to the network for its imports."""
    import subprocess

    calls = []

    def fake_run(cmd, check, env=None):
        """Capture the ROBOT command, its environment and the catalog it names, without launching it."""
        catalog = cmd[cmd.index("--catalog") + 1] if "--catalog" in cmd else None
        # A copy: the extract and convert calls may share one dict, and only the
        # extract's environment at the moment it ran shows whether it was offline.
        calls.append((list(cmd), dict(env), Path(catalog).read_text(encoding="utf-8") if catalog else None))
        return None

    monkeypatch.setattr(robot_utils, "_java_runs", lambda: True)
    monkeypatch.setattr(subprocess, "run", fake_run)
    raw = tmp_path / "raw"
    _pinned_robot(raw)
    (raw / "micro.owl").write_text(_TWO_IMPORTS, encoding="utf-8")
    imports_dir = raw / "imports"
    imports_dir.mkdir()
    for name in ("A_imports.owl", "B_imports.owl"):
        (imports_dir / name).write_text("<rdf:RDF/>", encoding="utf-8")
    transform = OntologiesStubsTransform(input_dir=raw, output_dir=tmp_path / "out")
    transform.output_dir.mkdir(parents=True, exist_ok=True)
    transform._run_mireot_extract(
        prefix="MICRO",
        lower_curies=["MICRO:0000082"],
        upper_curie="MICRO:0000031",
        owl_path=raw / "micro.owl",
        imports_dir=imports_dir,
    )
    (extract, extract_env, catalog_text), (_, convert_env, _) = calls
    assert "https://example.org/branch/A_imports.owl" in catalog_text
    # An import the catalog misses must fail, not be fetched: the JVM has no network.
    for flag in OFFLINE_FLAGS:
        assert flag in extract_env["ROBOT_JAVA_ARGS"], flag
        assert flag in convert_env["ROBOT_JAVA_ARGS"], flag
    # The catalog holds this machine's absolute paths; it must not land in the published output.
    catalog = Path(extract[extract.index("--catalog") + 1])
    assert not catalog.exists()
    assert not catalog.is_relative_to(transform.output_dir)


def test_run_routes_po_and_micro_through_the_catalog(tmp_path, monkeypatch):
    """
    Drive the configuration wiring from `run`, not just the extract helper.

    Dropping the `imports_dir` pass-through anywhere between `run` and the
    extract used to leave every test passing while ROBOT went back to MicrO's
    master branch for all 20 modules; PO's two came from its master branch the
    same way.
    """
    import subprocess

    extracts = {}

    def fake_run(cmd, check, env=None):
        """Record each extract by its input ontology."""
        if "extract" in cmd:
            extracts[Path(cmd[cmd.index("--input") + 1]).name] = (list(cmd), dict(env))
        return None

    monkeypatch.setattr(robot_utils, "_java_runs", lambda: True)
    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(
        stubs_module, "collect_stub_curies", lambda prefixes: {"PO": {"PO:0009046"}, "MICRO": {"MICRO:0000082"}}
    )
    monkeypatch.setattr(OntologiesStubsTransform, "_parse_mireot_module", lambda self, **kwargs: ([], [], set(), []))
    raw = tmp_path / "raw"
    _pinned_robot(raw)
    for owl_name, imports_name, _, _ in PINNED_IMPORTS.values():
        (raw / owl_name).write_text(_TWO_IMPORTS, encoding="utf-8")
        (raw / imports_name).mkdir()
        for name in ("A_imports.owl", "B_imports.owl"):
            (raw / imports_name / name).write_text("<rdf:RDF/>", encoding="utf-8")
    OntologiesStubsTransform(input_dir=raw, output_dir=tmp_path / "out").run()
    assert set(extracts) == {"po.owl", "micro.owl"}
    for owl_name, (cmd, env) in extracts.items():
        assert "--catalog" in cmd, owl_name
        assert all(flag in env["ROBOT_JAVA_ARGS"] for flag in OFFLINE_FLAGS), owl_name


def test_every_owl_mireot_source_resolves_its_imports_offline():
    """
    A pin is only effective while the source's config routes its extract through the catalog.

    An owl_mireot source without ``imports_dir`` runs ROBOT online, and ROBOT
    fetches whatever the OWL imports from wherever its IRIs point.
    """
    owl_sources = {p: c for p, c in STUB_ONTOLOGY_SOURCES.items() if c.get("source_type") == "owl_mireot"}
    assert set(owl_sources) == set(PINNED_IMPORTS)
    for prefix, (owl_name, imports_name, _, modules) in PINNED_IMPORTS.items():
        cfg = owl_sources[prefix]
        assert (cfg["owl_filename"], cfg["imports_dir"], cfg["import_modules"]) == (owl_name, imports_name, modules)
    # PO publishes releases, so preflight can also check which one is on disk; MicrO has none.
    assert owl_sources["PO"]["version_iri"] == PO_VERSION_IRI
    assert "version_iri" not in owl_sources["MICRO"]


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def test_sanitize_collapses_whitespace_and_caps_length():
    """Multi-line synonyms must collapse to one line and stay under the cell-length cap."""
    raw = "First line\n\nSecond paragraph\t with\ttabs   and  runs of spaces."
    cleaned = _sanitize(raw)
    assert "\n" not in cleaned and "\t" not in cleaned
    assert "  " not in cleaned  # no runs of multiple spaces
    assert cleaned == "First line Second paragraph with tabs and runs of spaces."
    # Length cap with ellipsis marker
    huge = "x" * 1000
    capped = _sanitize(huge)
    assert len(capped) <= 500
    assert capped.endswith("…")
    # Empties/None safe.
    assert _sanitize("") == ""
    assert _sanitize(None) == ""


def test_retag_curie_translates_mesh_case():
    """``_retag_curie`` swaps the prefix; no-op when source and target match."""
    assert _retag_curie("mesh:C000366", "mesh", "MESH") == "MESH:C000366"
    assert _retag_curie("NCIT:C29298", "NCIT", "NCIT") == "NCIT:C29298"
    # CURIE whose prefix doesn't match `from_prefix` is left untouched (defensive).
    assert _retag_curie("CHEBI:60004", "mesh", "MESH") == "CHEBI:60004"


def test_curie_to_iris_emits_both_micro_shapes():
    """MIREOT must receive both IRI forms for MICRO so neither shape is silently dropped."""
    assert _curie_to_iris("PO:0009046") == [
        "http://purl.obolibrary.org/obo/PO_0009046",
    ]
    assert _curie_to_iris("MICRO:0000082") == [
        "http://purl.obolibrary.org/obo/MICRO_0000082",
        "http://purl.obolibrary.org/obo/MicrO.owl/MICRO_0000082",
    ]


def test_iri_to_curie_handles_both_micro_shapes():
    """Standard and MicrO-quirky OBO IRIs both normalize to ``PREFIX:local``."""
    assert _iri_to_curie("http://purl.obolibrary.org/obo/MICRO_0000082") == "MICRO:0000082"
    assert _iri_to_curie("http://purl.obolibrary.org/obo/MicrO.owl/MICRO_0003152") == "MICRO:0003152"
    assert _iri_to_curie("http://purl.obolibrary.org/obo/PO_0009046") == "PO:0009046"
    # Non-OBO IRI → None (caller decides what to do).
    assert _iri_to_curie("http://example.org/notanobo") is None


# ---------------------------------------------------------------------------
# End-to-end assertions against committed mapping data (skipped when stub
# output absent — i.e. on a fresh checkout where the transform hasn't run).
# ---------------------------------------------------------------------------


_STUB_OUTPUT_DIR = REPO_ROOT / "data" / "transformed" / "ontologies_stubs"


def _stub_outputs_present() -> bool:
    # The integration assertion below loads every stub prefix, so require
    # all five outputs to be present before running it.
    return all((_STUB_OUTPUT_DIR / f"{prefix.lower()}_nodes.tsv").is_file() for prefix in STUB_ONTOLOGY_SOURCES)


@pytest.mark.skipif(not _stub_outputs_present(), reason="stub transform output not generated yet")
def test_every_referenced_curie_has_stub_node():
    """Every NCIT/mesh/BTO/PO/MICRO CURIE referenced under mappings/ must resolve to a stub node row."""
    expected = collect_stub_curies(["NCIT", "mesh", "BTO", "PO", "MICRO"])
    for prefix, curies in expected.items():
        out = _STUB_OUTPUT_DIR / f"{prefix.lower()}_nodes.tsv"
        rows = _read_tsv(out)
        ids = {row["id"] for row in rows}
        missing = curies - ids
        assert not missing, (
            f"{prefix} stub TSV missing nodes for: {sorted(missing)} "
            f"(re-run `poetry run kg transform -s ontologies_stubs`)"
        )
        # Every emitted row must carry a non-empty name (no dangling-style placeholders).
        empty_names = [row["id"] for row in rows if not (row["name"] or "").strip()]
        assert not empty_names, f"{prefix} stub rows with empty name: {empty_names}"


@pytest.mark.skipif(not _stub_outputs_present(), reason="stub transform output not generated yet")
def test_hierarchy_outputs_include_edges():
    """Every prefix that emits hierarchy must write both nodes and edges TSVs."""
    # PO, MICRO use owl_mireot (relation: rdfs:subClassOf).
    # NCIT uses semsql_mireot (relation: rdfs:subClassOf).
    # mesh uses mesh_nt_rdf — relation reflects the mesh predicate that
    # produced the edge (meshv:broaderDescriptor / meshv:preferredMappedTo /
    # meshv:mappedTo); the biolink predicate is uniformly biolink:subclass_of.
    for prefix, expected_relations, output_prefix in (
        ("po", {"rdfs:subClassOf"}, "PO"),
        ("micro", {"rdfs:subClassOf"}, "MICRO"),
        ("ncit", {"rdfs:subClassOf"}, "NCIT"),
        (
            "mesh",
            {"meshv:broaderDescriptor", "meshv:preferredMappedTo", "meshv:mappedTo"},
            "mesh",
        ),
    ):
        nodes_file = _STUB_OUTPUT_DIR / f"{prefix}_nodes.tsv"
        edges_file = _STUB_OUTPUT_DIR / f"{prefix}_edges.tsv"
        assert nodes_file.is_file(), f"{nodes_file} missing"
        assert edges_file.is_file(), f"{edges_file} missing"
        edges = _read_tsv(edges_file)
        for edge in edges:
            assert edge["predicate"] == "biolink:subclass_of"
            assert edge["relation"] in expected_relations
            assert edge["subject"].startswith(f"{output_prefix}:")
