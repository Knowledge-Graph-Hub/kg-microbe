"""Ontology utilities for category assignment and term processing."""

from typing import Optional

from oaklib.interfaces import OboGraphInterface

from kg_microbe.transform_utils.constants import (
    BIOLOGICAL_PROCESS_CATEGORY,
    CELLULAR_COMPONENT_CATEGORY,
    EC_CATEGORY,
    EC_PREFIX,
    GENE_CATEGORY,
    GO_CATEGORY,
    GO_PREFIX,
    HGNC_NEW_PREFIX,
    MOLECULAR_ACTIVITY_CATEGORY,
    PROTEIN_CATEGORY,
    RHEA_CATEGORY,
    RHEA_NEW_PREFIX,
    ROLE_CATEGORY,
    SMALL_MOLECULE_CATEGORY,
    UNIPROT_PREFIX,
)


def replace_category_ontology(line, id_index, category_index):
    """
    Replace node category according to prefix that has already been fixed.

    :param line: A line from the original triples.
    :type line: str
    """
    parts = line.split("\t")
    parts = [i.strip() for i in parts]
    if EC_PREFIX in parts[id_index]:
        new_category = EC_CATEGORY
        parts[category_index] = new_category
    if GO_PREFIX in parts[id_index]:
        new_category = GO_CATEGORY
        parts[category_index] = new_category
    if UNIPROT_PREFIX in parts[id_index]:
        new_category = PROTEIN_CATEGORY
        parts[category_index] = new_category
    if RHEA_NEW_PREFIX in parts[id_index]:
        new_category = RHEA_CATEGORY
        parts[category_index] = new_category
    if HGNC_NEW_PREFIX in parts[id_index]:
        new_category = GENE_CATEGORY
        parts[category_index] = new_category
    new_line = "\t".join(parts)
    return new_line


def get_go_category_by_aspect(
    go_term_id: str, go_adapter: Optional[OboGraphInterface] = None
) -> str:
    """
    Return Biolink category based on GO aspect (namespace).

    GO terms have three aspects (namespaces):
    - molecular_function → biolink:MolecularActivity
    - biological_process → biolink:BiologicalProcess
    - cellular_component → biolink:CellularComponent

    Args:
    ----
        go_term_id: GO term ID (e.g., "GO:0004096")
        go_adapter: Optional OAK adapter for GO ontology. If None, will create one.

    Returns:
    -------
        Biolink category string

    Examples:
    --------
        >>> get_go_category_by_aspect("GO:0004096")  # catalase activity
        'biolink:MolecularActivity'

        >>> get_go_category_by_aspect("GO:0006091")  # generation of precursor metabolites
        'biolink:BiologicalProcess'

    """
    # Create adapter if not provided
    if go_adapter is None:
        try:
            from oaklib import get_adapter

            from kg_microbe.transform_utils.constants import GO_SOURCE

            go_adapter = get_adapter(f"sqlite:{GO_SOURCE}")
        except Exception:
            # Fallback to default path
            from oaklib import get_adapter

            go_adapter = get_adapter("sqlite:data/raw/go.db")

    try:
        # Get term information
        term_info = go_adapter.entity_metadata_map(go_term_id)

        if term_info and go_term_id in term_info:
            # Get namespace (aspect) from term metadata
            namespace = term_info[go_term_id].get("namespace", "")

            if namespace == "molecular_function":
                return MOLECULAR_ACTIVITY_CATEGORY
            elif namespace == "biological_process":
                return BIOLOGICAL_PROCESS_CATEGORY
            elif namespace == "cellular_component":
                return CELLULAR_COMPONENT_CATEGORY

    except Exception as e:
        print(f"Warning: Could not determine GO aspect for {go_term_id}: {e}")

    # Fallback to BiologicalProcess for unknown/error cases
    return BIOLOGICAL_PROCESS_CATEGORY


