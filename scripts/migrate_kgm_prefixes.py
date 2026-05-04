#!/usr/bin/env python3
"""
Migrate KGM: prefix to split kgmicrobe.X: namespaces.

Rules (by Biolink category in custom_curies.yaml):
  biolink:MolecularActivity  → kgmicrobe.activity:
  biolink:PhenotypicQuality  → kgmicrobe.trait:
  biolink:Chemical*          → kgmicrobe.compound:
  biolink:Food               → kgmicrobe.compound:

Files updated:
  kg_microbe/transform_utils/custom_curies.yaml
  mappings/canonical/special_chemical_mappings.tsv
  mappings/canonical/enzyme_mappings.tsv
  mappings/canonical/phenotype_mappings.tsv
  kg_microbe/utils/validation_utils.py
  mappings/add_kgm_secondary_metabolites.py
  .claude/skills/kg-model-review/kg_model_review.py
  tests/test_validation_utils.py (if exists)
"""

import re
import sys
import yaml
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
CUSTOM_CURIES = REPO_ROOT / "kg_microbe" / "transform_utils" / "custom_curies.yaml"

CATEGORY_TO_PREFIX = {
    "biolink:MolecularActivity": "kgmicrobe.activity",
    "biolink:PhenotypicQuality": "kgmicrobe.trait",
    "biolink:ChemicalEntity": "kgmicrobe.compound",
    "biolink:ChemicalSubstance": "kgmicrobe.compound",
    "biolink:ChemicalMixture": "kgmicrobe.compound",
    "biolink:ComplexMolecularMixture": "kgmicrobe.compound",
    "biolink:Food": "kgmicrobe.compound",
    "biolink:SmallMolecule": "kgmicrobe.compound",
}


def build_rename_map() -> dict[str, str]:
    """Read custom_curies.yaml KGM section, return {old_curie: new_curie}."""
    with open(CUSTOM_CURIES, encoding="utf-8") as f:
        config = yaml.safe_load(f)

    kgm = config.get("KGM", {})
    rename_map = {}
    for slug, attrs in kgm.items():
        category = attrs.get("category", "")
        new_prefix = CATEGORY_TO_PREFIX.get(category)
        if new_prefix is None:
            print(f"  WARNING: unknown category {category!r} for KGM:{slug} — skipping")
            continue
        rename_map[f"KGM:{slug}"] = f"{new_prefix}:{slug}"
    return rename_map


def update_yaml(rename_map: dict[str, str]) -> None:
    """Rewrite custom_curies.yaml: split KGM: into three namespace sections."""
    with open(CUSTOM_CURIES, encoding="utf-8") as f:
        content = f.read()

    # Build per-namespace buckets preserving original block text
    # We'll do a text-level rewrite: read lines, identify KGM: section,
    # then emit three sections in its place.
    with open(CUSTOM_CURIES, encoding="utf-8") as f:
        config = yaml.safe_load(f)

    kgm = config.get("KGM", {})

    buckets: dict[str, list[tuple[str, dict]]] = {
        "kgmicrobe.activity": [],
        "kgmicrobe.trait": [],
        "kgmicrobe.compound": [],
    }
    for slug, attrs in kgm.items():
        category = attrs.get("category", "")
        new_prefix = CATEGORY_TO_PREFIX.get(category)
        if new_prefix:
            buckets[new_prefix].append((slug, attrs))

    # Find the KGM: section in the raw text and replace with three sections
    # Strategy: locate 'KGM:\n' and find the end (next top-level key or EOF)
    kgm_section_re = re.compile(r"^KGM:\n((?:  .+\n|\n)*)", re.MULTILINE)

    def format_entry(slug: str, attrs: dict) -> str:
        lines = [f"  {slug}:"]
        for k, v in attrs.items():
            lines.append(f'    {k}: "{v}"')
        lines.append("")
        return "\n".join(lines)

    def format_section(prefix: str, entries: list) -> str:
        section_key = f'"{prefix}"'
        lines = [f"{section_key}:"]
        for slug, attrs in entries:
            lines.append(format_entry(slug, attrs))
        return "\n".join(lines)

    new_sections = []
    for prefix in ["kgmicrobe.activity", "kgmicrobe.trait", "kgmicrobe.compound"]:
        if buckets[prefix]:
            new_sections.append(format_section(prefix, buckets[prefix]))

    replacement = "\n\n".join(new_sections) + "\n"

    new_content = kgm_section_re.sub(replacement, content)
    if new_content == content:
        print("  WARNING: KGM: section pattern not matched in YAML — manual edit may be needed")
    else:
        with open(CUSTOM_CURIES, "w", encoding="utf-8") as f:
            f.write(new_content)
        print(f"  Updated {CUSTOM_CURIES.relative_to(REPO_ROOT)}")


