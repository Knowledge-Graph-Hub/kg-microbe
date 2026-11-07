"""Tests for the LPSN JSON API transform (auth-gated enrichment layer)."""

import csv
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from kg_microbe.transform_utils.lpsn.lpsn import LPSN_KNOWLEDGE_SOURCE, LPSN_PREFIX
from kg_microbe.transform_utils.lpsn_api.lpsn_api import LPSNAPITransform


@pytest.fixture(autouse=True)
def _synthetic_authentication_environment(monkeypatch):
    """Keep native record guards independent of any credentials in the test host environment."""
    monkeypatch.setenv("LPSN_USERNAME", "synthetic-env-user")
    monkeypatch.setenv("LPSN_PASSWORD", "synthetic-env-password")


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
        self.access_token = "synthetic-access-token"  # noqa: S105 — offline fake, never a credential
        self.refresh_token = "synthetic-refresh-token"  # noqa: S105 — offline fake, never a credential

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
            "ijsem_list_doi": "10.1099/ijsem.0.999999",
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


def test_authenticated_client_uses_complete_environment_without_dotenv(monkeypatch):
    """Supplied credentials must reach the client without any dotenv discovery or read."""
    import kg_microbe.transform_utils.lpsn_api.lpsn_api as api_mod

    monkeypatch.setenv("LPSN_USERNAME", "synthetic-env-user")
    monkeypatch.setenv("LPSN_PASSWORD", "synthetic-env-password")
    dotenv = Mock(side_effect=AssertionError("Complete environment must not load dotenv"))
    client = _FakeLpsnClient({})
    constructor = Mock(return_value=client)
    monkeypatch.setattr(api_mod, "load_dotenv", dotenv)
    monkeypatch.setitem(sys.modules, "lpsn", SimpleNamespace(LpsnClient=constructor))

    transform = LPSNAPITransform.__new__(LPSNAPITransform)
    assert transform._make_authenticated_client() is client
    dotenv.assert_not_called()
    constructor.assert_called_once_with("synthetic-env-user", "synthetic-env-password")


@pytest.mark.parametrize(
    "username,password", [(None, None), ("synthetic-env-user", None), (None, "synthetic-env-password")]
)
def test_authenticated_client_preserves_missing_key_dotenv_fallback(monkeypatch, username, password):
    """The legacy fallback can supply absent keys while retaining supplied environment values."""
    import kg_microbe.transform_utils.lpsn_api.lpsn_api as api_mod

    for key, value in (("LPSN_USERNAME", username), ("LPSN_PASSWORD", password)):
        monkeypatch.delenv(key, raising=False)
        if value is not None:
            monkeypatch.setenv(key, value)

    def supply_missing_credentials():
        """Model default dotenv behavior without reading any credential file."""
        for key, value in (("LPSN_USERNAME", "synthetic-file-user"), ("LPSN_PASSWORD", "synthetic-file-password")):
            if key not in api_mod.os.environ:
                monkeypatch.setenv(key, value)

    dotenv = Mock(side_effect=supply_missing_credentials)
    client = _FakeLpsnClient({})
    constructor = Mock(return_value=client)
    monkeypatch.setattr(api_mod, "load_dotenv", dotenv)
    monkeypatch.setitem(sys.modules, "lpsn", SimpleNamespace(LpsnClient=constructor))

    transform = LPSNAPITransform.__new__(LPSNAPITransform)
    assert transform._make_authenticated_client() is client
    dotenv.assert_called_once_with()
    constructor.assert_called_once_with(username or "synthetic-file-user", password or "synthetic-file-password")


@pytest.mark.parametrize(
    "username,password",
    [
        (None, None),
        ("synthetic-env-user", None),
        (None, "synthetic-env-password"),
        ("", "synthetic-env-password"),
        ("synthetic-env-user", ""),
    ],
)
def test_authenticated_client_rejects_incomplete_fallback(monkeypatch, username, password):
    """Missing or empty credentials after fallback must never construct an authenticated client."""
    import kg_microbe.transform_utils.lpsn_api.lpsn_api as api_mod

    for key, value in (("LPSN_USERNAME", username), ("LPSN_PASSWORD", password)):
        monkeypatch.delenv(key, raising=False)
        if value is not None:
            monkeypatch.setenv(key, value)
    dotenv = Mock(return_value=False)
    constructor = Mock(side_effect=AssertionError("Incomplete credentials must not construct a client"))
    monkeypatch.setattr(api_mod, "load_dotenv", dotenv)
    monkeypatch.setitem(sys.modules, "lpsn", SimpleNamespace(LpsnClient=constructor))

    transform = LPSNAPITransform.__new__(LPSNAPITransform)
    with pytest.raises(RuntimeError, match="LPSN_USERNAME and LPSN_PASSWORD"):
        transform._make_authenticated_client()
    dotenv.assert_called_once_with()
    constructor.assert_not_called()


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


