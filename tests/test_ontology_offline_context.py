"""Real ontology KGX conversion must scope pinned prefixes without remote cache seeds."""

import csv
from pathlib import Path

import pytest
import requests

from kg_microbe.transform_utils.ontologies.ontologies_transform import _run_kgx_transform
from kg_microbe.utils.transform_fingerprint import shared_code_fingerprint

RESOURCES = Path(__file__).parent / "resources"
OBOJSON = RESOURCES / "ontology_offline_context/prefixes.json"
CONTEXT_NAMES = ("biolink", "monarch_context", "obo_context")


@pytest.fixture(autouse=True)
def pinned_namespace_fixture(monkeypatch):
    """Exercise installed default namespace maps plus an explicit pinned Biolink override."""
    monkeypatch.setenv("KG_MICROBE_BIOLINK_MODEL", str(RESOURCES / "merge_offline_context/biolink-model.yaml"))


def _rows(path):
    """Read only the tiny real converter output with its declared legacy TSV quoting."""
    with path.open(newline="") as stream:
        return list(csv.DictReader(stream, delimiter="\t"))


@pytest.mark.parametrize("prior_context", [False, True, "mixed"], ids=["absent", "present", "mixed"])
@pytest.mark.parametrize("conversion_failure", [False, True])
def test_real_ontology_conversion_is_offline_and_restores_exact_context(
    tmp_path, monkeypatch, prior_context, conversion_failure
):
    """No cache seed or substituted JSON-LD reader may hide the actual OBOJSON→TSV boundary."""
    from kg_microbe.utils.biolink_model import prepare_kgx

    prepare_kgx()
    from kgx import config, prefix_manager
    from kgx.transformer import Transformer

    contexts = config.jsonld_context_map
    previous = {
        name: {"biolink": f"https://prior-context.invalid/{name}/", "GO": f"urn:prior-{name}-go:"}
        for name in CONTEXT_NAMES
    }
    present = (
        set(CONTEXT_NAMES) if prior_context is True else {"monarch_context"} if prior_context == "mixed" else set()
    )
    unrelated = {"unrelated": "urn:unrelated:"}
    monkeypatch.setitem(contexts, "ontology-unrelated-context", unrelated)
    for name in CONTEXT_NAMES:
        if name in present:
            monkeypatch.setitem(contexts, name, previous[name])
        else:
            monkeypatch.delitem(contexts, name, raising=False)
    original_reader = prefix_manager.get_jsonld_context
    requested = []

    def reject_http(*args, **kwargs):
        """Record and fail every HTTP attempt rather than returning a fabricated context."""
        requested.append((args, kwargs))
        raise AssertionError("Ontology conversion attempted HTTP for a prefix context")

    monkeypatch.setattr(requests.sessions.Session, "request", reject_http)
    real_transform = Transformer.transform
    completed_conversions = []
    if conversion_failure:

        def fail_after_real_conversion(self, **kwargs):
            """Fail inside the production wrapper after actual KGX parsing/export succeeds."""
            result = real_transform(self, **kwargs)
            completed_conversions.append(result)
            assert contexts["biolink"]["biolink"] == "https://w3id.org/biolink/vocab/"
            assert contexts["biolink"]["GO"] == "http://purl.obolibrary.org/obo/GO_"
            raise OSError("injected ontology conversion failure")

        monkeypatch.setattr(Transformer, "transform", fail_after_real_conversion)
    output = tmp_path / "converted"
    kwargs = {"inputs": [OBOJSON], "input_format": "obojson", "output": output, "output_format": "tsv"}
    if conversion_failure:
        with pytest.raises(OSError, match="injected ontology conversion failure"):
            _run_kgx_transform(**kwargs)
        assert len(completed_conversions) == 1
    else:
        _run_kgx_transform(**kwargs)
    assert not requested
    assert {row["id"] for row in _rows(tmp_path / "converted_nodes.tsv")} == {
        "GO:0008152",
        "CHEBI:15377",
        "NCBITaxon:287",
        "biolink:NamedThing",
        "https://unmapped-ontology.invalid/term/Unknown",
    }
    assert {
        (row["subject"], row["predicate"], row["object"], row["relation"])
        for row in _rows(tmp_path / "converted_edges.tsv")
    } == {
        ("NCBITaxon:287", "biolink:related_to", "GO:0008152", "biolink:related_to"),
        ("GO:0008152", "biolink:related_to", "CHEBI:15377", "biolink:related_to"),
        (
            "https://unmapped-ontology.invalid/term/Unknown",
            "biolink:related_to",
            "biolink:NamedThing",
            "biolink:related_to",
        ),
    }
    assert config.jsonld_context_map is contexts
    assert contexts["ontology-unrelated-context"] is unrelated
    for name in CONTEXT_NAMES:
        if name in present:
            assert contexts[name] is previous[name]
        else:
            assert name not in contexts
    assert prefix_manager.get_jsonld_context is original_reader


@pytest.mark.parametrize("missing_input", ["KG_MICROBE_BIOLINK_MODEL", "KG_MICROBE_BIOLINK_PREDICATE_MAP"])
def test_missing_pinned_input_aborts_before_ontology_converter(tmp_path, monkeypatch, missing_input):
    """An absent local schema or predicate map cannot fall back to remote KGX defaults."""
    from kg_microbe.utils.biolink_model import prepare_kgx

    prepare_kgx()
    from kgx.config import jsonld_context_map
    from kgx.transformer import Transformer

    previous = {"caller": "urn:caller:"}
    monkeypatch.setitem(jsonld_context_map, "biolink", previous)
    monkeypatch.setenv(missing_input, str(tmp_path / "missing.yaml"))

    def unexpected_conversion(self, **kwargs):
        """Reject conversion once pinned authority preflight fails."""
        pytest.fail("Missing pinned input reached KGX conversion")

    monkeypatch.setattr(Transformer, "transform", unexpected_conversion)
    with pytest.raises(FileNotFoundError, match="Pinned Biolink"):
        _run_kgx_transform(inputs=[OBOJSON], input_format="obojson", output=tmp_path / "out", output_format="tsv")
    assert jsonld_context_map["biolink"] is previous
    assert not list(tmp_path.iterdir())


def test_local_context_behavior_is_in_shared_source_fingerprint(tmp_path):
    """Changing a helper now consumed by ontology transforms must invalidate source markers."""
    helper = tmp_path / "kg_microbe/merge_utils/local_context.py"
    helper.parent.mkdir(parents=True)
    helper.write_text("PREFIX_POLICY = 1\n")
    before = shared_code_fingerprint(tmp_path)
    helper.write_text("PREFIX_POLICY = 2\n")
    assert shared_code_fingerprint(tmp_path) != before
