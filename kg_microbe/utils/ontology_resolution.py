"""Pure ontology category policies over explicit lookup results and adapters."""

from typing import Protocol

from kg_microbe.transform_utils.constants import (
    ANATOMICAL_ENTITY_CATEGORY,
    BIOLOGICAL_PROCESS_CATEGORY,
    CELLULAR_COMPONENT_CATEGORY,
    EC_CATEGORY,
    EC_PREFIX,
    GENE_CATEGORY,
    GO_CATEGORY,
    GO_PREFIX,
    HGNC_NEW_PREFIX,
    MACROMOLECULE_CATEGORY,
    MOLECULAR_ACTIVITY_CATEGORY,
    NCBI_CATEGORY,
    PROTEIN_CATEGORY,
    RHEA_CATEGORY,
    RHEA_NEW_PREFIX,
    ROLE_CATEGORY,
    SMALL_MOLECULE_CATEGORY,
    UNIPROT_PREFIX,
)


class CategoryAdapter(Protocol):
    """Minimal adapter surface needed by ChEBI category policy."""

    def ancestors(self, term_id: str):
        """Return ancestor identifiers."""

    def label(self, term_id: str):
        """Return the preferred label, if present."""

    def relationships(self, term_id: str, predicates):
        """Return relationships matching the requested predicates."""


def replace_category_by_prefix(line: str, id_index: int, category_index: int) -> str:
    """Replace a TSV category according to its normalized identifier prefix."""
    parts = [item.strip() for item in line.split("\t")]
    replacements = (
        (EC_PREFIX, EC_CATEGORY),
        (GO_PREFIX, GO_CATEGORY),
        (UNIPROT_PREFIX, PROTEIN_CATEGORY),
        (RHEA_NEW_PREFIX, RHEA_CATEGORY),
        (HGNC_NEW_PREFIX, GENE_CATEGORY),
    )
    for prefix, category in replacements:
        if prefix in parts[id_index]:
            parts[category_index] = category
    return "\t".join(parts)


def go_category_for_namespace(namespace: str | None) -> str:
    """Map an OBO GO namespace to its Biolink category."""
    return {
        "molecular_function": MOLECULAR_ACTIVITY_CATEGORY,
        "biological_process": BIOLOGICAL_PROCESS_CATEGORY,
        "cellular_component": CELLULAR_COMPONENT_CATEGORY,
    }.get(namespace or "", BIOLOGICAL_PROCESS_CATEGORY)


def chebi_category(term_id: str, adapter: CategoryAdapter) -> str:
    """Classify a ChEBI term using injected ancestry, label, and parent data."""
    ancestors = set(adapter.ancestors(term_id))
    if "CHEBI:33839" in ancestors:
        return MACROMOLECULE_CATEGORY

    label = adapter.label(term_id)
    if label:
        label_lower = label.lower()
        role_suffixes = (
            "inhibitor",
            "agonist",
            "antagonist",
            "activator",
            "inducer",
            "agent",
            "cofactor",
            "coenzyme",
            "catalyst",
            "ligand",
            "substrate",
            "product",
            "intermediate",
            "donor",
            "acceptor",
        )
        standalone_roles = {
            "antioxidant",
            "drug",
            "pharmaceutical",
            "metabolite",
            "nutrient",
            "toxin",
            "poison",
            "mutagen",
            "carcinogen",
        }
        if label_lower in standalone_roles:
            return ROLE_CATEGORY
        if any(label_lower.endswith(suffix) or f" {suffix}" in label_lower for suffix in role_suffixes):
            return ROLE_CATEGORY
        if " role" in label_lower or label_lower.endswith("role"):
            return ROLE_CATEGORY

        relationships = adapter.relationships(term_id, predicates=["rdfs:subClassOf"])
        parent_ids = {str(relationship[2]) for relationship in relationships}
        if parent_ids & {"CHEBI:50906", "CHEBI:23888", "CHEBI:64047", "CHEBI:52217"}:
            return ROLE_CATEGORY

    return SMALL_MOLECULE_CATEGORY


def uberon_category(_term_id: str) -> str:
    """Return the invariant category for an UBERON term."""
    return ANATOMICAL_ENTITY_CATEGORY


def ncbitaxon_category(_term_id: str) -> str:
    """Return the invariant category for an NCBITaxon term."""
    return NCBI_CATEGORY


def replace_deprecated_category_names(category: str) -> str:
    """Replace Biolink categories removed in Biolink 4.x."""
    if not category:
        return category
    replacements = {
        "biolink:ChemicalSubstance": "biolink:ChemicalEntity",
        "biolink:Macromolecule": "biolink:MacromolecularComplex",
    }
    for old_category, new_category in replacements.items():
        category = category.replace(old_category, new_category)
    return category
