"""
Load curated microbial trait mappings from turbomam/microbial-trait-mappings TSVs.

These mappings provide subject_label -> (object_id, object_source, biolink_predicate, object_category)
for metatraits transform edge resolution. Used as the authoritative lookup before METPO fallback.
"""

import csv
from pathlib import Path
from typing import Dict, Optional

from kg_microbe.transform_utils.constants import METATRAITS_MAPPINGS_DIR

# Mappings dir: project_root/mappings/metatraits/
_MAPPINGS_DIR = METATRAITS_MAPPINGS_DIR

# Object source -> Biolink category
_OBJECT_SOURCE_TO_CATEGORY = {
    "CHEBI": "biolink:ChemicalSubstance",  # Use ChemicalSubstance for all CHEBI entities
    "EC": "biolink:MolecularActivity",
    "METPO": "biolink:PhenotypicFeature",
    "GO": "biolink:BiologicalProcess",
}

# Category override: GO terms in enzyme_mappings.tsv are molecular functions
_ENTITY_CATEGORY_OVERRIDE = {
    "enzyme": {"GO": "biolink:MolecularActivity"},
    "enzymes": {"GO": "biolink:MolecularActivity"},
}


def _resolve_biolink_predicate(subject_label: str, notes: str, entity_category: str = "") -> str:
    """
    Derive biolink predicate from notes or subject_label pattern.

    :param subject_label: Full trait label (e.g. 'produces: ethanol')
    :param notes: Notes column from mapping TSV
    :param entity_category: Entity category (chemicals, enzymes, pathways, phenotypes)
    :return: Biolink predicate CURIE
    """
    for token in notes.replace(";", " ").split():
        if token.startswith("biolink:"):
            return token
    # Fallback heuristics from subject_label pattern
    if subject_label.startswith("produces:"):
        return "biolink:produces"
    if subject_label.startswith("carbon source:") or subject_label.startswith("enzyme activity:"):
        return "biolink:capable_of"
    return "biolink:has_phenotype"


def _resolve_object_category(object_source: str, entity_category: str = "") -> str:
    """
    Derive KGX object category from object_source and entity category.

    :param object_source: CHEBI, EC, METPO, GO
    :param entity_category: Entity category (chemicals, enzymes, pathways, phenotypes)
    :return: Biolink category
    """
    if entity_category and entity_category in _ENTITY_CATEGORY_OVERRIDE:
        override = _ENTITY_CATEGORY_OVERRIDE[entity_category]
        if object_source in override:
            return override[object_source]
    return _OBJECT_SOURCE_TO_CATEGORY.get(object_source, "biolink:NamedThing")


def load_microbial_trait_mappings(
    mappings_dir: Optional[Path] = None,
) -> Dict[str, Dict[str, str]]:
    """
    Load all positive mapping TSVs from mappings/metatraits/.

    Excludes *_negative_mappings.tsv files.

    :param mappings_dir: Override default mappings directory
    :return: Dict mapping subject_label -> {object_id, object_label, object_source,
             biolink_predicate, object_category}
    """
    base = mappings_dir or _MAPPINGS_DIR
    if not base.exists():
        return {}

    result: Dict[str, Dict[str, str]] = {}

    for tsv_path in sorted(base.rglob("*.tsv")):
        if "negative" in tsv_path.name:
            continue
        # Derive entity category from filename (e.g. enzyme_mappings.tsv -> enzymes)
        entity_category = tsv_path.stem.replace("_mappings", "").replace("_mapping", "")

        try:
            with open(tsv_path, encoding="utf-8") as f:
                reader = csv.DictReader(f, delimiter="\t")
                for row in reader:
                    subject_label = row.get("subject_label", "").strip()
                    if not subject_label:
                        continue

                    object_id = row.get("object_id", "").strip()
                    object_label = row.get("object_label", "").strip()
                    object_source = row.get("object_source", "").strip()
                    notes = row.get("notes", "").strip()

                    if not object_id or not object_source:
                        continue

                    biolink_predicate = _resolve_biolink_predicate(
                        subject_label, notes, entity_category
                    )
                    object_category = _resolve_object_category(object_source, entity_category)

                    result[subject_label] = {
                        "object_id": object_id,
                        "object_label": object_label or subject_label,
                        "object_source": object_source,
                        "biolink_predicate": biolink_predicate,
                        "object_category": object_category,
                    }
                    # Also add normalized (lowercase) key for case-insensitive lookup
                    normalized = row.get("subject_label_normalized", subject_label.lower()).strip()
                    if normalized and normalized not in result:
                        result[normalized] = result[subject_label]
        except (OSError, csv.Error) as e:
            # Log but continue with other files
            print(f"Warning: Could not load {tsv_path}: {e}")

    return result
