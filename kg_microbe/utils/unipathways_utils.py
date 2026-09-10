"""Unipathways utilities."""

import re

from kg_microbe.transform_utils.constants import (
    CATEGORY_COLUMN,
    GO_PREFIX,
    ID_COLUMN,
    OBJECT_COLUMN,
    RHEA_CATEGORY,
    RHEA_NEW_PREFIX,
    SUBJECT_COLUMN,
    UNIPATHWAYS_CATEGORIES_DICT,
    UNIPATHWAYS_IGNORE_PREFIXES,
    UNIPATHWAYS_INCLUDE_PAIRS,
    UNIPATHWAYS_PATHWAY_PREFIX,
    UNIPATHWAYS_RELATIONS_DICT,
    UNIPATHWAYS_SHORT_PREFIX,
)


def project_onto_header(parts, source_header, node_header):
    """
    Reshape one row onto ``node_header``, matching columns by name.

    The caller writes ``node_header`` as the file's header, so every row has to
    be exactly that wide. Padding positionally is not enough: KGX leaks
    ``subsets``, ``meta`` and ``iri`` onto node rows (the columns
    ``_normalize_schema`` strips), and a row wider than the header made
    ``[""] * (len(node_header) - len(parts))`` evaluate to ``[]`` -- so the
    extra fields survived and the file became unreadable (#1033). Matching by
    name rather than truncating also means an extra, missing or reordered
    upstream column cannot shift a value into the wrong field.

    :param parts: The row's fields.
    :param source_header: Column names of the row, in order. ``None`` falls
        back to positional pad-or-truncate, for callers that never saw a header.
    :param node_header: Canonical column names to emit.
    :return: Exactly ``len(node_header)`` fields.
    """
    if source_header is None:
        return (parts + [""] * len(node_header))[: len(node_header)]
    # strict=False on purpose: a row may be short (KGX omits trailing empties)
    # or long (leaked columns); both are handled by name lookup below.
    by_name = dict(zip(source_header, parts, strict=False))
    return [by_name.get(column, "") for column in node_header]


def replace_id_with_xref(line, xref_index, id_index, category_index, nodes_dictionary, node_header, source_header=None):
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
    :param source_header: Column names of ``line``, so fields are matched by
        name rather than by position (#1033).
    :type source_header: list
    """
    parts = line.strip().split("\t")
    xrefs = parts[xref_index].split("|") if parts[xref_index] != "" else None
    new_lines = []
    if xrefs:
        # Avoid reactions that are given GO xrefs, use Unipathways prefix instead
        xrefs = [xref for xref in xrefs if GO_PREFIX not in xref]
        for xref in xrefs:
            # Stub node covered authoritatively by the Rhea ingest — emit an
            # empty row except for id. Set category on Rhea stubs so downstream
            # category-aware consumers (and validators) don't see an empty
            # category column (biolink:MolecularActivity matches the
            # rhea_mappings transform's own RHEA category).
            stub = {ID_COLUMN: xref}
            if xref.startswith(RHEA_NEW_PREFIX):
                # Set category on Rhea stubs so downstream category-aware
                # consumers (and validators) don't see an empty category
                # column. Keyed by name: category_index is an index into the
                # *source* header and only matched by luck (#1033).
                stub[CATEGORY_COLUMN] = RHEA_CATEGORY
            l_parts = [stub.get(column, "") for column in node_header]
            nodes_dictionary[parts[id_index]].append(xref)
            l_joined = "\t".join(l_parts)
            new_lines.append(l_joined)
    else:
        new_lines.append(replace_category_for_unipathways(line, id_index, category_index, node_header, source_header))
    return new_lines, nodes_dictionary


def replace_category_for_unipathways(line, id_index, category_index, node_header, source_header=None):
    """
    Replace category of a given node.

    :param line: A line from the original triples.
    :type line: str
    :param id_index: The index of the tab delimited line with the node id.
    :type id_index: int
    :param category_index: The index of the tab delimited line with the node category.
    :type category_index: int
    :param source_header: Column names of ``line``, so fields are matched by
        name rather than by position (#1033).
    :type source_header: list
    """
    parts = line.strip().split("\t")
    id_substring = get_unipathways_prefix(parts[id_index])
    # Get defined category
    category = UNIPATHWAYS_CATEGORIES_DICT[id_substring]
    parts[category_index] = category
    complete_parts = project_onto_header(parts, source_header, node_header)
    # Join the parts back together with a tab separator
    new_line = "\t".join(complete_parts)
    return new_line


def replace_triples_with_labels(line, subject_index, object_index, predicate_index, relation_index, nodes_dictionary):
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
        lambda row: not any(substring in str(cell) for substring in UNIPATHWAYS_IGNORE_PREFIXES for cell in row),
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
        new_df = df[(df[SUBJECT_COLUMN] == subject_node) & (df[OBJECT_COLUMN].str.contains(pair[1]))]
    else:
        new_df = df[(df[SUBJECT_COLUMN].str.contains(pair[0])) & df[OBJECT_COLUMN].str.contains(pair[1])]
    return new_df
