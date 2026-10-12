"""Keep native-transform progress descriptions consistent with temporal-category deferral."""

import csv

from kg_microbe.transform_utils.ontologies.ontologies_transform import OntologiesTransform


def test_uberon_log_does_not_claim_temporal_ids_are_anatomy(tmp_path, capsys):
    """The real category pass distinguishes known temporal IDs and reports that boundary accurately."""
    nodes = tmp_path / "uberon_nodes.tsv"
    nodes.write_text(
        "id\tcategory\tname\n"
        "UBERON:0000104\tbiolink:OntologyClass\tlife cycle\n"
        "UBERON:0000955\tbiolink:OntologyClass\tbrain\n"
    )
    transform = OntologiesTransform.__new__(OntologiesTransform)
    transform._fix_node_categories(nodes, "uberon")
    text = capsys.readouterr().out
    assert "all terms" not in text
    assert "reviewed temporal categories deferred to source finalization" in text
    with nodes.open() as stream:
        rows = {row["id"]: row["category"] for row in csv.DictReader(stream, delimiter="\t")}
    assert rows == {"UBERON:0000104": "biolink:OntologyClass", "UBERON:0000955": "biolink:AnatomicalEntity"}
    assert "Ensure all terms are AnatomicalEntity" not in OntologiesTransform._fix_node_categories.__doc__
