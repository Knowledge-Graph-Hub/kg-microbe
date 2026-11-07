"""Read the actual committed mapping artifact once while retaining every acceptance assertion."""

import hashlib
import json
from collections import Counter
from pathlib import Path

import pytest

from kg_microbe.utils import chemical_mapping_utils

_INDEX_NAMES = (
    "_NAME_INDEX",
    "_CANONICAL_NAME_INDEX",
    "_FORMULA_INDEX",
    "_XREF_INDEX",
    "_CATEGORY_INDEX",
    "_PRIMARY_NAME_INDEX",
    "_PRIMARY_SYNONYMS_INDEX",
    "_PRIMARY_XREFS_INDEX",
    "_PRIMARY_FORMULA_INDEX",
    "_PARENT_INDEX",
    "_HYDRATE_EQUIV_INDEX",
)


def _clear_artifact_loader():
    """Leave no successful lookup epoch or negative-query state behind this artifact-only module."""
    chemical_mapping_utils._LOADED = False
    chemical_mapping_utils._ENTITY_COUNT = 0
    chemical_mapping_utils._CACHED_PATH = None
    chemical_mapping_utils._CACHED_DIGEST = None
    chemical_mapping_utils._NEGATIVE_LOOKUP_CACHE.clear()
    for name in _INDEX_NAMES:
        setattr(chemical_mapping_utils, name, None)
    chemical_mapping_utils._NATIVE_HYDRATION_NAMES = {}
    chemical_mapping_utils._MAPPING_LOAD_AUDIT = {}


def _artifact_identity(path):
    """Bind actual full artifact bytes and locator without parsing or substituting its index."""
    before = path.stat()
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    after = path.stat()
    fields = ("st_dev", "st_ino", "st_mode", "st_size", "st_mtime_ns", "st_ctime_ns")
    assert tuple(getattr(before, key) for key in fields) == tuple(getattr(after, key) for key in fields)
    return str(path.resolve()), tuple(getattr(after, key) for key in fields), digest.hexdigest()


@pytest.fixture(scope="module")
def artifact_epoch():
    """Use the same explicit repository artifact as the real default loader, with module isolation."""
    path = Path(chemical_mapping_utils.__file__).parent.parent.parent / "mappings"
    path = path / "kgmicrobe_unified_entity_mappings.sssom.tsv.gz"
    identity = _artifact_identity(path)
    _clear_artifact_loader()
    try:
        yield path, identity
    finally:
        _clear_artifact_loader()
        assert _artifact_identity(path) == identity


@pytest.fixture(autouse=True)
def selected_artifact(artifact_epoch):
    """Select the genuine artifact for each case; only its verified existing loader cache may be reused."""
    path, identity = artifact_epoch
    assert _artifact_identity(path) == identity
    chemical_mapping_utils._NEGATIVE_LOOKUP_CACHE.clear()
    chemical_mapping_utils.load_unified_mappings(path)
    assert chemical_mapping_utils._LOADED is True
    assert chemical_mapping_utils._CACHED_PATH == path
    assert chemical_mapping_utils._CACHED_DIGEST is None
    indices = {name: getattr(chemical_mapping_utils, name) for name in _INDEX_NAMES}
    count = chemical_mapping_utils._ENTITY_COUNT
    try:
        yield
    finally:
        chemical_mapping_utils._NEGATIVE_LOOKUP_CACHE.clear()
        assert _artifact_identity(path) == identity
        assert chemical_mapping_utils._LOADED is True
        assert chemical_mapping_utils._CACHED_PATH == path
        assert chemical_mapping_utils._CACHED_DIGEST is None
        assert chemical_mapping_utils._ENTITY_COUNT == count
        assert all(getattr(chemical_mapping_utils, name) is value for name, value in indices.items())


