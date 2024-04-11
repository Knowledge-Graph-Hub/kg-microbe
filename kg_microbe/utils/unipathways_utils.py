"""Unipathways utilities."""

import re

from kg_microbe.transform_utils.constants import (
    GO_PREFIX,
    OBJECT_COLUMN,
    SUBJECT_COLUMN,
    UNIPATHWAYS_CATEGORIES_DICT,
    UNIPATHWAYS_IGNORE_PREFIXES,
    UNIPATHWAYS_INCLUDE_PAIRS,
    UNIPATHWAYS_PATHWAY_PREFIX,
    UNIPATHWAYS_RELATIONS_DICT,
    UNIPATHWAYS_SHORT_PREFIX,
)


def replace_id_with_xref(line, xref_index, id_index, category_index, nodes_dictionary, node_header):
    """
    Replace node ID with corresponding xref.

    :param line: A line from the original triples.
    :type line: str
    :param xref_index: The index of the tab delimited line with the node xref.
    :type xref_index: int
    :param id_index: The index of the tab delimited line with the node id.
    :type id_index: int
    :param category_index: The index of the tab delimited line with the node category.
    :type category_index: int
    :param node_header: List of all values in nodes file header.
    :type node_header: list
    """
    parts = line.strip().split("\t")
    xrefs = parts[xref_index].split("|") if parts[xref_index] != "" else None
    new_lines = []
    if xrefs:
        # Avoid reactions that are given GO xrefs, use Unipathways prefix instead
        xrefs = [xref for xref in xrefs if GO_PREFIX not in xref]
        for xref in xrefs:
            # Writing out blank values for all other columns than id since covered by Rhea ingest
            l_parts = [xref] + ([""] * (len(node_header) - 1))
            nodes_dictionary[parts[id_index]].append(xref)
            l_joined = "\t".join(l_parts)
            new_lines.append(l_joined)
    else:
        new_lines.append(replace_category(line, id_index, category_index))
    return new_lines, nodes_dictionary


def replace_category(line, id_index, category_index):
    """
    Replace category of a given node.

    :param line: A line from the original triples.
    :type line: str
    :param id_index: The index of the tab delimited line with the node id.
    :type id_index: int
    :param category_index: The index of the tab delimited line with the node category.
    :type category_index: int
    """
    parts = line.strip().split("\t")
    id_substring = get_unipathways_prefix(parts[id_index])
    # Get defined category
    category = UNIPATHWAYS_CATEGORIES_DICT[id_substring]
    parts[category_index] = category
    # Join the parts back together with a tab separator
    new_line = "\t".join(parts)
    return new_line


def replace_triples_with_labels(
    line, subject_index, object_index, predicate_index, relation_index, nodes_dictionary
):
    """
    Replace triples labels according to a dictionary lookup. Also replace the predicate and relation.

    :param line: A line from the original triples.
    :type line: str
    :param subject_index: The index of the tab delimited line with the triple subject.
    :type subject_index: int
    :param object_index: The index of the tab delimited line with the triple object.
    :type object_index: int
    :param predicate_index: The index of the tab delimited line with the triple predicate.
    :type predicate_index: int
    :param relation_index: The index of the tab delimited line with the triple relation.
    :type relation_index: int
    """
    parts = line.strip().split("\t")
    # Replace predicate
    new_predicate = get_key_from_value(UNIPATHWAYS_RELATIONS_DICT, parts[relation_index])
    if new_predicate:
        parts[predicate_index] = new_predicate
    # Get new labels for subject
    new_subject_labels = nodes_dictionary.get(parts[subject_index])
    # Get new labels for object
    new_object_labels = nodes_dictionary.get(parts[object_index])
    new_subj_parts = []
    new_obj_parts = []
    if new_subject_labels:
        for subj_lab in new_subject_labels:
            new_parts = parts[:]  # Create a copy of parts
            new_parts[subject_index] = subj_lab  # Assign subj_lab to the appropriate index
            new_subj_parts.append(new_parts)  # Append the copy to new_subj_parts
    else:
        new_subj_parts.append(parts)
    if new_object_labels:
        for p in new_subj_parts:
            for obj_lab in new_object_labels:
                new_parts = p[:]  # Create a copy of parts
                new_parts[object_index] = obj_lab  # Assign subj_lab to the appropriate index
                new_obj_parts.append(new_parts)  # Append the copy to new_subj_parts
    else:
        new_obj_parts = new_subj_parts
    new_lines = []
    for p in new_obj_parts:
        # Join the parts back together with a tab separator
        l_joined = "\t".join(p)
        new_lines.append(l_joined)
    return new_lines


