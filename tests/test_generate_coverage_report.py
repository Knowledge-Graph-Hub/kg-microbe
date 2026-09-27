"""Keep source counts truthful without inferring identity from queue labels."""

import csv
import sys
from pathlib import Path

import pytest

from scripts import generate_coverage_report as coverage

FIXTURES = Path(__file__).parent / "resources" / "source_coverage"
SOURCES = tuple(coverage.SOURCE_LAYOUTS)


def layout_for(source):
    """Select immutable miniature reports without changing their source schema."""
    filename = "microbedecoder.tsv" if source == "microbedecoder" else "metatraits.tsv"
    return {
        **coverage.SOURCE_LAYOUTS[source],
        "edges": str(FIXTURES / "edges.tsv"),
        "unmapped": str(FIXTURES / filename),
    }


def write_report(path, fields, rows):
    """Write synthetic producer-style report rows under tmp_path."""
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


def test_edge_stats_preserve_multiplicity_and_literal_quote():
    """A repeated mapped-looking edge is still two rows, not proven identity."""
    result = coverage.load_edge_stats(FIXTURES / "edges.tsv")
    assert result["edge_rows"] == 6
    assert result["predicates"]["biolink:consumes"] == 3
    assert result["ontology_objects"]["CHEBI"] == {"CHEBI:1": 2}
    assert result["object_families"] == {"other": 3, "source_attribute": 1, "pathway": 1, "compound": 1}
    assert result["object_prefixes"]["NCBITaxon"] == 1


def test_microbedecoder_keeps_same_labels_in_distinct_contexts():
    """Do not collapse labels across columns, facets, identities, or zero counts."""
    layout = layout_for("microbedecoder")
    result = coverage.load_unmapped(Path(layout["unmapped"]), layout)
    assert len(result) == 5
    assert [item["count"] for item in result] == [20, 30, 0, 2, 1]
    assert [item["facet"] for item in result] == [
        "source_attribute",
        "source_attribute",
        "compound",
        "pathway",
        "compound",
    ]
    with Path(layout["unmapped"]).open(newline="") as stream:
        original = list(csv.DictReader(stream, delimiter="\t"))
    assert [item["row"] for item in result] == original
    assert result[0]["row"]["source_columns"] != result[1]["row"]["source_columns"]


@pytest.mark.parametrize("source", SOURCES[:2])
def test_metatraits_keeps_taxon_polarity_counts_and_duplicates(source):
    """MetaTraits records and their observation counts are different units."""
    layout = layout_for(source)
    result = coverage.load_unmapped(Path(layout["unmapped"]), layout)
    assert len(result) == 3
    assert [item["count"] for item in result] == [7, 0, 7]
    assert result[0]["row"] == result[2]["row"]
    assert result[1]["row"]["majority_label"] == "absent"
    assert result[0]["line"] != result[2]["line"]


@pytest.mark.parametrize("source", SOURCES)
def test_all_source_cli_modes_keep_measures_separate(source, monkeypatch, capsys):
    """Exercise actual CLI dispatch with only synthetic source inputs."""
    monkeypatch.setitem(coverage.SOURCE_LAYOUTS, source, layout_for(source))
    monkeypatch.setattr(sys, "argv", ["coverage", "--source", source])
    coverage.main()
    output = capsys.readouterr().out
    assert "Finalized source edge rows: 6" in output
    assert "Report status: PRESENT" in output
    assert "Mapped edges:" not in output
    assert "Approximate mapping rate" not in output
    assert "MAPPING SUCCESS RATE" not in output
    assert "%" not in output
    if source == "microbedecoder":
        assert "Reported count total: 53" in output
        assert "source_attribute: 2 report rows; 50 reported counts" in output
        assert "BacDive_Motility" in output and "BacDive_Spores" in output
        assert "before edge deduplication" in output
    else:
        assert "Report rows: 3" in output
        assert "Reported count total: 14" in output
        assert '"tax_name": "Taxon B"' in output


@pytest.mark.parametrize("source", SOURCES)
@pytest.mark.parametrize("present", [False, True])
def test_missing_report_is_not_header_only_empty(source, present, tmp_path, capsys):
    """Missing evidence stays unknown while a valid empty report records zero."""
    layout = layout_for(source)
    path = tmp_path / "report.tsv"
    layout["unmapped"] = str(path)
    if present:
        write_report(path, layout["required_columns"], [])
    assert coverage.load_unmapped(path, layout) == ([] if present else None)
    coverage._report(source, layout)
    output = capsys.readouterr().out
    if present:
        assert "PRESENT_EMPTY (header only)" in output
        assert "Reported count total: 0" in output
    else:
        assert "MISSING" in output and "unknown" in output
        assert "Reported count total:" not in output


