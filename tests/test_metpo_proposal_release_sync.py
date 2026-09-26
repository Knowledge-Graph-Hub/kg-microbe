"""The proposal templates must not drift from the release again (#901)."""

import csv
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CLASSES = REPO_ROOT / "mappings" / "metpo_proposal_classes_robot.tsv"
GENERATOR = REPO_ROOT / "scripts" / "extract_metpo_proposals.py"
DIFF_SCRIPT = REPO_ROOT / "scripts" / "diff_metpo_proposals.py"


def _class_rows():
    with CLASSES.open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))[1:]


def test_the_diff_generator_is_in_the_repo():
    """
    The previous report told readers to rerun a script that lived in /tmp.

    An instruction that cannot be followed is worse than no instruction: the
    report went a release stale with nobody able to refresh it.
    """
    assert DIFF_SCRIPT.is_file()


def test_no_class_is_proposed_under_the_ontology_root():
    """
    Upstream re-parents anything at `METPO:1000000` to `METPO:1000059`.

    Proposing at the root guarantees a silent re-parent on the next adoption
    round and keeps our template permanently disagreeing with the release.
    """
    at_root = [r["proposed_id"] for r in _class_rows() if r["parent"] == "METPO:1000000"]
    assert not at_root, f"proposed under the ontology root: {at_root}"


def test_no_definition_uses_the_superseded_wording():
    """
    metpo#460 rewrites definitions into genus-differentia form on ingest.

    Keeping the old `A phenotypic quality describing ...` form means every
    future diff re-reports the same rows as differing.
    """
    old_form = [
        r["proposed_id"] for r in _class_rows() if r["definition"].startswith("A phenotypic quality describing")
    ]
    assert not old_form, f"superseded definition wording: {old_form}"


def test_the_generator_holds_the_parent_in_one_place():
    """Fourteen rows moved at once because the parent is a single constant."""
    source = GENERATOR.read_text(encoding="utf-8")
    assert '_PHENO_PARENT = "METPO:1000059"' in source
    assert '_PHENO_PARENT = "METPO:1000000"' not in source


def test_the_generated_report_says_how_to_regenerate_it():
    """
    #901 existed because a report named a generator that no longer existed.

    A reader who opens the report must not have to find a second document to
    learn it is generated, or that hand-editing it is pointless.
    """
    report = REPO_ROOT / "docs" / "metpo" / "metpo_proposal_release_diff.md"
    text = report.read_text(encoding="utf-8")
    assert "scripts/diff_metpo_proposals.py" in text
    assert "Do not edit by hand" in text
    # The proposal artifacts are generated too, and editing them directly is the
    # mistake the regenerate-and-diff gate exists to catch.
    assert "scripts/extract_metpo_proposals.py" in text
