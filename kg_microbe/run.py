"""Drive KG download, transform, merge steps."""

import os
import warnings

import click

# Suppress deprecated pkg_resources warning from eutils (transitive dependency via oaklib)
# eutils is unmaintained and uses deprecated API, but doesn't affect functionality
warnings.filterwarnings("ignore", message=".*pkg_resources is deprecated.*", category=UserWarning)

show_status_option = click.option("--show-status/--no-show-status", default=True)


@click.group()
def main():
    """CLI."""
    pass


@main.command()
@click.option("yaml_file", "-y", required=True, default="download.yaml", type=click.Path(exists=True))
@click.option("output_dir", "-o", required=True, default="data/raw")
@click.option(
    "snippet_only",
    "-x",
    is_flag=True,
    default=False,
    help="Download only the first 5 kB of each (uncompressed) source,\
    for testing and file checks [false]",
)
@click.option(
    "ignore_cache",
    "-i",
    is_flag=True,
    default=False,
    help="ignore cache and download files even if they exist [false]",
)
@click.option(
    "tags",
    "-t",
    "--tag",
    multiple=True,
    help="only download sources with this tag (repeatable); omit for all. See the tag list in download.yaml's header.",
)
def download(*args, **kwargs) -> None:
    """
    Download from list of URLs (default: download.yaml) into data directory (default: data/raw).

    :param yaml_file: Specify the YAML file containing a list of datasets to download.
    :param output_dir: A string pointing to the directory to download data to.
    :param snippet_only: Download 5 kB of each uncompressed source, for testing and file checks.
    :param ignore_cache: If specified, will ignore existing files and download again.
    :param tags: Restrict the run to sources carrying these tags (all sources if empty).
    :raises click.BadParameter: If a requested tag matches no entry in the YAML.
    :return: None
    """
    from kg_microbe import download as kg_download
    from kg_microbe.download import UnknownDownloadTagError

    try:
        kg_download(*args, **kwargs)
    except UnknownDownloadTagError as e:
        # An unknown -t value is user error, not a crash — report it as such.
        # Deliberately narrow: a blanket `except ValueError` also caught
        # JSONDecodeError and pydantic ValidationError from deeper in the
        # download and mislabelled them as bad tags, hiding the traceback.
        raise click.BadParameter(str(e)) from e

    return None


@main.command()
@click.option("input_dir", "-i", default="data/raw", type=click.Path(exists=True))
@click.option("output_dir", "-o", default="data/transformed")
@click.option("sources", "-s", default=None, multiple=True)
@show_status_option
def transform(*args, **kwargs) -> None:
    """
    Call project_name/transform/[source name]/ for node & edge transforms.

    :param input_dir: A string pointing to the directory to import data from.
    :param output_dir: A string pointing to the directory to output data to.
    :param sources: A list of sources to transform.
    :return: None
    """
    from kg_microbe.transform import transform as kg_transform

    try:
        kg_transform(*args, **kwargs)
    except ValueError as e:
        raise click.BadParameter(str(e), param_hint="--sources") from e

    return None


@main.command()
@click.option("yaml", "-y", default="merge.yaml", type=click.Path(exists=True))
@click.option("processes", "-p", default=1, type=int)
@click.option(
    "sources",
    "-s",
    "--source",
    multiple=True,
    help="Merge only these sources from the config (repeatable). Omit to merge all.",
)
def merge(yaml: str, processes: int, sources: tuple) -> None:
    """
    Use KGX to load subgraphs to create a merged graph.

    Restricting to a subset with ``-s`` allows a staged merge, which is the
    only way to keep a very large source from being resident at the same
    time as every other one — KGX collects all source graphs in the parent
    before combining them.

    :param yaml: A string pointing to a KGX compatible config YAML.
    :param processes: Number of processes to use.
    :param sources: Source keys to merge; empty means all.
    :return: None
    """
    from kg_microbe.merge_utils.merge_kg import load_and_merge

    load_and_merge(yaml, processes, list(sources) or None)


@main.command(name="query-organism")
@click.argument("organism_name", required=True)
@click.option(
    "--db-path",
    "-d",
    default="data/merged/kg-microbe.duckdb",
    help="DuckDB database path",
)
@click.option(
    "--nodes-path",
    "-n",
    default="data/merged/merged-kg_nodes.tsv",
    help="Nodes TSV path",
)
@click.option(
    "--edges-path",
    "-e",
    default="data/merged/merged-kg_edges.tsv",
    help="Edges TSV path",
)
@click.option("--output", "-o", default=None, help="Output markdown file")
@click.option("--force-reload", is_flag=True, help="Force database reload")
def query_organism(
    organism_name: str,
    db_path: str,
    nodes_path: str,
    edges_path: str,
    output: str,
    force_reload: bool,
) -> None:
    """Query organism information and media preferences from KG-Microbe."""
    from kg_microbe.query_utils.duckdb_loader import get_or_create_database
    from kg_microbe.query_utils.organism_queries import query_organism_full
    from kg_microbe.query_utils.utils import format_organism_report

    # Connect to database (creates if needed)
    click.echo("Loading KG-Microbe database...")
    try:
        conn = get_or_create_database(nodes_path, edges_path, db_path, force_reload)
    except Exception as e:
        raise click.ClickException(f"Error loading database: {e}") from e

    # Query organism
    click.echo(f"Querying organism: {organism_name}")
    try:
        result = query_organism_full(conn, organism_name)
    except ValueError as e:
        conn.close()
        raise click.ClickException(str(e)) from e
    except Exception as e:
        conn.close()
        raise click.ClickException(f"Query failed: {e}") from e

    # Format output
    report = format_organism_report(result)

    if output:
        with open(output, "w") as f:
            f.write(report)
        click.echo(f"✅ Report saved to {output}")
    else:
        click.echo("\n" + report)

    conn.close()


@main.command()
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
    Perform a query of knowledge graph using a class contained in query_utils.

    :param yaml: A YAML file containing a SPARQL query (see queries/sparql/ for examples)
    :param output_dir: Directory to output results of query
    :param query_key: the key in the yaml file containing the query string
    :param endpoint_key: the key in the yaml file containing the sparql endpoint URL
    :param outfile_ext: file extension for output file [.tsv]
    :return: None.
    """
    from kg_microbe.query import parse_query_yaml, result_dict_to_tsv, run_query

    query = parse_query_yaml(yaml)
    result_dict = run_query(query=query[query_key], endpoint=query[endpoint_key])
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    outfile = os.path.join(output_dir, os.path.splitext(os.path.basename(yaml))[0] + outfile_ext)
    result_dict_to_tsv(result_dict, outfile)


if __name__ == "__main__":
    main()
