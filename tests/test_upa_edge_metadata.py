"""UPA GO cross-references added after initialization retain metadata (#1071)."""

import csv

import pandas as pd

from kg_microbe.transform_utils.ontologies.ontologies_transform import OntologiesTransform


def test_late_added_curated_xrefs_have_metadata_and_keep_other_edges(tmp_path):
    """UPA xrefs are source assertions; pre-existing entailment metadata must survive."""
    transform = OntologiesTransform.__new__(OntologiesTransform)
    existing = pd.DataFrame(
        [
            {
                "subject": "RHEA:19032",
                "predicate": "biolink:part_of",
                "object": "UPA:UPA00150",
                "relation": "BFO:0000050",
                "primary_knowledge_source": "infores:upa",
                "knowledge_level": "logical_entailment",
                "agent_type": "automated_agent",
            }
        ]
    )
    added = transform._make_upa_go_xref_edges(
        {
            "UPA:UPA00150": "GO:0000025",
            "UPA:UCR00014": "GO:0004739",  # reaction, not pathway
            "UPA:UPA00001": "EC:1.1.1.1",  # not GO
        }
    )
    assert len(added) == 1
    row = added.iloc[0].to_dict()
    assert row["subject"] == "GO:0000025"
    assert row["object"] == "UPA:UPA00150"
    assert row["predicate"] == "biolink:related_to"
    assert row["primary_knowledge_source"] == "infores:upa"
    assert row["knowledge_level"] == "knowledge_assertion"
    assert row["agent_type"] == "manual_agent"
    output = tmp_path / "upa_edges.tsv"
    pd.concat([existing, added], ignore_index=True).to_csv(output, sep="\t", index=False)
    transform._add_kgx_metadata_to_edges(output)
    with output.open() as stream:
        rows = list(csv.DictReader(stream, delimiter="\t"))
    assert rows[0] == existing.iloc[0].to_dict()
    assert rows[1] == row


def test_no_go_pathway_xrefs_produces_header_only_frame():
    """An empty selection still has both metadata columns, never spurious rows."""
    transform = OntologiesTransform.__new__(OntologiesTransform)
    added = transform._make_upa_go_xref_edges({"UPA:UCR00014": "GO:0004739"})
    assert added.empty
    assert {"knowledge_level", "agent_type"} <= set(added.columns)
