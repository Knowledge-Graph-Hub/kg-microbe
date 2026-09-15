"""The public merge gate rejects stale prepared dependencies before KGX (#1092)."""

import inspect
import json
import shutil
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from kg_microbe.merge_utils import merge_kg
from kg_microbe.run import main
from kg_microbe.transform import DATA_SOURCES
from kg_microbe.transform_utils.transform import Transform
from kg_microbe.utils.source_finalization import SourceFinalizationRequired
from kg_microbe.utils.transform_fingerprint import upstream_fingerprint, write_fingerprint

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "resources/merge_source_freshness"


def record_source(transform):
    """Write the actual registered producer's metadata over the isolated fixture graph."""
    cls = type(transform)
    return write_fingerprint(
        transform.output_dir,
        Path(inspect.getsourcefile(cls)).parent,
        ROOT,
        cls.DATA_INPUTS,
        cls.TRANSFORM_INPUTS,
        input_dir=transform.input_base_dir,
        finalization_inputs=transform.finalization_inputs,
    )


def prepare_source(tmp_path, source, *, prefix="", marker=True, output_name=None):
    """Finalize immutable tiny TSVs with a real producer class, never its constructor or run method."""
    raw = tmp_path / "raw"
    raw.mkdir(exist_ok=True)
    cls = DATA_SOURCES[source].transform_class
    transform = cls.__new__(cls)
    Transform.__init__(transform, output_name or source, raw, tmp_path / "transformed")
    for kind in ("nodes", "edges"):
        shutil.copyfile(FIXTURES / f"{kind}.tsv", transform.output_dir / f"{prefix}{kind}.tsv")
    for role in getattr(cls, "REQUIRED_CONSUMED_INPUTS", ()):
        assert role == "bacdive_taxon_lookup", f"Fixture needs an explicit immutable input for {role}"
        lookup = tmp_path / f"{source}-bacdive-lookup.tsv"
        shutil.copyfile(FIXTURES / "lookup.tsv", lookup)
        with transform.consume_input(role, lookup) as reader:
            reader.read()
    transform.finalize(file_prefix=prefix, fresh_run=True)
    if marker:
        record_source(transform)
    return transform


def merge_config(tmp_path, transforms, *, diagnostic=False):
    """Select explicit fixture paths, using unrelated config labels to prevent path-name inference."""
    config = tmp_path / "merge.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "configuration": {
                    "output_directory": str(tmp_path / "published"),
                    "allow_unfinalized_sources": diagnostic,
                },
                "merged_graph": {
                    "name": "fixture",
                    "source": {
                        f"selected_{index}": {
                            "input": {
                                "format": "tsv",
                                "filename": [str(path) for path in transform.output_dir.glob("*nodes.tsv")]
                                + [str(path) for path in transform.output_dir.glob("*edges.tsv")],
                            }
                        }
                        for index, transform in enumerate(transforms)
                    },
                    "destination": {"tsv": {"format": "tsv", "filename": "fixture"}},
                },
            }
        ),
        encoding="utf-8",
    )
    return config


@pytest.fixture
def prepared(tmp_path):
    """Provide every declared upstream marker, initially current with exact prepared bytes."""
    sources = {
        source: prepare_source(tmp_path, source) for source in ("ontologies", "bacdive", "mediadive", "bactotraits")
    }
    lookup = tmp_path / "bacdive.tsv"
    shutil.copyfile(FIXTURES / "lookup.tsv", lookup)
    sources["bacdive"].finalization_inputs = (*sources["bacdive"].finalization_inputs, str(lookup))
    for source in ("bacdive", "mediadive", "bactotraits"):
        record_source(sources[source])
    return sources


@pytest.mark.parametrize("source", ["mediadive", "bactotraits"])
def test_changed_upstream_marker_blocks_cli_and_api_before_kgx(tmp_path, monkeypatch, prepared, source):
    """An upstream-only change rejects unchanged consumer bytes and preserves a published archive."""
    consumer = prepared[source]
    config = merge_config(tmp_path, [consumer])
    merge_kg._assert_sources_finalized(str(config))
    original = {path.name: path.read_bytes() for path in consumer.output_dir.iterdir()}
    marker = json.loads((consumer.output_dir / "source_fingerprint.json").read_text())
    shutil.copyfile(FIXTURES / "changed_lookup.tsv", tmp_path / "bacdive.tsv")
    record_source(prepared["bacdive"])
    assert marker["upstream"] != upstream_fingerprint(consumer.output_base_dir, type(consumer).TRANSFORM_INPUTS)
    published = tmp_path / "published/fixture.tar.gz"
    published.parent.mkdir()
    published.write_bytes(b"previous complete archive")

    def unexpected_kgx(*args, **kwargs):
        """Fail if the required gate admits stale upstream evidence."""
        raise AssertionError("KGX must not run")

    monkeypatch.setattr(merge_kg, "merge", unexpected_kgx)
    with pytest.raises(SourceFinalizationRequired, match="upstream"):
        merge_kg.load_and_merge(str(config))
    result = CliRunner().invoke(main, ["merge", "-y", str(config)])
    assert isinstance(result.exception, SourceFinalizationRequired)
    assert "upstream" in str(result.exception)
    assert original == {path.name: path.read_bytes() for path in consumer.output_dir.iterdir()}
    assert published.read_bytes() == b"previous complete archive"


