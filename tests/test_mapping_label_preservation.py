"""Preserve published synonym presentation without resurrecting scientific claims (#979)."""

import csv
import gzip

import pytest

from scripts import consolidate_chemical_mappings as exporter

TARGET = "CHEBI:15377"
SUBJECT = "kgm.name:dihydrogen_oxide"


def _prior(path, labels=("dihydrogen oxide",), **overrides):
    """Write explicit historical lexical rows, never a seed for new chemical claims."""
    rows = [
        {
            "subject_id": SUBJECT,
            "predicate_id": "skos:closeMatch",
            "object_id": TARGET,
            "subject_label": label,
            "comment": "synonym",
            "predicate_modifier": "",
            "mapping_date": "2020-01-01",
            **overrides,
        }
        for label in labels
    ]
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "wt", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, list(rows[0]), delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    return path


def _export(path, prior, *, canonical="water", synonyms=("Dihydrogen oxide", "dihydrogen oxide")):
    """Exercise the public exporter with one immutable scientific identity."""
    consolidator = exporter.ChemicalMappingConsolidator()
    consolidator.add_chemical(TARGET, canonical_name=canonical, synonyms=list(synonyms), source="test")
    consolidator.export_unified_sssom(path, published_path=prior)
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        return list(csv.DictReader((line for line in stream if not line.startswith("#")), delimiter="\t"))


@pytest.mark.parametrize("suffix", [".tsv", ".tsv.gz"])
def test_accepted_published_synonym_surface_wins_over_ascii_order(tmp_path, suffix):
    """Existing lower-case presentation remains when an uppercase variant sorts first."""
    prior = _prior(tmp_path / ("published" + suffix))
    rows = _export(tmp_path / "candidate.gz", prior)
    synonym = next(row for row in rows if row["comment"] == "synonym")
    assert synonym["subject_label"] == "dihydrogen oxide"
    assert synonym["subject_id"] == SUBJECT
    assert synonym["mapping_date"] == "2020-01-01"


def test_removed_surface_is_not_restored_by_the_published_row(tmp_path):
    """Normalized equivalence cannot restore the exact surface a current source removed."""
    prior = _prior(tmp_path / "published.tsv")
    rows = _export(tmp_path / "candidate.gz", prior, synonyms=["Dihydrogen oxide"])
    assert next(row for row in rows if row["comment"] == "synonym")["subject_label"] == "Dihydrogen oxide"


def test_quarantined_surface_is_not_restored_by_history(tmp_path, monkeypatch):
    """The final current identity policy applies before selecting any historical spelling."""
    prior = _prior(tmp_path / "published.tsv")
    original = exporter.ingredient_mapping_allowed
    monkeypatch.setattr(
        exporter,
        "ingredient_mapping_allowed",
        lambda name, target: name != "dihydrogen oxide" and original(name, target),
    )
    rows = _export(tmp_path / "candidate.gz", prior)
    assert next(row for row in rows if row["comment"] == "synonym")["subject_label"] == "Dihydrogen oxide"


@pytest.mark.parametrize(
    "overrides",
    [
        {"predicate_id": "skos:exactMatch"},
        {"object_id": "CHEBI:12345"},
        {"subject_id": "kgm.name:another_slug"},
        {"predicate_modifier": "Not"},
        {"comment": "canonical_name"},
    ],
)
def test_only_the_same_positive_synonym_triple_supplies_presentation(tmp_path, overrides):
    """Another target, predicate, subject or row shape cannot decide this row's spelling."""
    prior = _prior(tmp_path / "published.tsv", **overrides)
    rows = _export(tmp_path / "candidate.gz", prior)
    assert next(row for row in rows if row["comment"] == "synonym")["subject_label"] == "Dihydrogen oxide"


def test_current_canonical_relabeling_is_never_overridden(tmp_path):
    """Canonical names remain scientific current-input decisions, not cosmetic carry-forward."""
    prior = _prior(
        tmp_path / "published.tsv",
        labels=["water"],
        subject_id="kgm.name:water",
        predicate_id="skos:exactMatch",
        comment="canonical_name",
    )
    rows = _export(tmp_path / "candidate.gz", prior, canonical="Water", synonyms=["water"])
    assert len(rows) == 1
    assert rows[0]["subject_label"] == rows[0]["object_label"] == "Water"


@pytest.mark.parametrize("reverse", [False, True])
def test_conflicting_prior_surfaces_do_not_make_file_order_a_policy(tmp_path, reverse):
    """An ambiguous prior triple falls back to deterministic current-source presentation."""
    labels = ["dihydrogen oxide", "Dihydrogen oxide"]
    prior = _prior(tmp_path / "published.tsv", labels=labels[::-1] if reverse else labels)
    rows = _export(tmp_path / "candidate.gz", prior)
    assert next(row for row in rows if row["comment"] == "synonym")["subject_label"] == "Dihydrogen oxide"


def test_preserved_synonym_exports_are_byte_stable(tmp_path):
    """Two exports with identical accepted claims and prior presentation produce identical bytes."""
    prior = _prior(tmp_path / "published.tsv")
    first, second = tmp_path / "first.gz", tmp_path / "second.gz"
    _export(first, prior)
    _export(second, prior)
    assert first.read_bytes() == second.read_bytes()
