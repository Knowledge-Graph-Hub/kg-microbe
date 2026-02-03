"""Biolink Model hierarchy utility for category specificity comparison."""

import re
from collections import deque
from pathlib import Path
from typing import Dict, List, Optional, Union

import yaml

from kg_microbe.transform_utils.constants import BIOLINK_MODEL_FILE


class BiolinkHierarchy:

    """
    Utility for Biolink Model category hierarchy operations.

    Loads biolink-model.yaml and provides methods to:
    - Determine most specific category from a list
    - Check if category A is more specific than category B
    - Traverse hierarchy to find ancestors

    Example usage:
        >>> hierarchy = BiolinkHierarchy()
        >>> categories = ["biolink:ChemicalEntity", "biolink:SmallMolecule"]
        >>> result = hierarchy.get_most_specific_category(categories)
        >>> print(result)
        biolink:SmallMolecule
    """

    def __init__(self, biolink_yaml_path: Union[str, Path, None] = None) -> None:
        """
        Load Biolink Model schema.

        Args:
            biolink_yaml_path: Path to biolink-model.yaml file.
                              If None, uses BIOLINK_MODEL_FILE from constants.

        """
        if biolink_yaml_path is None:
            yaml_path = BIOLINK_MODEL_FILE
        else:
            yaml_path = Path(biolink_yaml_path)
        if not yaml_path.exists():
            raise FileNotFoundError(f"Biolink Model YAML not found at {biolink_yaml_path}")

        with open(yaml_path) as f:
            self.schema = yaml.safe_load(f)

        self.classes = self.schema.get("classes", {})
        self._build_hierarchy()

    @staticmethod
    def _pascal_to_snake(name: str) -> str:
        """
        Convert PascalCase to lowercase with spaces.

        Args:
            name: PascalCase string (e.g., "ChemicalEntity", "SmallMolecule")

        Returns:
            Lowercase string with spaces (e.g., "chemical entity", "small molecule")

        """
        # Insert space before uppercase letters (except the first one)
        spaced = re.sub(r"(?<!^)(?=[A-Z])", " ", name)
        return spaced.lower()

    @staticmethod
    def _snake_to_pascal(name: str) -> str:
        """
        Convert lowercase with spaces to PascalCase.

        Args:
            name: Lowercase string with spaces (e.g., "chemical entity", "small molecule")

        Returns:
            PascalCase string (e.g., "ChemicalEntity", "SmallMolecule")

        """
        return "".join(word.capitalize() for word in name.split())

    def _build_hierarchy(self) -> None:
        """Build parent-child mapping and depth map."""
        self.parent_map: Dict[str, str] = {}  # child -> parent
        self.children_map: Dict[str, List[str]] = {}  # parent -> [children]
        self.depth_map: Dict[str, int] = {}  # category -> depth from root

        for class_name, class_def in self.classes.items():
            parent = class_def.get("is_a")
            if parent:
                self.parent_map[class_name] = parent
                if parent not in self.children_map:
                    self.children_map[parent] = []
                self.children_map[parent].append(class_name)

        # Calculate depths via BFS from NamedThing root
        self._calculate_depths()

    def _calculate_depths(self) -> None:
        """Calculate hierarchy depth for each category via breadth-first search."""
        queue = deque([("named thing", 0)])

        while queue:
            category, depth = queue.popleft()
            self.depth_map[category] = depth

            for child in self.children_map.get(category, []):
                queue.append((child, depth + 1))

    def get_most_specific_category(self, categories: List[str]) -> str:
        """
        Return the most specific (deepest in hierarchy) category.

        Args:
            categories: List of category strings (e.g., ["ChemicalEntity", "SmallMolecule"])
                       Can include or omit "biolink:" prefix

        Returns:
            Most specific category string with "biolink:" prefix

        Example:
            >>> hierarchy = BiolinkHierarchy()
            >>> hierarchy.get_most_specific_category(["biolink:ChemicalEntity", "biolink:SmallMolecule"])
            'biolink:SmallMolecule'

        """
        if not categories:
            return None

        # Remove biolink: prefix and convert to YAML format (lowercase with spaces)
        clean_cats = []
        original_map = {}  # Map YAML format back to original format
        for c in categories:
            original = c
            c_no_prefix = c.replace("biolink:", "")
            yaml_format = self._pascal_to_snake(c_no_prefix)
            clean_cats.append(yaml_format)
            original_map[yaml_format] = original

        # Filter to only valid Biolink categories
        valid_cats = [c for c in clean_cats if c in self.depth_map]

        if not valid_cats:
            # Fallback: return first category if none are in Biolink hierarchy
            return categories[0]

        # Return category with maximum depth (most specific)
        most_specific_yaml = max(valid_cats, key=lambda c: self.depth_map[c])

        # Convert back to PascalCase and restore biolink: prefix
        most_specific_pascal = self._snake_to_pascal(most_specific_yaml)
        return f"biolink:{most_specific_pascal}"

    def is_more_specific(self, category_a: str, category_b: str) -> bool:
        """
        Check if category_a is more specific than category_b.

        Returns True if category_a is a descendant of category_b
        (i.e., category_a has greater depth in the hierarchy).

        Args:
            category_a: First category (can include or omit "biolink:" prefix)
            category_b: Second category (can include or omit "biolink:" prefix)

        Returns:
            True if category_a is more specific (deeper) than category_b

        Example:
            >>> hierarchy = BiolinkHierarchy()
            >>> hierarchy.is_more_specific("biolink:SmallMolecule", "biolink:ChemicalEntity")
            True

        """
        clean_a = self._pascal_to_snake(category_a.replace("biolink:", ""))
        clean_b = self._pascal_to_snake(category_b.replace("biolink:", ""))

        if clean_a not in self.depth_map or clean_b not in self.depth_map:
            return False

        return self.depth_map[clean_a] > self.depth_map[clean_b]

    def get_ancestors(self, category: str) -> List[str]:
        """
        Get all ancestor categories up to NamedThing root.

        Args:
            category: Category string (can include or omit "biolink:" prefix)

        Returns:
            List of ancestor categories with "biolink:" prefix, ordered from
            immediate parent to root (NamedThing)

        Example:
            >>> hierarchy = BiolinkHierarchy()
            >>> hierarchy.get_ancestors("biolink:SmallMolecule")
            ['biolink:ChemicalEntity', 'biolink:NamedThing']

        """
        clean_cat = self._pascal_to_snake(category.replace("biolink:", ""))
        ancestors = []
        current = clean_cat

        while current in self.parent_map:
            parent = self.parent_map[current]
            # Convert back to PascalCase
            parent_pascal = self._snake_to_pascal(parent)
            ancestors.append(f"biolink:{parent_pascal}")
            current = parent

        return ancestors

    def get_depth(self, category: str) -> Optional[int]:
        """
        Get the depth of a category in the hierarchy.

        Args:
            category: Category string (can include or omit "biolink:" prefix)

        Returns:
            Depth as integer (0 = NamedThing root), or None if category not found

        Example:
            >>> hierarchy = BiolinkHierarchy()
            >>> hierarchy.get_depth("biolink:NamedThing")
            0
            >>> hierarchy.get_depth("biolink:ChemicalEntity")
            2
            >>> hierarchy.get_depth("biolink:SmallMolecule")
            3

        """
        clean_cat = self._pascal_to_snake(category.replace("biolink:", ""))
        return self.depth_map.get(clean_cat)
