"""NLP utilities."""
import csv
from pathlib import Path
from typing import List

import pandas as pd
from oaklib import get_adapter
from oaklib.datamodels.text_annotator import TextAnnotationConfiguration

from kg_microbe.transform_utils.constants import (
    END_COLUMN,
    MATCHES_WHOLE_TEXT_COLUMN,
    OBJECT_ALIASES_COLUMN,
    OBJECT_CATEGORIES_COLUMN,
    OBJECT_ID_COLUMN,
    OBJECT_LABEL_COLUMN,
    START_COLUMN,
    SUBJECT_LABEL_COLUMN,
    TAX_ID_COLUMN,
    TRAITS_DATASET_LABEL_COLUMN,
)

# LLM_MODEL = "gpt-4"


def annotate(df: pd.DataFrame, prefix: str, exclusion_list: List, outfile: Path, llm: bool = False):
    """
    Annotate dataframe column text using oaklib + llm.

    :param df: Input DataFrame
    :param prefix: Ontology to be used.
    :param exclusion_list: Tokens that can be ignored.
    """
    ontology = prefix.strip(":")
    if llm:
        # ! Experimental
        oi = get_adapter(f"llm:sqlite:obo:{ontology}")
        matches_whole_text = False
        annotated_columns = [
            TAX_ID_COLUMN,
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
        oi = get_adapter(f"sqlite:obo:{ontology}")
        matches_whole_text = True
        annotated_columns = [
            TAX_ID_COLUMN,
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
        for sublist in df.iloc[:, 1].drop_duplicates().to_list()
        for item in sublist.split(", ")
    }

    unique_terms_annotated = {
        term: list(oi.annotate_text(term.replace("_", " "), configuration))
        for term in unique_terms_set
    }

    with open(str(outfile), "w", newline="") as file:
        writer = csv.writer(file, delimiter="\t", quoting=csv.QUOTE_NONE)
        writer.writerow(annotated_columns)

        for row in df.iterrows():
            terms_split = row[1].iloc[1].split(", ")
            for term in terms_split:
                responses = unique_terms_annotated.get(term, None)
                if responses:
                    for response in responses:
                        response_dict = response.__dict__
                        response_dict[TAX_ID_COLUMN] = row[1].iloc[0]
                        response_dict[TRAITS_DATASET_LABEL_COLUMN] = term

                        # Ensure the order of columns matches the header
                        row_to_write = [response_dict.get(col) for col in annotated_columns]
                        writer.writerow(row_to_write)
