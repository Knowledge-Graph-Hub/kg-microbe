"""Tests for the LPSN JSON API transform (auth-gated enrichment layer)."""

import csv
import hashlib
import json
from pathlib import Path

import pytest

from kg_microbe.transform_utils.lpsn.lpsn import LPSN_KNOWLEDGE_SOURCE, LPSN_PREFIX
from kg_microbe.transform_utils.lpsn_api.lpsn_api import LPSNAPITransform
from kg_microbe.transform_utils.lpsn_api.native_inputs import (
    AUDIT_COLUMNS,
    AUDIT_FILE,
    GSS_ROLE,
    RECORD_ROLE_PREFIX,
    audit_rows,
)
from kg_microbe.utils.source_finalization import SourceFinalizationRequired, verify_finalized_source_files
from kg_microbe.utils.tsv_io import tsv_writer


class _FakeLpsnClient:
    """
    Stand-in for ``lpsn.LpsnClient`` — deterministic and offline.

    The real client is search-then-retrieve: ``search(id=N)`` sets
    up a query, ``retrieve()`` yields matching records. The fake stores
    the last-searched id and yields the pre-canned response for it.
    """

    def __init__(self, records):
        """Keep the ``{record_no: record_dict}`` map for lookups."""
        self._records = records
        self._current = None

    def search(self, id=None, **kwargs):  # noqa: A002 — mirrors lpsn's ``search(id=...)`` kwarg
        """Note which record_no to yield on the next ``retrieve()``."""
        self._current = str(id)

    def retrieve(self):
        """Yield the record for the last-searched id (empty when unknown)."""
        rec = self._records.get(self._current)
        if rec is None:
            return
        yield rec


#: LPSN's web page for a record the API does not serve (#1004): the rank
#: and name sit in the title, the statuses in labelled paragraphs. 1004 is
#: the fixture's basonym target; the family (999) has no page in the fake.
_WEB_PAGES = {
    "1004": """<html><head><title>Species: Bacterium coli</title></head><body>
    <p><b>Nomenclatural status:</b>
        not validly published, basonym of name in Approved Lists        </p>
    <p><b>Taxonomic status:</b>
        <span>synonym (and no standing)</span></p></body></html>""",
}


