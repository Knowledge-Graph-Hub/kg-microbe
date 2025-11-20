"""Utility functions for COG transform."""

import csv
import logging
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


def parse_cog_definitions(def_file: Path) -> Dict[str, Dict[str, str]]:
    """
    Parse COG definitions file (cog-24.def.tab).

    :param def_file: Path to cog-24.def.tab file
    :return: Dictionary mapping COG ID to definition data
    """
    cog_defs = {}

    if not def_file.exists():
        logger.error(f"COG definitions file not found: {def_file}")
        return cog_defs

    with open(def_file, "r") as f:
        reader = csv.reader(f, delimiter="\t")

        for row in reader:
            # Skip empty lines
            if not row or len(row) < 3:
                continue

            # Columns: COG_ID, Functional_Category, COG_Name, Gene_Name, Pathway, PMID, PDB
            cog_id = row[0].strip()
            func_cat = row[1].strip() if len(row) > 1 else ""
            cog_name = row[2].strip() if len(row) > 2 else ""
            gene_name = row[3].strip() if len(row) > 3 else ""
            pathway = row[4].strip() if len(row) > 4 else ""
            pmid = row[5].strip() if len(row) > 5 else ""
            pdb = row[6].strip() if len(row) > 6 else ""

            cog_defs[cog_id] = {
                "functional_category": func_cat,
                "name": cog_name,
                "gene_name": gene_name,
                "pathway": pathway,
                "pmid": pmid,
                "pdb": pdb,
            }

    logger.info(f"Parsed {len(cog_defs)} COG definitions")
    return cog_defs


def parse_functional_categories(fun_file: Path) -> Dict[str, Dict[str, str]]:
    """
    Parse COG functional categories file (cog-24.fun.tab).

    :param fun_file: Path to cog-24.fun.tab file
    :return: Dictionary mapping category ID to category data
    """
    func_cats = {}

    if not fun_file.exists():
        logger.error(f"COG functional categories file not found: {fun_file}")
        return func_cats

    with open(fun_file, "r") as f:
        reader = csv.reader(f, delimiter="\t")

        for row in reader:
            # Skip empty lines
            if not row or len(row) < 4:
                continue

            # Columns: Category_ID, Group, Color, Description
            cat_id = row[0].strip()
            group = row[1].strip() if len(row) > 1 else ""
            color = row[2].strip() if len(row) > 2 else ""
            description = row[3].strip() if len(row) > 3 else ""

            func_cats[cat_id] = {
                "group": group,
                "color": color,
                "description": description,
            }

    logger.info(f"Parsed {len(func_cats)} functional categories")
    return func_cats


def get_category_group_name(group_id: str) -> str:
    """
    Get the name of a functional category group.

    :param group_id: Group ID (1-4)
    :return: Group name
    """
    group_names = {
        "1": "Information Storage and Processing",
        "2": "Cellular Processes and Signaling",
        "3": "Metabolism",
        "4": "Poorly Characterized",
    }
    return group_names.get(group_id, "Unknown")


def split_functional_categories(category_string: str) -> List[str]:
    """
    Split multi-category string into individual categories.

    COG entries can have multiple functional categories (e.g., "CP" means both C and P).

    :param category_string: Functional category string (e.g., "C", "CP", "PTM")
    :return: List of individual category letters
    """
    if not category_string:
        return []

    # Each letter is a separate category
    return list(category_string)
