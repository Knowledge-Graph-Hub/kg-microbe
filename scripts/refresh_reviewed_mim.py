"""Build an isolated, conservative KGM candidate from a pinned MIM release."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import tarfile
from pathlib import Path, PurePosixPath

PIN_FILE = Path("mappings/mim_reviewed_release.json")
UPSTREAM = "https://github.com/CultureBotAI/MediaIngredientMech"
SOURCE_SSSOM = "mappings/ingredient_mappings.sssom.tsv"
SOURCE_REVIEW = "reports/sssom_completion_20260921/review.json"
SOURCE_WORKFLOW = ".github/workflows/qc-reviewed-sssom.yaml"
PRODUCT_FILES = {"ingredient_mappings.sssom.tsv", "withheld_mappings.sssom.tsv", "mapping-dispositions.tsv"}
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


def _unique_object(pairs):
    """Reject duplicate JSON metadata instead of silently replacing a pin."""
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate reviewed MIM metadata key: {key}")
        result[key] = value
    return result


def _fields(value, required, label):
    """Reject omitted, unknown or wrongly typed contract objects."""
    if not isinstance(value, dict) or set(value) != required:
        raise ValueError(f"Invalid reviewed MIM {label} fields")


def _digest(value, label):
    """Require canonical non-floating SHA-256 metadata."""
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError(f"Invalid {label} in reviewed MIM pin")


def _hash_stream(stream):
    """Hash bounded chunks without reading the complete source archive into memory."""
    digest = hashlib.sha256()
    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
        digest.update(chunk)
    return digest.hexdigest()


def _file_hash(path):
    """Fingerprint only a regular, nonsymlink input."""
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Missing or unsafe provenance input: {path}")
    with path.open("rb") as stream:
        return _hash_stream(stream)


def load_release_pin(repo_root: Path) -> dict:
    """Require a strict tagged-release or immutable-export pin, never publication authority."""
    pin = json.loads((repo_root / PIN_FILE).read_text(encoding="utf-8"), object_pairs_hook=_unique_object)
    if not isinstance(pin, dict) or type(pin.get("schema_version")) is not int:
        raise ValueError("Invalid reviewed MIM release pin schema_version")
    version = pin["schema_version"]
    common = {"schema_version", "source_commit", "manifest_sha256", "mode"}
    if version == 1:
        required = common | {"release_tag", "release_url"}
    elif version == 2:
        required = common | {"origin", "source_archive", "export_recipe", "validation_run_url", "files"}
    else:
        raise ValueError("Unsupported reviewed MIM release pin schema_version")
    _fields(pin, required, "release pin")
    if pin["mode"] != "candidate_only":
        raise ValueError("Reviewed MIM release pin must use mode=candidate_only")
    for field, length in (("manifest_sha256", 64), ("source_commit", 40)):
        if not isinstance(pin[field], str) or re.fullmatch(rf"[0-9a-f]{{{length}}}", pin[field]) is None:
            raise ValueError(f"Invalid {field} in reviewed MIM release pin")
    if version == 1:
        tag = pin["release_tag"]
        if not isinstance(tag, str) or re.fullmatch(r"mim-sssom-\d{4}-\d{2}-\d{2}", tag) is None:
            raise ValueError("Invalid reviewed MIM release tag")
        if pin["release_url"] != f"{UPSTREAM}/releases/tag/{tag}":
            raise ValueError("Reviewed MIM release URL must identify the pinned upstream release")
        return pin
    if pin["origin"] != "immutable_commit_export":
        raise ValueError("Unsupported reviewed MIM export origin")
    _fields(pin["source_archive"], {"url", "sha256"}, "source archive")
    expected_url = "https://codeload.github.com/CultureBotAI/MediaIngredientMech/tar.gz/" + pin["source_commit"]
    if pin["source_archive"]["url"] != expected_url:
        raise ValueError("Source archive URL must identify the exact pinned upstream commit")
    _digest(pin["source_archive"]["sha256"], "source archive SHA-256")
    recipe = pin["export_recipe"]
    _fields(recipe, {"id", "python_version", "lock_sha256", "workflow_sha256"}, "export recipe")
    if recipe["id"] != "reviewed_sssom_v1" or recipe["python_version"] != "3.13":
        raise ValueError("Unsupported immutable export recipe or Python version")
    for field in ("lock_sha256", "workflow_sha256"):
        _digest(recipe[field], field)
    run_url = pin["validation_run_url"]
    if (
        not isinstance(run_url, str)
        or re.fullmatch(re.escape(UPSTREAM) + r"/actions/runs/[1-9][0-9]*", run_url) is None
    ):
        raise ValueError("Invalid immutable export validation run URL")
    _fields(pin["files"], PRODUCT_FILES, "product")
    for name, digest in pin["files"].items():
        _digest(digest, name)
    return pin


def validate_immutable_export(pin: dict, source_archive: Path, release_directory: Path) -> dict:
    """Bind the export to archived source/review/locked workflow bytes without extraction or execution."""
    if source_archive is None:
        raise ValueError("Immutable commit exports require --source-archive")
    source_archive, release_directory = Path(source_archive), Path(release_directory)
    if release_directory.is_symlink() or not release_directory.is_dir():
        raise ValueError("Missing or unsafe reviewed MIM release directory")
    if _file_hash(source_archive) != pin["source_archive"]["sha256"]:
        raise ValueError("Source archive SHA-256 does not match the immutable export pin")
    manifest_path = release_directory / "manifest.json"
    if _file_hash(manifest_path) != pin["manifest_sha256"]:
        raise ValueError("Export manifest SHA-256 does not match the pin")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"), object_pairs_hook=_unique_object)
    if not isinstance(manifest, dict) or manifest.get("source_sssom") != SOURCE_SSSOM:
        raise ValueError("Immutable export manifest names an unsupported source SSSOM")
    if manifest.get("files") != pin["files"]:
        raise ValueError("Export product hashes do not match the immutable pin")
    for name, digest in pin["files"].items():
        if _file_hash(release_directory / name) != digest:
            raise ValueError(f"Export product SHA-256 mismatch: {name}")
    expected = {
        SOURCE_SSSOM: manifest.get("source_sha256"),
        SOURCE_REVIEW: manifest.get("review_sha256"),
        "uv.lock": pin["export_recipe"]["lock_sha256"],
        SOURCE_WORKFLOW: pin["export_recipe"]["workflow_sha256"],
    }
    for name, digest in expected.items():
        _digest(digest, name)
    root = "MediaIngredientMech-" + pin["source_commit"]
    seen, observed = set(), {}
    with tarfile.open(source_archive, "r:gz") as archive:
        for member in archive:
            path = PurePosixPath(member.name)
            if (
                not path.parts
                or path.parts[0] != root
                or path.is_absolute()
                or ".." in path.parts
                or "\\" in member.name
                or path.as_posix() != member.name.rstrip("/")
                or any(ord(character) < 32 for character in member.name)
                or not (member.isfile() or member.isdir())
                or str(path) in seen
            ):
                raise ValueError(f"Unsafe, duplicate or wrong-commit source archive member: {member.name}")
            seen.add(str(path))
            relative = str(PurePosixPath(*path.parts[1:]))
            if relative in expected:
                if not member.isfile():
                    raise ValueError(f"Source provenance member is not a regular file: {relative}")
                with archive.extractfile(member) as stream:
                    observed[relative] = _hash_stream(stream)
    if observed != expected:
        raise ValueError("Archived source/review/locked workflow disagrees with the export provenance")
    if (
        _file_hash(source_archive) != pin["source_archive"]["sha256"]
        or _file_hash(manifest_path) != pin["manifest_sha256"]
    ):
        raise ValueError("Immutable export inputs changed during provenance verification")
    return {"archive_members_sha256": observed, "verification": "verified_archived_source_and_manifest_binding"}


def build_candidate(
    *,
    repo_root: Path,
    data_root: Path,
    release_directory: Path,
    output_directory: Path,
    source_archive: Path | None = None,
):
    """Select explicit current evidence; never sync floating sibling exports."""
    from scripts.mim_conservative_refresh import IndependentSource, build_conservative_candidate

    pin_path = repo_root / PIN_FILE
    pin_digest = _file_hash(pin_path)
    pin = load_release_pin(repo_root)
    if _file_hash(pin_path) != pin_digest:
        raise ValueError("Reviewed MIM pin changed while being read")
    provenance_inputs = {pin_path.resolve(): pin_digest, Path(__file__).resolve(): _file_hash(Path(__file__).resolve())}
    provenance = {"pin": pin}
    if pin["schema_version"] == 2:
        provenance.update(validate_immutable_export(pin, source_archive, release_directory))
        provenance_inputs[Path(source_archive).resolve()] = pin["source_archive"]["sha256"]
    elif source_archive is not None:
        raise ValueError("--source-archive is only valid for an immutable commit export pin")
    sources = tuple(IndependentSource(kind, repo_root / path) for kind, path in REPO_INPUTS)
    return build_conservative_candidate(
        baseline=repo_root / "mappings/kgmicrobe_unified_entity_mappings.sssom.tsv.gz",
        release_directory=release_directory,
        expected_manifest_sha256=pin["manifest_sha256"],
        ontology_paths=tuple(data_root / path for path in ONTOLOGY_INPUTS),
        independent_sources=sources,
        output_directory=output_directory,
        provenance_inputs=provenance_inputs,
        upstream_provenance=provenance,
    )


def main(argv=None) -> None:
    """Build a new candidate directory without changing production mappings."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-directory", type=Path, required=True, help="Downloaded complete pinned MIM bundle.")
    parser.add_argument("--output-directory", type=Path, required=True, help="New directory; must not already exist.")
    parser.add_argument(
        "--source-archive", type=Path, help="Pinned immutable source tar.gz; required for schema-v2 pins."
    )
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
        source_archive=args.source_archive,
    )
    print(f"Candidate built in {args.output_directory}. Production mappings are unchanged; review report.json first.")


if __name__ == "__main__":
    main()
