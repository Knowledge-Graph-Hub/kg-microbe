"""Query module."""
import logging

import yaml
from SPARQLWrapper import JSON, SPARQLWrapper  # type: ignore


def run_query(query: str, endpoint: str, return_format=JSON) -> dict:
    """
    Run a SPARQL query and return the results as a dictionary.

    :param query: SPARQL query to run.
    :param endpoint: SPARQL endpoint to query.
    :param return_format: Format of the returned data.
    :return: A dictionary of results from the SPARQL query.
    """
    sparql = SPARQLWrapper(endpoint)
    sparql.setQuery(query)
    sparql.setReturnFormat(return_format)
    results = sparql.query().convert()

    return results  # type: ignore


def parse_query_yaml(yaml_file) -> dict:
    """
    Parse a YAML file and return the results as a dictionary.

    :param yaml_file: YAML file to parse.
    :return: A dictionary of results from the YAML file.
    """
    return yaml.safe_load(open(yaml_file))  # type: ignore


def result_dict_to_tsv(result_dict: dict, outfile: str) -> None:
    """
    Write a dictionary to a TSV file.

    :param result_dict: Dictionary to write to TSV file.
    :param outfile: TSV file to write to.
    """
    with open(outfile, "wt") as f:
        # header
        f.write("\t".join(result_dict["head"]["vars"]) + "\n")
        for row in result_dict["results"]["bindings"]:
            row_items = []
            for col in result_dict["head"]["vars"]:
                try:
                    row_items.append(row[col]["value"])
                except KeyError:
                    logging.error(
                        "Problem retrieving result for col %s in row %s" % (col, "\t".join(row))
                    )
                    row_items.append("ERROR")
            try:
                f.write("\t".join(row_items) + "\n")
            except Exception as e:
                print(e)