@pytest.fixture()
def factory_transform(tmp_path, monkeypatch):
    """Exercise the production client factory using only supplied synthetic environment keys."""
    import kg_microbe.transform_utils.lpsn_api.lpsn_api as api_mod

    input_dir = tmp_path / "raw"
    output_dir = tmp_path / "transformed"
    input_dir.mkdir()
    _write_gss_nodes(output_dir / "lpsn" / "nodes.tsv", ["1"])
    monkeypatch.setenv("LPSN_USERNAME", "synthetic-env-user")
    monkeypatch.setenv("LPSN_PASSWORD", "synthetic-env-password")
    monkeypatch.setattr(api_mod, "load_dotenv", Mock(side_effect=AssertionError("No credential file read")))
    return LPSNAPITransform(input_dir=input_dir, output_dir=output_dir, page_fetch=_FakePageFetch({}))


@pytest.mark.parametrize(
    "token_fields",
    [
        {},  # Official constructor can exhaust authentication retries without setting tokens.
        {"access_token": "synthetic-access-token"},
        {"refresh_token": "synthetic-refresh-token"},
        {"access_token": "", "refresh_token": "synthetic-refresh-token"},
        {"access_token": "synthetic-access-token", "refresh_token": ""},
        {"access_token": True, "refresh_token": "synthetic-refresh-token"},
        {"access_token": "synthetic-access-token", "refresh_token": 123},
        {"access_token": " ", "refresh_token": "synthetic-refresh-token"},
        {"access_token": "synthetic-access-token", "refresh_token": "\t"},
    ],
)
def test_incomplete_authentication_refuses_warm_cache(factory_transform, monkeypatch, token_fields):
    """Cached records cannot turn an exhausted or invalid authentication attempt into success."""
    cache = factory_transform.input_base_dir / "lpsn" / "api_cache"
    cache.mkdir(parents=True)
    cached = cache / "1.json"
    native = b'{"id": 1, "full_name": "Synthetic cached species"}\n'
    cached.write_bytes(native)
    client = SimpleNamespace(**token_fields)
    constructor = Mock(return_value=client)
    monkeypatch.setitem(sys.modules, "lpsn", SimpleNamespace(LpsnClient=constructor))

    with pytest.raises(RuntimeError) as error:
        factory_transform.run()

    assert str(error.value) == "LPSN API authentication did not return both required tokens."
    constructor.assert_called_once_with("synthetic-env-user", "synthetic-env-password")
    assert factory_transform._stats["from_cache"] == 0
    assert cached.read_bytes() == native
    assert not factory_transform.output_node_file.exists()
    assert not factory_transform.output_edge_file.exists()
    assert not list(factory_transform.output_dir.glob("*.partial"))


def test_authenticated_warm_cache_preserves_success(factory_transform, monkeypatch):
    """Valid authenticated clients may reuse exact native cached records without an API request."""
    cache = factory_transform.input_base_dir / "lpsn" / "api_cache"
    cache.mkdir(parents=True)
    cached = cache / "1.json"
    native = b'{"id": 1, "full_name": "Synthetic cached species"}\n'
    cached.write_bytes(native)
    client = _FakeLpsnClient({})
    client.search = Mock(side_effect=AssertionError("Warm cache must not fetch"))
    monkeypatch.setitem(sys.modules, "lpsn", SimpleNamespace(LpsnClient=Mock(return_value=client)))

    factory_transform.run()

    client.search.assert_not_called()
    assert factory_transform._stats["from_cache"] == 1
    assert factory_transform._stats["errors"] == 0
    assert cached.read_bytes() == native
    assert [row["id"] for row in _read_tsv(factory_transform.output_node_file)] == ["lpsn:1"]
    assert _read_tsv(factory_transform.output_edge_file) == []


def test_valid_empty_api_result_can_complete(factory_transform, monkeypatch):
    """An authenticated successful empty result is an API miss, not a failed fetch."""
    client = _FakeLpsnClient({})
    monkeypatch.setitem(sys.modules, "lpsn", SimpleNamespace(LpsnClient=Mock(return_value=client)))

    factory_transform.run()

    assert client._current == "1"
    assert factory_transform._stats["api_misses"] == 1
    assert factory_transform._stats["errors"] == 0
    assert _read_tsv(factory_transform.output_node_file) == []
    assert _read_tsv(factory_transform.output_edge_file) == []
    assert factory_transform._page_fetch.calls == []


