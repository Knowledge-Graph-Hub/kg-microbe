"""Utilities for handling mapping files from remote sources."""

import csv
import json
from typing import Dict, List, Optional

import curies
import requests

from kg_microbe.transform_utils.constants import PREFIXMAP_JSON_FILEPATH

# remote URL location in metpo GitHub repository for METPO classes and properties
# sheets/ROBOT templates respectively, which will be used as the source of METPO mappings
METPO_CLASSES_ROBOT_TEMPLATE_URL = "https://raw.githubusercontent.com/berkeleybop/metpo/refs/tags/2025-11-24/src/templates/metpo_sheet.tsv"
METPO_PROPERTIES_ROBOT_TEMPLATE_URL = "https://raw.githubusercontent.com/berkeleybop/metpo/refs/tags/2025-11-24/src/templates/metpo-properties.tsv"


def uri_to_curie(uri: str) -> str:
    """
    Convert a URI to a CURIE using a `curies` library specified custom Prefix Map.

    It also checks if the input uri is already a CURIE, in which case it returns
    the CURIE value as-is.

    >>> uri_to_curie("https://w3id.org/metpo/1000059")
    'METPO:1000059'

    >>> uri_to_curie("METPO:1000059")
    'METPO:1000059'

    :param uri: The URI to convert, or a CURIE that's already in the correct format
    :return: The CURIE representation of the URI, or the original input if it's already a CURIE
    """
    with open(PREFIXMAP_JSON_FILEPATH, "r") as f:
        prefix_map = json.load(f)

    converter = curies.Converter.from_prefix_map(prefix_map)

    # If it's already a CURIE, return the string as-is
    if converter.is_curie(uri):
        return uri

    curie = converter.compress(uri)

    return curie if curie is not None else uri


class MetpoTreeNode:

    """
    Represents a node in the METPO class hierarchy tree.

    For example, consider METPO:1000602
    The node would have:
        iri = "METPO:1000602"
        label = "aerobic"
        synonyms = ["aerobic", "aerobe", "Ox_aerobe"]
        bacdive_json_paths = []
        biolink_equivalent = ""
        children = []
        parent = {'iri': 'METPO:1000601', 'label': 'oxygen preference', ...}
    """

    def __init__(
        self,
        iri: str,
        label: str,
        synonyms: List[str] = None,
        biolink_equivalent: str = None,
        bacdive_json_paths: List[str] = None,
    ):
        """
        Initialize a MetpoTreeNode.

        :param iri: The IRI or CURIE of the node
        :param label: The human-readable label of the node
        :param synonyms: List of synonyms for the node, defaults to None
        :param biolink_equivalent: Biolink equivalent IRI if available, defaults to None
        :param bacdive_json_paths: List of JSON paths for extracting values from BacDive records, defaults to None
        """
        self.iri = iri  # specified as CURIEs in the METPO classes/properties sheets
        self.label = label  # human-readable label
        self.synonyms = (
            synonyms or []
        )  # synonyms from different data sources (ex. Madin et al, BacDive) corresponding to this class
        self.biolink_equivalent = biolink_equivalent  # biolink equivalent URL if available
        self.bacdive_json_paths = (
            bacdive_json_paths or []
        )  # JSON paths for extracting values from BacDive records
        self.children: List["MetpoTreeNode"] = []  # list of child nodes
        self.parent: Optional["MetpoTreeNode"] = None  # reference to parent node

    def add_child(self, child: "MetpoTreeNode"):
        """Add a child node and set its parent."""
        child.parent = self
        self.children.append(child)

    def find_biolink_equivalent_parent(self) -> Optional[str]:
        """
        Find the closest parent (including self) that has a biolink equivalent.

        (value populated in the `biolink equivalent` column).
        """
        current = self
        while current is not None:
            if current.biolink_equivalent:
                return current.biolink_equivalent
            current = current.parent
        return None

    def find_synonym_node(self, synonym: str) -> Optional["MetpoTreeNode"]:
        """Find the node that contains the given synonym."""
        if synonym in self.synonyms:
            return self

        for child in self.children:
            result = child.find_synonym_node(synonym)
            if result:
                return result

        return None


