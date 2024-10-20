"""Pandas utilities."""

import csv
from itertools import combinations
from pathlib import Path
from typing import List

import pandas as pd

from kg_microbe.transform_utils.constants import (
    DO_NOT_CHANGE_PREFIXES,
    ID_COLUMN,
    MEDIADIVE_MEDIUM_PREFIX,
    MEDIADIVE_SOLUTION_PREFIX,
    NAME_COLUMN,
    OBJECT_COLUMN,
    PREDICATE_COLUMN,
    SUBJECT_COLUMN,
)


def drop_duplicates(
    file_path: Path,
    sort_by_column: str = SUBJECT_COLUMN,
    consolidation_columns: List = None,
):
    """
    Read TSV, drop duplicates, and export to the same file without making unnecessary copies.

    :param file_path: Path to the TSV file.
    :param sort_by_column: Column name to sort the DataFrame.
    :param consolidation_columns: List of columns to consolidate.
    """
    exclude_prefixes = DO_NOT_CHANGE_PREFIXES
    df = pd.read_csv(file_path, sep="\t", low_memory=False)

    # Store the original NAME_COLUMN if it's in consolidation_columns
    if consolidation_columns and NAME_COLUMN in consolidation_columns:
        original_name_column = df[NAME_COLUMN].copy()

    if consolidation_columns and all(col in df.columns for col in consolidation_columns):
        for col in consolidation_columns:
            df[col] = df[col].apply(
                lambda x: (
                    str(x).lower()
                    if not any(str(x).startswith(prefix) for prefix in exclude_prefixes)
                    else x
                )
            )

    df.drop_duplicates(inplace=True)
    df.sort_values(by=[sort_by_column], inplace=True)

    # Restore the original values of the NAME_COLUMN
    if consolidation_columns and NAME_COLUMN in consolidation_columns:
        df[NAME_COLUMN] = original_name_column.loc[df.index]

    df.to_csv(file_path, sep="\t", index=False)
    return df


def establish_transitive_relationship(
    file_path: Path,
    subject_prefix: str,
    intermediate_prefix: str,
    predicate: str,
    object_prefixes_list: List[str],
) -> pd.DataFrame:
    """
    Establish transitive relationship given the predicate is the same.

    e.g.: Existent relations:
        1. A => predicate => B
        2. B => predicate => C

    This function adds the relation A => predicate => C


    :param file_path: Filepath of the edge file.
    :param subject_prefix: Subject prefix (A in the example)
    :param intermediate_prefix: Intermediate prefix that connects the subject to object (B in the example).
    :param predicate: The common predicate between all relations.
    :param object_prefixes_list: List of Object prefixes (C in the example)
    :return: Core dataframe with additional deduced rows.
    """
    df = drop_duplicates(file_path)
    df_relations = df.loc[df[PREDICATE_COLUMN] == predicate]
    subject_condition = df_relations[SUBJECT_COLUMN].str.startswith(subject_prefix)
    intermediate_subject_condition = df_relations[SUBJECT_COLUMN].str.startswith(
        intermediate_prefix
    )
    object_condition = df_relations[OBJECT_COLUMN].apply(
        lambda x: any(str(x).startswith(prefix) for prefix in object_prefixes_list)
    )
    intermediate_object_condition = df_relations[OBJECT_COLUMN].str.startswith(intermediate_prefix)
    subject_intermediate_df = df_relations[subject_condition & intermediate_object_condition]
    intermediate_object_df = df_relations[intermediate_subject_condition & object_condition]

    list_of_dfs_to_append = []

    # for row in subject_intermediate_df.iterrows():
    #     transitive_relations_df = intermediate_object_df.loc[
    #         intermediate_object_df[SUBJECT_COLUMN] == row[1].object
    #     ]
    #     transitive_relations_df.loc[
    #         transitive_relations_df[SUBJECT_COLUMN] == row[1].object, SUBJECT_COLUMN
    #     ] = row[1].subject
    #     list_of_dfs_to_append.append(transitive_relations_df)
    # Create a dictionary to map objects to subjects
    object_to_subject = dict(
        zip(subject_intermediate_df["object"], subject_intermediate_df["subject"], strict=False)
    )

    # Filter the DataFrame to include only rows where the SUBJECT_COLUMN matches any object in the mapping
    filtered_df = intermediate_object_df[
        intermediate_object_df[SUBJECT_COLUMN].isin(object_to_subject.keys())
    ]

    # Map the SUBJECT_COLUMN in filtered_df to the corresponding subjects using the mapping
    filtered_df.loc[:, SUBJECT_COLUMN] = filtered_df[SUBJECT_COLUMN].map(object_to_subject)

    # Append the modified DataFrame to the list (assuming list_of_dfs_to_append is already defined)
    list_of_dfs_to_append.append(filtered_df)

    df = pd.concat([df] + list_of_dfs_to_append).sort_values(by=[SUBJECT_COLUMN])
    df = df.dropna(subset=[SUBJECT_COLUMN])
    df.to_csv(file_path, sep="\t", index=False)
    return df