@pytest.mark.parametrize("damage", ["missing", "unsupported"])
def test_missing_or_unsupported_upstream_marker_is_required(tmp_path, prepared, damage):
    """A recorded upstream cannot turn into an unknown absence accepted by production merge."""
    config = merge_config(tmp_path, [prepared["mediadive"]])
    marker = prepared["bacdive"].output_dir / "source_fingerprint.json"
    if damage == "missing":
        marker.unlink()
    else:
        payload = json.loads(marker.read_text())
        payload["version"] = 999
        marker.write_text(json.dumps(payload))
    with pytest.raises(SourceFinalizationRequired, match="upstream|fingerprint"):
        merge_kg._assert_sources_finalized(str(config))


def test_scoped_ontology_requires_whole_producer_schema_evidence(tmp_path, capsys):
    """A scoped graph record alone cannot prove missing producer or pinned-schema freshness."""
    ontology = prepare_source(tmp_path, "ontologies", prefix="pato_", marker=False)
    direct = merge_config(tmp_path, [ontology])
    with pytest.raises(SourceFinalizationRequired, match="whole producer/schema.*kg transform -s ontologies"):
        merge_kg._assert_sources_finalized(str(direct))
    diagnostic = merge_config(tmp_path, [ontology], diagnostic=True)
    merge_kg._assert_sources_finalized(str(diagnostic))
    assert "DIAGNOSTIC OPT-OUT" in capsys.readouterr().out
    consumer = prepare_source(tmp_path, "bacdive")
    config = merge_config(tmp_path, [consumer])
    with pytest.raises(SourceFinalizationRequired, match="upstream|whole|fingerprint"):
        merge_kg._assert_sources_finalized(str(config))


def test_only_explicit_diagnostic_opt_out_bypasses_dependency_gate(tmp_path, prepared, capsys):
    """The documented diagnostic flag remains conspicuous, never inferred from fixture paths."""
    (prepared["bacdive"].output_dir / "source_fingerprint.json").unlink()
    config = merge_config(tmp_path, [prepared["mediadive"]], diagnostic=True)
    merge_kg._assert_sources_finalized(str(config))
    assert "DIAGNOSTIC OPT-OUT" in capsys.readouterr().out


def test_prego_alias_uses_producer_metadata_not_directory_or_config_label(tmp_path):
    """Habitat-only PREGO output belongs to the registered prego producer."""
    prepare_source(tmp_path, "ontologies")
    source = prepare_source(tmp_path, "prego", output_name="prego_habitat")
    config = merge_config(tmp_path, [source])
    merge_kg._assert_sources_finalized(str(config))


def test_bakta_selected_dataset_uses_parent_producer_marker(tmp_path):
    """The explicit dataset protocol keeps local graph evidence and aggregate producer freshness."""
    raw = tmp_path / "raw"
    raw.mkdir()
    cls = DATA_SOURCES["bakta"].transform_class
    source = cls.__new__(cls)
    Transform.__init__(source, "bakta", raw, tmp_path / "transformed")
    dataset = source.output_dir / "selected_dataset"
    dataset.mkdir()
    for kind in ("nodes", "edges"):
        shutil.copyfile(FIXTURES / f"{kind}.tsv", dataset / f"{kind}.tsv")
    source.finalization_output_dirs = [dataset]
    source.finalize(fresh_run=True)
    record_source(source)
    config = merge_config(tmp_path, [source])
    payload = yaml.safe_load(config.read_text())
    payload["merged_graph"]["source"]["selected_0"]["input"]["filename"] = [
        str(dataset / "nodes.tsv"),
        str(dataset / "edges.tsv"),
    ]
    config.write_text(yaml.safe_dump(payload))
    merge_kg._assert_sources_finalized(str(config))


def test_valid_scoped_record_supersedes_stale_whole_ontology_record(tmp_path):
    """A stale full record must not shadow a current explicitly selected ontology bundle."""
    source = prepare_source(tmp_path, "ontologies", prefix="pato_", marker=False)
    source.finalize(fresh_run=True)
    record_source(source)
    nodes = source.output_dir / "pato_nodes.tsv"
    nodes.write_text(nodes.read_text().replace("One", "Updated"))
    source.finalize(file_prefix="pato_", fresh_run=True)
    config = merge_config(tmp_path, [source])
    merge_kg._assert_sources_finalized(str(config))


@pytest.mark.parametrize("schema", [None, {"version": "unknown", "digest": "matching-but-unproven"}])
def test_scoped_ontology_rejects_matching_unknown_schema(tmp_path, monkeypatch, schema):
    """Two matching unknown schema values cannot supply affirmative schema provenance."""
    from kg_microbe.merge_utils import source_freshness

    source = prepare_source(tmp_path, "ontologies", prefix="pato_")
    marker_path = source.output_dir / "source_fingerprint.json"
    marker = json.loads(marker_path.read_text())
    marker["schema"] = schema
    marker_path.write_text(json.dumps(marker))
    monkeypatch.setattr(source_freshness, "schema_fingerprint", lambda root: schema)
    config = merge_config(tmp_path, [source])
    with pytest.raises(SourceFinalizationRequired, match="schema"):
        merge_kg._assert_sources_finalized(str(config))


def test_unknown_producer_metadata_is_not_a_silent_exemption(tmp_path):
    """Unregistered external graphs require the explicit diagnostic opt-out, not guessed freshness."""
    raw = tmp_path / "raw"
    raw.mkdir()
    source = Transform("unknown", raw, tmp_path / "transformed")
    for kind in ("nodes", "edges"):
        shutil.copyfile(FIXTURES / f"{kind}.tsv", source.output_dir / f"{kind}.tsv")
    source.finalize(fresh_run=True)
    config = merge_config(tmp_path, [source])
    with pytest.raises(SourceFinalizationRequired, match="Unsupported producer metadata"):
        merge_kg._assert_sources_finalized(str(config))
