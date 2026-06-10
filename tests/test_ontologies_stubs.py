"""Tests for the OntologiesStubsTransform."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Dict, List, Set

import pytest

from kg_microbe.transform_utils.ontologies_stubs.ontologies_stubs_transform import (
    STUB_ONTOLOGY_SOURCES,
    OntologiesStubsTransform,
    _curie_to_iris,
    _iri_to_curie,
    _retag_curie,
    _sanitize,
)
from kg_microbe.utils.isolation_source_mapping_utils import (
    STUB_ONTOLOGY_CATEGORY,
    STUB_ONTOLOGY_PREFIXES,
)
from kg_microbe.utils.stub_curie_collection import collect_stub_curies

REPO_ROOT = Path(__file__).resolve().parents[1]


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
        """Return an OAK-shaped metadata dict carrying only ``oio:hasDbXref``."""
        xrefs = list(self._store.get(curie, {}).get("xrefs", []))
        return {"oio:hasDbXref": xrefs} if xrefs else {}


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
        )


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