@pytest.mark.parametrize("source", SOURCES)
@pytest.mark.parametrize("value", ["-1", "", "NaN", "1.5", "+2", " 3 "])
def test_invalid_counts_fail_explicitly(source, value, tmp_path):
    """Malformed or negative counts must not silently become zero or one."""
    layout = layout_for(source)
    path = tmp_path / "bad.tsv"
    fields = layout["required_columns"]
    row = dict.fromkeys(fields, "example")
    row[layout["count_column"]] = value
    write_report(path, fields, [row])
    with pytest.raises(ValueError, match="nonnegative integer"):
        coverage.load_unmapped(path, layout)


@pytest.mark.parametrize("source", SOURCES)
def test_zero_count_is_preserved_and_valid(source, tmp_path):
    """An explicit zero has meaning and must remain a report row."""
    layout = layout_for(source)
    path = tmp_path / "zero.tsv"
    row = dict.fromkeys(layout["required_columns"], "example")
    row[layout["count_column"]] = "0"
    write_report(path, layout["required_columns"], [row])
    records = coverage.load_unmapped(path, layout)
    assert len(records) == 1 and records[0]["count"] == 0 and records[0]["row"] == row


@pytest.mark.parametrize("content", ["", "label\tlabel\n", "wrong\theader\n"])
def test_invalid_report_headers_are_not_empty_reports(content, tmp_path):
    """An empty file or broken schema is not a successful zero-result report."""
    path = tmp_path / "bad.tsv"
    path.write_text(content)
    with pytest.raises(ValueError, match="invalid header"):
        coverage.load_unmapped(path, layout_for("microbedecoder"))


@pytest.mark.parametrize("content", ["predicate\tobject\np\to\textra\n", "predicate\tobject\np\n"])
def test_malformed_edge_width_fails(content, tmp_path):
    """Graph reader must not discard surplus cells or fill missing objects."""
    path = tmp_path / "bad.tsv"
    path.write_text(content)
    with pytest.raises(ValueError, match="row width"):
        coverage.load_edge_stats(path)


def test_report_preserves_quoted_values_and_extensions(tmp_path):
    """Ordinary report quoting preserves literal labels and all extra fields."""
    layout = layout_for("metatraits")
    path = tmp_path / "quoted.tsv"
    row = {
        "trait_name": '"0"\nsecond line',
        "tax_name": "Taxon A",
        "majority_label": "-",
        "num_observations": "2",
        "extra": "evidence",
        "placeholder_curie": "kgmicrobe.source_attribute:extension_is_not_a_source_role",
    }
    write_report(path, list(row), [row])
    result = coverage.load_unmapped(path, layout)
    assert result[0]["row"] == row
    assert result[0]["facet"] == "unresolved_trait"


@pytest.mark.parametrize("suffix", ["same\tTaxon A\tpresent\n", "same\tTaxon A\tpresent\t2\textra\n"])
def test_malformed_report_width_fails(suffix, tmp_path):
    """Report readers may not silently truncate or fill incomplete records."""
    path = tmp_path / "bad.tsv"
    path.write_text("trait_name\ttax_name\tmajority_label\tnum_observations\n" + suffix)
    with pytest.raises(ValueError, match="row width"):
        coverage.load_unmapped(path, layout_for("metatraits"))


def test_unterminated_report_quote_fails(tmp_path):
    """Malformed CSV quoting is not a literal successfully parsed report row."""
    path = tmp_path / "bad.tsv"
    path.write_text('trait_name\ttax_name\tmajority_label\tnum_observations\n"unterminated')
    with pytest.raises(csv.Error):
        coverage.load_unmapped(path, layout_for("metatraits"))


def test_cli_reports_input_error_without_success_text(tmp_path, monkeypatch, capsys):
    """Bad input has a useful nonzero exit instead of a misleading summary."""
    layout = layout_for("microbedecoder")
    layout["edges"] = str(tmp_path / "missing-edges.tsv")
    monkeypatch.setitem(coverage.SOURCE_LAYOUTS, "microbedecoder", layout)
    monkeypatch.setattr(sys, "argv", ["coverage", "-s", "microbedecoder"])
    with pytest.raises(SystemExit, match=r"\[coverage\]"):
        coverage.main()
    assert capsys.readouterr().out == ""