def _build_metpo_tree() -> Dict[str, MetpoTreeNode]:
    """
    Build a tree structure from METPO classes based on parent-child relationships.

    For example, consider the classes METPO:1000602 and METPO:1000603, which are
    classes for "aerobic" and "anaerobic" microbial oxygen preference traits respectively.
    Both have a parent class METPO:1000601 ("oxygen preference"). The "oxygen preference"
    class further has a parent METPO:1000059 ("phenotype"), which also has a parent
    METPO:1000188 ("quality").

    The METPO tree structure would look like this:
        METPO:1000188 (quality)
            └── METPO:1000059 (phenotype)
                └── METPO:1000601 (oxygen preference)
                    ├── METPO:1000602 (aerobic)
                    └── METPO:1000603 (anaerobic)

    :return: Dictionary mapping IRIs/CURIEs to MetpoTreeNode objects
    """
    try:
        response = requests.get(METPO_CLASSES_ROBOT_TEMPLATE_URL, timeout=30)
        response.raise_for_status()

        if not response.text.strip():
            raise ValueError("The contents of the metpo sheet file are empty or invalid.")

        lines = response.text.splitlines()
        reader = csv.DictReader(lines[2:], fieldnames=lines[0].split("\t"), delimiter="\t")

        # first pass: create all nodes
        nodes = {}
        for row in reader:
            iri = row.get("ID", "").strip()  # now this is a CURIE like METPO:1000059
            label = row.get("label", "").strip()
            madin_synonym = row.get("madin synonym or field", "").strip()
            bacdive_synonym = row.get("bacdive keyword synonym", "").strip()
            biolink_equivalent = row.get("biolink equivalent", "").strip()

            if iri and label:
                # handle pipe-separated synonyms from madin column
                synonyms = []
                if madin_synonym:
                    synonyms.extend([s.strip() for s in madin_synonym.split("|") if s.strip()])

                # handle bacdive column: distinguish between JSON paths and literal values
                bacdive_json_paths = []
                if bacdive_synonym:
                    bacdive_items = [s.strip() for s in bacdive_synonym.split("|") if s.strip()]
                    for item in bacdive_items:
                        # Check if it's a JSON path (contains a dot)
                        if "." in item:
                            bacdive_json_paths.append(item)
                        else:
                            # It's a literal value synonym
                            synonyms.append(item)

                nodes[iri] = MetpoTreeNode(
                    iri, label, synonyms, biolink_equivalent, bacdive_json_paths
                )

        # second pass: establish parent-child relationships
        lines = response.text.splitlines()
        reader = csv.DictReader(lines[2:], fieldnames=lines[0].split("\t"), delimiter="\t")

        roots = set(nodes.keys())

        for row in reader:
            iri = row.get("ID", "").strip()
            parent_classes = row.get("parent classes (one strongly preferred)", "").strip()
            # Handle pipe-separated parent classes, take the first one
            parent_label = parent_classes.split("|")[0].strip() if parent_classes else ""

            if iri in nodes and parent_label:
                # find parent by label since parent class column contains labels, not CURIEs
                parent_iri = None
                for candidate_iri, candidate_node in nodes.items():
                    if candidate_node.label == parent_label:
                        parent_iri = candidate_iri
                        break

                if parent_iri and parent_iri in nodes:
                    nodes[parent_iri].add_child(nodes[iri])
                    roots.discard(iri)

        return nodes

    except requests.exceptions.HTTPError as e:
        raise requests.exceptions.HTTPError(
            f"Please ensure the METPO sheet URL is accessible: {e}"
        ) from e


def _load_metpo_properties() -> Dict[str, Dict[str, str]]:
    """
    Load METPO properties and create a mapping from RANGE class labels to property info.

    For example, from the METPO properties sheet, we can extract:
    | ID            | label         | RANGE     | biolink equivalent                                    |
    |---------------|---------------|-----------|-------------------------------------------------------|
    | METPO:2000102 | has phenotype | phenotype | https://biolink.github.io/biolink-model/has_phenotype |

    This would create a mapping that looks like below:
    {
        "phenotype": {
            "label": "has phenotype",
            "biolink_equivalent": "https://biolink.github.io/biolink-model/has_phenotype"
        },
        ...
    }

    :return: Dictionary mapping RANGE class labels to property info (label and biolink_equivalent)
    """
    try:
        response = requests.get(METPO_PROPERTIES_ROBOT_TEMPLATE_URL, timeout=30)
        response.raise_for_status()

        if not response.text.strip():
            raise ValueError("The contents of the metpo properties file are empty or invalid.")

        lines = response.text.splitlines()
        reader = csv.DictReader(lines[2:], fieldnames=lines[0].split("\t"), delimiter="\t")

        range_to_predicate = {}
        for row in reader:
            range_class = row.get("RANGE", "").strip()
            label = row.get("label", "").strip()
            biolink_equivalent = row.get("biolink equivalent", "").strip()

            if range_class and label:
                # Map RANGE class labels to property info
                range_to_predicate[range_class] = {
                    "label": label,
                    "biolink_equivalent": biolink_equivalent,
                }

        return range_to_predicate

    except requests.exceptions.HTTPError as e:
        raise requests.exceptions.HTTPError(
            f"Please ensure the METPO properties URL is accessible: {e}"
        ) from e


