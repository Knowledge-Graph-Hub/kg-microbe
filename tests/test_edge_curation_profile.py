"""Planning profiles must count literal KGX cells, not reinterpret CSV quoting (#1719)."""

import copy
import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/adhoc/profile_edge_curation_snapshot.py"
SPEC = importlib.util.spec_from_file_location("edge_curation_profile", SCRIPT)
profiler = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(profiler)


@pytest.fixture
def source(tmp_path):
    """Create literal-quote rows that a CSV quoting reader would alter or combine."""
    header = (
        b"subject\tpredicate\tobject\trelation\tprimary_knowledge_source\tknowledge_level\tagent_type\tdescription\n"
    )
    prefix = b"fixture:s\tMETPO:1\tfixture:o\tRO:1\tinfores:fixture\tobservation\tmanual_agent\t"
    edges = header + prefix + b'""\n' + prefix + b'"unclosed\n' + prefix + b"next physical row\n"
    nodes = b'id\tcategory\tname\nfixture:s\tbiolink:OrganismTaxon\t""\n'
    members = {}
    for name, raw in (("merged-kg_edges.tsv", edges), ("merged-kg_nodes.tsv", nodes)):
        (tmp_path / name).write_bytes(raw)
        members[name] = {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw), "rows": raw.count(b"\n") - 1}
    (tmp_path / "manifest.json").write_text(json.dumps({"manifest_version": 1, "members": members}))
    return tmp_path


def test_literal_quotes_are_nonempty_and_do_not_consume_following_rows(source):
    """All physical rows and literal two-quote cells survive while byte hashes still agree."""
    result = profiler.profile(source, 0)
    edges = result["members"]["merged-kg_edges.tsv"]
    nodes = result["members"]["merged-kg_nodes.tsv"]
    assert edges["rows"] == 3
    assert edges["nonempty_fields"]["description"] == 3
    assert edges["counts"]["predicate"] == {"METPO:1": 3}
    assert nodes["nonempty_fields"]["name"] == 1
    for name, member in result["members"].items():
        raw = (source / name).read_bytes()
        assert member["row_width_errors"] == 0
        assert member["matches_manifest"] is True
        assert member["sha256"] == hashlib.sha256(raw).hexdigest()
        assert member["bytes_read"] == len(raw)


def test_comparison_ignores_timings_but_detects_false_empty_coverage(source):
    """Identical bytes are insufficient when a parser has changed measured fields."""
    current = profiler.profile(source, 0)
    previous = copy.deepcopy(current)
    previous["acquired_at"] = "earlier"
    previous["members"]["merged-kg_edges.tsv"]["elapsed_seconds"] = 999
    assert profiler.compare_profiles(previous, current)["statistics_equal"] is True
    previous["members"]["merged-kg_edges.tsv"]["nonempty_fields"]["description"] = 2
    comparison = profiler.compare_profiles(previous, current)
    assert comparison["statistics_equal"] is False
    edge_comparison = comparison["members"]["merged-kg_edges.tsv"]
    assert edge_comparison["changed_fields"] == ["nonempty_fields"]
    assert edge_comparison["raw_counts_equal"] is True
    assert edge_comparison["nonempty_fields_equal"] is False


def test_partial_profile_cannot_certify_count_equality(source):
    """A prefix scan cannot establish equality with a complete historical measurement."""
    current = profiler.profile(source, 0)
    partial = profiler.profile(source, 1)
    with pytest.raises(ValueError, match="complete manifest-verified"):
        profiler.compare_profiles(partial, current)


@pytest.mark.parametrize("invalid", [None, [], "text", 17, True])
def test_cli_rejects_nonobject_comparison_before_scanning(tmp_path, invalid):
    """An explicit invalid baseline cannot silently disable comparison or start a scan."""
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps(invalid), encoding="utf-8")
    output = tmp_path / "not-created" / "profile.json"
    result = subprocess.run(  # noqa: S603 - fixed interpreter/script and test-owned paths
        [
            sys.executable,
            "-S",
            str(SCRIPT),
            str(tmp_path / "missing-snapshot"),
            str(output),
            "--compare-profile",
            str(baseline),
        ],
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    assert result.returncode == 2
    assert "--compare-profile must contain a JSON object" in result.stderr
    assert result.stdout == ""
    assert not output.parent.exists()
    assert baseline.read_text(encoding="utf-8") == json.dumps(invalid)
