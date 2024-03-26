"""Utility functions for working with the UniProtKB/Swiss-Prot database."""

import csv
import gzip
from pathlib import Path

from Bio import SwissProt

from kg_microbe.transform_utils.constants import (
    ACCESSIONS_KEY,
    FILENAME_KEY,
    NCBITAXON_PREFIX,
    PROTEOME_ID_COLUMN,
    PROTEOME_PREFIX,
    TAXONOMY_ID_UNIPROT_COLUMN,
    UNIPROT_TREMBL_TMP_DIR,
)


def clean_string(s):
    """
    Remove newline characters, semicolons, and leading/trailing whitespace from a string.

    :param s: The string to be cleaned.
    :type s: str
    :return: The cleaned string.
    :rtype: str
    """
    return s.replace("\n", "").replace(";", "").strip()


def process_value(value):
    """
    Process the value of the record attribute.

    Clean strings in an input value by removing newline characters, semicolons,
    and leading/trailing whitespace. If the input is a list or tuple, clean each
    string element within it. Non-string elements are left unchanged.

    :param value: The input value containing the string(s) to be cleaned.
                  It can be a single string, a list, or a tuple.
    :type value: str | list | tuple
    :return: The cleaned input value, with strings processed and other types left as-is.
             If the input is a list or tuple, returns a new list with cleaned strings.
             If the input is a single string, returns the cleaned string.
             If the input is neither a string, list, nor tuple, returns the input as-is.
    :rtype: str | list
    """
    if isinstance(value, (list, tuple)):
        return [clean_string(val) if isinstance(val, str) else val for val in value]
    elif isinstance(value, str):
        return clean_string(value)
    return value


def unzip_trembl_file(path: Path) -> None:
    """
    Unzip the gzipped UniProtKB/Swiss-Prot file and return contents as an object.

    :param trembl_file: Path to the gzipped UniProtKB/Swiss-Prot file.
    :param output_dir: Path to the output directory.
    """
    with gzip.open(path, "rt") as file:
        record_attributes = []
        records = SwissProt.parse(file)
        for record in records:
            if not record_attributes:
                # For each record. get all attributes of the record object
                record_attributes = [
                    attr
                    for attr in dir(record)
                    if not callable(getattr(record, attr)) and not attr.startswith("__")
                ]
                # Add an element to the beginning of record attributes list to store the file name
                record_attributes.insert(0, FILENAME_KEY)
                record_attributes.insert(1, PROTEOME_ID_COLUMN)
                # move the taxonomy_id column to position 1
                record_attributes.remove(TAXONOMY_ID_UNIPROT_COLUMN)
                record_attributes.insert(2, TAXONOMY_ID_UNIPROT_COLUMN)
                external_keys = [FILENAME_KEY, PROTEOME_ID_COLUMN]

            # Create a table of the record attributes
            record_table = {
                attr: process_value(getattr(record, attr))
                for attr in record_attributes
                if attr not in external_keys
            }
            record_table[ACCESSIONS_KEY] = record_table[ACCESSIONS_KEY][0]
            record_table[FILENAME_KEY] = str(path).split("/")[-1]
            record_table[PROTEOME_ID_COLUMN] = (
                PROTEOME_PREFIX + record_table[FILENAME_KEY].split("_")[0]
            )
            record_table[TAXONOMY_ID_UNIPROT_COLUMN] = (
                NCBITAXON_PREFIX + record_table[TAXONOMY_ID_UNIPROT_COLUMN][0]
            )
            # Define the output file path
            output_file = UNIPROT_TREMBL_TMP_DIR / f"{str(path).split('/')[-3]}.tsv"

            # Check if the file already exists to avoid writing headers multiple times
            file_exists = output_file.exists()

            with open(output_file, "a" if file_exists else "w", newline="") as file:
                csv_writer = csv.writer(file, delimiter="\t")

                # Write the header only if the file is being created
                if not file_exists:
                    csv_writer.writerow(record_attributes)

                # Write the record values based on the order of the headers
                csv_writer.writerow([record_table[attr] for attr in record_attributes])