class _FakePageFetch:
    """Serve canned LPSN pages; record every request so tests can assert on it."""

    def __init__(self, pages):
        """Keep the ``{record_no: html}`` map."""
        self._pages = pages
        self.calls = []

    def __call__(self, record_no):
        """Return the page for ``record_no`` or ``None`` when the fake has none."""
        self.calls.append(record_no)
        return self._pages.get(record_no)


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
            "publication_text": "Fixture authors. Primary species description. Fixture Journal 2000; 1:1-2.",
            "ijsem_list_doi": "10.1099/ijsem.0.999999",
            "ijsem_list_text": "Fixture editor. Validation list. Fixture Journal 2001; 2:3-4.",
            "lpsn_parent_id": 1001,  # genus
            "basonym_id": None,
            "is_legitimate": True,
            "nomenclatural_status": "correct name",
            "lpsn_taxonomic_status": "correct name",
            # Real LPSN molecules[] schema: one dict per registered 16S
            # sequence, keyed kind/database/identifier. Includes a dup
            # (must be dedup'd) and a non-INSDC database row (must be
            # skipped so only valid INSDC: CURIEs are emitted).
            "molecules": [
                {"kind": "16S rRNA gene", "database": "insdc-nucleotide", "identifier": "M87049"},
                {"kind": "16S rRNA gene", "database": "insdc-nucleotide", "identifier": "AB030918"},
                {"kind": "16S rRNA gene", "database": "insdc-nucleotide", "identifier": "M87049"},
                {"kind": "16S rRNA gene", "database": "silva", "identifier": "SILVA123"},
            ],
        },
        "1001": {
            "id": 1001,
            "full_name": "Escherichia",
            "publication_doi": "",
            "publication_pmid": None,
            "ijsem_list_doi": "",
            "lpsn_parent_id": 999,  # family; deliberately absent from the fake API
            "basonym_id": None,
            "is_legitimate": True,
            "nomenclatural_status": "correct name",
            "lpsn_taxonomic_status": "correct name",
            "molecules": [],
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
            "molecules": [],  # no molecules — must not emit any INSDC edge
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
        page_fetch=_FakePageFetch(_WEB_PAGES),
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


def test_all_api_edge_families_restate_curated_metadata(api_transform):
    """An automated fetch does not make the asserted source facts automated (#1071)."""
    api_transform.run()
    edges = _read_tsv(api_transform.output_edge_file)
    assert {e["predicate"] for e in edges} == {
        "biolink:subclass_of",
        "biolink:same_as",
        "biolink:close_match",
    }
    assert {e["object"].split(":", 1)[0] for e in edges} >= {"lpsn", "doi", "PMID", "INSDC"}
    assert all(e["knowledge_level"] == "knowledge_assertion" for e in edges)
    assert all(e["agent_type"] == "manual_agent" for e in edges)


def test_publication_stub_nodes_are_emitted(api_transform):
    """DOI / PMID stubs land as biolink:Publication nodes so edges aren't dangling."""
    api_transform.run()
    nodes = _read_tsv(api_transform.output_node_file)
    pubs = {n["id"] for n in nodes if n["category"] == "biolink:Publication"}
    assert "doi:10.1099/00207713-19-1-1" in pubs
    assert "PMID:12345" in pubs


def test_publication_labels_use_the_matching_source_citation(api_transform, api_records):
    """Main DOI/PMID and validation-list DOI retain distinct bibliographic provenance."""
    api_transform.run()
    nodes = {row["id"]: row for row in _read_tsv(api_transform.output_node_file)}
    main = api_records["1002"]["publication_text"]
    for curie in ("doi:10.1099/00207713-19-1-1", "PMID:12345"):
        assert nodes[curie]["name"] == main
        assert "not a separately verified publication title" in nodes[curie]["description"]
        assert "lpsn:1002.publication_text" in nodes[curie]["description"]
        assert nodes[curie]["provided_by"] == LPSN_KNOWLEDGE_SOURCE
    validation = nodes["doi:10.1099/ijsem.0.999999"]
    assert validation["name"] == api_records["1002"]["ijsem_list_text"]
    assert "lpsn:1002.ijsem_list_text" in validation["description"]


@pytest.mark.parametrize("value", [None, "", " \t ", 123, ["citation"], {"title": "not source text"}])
def test_missing_or_malformed_citations_do_not_create_synthetic_labels(api_transform, api_records, value):
    """Keep identifiers and edges even when source-owned names are unavailable."""
    api_records["1002"]["publication_text"] = value
    api_records["1002"]["ijsem_list_text"] = value
    api_transform.run()
    nodes = {row["id"]: row for row in _read_tsv(api_transform.output_node_file)}
    for curie in ("doi:10.1099/00207713-19-1-1", "PMID:12345", "doi:10.1099/ijsem.0.999999"):
        assert nodes[curie]["name"] == ""
        assert "No usable LPSN source citation" in nodes[curie]["description"]
    assert {row["object"] for row in _read_tsv(api_transform.output_edge_file)} >= {
        "doi:10.1099/00207713-19-1-1",
        "PMID:12345",
        "doi:10.1099/ijsem.0.999999",
    }


@pytest.mark.parametrize("conflicting", [False, True])
def test_shared_publications_keep_duplicate_or_conflicting_source_citations(api_transform, api_records, conflicting):
    """Repeated IDs produce one node; contradictory citations never choose a winner."""
    first = api_records["1002"]
    api_records["1005"].update(
        publication_doi=first["publication_doi"],
        publication_pmid=first["publication_pmid"],
        publication_text="Different source citation." if conflicting else first["publication_text"],
    )
    api_transform.run()
    nodes = _read_tsv(api_transform.output_node_file)
    for curie in ("doi:10.1099/00207713-19-1-1", "PMID:12345"):
        selected = [row for row in nodes if row["id"] == curie]
        assert len(selected) == 1
        node = selected[0]
        assert node["name"] == ("" if conflicting else first["publication_text"])
        assert "lpsn:1002.publication_text" in node["description"]
        assert "lpsn:1005.publication_text" in node["description"]
        assert ("Conflicting LPSN citation texts" in node["description"]) == conflicting


def test_publication_aggregation_is_order_stable_and_blank_text_does_not_erase_label(api_transform):
    """Source order cannot change conflict disposition or retained citation provenance."""

    class Writer:
        """Collect emitted rows to compare aggregation across source orders."""

        def __init__(self):
            """Start an empty collection for one aggregation order."""
            self.rows = []

        def writerow(self, row):
            """Retain one emitted row without changing its fields."""
            self.rows.append(row)

    inputs = [
        ("doi:10.1234/example", "2", "publication_text", "Citation A."),
        ("doi:10.1234/example", "1", "publication_text", ""),
        ("PMID:123", "3", "publication_text", "Citation C."),
        ("PMID:123", "4", "publication_text", "Conflicting citation."),
    ]
    outputs = []
    for records in (inputs, list(reversed(inputs))):
        api_transform._publication_citations = {}
        for record in records:
            api_transform._record_publication_citation(*record)
        writer = Writer()
        api_transform._emit_publication_nodes(writer)
        outputs.append(writer.rows)
    assert outputs[0] == outputs[1]
    nodes = {row[0]: dict(zip(api_transform.node_header, row, strict=True)) for row in outputs[0]}
    assert nodes["doi:10.1234/example"]["name"] == "Citation A."
    assert nodes["PMID:123"]["name"] == ""


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


def test_molecules_emit_insdc_close_match_edges(api_transform):
    """Each unique INSDC accession → biolink:close_match edge from lpsn: to INSDC:."""
    api_transform.run()
    edges = _read_tsv(api_transform.output_edge_file)
    targets = {
        e["object"]
        for e in edges
        if e["subject"] == f"{LPSN_PREFIX}1002"
        and e["object"].startswith("INSDC:")
        and e["predicate"] == "biolink:close_match"
    }
    assert targets == {"INSDC:M87049", "INSDC:AB030918"}
    # Dedup guard: the duplicate M87049 in the fixture must appear
    # exactly once, not twice.
    m87049 = [e for e in edges if e["subject"] == f"{LPSN_PREFIX}1002" and e["object"] == "INSDC:M87049"]
    assert len(m87049) == 1


def test_molecules_emit_nucleic_acid_stub_nodes(api_transform):
    """INSDC stub targets land as biolink:NucleicAcidEntity so edges aren't dangling."""
    api_transform.run()
    nodes = _read_tsv(api_transform.output_node_file)
    seq = {n["id"] for n in nodes if n["category"] == "biolink:NucleicAcidEntity"}
    assert "INSDC:M87049" in seq
    assert "INSDC:AB030918" in seq


def test_empty_molecules_emit_no_insdc_edges(api_transform):
    """Record 1005 with molecules=[] emits no INSDC edges (or stub nodes)."""
    api_transform.run()
    edges = _read_tsv(api_transform.output_edge_file)
    hits = [e for e in edges if e["subject"] == f"{LPSN_PREFIX}1005" and e["object"].startswith("INSDC:")]
    assert hits == []


def _linked_targets(edges):
    """Every lpsn:* object of a subclass_of / same_as edge."""
    return {
        e["object"]
        for e in edges
        if e["object"].startswith(LPSN_PREFIX) and e["predicate"] in ("biolink:subclass_of", "biolink:same_as")
    }


def test_every_linked_record_has_a_node_row(api_transform):
    """
    #991: 1,344 lpsn:* endpoints were invented by KGX at merge time.

    The parent chain above genus and the basonym targets are not in the GSS,
    so nothing declared them. Every record this file links to now has a row.
    """
    api_transform.run()
    nodes = {n["id"] for n in _read_tsv(api_transform.output_node_file)}
    missing = _linked_targets(_read_tsv(api_transform.output_edge_file)) - nodes
    assert not missing, sorted(missing)


def test_a_fetchable_linked_record_is_named_and_walks_up(api_transform):
    """The genus (1001) is fetched, labelled from full_name, and its own parent edge is emitted."""
    api_transform.run()
    nodes = {n["id"]: n for n in _read_tsv(api_transform.output_node_file)}
    genus = nodes[f"{LPSN_PREFIX}1001"]
    assert genus["name"] == "Escherichia"
    assert genus["category"] == "biolink:OrganismTaxon"
    edges = _read_tsv(api_transform.output_edge_file)
    assert any(
        e["subject"] == f"{LPSN_PREFIX}1001"
        and e["object"] == f"{LPSN_PREFIX}999"
        and e["predicate"] == "biolink:subclass_of"
        for e in edges
    )
    assert api_transform._stats["linked_declared"] >= 1


def test_an_unfetchable_linked_record_gets_a_declared_stub(api_transform):
    """
    The family (999) is in neither the API nor the fake web.

    A bare stub in our own namespace, saying so, beats a NamedThing KGX
    invents with nothing on it.
    """
    api_transform.run()
    nodes = {n["id"]: n for n in _read_tsv(api_transform.output_node_file)}
    stub = nodes[f"{LPSN_PREFIX}999"]
    assert stub["category"] == "biolink:OrganismTaxon"
    assert stub["name"] == ""
    assert "not retrievable" in stub["description"]
    assert api_transform._stats["linked_stubbed"] == 1
    assert "999" in api_transform._page_fetch.calls


def test_a_basonym_the_api_lacks_is_labelled_from_its_web_page(api_transform):
    """
    #1004: every one of the 665 API misses is a pre-Approved-Lists basonym.

    The JSON API has no record for them by any route, but the website has
    a page per record number. The node takes its name and rank from the
    page and its description says where the label came from; no edges are
    minted from it because the page carries no ids.
    """
    api_transform.run()
    nodes = {n["id"]: n for n in _read_tsv(api_transform.output_node_file)}
    basonym = nodes[f"{LPSN_PREFIX}1004"]
    assert basonym["name"] == "Bacterium coli"
    assert basonym["category"] == "biolink:OrganismTaxon"
    assert "not served by the LPSN JSON API" in basonym["description"]
    assert "https://lpsn.dsmz.de/taxon/1004" in basonym["description"]
    assert "basonym of name in Approved Lists" in basonym["description"]
    assert api_transform._stats["linked_from_web"] == 1
    edges = _read_tsv(api_transform.output_edge_file)
    assert not [e for e in edges if e["subject"] == f"{LPSN_PREFIX}1004"]


def test_a_web_labelled_record_is_cached_apart_from_the_api_cache(api_transform, tmp_path):
    """The page is fetched once; the second run reads the web cache and never touches the fetcher."""
    api_transform.run()
    web_cache = tmp_path / "raw" / "lpsn" / "web_cache" / "1004.json"
    assert web_cache.exists()
    assert not (tmp_path / "raw" / "lpsn" / "api_cache" / "1004.json").exists()
    cached = json.loads(web_cache.read_text())
    assert cached["kgmicrobe_source"] == "lpsn-web-page"
    api_transform._page_fetch = _FakePageFetch({})
    api_transform.run()
    assert api_transform._page_fetch.calls == ["999"]
    nodes = {n["id"]: n for n in _read_tsv(api_transform.output_node_file)}
    assert nodes[f"{LPSN_PREFIX}1004"]["name"] == "Bacterium coli"


def test_parse_taxon_page_reads_rank_name_and_statuses():
    """Title gives rank and name (quotes and italics stripped); statuses are optional."""
    from kg_microbe.transform_utils.lpsn_api.lpsn_api import parse_taxon_page

    record = parse_taxon_page(
        "4387", _WEB_PAGES["1004"].replace("Bacterium coli", "&quot;<i>Bacterium</i> sonnei&quot;")
    )
    assert record["full_name"] == "Bacterium sonnei"
    assert record["category"] == "species"
    assert record["id"] == 4387
    assert record["nomenclatural_status"] == "not validly published, basonym of name in Approved Lists"
    assert record["lpsn_taxonomic_status"] == "synonym (and no standing)"
    assert parse_taxon_page("1", "<html><title>Genus: Escherichia</title></html>") == {
        "id": 1,
        "category": "genus",
        "full_name": "Escherichia",
        "lpsn_address": "https://lpsn.dsmz.de/taxon/1",
        "kgmicrobe_source": "lpsn-web-page",
    }
    assert parse_taxon_page("1", "<html><title>LPSN</title></html>") is None
    assert parse_taxon_page("1", "<html></html>") is None


def test_a_linked_record_is_declared_once(api_transform):
    """1002 and 1005 both sit under genus 1001 (via 1002); one row for it, not two."""
    api_transform.run()
    ids = [n["id"] for n in _read_tsv(api_transform.output_node_file)]
    assert ids.count(f"{LPSN_PREFIX}1001") == 1


def test_an_api_miss_is_counted_apart_from_errors(api_transform):
    """
    #1020: the summary line read errors=665 beside linked_records_from_web=665.

    An empty result set is the API answering "no such record"; a transport or
    parse failure is an error. The fixture has two misses (999, 1004) and no
    failures.
    """
    api_transform.run()
    assert api_transform._stats["api_misses"] == 2
    assert api_transform._stats["errors"] == 0


def test_a_run_that_dies_midway_leaves_no_output_file(api_transform, monkeypatch):
    """
    A truncated nodes.tsv is worse than none (#985, same rule as lpsn's #820).

    The merge reads whatever pair is on disk as complete; absence is the state
    the freshness check and the merge both understand.
    """
    calls = {"n": 0}
    original = api_transform._emit

    def explode(record_no, record, node_writer, edge_writer):
        """Crash after one record to exercise atomic output publication."""
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("simulated crash after the first record")
        return original(record_no, record, node_writer, edge_writer)

    monkeypatch.setattr(api_transform, "_emit", explode)
    with pytest.raises(RuntimeError):
        api_transform.run()
    assert not api_transform.output_node_file.exists()
    assert not api_transform.output_edge_file.exists()
    assert not list(Path(api_transform.output_dir).glob("*.partial"))


def test_cold_cache_records_are_consumed_and_audited_after_persistence(api_transform):
    """Generated API records are dynamic inputs, so an empty cache can bootstrap offline."""
    assert not (api_transform.input_base_dir / "lpsn/api_cache/1002.json").exists()
    api_transform.run()
    api_transform.verify_consumed_inputs()
    snapshots = api_transform.consumed_input_snapshots
    assert set(snapshots) == {GSS_ROLE, *(RECORD_ROLE_PREFIX + key for key in ("1001", "1002", "1005"))}
    for snapshot in snapshots.values():
        assert hashlib.sha256(Path(snapshot["path"]).read_bytes()).hexdigest() == snapshot["sha256"]
    rows = _read_tsv(api_transform.output_dir / AUDIT_FILE)
    assert len(rows) == 6  # GSS selection, three API records, two absent API cache paths.
    assert {row["record_no"] for row in rows if row["state"] == "absent"} == {"999", "1004"}
    assert set(api_transform.producer_audit_snapshots) == {AUDIT_FILE}


def _native_report(transform):
    """Capture the native subset without using a saved report to hydrate live evidence."""
    return {
        "producer_native_inputs": transform.producer_native_inputs,
        "consumed_inputs": transform.consumed_input_snapshots,
        "raw_input_directory": str(transform.input_base_dir.resolve()),
    }


@pytest.mark.parametrize("damage", ["change", "delete", "retarget", "cache_directory_retarget", "gss_change"])
@pytest.mark.parametrize("saved", [False, True])
def test_selected_api_input_drift_blocks_live_and_saved_admission(api_transform, tmp_path, damage, saved):
    """A valid original file cannot bless changed bytes, a disappeared record or a new selected locator."""
    api_transform.run()
    report = _native_report(api_transform)
    cache = api_transform.input_base_dir / "lpsn/api_cache"
    path = cache / "1002.json"
    if damage == "change":
        path.write_text(path.read_text().replace("Primary species", "Changed species"))
    elif damage == "delete":
        path.unlink()
    elif damage == "retarget":
        other = tmp_path / "same-record.json"
        other.write_bytes(path.read_bytes())
        path.unlink()
        path.symlink_to(other)
    elif damage == "cache_directory_retarget":
        other = tmp_path / "other-cache"
        cache.rename(other)
        cache.symlink_to(other, target_is_directory=True)
    else:
        with api_transform._find_gss_nodes().open("a") as handle:
            handle.write("lpsn:99999\tbiolink:OrganismTaxon\n")
    with pytest.raises(SourceFinalizationRequired, match="changed|missing|locator|record"):
        if saved:
            LPSNAPITransform.verify_recorded_native_inputs(
                report, api_transform.output_dir / "source_finalization.json"
            )
        else:
            api_transform.verify_consumed_inputs()


def test_saved_admission_retains_locator_binding_after_initial_verification(api_transform, tmp_path):
    """Read-only merge admission keeps selected paths bound throughout its publication window."""
    api_transform.run()
    report = _native_report(api_transform)
    guard = LPSNAPITransform.verify_recorded_native_inputs(
        report, api_transform.output_dir / "source_finalization.json"
    )
    path = api_transform.input_base_dir / "lpsn/api_cache/1002.json"
    other = tmp_path / "same-record.json"
    other.write_bytes(path.read_bytes())
    path.unlink()
    path.symlink_to(other)
    with pytest.raises(SourceFinalizationRequired, match="locator changed"):
        guard.verify()


def test_previously_absent_selected_api_cache_record_invalidates_completion(api_transform):
    """A newly available parent record requires regeneration rather than retaining a stale stub."""
    api_transform.run()
    report = _native_report(api_transform)
    (api_transform.input_base_dir / "lpsn/api_cache/999.json").write_text('{"id": 999, "full_name": "New parent"}')
    with pytest.raises(SourceFinalizationRequired, match="appeared"):
        api_transform.verify_native_inputs()
    with pytest.raises(SourceFinalizationRequired, match="appeared"):
        LPSNAPITransform.verify_recorded_native_inputs(report, api_transform.output_dir / "source_finalization.json")


def test_unselected_cached_record_does_not_invalidate_completion(api_transform):
    """The contract follows requested records, not unrelated cache membership."""
    api_transform.run()
    (api_transform.input_base_dir / "lpsn/api_cache/99999.json").write_text('{"id": 99999}')
    api_transform.verify_consumed_inputs()


@pytest.mark.parametrize("damage", ["delete", "drop_row", "drop_contract_record", "drop_snapshot"])
def test_record_audit_and_dynamic_inventory_cannot_be_omitted(api_transform, damage):
    """Selected records, consumed snapshots and mandatory audit rows must agree exactly."""
    api_transform.run()
    report = _native_report(api_transform)
    audit = api_transform.output_dir / AUDIT_FILE
    if damage == "delete":
        audit.unlink()
    elif damage == "drop_row":
        audit.write_text("\n".join(audit.read_text().splitlines()[:-1]) + "\n")
    elif damage == "drop_contract_record":
        del report["producer_native_inputs"]["records"]["1002"]
    else:
        del report["consumed_inputs"][RECORD_ROLE_PREFIX + "1002"]
    with pytest.raises(SourceFinalizationRequired):
        LPSNAPITransform.verify_recorded_native_inputs(report, api_transform.output_dir / "source_finalization.json")


def test_recorded_native_contract_cannot_replace_live_consumption(api_transform):
    """Restore/finalization never turns a mutable report into proof that this instance read its inputs."""
    api_transform.run()
    replacement = api_transform.producer_native_inputs
    replacement["records"].clear()
    assert api_transform.producer_native_inputs["records"]
    with pytest.raises(SourceFinalizationRequired, match="native reads differ"):
        api_transform.producer_native_inputs = replacement


def test_finalized_lpsn_source_retains_record_evidence_and_rejects_stale_labels(api_transform):
    """Exercise the actual source finalization and merge freshness boundary with a canned client."""
    api_transform.run()
    report = api_transform.finalize(fresh_run=True)
    api_transform.verify_consumed_inputs()
    assert api_transform.finalize() == report
    assert report["consumed_inputs"][RECORD_ROLE_PREFIX + "1002"] in report["inputs"]
    assert AUDIT_FILE in report["producer_audit_members"]
    paths = [api_transform.output_node_file, api_transform.output_edge_file]
    verify_finalized_source_files(paths)
    cache = api_transform.input_base_dir / "lpsn/api_cache/1002.json"
    original = cache.read_bytes()
    cache.write_bytes(original.replace(b"Primary species", b"Changed species"))
    with pytest.raises(SourceFinalizationRequired, match="changed"):
        verify_finalized_source_files(paths)
    cache.write_bytes(original)
    verify_finalized_source_files(paths)
    (api_transform.output_dir / AUDIT_FILE).unlink()
    with pytest.raises(SourceFinalizationRequired, match="missing"):
        verify_finalized_source_files(paths)


def _rewrite_native_record_audit(transform, report):
    """Model coordinated metadata editing, including all recorded audit-byte identities."""
    audit = transform.output_dir / AUDIT_FILE
    with audit.open("w", newline="") as handle:
        writer = tsv_writer(handle)
        writer.writerow(AUDIT_COLUMNS)
        writer.writerows(audit_rows(report["producer_native_inputs"]))
    identity = {"bytes": audit.stat().st_size, "sha256": hashlib.sha256(audit.read_bytes()).hexdigest()}
    report["producer_audit_members"][AUDIT_FILE] = identity
    report["audit_members"][AUDIT_FILE] = identity
    (transform.output_dir / "source_finalization.json").write_text(json.dumps(report))


@pytest.mark.parametrize("record_no", ["1002", "1001", "999"])
def test_coordinated_record_omission_cannot_override_verified_source_selection(api_transform, record_no):
    """GSS roots, linked payloads and absent linked records remain mandatory after rehashed ledger edits."""
    api_transform.run()
    report = api_transform.finalize(fresh_run=True)
    paths = [api_transform.output_node_file, api_transform.output_edge_file]
    before = [path.read_bytes() for path in paths]
    verify_finalized_source_files(paths)
    del report["producer_native_inputs"]["records"][record_no]
    snapshot = report["consumed_inputs"].pop(RECORD_ROLE_PREFIX + record_no, None)
    if snapshot is not None:
        report["inputs"] = [item for item in report["inputs"] if item["path"] != snapshot["path"]]
    _rewrite_native_record_audit(api_transform, report)
    assert [path.read_bytes() for path in paths] == before
    with pytest.raises(SourceFinalizationRequired, match=f"required selected record omitted: {record_no}"):
        verify_finalized_source_files(paths)


def test_coordinated_extra_record_cannot_expand_verified_source_selection(api_transform):
    """An unrelated cache payload cannot be inserted into the source's claimed request inventory."""
    api_transform.run()
    report = api_transform.finalize(fresh_run=True)
    extra = api_transform.input_base_dir / "lpsn/api_cache/99999.json"
    extra.write_text('{"id": 99999}')
    snapshot = {"path": str(extra.resolve()), "sha256": hashlib.sha256(extra.read_bytes()).hexdigest()}
    report["producer_native_inputs"]["records"]["99999"] = {
        "state": "present",
        "locator": str(extra.absolute()),
        **snapshot,
    }
    report["consumed_inputs"][RECORD_ROLE_PREFIX + "99999"] = snapshot
    report["inputs"].append(snapshot)
    _rewrite_native_record_audit(api_transform, report)
    with pytest.raises(SourceFinalizationRequired, match="outside the required selection"):
        verify_finalized_source_files([api_transform.output_node_file, api_transform.output_edge_file])


def _run_selection_fixture(tmp_path, roots, records):
    """Run bounded topology fixtures through the same producer and saved admission rules."""
    raw, output = tmp_path / "raw", tmp_path / "transformed"
    raw.mkdir()
    _write_gss_nodes(output / "lpsn/nodes.tsv", roots)
    transform = LPSNAPITransform(
        input_dir=raw, output_dir=output, client=_FakeLpsnClient(records), page_fetch=_FakePageFetch({})
    )
    transform.run()
    LPSNAPITransform.verify_recorded_native_inputs(
        _native_report(transform), transform.output_dir / "source_finalization.json"
    )
    return transform


def test_independent_inventory_preserves_cycle_and_duplicate_link_semantics(tmp_path):
    """Cycles, self links and repeated parent/basonym references request each linked record once."""
    transform = _run_selection_fixture(
        tmp_path,
        ["1"],
        {
            "1": {"id": 1, "lpsn_parent_id": 2, "basonym_id": 2},
            "2": {"id": 2, "lpsn_parent_id": 3, "basonym_id": 2},
            "3": {"id": 3, "lpsn_parent_id": 1, "basonym_id": 2},
        },
    )
    assert set(transform.producer_native_inputs["records"]) == {"1", "2", "3"}


@pytest.mark.parametrize("second_root", [False, True])
def test_independent_inventory_preserves_depth_boundary_and_predeclared_roots(tmp_path, second_root):
    """Depth 12 is consumed, depth 13 is skipped, and a later GSS root starts its own traversal."""
    records = {str(number): {"id": number, "lpsn_parent_id": number + 1} for number in range(1, 17)}
    records["17"] = {"id": 17}
    transform = _run_selection_fixture(tmp_path, ["1", "15"] if second_root else ["1"], records)
    expected = {str(number) for number in range(1, 18 if second_root else 15)}
    assert set(transform.producer_native_inputs["records"]) == expected