def load_metpo_mappings(synonym_column: str) -> Dict[str, Dict[str, str]]:
    """
    Load METPO mappings from METPO classes ROBOT template file for a given synonym column.

    Implements the logic to find appropriate _predicates_ by traversing the parent hierarchy to find
    `biolink equivalent` and then mapping to properties.

    For ambiguous synonyms (e.g., "yes" or "no" that appear under multiple parent concepts),
    compound keys are created using the parent label as context (e.g., "motility.yes", "sporulation.yes").

    :param synonym_column: The column name to use for synonyms
        (e.g., 'bacdive keyword synonym', 'madin synonym or field', etc.)
    :return: Dictionary mapping synonyms to METPO curie, label, and predicate information.
        Format: {synonym: {'curie': metpo_curie, 'label': metpo_label, 'predicate': predicate_label}}
        For ambiguous values, also includes compound keys like "parent.synonym"
    :rtype: Dict[str, Dict[str, str]]
    :raises requests.exceptions.HTTPError: If unable to fetch from remote URL
    :raises ValueError: If the response content is empty or invalid
    """
    mappings = {}
    synonym_to_parents = {}  # Track which parents each synonym appears under

    try:
        nodes = _build_metpo_tree()  # build the METPO tree structure

        range_to_predicate = (
            _load_metpo_properties()
        )  # load properties mapping (RANGE class label -> predicate label)

        # load the METPO classes ROBOT template file/sheet
        response = requests.get(METPO_CLASSES_ROBOT_TEMPLATE_URL, timeout=30)
        response.raise_for_status()

        if not response.text.strip():
            raise ValueError("The contents of the file at the remote URL are empty or invalid.")

        lines = response.text.splitlines()
        reader = csv.DictReader(lines[2:], fieldnames=lines[0].split("\t"), delimiter="\t")

        # First pass: collect all synonym -> parent relationships
        temp_mappings = []
        for row in reader:
            synonym = row.get(synonym_column, "").strip()
            metpo_curie = row.get("ID", "").strip()  # already a CURIE
            metpo_label = row.get("label", "").strip()
            biolink_equivalent = row.get("biolink equivalent", "").strip()

            if synonym and metpo_curie:
                # Find the appropriate predicate and category using tree traversal logic:
                # 1. find the closest parent with `biolink equivalent`
                # 2. use the parent's label to find matching RANGE in properties sheet
                # 3. get the predicate info for that RANGE
                # 4. use the parent's label as the category
                predicate_label = "has phenotype"  # default
                predicate_biolink_equivalent = ""  # default empty
                inferred_category = ""  # default empty, will be inferred from parent
                immediate_parent_label = None  # Track the immediate parent for compound keys

                if metpo_curie in nodes:
                    node = nodes[metpo_curie]
                    # Get immediate parent label for compound key creation
                    if node.parent:
                        immediate_parent_label = node.parent.label

                    # find the parent node that has a `biolink equivalent`
                    current = node
                    while current is not None:
                        if current.biolink_equivalent:
                            # use the parent's biolink_equivalent URL as the category
                            parent_label = current.label
                            inferred_category = (
                                current.biolink_equivalent
                            )  # use parent's biolink_equivalent URL as category
                            if parent_label in range_to_predicate:
                                predicate_label = range_to_predicate[parent_label]["label"]
                                predicate_biolink_equivalent = range_to_predicate[parent_label][
                                    "biolink_equivalent"
                                ]
                            break
                        current = current.parent

                # handle pipe-separated synonyms
                synonyms = [s.strip() for s in synonym.split("|")]

                mapping_data = {
                    "curie": metpo_curie,
                    "label": metpo_label,
                    "predicate": predicate_label,
                    "predicate_biolink_equivalent": predicate_biolink_equivalent,
                    "biolink_equivalent": biolink_equivalent,
                    "inferred_category": inferred_category,
                }

                for syn in synonyms:
                    if syn:  # only add non-empty synonyms
                        # Track parent relationships for ambiguity detection
                        if syn not in synonym_to_parents:
                            synonym_to_parents[syn] = []
                        if immediate_parent_label:
                            synonym_to_parents[syn].append(immediate_parent_label)

                        temp_mappings.append((syn, immediate_parent_label, mapping_data))

        # Second pass: create mappings with compound keys for ambiguous synonyms
        for syn, parent_label, mapping_data in temp_mappings:
            # Check if this synonym is ambiguous (appears under multiple parents)
            is_ambiguous = len(synonym_to_parents.get(syn, [])) > 1

            if is_ambiguous and parent_label:
                # Create compound key: "parent.synonym" (e.g., "motility.yes")
                compound_key = f"{parent_label}.{syn}"
                mappings[compound_key] = mapping_data

            # Always add the simple key (last occurrence wins for ambiguous cases)
            mappings[syn] = mapping_data

        return mappings

    except requests.exceptions.HTTPError as e:
        raise requests.exceptions.HTTPError(
            f"Please ensure the remote URL is accessible: {e}"
        ) from e


