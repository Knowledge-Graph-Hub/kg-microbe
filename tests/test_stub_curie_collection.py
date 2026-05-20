"""Tests for kg_microbe.utils.stub_curie_collection."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from kg_microbe.utils.stub_curie_collection import (
    DEFAULT_MAPPING_PATHS,
    collect_stub_curies,
)


def _write_tsv(path: Path, header: list[str], rows: list[list[str]]) -> None:
    """Write a small TSV with the given header + rows."""
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh, delimiter="\t", lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)


def test_collect_finds_known_ncit_mesh_curies(tmp_path):
    """A fixture mapping with one NCIT and one mesh row must surface both CURIEs."""
    fixture = tmp_path / "fixture.tsv"
    _write_tsv(
        fixture,
        ["subject_id", "object_id", "object_label"],
        [
            ["kgmicrobe.compound:oatmeal", "NCIT:C29298", "Oatmeal"],
            ["kgmicrobe.compound:tween", "mesh:D011136", "Tween"],
            ["kgmicrobe.compound:other", "CHEBI:15377", "water"],  # ignored prefix
        ],
    )
    result = collect_stub_curies(["NCIT", "mesh"], mapping_paths=[fixture])
    assert result["NCIT"] == {"NCIT:C29298"}
    assert result["mesh"] == {"mesh:D011136"}


def test_collect_normalizes_curie_case(tmp_path):
    """``Mesh:D011136`` and ``ncit:C29298`` (wrong case) must collapse to the canonical case."""
    fixture = tmp_path / "fixture.tsv"
    _write_tsv(
        fixture,
        ["subject_id", "object_id", "object_label"],
        [
            ["x", "ncit:C29298", "lowercase ncit"],
            ["x", "Mesh:D011136", "mixed-case mesh"],
        ],
    )
    result = collect_stub_curies(["NCIT", "mesh"], mapping_paths=[fixture])
    # Case is normalized to the requested-prefix case.
    assert result["NCIT"] == {"NCIT:C29298"}
    assert result["mesh"] == {"mesh:D011136"}


def test_collect_returns_empty_set_for_unreferenced_prefix(tmp_path):
    """A prefix with no references in any file gets an empty set, not a missing key."""
    fixture = tmp_path / "fixture.tsv"
    _write_tsv(fixture, ["object_id"], [["CHEBI:15377"]])
    result = collect_stub_curies(["NCIT", "mesh"], mapping_paths=[fixture])
    assert result == {"NCIT": set(), "mesh": set()}


def test_collect_skips_missing_files_silently(tmp_path):
    """Removing a mapping source from the repo must not break the collector."""
    missing = tmp_path / "does-not-exist.tsv"
    result = collect_stub_curies(["NCIT", "mesh"], mapping_paths=[missing])
    assert result == {"NCIT": set(), "mesh": set()}


def test_collect_handles_sssom_yaml_header(tmp_path):
    """SSSOM-style ``# ...`` YAML metadata header lines must be skipped before the column header."""
    fixture = tmp_path / "fixture.sssom.tsv"
    fixture.write_text(
        "# curie_map:\n"
        "#   NCIT: 'http://purl.obolibrary.org/obo/NCIT_'\n"
        "subject_id\tobject_id\tobject_label\n"
        "x\tNCIT:C29298\tOatmeal\n",
        encoding="utf-8",
    )
    result = collect_stub_curies(["NCIT"], mapping_paths=[fixture])
    assert result["NCIT"] == {"NCIT:C29298"}


def test_default_paths_yield_real_curies():
    """Smoke-test against the committed mapping files: must find ≥1 NCIT and ≥1 mesh CURIE."""
    if not any(p.is_file() for p in DEFAULT_MAPPING_PATHS):
        pytest.skip("no mapping files present in this checkout")
    result = collect_stub_curies(["NCIT", "mesh"])
    assert len(result["NCIT"]) >= 1, "expected at least one NCIT CURIE in committed mappings"
    assert len(result["mesh"]) >= 1, "expected at least one mesh CURIE in committed mappings"
