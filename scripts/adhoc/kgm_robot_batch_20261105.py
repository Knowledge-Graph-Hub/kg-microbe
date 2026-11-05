"""
Regenerate staged ROBOT-derived ontology JSON after the 2026-11-05 UPA canary.

Inputs: unchanged staged native ontology sources, verified ROBOT1.9.11 candidates,
and the retained UPA canary/annotation assessment. Outputs: independent conversion
candidates and per-source receipts. Production raw activation is a separate gate.
"""

import argparse
import ast
import hashlib
import json
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
UPGRADES = ROOT / "data/rebuild-evidence/20261105/upgrades"
DESTINATION = UPGRADES / "robot-conversions"


def digest(path):
    """Hash an input or output in bounded memory."""
    checksum = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            checksum.update(block)
    return checksum.hexdigest()


def save(path, value):
    """Retain each successful stage as a new evidence file."""
    with path.open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")


def derived_sources():
    """Read the exact canonical source map without invoking any transform."""
    source = ROOT / "kg_microbe/transform_utils/ontologies/ontologies_transform.py"
    tree = ast.parse(source.read_text())
    matches = [
        node.value
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "ONTOLOGIES_MAP" for target in node.targets)
    ]
    if len(matches) != 1:
        raise RuntimeError("Expected one literal canonical ontology map")
    mapping = ast.literal_eval(matches[0])
    return {key: name for key, name in mapping.items() if name.endswith((".owl", ".owl.gz"))}


def clone(source, target):
    """Make a byte-verified independent APFS clone, refusing any destination collision."""
    if source.is_symlink() or not source.is_file() or target.exists() or target.is_symlink():
        raise RuntimeError(f"Unsafe conversion clone: {source} -> {target}")
    subprocess.run(["/bin/cp", "-c", "-p", str(source), str(target)], check=True)  # noqa: S603
    checksum = digest(source)
    if target.samefile(source) or target.stat().st_nlink != 1 or digest(target) != checksum:
        raise RuntimeError(f"Conversion clone differs or aliases its source: {source}")
    return {"source": str(source), "sha256": checksum, "bytes": source.stat().st_size}


def execute():
    """Run each conversion once, including the production NCBITaxon removal path."""
    from kg_microbe.transform_utils.constants import EXCLUSION_TERMS_FILE, ROBOT_REMOVED_SUFFIX
    from kg_microbe.utils.ontology_utils import _decompress_atomically
    from kg_microbe.utils.robot_utils import convert_to_json, remove_convert_to_json

    if Path.cwd().resolve() != ROOT:
        raise RuntimeError("Use the owned worktree")
    canary = json.loads((UPGRADES / "upa-canary/conversion.json").read_text())
    assessment = UPGRADES / "robot-rhea/upa-review-1/upa-xref-annotation-assessment.json"
    if not assessment.is_file():
        raise RuntimeError("The retained UPA annotation review is required before batch conversion")
    review = json.loads(assessment.read_text())
    for key in (
        "all_added_annotations_exactly_present_in_pinned_owl",
        "removing_only_added_xref_metadata_recovers_exact_old_document",
        "removing_only_added_xref_metadata_recovers_exact_old_ordered_routes",
    ):
        if review.get(key) is not True:
            raise RuntimeError(f"UPA canary review is incomplete: {key}")
    if review.get("source_annotation_mismatches") != [] or review.get("scientific_dispositions_changed") is not False:
        raise RuntimeError("UPA annotations or scientific dispositions require further review")
    for source in review["inputs"]:
        if digest(Path(source["path"])) != source["sha256"]:
            raise RuntimeError(f"UPA review input changed: {source['path']}")
    robot = UPGRADES / "candidates/robot1911"
    for name in ("robot.jar", "robot"):
        if digest(robot / name) != canary["input_identities"][name]["sha256"]:
            raise RuntimeError(f"Batch ROBOT differs from the UPA canary: {name}")
    if digest(ROOT / "data/raw/upa.owl") != canary["input_identities"]["upa.owl"]["sha256"]:
        raise RuntimeError("Staged UPA source differs from the canary input")
    sources = derived_sources()
    DESTINATION.mkdir(parents=True, exist_ok=False)
    receipts = DESTINATION / "receipts"
    receipts.mkdir()
    save(
        DESTINATION / "plan.json",
        {
            "sources": sources,
            "upa_canary": canary,
            "annotation_assessment_sha256": digest(assessment),
            "raw_activation": False,
        },
    )
    for name in ("robot.jar", "robot"):
        clone(robot / name, DESTINATION / name)
    clone(ROOT / "data/raw" / EXCLUSION_TERMS_FILE, DESTINATION / EXCLUSION_TERMS_FILE)
    order = ("upa", "ro", "uberon", "foodon", "pato", "metpo", "taxrank", "go", "ec", "chebi", "ncbitaxon")
    if set(order) != set(sources):
        raise RuntimeError("Canonical derived ontology set changed; review conversion order")
    for name in order:
        filename = sources[name]
        started = time.time()
        output = DESTINATION / (name + (ROBOT_REMOVED_SUFFIX if name == "ncbitaxon" else "") + ".json")
        input_identity = clone(ROOT / "data/raw" / filename, DESTINATION / filename)
        if name == "upa":
            expected = canary["candidate_json_sha256"]
            if digest(UPGRADES / "upa-canary/upa.json") != expected:
                raise RuntimeError("UPA canary JSON changed")
            clone(UPGRADES / "upa-canary/upa.json", output)
        else:
            if filename.endswith(".gz"):
                if not _decompress_atomically(DESTINATION / filename, DESTINATION / filename.removesuffix(".gz")):
                    raise RuntimeError(f"Native decompression failed: {filename}")
            if name == "ncbitaxon":
                terms = [
                    line.strip()
                    for line in (DESTINATION / EXCLUSION_TERMS_FILE).read_text().splitlines()
                    if line.lower().startswith(name)
                ]
                remove_convert_to_json(str(DESTINATION), name, terms)
            else:
                convert_to_json(str(DESTINATION), name)
        if not output.is_file() or output.stat().st_size == 0:
            raise RuntimeError(f"No nonempty converted candidate: {name}")
        save(
            receipts / (name + ".json"),
            {
                "input": input_identity,
                "output": str(output),
                "sha256": digest(output),
                "bytes": output.stat().st_size,
                "elapsed_seconds": time.time() - started,
                "robot_sha256": digest(DESTINATION / "robot.jar"),
                "robot_wrapper_sha256": digest(DESTINATION / "robot"),
                "semantic_admission": False,
            },
        )
        print(f"Converted candidate {name}: {output.stat().st_size} bytes", flush=True)
    save(DESTINATION / "receipt.json", {"converted_sources": list(sources), "raw_activation": False})


def main():
    """Print the planned source set, or explicitly regenerate independent candidates."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if args.execute:
        execute()
    else:
        print(json.dumps({"sources": derived_sources(), "destination": str(DESTINATION)}, indent=2))


if __name__ == "__main__":
    main()
