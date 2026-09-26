"""Keep the curation queue aligned with current and historical report prefixes."""

import csv
import sys

from scripts.dump_unmapped_microbedecoder_labels import _filter_and_sort, main


def report_rows():
    """Return same-label records whose distinct source contexts must survive."""
    return [
        {
            "placeholder_curie": prefix + suffix,
            "category": category,
            "label": "0",
            "source_columns": column,
            "occurrences": str(count),
        }
        for prefix, suffix, category, column, count in [
            ("kgmicrobe.source_attribute:", "motility_0", "biolink:Attribute", "BacDive_Motility", 20),
            ("kgmicrobe.source_attribute:", "spore_0", "biolink:Attribute", "BacDive_Spores", 30),
            ("kgmicrobe.trait:", "0", "biolink:PhenotypicQuality", "historical", 15),
            ("kgmicrobe.compound:", "0", "biolink:ChemicalEntity", "substrate", 40),
        ]
    ]


def test_source_attribute_filter_preserves_context():
    """Current facet keeps both columns and excludes unrelated/historical rows."""
    rows = _filter_and_sort(report_rows(), "source_attribute", 10)
    assert [row["source_columns"] for row in rows] == ["BacDive_Spores", "BacDive_Motility"]
    assert all(row["category"] == "biolink:Attribute" for row in rows)
    assert len({row["placeholder_curie"] for row in rows}) == 2
    assert len(_filter_and_sort(report_rows(), "source_attribute", 25)) == 1


def test_legacy_trait_filter_accepts_both_generations():
    """Legacy CLI usage must not silently discard current source attributes."""
    rows = _filter_and_sort(report_rows(), "trait", 10)
    assert len(rows) == 3
    assert rows[-1]["placeholder_curie"] == "kgmicrobe.trait:0"
    assert len(_filter_and_sort(report_rows(), "compound", 10)) == 1
    assert len(_filter_and_sort(report_rows(), None, 10)) == 4


def test_current_facet_cli_writes_unmodified_context(tmp_path, monkeypatch):
    """Exercise argparse and TSV output without touching the real curation queue."""
    source = tmp_path / "unmapped.tsv"
    output = tmp_path / "curation.tsv"
    rows = report_rows()
    with source.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)
    monkeypatch.setattr(
        sys, "argv", ["queue", "--input", str(source), "--output", str(output), "--prefix", "source_attribute"]
    )
    main()
    with output.open(newline="") as handle:
        result = list(csv.DictReader(handle, delimiter="\t"))
    assert len(result) == 2
    assert {row["source_columns"] for row in result} == {"BacDive_Motility", "BacDive_Spores"}
    assert all(row["target_curie"] == "" and row["label"] == "0" for row in result)
