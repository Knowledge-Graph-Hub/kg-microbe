"""Native GTDB assembly assignments are taxonomic membership, not subsumption."""

import csv
from pathlib import Path

import pytest

from kg_microbe.transform_utils.gtdb.gtdb import GTDBTransform

FIXTURE = Path(__file__).parent / "resources" / "gtdb_genome_taxon_semantics"
EXPECTED_ASSIGNMENTS = {
    "ncbi.assembly:GCA_950287535.1": "GTDB:s__Escherichia_coli",
    "ncbi.assembly:GCF_000005845.2": "GTDB:s__G047199095_sp047199095",
    "ncbi.assembly:GCF_964307495.1": "GTDB:s__Methanocatella_smithii",
    "ncbi.assembly:GCA_048462655.1": "GTDB:s__Methanocatella_smithii",
}


@pytest.mark.parametrize("with_metadata", [True, False], ids=["metadata", "taxonomy-only"])
def test_native_assembly_assignments_preserve_identity_and_taxon_crosswalks(tmp_path, with_metadata):
    """Both ingestion paths retain each assembly, its assignment and distinct taxon semantics."""
    transform = GTDBTransform(input_dir=tmp_path / "raw", output_dir=tmp_path / "out")
    transform.input_dir = FIXTURE
    # A frozen empty retirement map keeps this regression independent of taxdump.
    transform._taxid_merges = {}
    taxa = transform._parse_taxonomy_file("taxonomy.tsv")
    transform._build_taxonomy_hierarchy(taxa)
    original_hierarchy = [dict(row) for row in transform.edges]
    if with_metadata:
        transform._parse_metadata_file("metadata.tsv", taxa)
    else:
        transform._create_genomes_from_taxonomy(taxa)
    transform._emit_ncbi_mapping_edges()
    transform._write_tsv_files()

    with transform.output_node_file.open() as stream:
        nodes = {row["id"]: row for row in csv.DictReader(stream, delimiter="\t")}
    with transform.output_edge_file.open() as stream:
        edges = list(csv.DictReader(stream, delimiter="\t"))

    assignments = [row for row in edges if row["subject"].startswith("ncbi.assembly:")]
    assert len(assignments) == 4
    assert {row["subject"]: row["object"] for row in assignments} == EXPECTED_ASSIGNMENTS
    for edge in assignments:
        assert (edge["predicate"], edge["relation"]) == ("biolink:in_taxon", "RO:0002162")
        assert edge["primary_knowledge_source"] == "infores:gtdb"
        assert (edge["knowledge_level"], edge["agent_type"]) == ("knowledge_assertion", "not_provided")
        assert nodes[edge["subject"]]["category"] == "biolink:Genome"
        assert nodes[edge["object"]]["category"] == "biolink:OrganismTaxon"

    # Taxon-class subsumption and taxon-to-taxon mappings remain separate relations.
    hierarchy = [row for row in edges if row["predicate"] == "biolink:subclass_of"]
    assert len(hierarchy) == len(original_hierarchy) > 0
    assert all({key: row[key] for key in old} == old for row, old in zip(hierarchy, original_hierarchy, strict=True))
    assert all(
        nodes[row[side]]["category"] == "biolink:OrganismTaxon" for row in hierarchy for side in ("subject", "object")
    )
    crosswalks = [row for row in edges if row["object"].startswith("NCBITaxon:")]
    expected_crosswalks = {
        ("GTDB:s__G047199095_sp047199095", "NCBITaxon:511145"),
        ("GTDB:s__Escherichia_coli", "NCBITaxon:624"),
        ("GTDB:s__Methanocatella_smithii", "NCBITaxon:2173"),
    }
    assert {(row["subject"], row["object"]) for row in crosswalks} == (expected_crosswalks if with_metadata else set())
    assert len(crosswalks) == (3 if with_metadata else 0)
    assert all((row["predicate"], row["relation"]) == ("biolink:close_match", "skos:closeMatch") for row in crosswalks)
    assert all((row["knowledge_level"], row["agent_type"]) == ("prediction", "automated_agent") for row in crosswalks)

    genomes = {key: row for key, row in nodes.items() if row["category"] == "biolink:Genome"}
    assert set(genomes) == set(EXPECTED_ASSIGNMENTS)
    for identifier, genome in genomes.items():
        accession = identifier.removeprefix("ncbi.assembly:")
        assert genome["name"] == accession
        archive = "RefSeq" if accession.startswith("GCF_") else "GenBank"
        assert genome["description"] == f"{archive} assembly {accession}"
        expected_pair = identifier.replace("GCF_", "GCA_") if archive == "RefSeq" and with_metadata else ""
        assert genome["same_as"] == expected_pair
        assert genome["provided_by"] == "infores:gtdb"