class TestSupportedOnlyMimArtifact:
    """Check the real promoted artifact against the content-bound MIM decisions."""

    @pytest.mark.parametrize(
        ("name", "child", "parent"),
        [
            ("Vermont Soil", "kgmicrobe.ingredient:vermont_soil", "ENVO:00001998"),
            ("Beef brain powder", "kgmicrobe.ingredient:beef_brain_powder", "FOODON:02020911"),
        ],
    )
    def test_supported_local_reference_does_not_resurrect_withheld_parent(self, name, child, parent):
        """Supported registry identities do not also admit their withheld relations."""
        assert chemical_mapping_utils.find_chebi_by_name(name) == child
        assert chemical_mapping_utils.get_parents(child) == []
        assert parent not in chemical_mapping_utils.get_xrefs(child)

    def test_actinomycin_a_withheld_owner_is_not_an_admitted_unified_identity(self):
        """Both its exact registry row and broad parent row await upstream review."""
        assert chemical_mapping_utils.find_chebi_by_name("Actinomycin A") is None
        assert chemical_mapping_utils.get_canonical_name("kgmicrobe.compound:actinomycin_a") is None
        assert chemical_mapping_utils.get_parents("kgmicrobe.compound:actinomycin_a") == []


_BROADER_FIXTURE = Path(__file__).parent / "resources/mim_reviewed_broader_20261107/source-claims.json"
_BROADER_FIXTURE_SHA256 = "a08a231ea586e84b549736c76b3e8c5d6c8c4d9a8977da69cdfa481b8ef378c0"
_BROADER_MANIFEST_SHA256 = "b02a92446e8a613fd0d96b0dd8147d439733fcf73e731b363a6388e95d616703"
_BROADER_PAIRS = (
    ("cas:10030-67-8", "CHEBI:6731"),
    ("kgmicrobe.compound:d-_-melezitose_monohydrate", "CHEBI:6731"),
    ("cas:7791-07-3", "CHEBI:132103"),
    ("kgmicrobe.compound:sodium_perchlorate_monohydrate", "CHEBI:132103"),
)
_UNIFIED_FIELDS = (
    "subject_id",
    "subject_label",
    "predicate_id",
    "object_id",
    "object_label",
    "object_source",
    "mapping_justification",
    "source",
    "mapping_date",
    "confidence",
    "comment",
    "object_formula",
    "object_category",
)


