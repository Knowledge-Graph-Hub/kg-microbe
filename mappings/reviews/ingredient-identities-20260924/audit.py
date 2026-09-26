"""Verify reviewed ingredient routes and CAS annotations on the full candidate."""

import argparse
import hashlib
import json
from pathlib import Path

from kg_microbe.utils import chemical_mapping_utils as runtime

CASES = {
    "Anabasine Hydrochloride": ("NCIT:C216370", "53912-89-3"),
    "Cotarnine Chloride": ("NCIT:C79997", "10018-19-6"),
    "Pretomanid": ("NCIT:C166606", "187235-37-6"),
    "Sutezolid": ("NCIT:C152482", "168828-58-8"),
    "Bovine Serum Albumin": ("NCIT:C85253", "9048-46-8"),
    "Sunflower Oil": ("NCIT:C1241", "8001-21-6"),
    "Zymosan": ("NCIT:C183132", "9010-72-4"),
    "Locust Bean Gum": ("FOODON:03413132", "9000-40-2"),
    "Tara Gum": ("FOODON:03413299", "39300-88-4"),
    "Sodium Adipate": ("FOODON:03413240", "7486-38-6"),
    "Acriflavine": ("NCIT:C76253", "65589-70-0"),
}
LOCAL = "kgmicrobe.ingredient:lysozyme"


def require(condition, detail):
    """Reject a failed audit even when Python assertions are disabled."""
    if not condition:
        raise ValueError(detail)


def sha(path):
    """Fingerprint an input without loading graph-scale files into memory."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    """Fail if an approved route, annotation or rejected equivalence regresses."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[3]
    inputs = [
        args.candidate,
        root / "mappings/ingredient_name_scopes.tsv",
        root / "mappings/ingredient_identity_exclusions.tsv",
        root / "kg_microbe/utils/chemical_mapping_utils.py",
        root / "kg_microbe/utils/ingredient_identity.py",
    ]
    fingerprints = {str(path): sha(path) for path in inputs}
    runtime.load_unified_mappings(args.candidate)
    results = []
    for name, (target, cas) in CASES.items():
        subject = "MIM:" + name.replace(" ", "_")
        annotations = runtime.get_node_enrichment(target)["xref"].split("|")
        found = {
            "name": runtime.find_chebi_by_name(name),
            "subject": runtime.find_chebi_by_xref(subject),
            "cas": runtime.find_chebi_by_xref("cas:" + cas),
        }
        require(set(found.values()) == {target}, (name, found))
        require("cas:" + cas in annotations, (name, annotations))
        results.append(
            {"name": name, "target": target, "current_cas": cas, "lookups": found, "node_xrefs": annotations}
        )
    require(runtime.find_chebi_by_name("Lysozyme") == LOCAL, "Wrong generic Lysozyme route")
    require(runtime.find_chebi_by_xref("MIM:Lysozyme") == LOCAL, "Wrong explicit Lysozyme route")
    local_annotations = runtime.get_node_enrichment(LOCAL)["xref"].split("|")
    require(not any(token.lower().startswith("cas:") for token in local_annotations), "Unreviewed Lysozyme CAS")
    require("FOODON:03413135" not in runtime.get_xrefs(LOCAL), "Unreviewed Lysozyme equivalence")
    require(
        "cas:8048-52-0" not in runtime.get_node_enrichment("NCIT:C76253")["xref"].split("|"),
        "Historical CAS in active xrefs",
    )
    rejected = {}
    for cas, prohibited in [("2650-88-3", LOCAL), ("12650-88-3", LOCAL), ("8048-52-0", "NCIT:C76253")]:
        found = runtime.find_chebi_by_xref("cas:" + cas)
        require(found != prohibited, (cas, found))
        require(runtime.find_chebi_by_name("CAS:" + cas) != prohibited, "Rejected CAS alias " + cas)
        rejected[cas] = {"prohibited_target": prohibited, "actual_lookup": found}
    require(all(sha(Path(path)) == value for path, value in fingerprints.items()), "Inputs changed during audit")
    report = {
        "scope": (
            "Eleven reviewed ontology identities and one unresolved local material in the full candidate; "
            "native identifiers in other supported contexts remain available."
        ),
        "input_sha256": fingerprints,
        "ontology_cases": results,
        "lysozyme": {"target": LOCAL, "node_xrefs": local_annotations, "cas_assigned": False},
        "rejected_cas_equivalence": rejected,
    }
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(
        json.dumps(
            {"verified_ontology_cases": len(results), "local_lysozyme": LOCAL, "rejected_cas_equivalence": rejected},
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