@pytest.mark.parametrize("linked", [False, True])
@pytest.mark.parametrize("existing_outputs", [False, True])
def test_api_transport_errors_refuse_atomic_publication(tmp_path, monkeypatch, linked, existing_outputs):
    """Failed direct or linked API fetches cannot publish partial graphs or replace a prior pair."""
    import requests

    input_dir = tmp_path / "raw"
    output_dir = tmp_path / "transformed"
    input_dir.mkdir()
    _write_gss_nodes(output_dir / "lpsn" / "nodes.tsv", ["1"] if linked else ["1", "2", "3"])
    record = {"id": 1, "full_name": "Synthetic fetched species"}
    if linked:
        record.update(lpsn_parent_id=2, basonym_id=3)
    client = _FakeLpsnClient({"1": record})
    calls = []
    original_search = client.search

    def fail_selected_fetch(id=None):  # noqa: A002 — follows the native client signature
        """Let one record reach both temporary writers before two native transport failures."""
        calls.append(id)
        if id in {"2", "3"}:
            raise requests.ConnectionError("synthetic transport failure")
        original_search(id=id)

    monkeypatch.setattr(client, "search", fail_selected_fetch)
    transform = LPSNAPITransform(
        input_dir=input_dir, output_dir=output_dir, client=client, page_fetch=_FakePageFetch({})
    )
    prior = {
        transform.output_node_file: b"id\tcategory\nprior:1\tbiolink:OrganismTaxon\n",
        transform.output_edge_file: b"subject\tpredicate\tobject\nprior:1\tbiolink:related_to\tprior:1\n",
    }
    if existing_outputs:
        transform.output_dir.mkdir(parents=True, exist_ok=True)
        for path, content in prior.items():
            path.write_bytes(content)

    with pytest.raises(RuntimeError) as error:
        transform.run()

    assert (
        str(error.value) == "LPSN API transform failed with 2 record fetch error(s); graph outputs were not published."
    )
    assert calls == ["1", "2", "3"]
    assert transform._stats["fetched"] == 1
    assert transform._stats["errors"] == 2
    assert transform._stats["api_misses"] == 0
    assert transform._stats["linked_stubbed"] == (2 if linked else 0)
    assert json.loads((input_dir / "lpsn" / "api_cache" / "1.json").read_text()) == record
    for path, content in prior.items():
        if existing_outputs:
            assert path.read_bytes() == content
        else:
            assert not path.exists()
    assert not list(transform.output_dir.glob("*.partial"))


def _record_with_echo(secret, location):
    """Embed a synthetic sensitive string in a native-looking nested response."""
    record = {"id": 1, "full_name": "Synthetic public species"}
    echo = f"prefix-{secret}-suffix"
    if location == "key":
        record["details"] = [{echo: "scientific text"}]
    elif location == "value":
        record["details"] = [{"source_note": echo}]
    else:
        record["details"] = ["scientific text", [echo]]
    return record


@pytest.mark.parametrize("location", ["key", "value", "list"])
@pytest.mark.parametrize(
    "secret",
    ["synthetic-env-user", "synthetic-env-password", "synthetic-access-token", "synthetic-refresh-token"],
)
def test_fresh_record_echo_refused_before_cache_or_graph(factory_transform, monkeypatch, capsys, secret, location):
    """No known credential or token echo in a native record may be persisted or emitted."""
    record = _record_with_echo(secret, location)
    client = _FakeLpsnClient({"1": record})
    monkeypatch.setitem(sys.modules, "lpsn", SimpleNamespace(LpsnClient=Mock(return_value=client)))

    with pytest.raises(RuntimeError) as error:
        factory_transform.run()

    assert str(error.value) == "LPSN API record contains sensitive authentication material."
    captured = capsys.readouterr()
    assert secret not in captured.out + captured.err + str(error.value)
    assert not (factory_transform.input_base_dir / "lpsn" / "api_cache" / "1.json").exists()
    assert not factory_transform.output_node_file.exists()
    assert not factory_transform.output_edge_file.exists()
    assert not list(factory_transform.output_dir.glob("*.partial"))


