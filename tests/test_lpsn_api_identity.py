"""Reject unrelated or malformed LPSN API records before citation attribution (#1837)."""

import csv
import json
from types import SimpleNamespace

import pytest

from kg_microbe.transform_utils.lpsn_api.lpsn_api import LPSNAPITransform
from kg_microbe.transform_utils.lpsn_api.native_inputs import AUDIT_FILE, CACHE_SUBDIR
from kg_microbe.utils.source_finalization import SourceFinalizationRequired

_CITATION = "Fixture authors. Source-owned species description. Fixture Journal 2000."
_DOI = "doi:10.1234/identity-fixture"


class _CannedClient:
    """Return the supplied sequence, including malformed records, without network access."""

    def __init__(self, records):
        """Retain records and record every search for cache-precedence assertions."""
        self.records = records
        self.calls = []

    def search(self, id=None):  # noqa: A002 — matches the API client interface
        """Record the literal requested ID."""
        self.calls.append(id)

    def retrieve(self):
        """Yield even null payloads, distinct from an empty API result."""
        return iter(self.records)


def _record(record_id=1002):
    """Make a minimal publication-bearing record without linked taxonomy records."""
    return {
        "id": record_id,
        "publication_doi": _DOI.removeprefix("doi:"),
        "publication_pmid": 12345,
        "publication_text": _CITATION,
        "molecules": [],
    }


def _reject_page_fetch(record_no):
    """Ensure the identity fixtures cannot fall back to a web lookup."""
    raise AssertionError(f"Unexpected web lookup for {record_no}")


def _transform(tmp_path, records):
    """Create a complete isolated run with one GSS-selected record and a canned client."""
    raw = tmp_path / "raw"
    raw.mkdir()
    transformed = tmp_path / "transformed"
    gss = transformed / "lpsn" / "nodes.tsv"
    gss.parent.mkdir(parents=True)
    gss.write_text("id\tcategory\nlpsn:1002\tbiolink:OrganismTaxon\n")
    client = _CannedClient(records)
    transform = LPSNAPITransform(
        input_dir=raw,
        output_dir=transformed,
        client=client,
        page_fetch=_reject_page_fetch,
    )
    return transform, client, raw / CACHE_SUBDIR / "1002.json"


def _assert_unpublished(transform):
    """Require failure before attribution and before any graph or audit is published."""
    assert transform._publication_citations == {}
    assert not transform.output_node_file.exists()
    assert not transform.output_edge_file.exists()
    assert not (transform.output_dir / AUDIT_FILE).exists()
    assert transform._stats["fetched"] == 0
    assert transform._stats["from_cache"] == 0


@pytest.mark.parametrize("origin", ["cache", "live"])
@pytest.mark.parametrize(
    "record_id",
    [None, True, False, 1002.0, ["1002"], {"value": 1002}, "1005", "1002 ", "01002"],
    ids=["null", "true", "false", "float", "list", "mapping", "unrelated", "whitespace", "zero-padded"],
)
def test_wrong_record_identity_aborts_before_publication(tmp_path, origin, record_id):
    """Cache filenames and requested IDs cannot relabel another payload's citations."""
    payload = _record(record_id)
    transform, client, cache = _transform(tmp_path, [payload])
    original = json.dumps(payload).encode()
    if origin == "cache":
        cache.parent.mkdir(parents=True)
        cache.write_bytes(original)

    with pytest.raises(SourceFinalizationRequired, match="identity does not match requested record 1002"):
        transform.run()

    _assert_unpublished(transform)
    assert client.calls == ([] if origin == "cache" else ["1002"])
    if origin == "cache":
        assert cache.read_bytes() == original
    else:
        assert not cache.exists()


@pytest.mark.parametrize("origin", ["cache", "live"])
@pytest.mark.parametrize(
    "payload",
    [None, [], 1002, "record", {"publication_doi": "10.1234/identity-fixture", "publication_text": _CITATION}],
    ids=["null", "list", "number", "string", "missing-id"],
)
def test_malformed_record_aborts_before_publication(tmp_path, origin, payload):
    """An API result item must be a mapping with its own explicit matching ID."""
    transform, client, cache = _transform(tmp_path, [payload])
    original = json.dumps(payload).encode()
    if origin == "cache":
        cache.parent.mkdir(parents=True)
        cache.write_bytes(original)

    with pytest.raises(SourceFinalizationRequired, match="identity does not match requested record 1002"):
        transform.run()

    _assert_unpublished(transform)
    assert client.calls == ([] if origin == "cache" else ["1002"])
    if origin == "cache":
        assert cache.read_bytes() == original
    else:
        assert not cache.exists()


