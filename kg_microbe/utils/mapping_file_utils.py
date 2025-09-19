"""Utilities for handling mapping files from remote sources."""
import csv
import json
from typing import Dict, List, Optional

import curies
import requests

from kg_microbe.transform_utils.constants import PREFIXMAP_JSON_FILEPATH

# remote URL location in metpo GitHub repository for ROBOT template
# which will be used as the source of METPO mappings
METPO_ROBOT_TEMPLATE_URL = "https://raw.githubusercontent.com/berkeleybop/metpo/refs/heads/main/src/templates/metpo_sheet.tsv"
METPO_PROPERTIES_URL = "https://raw.githubusercontent.com/berkeleybop/metpo/refs/heads/main/src/templates/metpo-properties.tsv"


def uri_to_curie(uri: str) -> str:
    """
    Convert a URI to a CURIE using custom prefix map.

    :param uri: The URI to convert
    :return: The CURIE representation of the URI, or the original URI if conversion fails
    """
    with open(PREFIXMAP_JSON_FILEPATH, 'r') as f:
        prefix_map = json.load(f)

    converter = curies.Converter.from_prefix_map(prefix_map)
    curie = converter.compress(uri)

    return curie if curie is not None else uri


class MetpoTreeNode:
    """
    Represents a node in the METPO class hierarchy tree.
    """
    def __init__(self, iri: str, label: str, synonyms: List[str] = None):
        self.iri = iri
        self.label = label
        self.synonyms = synonyms or []
        self.children: List['MetpoTreeNode'] = []
        self.parent: Optional['MetpoTreeNode'] = None
    
    def add_child(self, child: 'MetpoTreeNode'):
        """Add a child node and set its parent."""
        child.parent = self
        self.children.append(child)
    
    def get_root_class_iri(self) -> str:
        """Get the IRI of the root class by traversing up the tree."""
        current = self
        while current.parent is not None:
            current = current.parent
        return current.iri
    
    def find_synonym_node(self, synonym: str) -> Optional['MetpoTreeNode']:
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
    
    :return: Dictionary mapping IRIs to MetpoTreeNode objects
    """
    try:
        response = requests.get(METPO_ROBOT_TEMPLATE_URL, timeout=30)
        response.raise_for_status()
        
        if not response.text.strip():
            raise ValueError("The contents of the metpo sheet file are empty or invalid.")
        
        lines = response.text.splitlines()
        reader = csv.DictReader(lines[2:], fieldnames=lines[0].split('\t'), delimiter='\t')
        
        # First pass: create all nodes
        nodes = {}
        for row in reader:
            iri = row.get(' ID', '').strip()
            label = row.get('label', '').strip()
            madin_synonym = row.get('madin synonym or field', '').strip()
            
            if iri and label:
                # Handle pipe-separated synonyms
                if madin_synonym:
                    synonyms = [s.strip() for s in madin_synonym.split('|') if s.strip()]
                else:
                    synonyms = []
                nodes[iri] = MetpoTreeNode(iri, label, synonyms)
        
        # Second pass: establish parent-child relationships
        lines = response.text.splitlines()
        reader = csv.DictReader(lines[2:], fieldnames=lines[0].split('\t'), delimiter='\t')
        
        roots = set(nodes.keys())
        
        for row in reader:
            iri = row.get(' ID', '').strip()
            parent_iri = row.get('parent class', '').strip()
            
            if iri in nodes and parent_iri and parent_iri in nodes:
                nodes[parent_iri].add_child(nodes[iri])
                roots.discard(iri)
        
        return nodes
        
    except requests.exceptions.HTTPError as e:
        raise requests.exceptions.HTTPError(f"Please ensure the METPO sheet URL is accessible: {e}") from e


def _load_metpo_properties() -> Dict[str, str]:
    """
    Load METPO properties and create a mapping from RANGE class IRI to property label.
    
    :return: Dictionary mapping RANGE IRIs to property labels
    """
    try:
        response = requests.get(METPO_PROPERTIES_URL, timeout=30)
        response.raise_for_status()
        
        if not response.text.strip():
            raise ValueError("The contents of the metpo properties file are empty or invalid.")
        
        lines = response.text.splitlines()
        reader = csv.DictReader(lines[2:], fieldnames=lines[0].split('\t'), delimiter='\t')
        
        range_to_label = {}
        for row in reader:
            range_iri = row.get('RANGE', '').strip()
            label = row.get('label', '').strip()
            
            if range_iri and label:
                range_to_label[range_iri] = label
        
        return range_to_label
        
    except requests.exceptions.HTTPError as e:
        raise requests.exceptions.HTTPError(f"Please ensure the METPO properties URL is accessible: {e}") from e


def load_metpo_mappings(synonym_column: str) -> Dict[str, Dict[str, str]]:
    """
    Load METPO mappings from ROBOT template file (in metpo repository) for a specific synonym column.
    Now supports building tree structure and finding appropriate predicates.

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
        
        # Load properties mapping
        range_to_predicate = _load_metpo_properties()
        
        # Load the main sheet for synonyms
        response = requests.get(METPO_ROBOT_TEMPLATE_URL, timeout=30)
        response.raise_for_status()

        if not response.text.strip():
            raise ValueError("The contents of the file at the remote URL are empty or invalid.")

        lines = response.text.splitlines()
        reader = csv.DictReader(lines[2:], fieldnames=lines[0].split('\t'), delimiter='\t')
        
        for row in reader:
            synonym = row.get(synonym_column, '').strip()
            metpo_iri = row.get(' ID', '').strip()
            metpo_label = row.get('label', '').strip()

            if synonym and metpo_iri:
                # Convert IRI to CURIE using the uri_to_curie function
                metpo_curie = uri_to_curie(metpo_iri)

                # Find the appropriate predicate
                predicate_label = "has phenotype"  # default
                if metpo_iri in nodes:
                    node = nodes[metpo_iri]
                    root_iri = node.get_root_class_iri()
                    if root_iri in range_to_predicate:
                        predicate_label = range_to_predicate[root_iri]

                # Handle pipe-separated synonyms
                synonyms = [s.strip() for s in synonym.split('|')]

                for syn in synonyms:
                    if syn:  # Only add non-empty synonyms
                        mappings[syn] = {
                            'curie': metpo_curie,
                            'label': metpo_label,
                            'predicate': predicate_label
                        }

        return mappings

    except requests.exceptions.HTTPError as e:
        raise requests.exceptions.HTTPError(f"Please ensure the remote URL is accessible: {e}") from e