def get_key_from_value(dictionary, value):
    """Extract a key from a dictionary with the corresponding value."""
    for key, val in dictionary.items():
        if val == value:
            return key
    return None  # If value not found


def remove_unwanted_prefixes_from_node_xrefs(line, xref_index):
    """
    Remove unwanted prefixes that exist in xrefs for given node.

    :param line: A line from the original triples.
    :type line: str
    :param xref_index: The index of the tab delimited line with the triple xref.
    :type xref_index: int
    """
    # Construct regex pattern
    pattern = r"\b(?:{}):[^\s|]+\|?".format(
        "|".join(re.escape(prefix.rstrip(":")) for prefix in UNIPATHWAYS_IGNORE_PREFIXES)
    )
    # Remove substrings matching the pattern, make all caps since there is variation among node types
    line = re.sub(pattern, "", line, flags=re.IGNORECASE)
    # Remove trailing |
    parts = line.strip().split("\t")
    parts[xref_index] = parts[xref_index].rstrip("|")
    line = "\t".join(parts)
    return line


def remove_unwanted_prefixes_from_edges(df):
    """
    Remove unwanted prefixes that exist in all triple.

    :param df: A dataframe of all triples.
    :type df: pd.DataFrame
    """
    # Boolean mask to filter rows
    mask = df.apply(
        lambda row: not any(
            substring in str(cell) for substring in UNIPATHWAYS_IGNORE_PREFIXES for cell in row
        ),
        axis=1,
    )

    # Filter DataFrame
    filtered_df = df[mask]

    return filtered_df

    """for prefix in UNIPATHWAYS_IGNORE_PREFIXES:
        if prefix in line:
            return None
        else:
            continue
    return line"""


def get_unipathways_prefix(id):
    """
    Get unipathways prefix of a given node ID if available.

    :param id: The node ID.
    :type line: str
    """
    if UNIPATHWAYS_SHORT_PREFIX in id:
        prefix = re.match(r"^(?:OBO:[A-Za-z]+)_?[A-Za-z]+", id).group()
    else:
        prefix = id

    return prefix


def check_wanted_pairs(line, subject_index, object_index):
    """
    Check if subject object pair should be included.

    :param line: A line from the original triples.
    :type line: str
    :param subject_index: The index of the tab delimited line with the triple subject.
    :type subject_index: int
    :param object_index: The index of the tab delimited line with the triple object.
    :type object_index: int
    """
    parts = line.strip().split("\t")
    # Look at prefixes in UNIPATHWAYS_INCLUDE_PAIRS in addition to pathway-pathway triples,
    # even though not a part of the final pattern which uses UNIPATHWAYS_INCLUDE_PAIRS
    if [
        get_unipathways_prefix(parts[subject_index]),
        get_unipathways_prefix(parts[object_index]),
    ] in UNIPATHWAYS_INCLUDE_PAIRS + [[UNIPATHWAYS_PATHWAY_PREFIX, UNIPATHWAYS_PATHWAY_PREFIX]]:
        return line
    else:
        return None


def create_df_from_pair(df, pair, subject_node=None):
    """
    Create a dataframe from a given dataframe according to substrings in a given pair.

    :param df: A dataframe that contains all triples.
    :type df: pd.DataFrame
    :param pair: A list of the subject, object of the desired triple pattern.
    :type pair: List
    :param subject_node: Optional, a specific subject node ID to base the search on.
    :type subject_node: str
    """
    if subject_node:
        new_df = df[
            (df[SUBJECT_COLUMN] == subject_node) & (df[OBJECT_COLUMN].str.contains(pair[1]))
        ]
    else:
        new_df = df[
            (df[SUBJECT_COLUMN].str.contains(pair[0])) & df[OBJECT_COLUMN].str.contains(pair[1])
        ]
    return new_df
