"""Tests for the OntologiesStubsTransform."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Dict, List, Set

import pytest

from kg_microbe.transform_utils.ontologies_stubs.ontologies_stubs_transform import (
    STUB_ONTOLOGY_SOURCES,
    OntologiesStubsTransform,
    _ObographJsonAdapter,
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
        self._store = store  # {curie: {"label": str, "aliases": [...], "xrefs": [...]}}

    def label(self, curie: str):
        return self._store.get(curie, {}).get("label", "")

    def entity_aliases(self, curie: str):
        return list(self._store.get(curie, {}).get("aliases", []))

    def entity_metadata_map(self, curie: str):
        xrefs = list(self._store.get(curie, {}).get("xrefs", []))
        return {"oio:hasDbXref": xrefs} if xrefs else {}


class _StubbedTransform(OntologiesStubsTransform):

    """Subclass that swaps in an in-memory adapter so tests don't touch SemSQL DBs on disk."""

    def __init__(
        self,
        *,
        adapters: Dict[str, _FakeAdapter],
        curies: Dict[str, Set[str]],
        input_dir: Path,
        output_dir: Path,
    ):
        super().__init__(input_dir=input_dir, output_dir=output_dir)
        self._fake_adapters = adapters
        self._fake_curies = curies

    def _open_adapter(self, prefix, db_path):  # noqa: D401 — override
        return self._fake_adapters.get(prefix)

    def run(self, data_file=None):  # noqa: D401 — override
        # Bypass collect_stub_curies (we inject a curated set instead).
        for prefix, curies in self._fake_curies.items():
            if prefix not in STUB_ONTOLOGY_SOURCES:
                continue
            cfg = STUB_ONTOLOGY_SOURCES[prefix]
            output_file = self.output_dir / f"{prefix.lower()}_nodes.tsv"
            self._write_stub_nodes(
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
    stub path shortly after (PO via SemSQL, MICRO via obograph JSON since
    its bbop-sqlite distribution is a broken 29-byte placeholder).
    """
    assert set(STUB_ONTOLOGY_SOURCES.keys()) == {"NCIT", "mesh", "BTO", "PO", "MICRO"}


def test_micro_source_type_is_obograph_json():
    """MICRO must dispatch to the obograph-JSON adapter, not SemSQL."""
    assert STUB_ONTOLOGY_SOURCES["MICRO"]["source_type"] == "obograph_json"
    assert STUB_ONTOLOGY_SOURCES["MICRO"]["db_filename"].endswith(".json")


def test_semsql_sources_use_db_files():
    """NCIT, mesh, BTO, PO all use the SemSQL adapter against a .db file."""
    for prefix in ("NCIT", "mesh", "BTO", "PO"):
        cfg = STUB_ONTOLOGY_SOURCES[prefix]
        # source_type may be absent (defaults to semsql) or explicit "semsql".
        assert cfg.get("source_type", "semsql") == "semsql"
        assert cfg["db_filename"].endswith(".db")


# ---------------------------------------------------------------------------
# Transform behaviour with in-memory adapter
# ---------------------------------------------------------------------------


def test_transform_writes_label_synonyms_xrefs(tmp_path):
    """A CURIE with full metadata in the fake adapter must round-trip into the TSV."""
    adapters = {
        "NCIT": _FakeAdapter(
            {
                "NCIT:C29298": {
                    "label": "Oatmeal",
                    "aliases": ["Avena sativa rolled groats", "Porridge oats"],
                    "xrefs": ["FOODON:00001540", "wikipedia:Oatmeal"],
                },
            }
        ),
    }
    curies = {"NCIT": {"NCIT:C29298"}, "mesh": set()}
    t = _StubbedTransform(adapters=adapters, curies=curies, input_dir=tmp_path / "in", output_dir=tmp_path / "out")
    (tmp_path / "in").mkdir()
    t.run()
    rows = _read_tsv(tmp_path / "out" / "ontologies_stubs" / "ncit_nodes.tsv")
    assert len(rows) == 1
    row = rows[0]
    assert row["id"] == "NCIT:C29298"
    assert row["category"] == STUB_ONTOLOGY_CATEGORY
    assert row["name"] == "Oatmeal"
    assert "Avena sativa rolled groats" in row["synonym"].split("|")
    assert "FOODON:00001540" in row["xref"].split("|")


def test_transform_falls_back_to_curie_when_label_missing(tmp_path):
    """Missing label must NOT produce an empty `name` cell — fall back to the CURIE."""
    adapters = {"NCIT": _FakeAdapter({})}  # adapter knows nothing
    curies = {"NCIT": {"NCIT:C99999"}, "mesh": set()}
    t = _StubbedTransform(adapters=adapters, curies=curies, input_dir=tmp_path / "in", output_dir=tmp_path / "out")
    (tmp_path / "in").mkdir()
    t.run()
    rows = _read_tsv(tmp_path / "out" / "ontologies_stubs" / "ncit_nodes.tsv")
    assert len(rows) == 1
    assert rows[0]["name"] == "NCIT:C99999"  # falls back to the CURIE itself


def test_transform_writes_empty_tsv_when_no_curies(tmp_path):
    """No CURIEs → empty file with header (so merge.yaml's filename declaration is satisfied)."""
    adapters = {"mesh": _FakeAdapter({})}
    curies = {"NCIT": set(), "mesh": set()}
    t = _StubbedTransform(adapters=adapters, curies=curies, input_dir=tmp_path / "in", output_dir=tmp_path / "out")
    (tmp_path / "in").mkdir()
    t.run()
    out = tmp_path / "out" / "ontologies_stubs"
    # Both files written even with empty inputs (header-only).
    assert (out / "ncit_nodes.tsv").is_file()
    assert (out / "mesh_nodes.tsv").is_file()
    assert _read_tsv(out / "ncit_nodes.tsv") == []
    assert _read_tsv(out / "mesh_nodes.tsv") == []


def test_transform_synonym_does_not_duplicate_label(tmp_path):
    """If an alias equals the label, drop it from the synonym set (keep them disjoint)."""
    adapters = {
        "NCIT": _FakeAdapter(
            {
                "NCIT:C29298": {
                    "label": "Oatmeal",
                    "aliases": ["Oatmeal", "Porridge oats"],
                    "xrefs": [],
                },
            }
        ),
    }
    curies = {"NCIT": {"NCIT:C29298"}, "mesh": set()}
    t = _StubbedTransform(adapters=adapters, curies=curies, input_dir=tmp_path / "in", output_dir=tmp_path / "out")
    (tmp_path / "in").mkdir()
    t.run()
    rows = _read_tsv(tmp_path / "out" / "ontologies_stubs" / "ncit_nodes.tsv")
    assert rows[0]["name"] == "Oatmeal"
    assert rows[0]["synonym"] == "Porridge oats"


def test_transform_raises_when_db_missing(tmp_path):
    """If neither the .db nor the .db.gz exists, the transform fails loudly (not silently)."""
    # Use the real OntologiesStubsTransform here (not the _StubbedTransform) so the
    # _open_adapter path runs against an empty input dir.
    transform = OntologiesStubsTransform(
        input_dir=tmp_path / "raw",  # empty
        output_dir=tmp_path / "out",
    )
    (tmp_path / "raw").mkdir()
    # Force collection to return at least one CURIE so we exercise the missing-DB branch.
    object.__setattr__(
        transform,
        "run",
        lambda data_file=None: transform._write_stub_nodes(
            prefix="NCIT",
            curies=["NCIT:C29298"],
            db_path=tmp_path / "raw" / "ncit.db",
            knowledge_source="infores:ncit",
            output_file=tmp_path / "out" / "ncit_nodes.tsv",
        ),
    )
    with pytest.raises(FileNotFoundError, match="ncit.db"):
        transform.run()


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


# ---------------------------------------------------------------------------
# Obograph-JSON adapter (MICRO fallback when SemSQL DB is unavailable)
# ---------------------------------------------------------------------------


def test_obograph_json_adapter_handles_both_iri_shapes(tmp_path):
    """Standard and MicrO-quirky IRI forms must both resolve to the canonical CURIE."""
    fixture = {
        "graphs": [
            {
                "nodes": [
                    {
                        # Standard OBO IRI shape.
                        "id": "http://purl.obolibrary.org/obo/MICRO_0000082",
                        "lbl": "nutrient broth",
                        "meta": {
                            "synonyms": [
                                {"pred": "hasBroadSynonym", "val": "nutrient medium"},
                            ],
                            "xrefs": [{"val": "Wikipedia:Nutrient_broth"}],
                        },
                    },
                    {
                        # MicrO's quirky IRI shape (note the extra MicrO.owl/ segment).
                        "id": "http://purl.obolibrary.org/obo/MicrO.owl/MICRO_0003152",
                        "lbl": "phenylacetic acid fermentation assay",
                        "meta": {
                            "synonyms": [
                                {"pred": "hasRelatedSynonym", "val": "o-toluate"},
                                # Malformed entry (no val) — must be silently skipped.
                                {"pred": "hasRelatedSynonym"},
                            ],
                        },
                    },
                ],
            }
        ],
    }
    import json

    path = tmp_path / "micro.json"
    path.write_text(json.dumps(fixture), encoding="utf-8")

    adapter = _ObographJsonAdapter.from_file(path)
    # Standard-shape IRI → CURIE
    assert adapter.label("MICRO:0000082") == "nutrient broth"
    assert adapter.entity_aliases("MICRO:0000082") == ["nutrient medium"]
    assert adapter.entity_metadata_map("MICRO:0000082") == {
        "oio:hasDbXref": ["Wikipedia:Nutrient_broth"],
    }
    # Quirky-shape IRI → CURIE
    assert adapter.label("MICRO:0003152") == "phenylacetic acid fermentation assay"
    assert adapter.entity_aliases("MICRO:0003152") == ["o-toluate"]
    # No xrefs metadata in fixture → empty dict.
    assert adapter.entity_metadata_map("MICRO:0003152") == {}
    # Unknown CURIE → empty results (no exceptions).
    assert adapter.label("MICRO:9999999") == ""
    assert adapter.entity_aliases("MICRO:9999999") == []
    assert adapter.entity_metadata_map("MICRO:9999999") == {}
