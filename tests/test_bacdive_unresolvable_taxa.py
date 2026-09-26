"""Every NCBITaxon this transform points at must get a typed node (#895)."""

import csv

from kg_microbe.transform_utils.bacdive.bacdive import BacDiveTransform
from kg_microbe.transform_utils.constants import NCBI_CATEGORY

NODE_HEADER = [
    "id",
    "category",
    "name",
    "description",
    "xref",
    "provided_by",
    "synonym",
    "deprecated",
    "same_as",
]
EDGE_HEADER = ["subject", "predicate", "object", "relation", "primary_knowledge_source"]


def _transform(tmp_path, edges, nodes, extract_labels, adapter_labels=None):
    """Build a BacDiveTransform with only the fields the stub pass touches."""
    t = BacDiveTransform.__new__(BacDiveTransform)
    t.output_edge_file = tmp_path / "edges.tsv"
    t.output_node_file = tmp_path / "nodes.tsv"
    t.knowledge_source = "infores:bacdive"
    t.node_header = list(NODE_HEADER)
    t.ncbitaxon_labels = dict(extract_labels)
    lookup = dict(adapter_labels or {})
    t._get_ncbitaxon_label = lookup.get  # noqa: SLF001
    with t.output_edge_file.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, delimiter="\t")
        writer.writerow(EDGE_HEADER)
        writer.writerows(edges)
    with t.output_node_file.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, delimiter="\t")
        writer.writerow(NODE_HEADER)
        writer.writerows(nodes)
    return t


def _written(t):
    rows = list(csv.DictReader(t.output_node_file.open(encoding="utf-8"), delimiter="\t"))
    return {r["id"]: r for r in rows}


def _edge(subject, obj):
    return [subject, "biolink:subclass_of", obj, "rdfs:subClassOf", "infores:bacdive"]


def test_a_taxon_the_pinned_release_lacks_gets_a_typed_stub(tmp_path):
    """
    Otherwise KGX synthesizes a bare `biolink:NamedThing` with no label.

    That is what #892 saw 1,652 of in the 20240826 build and asked about.
    """
    t = _transform(tmp_path, [_edge("kgmicrobe.strain:X", "NCBITaxon:999")], [], {})
    assert t._emit_stubs_for_unresolvable_taxa() == 1
    node = _written(t)["NCBITaxon:999"]
    assert node["category"] == NCBI_CATEGORY
    assert "absent from the pinned NCBITaxon release" in node["description"]


def test_a_taxon_in_the_pinned_release_gets_no_stub(tmp_path):
    """
    The ontologies transform supplies its node row at merge time.

    Writing our own would duplicate 925,220 nodes and override their real labels.
    """
    t = _transform(
        tmp_path,
        [_edge("kgmicrobe.strain:X", "NCBITaxon:562")],
        [],
        {"NCBITaxon:562": "Escherichia coli"},
    )
    assert t._emit_stubs_for_unresolvable_taxa() == 0
    assert "NCBITaxon:562" not in _written(t)


def test_a_taxon_this_run_already_wrote_gets_no_second_row(tmp_path):
    """
    94 of the 113 unresolvable parents already have a BacDive node row.

    Re-emitting them would replace a real label with a bare CURIE, since
    `drop_duplicates` keeps one row per id.
    """
    t = _transform(
        tmp_path,
        [_edge("kgmicrobe.strain:X", "NCBITaxon:999")],
        [["NCBITaxon:999", NCBI_CATEGORY, "Some taxon", "", "", "infores:bacdive", "", "", ""]],
        {},
    )
    assert t._emit_stubs_for_unresolvable_taxa() == 0
    assert _written(t)["NCBITaxon:999"]["name"] == "Some taxon"


def test_a_recoverable_label_is_used_rather_than_the_bare_curie(tmp_path):
    """`Moorella` is a real genus the pinned release happens not to carry."""
    t = _transform(
        tmp_path,
        [_edge("kgmicrobe.strain:X", "NCBITaxon:216400")],
        [],
        {},
        adapter_labels={"NCBITaxon:216400": "Moorella"},
    )
    assert t._emit_stubs_for_unresolvable_taxa() == 1
    node = _written(t)["NCBITaxon:216400"]
    assert node["name"] == "Moorella"
    assert "label recovered from the ontology adapter" in node["description"]


def test_an_unlabelled_stub_says_it_is_probably_retired(tmp_path):
    """The two cases need different descriptions, or the node misleads."""
    t = _transform(tmp_path, [_edge("kgmicrobe.strain:X", "NCBITaxon:999")], [], {})
    t._emit_stubs_for_unresolvable_taxa()
    node = _written(t)["NCBITaxon:999"]
    assert node["name"] == "NCBITaxon:999"
    assert "retired or merged by NCBI" in node["description"]


def test_taxa_reached_by_any_predicate_are_covered(tmp_path):
    """
    Reading back the edges covers emission paths nobody remembered to hook.

    BacDive writes taxon edges from about ten places; a pass that scanned only
    the main one would leave the rest to KGX.
    """
    edges = [
        ["kgmicrobe.strain:X", "biolink:related_to", "NCBITaxon:998", "rel", "infores:bacdive"],
        _edge("kgmicrobe.strain:Y", "NCBITaxon:999"),
    ]
    t = _transform(tmp_path, edges, [], {})
    assert t._emit_stubs_for_unresolvable_taxa() == 2


def test_no_taxon_edges_writes_nothing(tmp_path):
    """An empty result must not append a header or a blank row."""
    t = _transform(tmp_path, [["a", "biolink:related_to", "CHEBI:1", "rel", "src"]], [], {})
    assert t._emit_stubs_for_unresolvable_taxa() == 0
    assert len(_written(t)) == 0


def test_a_taxon_name_is_never_a_bacdive_description_sentence():
    """
    An unlabelled taxon fell back to BacDive's free-text description (#919).

    That gave 93 nodes a 130-character sentence about one strain for a name --
    worse than being unlabelled, because it passes every "does this node have a
    name" check while being unusable for lookup, display or matching.
    """
    import inspect
    from pathlib import Path

    source = Path(inspect.getsourcefile(BacDiveTransform)).read_text()
    assert "ncbi_label = ncbi_description" not in source


def test_an_unlabelled_taxon_keeps_its_sentence_as_a_description():
    """
    The sentence is real information; it just belongs in the description slot.

    Dropping it would lose what BacDive knows about the organism, so both write
    sites pass it as `description` and fall back to the CURIE for the name.
    """
    import inspect
    from pathlib import Path

    source = Path(inspect.getsourcefile(BacDiveTransform)).read_text()
    assert source.count("description=None if ncbi_label else ncbi_description") == 2
    assert source.count("ncbi_label or ncbitaxon_id") == 2