@pytest.mark.parametrize("origin", ["cache", "live"])
@pytest.mark.parametrize("record_id", [1002, "1002"], ids=["integer", "string"])
def test_matching_record_identity_preserves_citation_attribution(tmp_path, origin, record_id):
    """Both native ID representations produce labels bound to the requested record."""
    payload = _record(record_id)
    transform, client, cache = _transform(tmp_path, [payload])
    if origin == "cache":
        cache.parent.mkdir(parents=True)
        cache.write_text(json.dumps(payload))

    transform.run()

    assert client.calls == ([] if origin == "cache" else ["1002"])
    assert json.loads(cache.read_text()) == payload
    with transform.output_node_file.open(newline="") as handle:
        nodes = {row["id"]: row for row in csv.DictReader(handle, delimiter="\t")}
    for publication in (_DOI, "PMID:12345"):
        assert nodes[publication]["name"] == _CITATION
        assert "lpsn:1002.publication_text" in nodes[publication]["description"]
    assert transform.output_edge_file.stat().st_size > 0
    assert (transform.output_dir / AUDIT_FILE).stat().st_size > 0


def test_persisted_record_audit_uses_lf_and_contains_required_rows(tmp_path):
    """Keep the mandatory producer ledger usable by LF-only TSV consumers (#1839)."""
    transform, client, cache = _transform(tmp_path, [_record()])

    transform.run()

    assert client.calls == ["1002"]
    assert cache.stat().st_size > 0
    audit_bytes = (transform.output_dir / AUDIT_FILE).read_bytes()
    assert audit_bytes.endswith(b"\n")
    assert b"\r" not in audit_bytes
    rows = list(csv.DictReader(audit_bytes.decode("utf-8").splitlines(), delimiter="\t"))
    assert len(rows) == 2
    assert {(row["kind"], row["record_no"], row["state"]) for row in rows} == {
        ("gss", "", "present"),
        ("api", "1002", "present"),
    }
    assert all(row["locator"] and row["path"] and row["sha256"] for row in rows)


def test_live_client_record_object_is_validated_and_persisted(tmp_path):
    """A client object exposing record fields through __dict__ remains supported."""
    payload = _record()
    transform, client, cache = _transform(tmp_path, [SimpleNamespace(**payload)])

    transform.run()

    assert client.calls == ["1002"]
    assert json.loads(cache.read_text()) == payload
    with transform.output_node_file.open(newline="") as handle:
        nodes = {row["id"]: row for row in csv.DictReader(handle, delimiter="\t")}
    assert nodes[_DOI]["name"] == _CITATION
    assert "lpsn:1002.publication_text" in nodes[_DOI]["description"]


@pytest.mark.parametrize("second_id", [1002, 1005], ids=["duplicate", "unrelated"])
def test_multiple_live_records_are_rejected_before_cache_write(tmp_path, second_id):
    """A requested record never silently selects the first of multiple payloads."""
    transform, client, cache = _transform(tmp_path, [_record(), _record(second_id)])

    with pytest.raises(SourceFinalizationRequired, match="multiple payloads for requested record 1002"):
        transform.run()

    _assert_unpublished(transform)
    assert client.calls == ["1002"]
    assert not cache.exists()


def test_malformed_cached_json_aborts_without_live_fallback(tmp_path):
    """An unreadable selected cache cannot be replaced by an unrequested live response."""
    transform, client, cache = _transform(tmp_path, [_record()])
    cache.parent.mkdir(parents=True)
    original = b'{"id": 1002, invalid JSON}'
    cache.write_bytes(original)

    with pytest.raises(json.JSONDecodeError):
        transform.run()

    _assert_unpublished(transform)
    assert client.calls == []
    assert cache.read_bytes() == original
