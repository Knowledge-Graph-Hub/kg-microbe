"""NLP utilities."""

import csv
from pathlib import Path
from typing import List

import pandas as pd
from oaklib import get_adapter
from oaklib.datamodels.text_annotator import TextAnnotation, TextAnnotationConfiguration

from kg_microbe.transform_utils.constants import (
    ACTION_COLUMN,
    CHEBI_PREFIX,
    CHEBI_SOURCE,
    END_COLUMN,
    GO_PREFIX,
    GO_SOURCE,
    MATCHES_WHOLE_TEXT_COLUMN,
    OBJECT_ALIASES_COLUMN,
    OBJECT_CATEGORIES_COLUMN,
    OBJECT_ID_COLUMN,
    OBJECT_LABEL_COLUMN,
    REPLACEMENT,
    START_COLUMN,
    SUBJECT_LABEL_COLUMN,
    SUPPLEMENT,
    TRAITS_DATASET_LABEL_COLUMN,
)
from kg_microbe.utils.pandas_utils import drop_duplicates

# LLM_MODEL = "gpt-4"

PREFIX_SOURCE_MAP = {
    GO_PREFIX: GO_SOURCE,
    CHEBI_PREFIX: CHEBI_SOURCE,
}


def _overlap(a, b):
    """Get number of characters in 2 strings that overlap."""
    return len(set(a) & set(b))


def annotate(
    df: pd.DataFrame,
    prefix: str,
    exclusion_list: List,
    outfile: Path,
    llm: bool = False,
    manual_annotation_path: Path = None,
):
    """
    Annotate dataframe column text using oaklib + llm.

    :param df: Input DataFrame
    :param prefix: Ontology to be used.
    :param exclusion_list: Tokens that can be ignored.
    """
    ontology = prefix.strip(":")
    outfile_for_unmatched = outfile.with_name(outfile.stem + "_unmatched" + outfile.suffix)

    if llm:
        # ! Experimental
        oi = get_adapter(f"llm:sqlite:{PREFIX_SOURCE_MAP[ontology]}")
        matches_whole_text = False
        annotated_columns = [
            OBJECT_ID_COLUMN,
            OBJECT_LABEL_COLUMN,
            OBJECT_CATEGORIES_COLUMN,
            OBJECT_ALIASES_COLUMN,
            SUBJECT_LABEL_COLUMN,
            START_COLUMN,
            END_COLUMN,
            TRAITS_DATASET_LABEL_COLUMN,
        ]
    else:
        oi = get_adapter(f"sqlite:{PREFIX_SOURCE_MAP[ontology]}")
        matches_whole_text = True
        annotated_columns = [
            OBJECT_ID_COLUMN,
            OBJECT_LABEL_COLUMN,
            SUBJECT_LABEL_COLUMN,
            MATCHES_WHOLE_TEXT_COLUMN,
            START_COLUMN,
            END_COLUMN,
            TRAITS_DATASET_LABEL_COLUMN,
        ]

    configuration = TextAnnotationConfiguration(
        include_aliases=True,
        token_exclusion_list=exclusion_list,
        # model=LLM_MODEL,
        matches_whole_text=matches_whole_text,
    )

    unique_terms_set = {
        item.strip()
        for sublist in df.iloc[:, 0].drop_duplicates().to_list()
        for item in sublist.split(", ")
    }

    unique_terms_annotated = {
        term: list(oi.annotate_text(term.replace("_", " "), configuration))
        for term in unique_terms_set
    }
    terms_not_annotated = {k: v for k, v in unique_terms_annotated.items() if v == []}
    # The annotations upto this point is matches_whole_text = True.
    # There are still some terms that aren't annotated.
    # For those we flip matches_whole_text = False and then rerun.
    if len(terms_not_annotated) > 0:
        configuration.matches_whole_text = False
        unique_terms_not_annotated_set = set(terms_not_annotated.keys())
        unique_terms_annotated_not_whole_match = {
            term: [
                x
                for x in oi.annotate_text(term.replace("_", " "), configuration)
                if len(x.object_label) > 2
            ]
            for term in unique_terms_not_annotated_set
        }

        # Initialize an empty dictionary
        max_overlap_dict = {}

        # Iterate over items in the original dictionary
        for k, v in unique_terms_annotated_not_whole_match.items():
            # Find the max value using the overlap function and assign it to the new dictionary
            if v != []:
                max_overlap_dict[k] = [max(v, key=lambda obj: _overlap(obj.object_label, k))]
        # Now new_dict is equivalent to unique_terms_annotated_not_whole_match in the original code
        unique_terms_annotated_not_whole_match = max_overlap_dict

        # unique_terms_annotated.update(unique_terms_annotated_not_whole_match)

    with (
        open(str(outfile), "w", newline="") as file_1,
        open(str(outfile_for_unmatched), "w", newline="") as file_2,
    ):
        writer_1 = csv.writer(file_1, delimiter="\t", quoting=csv.QUOTE_NONE)
        writer_2 = csv.writer(file_2, delimiter="\t", quoting=csv.QUOTE_NONE)
        writer_1.writerow(annotated_columns)
        writer_2.writerow(annotated_columns)
        if manual_annotation_path:
            manual_annotation_df = pd.read_csv(manual_annotation_path, sep="\t", low_memory=False)
        else:
            manual_annotation_df = pd.DataFrame()

        for row in df.iterrows():
            terms_split = row[1].iloc[0].split(", ")
            for term in terms_split:
                responses = unique_terms_annotated.get(term, None)
                if responses:
                    writer = writer_1
                else:
                    if not manual_annotation_df.empty:
                        manual_annotation_row: pd.DataFrame = manual_annotation_df.loc[
                            manual_annotation_df[TRAITS_DATASET_LABEL_COLUMN] == term
                        ]
                    else:
                        manual_annotation_row = pd.DataFrame()
                    responses = unique_terms_annotated_not_whole_match.get(term, None)
                    if not manual_annotation_row.empty:
                        for _, row in manual_annotation_row.iterrows():
                            if row[ACTION_COLUMN] == REPLACEMENT:
                                responses[0].object_id = row[OBJECT_ID_COLUMN]
                                responses[0].object_label = row[OBJECT_LABEL_COLUMN]
                            elif row[ACTION_COLUMN] == SUPPLEMENT:
                                tmp_response = TextAnnotation(
                                    object_id=row[OBJECT_ID_COLUMN],
                                    object_label=row[OBJECT_LABEL_COLUMN],
                                    subject_start=1,
                                    subject_end=len(row[OBJECT_LABEL_COLUMN]),
                                )

                                responses.append(tmp_response)
                            else:
                                print(f"{row[ACTION_COLUMN]} has no action implemented.")
                        writer = writer_1
                    else:
                        writer = writer_2
                if responses:
                    for response in responses:
                        response_dict = response.__dict__
                        # response_dict[TAX_ID_COLUMN] = row[1].iloc[0]
                        response_dict[TRAITS_DATASET_LABEL_COLUMN] = term

                        # Ensure the order of columns matches the header
                        row_to_write = [response_dict.get(col) for col in annotated_columns]
                        writer.writerow(row_to_write)

    drop_duplicates(outfile, sort_by_column=OBJECT_ID_COLUMN)
    drop_duplicates(outfile_for_unmatched, sort_by_column=OBJECT_ID_COLUMN)
