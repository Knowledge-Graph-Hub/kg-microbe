"""Node provenance must survive source ingestion, overlap and archive export (#1049)."""

import csv
import io
import tarfile
from multiprocessing.pool import ThreadPool

import yaml


def test_real_kgx_merge_preserves_node_sources(tmp_path, monkeypatch):
    """Exercise KGX's actual merge path, using threads only to keep fixtures hermetic."""
    from kg_microbe.utils.biolink_model import prepare_kgx

    prepare_kgx()
    from kgx.cli import cli_utils

    from kg_microbe.merge_utils.merge_kg import merge

    monkeypatch.setattr("kgx.prefix_manager.get_jsonld_context", lambda: {"@context": {}})
    monkeypatch.setattr(cli_utils, "Pool", ThreadPool)
    sources = {}
    for source in ("alpha", "beta"):
        nodes = tmp_path / f"{source}_nodes.tsv"
        edges = tmp_path / f"{source}_edges.tsv"
        nodes.write_text(
            "id\tcategory\tname\tprovided_by\n"
            f"NCBITaxon:1\tbiolink:OrganismTaxon\tshared\tinfores:{source}\n"
            f"NCBITaxon:{source}\tbiolink:OrganismTaxon\t{source}\tinfores:{source}\n",
            encoding="utf-8",
        )
        edges.write_text(
            "subject\tpredicate\tobject\tprimary_knowledge_source\n"
            f"NCBITaxon:{source}\tbiolink:subclass_of\tNCBITaxon:1\tinfores:{source}\n",
            encoding="utf-8",
        )
        sources[source] = {"input": {"format": "tsv", "filename": [str(nodes), str(edges)]}}
    config = tmp_path / "merge.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "configuration": {"output_directory": str(tmp_path)},
                "merged_graph": {
                    "source": sources,
                    "destination": {"tsv": {"format": "tsv", "compression": "tar.gz", "filename": "merged"}},
                },
            }
        ),
        encoding="utf-8",
    )
    graph = merge(str(config))
    assert set(graph.nodes()["NCBITaxon:1"]["provided_by"]) == {"infores:alpha", "infores:beta"}
    with tarfile.open(tmp_path / "merged.tar.gz") as archive:
        with archive.extractfile("merged_nodes.tsv") as handle:
            rows = {row["id"]: row for row in csv.DictReader(io.TextIOWrapper(handle), delimiter="\t")}
    assert set(rows["NCBITaxon:1"]["provided_by"].split("|")) == {"infores:alpha", "infores:beta"}
    assert rows["NCBITaxon:alpha"]["provided_by"] == "infores:alpha"
    assert rows["NCBITaxon:beta"]["provided_by"] == "infores:beta"


def test_export_provenance_override_is_restored_on_failure(monkeypatch):
    """The compatibility shim must not change later KGX calls after an exception."""
    import pytest

    from kg_microbe.utils.biolink_model import prepare_kgx

    prepare_kgx()
    from kgx import transformer as transformer_module
    from kgx.cli import cli_utils

    from kg_microbe.merge_utils.merge_kg import merge

    original = cli_utils.Transformer
    parser = cli_utils.parse_source
    graph_merger = cli_utils.merge_all_graphs
    sink = transformer_module.GraphSink
    graph_source = transformer_module.SOURCE_MAP["graph"]
    tsv_sinks = {name: transformer_module.SINK_MAP[name] for name in ("tsv", "csv")}

    def fail(*args, **kwargs):
        """Simulate a KGX failure after the scoped adapters have been installed."""
        raise RuntimeError("failed merge")

    monkeypatch.setattr(cli_utils, "merge", fail)
    with pytest.raises(RuntimeError, match="failed merge"):
        merge("unused.yaml")
    assert cli_utils.Transformer is original
    assert cli_utils.parse_source is parser
    assert cli_utils.merge_all_graphs is graph_merger
    assert transformer_module.GraphSink is sink
    assert transformer_module.SOURCE_MAP["graph"] is graph_source
    assert all(transformer_module.SINK_MAP[name] is sink for name, sink in tsv_sinks.items())
