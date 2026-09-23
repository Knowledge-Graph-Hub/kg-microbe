"""Build an isolated, conservative KGM candidate from a pinned MIM release."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

PIN_FILE = Path("mappings/mim_reviewed_release.json")
ONTOLOGY_INPUTS = (
    "transformed/ontologies/chebi_nodes.tsv",
    "transformed/ontologies/envo_nodes.tsv",
    "transformed/ontologies/foodon_nodes.tsv",
    "transformed/ontologies/uberon_nodes.tsv",
    "transformed/ontologies_stubs/ncit_nodes.tsv",
    "transformed/ontologies_stubs/mesh_nodes.tsv",
    "transformed/ontologies_stubs/micro_nodes.tsv",
    "transformed/ontologies_stubs/bto_nodes.tsv",
    "transformed/ontologies_stubs/po_nodes.tsv",
)
REPO_INPUTS = (
    ("metabolite_json", "kg_microbe/transform_utils/bacdive/metabolite_mapping.json"),
    ("manual_annotations", "kg_microbe/transform_utils/madin_etal/chebi_manual_annotation.tsv"),
    ("metatraits_chemical_mappings", "mappings/canonical/chemical_mappings.tsv"),
)


def load_release_pin(repo_root: Path) -> dict:
    """Require an explicit, reviewable release pin with no publication authority."""
    pin = json.loads((repo_root / PIN_FILE).read_text(encoding="utf-8"))
    required = {"schema_version", "release_tag", "release_url", "source_commit", "manifest_sha256", "mode"}
    if not isinstance(pin, dict) or set(pin) != required:
        raise ValueError("Invalid reviewed MIM release pin fields")
    if type(pin["schema_version"]) is not int or pin["schema_version"] != 1 or pin["mode"] != "candidate_only":
        raise ValueError("Reviewed MIM release pin must use schema_version=1, mode=candidate_only")
    for field, length in (("manifest_sha256", 64), ("source_commit", 40)):
        if not isinstance(pin[field], str) or re.fullmatch(rf"[0-9a-f]{{{length}}}", pin[field]) is None:
            raise ValueError(f"Invalid {field} in reviewed MIM release pin")
    tag = pin["release_tag"]
    if not isinstance(tag, str) or re.fullmatch(r"mim-sssom-\d{4}-\d{2}-\d{2}", tag) is None:
        raise ValueError("Invalid reviewed MIM release tag")
    if pin["release_url"] != f"https://github.com/CultureBotAI/MediaIngredientMech/releases/tag/{tag}":
        raise ValueError("Reviewed MIM release URL must identify the pinned upstream release")
    return pin


def build_candidate(*, repo_root: Path, data_root: Path, release_directory: Path, output_directory: Path):
    """Select explicit current evidence; never sync floating sibling exports."""
    from scripts.mim_conservative_refresh import IndependentSource, build_conservative_candidate

    pin = load_release_pin(repo_root)
    sources = tuple(IndependentSource(kind, repo_root / path) for kind, path in REPO_INPUTS)
    return build_conservative_candidate(
        baseline=repo_root / "mappings/kgmicrobe_unified_entity_mappings.sssom.tsv.gz",
        release_directory=release_directory,
        expected_manifest_sha256=pin["manifest_sha256"],
        ontology_paths=tuple(data_root / path for path in ONTOLOGY_INPUTS),
        independent_sources=sources,
        output_directory=output_directory,
    )


def main(argv=None) -> None:
    """Build a new candidate directory without changing production mappings."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-directory", type=Path, required=True, help="Downloaded complete pinned MIM bundle.")
    parser.add_argument("--output-directory", type=Path, required=True, help="New directory; must not already exist.")
    parser.add_argument(
        "--data-root", type=Path, help="Current raw/transformed evidence root; defaults to this repo's data/."
    )
    args = parser.parse_args(argv)
    repo_root = Path(__file__).resolve().parents[1]
    build_candidate(
        repo_root=repo_root,
        data_root=args.data_root or repo_root / "data",
        release_directory=args.release_directory,
        output_directory=args.output_directory,
    )
    print(f"Candidate built in {args.output_directory}. Production mappings are unchanged; review report.json first.")


if __name__ == "__main__":
    main()
