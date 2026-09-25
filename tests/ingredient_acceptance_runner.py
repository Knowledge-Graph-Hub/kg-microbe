"""Run immutable producer-to-archive acceptance in a fresh pinned-schema process."""

import argparse
import csv
import hashlib
import inspect
import io
import json
import os
import shutil
import socket
import tarfile
from multiprocessing.pool import ThreadPool
from pathlib import Path

import yaml

RESOURCE = Path(__file__).parent / "resources/ingredient_bundle"
ROOT = RESOURCE.parents[2]


def sha256(path):
    """Hash exact fixture and output bytes without loading graph-scale files."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_records(path, records, is_node):
    """Serialize native excerpt rows using the same canonical TSV contract as producers."""
    from kg_microbe.utils.graph_schema import canonical_header
    from kg_microbe.utils.tsv_io import tsv_dict_writer

    fields = canonical_header({key for row in records for key in row}, is_node)
    with path.open("w", newline="") as stream:
        writer = tsv_dict_writer(stream, fields, quoting=csv.QUOTE_NONE, quotechar=None)
        writer.writeheader()
        writer.writerows(records)


def record_source(transform):
    """Record actual registered code, consumed inputs and finalized graph hashes."""
    from kg_microbe.utils.transform_fingerprint import write_fingerprint

    cls = type(transform)
    write_fingerprint(
        transform.output_dir,
        Path(inspect.getsourcefile(cls)).parent,
        ROOT,
        cls.DATA_INPUTS,
        cls.TRANSFORM_INPUTS,
        input_dir=transform.input_base_dir,
        finalization_inputs=transform.finalization_inputs,
    )


def run(output, synthetic=False, reverse=False):
    """Verify the original claims against archived output, using independent native declarations."""
    from kg_microbe.utils.biolink_model import prepare_kgx

    def deny_network(*args, **kwargs):
        """Reject live-service dependencies in the acceptance subprocess."""
        raise RuntimeError("External network is disabled in ingredient acceptance")

    socket.getaddrinfo = deny_network
    socket.socket.connect = deny_network

    native = RESOURCE / "native"
    origin = json.loads((native / "acceptance-native-origin.json").read_text())
    for name, expected in origin["members"].items():
        assert sha256(native / name) == expected["sha256"], name
    os.environ["KG_MICROBE_BIOLINK_MODEL"] = str(native / "biolink-model.yaml")
    os.environ["KG_MICROBE_BIOLINK_PREDICATE_MAP"] = str(native / "predicate_mapping.yaml")
    prepare_kgx()

    from kgx.cli import cli_utils

    from kg_microbe.merge_utils import source_freshness
    from kg_microbe.merge_utils.merge_kg import load_and_merge
    from kg_microbe.transform_utils.microbedecoder.microbedecoder import MicrobeDecoderTransform
    from kg_microbe.transform_utils.mim_ingredients.mim_ingredients import MIMIngredientsTransform
    from kg_microbe.transform_utils.ontologies.ontologies_transform import OntologiesTransform
    from kg_microbe.utils import transform_fingerprint
    from kg_microbe.utils.chemical_mapping_utils import ChemicalMappingLoader
    from kg_microbe.utils.ingredient_bundle import ReviewedIngredientBundle, build_ingredient_lookup_bundle
    from kg_microbe.utils.ingredient_bundle_contract import canonical_json, safe_member
    from kg_microbe.utils.ingredient_kgx import json_scalar
    from scripts.consolidate_chemical_mappings import ChemicalMappingConsolidator

    cli_utils.Pool = ThreadPool
    # Select the same complete immutable model for provenance and validation.
    # This is the test harness equivalent of local_source_schema, with real 4.4.2 bytes.
    schema_files = tuple(
        (native / name).relative_to(ROOT)
        for name in ("biolink-model.yaml", "attributes.yaml", "predicate_mapping.yaml")
    )
    transform_fingerprint.SCHEMA_FILES = schema_files
    source_freshness.SCHEMA_FILES = schema_files
    output.mkdir(parents=True, exist_ok=False)
    raw = output / "raw"
    raw.mkdir()
    foodon_origin = json.loads((native / "foodon-origin.json").read_text())
    assert sha256(native / "foodon-authority.json") == foodon_origin["fixture_sha256"]
    shutil.copyfile(native / "foodon-authority.json", raw / "foodon.json")
    fixture = "synthetic-shared-cas" if synthetic else "reviewed-cases"
    bundle_origin = json.loads(
        (RESOURCE / ("synthetic-shared-cas-origin.json" if synthetic else "origin.json")).read_text()
    )
    archive = RESOURCE / f"{fixture}-v1.tar.gz"
    assert sha256(archive) == bundle_origin["archive_sha256"]
    bundle_dir = output / "producer-bundle"
    with tarfile.open(archive) as source:
        for member in source.getmembers():
            assert member.isfile()
            path = safe_member(bundle_dir, member.name)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(source.extractfile(member).read())
    bundle = ReviewedIngredientBundle(bundle_dir, manifest_sha256=bundle_origin["bundle_manifest_sha256"])

    native_rows = [row for rows in json.loads((native / "native-nodes.json").read_text()).values() for row in rows]
    # Native scope is an independent input, including generic trait xanthine.
    # Only unresolved reviewed local material declarations come from the bundle.
    consolidator = ChemicalMappingConsolidator()
    for row in list(reversed(native_rows)) if reverse else native_rows:
        consolidator.add_chemical(
            row["id"],
            canonical_name=row["name"],
            synonyms=row.get("synonym", "").split("|"),
            xrefs=row.get("xref", "").split("|"),
            source="pinned_native_excerpt",
            priority=1,
        )
    for row in bundle.mappings():
        if row["object_id"].startswith("kgmicrobe.ingredient:"):
            consolidator.add_chemical(
                row["object_id"], canonical_name=row["object_label"], source="reviewed_local", priority=1
            )
    lookup = output / "lookup"
    receipt = build_ingredient_lookup_bundle(consolidator, bundle, lookup)
    loader = ChemicalMappingLoader.from_ingredient_lookup_bundle(lookup, manifest_sha256=receipt["manifest_sha256"])
    assert bundle.policy_parity()["status"] == "PASS"
    assert all(loader.resolve_ingredient_source(row["subject_id"]) == row["object_id"] for row in bundle.mappings())
    decoder = MicrobeDecoderTransform.__new__(MicrobeDecoderTransform)
    decoder.chemical_loader = loader
    writer = csv.writer(io.StringIO())
    for column in ("BacDive_Metabolite_production", "BacDive_Metabolite_production", "BacDive_Antibiotic_resistance"):
        assert decoder._resolve_chemical_curie("rifamycin", writer, column) == "CHEBI:26580"
    assert decoder._resolve_chemical_curie("rifamycin SV", writer, "BacDive_Antibiotic_resistance") == "CHEBI:29673"
    assert decoder._resolve_chemical_curie("xanthine", writer, "BacDive_Metabolite_utilization") == "CHEBI:15318"
    assert loader.resolve_ingredient_source("MIM:Xanthine") == "CHEBI:17712"

    ontology = OntologiesTransform(raw, output / "transformed")
    for kind, rows in (("nodes", native_rows), ("edges", json.loads((native / "native-edges.json").read_text()))):
        write_records(ontology.output_dir / f"{kind}.tsv", rows, kind == "nodes")
    ontology.finalize(fresh_run=True)
    record_source(ontology)
    selection_dir = raw / "mim_ingredients"
    selection_dir.mkdir()
    selection = {
        "mode": "candidate_only",
        "lookup_directory": str(lookup),
        "lookup_manifest_sha256": receipt["manifest_sha256"],
    }
    (selection_dir / "selection.json").write_bytes(canonical_json(selection) + b"\n")
    transform = MIMIngredientsTransform(raw, output / "transformed")
    projected = transform.run()
    transform.finalize(fresh_run=True)
    record_source(transform)
    config = output / "merge.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "configuration": {"output_directory": str(output / "published")},
                "merged_graph": {
                    "name": "ingredients",
                    "source": {
                        str(index): {
                            "input": {
                                "format": "tsv",
                                "filename": [str(source.output_node_file), str(source.output_edge_file)],
                            }
                        }
                        for index, source in enumerate((ontology, transform))
                    },
                    "destination": {"tsv": {"format": "tsv", "compression": "tar.gz", "filename": "ingredients"}},
                },
            }
        )
    )
    load_and_merge(str(config), processes=1)
    published = output / "published/ingredients.tar.gz"
    with tarfile.open(published) as archive:
        nodes = {
            row["id"]: row
            for row in csv.DictReader(
                io.StringIO(archive.extractfile("ingredients_nodes.tsv").read().decode()),
                delimiter="\t",
                quoting=csv.QUOTE_NONE,
            )
        }
        edges = list(
            csv.DictReader(
                io.StringIO(archive.extractfile("ingredients_edges.tsv").read().decode()),
                delimiter="\t",
                quoting=csv.QUOTE_NONE,
            )
        )
    ingredient_edges = [row for row in edges if row.get("ingredient_profile")]
    original = {
        "ingredient_mapping_json": bundle.mappings(),
        "ingredient_annotation_json": bundle.identifier_claims(),
        "ingredient_product_json": bundle.products(),
        "ingredient_occurrence_json": bundle.occurrences(),
    }
    for column, claims in original.items():
        assert sorted(row[column] for row in ingredient_edges if row.get(column)) == sorted(map(json_scalar, claims)), (
            column
        )
    assert len(ingredient_edges) == sum(map(len, original.values()))
    assert all(row["ingredient_bundle_sha256"] == bundle.fingerprint for row in ingredient_edges)
    assert all(row[end] in nodes for row in edges for end in ("subject", "object"))
    expected_classification = {("CHEBI:17712", "CHEBI:15318"), ("CHEBI:29673", "CHEBI:26580")}
    assert {
        (row["subject"], row["object"]) for row in edges if row["predicate"] == "biolink:subclass_of"
    } == expected_classification
    assert all(row["predicate"] not in {"biolink:subclass_of", "biolink:same_as"} for row in ingredient_edges)
    for owner in {bundle.canonical_owner(row["subject_id"]) for row in bundle.mappings()} | {
        row["product_id"] for row in bundle.products()
    }:
        assert sorted(
            x for x in nodes[owner].get("xref", "").split("|") if x.lower().startswith("cas:")
        ) == bundle.active_xrefs(owner), owner
    assert not any(x.lower().startswith("cas:") for x in nodes["CHEBI:15318"].get("xref", "").split("|"))
    assert nodes["CHEBI:26580"].get("xref", "").find("cas:") == -1
    assert "cas:6998-60-3" in nodes["CHEBI:29673"]["xref"].split("|")
    assert "cas:69-89-6" in nodes["CHEBI:17712"]["xref"].split("|")
    assert "cas:65589-70-0" in nodes["NCIT:C76253"]["xref"].split("|")
    assert "cas:8048-52-0" not in nodes["NCIT:C76253"]["xref"].split("|")
    bsa = [row for row in bundle.occurrences() if row["ingredient_id"] == "MIM:Bovine_Serum_Albumin"]
    assert len([row for row in bsa if row["source_id"].startswith("CultureMech:")]) == 7
    alternative = next(row for row in bsa if row["source_id"] == "CultureMech:015191")
    assert alternative["product_id"] is None
    assert alternative["alternatives"][0]["operator"] == "one_of"
    assert alternative["alternatives"][0]["selection_status"] == "UNSPECIFIED"
    assert len(alternative["alternatives"][0]["members"]) == 2
    assert not any(row["catalog_number"] in json.dumps(nodes["NCIT:C85253"]) for row in bundle.products())
    if synthetic:
        shared = [row for row in bundle.products() if row["supplier"] == "Example Supplier"]
        assert len(shared) == 2 and shared[0]["product_id"] != shared[1]["product_id"]
        assert all(nodes[row["product_id"]]["xref"] == "cas:9048-46-8" for row in shared)
        assert len([row for row in bsa if row["source_id"] == "example:synthetic-occurrences"]) == 2
    else:
        assert [row["source_id"] for row in bsa if row["product_id"]] == ["CultureBotHT:compounds-to-cas"]
    report = {
        "status": "PASS",
        "mode": "candidate_only",
        "production_promotion_authorized": False,
        "bundle_manifest_sha256": bundle.fingerprint,
        "lookup_manifest_sha256": receipt["manifest_sha256"],
        "producer_commit": bundle_origin["producer_commit"],
        "synthetic_software_fixture": synthetic,
        "native_input_origin_sha256": sha256(native / "acceptance-native-origin.json"),
        "biolink_version": "4.4.2",
        "chebi_version": "253",
        "foodon_version": "2025-12-30",
        "archive_sha256": sha256(published),
        "projected": projected,
        "merged_nodes": len(nodes),
        "merged_edges": len(edges),
        "audit": bundle.audit(),
        "claim_payloads_sha256": hashlib.sha256(
            canonical_json({key: sorted(map(json_scalar, rows)) for key, rows in original.items()})
        ).hexdigest(),
        "graph_semantics_sha256": hashlib.sha256(
            canonical_json({"nodes": nodes, "edges": sorted(edges, key=json_scalar)})
        ).hexdigest(),
    }
    (output / "acceptance.json").write_bytes(canonical_json(report) + b"\n")
    return report


def main():
    """Keep KGX import and full pinned model selection isolated from the pytest process."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--synthetic", action="store_true")
    parser.add_argument("--reverse", action="store_true")
    args = parser.parse_args()
    print(json.dumps(run(args.output, args.synthetic, args.reverse), indent=2))


if __name__ == "__main__":
    main()
