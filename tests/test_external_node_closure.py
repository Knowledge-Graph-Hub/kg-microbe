"""External endpoint closure requires exact local proof and preserves source evidence."""

import csv
import gzip
import io
import json
import sqlite3
import tarfile

import pytest

from kg_microbe.merge_utils.external_node_closure import resolve_external_references
from kg_microbe.transform_utils.metatraits_gtdb.metatraits_gtdb import MetaTraitsGTDBTransform
from kg_microbe.utils.external_identifiers import load_assembly_aliases, load_taxid_merges


def _tsv(path, fields, rows):
    """Create a small explicitly supplied TSV fixture."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _read(path):
    """Read a bounded fixture output."""
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def _taxdump(raw_dir, merged="10\t|\t11\t|\n11\t|\t12\t|\n", nodes=None):
    """Supply a minimal exact retirement chain and both permitted/excluded lineages."""
    with tarfile.open(raw_dir / "taxdump.tar.gz", "w:gz") as archive:
        members = {
            "merged.dmp": merged,
            "nodes.dmp": nodes
            if nodes is not None
            else (
                "1\t|\t1\t|\tno rank\t|\n2\t|\t1\t|\tsuperkingdom\t|\n12\t|\t2\t|\tspecies\t|\n"
                "13\t|\t2\t|\tsubspecies\t|\n20\t|\t1\t|\tspecies\t|\n"
            ),
            "names.dmp": (
                "12\t|\tAccepted bacterium\t|\t\t|\tscientific name\t|\n"
                "13\t|\tNamed subspecies\t|\t\t|\tscientific name\t|\n"
                "20\t|\tExcluded eukaryote\t|\t\t|\tscientific name\t|\n"
            ),
        }
        for name, value in members.items():
            data = value.encode()
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))


def _graph(tmp_path, anonymous):
    """Supply anonymous targets, a shared source, and two retired references that converge."""
    nodes, edges = tmp_path / "nodes.tsv", tmp_path / "edges.tsv"
    node_rows = [{"id": value, "category": "biolink:NamedThing", "name": "", "provided_by": ""} for value in anonymous]
    node_rows.append(
        {"id": "source:1", "name": "Source", "category": "biolink:OrganismTaxon", "provided_by": "infores:source"}
    )
    _tsv(nodes, ["id", "category", "name", "provided_by"], node_rows)
    edge_rows = [
        {
            "subject": "source:1",
            "predicate": "biolink:close_match",
            "object": value,
            "relation": "skos:closeMatch",
            "primary_knowledge_source": "infores:source",
        }
        for value in anonymous
    ]
    _tsv(edges, ["subject", "predicate", "object", "relation", "primary_knowledge_source"], edge_rows)
    return nodes, edges


def test_taxid_retirement_preserves_distinct_original_evidence(tmp_path):
    """Convergent identities do not pool assertions or erase their original identifiers."""
    _taxdump(tmp_path)
    nodes, edges = _graph(tmp_path, ["NCBITaxon:10", "NCBITaxon:11", "NCBITaxon:13", "NCBITaxon:20"])
    report = tmp_path / "resolution.tsv"
    counts = resolve_external_references(nodes, edges, tmp_path, report)
    assert counts == {"retired_id_replaced": 2, "authority_declaration": 1, "excluded_outside_prokaryote_trim": 1}
    actual = {row["id"]: row for row in _read(nodes)}
    assert set(actual) == {"source:1", "NCBITaxon:12", "NCBITaxon:13"}
    assert actual["NCBITaxon:12"]["name"] == "Accepted bacterium"
    assertions = _read(edges)
    assert len(assertions) == 3
    assert {row["original_object"] for row in assertions if row["object"] == "NCBITaxon:12"} == {
        "NCBITaxon:10",
        "NCBITaxon:11",
    }
    assert all(row["primary_knowledge_source"] == "infores:source" for row in assertions)
    evidence = _read(report)
    assert len(evidence) == 4
    assert all(len(row["authority_sha256"]) == 64 for row in evidence)
    assert "NCBITaxon:20" in evidence[-1]["original_edge_json"]


def test_obsolete_without_replacement_is_reported_not_reinvented(tmp_path):
    """Honor ontology exclusion policy, follow unique IAO replacements, preserve current labels."""
    with sqlite3.connect(tmp_path / "go.db") as connection:
        connection.execute("CREATE TABLE statements(subject,predicate,object,value)")
        connection.executemany(
            "INSERT INTO statements VALUES(?,?,?,?)",
            [
                ("GO:1", "owl:deprecated", None, "true"),
                ("GO:1", "rdfs:label", None, "obsolete old activity"),
                ("GO:2", "owl:deprecated", None, "true"),
                ("GO:2", "IAO:0100001", "GO:3", None),
                ("GO:3", "rdfs:label", None, "Current activity"),
                ("GO:3", "oboInOwl:hasOBONamespace", None, "molecular_function"),
            ],
        )
    nodes, edges = _graph(tmp_path, ["GO:1", "GO:2"])
    report = tmp_path / "resolution.tsv"
    counts = resolve_external_references(nodes, edges, tmp_path, report)
    assert counts["excluded_obsolete_without_unique_replacement"] == 1
    assert _read(edges)[0]["original_object"] == "GO:2"
    assert _read(edges)[0]["object"] == "GO:3"
    assert {row["id"] for row in _read(nodes)} == {"source:1", "GO:3"}
    assert any(row["original_id"] == "GO:1" and row["original_edge_json"] for row in _read(report))


def test_missing_authority_is_explicit_and_non_destructive(tmp_path):
    """A missing local database does not justify inventing a label or silently dropping data."""
    nodes, edges = _graph(tmp_path, ["GO:1"])
    report = tmp_path / "resolution.tsv"
    counts = resolve_external_references(nodes, edges, tmp_path, report)
    assert counts == {"unresolved_no_exact_local_authority": 1}
    assert _read(edges)[0]["object"] == "GO:1"
    assert _read(report)[0]["authority"] == ""


def test_corrupt_authority_aborts_before_graph_writes(tmp_path):
    """Invalid evidence cannot produce a superficially successful graph or clobber old outputs."""
    _taxdump(tmp_path, "10\t|\t11\t|\n11\t|\t10\t|\n")
    nodes, edges = _graph(tmp_path, ["NCBITaxon:10"])
    before = nodes.read_bytes(), edges.read_bytes()
    with pytest.raises(ValueError, match="Cyclic"):
        resolve_external_references(nodes, edges, tmp_path, tmp_path / "report.tsv")
    assert (nodes.read_bytes(), edges.read_bytes()) == before


@pytest.mark.parametrize("parent", [0, 11, 999])
def test_incomplete_lineage_does_not_prove_exclusion(tmp_path, parent):
    """Absent parent declarations must abort, not erase a taxon and its evidence."""
    _taxdump(tmp_path, nodes=f"1 | 1 | no rank |\n2 | 1 | superkingdom |\n12 | {parent} | species |\n")
    nodes, edges = _graph(tmp_path, ["NCBITaxon:12"])
    report = tmp_path / "report.tsv"
    report.write_text("previous complete report\n")
    before = nodes.read_bytes(), edges.read_bytes(), report.read_bytes()
    with pytest.raises(ValueError, match="incomplete NCBI lineage"):
        resolve_external_references(nodes, edges, tmp_path, report)
    assert (nodes.read_bytes(), edges.read_bytes(), report.read_bytes()) == before


def test_missing_prokaryote_root_is_not_assumed_present(tmp_path):
    """Reaching numeric taxid 2 is insufficient when that authority node is absent."""
    _taxdump(tmp_path, nodes="1 | 1 | no rank |\n12 | 2 | species |\n")
    nodes, edges = _graph(tmp_path, ["NCBITaxon:12"])
    with pytest.raises(ValueError, match="missing node 2"):
        resolve_external_references(nodes, edges, tmp_path, tmp_path / "report.tsv")


def test_assembly_alias_requires_explicit_versioned_same_as(tmp_path):
    """A same numeric base or changed version never establishes identity."""
    path = tmp_path / "nodes.tsv"
    _tsv(
        path,
        ["id", "same_as"],
        [
            {"id": "ncbi.assembly:GCF_1.2", "same_as": "ncbi.assembly:GCA_1.2"},
            {"id": "ncbi.assembly:GCA_2.1", "same_as": ""},
        ],
    )
    declared, aliases = load_assembly_aliases(path)
    assert aliases == {"ncbi.assembly:GCA_1.2": "ncbi.assembly:GCF_1.2"}
    assert "ncbi.assembly:GCA_1.1" not in aliases
    assert "ncbi.assembly:GCF_2.1" not in aliases
    assert len(declared) == 2


def test_taxid_merge_conflicts_fail(tmp_path):
    """Contradictory authority rows must not silently become last-row-wins identity."""
    _taxdump(tmp_path, "10\t|\t11\t|\n10\t|\t12\t|\n")
    with pytest.raises(ValueError, match="conflicting"):
        load_taxid_merges(tmp_path)


def test_anonymous_canonical_is_emitted_only_once(tmp_path):
    """Two retired IDs plus an existing anonymous canonical row produce one declaration."""
    _taxdump(tmp_path)
    nodes, edges = _graph(tmp_path, ["NCBITaxon:10", "NCBITaxon:11", "NCBITaxon:12"])
    resolve_external_references(nodes, edges, tmp_path, tmp_path / "report.tsv")
    actual = _read(nodes)
    assert sum(row["id"] == "NCBITaxon:12" for row in actual) == 1
    assert {row["provided_by"] for row in actual if row["id"] == "NCBITaxon:12"} == {"infores:ncbitaxon"}


@pytest.mark.parametrize("canonical_first", [True, False])
def test_convergence_preserves_existing_node_and_donor_metadata(tmp_path, canonical_first):
    """Canonical typing stays authoritative while donor attribution and exact fields survive."""
    _taxdump(tmp_path)
    nodes, edges = _graph(tmp_path, ["NCBITaxon:10", "NCBITaxon:11"])
    fields = ["id", "category", "name", "provided_by", "description", "deprecated", "xref"]
    originals = _read(nodes)
    for index, row in enumerate(originals[:2]):
        row.update(
            provided_by=f"infores:donor{index}|infores:shared",
            description=f"Donor {index} context | verbatim",
            deprecated="true",
            xref=f"record:{index}",
        )
    canonical = {
        "id": "NCBITaxon:12",
        "name": "Canonical authoritative label",
        "category": "biolink:OrganismTaxon",
        "provided_by": "infores:existing",
        "description": "Canonical description.",
        "deprecated": "false",
        "xref": "record:canonical",
    }
    rows = [canonical, *originals] if canonical_first else [*originals, canonical]
    _tsv(nodes, fields, rows)
    donor_rows = {row["id"]: row for row in _read(nodes) if row["id"] in {"NCBITaxon:10", "NCBITaxon:11"}}
    report = tmp_path / "report.tsv"
    resolve_external_references(nodes, edges, tmp_path, report)
    actual = {row["id"]: row for row in _read(nodes)}["NCBITaxon:12"]
    assert actual["name"] == canonical["name"]
    assert actual["category"] == canonical["category"]
    assert actual["deprecated"] == "false"
    assert actual["xref"] == "record:canonical"
    assert set(actual["provided_by"].split("|")) == {
        "infores:existing",
        "infores:donor0",
        "infores:donor1",
        "infores:shared",
        "infores:ncbitaxon",
    }
    assert all(
        description in actual["description"]
        for description in [canonical["description"], *[row["description"] for row in donor_rows.values()]]
    )
    for row in _read(report):
        assert json.loads(row["original_node_json"]) == donor_rows[row["original_id"]]


def test_new_declaration_does_not_inherit_retired_scalar_metadata(tmp_path):
    """A replacement is current; obsolete donor flags remain in the lossless sidecar only."""
    _taxdump(tmp_path)
    nodes, edges = _graph(tmp_path, ["NCBITaxon:10", "NCBITaxon:11"])
    rows = _read(nodes)
    for index, row in enumerate(rows[:2]):
        row.update(
            provided_by=f"infores:donor{index}",
            description=f"Donor {index} description.",
            deprecated="true",
            xref=f"record:{index}",
        )
    _tsv(nodes, ["id", "category", "name", "provided_by", "description", "deprecated", "xref"], rows)
    # An edgeless donor must have its original metadata recorded as well.
    _tsv(edges, list(_read(edges)[0]), _read(edges)[:1])
    report = tmp_path / "report.tsv"
    resolve_external_references(nodes, edges, tmp_path, report)
    actual = {row["id"]: row for row in _read(nodes)}["NCBITaxon:12"]
    assert actual["name"] == "Accepted bacterium"
    assert actual["category"] == "biolink:OrganismTaxon"
    assert actual["deprecated"] == actual["xref"] == ""
    assert set(actual["provided_by"].split("|")) == {"infores:donor0", "infores:donor1", "infores:ncbitaxon"}
    assert all(row["description"] in actual["description"] for row in rows[:2])
    evidence = {row["original_id"]: row for row in _read(report)}
    assert evidence["NCBITaxon:11"]["original_edge_json"] == ""
    assert json.loads(evidence["NCBITaxon:11"]["original_node_json"])["xref"] == "record:1"


def test_no_targets_clears_stale_report_without_authority_scan(tmp_path, monkeypatch):
    """An empty disposition is still a fresh artifact, not a stale prior report."""
    nodes, edges = _graph(tmp_path, [])
    report = tmp_path / "report.tsv"
    report.write_text("stale previous report")
    monkeypatch.setattr("kg_microbe.merge_utils.external_node_closure._digest", lambda _: pytest.fail("No raw scans"))
    assert resolve_external_references(nodes, edges, tmp_path, report) == {}
    assert _read(report) == []
    assert report.read_text().startswith("original_id\tcanonical_id")


def test_go_cellular_component_not_misclassified_as_process(tmp_path):
    """Only explicit aspect evidence selects a specialized GO category."""
    with sqlite3.connect(tmp_path / "go.db") as connection:
        connection.execute("CREATE TABLE statements(subject,predicate,object,value)")
        connection.executemany(
            "INSERT INTO statements VALUES(?,?,?,?)",
            [
                ("GO:1", "rdfs:label", None, "A cellular component"),
                ("GO:1", "oboInOwl:hasOBONamespace", None, "cellular_component"),
                ("GO:2", "rdfs:label", None, "No aspect provided"),
            ],
        )
    nodes, edges = _graph(tmp_path, ["GO:1", "GO:2"])
    resolve_external_references(nodes, edges, tmp_path, tmp_path / "report.tsv")
    actual = {row["id"]: row for row in _read(nodes)}
    assert actual["GO:1"]["category"] == "biolink:CellularComponent"
    assert actual["GO:2"]["category"] == "biolink:OntologyClass"


def test_chebi_uses_asserted_ancestry_of_canonical_replacements(tmp_path):
    """Recovered role/macromolecule classes use the shared policy, never has-role links."""
    with sqlite3.connect(tmp_path / "chebi.db") as connection:
        connection.execute("CREATE TABLE statements(subject,predicate,object,value)")
        connection.executemany(
            "INSERT INTO statements VALUES(?,?,?,?)",
            [
                ("CHEBI:50906", "rdfs:label", None, "role"),
                ("CHEBI:33839", "rdfs:label", None, "macromolecule"),
                ("CHEBI:1", "owl:deprecated", None, "true"),
                ("CHEBI:1", "IAO:0100001", "CHEBI:2", None),
                ("CHEBI:2", "rdfs:label", None, "Canonical chemical role"),
                ("CHEBI:2", "rdfs:subClassOf", "CHEBI:3", None),
                ("CHEBI:3", "rdfs:subClassOf", "CHEBI:50906", None),
                ("CHEBI:4", "rdfs:label", None, "A macromolecule"),
                ("CHEBI:4", "rdfs:subClassOf", "CHEBI:33839", None),
                ("CHEBI:5", "rdfs:label", None, "A chemical with a role"),
                ("CHEBI:5", "RO:0000087", "CHEBI:50906", None),
            ],
        )
    nodes, edges = _graph(tmp_path, ["CHEBI:50906", "CHEBI:33839", "CHEBI:1", "CHEBI:4", "CHEBI:5"])
    resolve_external_references(nodes, edges, tmp_path, tmp_path / "report.tsv")
    actual = {row["id"]: row["category"] for row in _read(nodes)}
    assert actual["CHEBI:50906"] == actual["CHEBI:2"] == "biolink:ChemicalRole"
    assert actual["CHEBI:33839"] == actual["CHEBI:4"] == "biolink:MacromolecularComplex"
    assert actual["CHEBI:5"] == "biolink:ChemicalEntity"
    assert "CHEBI:1" not in actual


def test_micro_does_not_prefix_default_to_procedure(tmp_path):
    """A labeled MICRO chemical is not an assay solely because its prefix matches."""
    (tmp_path / "micro.owl").write_text("<not-valid-xml>")
    nodes, edges = _graph(tmp_path, ["MICRO:9999999"])
    counts = resolve_external_references(nodes, edges, tmp_path, tmp_path / "report.tsv")
    assert counts == {"unresolved_no_exact_local_authority": 1}
    assert _read(nodes)[0]["category"] == "biolink:NamedThing"


def test_metatraits_gtdb_retirements_precede_majority_counts(tmp_path, monkeypatch):
    """Two obsolete IDs must count for their shared accepted taxon before majority selection."""
    from collections import Counter, defaultdict

    _taxdump(tmp_path)
    gtdb = tmp_path / "gtdb"
    gtdb.mkdir()
    with gzip.open(gtdb / "bac120_metadata.tsv.gz", "wt") as output:
        output.write("accession\tgtdb_taxonomy\tncbi_taxid\n")
        for accession, taxid in (("GCA_1.1", "10"), ("GCA_2.1", "11"), ("GCA_3.1", "13")):
            output.write(f"{accession}\td__Bacteria;p__P;c__C;o__O;f__F;g__G;s__S\t{taxid}\n")
    monkeypatch.setattr("kg_microbe.transform_utils.metatraits_gtdb.metatraits_gtdb.RAW_DATA_DIR", tmp_path)
    transform = object.__new__(MetaTraitsGTDBTransform)
    transform.gtdb_to_ncbi = defaultdict(Counter)
    transform.accession_to_ncbi = {}
    transform._load_gtdb_to_ncbi_mapping()
    assert transform.gtdb_to_ncbi["S"] == Counter({"NCBITaxon:12": 2, "NCBITaxon:13": 1})
    assert transform._pick_ncbi_id(transform.gtdb_to_ncbi["S"]) == "NCBITaxon:12"