def establish_transitive_relationship_multiple(
    file_path: Path,
    subject_prefix: str,
    intermediate_prefix_list: list,
    predicate_list: list,
    object_prefixes_lists: List[list[str]],
) -> pd.DataFrame:
    """
    Establish multiple transitive relationships via the establish_transitive_relationship function.

    e.g.: Existent relations:
        1. A => predicate => B
        2. B => predicate => C
        3. C => predicate => D

    This function adds the relation A => predicate => D


    :param file_path: Filepath of the edge file.
    :param subject_prefix: Subject prefix (A in the example)
    :param intermediate_prefix_list: List of intermediate prefixes ([B,C] in the example).
    :param predicate_list: List of the common predicate between all relations. Len == intermediate_prefix_list.
    :param object_prefixes_list: List of Object prefixes ([[C,D]] in the example). Len == intermediate_prefix_list.
    :return: Core dataframe with additional deduced rows.
    """
    num_triples_in_path = len(intermediate_prefix_list)
    for search_number in range(num_triples_in_path):
        intermediate_prefix = intermediate_prefix_list[search_number]
        predicate = predicate_list[search_number]
        object_prefixes_list = object_prefixes_lists[search_number]
        df = establish_transitive_relationship(
            file_path, subject_prefix, intermediate_prefix, predicate, object_prefixes_list
        )
    return df


def dump_ont_nodes_from(nodes_filepath: Path, target_path: Path, prefix: str):
    """
    Dump CURIEs of an ontology for further processing.

    :param nodes_filepath: Path of the nodes file.
    :param target_path: Path where this list of CURIEs need to be exported.
    :param prefix: Prefix determines the CURIEs of interest.
    """
    df = pd.read_csv(nodes_filepath, sep="\t", low_memory=False)
    all_ont_nodes = (
        df.loc[df[ID_COLUMN].str.startswith(prefix)][[ID_COLUMN]]
        .drop_duplicates()
        .sort_values(by=[ID_COLUMN])
    )
    if target_path.is_file():
        try:
            captured_chebi = pd.read_csv(
                target_path, sep="\t", low_memory=False, names=all_ont_nodes.columns
            )
        except pd.errors.EmptyDataError:
            captured_chebi = pd.DataFrame(columns=all_ont_nodes.columns)
        all_ont_nodes = (
            pd.concat([all_ont_nodes, captured_chebi]).drop_duplicates().sort_values(by=[ID_COLUMN])
        )
    all_ont_nodes.to_csv(target_path, sep="\t", index=False, header=None)


def get_ingredients_overlap(file_path: Path, target_path: Path):
    """
    Export TSV showing ingredient overlap between solutions and media.

    :param file_path: Edges file path
    :param target_path: Output path.
    """
    columns_of_interest = [SUBJECT_COLUMN, PREDICATE_COLUMN, OBJECT_COLUMN]
    edges_df = pd.read_csv(file_path, sep="\t", low_memory=False, usecols=columns_of_interest)
    edges_df.dropna(inplace=True)

    # Filter rows where subject starts with the desired prefixes
    solution_medium_df = edges_df[
        edges_df[SUBJECT_COLUMN].str.startswith(
            (MEDIADIVE_MEDIUM_PREFIX, MEDIADIVE_SOLUTION_PREFIX)
        )
    ]

    # Create a dictionary to store ingredients for each solution/medium
    ingredients_dict = {
        sol_med: set(group_df[OBJECT_COLUMN])
        for sol_med, group_df in solution_medium_df.groupby(SUBJECT_COLUMN)
    }

    # Prepare the list to hold all rows for the CSV file
    rows_to_write = []

    for sol_med_1, sol_med_2 in combinations(ingredients_dict.keys(), 2):
        ingredients_1 = ingredients_dict[sol_med_1]
        ingredients_2 = ingredients_dict[sol_med_2]

        overlapping_ingredients = ingredients_1.intersection(ingredients_2)
        total_unique_ingredients = len(ingredients_1.union(ingredients_2))

        # Calculate overlap percentage and round it to 2 decimal places
        overlap_percentage = round(
            (
                ((len(overlapping_ingredients) / total_unique_ingredients) * 100)
                if total_unique_ingredients > 0
                else 0
            ),
            2,
        )

        # Add the current row to the list if there is an overlap
        if overlap_percentage > 0.0:
            rows_to_write.append(
                [sol_med_1, sol_med_2, ", ".join(overlapping_ingredients), overlap_percentage]
            )

    # Sort the rows by overlap percentage in descending order
    rows_to_write.sort(key=lambda x: x[3], reverse=True)

    # Write the sorted rows to the CSV file
    with open(target_path, "w", newline="") as f:
        writer = csv.writer(f, delimiter="\t")
        writer.writerow(
            ["Solution_medium_1", "Solution_medium_2", "Overlapping_ingredients", "Overlap_%"]
        )
        writer.writerows(rows_to_write)