def load_metpo_metabolite_utilization_mappings() -> Dict[str, Dict[str, str]]:
    """
    Load METPO metabolite utilization mappings from the METPO properties sheet.

    This function parses the "synonym property and value TUPLES" and "assay outcome" columns
    to extract mappings for metabolite utilization predicates. The mappings are used to convert
    BacDive's "kind of utilization tested" values into appropriate METPO predicates.

    For example, from the rows:
    | ID            | label            | synonym property and value TUPLES           | assay outcome |
    |---------------|------------------|---------------------------------------------|---------------|
    | METPO:2000003 | builds acid from | oboInOwl:hasRelatedSynonym 'builds acid from' | +             |
    | METPO:2000028 | does not build acid from | oboInOwl:hasRelatedSynonym 'builds acid from' | -     |

    This creates mappings:
    {
        'builds acid from': {
            '+': {'curie': 'METPO:2000003', 'label': 'builds acid from'},
            '-': {'curie': 'METPO:2000028', 'label': 'does not build acid from'}
        },
        ...
    }

    The sign (+ or -) is now directly read from the "assay outcome" column.

    :return: Dictionary mapping utilization type synonyms to sign-based predicate info
    :rtype: Dict[str, Dict[str, Dict[str, str]]]
    :raises requests.exceptions.HTTPError: If unable to fetch from remote URL
    :raises ValueError: If the response content is empty or invalid
    """
    try:
        response = requests.get(METPO_PROPERTIES_ROBOT_TEMPLATE_URL, timeout=30)
        response.raise_for_status()

        if not response.text.strip():
            raise ValueError("The contents of the METPO properties file are empty or invalid.")

        lines = response.text.splitlines()
        reader = csv.DictReader(lines[2:], fieldnames=lines[0].split("\t"), delimiter="\t")

        mappings = {}
        for row in reader:
            # Note: The header has a leading space for ID column (" ID")
            metpo_id = row.get(" ID", "").strip() or row.get("ID", "").strip()
            label = row.get("label", "").strip()
            synonym_tuples = row.get("synonym property and value TUPLES", "").strip()
            assay_outcome = row.get("assay outcome", "").strip()

            # Skip rows without required fields
            if not (metpo_id and label and synonym_tuples and assay_outcome):
                continue

            # Parse synonym tuples - format: "oboInOwl:hasRelatedSynonym 'synonym_value'"
            # Can have multiple tuples separated by pipes
            tuples = [t.strip() for t in synonym_tuples.split("|") if t.strip()]

            for tuple_str in tuples:
                # Extract the synonym from the tuple (text between quotes)
                import re

                match = re.search(r"'([^']+)'", tuple_str)
                if match:
                    synonym = match.group(1)

                    # Use the sign directly from the "assay outcome" column
                    sign = assay_outcome

                    # Initialize the synonym entry if not present
                    if synonym not in mappings:
                        mappings[synonym] = {}

                    # Add the mapping for this sign
                    mappings[synonym][sign] = {"curie": metpo_id, "label": label}

        return mappings

    except requests.exceptions.HTTPError as e:
        raise requests.exceptions.HTTPError(
            f"Please ensure the METPO properties URL is accessible: {e}"
        ) from e


