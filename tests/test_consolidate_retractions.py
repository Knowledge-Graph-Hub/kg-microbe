"""
Tests for the consolidator's retraction pass (apply_retractions).

The consolidator seeds each run from its own prior output, which is additive:
a corrected upstream grounding adds the right object record but cannot remove
the superseded one. ``apply_retractions`` drops explicitly-listed stale object
records, but only when their sole contributing source is
``culturebotai_reviewed`` so attribution stays unambiguous.
"""

import importlib.util
from pathlib import Path

import pytest

_CONSOLIDATOR_PATH = Path(__file__).resolve().parents[1] / "scripts" / "consolidate_chemical_mappings.py"


def _load_consolidator_module():
    """Import the standalone consolidator script as a module."""
    spec = importlib.util.spec_from_file_location("consolidate_chemical_mappings", _CONSOLIDATOR_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def consolidator():
    """Return a consolidator seeded with drop / skip / keep / absent fixtures."""
    mod = _load_consolidator_module()
    c = mod.ChemicalMappingConsolidator()
    # Sole-source culturebotai phantom → must be dropped.
    c.add_chemical(
        id="CHEBI:15743",
        canonical_name="Glycylglycine",
        source="culturebotai_reviewed",
        priority=10,
    )
    # Mixed-source → must be SKIPPED (another source still asserts it).
    c.add_chemical(
        id="CHEBI:30411",
        canonical_name="Cobalamine",
        source="culturebotai_reviewed",
        priority=10,
    )
    c.add_chemical(
        id="CHEBI:30411",
        canonical_name="Cobalamine",
        source="mediadive_compounds",
        priority=1,
    )
    # Correct grounding, not listed → must be untouched.
    c.add_chemical(
        id="CHEBI:17201",
        canonical_name="Glycylglycine",
        source="culturebotai_reviewed",
        priority=10,
    )
    return c


def _write_retraction_tsv(path: Path):
    """Write a retraction TSV with a comment header + one already-absent row."""
    path.write_text(
        "# comment lines must be ignored by the reader\n"
        "subject_id\tsubject_label\tstale_object\tstale_object_label\tnow_asserted\tsource\n"
        "kgm.name:glycylglycine\tGlycylglycine\tCHEBI:15743\tGlycylglycine\tCHEBI:17201\tculturebotai_reviewed\n"
        "kgm.name:cobalamin\tCOBALAMIN\tCHEBI:30411\tCobalamine\tCHEBI:28911\tculturebotai_reviewed\n"
        "kgm.name:gone\tGone\tCHEBI:99999\tGone\tCHEBI:1\tculturebotai_reviewed\n",
        encoding="utf-8",
    )


def test_drops_sole_source_culturebotai_object(consolidator, tmp_path):
    """A stale object sourced solely from culturebotai_reviewed is removed."""
    rf = tmp_path / "retract.tsv"
    _write_retraction_tsv(rf)
    consolidator.apply_retractions(rf)
    assert "CHEBI:15743" not in consolidator.chemicals


def test_skips_mixed_source_object(consolidator, tmp_path):
    """A listed object that also has a non-culturebotai source is left in place."""
    rf = tmp_path / "retract.tsv"
    _write_retraction_tsv(rf)
    consolidator.apply_retractions(rf)
    assert "CHEBI:30411" in consolidator.chemicals


def test_leaves_unlisted_object_untouched(consolidator, tmp_path):
    """The correct grounding (not in the list) survives retraction."""
    rf = tmp_path / "retract.tsv"
    _write_retraction_tsv(rf)
    consolidator.apply_retractions(rf)
    assert "CHEBI:17201" in consolidator.chemicals


def test_absent_object_is_a_noop(consolidator, tmp_path):
    """A listed object not present in the graph does not raise."""
    rf = tmp_path / "retract.tsv"
    _write_retraction_tsv(rf)
    # CHEBI:99999 is listed but was never added — must be a silent no-op.
    consolidator.apply_retractions(rf)
    assert "CHEBI:99999" not in consolidator.chemicals


def test_missing_retraction_file_is_a_noop(consolidator, tmp_path):
    """A missing retraction file skips the pass without dropping anything."""
    consolidator.apply_retractions(tmp_path / "does_not_exist.tsv")
    assert "CHEBI:15743" in consolidator.chemicals


def test_idempotent_across_runs(consolidator, tmp_path):
    """Re-running the pass is a no-op on the already-dropped object (no raise)."""
    rf = tmp_path / "retract.tsv"
    _write_retraction_tsv(rf)
    consolidator.apply_retractions(rf)
    assert "CHEBI:15743" not in consolidator.chemicals
    # Second run: the object is already absent — must not raise and must not
    # resurrect or otherwise disturb the graph.
    consolidator.apply_retractions(rf)
    assert "CHEBI:15743" not in consolidator.chemicals
    assert "CHEBI:17201" in consolidator.chemicals


def test_curator_qualified_source_is_sole_source(tmp_path):
    """A ``culturebotai_reviewed[curator=…]`` variant counts as sole-source and drops."""
    mod = _load_consolidator_module()
    c = mod.ChemicalMappingConsolidator()
    c.add_chemical(
        id="CHEBI:15743",
        canonical_name="Glycylglycine",
        source="culturebotai_reviewed[curator=auto_classify]",
        priority=10,
    )
    rf = tmp_path / "retract.tsv"
    _write_retraction_tsv(rf)
    c.apply_retractions(rf)
    assert "CHEBI:15743" not in c.chemicals


def test_empty_source_object_is_not_dropped(tmp_path):
    """An object with no culturebotai_reviewed source (empty/unknown) is left in place."""
    mod = _load_consolidator_module()
    c = mod.ChemicalMappingConsolidator()
    # Seed a record then blank its source set to simulate unknown attribution.
    c.add_chemical(
        id="CHEBI:15743",
        canonical_name="Glycylglycine",
        source="culturebotai_reviewed",
        priority=10,
    )
    c.chemicals["CHEBI:15743"]["sources"] = set()
    rf = tmp_path / "retract.tsv"
    _write_retraction_tsv(rf)
    c.apply_retractions(rf)
    assert "CHEBI:15743" in c.chemicals


# --- name-level retraction (#599 item 1, motivated by #784) -------------------


@pytest.fixture()
def name_level_consolidator():
    """
    Return a consolidator in the shape #784 left behind.

    ``CHEBI:28911`` is a real ChEBI term that accreted the bare-vitamer names
    after upstream reground them to its parent ``CHEBI:30411``. It is
    multi-source, so an object-level drop is refused — and should be: dropping
    it would delete a legitimate term and its KEGG / PDB xrefs.
    """
    mod = _load_consolidator_module()
    c = mod.ChemicalMappingConsolidator()
    c.add_chemical(
        id="CHEBI:28911",
        canonical_name="Cobalamine",
        synonyms=["COBALAMIN", "Cbl", "Cob(III)alamin", "cobalamin(III)"],
        source="culturebotai_reviewed",
        priority=10,
        xrefs=["CHEBI:30411"],
    )
    c.add_chemical(id="CHEBI:28911", canonical_name="Cobalamine", source="chebi_xrefs", priority=2)
    c.add_chemical(
        id="CHEBI:30411",
        canonical_name="Cobalamine",
        synonyms=["COBALAMIN", "Cbl"],
        source="culturebotai_reviewed",
        priority=10,
        xrefs=["CHEBI:28911"],
    )
    return c


def _write_name_level_tsv(path: Path, names="Cobalamine|COBALAMIN|Cbl"):
    """Write a retraction TSV carrying one name-level row."""
    path.write_text(
        "subject_id\tsubject_label\tstale_object\tstale_object_label\tnow_asserted\tsource\tretract_names\n"
        f"kgm.name:cobalamine\tCobalamine\tCHEBI:28911\tcob(III)alamin\tCHEBI:30411\t"
        f"culturebotai_reviewed\t{names}\n",
        encoding="utf-8",
    )


def test_name_level_retraction_strips_names_but_keeps_the_record(name_level_consolidator, tmp_path):
    """
    The record survives; only the enumerated names leave.

    Object-level granularity was the wrong tool here — CHEBI:28911 is a real
    ChEBI term whose KEGG and PDB xrefs must not be collateral damage.
    """
    rf = tmp_path / "retract.tsv"
    _write_name_level_tsv(rf)
    name_level_consolidator.apply_retractions(rf)

    rec = name_level_consolidator.chemicals["CHEBI:28911"]
    assert rec is not None, "the record must not be dropped"
    assert "COBALAMIN" not in rec["synonyms"]
    assert "Cbl" not in rec["synonyms"]


def test_name_level_retraction_keeps_the_terms_own_synonyms(name_level_consolidator, tmp_path):
    """Names that genuinely belong to the term are untouched."""
    rf = tmp_path / "retract.tsv"
    _write_name_level_tsv(rf)
    name_level_consolidator.apply_retractions(rf)

    rec = name_level_consolidator.chemicals["CHEBI:28911"]
    assert "Cob(III)alamin" in rec["synonyms"]
    assert "cobalamin(III)" in rec["synonyms"]


def test_a_name_level_row_does_not_drop_the_object(name_level_consolidator, tmp_path):
    """A row with retract_names must never be treated as an object-level drop."""
    rf = tmp_path / "retract.tsv"
    _write_name_level_tsv(rf)
    name_level_consolidator.apply_retractions(rf)
    assert "CHEBI:28911" in name_level_consolidator.chemicals
    assert "CHEBI:30411" in name_level_consolidator.chemicals


def test_a_name_no_replacement_carries_is_refused(name_level_consolidator, tmp_path, capsys):
    """
    Retraction must never leave a name grounded nowhere.

    The sole-source guard protects object-level rows; this is the equivalent
    protection for name-level ones, and it is what makes them safe to apply
    under mixed sources.
    """
    rf = tmp_path / "retract.tsv"
    _write_name_level_tsv(rf, names="Cob(III)alamin")  # CHEBI:30411 does not carry this
    name_level_consolidator.apply_retractions(rf)

    rec = name_level_consolidator.chemicals["CHEBI:28911"]
    assert "Cob(III)alamin" in rec["synonyms"], "must not be removed — nothing else carries it"
    assert "now_asserted target(s)" in capsys.readouterr().out


def test_propagation_cannot_hand_a_retracted_name_back(name_level_consolidator, tmp_path):
    """
    The regression that made the first implementation useless.

    ``propagate_synonyms_via_xrefs`` copies names across the exactMatch xref —
    which points straight at the target that superseded them — so every
    retracted name reappeared as a synonym in the same run.
    """
    rf = tmp_path / "retract.tsv"
    _write_name_level_tsv(rf)
    name_level_consolidator.apply_retractions(rf)
    name_level_consolidator.propagate_synonyms_via_xrefs()

    rec = name_level_consolidator.chemicals["CHEBI:28911"]
    assert "COBALAMIN" not in rec["synonyms"]
    assert "Cbl" not in rec["synonyms"]


def test_object_level_drop_prunes_the_name_index(consolidator, tmp_path):
    """
    #599 item 2: a dropped record must not leave indices pointing at it.

    Inert for today's callers, but a name resolved via ``name_index`` after
    this pass would hand back a CURIE that no longer has a record.
    """
    rf = tmp_path / "retract.tsv"
    _write_retraction_tsv(rf)
    assert "CHEBI:15743" in consolidator.name_index.values()
    consolidator.apply_retractions(rf)
    assert "CHEBI:15743" not in consolidator.chemicals
    assert "CHEBI:15743" not in consolidator.name_index.values()


# --- defects found reviewing the first implementation (#787) ------------------


def test_the_restored_canonical_is_the_terms_own_label(name_level_consolidator, tmp_path, monkeypatch):
    """
    Retracting the canonical restores the ontology label, not an arbitrary synonym.

    Promoting alphabetically labelled cob(III)alamin
    "Coalpha-[alpha-(5,6-dimethylbenzimidazolyl)]-cobamide" — worse than the
    wrong name it replaced.
    """
    rf = tmp_path / "retract.tsv"
    _write_name_level_tsv(rf)
    monkeypatch.setattr(type(name_level_consolidator), "_ontology_label", lambda self, curie: "cob(III)alamin")
    name_level_consolidator.apply_retractions(rf)
    assert name_level_consolidator.chemicals["CHEBI:28911"]["canonical_name"] == "cob(III)alamin"


def test_a_canonical_nobody_retracted_is_left_alone(tmp_path, monkeypatch):
    """
    The restore repairs the name it removed; it is not a licence to relabel.

    Firing it for any object with retract_names clobbered a deliberate
    priority-10 curator label with a raw ChEBI systematic name.
    """
    mod = _load_consolidator_module()
    c = mod.ChemicalMappingConsolidator()
    c.add_chemical(
        id="CHEBI:28911",
        canonical_name="Widget",
        synonyms=["COBALAMIN"],
        source="culturebotai_reviewed",
        priority=10,
    )
    c.add_chemical(id="CHEBI:30411", canonical_name="COBALAMIN", source="culturebotai_reviewed", priority=10)
    monkeypatch.setattr(type(c), "_ontology_label", lambda self, curie: "systematic-chebi-name")

    rf = tmp_path / "retract.tsv"
    _write_name_level_tsv(rf, names="COBALAMIN")
    c.apply_retractions(rf)

    assert c.chemicals["CHEBI:28911"]["canonical_name"] == "Widget"


def test_the_ontology_label_is_not_reinstated_when_it_is_itself_retracted(tmp_path, monkeypatch):
    """
    Restoring a name that was just retracted would silently undo the retraction.

    It would also re-export as an exactMatch row while the propagation guard
    reported it blocked — a false success.
    """
    mod = _load_consolidator_module()
    c = mod.ChemicalMappingConsolidator()
    c.add_chemical(
        id="CHEBI:30411",
        canonical_name="cobalamin",
        synonyms=["survivor"],
        source="culturebotai_reviewed",
        priority=10,
    )
    c.add_chemical(id="CHEBI:28911", canonical_name="cobalamin", source="culturebotai_reviewed", priority=10)
    monkeypatch.setattr(type(c), "_ontology_label", lambda self, curie: "cobalamin")

    rf = tmp_path / "retract.tsv"
    rf.write_text(
        "subject_id\tsubject_label\tstale_object\tstale_object_label\tnow_asserted\tsource\tretract_names\n"
        "kgm.name:cobalamin\tcobalamin\tCHEBI:30411\tcobalamin\tCHEBI:28911\tculturebotai_reviewed\tcobalamin\n",
        encoding="utf-8",
    )
    c.apply_retractions(rf)

    assert c.chemicals["CHEBI:30411"]["canonical_name"] != "cobalamin"


def test_a_non_chebi_object_falls_back_to_a_surviving_synonym(tmp_path):
    """
    Only CHEBI has a label lookup here, and FOODON dominates the retraction file.

    Without a fallback the record exports an empty object_label on every row,
    and the propagation guard then blocks the only name that could restore it.
    """
    mod = _load_consolidator_module()
    c = mod.ChemicalMappingConsolidator()
    c.add_chemical(
        id="FOODON:00001264",
        canonical_name="Malt extract",
        synonyms=["malt syrup"],
        source="culturebotai_reviewed",
        priority=10,
    )
    c.add_chemical(id="FOODON:03301056", canonical_name="Malt extract", source="culturebotai_reviewed", priority=10)

    rf = tmp_path / "retract.tsv"
    rf.write_text(
        "subject_id\tsubject_label\tstale_object\tstale_object_label\tnow_asserted\tsource\tretract_names\n"
        "kgm.name:malt_extract\tMalt extract\tFOODON:00001264\tMalt extract\tFOODON:03301056"
        "\tculturebotai_reviewed\tMalt extract\n",
        encoding="utf-8",
    )
    c.apply_retractions(rf)

    assert c.chemicals["FOODON:00001264"]["canonical_name"] == "malt syrup"


def test_another_rows_target_cannot_vouch_for_this_rows_name(tmp_path):
    """
    The orphan guard must consult the row's own now_asserted, not a global pool.

    Pooling let an unrelated row's replacement satisfy the check, so the stated
    invariant — a name is never left grounded nowhere — held only by accident.
    """
    mod = _load_consolidator_module()
    c = mod.ChemicalMappingConsolidator()
    # Row A's target legitimately carries "Glycylglycine".
    c.add_chemical(id="CHEBI:17201", canonical_name="Glycylglycine", source="culturebotai_reviewed", priority=10)
    # Row B retracts that same name from a different object, but ITS target does not carry it.
    c.add_chemical(id="CHEBI:99991", canonical_name="Glycylglycine", source="culturebotai_reviewed", priority=10)
    c.add_chemical(id="CHEBI:99992", canonical_name="Something else", source="culturebotai_reviewed", priority=10)

    rf = tmp_path / "retract.tsv"
    rf.write_text(
        "subject_id\tsubject_label\tstale_object\tstale_object_label\tnow_asserted\tsource\tretract_names\n"
        "kgm.name:gg\tGlycylglycine\tCHEBI:15743\tGlycylglycine\tCHEBI:17201\tculturebotai_reviewed\t\n"
        "kgm.name:gg2\tGlycylglycine\tCHEBI:99991\tGlycylglycine\tCHEBI:99992\tculturebotai_reviewed"
        "\tGlycylglycine\n",
        encoding="utf-8",
    )
    c.apply_retractions(rf)

    assert c.chemicals["CHEBI:99991"]["canonical_name"] == "Glycylglycine", (
        "CHEBI:99992 never carried this name, so row B must be refused"
    )


def test_a_missing_ontology_db_does_not_abort_the_pass(name_level_consolidator, tmp_path, monkeypatch):
    """
    FatalOntologyError derives from BaseException, so `except Exception` misses it.

    Before name-level retraction this pass touched no ontology at all; it must
    not start failing where data/raw/chebi.db is absent.
    """
    from kg_microbe.utils.ontology_utils import OntologyDbUnavailableError

    def _boom(self):
        raise OntologyDbUnavailableError("no chebi.db")

    monkeypatch.setattr(type(name_level_consolidator), "_get_chebi_adapter", _boom)

    rf = tmp_path / "retract.tsv"
    _write_name_level_tsv(rf)
    name_level_consolidator.apply_retractions(rf)  # must not raise

    rec = name_level_consolidator.chemicals["CHEBI:28911"]
    assert "COBALAMIN" not in rec["synonyms"], "the retraction itself must still happen"
    assert rec["canonical_name"], "must fall back to a surviving synonym, not go nameless"


def test_a_name_level_row_blocks_a_later_object_level_drop_of_the_same_object(name_level_consolidator, tmp_path):
    """A name-level claim on an object must not silently escalate to a record drop."""
    rf = tmp_path / "retract.tsv"
    rf.write_text(
        "subject_id\tsubject_label\tstale_object\tstale_object_label\tnow_asserted\tsource\tretract_names\n"
        "kgm.name:cobalamine\tCobalamine\tCHEBI:28911\tcob(III)alamin\tCHEBI:30411"
        "\tculturebotai_reviewed\tCobalamine\n"
        "kgm.name:other\tOther\tCHEBI:28911\tcob(III)alamin\tCHEBI:30411\tculturebotai_reviewed\t\n",
        encoding="utf-8",
    )
    name_level_consolidator.apply_retractions(rf)
    assert "CHEBI:28911" in name_level_consolidator.chemicals


def test_a_retract_names_row_for_an_absent_object_is_reported_not_crashed(name_level_consolidator, tmp_path, capsys):
    """A stale list entry must degrade to a message, not a KeyError."""
    rf = tmp_path / "retract.tsv"
    rf.write_text(
        "subject_id\tsubject_label\tstale_object\tstale_object_label\tnow_asserted\tsource\tretract_names\n"
        "kgm.name:x\tX\tCHEBI:99999\tGone\tCHEBI:30411\tculturebotai_reviewed\tCobalamine\n",
        encoding="utf-8",
    )
    name_level_consolidator.apply_retractions(rf)
    assert "no such record" in capsys.readouterr().out