@pytest.mark.parametrize(
    "field", ["Token", "access-token", "REFRESH_TOKEN", "password", "Authorization", "LPSN_USERNAME", "LPSN_PASSWORD"]
)
def test_sensitive_record_fields_refused_without_known_value(factory_transform, monkeypatch, field):
    """Named authentication fields are refused even when their values differ from known credentials."""
    record = {"id": 1, "full_name": "Synthetic public species", "details": [{field: "unrelated-value"}]}
    client = _FakeLpsnClient({"1": record})
    monkeypatch.setitem(sys.modules, "lpsn", SimpleNamespace(LpsnClient=Mock(return_value=client)))

    with pytest.raises(RuntimeError, match=r"^LPSN API record contains sensitive authentication material\.$"):
        factory_transform.run()

    assert not (factory_transform.input_base_dir / "lpsn" / "api_cache" / "1.json").exists()
    assert not factory_transform.output_node_file.exists()
    assert not factory_transform.output_edge_file.exists()


@pytest.mark.parametrize("location", ["key", "value", "list"])
@pytest.mark.parametrize("secret", ["synthetic-env-password", "synthetic-refresh-token"])
def test_cached_record_echo_refused_without_rewrite(factory_transform, monkeypatch, secret, location):
    """Existing native cache and prior graphs remain byte-identical on a cached-record refusal."""
    record = _record_with_echo(secret, location)
    cache = factory_transform.input_base_dir / "lpsn" / "api_cache"
    cache.mkdir(parents=True)
    cached = cache / "1.json"
    native = json.dumps(record, indent=3).encode() + b"\n"
    cached.write_bytes(native)
    client = _FakeLpsnClient({})
    client.search = Mock(side_effect=AssertionError("Refused cache must not be silently replaced"))
    monkeypatch.setitem(sys.modules, "lpsn", SimpleNamespace(LpsnClient=Mock(return_value=client)))
    prior = {
        factory_transform.output_node_file: b"id\tcategory\nprior:1\tbiolink:OrganismTaxon\n",
        factory_transform.output_edge_file: b"subject\tpredicate\tobject\n",
    }
    factory_transform.output_dir.mkdir(parents=True, exist_ok=True)
    for path, content in prior.items():
        path.write_bytes(content)

    with pytest.raises(RuntimeError, match=r"^LPSN API record contains sensitive authentication material\.$"):
        factory_transform.run()

    client.search.assert_not_called()
    assert cached.read_bytes() == native
    assert factory_transform._stats["from_cache"] == 0
    for path, content in prior.items():
        assert path.read_bytes() == content
    assert not list(factory_transform.output_dir.glob("*.partial"))


@pytest.mark.parametrize(
    "secret",
    ["synthetic-access-token", "synthetic-refresh-token", "synthetic-new-access", "synthetic-new-refresh"],
)
def test_retrieval_refresh_checks_both_token_pairs(factory_transform, monkeypatch, secret):
    """Refreshing a client during retrieve cannot make either old or new token echoes safe to cache."""
    client = _FakeLpsnClient({})
    record = _record_with_echo(secret, "value")

    def refreshed_retrieve():
        """Replace both synthetic tokens while producing the native record."""
        client.access_token = "synthetic-new-access"  # noqa: S105 — offline fake
        client.refresh_token = "synthetic-new-refresh"  # noqa: S105 — offline fake
        yield record

    monkeypatch.setattr(client, "retrieve", refreshed_retrieve)
    monkeypatch.setitem(sys.modules, "lpsn", SimpleNamespace(LpsnClient=Mock(return_value=client)))

    with pytest.raises(RuntimeError, match=r"^LPSN API record contains sensitive authentication material\.$"):
        factory_transform.run()

    assert not (factory_transform.input_base_dir / "lpsn" / "api_cache" / "1.json").exists()
    assert not factory_transform.output_node_file.exists()
    assert not factory_transform.output_edge_file.exists()


def test_benign_scientific_record_retains_exact_content(factory_transform, monkeypatch):
    """Scientific authority and free text are preserved rather than redacted or broadly rejected."""
    record = {
        "id": 1,
        "full_name": "Synthetic public species",
        "authority": "Example et al. 2026",
        "details": ["authorization discussed in publication", {"note": "token for culture tracking"}],
        "is_legitimate": True,
    }
    client = _FakeLpsnClient({"1": record})
    monkeypatch.setitem(sys.modules, "lpsn", SimpleNamespace(LpsnClient=Mock(return_value=client)))

    factory_transform.run()

    cached = factory_transform.input_base_dir / "lpsn" / "api_cache" / "1.json"
    assert json.loads(cached.read_text()) == record
    assert [row["id"] for row in _read_tsv(factory_transform.output_node_file)] == ["lpsn:1"]
    assert factory_transform._stats["fetched"] == 1
    assert factory_transform._stats["errors"] == 0