def get_chebi_category(
    chebi_term_id: str, chebi_adapter: Optional[OboGraphInterface] = None
) -> str:
    """
    Return appropriate Biolink category for ChEBI term.

    ChEBI terms can be:
    - Macromolecules (proteins, nucleic acids, polysaccharides) → biolink:Macromolecule
    - Roles (e.g., "antioxidant", "inhibitor") → biolink:ChemicalRole
    - Small molecules (default) → biolink:SmallMolecule

    Args:
    ----
        chebi_term_id: ChEBI term ID (e.g., "CHEBI:16828")
        chebi_adapter: Optional OAK adapter for ChEBI ontology

    Returns:
    -------
        Biolink category string

    """
    from kg_microbe.transform_utils.constants import MACROMOLECULE_CATEGORY

    # Create adapter if not provided
    if chebi_adapter is None:
        try:
            from oaklib import get_adapter

            from kg_microbe.transform_utils.constants import CHEBI_SOURCE

            chebi_adapter = get_adapter(f"sqlite:{CHEBI_SOURCE}")
        except Exception:
            from oaklib import get_adapter

            chebi_adapter = get_adapter("sqlite:data/raw/chebi.db")

    try:
        ancestors = list(chebi_adapter.ancestors(chebi_term_id))

        # FIRST: Check if this is a macromolecule (more specific than role)
        # CHEBI:33839 is the parent class for all macromolecules
        if "CHEBI:33839" in ancestors:
            return MACROMOLECULE_CATEGORY

        # SECOND: Check if this is a role term using name-based detection
        # This is more reliable than checking ancestry because "role" is a very general parent
        label = chebi_adapter.label(chebi_term_id)

        if label:
            label_lower = label.lower()

            # ChEBI roles have specific patterns in their names
            # Check for role terms (as suffix or complete word)
            role_suffixes = [
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
            ]

            # Standalone role terms (the term itself IS a role)
            standalone_roles = [
                "antioxidant",
                "drug",
                "pharmaceutical",
                "metabolite",
                "nutrient",
                "toxin",
                "poison",
                "mutagen",
                "carcinogen",
            ]

            # Check if the term itself is a standalone role
            if label_lower in standalone_roles:
                return ROLE_CATEGORY

            # Check for role suffixes at end of name
            if any(label_lower.endswith(suffix) for suffix in role_suffixes):
                return ROLE_CATEGORY

            # Check for role suffixes with space prefix (e.g., "enzyme inhibitor")
            if any(f" {suffix}" in label_lower for suffix in role_suffixes):
                return ROLE_CATEGORY

            # Check for "role" in the name itself
            if " role" in label_lower or label_lower.endswith("role"):
                return ROLE_CATEGORY

            # Check for specific role parent classes (direct children of CHEBI:50906)
            # These are more specific role categories
            specific_role_parents = [
                "CHEBI:50906",  # role
                "CHEBI:23888",  # drug
                "CHEBI:64047",  # chromophore
                "CHEBI:52217",  # pharmaceutical
            ]

            # Only categorize as role if it's a close descendant of specific role classes
            # (not just any distant ancestor)
            parents = list(
                chebi_adapter.relationships(chebi_term_id, predicates=["rdfs:subClassOf"])
            )
            parent_ids = [str(p[2]) for p in parents]

            if any(role_parent in parent_ids for role_parent in specific_role_parents):
                return ROLE_CATEGORY

    except Exception as e:
        print(f"Warning: Could not determine ChEBI category for {chebi_term_id}: {e}")

    # Default to SmallMolecule for most ChEBI terms (chemical compounds)
    return SMALL_MOLECULE_CATEGORY


def get_uberon_category(uberon_term_id: str) -> str:
    """
    Return appropriate Biolink category for UBERON anatomical terms.

    UBERON is an anatomy ontology, so all terms should be AnatomicalEntity.
    This handles edge cases where UBERON terms have multiple categories.

    Args:
    ----
        uberon_term_id: UBERON term ID (e.g., "UBERON:0000178")

    Returns:
    -------
        Biolink category string (always AnatomicalEntity for UBERON)

    Examples:
    --------
        >>> get_uberon_category("UBERON:0000178")  # blood
        'biolink:AnatomicalEntity'

        >>> get_uberon_category("UBERON:0001970")  # bile
        'biolink:AnatomicalEntity'

    """
    from kg_microbe.transform_utils.constants import ANATOMICAL_ENTITY_CATEGORY

    # All UBERON terms are anatomical entities
    return ANATOMICAL_ENTITY_CATEGORY


def get_ncbitaxon_category(ncbitaxon_id: str) -> str:
    """
    Return appropriate Biolink category for NCBITaxon terms.

    NCBITaxon is a taxonomy, so all terms should be OrganismTaxon.
    This handles edge cases like NCBITaxon:1 (root).

    Args:
    ----
        ncbitaxon_id: NCBITaxon term ID (e.g., "NCBITaxon:1")

    Returns:
    -------
        Biolink category string (always OrganismTaxon for NCBITaxon)

    Examples:
    --------
        >>> get_ncbitaxon_category("NCBITaxon:1")  # root
        'biolink:OrganismTaxon'

    """
    from kg_microbe.transform_utils.constants import NCBI_CATEGORY

    # All NCBITaxon terms are organism taxa
    return NCBI_CATEGORY


def replace_deprecated_categories(category_str: str) -> str:
    """
    Replace deprecated Biolink categories with current equivalents.

    Deprecated categories:
    - biolink:ChemicalSubstance → biolink:SmallMolecule

    Args:
    ----
        category_str: Category string (may be pipe-delimited)

    Returns:
    -------
        Updated category string with deprecated categories replaced

    Examples:
    --------
        >>> replace_deprecated_categories("biolink:ChemicalSubstance")
        'biolink:SmallMolecule'

        >>> replace_deprecated_categories("biolink:ChemicalEntity|biolink:ChemicalSubstance")
        'biolink:ChemicalEntity|biolink:SmallMolecule'

    """
    if not category_str or category_str == "":
        return category_str

    # Map of deprecated → current categories
    deprecated_map = {
        "biolink:ChemicalSubstance": "biolink:SmallMolecule",
    }

    # Replace each deprecated category
    updated_category = category_str
    for old_cat, new_cat in deprecated_map.items():
        updated_category = updated_category.replace(old_cat, new_cat)

    return updated_category
