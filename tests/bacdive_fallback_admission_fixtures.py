"""Honest native fallback context and a synthetic taxdump container for admission tests."""

import hashlib
import io
import tarfile
from pathlib import Path

from kg_microbe.utils.source_finalization import graph_rows
from tests.bacdive_fallback_fixtures import native_payload, records_by_id

CONTROL_RECORD = "134696"
CONTROL_TAXON = "NCBITaxon:2745"


def write_selected_taxdump(raw_dir):
    """Encode existing literal class evidence; empty retirements are explicit synthetic controls."""
    native, _ = native_payload()
    declarations = native["literal_native_declarations"]
    nodes, names = [], []
    for identifier, statements in sorted(declarations.items()):
        taxid = identifier.removeprefix("NCBITaxon:")
        assert taxid.isdigit()
        parents = {row["object"] for row in statements if row["predicate"] == "rdfs:subClassOf"}
        labels = {row["value"] for row in statements if row["predicate"] == "rdfs:label"}
        ranks = {row["object"] for row in statements if row["predicate"] == "obo:ncbitaxon#has_rank"}
        assert len(labels) == 1
        if identifier == "NCBITaxon:1":
            assert not parents and not ranks
            # Synthetic taxdump encoding of the ontology root, not a claimed
            # literal row from the production NCBI archive.
            parent, rank = identifier, "no rank"
        else:
            assert len(parents) == len(ranks) == 1
            parent = next(iter(parents))
            assert parent in declarations
            rank = next(iter(ranks)).removeprefix("NCBITaxon:").replace("_", " ")
        nodes.append(f"{taxid} | {parent.removeprefix('NCBITaxon:')} | {rank} |\n")
        names.append(f"{taxid} | {next(iter(labels))} | | scientific name |\n")
    members = {
        "nodes.dmp": "".join(nodes),
        "names.dmp": "".join(names),
        "merged.dmp": "",
        "delnodes.dmp": "",
        "fixture_scope.txt": (
            "Synthetic test archive from hash-verified literal ontology excerpts. "
            "No retired/deleted IDs are asserted in this control. "
            "This is not the production NCBI taxdump or a native release snapshot.\n"
        ),
    }
    path = Path(raw_dir) / "taxdump.tar.gz"
    assert not path.exists()
    with tarfile.open(path, "w:gz") as archive:
        for name, content in members.items():
            data = content.encode()
            member = tarfile.TarInfo(name)
            member.size = len(data)
            archive.addfile(member, io.BytesIO(data))
    return path


def with_native_ncbi_control(records):
    """Add the unchanged reviewed Halomonas record through the normal producer input."""
    result = list(records)
    if not any(str(record["General"]["BacDive-ID"]) == CONTROL_RECORD for record in result):
        result.append(records_by_id()[CONTROL_RECORD]["record"])
    return result


def assert_native_ncbi_admission(transform, report):
    """Prove the scientific negative has an honestly consumed authority before its attack."""
    subject = "kgmicrobe.strain:bacdive_" + CONTROL_RECORD
    nodes = {row["id"]: row for row in graph_rows(transform.output_node_file)}
    assert nodes[CONTROL_TAXON]["category"] == "biolink:OrganismTaxon"
    assert nodes[CONTROL_TAXON]["name"] == "Halomonas"
    assert any(
        row["subject"] == subject and row["predicate"] == "biolink:subclass_of" and row["object"] == CONTROL_TAXON
        for row in graph_rows(transform.output_edge_file)
    )
    plans = report["producer_native_inputs"]["taxonomy"]["fallback_native_evidence"]["plans"]
    selected = [plan for plan in plans.values() if plan["native_record"]["record_id"] == CONTROL_RECORD]
    assert len(selected) == 1
    assert selected[0]["native_record"]["record_sha256"] == records_by_id()[CONTROL_RECORD]["canonical_record_sha256"]
    assert [subject, CONTROL_TAXON] in selected[0]["parent_pairs"]
    path = Path(transform.input_base_dir) / "taxdump.tar.gz"
    identity = {"path": str(path.resolve()), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    assert report["consumed_inputs"]["ncbi_taxonomy_authority"] == identity
    assert identity in report["inputs"]
