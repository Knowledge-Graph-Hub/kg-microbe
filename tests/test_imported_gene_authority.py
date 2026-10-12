"""Native gene records authorize exactly the imported IDs, not their namespace."""

import copy
import hashlib
import json
from io import StringIO
from pathlib import Path

import pytest

MAPPING = Path(__file__).parents[1] / "mappings" / "imported_gene_authority.json"


def test_curation_is_exact_projection_of_pinned_native_response():
    """Record curation and the source content identity can be checked offline."""
    from kg_microbe.utils.imported_gene_authority import GENE_NATIVE_EVIDENCE_FILE

    raw = (Path(__file__).parent / "resources" / "ncbi_gene_authority_esummary.json").read_bytes()
    assert GENE_NATIVE_EVIDENCE_FILE.read_bytes() == raw
    native = json.loads(raw)["result"]
    payload = json.loads(MAPPING.read_text())
    assert hashlib.sha256(raw).hexdigest() == payload["source_sha256"]
    assert set(native["uids"]) == {"26468", "55553"}
    for evidence in payload["records"].values():
        projected = evidence["native_record"]
        assert projected == {key: native[projected["uid"]][key] for key in projected}


def test_pinned_native_records_supply_gene_category_and_official_symbol():
    """Real records correct only their own IDs and preserve taxon evidence."""
    from kg_microbe.utils.imported_gene_authority import imported_gene_record

    lhx6 = imported_gene_record("NCBIGene:26468")
    sox6 = imported_gene_record("NCBIGene:55553")
    assert (lhx6.name, lhx6.category, lhx6.taxon) == ("LHX6", "biolink:Gene", "NCBITaxon:9606")
    assert (sox6.name, sox6.description) == ("SOX6", "SRY-box transcription factor 6")
    assert imported_gene_record("NCBIGene:999999999") is None
    assert imported_gene_record("HGNC:21735") is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("uid", "55553"),
        ("status", "discontinued"),
        ("currentid", "55553"),
        ("name", ""),
        ("nomenclaturesymbol", "OTHER"),
        ("nomenclaturestatus", "Unofficial"),
        ("organism", {"taxid": 0, "scientificname": "Homo sapiens"}),
    ],
)
def test_conflicting_or_incomplete_authority_aborts(field, value):
    """Incomplete, superseded, or identity-inconsistent records cannot authorize typing."""
    from kg_microbe.utils.imported_gene_authority import load_imported_gene_records

    payload = json.loads(MAPPING.read_text())
    payload["records"]["NCBIGene:26468"]["native_record"][field] = value
    with pytest.raises(ValueError, match="gene authority"):
        load_imported_gene_records(StringIO(json.dumps(payload)))


def test_snapshot_lookup_requires_validated_records_and_exact_record_url():
    """Producer snapshot lookup preserves the same finite identity contract."""
    from kg_microbe.utils.imported_gene_authority import imported_gene_record, load_imported_gene_records

    payload = json.loads(MAPPING.read_text())
    records = load_imported_gene_records(StringIO(json.dumps(payload)))
    assert imported_gene_record("NCBIGene:26468", records=records).name == "LHX6"
    bad = copy.deepcopy(payload)
    bad["records"]["NCBIGene:26468"]["record_url"] = "https://www.ncbi.nlm.nih.gov/gene/55553"
    with pytest.raises(ValueError, match="gene authority"):
        load_imported_gene_records(StringIO(json.dumps(bad)))


def test_source_identity_is_required():
    """Curation without its pinned original content identity is invalid."""
    from kg_microbe.utils.imported_gene_authority import load_imported_gene_records

    payload = json.loads(MAPPING.read_text())
    payload["source_sha256"] = "unverified"
    with pytest.raises(ValueError, match="gene authority"):
        load_imported_gene_records(StringIO(json.dumps(payload)))


@pytest.mark.parametrize("change", ["taxon", "official_symbol", "official_name"])
def test_plausible_changed_record_is_bound_to_actual_native_bytes(change):
    """A valid-looking record cannot borrow the unchanged digest of different facts."""
    from kg_microbe.utils.imported_gene_authority import load_imported_gene_records

    payload = json.loads(MAPPING.read_text())
    record = payload["records"]["NCBIGene:26468"]["native_record"]
    if change == "taxon":
        record["organism"] = {"taxid": 10090, "scientificname": "Mus musculus", "commonname": "mouse"}
    elif change == "official_symbol":
        record["name"] = record["nomenclaturesymbol"] = "WRONG"
    else:
        record["description"] = record["nomenclaturename"] = "Plausible but unsupported name"
    with pytest.raises(ValueError, match="gene authority"):
        load_imported_gene_records(StringIO(json.dumps(payload)))


def test_changed_native_bytes_cannot_reuse_previous_curated_source_identity():
    """Even a parse-equivalent native response must retain its exact evidence hash."""
    from kg_microbe.utils.imported_gene_authority import GENE_NATIVE_EVIDENCE_FILE, load_imported_gene_records

    with MAPPING.open() as curated:
        with pytest.raises(ValueError, match="native evidence digest"):
            load_imported_gene_records(curated, native_stream=StringIO(GENE_NATIVE_EVIDENCE_FILE.read_text() + "\n"))
