"""Offline error-envelope and exact byte-bound controls for the finite source probe."""

import io
import json
from pathlib import Path

import pytest

from scripts.adhoc import kgm_mediadive_sparql_probe_20261105 as probe

FIXTURE = json.loads((Path(__file__).parent / "resources/mediadive_sparql_probe_20261105.json").read_text())


@pytest.mark.parametrize("name", ["stats", "legacy_stats"])
def test_documented_stats_shapes(name):
    """Both current and legacy field names used by the official client are recognized."""
    probe.validate_stats(FIXTURE[name])


@pytest.mark.parametrize(
    "mutation",
    [
        {"status": "ERROR"},
        {"exception": "failure"},
        {"error": None},
        {"num-triples-normal": True},
        {"num-permutations": True},
        {"name-index": None},
    ],
)
def test_stats_errors_and_invalid_fields_are_refused(mutation):
    """HTTP200 success cannot mask an error or unknown metadata shape."""
    with pytest.raises(ValueError):
        probe.validate_stats({**FIXTURE["stats"], **mutation})


def test_unknown_stats_shape_is_not_verified():
    """An arbitrary JSON object does not establish successful index metadata."""
    with pytest.raises(ValueError):
        probe.validate_stats({"data": []})


@pytest.mark.parametrize("chunks", [[b"abc", b"def"], [b"abcdef"], [b"abcdef", b""]])
def test_exact_limit_is_retained(chunks):
    """Exact-limit complete input retains every byte without a truncation claim."""
    target = io.BytesIO()
    assert probe.write_bounded(chunks, target, 6) == 6
    assert target.getvalue() == b"abcdef"


@pytest.mark.parametrize("chunks", [[b"abc", b"defg"], [b"abcdefg"], [b"abcdef", b"g"]])
def test_over_limit_retains_only_bounded_prefix(chunks):
    """No chunk can overshoot the written evidence ceiling, and excess always fails."""
    target = io.BytesIO()
    with pytest.raises(ValueError, match="byte ceiling"):
        probe.write_bounded(chunks, target, 6)
    assert target.getvalue() == b"abcdef"


def test_official_unnamed_index_is_metadata_not_identity():
    """The official client permits unnamed indexes; counts establish no dataset freshness."""
    probe.validate_stats({**FIXTURE["stats"], "name-index": ""})
