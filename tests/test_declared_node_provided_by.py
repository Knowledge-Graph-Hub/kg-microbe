"""A source declares every node it writes with its own provided_by, not a blank one (#1601)."""

from collections import defaultdict

import pytest

from kg_microbe.utils import go_authority as go_module
from kg_microbe.utils.unipathways_utils import replace_id_with_xref
from tests.test_assay_reference_repairs import _read_assays, authority, transform  # noqa: F401
from tests.test_unipathways_row_shape import KGX_HEADER, NODE_HEADER


def test_bacdive_assay_and_assay_target_nodes_name_bacdive(authority, transform, monkeypatch):  # noqa: F811
    """BacDive's 503 assay, 44 CHEBI and 10 EC declarations were written with provided_by blank."""
    monkeypatch.setattr(go_module, "load_go_authority", lambda raw_dir: authority)
    transform.assay_kit_mappings = {"loaded": True}
    transform.assay_raw_data = _read_assays()
    transform._prepare_assay_outputs()
    column = transform.node_header.index("provided_by")
    rows = transform.assay_nodes_generated + transform.assay_target_nodes_generated
    assert rows and transform.assay_nodes_generated and transform.assay_target_nodes_generated
    by_prefix = {(row[0].split(":")[0], row[column]) for row in rows}
    # GO declarations carry the GO authority's own provenance, as before.
    assert {provided for prefix, provided in by_prefix if prefix == "GO"} <= {"infores:go"}
    assert {provided for prefix, provided in by_prefix if prefix != "GO"} == {transform.knowledge_source}
    assert {prefix for prefix, _ in by_prefix} >= {"kgmicrobe.assay", "CHEBI", "EC"}


@pytest.mark.parametrize("source_header", [KGX_HEADER, None], ids=["by-name", "positional"])
def test_a_rhea_stub_from_upa_names_the_row_that_declared_it(source_header):
    """The 963 RHEA stubs in upa_nodes.tsv were blank, unlike every other row in that file ("upa.json")."""
    header = KGX_HEADER if source_header else NODE_HEADER
    values = {
        "id": "OBO:UPa_UCR00014",
        "category": "biolink:NamedThing",
        "xref": "RHEA:19032",
        "provided_by": "upa.json",
    }
    line = "\t".join(values.get(column, "") for column in header)
    (stub,), _ = replace_id_with_xref(line, header.index("xref"), 0, 1, defaultdict(list), NODE_HEADER, source_header)
    fields = dict(zip(NODE_HEADER, stub.split("\t"), strict=True))
    assert fields["id"] == "RHEA:19032" and fields["provided_by"] == "upa.json"
