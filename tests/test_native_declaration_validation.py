"""Merge proof-consumer boundary; GOLD's native-proof production is tested separately."""

import csv
from types import SimpleNamespace

import pytest

from kg_microbe.utils.source_finalization import SourceFinalizationRequired, validate_graph_bundle


def _pair(tmp_path, *, identifier="gold:Go0531699", xref="NCBITaxon:562"):
    row = {
        "id": identifier,
        "category": "biolink:NamedThing",
        "name": "",
        "provided_by": "infores:gold",
        "xref": xref,
    }
    nodes, edges = tmp_path / "nodes.tsv", tmp_path / "edges.tsv"
    with nodes.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(row), delimiter="\t")
        writer.writeheader()
        writer.writerow(row)
        writer.writerow({"id": "NCBITaxon:562", "category": "biolink:OrganismTaxon", "name": "Escherichia coli"})
    edges.write_text(
        "subject\tpredicate\tobject\trelation\n"
        f"{identifier}\tbiolink:related_to\tNCBITaxon:562\tgold:organism_v2.ncbi_taxonomy_id\n"
    )
    return nodes, edges, row


def _provider(expected, *, mutate=False):
    """Create a protocol double, not an implementation of GOLD's native evidence validator."""
    verifications = []
    state = {"unchanged": True}

    def verify(*, metadata_only):
        """Model a native declaration proof that fails once its evidence changes."""
        assert metadata_only
        verifications.append(True)
        if not state["unchanged"]:
            raise SourceFinalizationRequired("Native declaration proof changed")

    def declaration_for(identifier):
        """Return only the selected declaration and optionally invalidate its proof."""
        if identifier != expected["id"]:
            return None
        if mutate:
            state["unchanged"] = False
        return SimpleNamespace(matches=lambda row, *, merged: merged and row == expected)

    return SimpleNamespace(verify=verify, declaration_for=declaration_for), verifications


def test_nameless_gold_source_referent_requires_proof_not_id_exception(tmp_path):
    """The real exceptional ID remains rejected without an admitted native declaration."""
    nodes, edges, _ = _pair(tmp_path)
    with pytest.raises(SourceFinalizationRequired, match="unresolved authoritative endpoint"):
        validate_graph_bundle([nodes], [edges], require_closure=True)


def test_exact_proof_is_checked_before_and_after_read_only_validation(tmp_path):
    """A matched native row is counted explicitly without changing either graph file."""
    nodes, edges, row = _pair(tmp_path)
    provider, checks = _provider(row)
    before = nodes.read_bytes(), edges.read_bytes()
    assert validate_graph_bundle([nodes], [edges], require_closure=True, native_declarations=provider) == {
        "nodes": 2,
        "edges": 1,
        "audited_native_nameless_nodes": 1,
    }
    assert checks == [True, True]
    assert (nodes.read_bytes(), edges.read_bytes()) == before


@pytest.mark.parametrize("field,value", [("xref", "NCBITaxon:1"), ("provided_by", "Graph"), ("category", "")])
def test_same_id_does_not_admit_changed_native_fields(tmp_path, field, value):
    """Identifier equality alone cannot satisfy the proof-consumer contract."""
    nodes, edges, row = _pair(tmp_path)
    provider, _ = _provider({**row, field: value})
    with pytest.raises(SourceFinalizationRequired, match="unresolved authoritative endpoint"):
        validate_graph_bundle([nodes], [edges], require_closure=True, native_declarations=provider)


def test_proof_lookup_mutation_is_rejected_at_terminal_check(tmp_path):
    """A proof valid before graph iteration cannot silently change during lookup."""
    nodes, edges, row = _pair(tmp_path)
    provider, _ = _provider(row, mutate=True)
    with pytest.raises(SourceFinalizationRequired, match="proof changed"):
        validate_graph_bundle([nodes], [edges], require_closure=True, native_declarations=provider)


def test_unrelated_nameless_gold_id_is_not_covered(tmp_path):
    """An admitted source referent does not create a prefix-wide exception."""
    nodes, edges, row = _pair(tmp_path, identifier="gold:Go0000000")
    provider, _ = _provider({**row, "id": "gold:Go0531699"})
    with pytest.raises(SourceFinalizationRequired, match="unresolved authoritative endpoint"):
        validate_graph_bundle([nodes], [edges], require_closure=True, native_declarations=provider)