def load_metpo_metabolite_production_mappings() -> Dict[str, Dict[str, str]]:
    """
    Load METPO metabolite production mappings from the METPO properties sheet.

    This function specifically looks for rows with the synonym 'produces' and maps
    BacDive's "production" values ("yes"/"no") to METPO predicates based on the
    "assay outcome" column.

    For example, from the rows:
    | ID            | label            | synonym property and value TUPLES           | assay outcome |
    |---------------|------------------|---------------------------------------------|---------------|
    | METPO:2000202 | produces         | oboInOwl:hasRelatedSynonym 'produces'       | +             |
    | METPO:2000222 | does not produce | oboInOwl:hasRelatedSynonym 'produces'       | -             |

    This creates mappings:
    {
        'yes': {'curie': 'METPO:2000202', 'label': 'produces'},
        'no': {'curie': 'METPO:2000222', 'label': 'does not produce'}
    }

    The mapping is:
    - "assay outcome" = "+" maps to "production" = "yes"
    - "assay outcome" = "-" maps to "production" = "no"

    :return: Dictionary mapping production values ("yes"/"no") to METPO predicate info
    :rtype: Dict[str, Dict[str, str]]
    :raises requests.exceptions.HTTPError: If unable to fetch from remote URL
    :raises ValueError: If the response content is empty or invalid
    """
    try:
        response = requests.get(METPO_PROPERTIES_ROBOT_TEMPLATE_URL, timeout=30)
        response.raise_for_status()

        if not response.text.strip():
            raise ValueError("The contents of the METPO properties file are empty or invalid.")

        lines = response.text.splitlines()
        reader = csv.DictReader(lines[2:], fieldnames=lines[0].split("\t"), delimiter="\t")

        mappings = {}
        for row in reader:
            # Note: The header has a leading space for ID column (" ID")
            metpo_id = row.get(" ID", "").strip() or row.get("ID", "").strip()
            label = row.get("label", "").strip()
            synonym_tuples = row.get("synonym property and value TUPLES", "").strip()
            assay_outcome = row.get("assay outcome", "").strip()

            # Skip rows without required fields
            if not (metpo_id and label and synonym_tuples and assay_outcome):
                continue

            # Only process rows with 'produces' synonym
            if "'produces'" in synonym_tuples:
                # Map assay outcome (+/-) to production value (yes/no)
                if assay_outcome == "+":
                    production_value = "yes"
                elif assay_outcome == "-":
                    production_value = "no"
                else:
                    continue

                mappings[production_value] = {"curie": metpo_id, "label": label}

        return mappings

    except requests.exceptions.HTTPError as e:
        raise requests.exceptions.HTTPError(
            f"Please ensure the METPO properties URL is accessible: {e}"
        ) from e


def load_metpo_enzyme_mappings() -> Dict[str, Dict[str, str]]:
    """
    Load METPO enzyme activity mappings from the METPO properties sheet.

    This function looks for rows with the synonym 'Physiology and metabolism.enzymes.[].activity'
    and maps BacDive's enzyme "activity" values ("+"/"-") to METPO predicates based on the
    "assay outcome" column.

    For example, from the rows:
    | ID            | label                      | synonym TUPLES                | assay outcome |
    |---------------|----------------------------|-------------------------------|---------------|
    | METPO:2000302 | shows activity of          | hasRelatedSynonym 'Phys...[]' | +             |
    | METPO:2000303 | does not show activity of  | hasRelatedSynonym 'Phys...[]' | -             |

    This creates mappings:
    {
        '+': {'curie': 'METPO:2000302', 'label': 'shows activity of'},
        '-': {'curie': 'METPO:2000303', 'label': 'does not show activity of'}
    }

    :return: Dictionary mapping activity values ("+"/"-") to METPO predicate info
    :rtype: Dict[str, Dict[str, str]]
    :raises requests.exceptions.HTTPError: If unable to fetch from remote URL
    :raises ValueError: If the response content is empty or invalid
    """
    try:
        response = requests.get(METPO_PROPERTIES_ROBOT_TEMPLATE_URL, timeout=30)
        response.raise_for_status()

        if not response.text.strip():
            raise ValueError("The contents of the METPO properties file are empty or invalid.")

        lines = response.text.splitlines()
        reader = csv.DictReader(lines[2:], fieldnames=lines[0].split("\t"), delimiter="\t")

        mappings = {}
        for row in reader:
            # Note: The header has a leading space for ID column (" ID")
            metpo_id = row.get(" ID", "").strip() or row.get("ID", "").strip()
            label = row.get("label", "").strip()
            synonym_tuples = row.get("synonym property and value TUPLES", "").strip()
            assay_outcome = row.get("assay outcome", "").strip()

            # Skip rows without required fields
            if not (metpo_id and label and synonym_tuples and assay_outcome):
                continue

            # Only process rows with enzyme activity synonym
            if "'Physiology and metabolism.enzymes.[].activity'" in synonym_tuples:
                # Map assay outcome directly to activity value
                mappings[assay_outcome] = {"curie": metpo_id, "label": label}

        return mappings

    except requests.exceptions.HTTPError as e:
        raise requests.exceptions.HTTPError(
            f"Please ensure the METPO properties URL is accessible: {e}"
        ) from e
