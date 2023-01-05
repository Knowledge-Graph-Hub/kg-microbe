"""Run script with CLI."""

import os

import click

from kg_microbe import download as kg_download
from kg_microbe import transform as kg_transform
from kg_microbe.merge_utils.merge_kg import load_and_merge
from kg_microbe.query import parse_query_yaml, result_dict_to_tsv, run_query
from kg_microbe.transform import DATA_SOURCES


@click.group()
def cli():
    pass


@cli.command()
@click.option(
    "yaml_file",
    "-y",
    required=True,
    default="download.yaml",
    type=click.Path(exists=True),
)
@click.option("output_dir", "-o", required=True, default="data/raw")
@click.option(
    "ignore_cache",
    "-i",
    is_flag=True,
    default=False,
    help="ignore cache and download files even if they exist [false]",
)
def download(*args, **kwargs) -> None:
    """
    Downloads data files from list of URLs (default: download.yaml) into data
    directory (default: data/raw).

    :param yaml_file: Specify the YAML file containing a list of datasets to download.
    :param output_dir: A string pointing to the directory to download data to.
    :param ignore_cache: If specified, will ignore existing files and download again.
    :return: None.
    """

    kg_download(*args, **kwargs)

    return None


@cli.command()
@click.option("input_dir", "-i", default="data/raw", type=click.Path(exists=True))
@click.option("output_dir", "-o", default="data/transformed")
@click.option(
    "sources", "-s", default=None, multiple=True, type=click.Choice(DATA_SOURCES.keys())
)
def transform(*args, **kwargs) -> None:
    """
    Calls scripts in kg_microbe/transform/[source name]/ to transform each source
    into nodes and edges.

    :param input_dir: A string pointing to the directory to import data from.
    :param output_dir: A string pointing to the directory to output data to.
    :param sources: A list of sources to transform.
    :return: None.
    """

    # call transform script for each source
    kg_transform(*args, **kwargs)

    return None


@cli.command()
@click.option("yaml", "-y", default="merge.yaml", type=click.Path(exists=True))
@click.option("processes", "-p", default=1, type=int)
def merge(yaml: str, processes: int) -> None:
    """
    Use KGX to load subgraphs to create a merged graph.

    :param yaml: A string pointing to a KGX compatible config YAML.
    :param processes: Number of processes to use.
    :return: None.
    """

    load_and_merge(yaml, processes)


@cli.command()
@click.option("yaml", "-y", required=True, default=None, multiple=False)
@click.option("output_dir", "-o", default="data/queries/")
def query(
    yaml: str,
    output_dir: str,
    query_key: str = "query",
    endpoint_key: str = "endpoint",
    outfile_ext: str = ".tsv",
) -> None:
    """
    Perform a query of knowledge graph using a class contained in query_utils

    :param yaml: A YAML file containing a SPARQL query (see queries/sparql/ for examples)
    :param output_dir: Directory to output results of query
    :param query_key: the key in the yaml file containing the query string
    :param endpoint_key: the key in the yaml file containing the sparql endpoint URL
    :param outfile_ext: file extension for output file [.tsv]
    :return: None.
    """

    query = parse_query_yaml(yaml)
    result_dict = run_query(query=query[query_key], endpoint=query[endpoint_key])
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    outfile = os.path.join(
        output_dir, os.path.splitext(os.path.basename(yaml))[0] + outfile_ext
    )
    result_dict_to_tsv(result_dict, outfile)


if __name__ == "__main__":
    cli()