def update_file_text(path: Path, rename_map: dict[str, str], count_label: str) -> int:
    """Apply all renames as string replacements in a text file. Returns replacement count."""
    if not path.exists():
        print(f"  SKIP (not found): {path.relative_to(REPO_ROOT)}")
        return 0
    text = path.read_text(encoding="utf-8")
    count = 0
    for old, new in rename_map.items():
        occurrences = text.count(old)
        if occurrences:
            text = text.replace(old, new)
            count += occurrences
    if count:
        path.write_text(text, encoding="utf-8")
        print(f"  {count_label}: {count} replacements → {path.relative_to(REPO_ROOT)}")
    else:
        print(f"  {count_label}: no KGM: references found in {path.relative_to(REPO_ROOT)}")
    return count


def update_validation_utils(rename_map: dict[str, str]) -> None:
    """Update validation_utils.py to handle all three new prefixes."""
    path = REPO_ROOT / "kg_microbe" / "utils" / "validation_utils.py"
    if not path.exists():
        print(f"  SKIP: {path.relative_to(REPO_ROOT)} not found")
        return

    text = path.read_text(encoding="utf-8")

    # Replace the load_valid_kgm_terms function with a generalised version
    old_fn = '''def load_valid_kgm_terms(custom_curies_path: Optional[Path] = None) -> Set[str]:
    """
    Load valid KGM custom terms from custom_curies.yaml.

    :param custom_curies_path: Path to custom_curies.yaml file
                               If None, uses default path relative to this file
    :return: Set of valid KGM CURIEs (e.g., {"KGM:voges_proskauer_test_positive"})
    """
    if custom_curies_path is None:
        # Default path: kg_microbe/transform_utils/custom_curies.yaml
        base_dir = Path(__file__).parent.parent
        custom_curies_path = base_dir / "transform_utils" / "custom_curies.yaml"

    if not custom_curies_path.exists():
        return set()

    try:
        with open(custom_curies_path, encoding="utf-8") as f:
            config = yaml.safe_load(f)

        kgm_terms = set()
        if config and "KGM" in config:
            kgm_data = config["KGM"]
            # Extract term IDs from the KGM configuration
            # Structure: KGM: { term_id: { label: "...", description: "..." } }
            for term_id in kgm_data.keys():
                kgm_terms.add(f"KGM:{term_id}")

        return kgm_terms
    except (OSError, yaml.YAMLError):
        return set()


def validate_kgm_term(curie: str, valid_kgm_terms: Optional[Set[str]] = None) -> bool:
    """
    Validate that a KGM custom term exists in custom_curies.yaml.

    :param curie: CURIE to validate (e.g., "KGM:voges_proskauer_test_positive")
    :param valid_kgm_terms: Pre-loaded set of valid KGM terms
                            If None, will load from custom_curies.yaml
    :return: True if the KGM term is valid, False otherwise
    """
    if not curie or not curie.startswith("KGM:"):
        return False

    if valid_kgm_terms is None:
        valid_kgm_terms = load_valid_kgm_terms()

    return curie in valid_kgm_terms'''

    new_fn = '''# Namespace prefixes used by KG-Microbe custom terms
KGMICROBE_CUSTOM_PREFIXES = {
    "kgmicrobe.activity",
    "kgmicrobe.trait",
    "kgmicrobe.compound",
}


def load_valid_kgm_terms(custom_curies_path: Optional[Path] = None) -> Set[str]:
    """
    Load valid KG-Microbe custom terms from custom_curies.yaml.

    :param custom_curies_path: Path to custom_curies.yaml file
                               If None, uses default path relative to this file
    :return: Set of valid CURIEs (e.g., {"kgmicrobe.trait:voges_proskauer_test_positive"})
    """
    if custom_curies_path is None:
        # Default path: kg_microbe/transform_utils/custom_curies.yaml
        base_dir = Path(__file__).parent.parent
        custom_curies_path = base_dir / "transform_utils" / "custom_curies.yaml"

    if not custom_curies_path.exists():
        return set()

    try:
        with open(custom_curies_path, encoding="utf-8") as f:
            config = yaml.safe_load(f)

        kgm_terms = set()
        for prefix in KGMICROBE_CUSTOM_PREFIXES:
            section = config.get(prefix, {})
            if section:
                for term_id in section.keys():
                    kgm_terms.add(f"{prefix}:{term_id}")

        return kgm_terms
    except (OSError, yaml.YAMLError):
        return set()


def validate_kgm_term(curie: str, valid_kgm_terms: Optional[Set[str]] = None) -> bool:
    """
    Validate that a KG-Microbe custom term exists in custom_curies.yaml.

    :param curie: CURIE to validate (e.g., "kgmicrobe.trait:voges_proskauer_test_positive")
    :param valid_kgm_terms: Pre-loaded set of valid terms
                            If None, will load from custom_curies.yaml
    :return: True if the term is valid, False otherwise
    """
    if not curie:
        return False
    prefix = curie.split(":", 1)[0] if ":" in curie else ""
    if prefix not in KGMICROBE_CUSTOM_PREFIXES:
        return False

    if valid_kgm_terms is None:
        valid_kgm_terms = load_valid_kgm_terms()

    return curie in valid_kgm_terms'''

    if old_fn in text:
        text = text.replace(old_fn, new_fn)
        # Also fix validate_curie to allow dots in prefix
        text = text.replace(
            'pattern = r"^[A-Za-z][A-Za-z0-9_]*:\\S+$"',
            'pattern = r"^[A-Za-z][A-Za-z0-9_.]*:\\S+$"',
        )
        path.write_text(text, encoding="utf-8")
        print(f"  Updated validation_utils.py (generalised to kgmicrobe.* prefixes)")
    else:
        print("  WARNING: validation_utils.py pattern not matched — check manually")
        # Still apply simple string replacements for any literal KGM: refs
        update_file_text(path, rename_map, "validation_utils.py")


