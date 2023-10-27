"""Pandas utilities."""
from pathlib import Path

import pandas as pd

from kg_microbe.transform_utils.constants import OBJECT_COLUMN, PREDICATE_COLUMN, SUBJECT_COLUMN


def drop_duplicates(file_path: Path):
    """
    Read TSV, drop duplicates and export to same file.

    :param df: Dataframe
    :param file_path: file path.
    """
    df = pd.read_csv(file_path, sep="\t", low_memory=False)
    df = df.drop_duplicates()
    df.to_csv(file_path, sep="\t", index=False)
    return df


def establish_transitive_relationship(
    file_path: Path,
    subject_prefix: str,
    intermediate_prefix: str,
    predicate: str,
    object_prefix: str,
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
    :param object_prefix: Object prefix (C in the example)
    :return: Core dataframe with additional deduced rows.
    """
    df = drop_duplicates(file_path)
    df_relations = df.loc[df[PREDICATE_COLUMN] == predicate]
    subject_condition = df_relations[SUBJECT_COLUMN].str.startswith(subject_prefix)
    intermediate_subject_condition = df_relations[SUBJECT_COLUMN].str.startswith(
        intermediate_prefix
    )
    object_condition = df_relations[OBJECT_COLUMN].str.startswith(object_prefix)
    intermediate_object_condition = df_relations[OBJECT_COLUMN].str.startswith(intermediate_prefix)
    subject_intermediate_df = df_relations[subject_condition & intermediate_object_condition]
    intermediate_object_df = df_relations[intermediate_subject_condition & object_condition]

    list_of_dfs_to_append = []

    for row in subject_intermediate_df.iterrows():
        transitive_relations_df = intermediate_object_df.loc[
            intermediate_object_df[SUBJECT_COLUMN] == row[1].object
        ]
        transitive_relations_df.loc[
            transitive_relations_df[SUBJECT_COLUMN] == row[1].object, SUBJECT_COLUMN
        ] = row[1].subject
        list_of_dfs_to_append.append(transitive_relations_df)

    df = pd.concat([df] + list_of_dfs_to_append)
    df.to_csv(file_path, sep="\t", index=False)
    return df
