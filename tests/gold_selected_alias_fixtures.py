"""Stage genuine finite native GOLD/selected-NCBI excerpts for the alias contract."""

import csv
import io
import json
import tarfile
from contextlib import ExitStack
from pathlib import Path

from kg_microbe.transform_utils.gold import selected_taxon_aliases as aliases
from kg_microbe.transform_utils.transform import Transform

FIXTURE = Path(__file__).parent / "resources/gold_selected_taxon_aliases/native_evidence.json"


def write_rows(path, rows, header):
    """Preserve original native column values in an isolated fixture member."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=header, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_taxdump(path, literal, *, member="merged.dmp", duplicate=False):
    """Create a tiny archive containing unchanged relevant native lines."""
    with tarfile.open(path, "w:gz") as archive:
        for _ in range(2 if duplicate else 1):
            info = tarfile.TarInfo(member)
            info.size = len(literal.encode())
            archive.addfile(info, io.BytesIO(literal.encode()))


def stage(tmp_path, *, empty=False):
    """Return a real Transform and actual immutable native fixture files."""
    evidence = json.loads(FIXTURE.read_text())
    raw, output = tmp_path / "raw", tmp_path / "transformed"
    transform = Transform("gold", raw, output)
    nodes = evidence["native_taxon_nodes"] + evidence["native_records"]
    edges = evidence["native_incident_rows"]
    write_rows(raw / "gold/GOLD_nodes.tsv", [] if empty else nodes, list(nodes[0]))
    write_rows(raw / "gold/GOLD_edges.tsv", [] if empty else edges, list(edges[0]))
    if not empty:
        write_rows(
            output / "ontologies/ncbitaxon_nodes.tsv", evidence["projected_nodes"], list(evidence["projected_nodes"][0])
        )
        (raw / "ncbitaxon_removed_subset.json").write_text(
            json.dumps(
                {"graphs": [{"meta": evidence["selected_ontology_metadata"][0], "nodes": evidence["selected_nodes"]}]}
            )
        )
        write_taxdump(raw / "taxdump.tar.gz", "".join(item["literal"] for item in evidence["taxdump_merged_dmp"]))
    return transform, evidence


def prepare(transform, stack):
    """Consume authentic existing roles, then invoke the actual finite producer reader."""
    sources = (
        (aliases.NODES_ROLE, transform.input_base_dir / "gold/GOLD_nodes.tsv"),
        (aliases.EDGES_ROLE, transform.input_base_dir / "gold/GOLD_edges.tsv"),
        (aliases.NCBI_ROLE, transform.output_base_dir / "ontologies/ncbitaxon_nodes.tsv"),
        (aliases.TAXDUMP_ROLE, transform.input_base_dir / "taxdump.tar.gz"),
    )
    paths = [
        Path(stack.enter_context(transform.consume_input(role, path)).name) if path.is_file() else None
        for role, path in sources
    ]
    return aliases.prepare(transform, stack, *paths)


def finish_empty(transform):
    """Complete the authentic inert-fixture lifecycle from actual empty native GOLD inputs."""
    with ExitStack() as stack:
        resolver = prepare(transform, stack)
        resolver.finish(transform.output_dir)
        transform.record_producer_audit(aliases.AUDIT_FILE)
    return resolver


def report(transform, resolver):
    """Construct only the contract fields consumed by this standalone verifier."""
    return {
        "source": "gold",
        "raw_input_directory": str(transform.input_base_dir.resolve()),
        "consumed_inputs": transform.consumed_input_snapshots,
        "producer_native_inputs": {aliases.CONTRACT_KEY: resolver.contract()},
    }
