"""Utilities for handling mapping files from remote sources."""

import csv
import json
from typing import Dict, List, Optional

import curies
import requests

from kg_microbe.transform_utils.constants import PREFIXMAP_JSON_FILEPATH

# remote URL location in metpo GitHub repository for ROBOT template
# which will be used as the source of METPO mappings
METPO_ROBOT_TEMPLATE_URL = "https://raw.githubusercontent.com/berkeleybop/metpo/refs/tags/2025-09-23/src/templates/metpo_sheet.tsv"
METPO_PROPERTIES_URL = "https://raw.githubusercontent.com/berkeleybop/metpo/refs/tags/2025-09-23/src/templates/metpo-properties.tsv"


def uri_to_curie(uri: str) -> str:
    """
    Convert a URI to a CURIE using custom prefix map.
    Now also handles cases where the input is already a CURIE.

    :param uri: The URI to convert, or a CURIE that's already in the correct format
    :return: The CURIE representation of the URI, or the original input if it's already a CURIE
    """
    # If it's already a CURIE (contains ':' and doesn't start with http), return as-is
    if ":" in uri and not uri.startswith("http"):
        return uri

    with open(PREFIXMAP_JSON_FILEPATH, "r") as f:
        prefix_map = json.load(f)

    converter = curies.Converter.from_prefix_map(prefix_map)
    curie = converter.compress(uri)

    return curie if curie is not None else uri


class MetpoTreeNode:

    """
    Represents a node in the METPO class hierarchy tree.
    """

    def __init__(
        self, iri: str, label: str, synonyms: List[str] = None, biolink_equivalent: str = None
    ):
        self.iri = iri
        self.label = label
        self.synonyms = synonyms or []
        self.biolink_equivalent = biolink_equivalent
        self.children: List["MetpoTreeNode"] = []
        self.parent: Optional["MetpoTreeNode"] = None

    def add_child(self, child: "MetpoTreeNode"):
        """Add a child node and set its parent."""
        child.parent = self
        self.children.append(child)

    def find_biolink_equivalent_parent(self) -> Optional[str]:
        """Find the closest parent (including self) that has a biolink equivalent."""
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

    :return: Dictionary mapping IRIs/CURIEs to MetpoTreeNode objects
    """
    try:
        response = requests.get(METPO_ROBOT_TEMPLATE_URL, timeout=30)
        response.raise_for_status()

        if not response.text.strip():
            raise ValueError("The contents of the metpo sheet file are empty or invalid.")

        lines = response.text.splitlines()
        reader = csv.DictReader(lines[2:], fieldnames=lines[0].split("\t"), delimiter="\t")

        # First pass: create all nodes
        nodes = {}
        for row in reader:
            iri = row.get("ID", "").strip()  # Now this is a CURIE like METPO:1000059
            label = row.get("label", "").strip()
            madin_synonym = row.get("madin synonym or field", "").strip()
            biolink_equivalent = row.get("biolink equivalent", "").strip()

            if iri and label:
                # Handle pipe-separated synonyms
                if madin_synonym:
                    synonyms = [s.strip() for s in madin_synonym.split("|") if s.strip()]
                else:
                    synonyms = []
                nodes[iri] = MetpoTreeNode(iri, label, synonyms, biolink_equivalent)

        # Second pass: establish parent-child relationships
        lines = response.text.splitlines()
        reader = csv.DictReader(lines[2:], fieldnames=lines[0].split("\t"), delimiter="\t")

        roots = set(nodes.keys())

        for row in reader:
            iri = row.get("ID", "").strip()
            parent_label = row.get("parent class", "").strip()

            if iri in nodes and parent_label:
                # Find parent by label since parent class column contains labels, not CURIEs
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

    :return: Dictionary mapping RANGE class labels to property info (label and biolink_equivalent)
    """
    try:
        response = requests.get(METPO_PROPERTIES_URL, timeout=30)
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
    Load METPO mappings from ROBOT template file (in metpo repository) for a specific synonym column.
    Implements the logic to find appropriate predicates by traversing parent hierarchy to find
    biolink equivalent and then mapping to properties.

    :param synonym_column: The column name to use for synonyms (e.g., 'bacdive keyword synonym', 'madin synonym or field', etc.)
    :return: Dictionary mapping synonyms to METPO curie, label, and predicate information.
             Format: {synonym: {'curie': metpo_curie, 'label': metpo_label, 'predicate': predicate_label}}
    :rtype: Dict[str, Dict[str, str]]
    :raises requests.exceptions.HTTPError: If unable to fetch from remote URL
    :raises ValueError: If the response content is empty or invalid
    """
    mappings = {}

    try:
        # Build the METPO tree structure
        nodes = _build_metpo_tree()

        # Load properties mapping (RANGE class label -> predicate label)
        range_to_predicate = _load_metpo_properties()

        # Load the main sheet for synonyms
        response = requests.get(METPO_ROBOT_TEMPLATE_URL, timeout=30)
        response.raise_for_status()

        if not response.text.strip():
            raise ValueError("The contents of the file at the remote URL are empty or invalid.")

        lines = response.text.splitlines()
        reader = csv.DictReader(lines[2:], fieldnames=lines[0].split("\t"), delimiter="\t")

        for row in reader:
            synonym = row.get(synonym_column, "").strip()
            metpo_curie = row.get("ID", "").strip()  # Already a CURIE
            metpo_label = row.get("label", "").strip()
            biolink_equivalent = row.get("biolink equivalent", "").strip()

            if synonym and metpo_curie:
                # Find the appropriate predicate using the logic:
                # 1. Find the closest parent with biolink equivalent
                # 2. Use the parent's label to find matching RANGE in properties sheet
                # 3. Get the predicate info for that RANGE
                predicate_label = "has phenotype"  # default
                predicate_biolink_equivalent = ""  # default empty
                if metpo_curie in nodes:
                    node = nodes[metpo_curie]
                    # Find the parent node that has a biolink equivalent
                    current = node
                    while current is not None:
                        if current.biolink_equivalent:
                            # Use the parent's label to look up in properties RANGE
                            parent_label = current.label
                            if parent_label in range_to_predicate:
                                predicate_label = range_to_predicate[parent_label]["label"]
                                predicate_biolink_equivalent = range_to_predicate[parent_label][
                                    "biolink_equivalent"
                                ]
                            break
                        current = current.parent

                # Handle pipe-separated synonyms
                synonyms = [s.strip() for s in synonym.split("|")]

                for syn in synonyms:
                    if syn:  # Only add non-empty synonyms
                        mappings[syn] = {
                            "curie": metpo_curie,
                            "label": metpo_label,
                            "predicate": predicate_label,
                            "predicate_biolink_equivalent": predicate_biolink_equivalent,
                            "biolink_equivalent": biolink_equivalent,
                        }

        return mappings

    except requests.exceptions.HTTPError as e:
        raise requests.exceptions.HTTPError(
            f"Please ensure the remote URL is accessible: {e}"
        ) from e
