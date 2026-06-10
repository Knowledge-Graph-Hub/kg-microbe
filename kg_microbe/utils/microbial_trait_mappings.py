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

# Object source -> Biolink category. Keys are the literal values that appear in
# the canonical TSVs' ``object_source`` column. The kgmicrobe.* keys are the
# real-world namespace strings used by mappings/canonical/*_mappings.tsv (e.g.
# ``object_source = kgmicrobe.trait``); ``KGM`` is a legacy alias kept for
# back-compat with any older mapping that still uses the abbreviation.
_OBJECT_SOURCE_TO_CATEGORY = {
    "CHEBI": "biolink:ChemicalEntity",  # Use ChemicalEntity for all CHEBI entities
    "EC": "biolink:MolecularActivity",
    "METPO": "biolink:PhenotypicQuality",  # Changed from PhenotypicFeature per Biolink Model
    "GO": "biolink:BiologicalProcess",
    "KGM": "biolink:PhenotypicQuality",  # Custom KG-Microbe terms for phenotypes not in METPO
    "kgmicrobe.trait": "biolink:PhenotypicQuality",
    "kgmicrobe.activity": "biolink:MolecularActivity",
    "kgmicrobe.compound": "biolink:ChemicalEntity",
    "kgmicrobe.pathway": "biolink:BiologicalProcess",
    "kgmicrobe.ingredient": "biolink:ChemicalEntity",
    "kgmicrobe.medium": "biolink:GrowthMedium",  # objects of METPO:2000517 'grows in'
}

# Category override: GO terms in enzyme_mappings.tsv are molecular functions.
# KGM (kgmicrobe.activity:* placeholders for not-yet-minted METPO activity terms)
# also resolves to MolecularActivity in the enzyme context — see
# mappings/kgmicrobe_proposal_placeholders.tsv for the registry of these placeholders.
_ENTITY_CATEGORY_OVERRIDE = {
    "enzyme": {
        "GO": "biolink:MolecularActivity",
        "KGM": "biolink:MolecularActivity",
        "kgmicrobe.activity": "biolink:MolecularActivity",
    },
    "enzymes": {
        "GO": "biolink:MolecularActivity",
        "KGM": "biolink:MolecularActivity",
        "kgmicrobe.activity": "biolink:MolecularActivity",
    },
}


_SUBJECT_PREFIX_TO_PREDICATE = (
    ("produces:", "biolink:produces"),
    ("carbon source:", "METPO:2000006"),
    ("enzyme activity:", "biolink:capable_of"),
    ("fermentation:", "METPO:2000011"),
    ("ferments:", "METPO:2000011"),
    ("assimilation:", "METPO:2000002"),
    ("assimilates:", "METPO:2000002"),
    ("hydrolyzes:", "METPO:2000013"),
    ("hydrolysis:", "METPO:2000013"),
    ("degrades:", "METPO:2000007"),
    ("degradation:", "METPO:2000007"),
    ("oxidizes:", "biolink:consumes"),
    ("oxidation:", "biolink:consumes"),
    ("reduces:", "biolink:consumes"),
    ("reduction:", "biolink:consumes"),
    ("electron acceptor:", "biolink:consumes"),
    ("electron donor:", "METPO:2000009"),
    ("energy source:", "METPO:2000010"),
    ("nitrogen source:", "METPO:2000014"),
    ("sulfur source:", "biolink:consumes"),
    ("respiration:", "biolink:consumes"),
    ("denitrification:", "biolink:consumes"),
    ("ammonification:", "biolink:consumes"),
    ("builds acid from:", "METPO:2000003"),
    ("builds base from:", "METPO:2000004"),
    ("builds gas from:", "METPO:2000005"),
)


def _resolve_biolink_predicate(subject_label: str, notes: str, entity_category: str = "") -> str:
    """
    Derive biolink (or METPO:2000xxx) predicate from notes or subject_label pattern.

    Order: explicit biolink: token in notes, then explicit METPO:2000xxx token in
    notes, then subject_label prefix lookup, then default biolink:has_phenotype.

    :param subject_label: Full trait label (e.g. 'produces: ethanol')
    :param notes: Notes column from mapping TSV
    :param entity_category: Entity category (chemicals, enzymes, pathways, phenotypes)
    :return: Predicate CURIE (biolink: or METPO:2000xxx)
    """
    for token in notes.replace(";", " ").replace(",", " ").replace("(", " ").replace(")", " ").split():
        if token.startswith("biolink:"):
            return token
    for token in notes.replace(";", " ").replace(",", " ").replace("(", " ").replace(")", " ").split():
        if token.startswith("METPO:2000"):
            return token
    label_lower = subject_label.lower()
    for prefix, predicate in _SUBJECT_PREFIX_TO_PREDICATE:
        if label_lower.startswith(prefix):
            return predicate
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

                    # Phase-3 canonical-schema files (special_chemical_mappings.tsv,
                    # enzyme_name_to_go.tsv) carry per-row routing overrides via
                    # the bespoke ``emit_predicate`` / ``emit_category`` extension
                    # columns. Honor those when present — they encode the
                    # curator's intent at the row level (e.g. "electron acceptor:
                    # sulfur compounds" → METPO:2000008, biolink:ChemicalEntity)
                    # and would otherwise be silently rewritten to less specific
                    # generic-loader defaults (biolink:consumes / biolink:NamedThing).
                    # The generic resolvers run only as a fallback for rows
                    # without explicit overrides.
                    emit_predicate = (row.get("emit_predicate") or "").strip()
                    emit_category = (row.get("emit_category") or "").strip()
                    biolink_predicate = emit_predicate or _resolve_biolink_predicate(
                        subject_label, notes, entity_category
                    )
                    object_category = emit_category or _resolve_object_category(object_source, entity_category)

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
