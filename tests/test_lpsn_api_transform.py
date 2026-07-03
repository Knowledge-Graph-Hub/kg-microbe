"""Tests for the LPSN JSON API transform (auth-gated enrichment layer)."""

import csv
import json
from pathlib import Path

import pytest

from kg_microbe.transform_utils.lpsn.lpsn import LPSN_KNOWLEDGE_SOURCE, LPSN_PREFIX
from kg_microbe.transform_utils.lpsn_api.lpsn_api import LPSNAPITransform


class _FakeLpsnClient:

    """
    Stand-in for ``lpsn.LpsnClient`` — deterministic and offline.

    The real client is search-then-retrieve: ``search({"id": N})`` sets
    up a query, ``retrieve()`` yields matching records. The fake stores
    the last-searched id and yields the pre-canned response for it.
    """

    def __init__(self, records):
        """Keep the ``{record_no: record_dict}`` map for lookups."""
        self._records = records
        self._current = None

    def search(self, query):
        """Note which record_no to yield on the next ``retrieve()``."""
        self._current = str(query["id"])

    def retrieve(self):
        """Yield the record for the last-searched id (empty when unknown)."""
        rec = self._records.get(self._current)
        if rec is None:
            return
        yield rec


def _write_gss_nodes(path: Path, record_nos):
    """Write a fake GSS nodes.tsv with one row per requested record_no."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh, delimiter="\t")
        w.writerow(["id", "category"])  # minimal header the transform reads
        for n in record_nos:
            w.writerow([f"{LPSN_PREFIX}{n}", "biolink:OrganismTaxon"])


def _read_tsv(path):
    """Read a TSV into a list of dicts."""
    with open(path, newline="") as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


@pytest.fixture()
def api_records():
    """Canned API responses for record numbers 1002 (species) and 1005 (comb. nov.)."""
    return {
        "1002": {
            "id": 1002,
            "publication_doi": "10.1099/00207713-19-1-1",
            "publication_pmid": 12345,
            "ijsem_list_doi": "10.1099/ijsem.0.999999",
            "lpsn_parent_id": 1001,  # genus
            "basonym_id": None,
            "is_legitimate": True,
            "nomenclatural_status": "correct name",
            "lpsn_taxonomic_status": "correct name",
        },
        "1005": {
            "id": 1005,
            "publication_doi": "",
            "publication_pmid": None,
            "ijsem_list_doi": "",
            "lpsn_parent_id": 1002,
            "basonym_id": 1004,  # comb. nov. pointing at its basonym
            "is_legitimate": True,
            "nomenclatural_status": "correct name (comb. nov.)",
            "lpsn_taxonomic_status": "",
        },
    }


@pytest.fixture()
def api_transform(tmp_path, api_records):
    """LPSNAPITransform wired to fake GSS nodes + fake API client."""
    input_dir = tmp_path / "raw"
    output_dir = tmp_path / "transformed"
    input_dir.mkdir()
    # The transform's default GSS path is derived from output_base_dir:
    # output_base_dir/lpsn/nodes.tsv. Base Transform sets
    # output_base_dir = output_dir; we mirror that.
    _write_gss_nodes(output_dir / "lpsn" / "nodes.tsv", ["1002", "1005"])
    xform = LPSNAPITransform(
        input_dir=input_dir,
        output_dir=output_dir,
        client=_FakeLpsnClient(api_records),
    )
    return xform


def test_species_row_emits_publication_edges(api_transform):
    """Record 1002's DOI, PMID, and IJSEM list DOI all become close_match edges."""
    api_transform.run()
    edges = _read_tsv(api_transform.output_edge_file)
    targets = {
        e["object"] for e in edges if e["subject"] == f"{LPSN_PREFIX}1002" and e["predicate"] == "biolink:close_match"
    }
    assert "doi:10.1099/00207713-19-1-1" in targets
    assert "doi:10.1099/ijsem.0.999999" in targets
    assert "PMID:12345" in targets


def test_publication_stub_nodes_are_emitted(api_transform):
    """DOI / PMID stubs land as biolink:Publication nodes so edges aren't dangling."""
    api_transform.run()
    nodes = _read_tsv(api_transform.output_node_file)
    pubs = {n["id"] for n in nodes if n["category"] == "biolink:Publication"}
    assert "doi:10.1099/00207713-19-1-1" in pubs
    assert "PMID:12345" in pubs