def update_review_skill(rename_map: dict[str, str]) -> None:
    """Add kgmicrobe.* prefixes to STANDARD_PREFIXES in kg_model_review.py."""
    path = REPO_ROOT / ".claude" / "skills" / "kg-model-review" / "kg_model_review.py"
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8")
    old = '"KGM", "UniProtKB"'
    new = '"kgmicrobe.activity", "kgmicrobe.trait", "kgmicrobe.compound",\n    "UniProtKB"'
    if old in text:
        text = text.replace(old, new)
        # Also remove old KGM from the set
        text = text.replace('"KGM",\n    ', '')
        path.write_text(text, encoding="utf-8")
        print(f"  Updated kg_model_review.py STANDARD_PREFIXES")
    # Also update any literal KGM: references
    update_file_text(path, rename_map, "kg_model_review.py literal refs")


def main() -> None:
    """Run the full migration."""
    print("Building rename map from custom_curies.yaml...")
    rename_map = build_rename_map()
    print(f"  {len(rename_map)} KGM: terms to rename:")
    by_prefix: dict[str, list] = {}
    for old, new in rename_map.items():
        p = new.split(":")[0]
        by_prefix.setdefault(p, []).append(f"  {old} → {new}")
    for prefix, items in sorted(by_prefix.items()):
        print(f"  {prefix}: ({len(items)} terms)")

    print("\nUpdating custom_curies.yaml...")
    update_yaml(rename_map)

    print("\nUpdating TSV mapping files...")
    for tsv_rel in [
        "mappings/canonical/special_chemical_mappings.tsv",
        "mappings/canonical/enzyme_mappings.tsv",
        "mappings/canonical/phenotype_mappings.tsv",
        "mappings/canonical/microbial_trait_mappings.tsv",
    ]:
        update_file_text(REPO_ROOT / tsv_rel, rename_map, tsv_rel.split("/")[-1])

    print("\nUpdating validation_utils.py...")
    update_validation_utils(rename_map)

    print("\nUpdating mappings/add_kgm_secondary_metabolites.py...")
    update_file_text(
        REPO_ROOT / "mappings" / "add_kgm_secondary_metabolites.py",
        rename_map,
        "add_kgm_secondary_metabolites.py",
    )

    print("\nUpdating tests...")
    update_file_text(
        REPO_ROOT / "tests" / "test_validation_utils.py",
        rename_map,
        "test_validation_utils.py",
    )

    print("\nUpdating review skill...")
    update_review_skill(rename_map)

    print("\nDone. Run the tests to verify:")
    print("  poetry run pytest tests/ -x -q")


if __name__ == "__main__":
    main()