def _source_row_sha256(row):
    """Hash every native column with the pinned publisher's canonical JSON encoding."""
    return hashlib.sha256(
        json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


@pytest.fixture(scope="module")
def reviewed_broader_claims(artifact_epoch):
    """Bind four complete directed rows to immutable native broad and same-subject exact claims."""
    path, identity = artifact_epoch
    raw = _BROADER_FIXTURE.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == _BROADER_FIXTURE_SHA256
    claims = json.loads(raw)["claims"]
    assert len(claims) == 6
    for claim in claims:
        assert claim["decision"]["disposition"] == "SUPPORTED"
        assert _source_row_sha256(claim["row"]) == claim["decision"]["row_sha256"]
    originals = [claim["row"] for claim in claims]
    subjects = {row["subject_id"] for row in originals}
    native_path = path.with_name("ingredient_mappings.sssom.tsv")
    observed_native = [
        row for row in chemical_mapping_utils._iter_sssom_rows(native_path) if row["subject_id"] in subjects
    ]
    assert Counter(_source_row_sha256(row) for row in observed_native) == Counter(
        _source_row_sha256(row) for row in originals
    )
    expected = {}
    for broad in (row for row in originals if row["predicate_id"] == "skos:broadMatch"):
        for exact in originals:
            if exact["predicate_id"] != "skos:exactMatch" or exact["subject_id"] != broad["subject_id"]:
                continue
            key = exact["object_id"], broad["object_id"]
            assert key not in expected
            row = {field: broad.get(field, "") for field in _UNIFIED_FIELDS}
            row.update(
                subject_id=exact["object_id"],
                object_formula="",
                object_category="",
                source=(
                    f"mediaingredientmech_reviewed[manifest={_BROADER_MANIFEST_SHA256}]"
                    f"[broad-row-sha256={_source_row_sha256(broad)};exact-row-sha256={_source_row_sha256(exact)}]"
                ),
            )
            expected[key] = {"row": row, "broad": broad, "exact": exact}
    assert set(expected) == set(_BROADER_PAIRS)
    actual = [row for row in chemical_mapping_utils._iter_sssom_rows(path) if row["predicate_id"] == "skos:broadMatch"]
    assert Counter(_source_row_sha256(row) for row in actual) == Counter(
        _source_row_sha256(item["row"]) for item in expected.values()
    )
    assert _artifact_identity(path) == identity
    return expected


class TestReviewedBroaderArtifact:
    """Read all four reviewed form relations without admitting parent identity or aliases."""

    @pytest.mark.parametrize(("child", "parent"), _BROADER_PAIRS)
    def test_native_form_parents_keep_both_source_hashes_and_nonidentity_scope(
        self, reviewed_broader_claims, child, parent
    ):
        """Actual reader navigation follows each explicit form while all identity routes remain separate."""
        claim = reviewed_broader_claims[child, parent]
        broad, exact = claim["broad"], claim["exact"]
        assert chemical_mapping_utils.get_parents(child) == [parent]
        assert child not in chemical_mapping_utils.get_parents(parent)
        assert parent not in chemical_mapping_utils.get_xrefs(child)
        assert child not in chemical_mapping_utils.get_xrefs(parent)
        assert broad["subject_id"] not in chemical_mapping_utils.get_xrefs(parent)
        assert chemical_mapping_utils.get_formula(child) is None
        native_form_ids = {
            item["exact"]["object_id"]
            for item in reviewed_broader_claims.values()
            if item["exact"]["subject_id"] == broad["subject_id"]
        }
        assert chemical_mapping_utils.find_chebi_by_name(broad["subject_label"]) in native_form_ids
        assert chemical_mapping_utils.find_chebi_by_xref(broad["subject_id"]) in native_form_ids
        assert chemical_mapping_utils.find_chebi_by_name(broad["object_label"]) == parent
        parent_names = {
            chemical_mapping_utils.normalize_name(name)
            for name in [
                chemical_mapping_utils.get_canonical_name(parent),
                *chemical_mapping_utils.get_synonyms(parent),
            ]
        }
        form_names = {broad["subject_label"], *filter(None, exact["other"].split("|"))}
        assert not parent_names.intersection(chemical_mapping_utils.normalize_name(name) for name in form_names)


class TestHydrateEquivalents:
    """
    Regression tests for ``get_hydrate_equivalents``.

    Anhydrous and hydrated forms of a salt are different chemical
    entities (different formula, different molecular weight) but are
    media-recipe interchangeable. The consolidator emits
    ``skos:closeMatch`` rows for known pairs (e.g. CaCl2 ↔ CaCl2·2H2O)
    with ``comment == 'recipe_equivalent_hydrate'``, and the runtime
    reader exposes them through ``get_hydrate_equivalents`` for use by
    recipe comparators.

    The relationship is symmetric: looking up either form returns the
    other. Distinct from ``get_xrefs`` which asserts chemical identity.
    """

    def test_lookup_returns_recipe_equivalent_pair(self):
        """A known anhydrous CHEBI returns its hydrated companion."""
        # CHEBI:32149 (Na2SO4) ↔ CHEBI:32586 (Na2SO4·10H2O) — committed
        # in the unified mapping via the mediadive_compounds_hydrate path.
        equivs = chemical_mapping_utils.get_hydrate_equivalents("CHEBI:32149")
        assert equivs == ["CHEBI:32586"], (
            f"expected ['CHEBI:32586'], got {equivs!r} (consolidator hydrate-pair emission likely regressed)"
        )

    def test_lookup_is_symmetric(self):
        """The reverse direction returns the original CURIE — closeMatch is symmetric."""
        equivs = chemical_mapping_utils.get_hydrate_equivalents("CHEBI:32586")
        assert "CHEBI:32149" in equivs

    def test_unknown_curie_returns_empty(self):
        """A CURIE with no hydrate pair returns an empty list, not None."""
        # CHEBI:15377 (water) has no hydrate-pair partner.
        equivs = chemical_mapping_utils.get_hydrate_equivalents("CHEBI:15377")
        assert equivs == []

    def test_get_xrefs_does_not_contain_hydrate_partner(self):
        """
        Hydrate pairs are NOT exactMatch — they must not leak into xrefs.

        Regression guard for the prior behavior where the hydrate loader
        appended hydrated_chebi to xrefs (incorrectly asserting chemical
        identity). xref readers should now see only true exactMatch
        cross-references.
        """
        xrefs = chemical_mapping_utils.get_xrefs("CHEBI:32149")
        assert "CHEBI:32586" not in xrefs, (
            "CHEBI:32586 (hydrated form) leaked into xrefs of CHEBI:32149 "
            "(anhydrous) — must be in get_hydrate_equivalents instead"
        )


class TestKnownBadFilters:
    """
    Regression guards for the consolidator's KNOWN_BAD_* filter lists.

    Two upstream curation bugs surfaced in PR #559 review and were
    filtered at consolidator export time. These tests assert the bad data
    stays out of the unified SSSOM. If a future consolidator change
    accidentally drops the filters, these tests fail loudly.
    """

    def test_polluted_pubchem_mega_node_dropped(self):
        """``pubchem.compound:167312541`` (the peptone+casamino-acids merge) is gone."""
        chemical_mapping_utils.load_unified_mappings()
        # The mega-node should not appear as either a primary id (with a
        # canonical name index entry) nor as the target of any synonym
        # row. Lookups for the distinct ingredients should NOT resolve to
        # this CURIE.
        assert chemical_mapping_utils.get_canonical_name("pubchem.compound:167312541") is None
        assert chemical_mapping_utils.find_chebi_by_name("Peptone") != "pubchem.compound:167312541"
        assert chemical_mapping_utils.find_chebi_by_name("Vitamin-free casamino acids") != "pubchem.compound:167312541"

    def test_wrong_chebi_hydrate_xref_dropped(self):
        """
        CHEBI:32599 ↔ CHEBI:31795 false ``skos:exactMatch`` xref is gone.

        CHEBI:32599 is anhydrous magnesium sulfate; CHEBI:31795 is the
        heptahydrate. Different formulas, different molecular weights —
        not the same entity. The recipe-equivalent ``closeMatch`` row
        (with comment=recipe_equivalent_hydrate) is the only relationship
        between them that the unified SSSOM should carry.
        """
        xrefs_32599 = set(chemical_mapping_utils.get_xrefs("CHEBI:32599"))
        xrefs_31795 = set(chemical_mapping_utils.get_xrefs("CHEBI:31795"))
        assert "CHEBI:31795" not in xrefs_32599, (
            "CHEBI:31795 (heptahydrate) re-appeared as exactMatch xref of "
            "CHEBI:32599 (anhydrous) — KNOWN_BAD_XREF_PAIRS filter regressed"
        )
        assert "CHEBI:32599" not in xrefs_31795, "Reverse direction also re-appeared — filter regressed"


class TestNamePrecedence:
    """
    Regression tests for canonical-vs-synonym name index precedence.

    The unified SSSOM is exported sorted by ``object_id``, so a naive
    first-row-wins index lets a low-numbered CHEBI hijack a name via its
    synonym list before the higher-numbered CHEBI's canonical row is
    reached. The fix tracks a per-name rank (0=canonical, 1=synonym) and
    only overwrites when the new row has strictly better rank.
    """

    def test_perillyl_alcohol_resolves_to_canonical(self):
        """
        ``perillyl alcohol`` resolves to the canonical CHEBI, not a synonym hit.

        ``perillyl alcohol`` is the canonical name of CHEBI:15420 and
        also appears as a synonym of CHEBI:10782. Because the SSSOM is
        sorted by object_id, CHEBI:10782 is processed first and would
        win under setdefault() first-row-wins. The rank-aware indexer
        must overwrite when CHEBI:15420's canonical row arrives.
        """
        cid = chemical_mapping_utils.find_chebi_by_name("perillyl alcohol")
        assert cid == "CHEBI:15420", (
            f"expected CHEBI:15420 (canonical), got {cid!r} — "
            "name index precedence regressed: synonym hit hijacked the "
            "canonical-name lookup. See _index_name(rank=...) in "
            "kg_microbe/utils/chemical_mapping_utils.py."
        )

    def test_canonical_name_index_ranks_canonical_above_synonym(self):
        """``_CANONICAL_NAME_INDEX`` should resolve to the canonical owner."""
        chemical_mapping_utils.load_unified_mappings()
        canonical = chemical_mapping_utils._CANONICAL_NAME_INDEX.get("perillyl alcohol")
        assert canonical == "CHEBI:15420"