def test_parent_id_emits_subclass_edge(api_transform):
    """``lpsn_parent_id`` becomes ``lpsn:child biolink:subclass_of lpsn:parent``."""
    api_transform.run()
    edges = _read_tsv(api_transform.output_edge_file)
    hits = [
        e
        for e in edges
        if e["subject"] == f"{LPSN_PREFIX}1002"
        and e["object"] == f"{LPSN_PREFIX}1001"
        and e["predicate"] == "biolink:subclass_of"
    ]
    assert len(hits) == 1
    assert hits[0]["relation"] == "rdfs:subClassOf"
    assert hits[0]["primary_knowledge_source"] == LPSN_KNOWLEDGE_SOURCE


def test_basonym_id_emits_same_as_edge(api_transform):
    """Record 1005's ``basonym_id`` becomes biolink:same_as → lpsn:1004."""
    api_transform.run()
    edges = _read_tsv(api_transform.output_edge_file)
    hits = [
        e
        for e in edges
        if e["subject"] == f"{LPSN_PREFIX}1005"
        and e["object"] == f"{LPSN_PREFIX}1004"
        and e["predicate"] == "biolink:same_as"
    ]
    assert len(hits) == 1
    assert hits[0]["relation"] == "skos:exactMatch"


def test_absent_fields_emit_no_edges(api_transform):
    """Record 1005 has no DOI/PMID → no publication edges for it."""
    api_transform.run()
    edges = _read_tsv(api_transform.output_edge_file)
    pubs = [
        e
        for e in edges
        if e["subject"] == f"{LPSN_PREFIX}1005" and (e["object"].startswith("doi:") or e["object"].startswith("PMID:"))
    ]
    assert pubs == []


def test_description_carries_status_details(api_transform):
    """Enrichment node's description folds legitimate + nomenclatural + taxonomic status."""
    api_transform.run()
    nodes = {n["id"]: n for n in _read_tsv(api_transform.output_node_file)}
    ecoli = nodes[f"{LPSN_PREFIX}1002"]
    # Base Transform's node_header includes description
    assert "legitimate=True" in ecoli["description"]
    assert "correct name" in ecoli["description"]


def test_response_is_cached_after_first_fetch(api_transform, tmp_path):
    """First run writes {record_no}.json under api_cache/; second run reads from it."""
    api_transform.run()
    cache_dir = tmp_path / "raw" / "lpsn" / "api_cache"
    assert (cache_dir / "1002.json").is_file()
    assert (cache_dir / "1005.json").is_file()

    # Sanity: cache contents are the record dicts we injected.
    with open(cache_dir / "1002.json") as fh:
        assert json.load(fh)["publication_pmid"] == 12345

    # Second run with an empty fake client should still work — it must
    # read from cache. Force the situation by resetting stats and
    # calling run() again.
    api_transform._client_override = _FakeLpsnClient({})
    api_transform._stats = {"fetched": 0, "from_cache": 0, "errors": 0}
    api_transform.run()
    assert api_transform._stats["from_cache"] >= 2
    assert api_transform._stats["fetched"] == 0


def test_missing_creds_raises_runtime_error(tmp_path, monkeypatch):
    """No client injected + no LPSN_USERNAME env var → helpful RuntimeError."""
    input_dir = tmp_path / "raw"
    output_dir = tmp_path / "transformed"
    input_dir.mkdir()
    _write_gss_nodes(output_dir / "lpsn" / "nodes.tsv", ["1"])
    # Clear any env-vars the test host might have leaking through.
    monkeypatch.delenv("LPSN_USERNAME", raising=False)
    monkeypatch.delenv("LPSN_PASSWORD", raising=False)
    # And short-circuit dotenv so a real .env at repo root doesn't
    # accidentally satisfy the check under test.
    monkeypatch.setattr(
        "kg_microbe.transform_utils.lpsn_api.lpsn_api.LPSNAPITransform._find_gss_nodes",
        lambda self: output_dir / "lpsn" / "nodes.tsv",
    )
    import kg_microbe.transform_utils.lpsn_api.lpsn_api as api_mod

    monkeypatch.setattr(api_mod, "load_dotenv", lambda: None, raising=False)

    xform = LPSNAPITransform(input_dir=input_dir, output_dir=output_dir)
    with pytest.raises(RuntimeError, match="LPSN_USERNAME and LPSN_PASSWORD"):
        xform.run()


def test_missing_gss_raises_file_not_found(tmp_path):
    """No GSS nodes.tsv on disk → helpful FileNotFoundError before any API call."""
    input_dir = tmp_path / "raw"
    output_dir = tmp_path / "transformed"
    input_dir.mkdir()
    xform = LPSNAPITransform(
        input_dir=input_dir,
        output_dir=output_dir,
        client=_FakeLpsnClient({}),
    )
    with pytest.raises(FileNotFoundError, match="LPSN GSS transform output"):
        xform.run()
