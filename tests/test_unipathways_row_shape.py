"""Every UPA node row must be exactly as wide as the header written above it (#1033)."""

from collections import defaultdict

import pytest

from kg_microbe.utils.unipathways_utils import (
    project_onto_header,
    replace_category_for_unipathways,
    replace_id_with_xref,
)

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
# What KGX actually writes for an ontology: the canonical columns plus the
# obograph/RDF leftovers that _normalize_schema strips later.
KGX_HEADER = NODE_HEADER + ["subsets", "meta", "iri"]


def _row(**values):
    return "\t".join(values.get(column, "") for column in KGX_HEADER)


def test_a_row_wider_than_the_header_is_truncated_not_kept():
    """
    The bug: `parts + [""] * (len(node_header) - len(parts))`.

    With 12 fields and a 9-column header the multiplier is negative, `[""] * -3`
    is `[]`, and all 12 fields survived — so pandas could not read the file the
    transform had just written.
    """
    line = _row(
        id="OBO:UPa_UCR00014",
        category="biolink:NamedThing",
        name="pyruvate + thiamine diphosphate = 2-hydroxyethyl-ThPP + CO(2)",
        provided_by="upa.json",
        iri="http://purl.obolibrary.org/obo/UPa_UCR00014",
    )
    out = replace_category_for_unipathways(line, 0, 1, NODE_HEADER, KGX_HEADER)
    fields = out.split("\t")
    assert len(fields) == len(NODE_HEADER)
    assert fields[0] == "OBO:UPa_UCR00014"
    assert fields[2] == "pyruvate + thiamine diphosphate = 2-hydroxyethyl-ThPP + CO(2)"
    assert fields[5] == "upa.json"
    assert "purl.obolibrary.org" not in out


def test_a_short_row_is_padded():
    """KGX omits trailing empty columns for some rows; those must still be header-width."""
    out = replace_category_for_unipathways(
        "OBO:UPa_UCR00014\tbiolink:NamedThing", 0, 1, NODE_HEADER, ["id", "category"]
    )
    assert len(out.split("\t")) == len(NODE_HEADER)


def test_columns_are_matched_by_name_not_position():
    """A reordered upstream column must not shift a value into the wrong field."""
    reordered = ["category", "id", "iri", "name", "provided_by"]
    line = "\t".join(["biolink:NamedThing", "OBO:UPa_UCR00014", "http://x", "a name", "upa.json"])
    out = replace_category_for_unipathways(line, 1, 0, NODE_HEADER, reordered).split("\t")
    assert out[NODE_HEADER.index("id")] == "OBO:UPa_UCR00014"
    assert out[NODE_HEADER.index("name")] == "a name"
    assert out[NODE_HEADER.index("provided_by")] == "upa.json"
    assert "http://x" not in out


def test_a_rhea_stub_is_header_width_and_carries_its_category():
    """The RHEA half was already well-formed; keep it that way, and key it by name."""
    line = _row(id="OBO:UPa_UCR00014", category="biolink:NamedThing", xref="RHEA:19032|GO:0004739")
    new_lines, mapping = replace_id_with_xref(line, 4, 0, 1, defaultdict(list), NODE_HEADER, KGX_HEADER)
    assert len(new_lines) == 1, "GO xrefs are dropped in favour of the Unipathways prefix"
    fields = new_lines[0].split("\t")
    assert len(fields) == len(NODE_HEADER)
    assert fields[NODE_HEADER.index("id")] == "RHEA:19032"
    assert fields[NODE_HEADER.index("category")] == "biolink:MolecularActivity"
    assert mapping["OBO:UPa_UCR00014"] == ["RHEA:19032"]


def test_a_stub_category_lands_by_name_even_when_the_headers_disagree():
    """category_index indexes the source header; using it on the output row was luck."""
    reordered_node_header = ["id", "name", "category", "description", "xref"]
    line = "\t".join(["OBO:UPa_UCR00014", "biolink:NamedThing", "RHEA:19032"])
    new_lines, _ = replace_id_with_xref(
        line, 2, 0, 1, defaultdict(list), reordered_node_header, ["id", "category", "xref"]
    )
    fields = new_lines[0].split("\t")
    assert fields[reordered_node_header.index("category")] == "biolink:MolecularActivity"
    assert fields[reordered_node_header.index("id")] == "RHEA:19032"


@pytest.mark.parametrize(
    ("parts", "expected"),
    [(["a", "b", "c", "d"], ["a", "b", "c"]), (["a"], ["a", "", ""])],
)
def test_without_a_source_header_it_falls_back_to_pad_or_truncate(parts, expected):
    """Callers that never saw a header still get exactly header-width rows."""
    assert project_onto_header(parts, None, ["x", "y", "z"]) == expected
