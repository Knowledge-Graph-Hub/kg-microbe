"""Hydrated ingredients cannot become their anhydrous parents by any fallback (#1158)."""

import csv
from pathlib import Path
from types import SimpleNamespace

import pytest

from kg_microbe.transform_utils.mediadive.mediadive import MediaDiveTransform
from kg_microbe.utils import chemical_mapping_utils as runtime
from kg_microbe.utils.ingredient_identity import ingredient_hydration_compatible
from tests.test_chemical_mapping_utils import _write_mock_sssom

FIXTURE = Path(__file__).parent / "resources/hydrate_identity_authorities.tsv"
with FIXTURE.open(newline="") as handle:
    AUTHORITIES = {row["id"]: row for row in csv.DictReader(handle, delimiter="\t")}

UNSAFE = [
    ("FeCl3 x 6 H2O", "CHEBI:30808"),
    ("CoCl2 x 6 H2O", "CHEBI:35696"),
    ("Na2WO4 x 2 H2O", "CHEBI:63940"),
    ("NiCl2 x 6 H2O", "CHEBI:34887"),
]


def resolver(unified=None, legacy=None, embedded=None, labels=None):
    """Instantiate only the actual resolver with independent immutable authority labels."""
    value = MediaDiveTransform.__new__(MediaDiveTransform)
    value.chebi_labels = {curie: row["name"] for curie, row in AUTHORITIES.items()}
    value.chebi_hydrate_names = {curie: row["synonym"].split("|") for curie, row in AUTHORITIES.items()}
    value.chemical_loader = SimpleNamespace(
        find_chebi_by_name=lambda *args, **kwargs: unified,
        get_canonical_name=lambda target: (labels or {}).get(target),
    )
    value.compound_mappings = legacy or {}
    value.compounds_data = {"99": embedded or {}}
    value.using_bulk_data = True
    value.api_calls_avoided = 0
    return value


@pytest.mark.parametrize("name,target", UNSAFE)
@pytest.mark.parametrize("route", ["unified", "legacy", "embedded", "mixed"])
def test_four_demonstrated_hydrates_cannot_become_anhydrous(name, target, route):
    """The same original query reaches admission after every independently attempted route."""
    value = resolver(
        unified=target if route in {"unified", "mixed"} else None,
        legacy={name.lower(): target} if route in {"legacy", "mixed"} else {},
        embedded={"ChEBI": target.split(":")[1]} if route in {"embedded", "mixed"} else {},
    )
    assert value.standardize_compound_id("99", name) == "mediadive.ingredient:99"


@pytest.mark.parametrize("route", ["unified", "legacy", "embedded", "mixed"])
def test_independently_supplied_iron_hexahydrate_survives(route):
    """A rejected unified anhydrous match must not hide a known correct later hydrate."""
    value = resolver(
        unified="CHEBI:86254" if route == "unified" else "CHEBI:30808" if route == "mixed" else None,
        legacy={"fecl3 x 6 h2o": "CHEBI:86254"} if route in {"legacy", "mixed"} else {},
        embedded={"ChEBI": "86254"} if route == "embedded" else {},
    )
    assert value.standardize_compound_id("99", "FeCl3 x 6 H2O") == "CHEBI:86254"
    # Knowing one hydrate does not authorize another or an unspecified water count.
    value.compound_mappings.update({"fecl3 x 2 h2o": "CHEBI:86254", "fecl3 x n h2o": "CHEBI:86254"})
    assert value.standardize_compound_id("99", "FeCl3 x 2 H2O") == "mediadive.ingredient:99"
    assert value.standardize_compound_id("99", "FeCl3 x n H2O") == "mediadive.ingredient:99"


@pytest.mark.parametrize("key,prefix", [("KEGG-Compound", "KEGG:"), ("PubChem", "PubChem:"), ("CAS-RN", "CAS-RN:")])
@pytest.mark.parametrize("label", [None, "unhydrated fixture chemical", "fixture chemical dihydrate"])
def test_other_embedded_namespaces_require_independent_matching_scope(key, prefix, label):
    """Missing labels and different hydrates cannot escape via an alternate namespace."""
    value = resolver(
        embedded={key: "fixture", "compound": "fixture chemical x 6 H2O"}, labels={prefix + "fixture": label}
    )
    assert value.standardize_compound_id("99") == "mediadive.ingredient:99"
    value.chemical_loader.get_canonical_name = lambda target: "fixture chemical hexahydrate"
    assert value.standardize_compound_id("99") == prefix + "fixture"


def test_native_label_overrides_contaminated_unified_label():
    """A circular source alias is not independent support for changing a native identity."""
    value = resolver(unified="CHEBI:30808", labels={"CHEBI:30808": "FeCl3 x 6 H2O"})
    assert value.standardize_compound_id("99", "FeCl3 x 6 H2O") == "mediadive.ingredient:99"


@pytest.mark.parametrize("name,target", UNSAFE)
def test_nested_solution_routes_obey_hydration_scope(name, target):
    """Nested solution mappings cannot bypass ingredient admission."""
    value = resolver(unified=target, legacy={name.lower(): target})
    value.translation_table = {}
    value.solutions_data = {"1": {"recipe": [{"solution_id": 2, "solution": name, "amount": 5, "unit": "ml"}]}}
    assert value.get_compounds_of_solution("1")[name] == {
        "id": "mediadive.solution:2",
        "amount": 5,
        "unit": "ml",
        "g_l": None,
        "mmol_l": None,
    }


def test_legacy_filter_rejects_false_identity_before_selecting_valid_later_row(tmp_path):
    """Hydrate admission occurs before duplicate-name priority is chosen."""
    path = tmp_path / "legacy.tsv"
    path.write_text("original\tmapped\nFeCl3 x 6 H2O\tCHEBI:30808\nFeCl3 x 6 H2O\tCHEBI:86254\n")
    assert resolver()._load_mapping_file(path, "fixture") == {"fecl3 x 6 h2o": "CHEBI:86254"}


@pytest.mark.parametrize(
    "query,label,allowed",
    [
        ("compound x H2O", "compound monohydrate", True),
        (" compound · 6 H2O ", "compound hexahydrate", True),
        ("compound.6H2O", "compound hexahydrate", True),
        ("compound * 0.5 H2O", "compound hemihydrate", True),
        ("compound x 18 H2O", "compound octadecahydrate", True),
        ("compound x n H2O", "compound hydrate", True),
        ("compound.xH2O", "compound hydrate", True),
        ("compound.xH2O", "compound monohydrate", False),
        ("compound x 2 H2O", "compound hexahydrate", False),
        ("compound x n H2O", "compound hexahydrate", False),
        ("compound hydrate", "compound hexahydrate", False),
        ("compound hydrated", "compound", False),
        ("compound hexahydrate", "", False),
        ("compound", "compound hexahydrate", False),
        ("compound hexahydrate", "compound hexahydrate", True),
        ("native hydrate", "native hydrate", True),
        ("native chemical", "", True),
        ("cas:10025-77-1", "iron trichloride hexahydrate", True),
        ("10025-77-1", "iron trichloride hexahydrate", True),
        ("10025-77-2", "iron trichloride hexahydrate", False),
    ],
)
def test_hydration_scope_is_only_a_negative_admission_check(query, label, allowed):
    """Water-count compatibility never manufactures a target or a base-chemical identity."""
    assert ingredient_hydration_compatible(query, label) is allowed


@pytest.mark.parametrize(
    "query,target",
    [
        ("Al2(SO4)3 x 18 H2O", "CHEBI:74779"),
        ("Impenum monohydrate", "CHEBI:51799"),
        ("VOSO4 x n H2O", "CHEBI:87020"),
    ],
)
def test_native_hydrate_scope_controls_preserve_supported_existing_targets(query, target):
    """Independent native evidence, never a circular recipe alias, supports these scopes."""
    value = resolver(unified=target)
    assert value.standardize_compound_id("99", query) == target


def test_unspecified_target_refinement_requires_consistent_independent_numeric_evidence():
    """Neither an absent count nor conflicting native counts chooses a hydrate."""
    query, label = "Impenum monohydrate", "imipenem hydrate"
    assert not ingredient_hydration_compatible(query, label)
    assert ingredient_hydration_compatible(query, label, ["N-formimidoyl thienamycin monohydrate"])
    assert not ingredient_hydration_compatible(query, label, ["compound monohydrate", "compound dihydrate"])
    assert not ingredient_hydration_compatible("VOSO4 x 2 H2O", "vanadyl sulfate hydrate", ["VOSO4.nH2O"])


@pytest.mark.parametrize("native_first", [False, True])
@pytest.mark.parametrize("native_source", ["native_ontology:chebi", "historical_recipe"])
def test_shared_runtime_refines_hydrate_only_from_native_evidence(tmp_path, native_first, native_source):
    """Source aliases cannot bootstrap water counts; native evidence is order-independent."""
    from tests.test_mim_conservative_refresh import FIELDS, _metadata, _row, _table

    path = tmp_path / "native-hydrate.sssom.tsv"
    native = _row(
        "kgm.name:native",
        "CHEBI:51799",
        "imipenem hydrate",
        native_source,
        "skos:closeMatch",
        "N-formimidoyl thienamycin monohydrate",
        "synonym",
    )
    query = _row(
        "kgm.name:query",
        "CHEBI:51799",
        "imipenem hydrate",
        "reviewed_mim",
        "skos:closeMatch",
        "Impenum monohydrate",
        "synonym",
    )
    _table(path, FIELDS, [native, query] if native_first else [query, native], _metadata())
    runtime.load_unified_mappings(path)
    assert runtime.find_chebi_by_name("Impenum monohydrate") == (
        "CHEBI:51799" if native_source.startswith("native_") else None
    )
    assert runtime.find_chebi_by_name("imipenem hydrate") == "CHEBI:51799"


@pytest.mark.parametrize("synonyms", [True, False])
def test_shared_runtime_cannot_strip_or_reverse_hydration(tmp_path, synonyms):
    """All consumers of the shared lookup retain distinct hydration states."""
    path = tmp_path / "mappings.sssom.tsv.gz"
    entries = [
        {"id": curie, "canonical_name": row["name"], "synonyms": row["synonym"], "category": "biolink:ChemicalEntity"}
        for curie, row in AUTHORITIES.items()
    ]
    # Deliberately stale exact aliases must not outrank target hydration scope.
    for query, target in UNSAFE:
        next(row for row in entries if row["id"] == target)["synonyms"] += "|" + query
    _write_mock_sssom(entries, path)
    runtime.load_unified_mappings(path)
    for query, _ in UNSAFE:
        for mode in [{}, {"fuzzy_hydrate": True}, {"fuzzy_stereochemistry": True}]:
            assert runtime.find_chebi_by_name(query, synonyms=synonyms, **mode) is None
    for curie, row in AUTHORITIES.items():
        assert runtime.find_chebi_by_name(row["name"], synonyms=synonyms) == curie
    assert runtime.find_chebi_by_name("FeCl3.6H2O") == "CHEBI:86254"
    assert runtime.find_chebi_by_name("iron trichloride x 2 H2O", fuzzy_hydrate=True) is None
    # Removing the anhydrous record cannot make a bare query resolve to a hydrate.
    hydrated_only = tmp_path / "hydrated-only.sssom.tsv.gz"
    _write_mock_sssom([entries[1]], hydrated_only)
    runtime.load_unified_mappings(hydrated_only)
    assert runtime.find_chebi_by_name("iron trichloride", synonyms=synonyms, fuzzy_hydrate=True) is None


def test_weak_recipe_hydrate_relation_is_not_used_as_identity(tmp_path):
    """The separate weak-relation API survives without installing name/xref substitutions."""
    from tests.test_mim_conservative_refresh import FIELDS, _metadata, _row, _table

    path = tmp_path / "weak.sssom.tsv"
    _table(
        path,
        FIELDS,
        [
            _row("kgm.name:iron", "CHEBI:30808", "iron trichloride", name="iron trichloride", comment="canonical_name"),
            _row(
                "kgm.name:iron_hydrate",
                "CHEBI:86254",
                "iron trichloride hexahydrate",
                name="iron trichloride hexahydrate",
                comment="canonical_name",
            ),
            _row(
                "CHEBI:30808",
                "CHEBI:86254",
                "iron trichloride hexahydrate",
                predicate="skos:closeMatch",
                comment="recipe_equivalent_hydrate",
            ),
        ],
        _metadata(),
    )
    runtime.load_unified_mappings(path)
    assert runtime.get_hydrate_equivalents("CHEBI:30808") == ["CHEBI:86254"]
    assert runtime.get_hydrate_equivalents("CHEBI:86254") == ["CHEBI:30808"]
    assert runtime.find_chebi_by_name("iron trichloride") == "CHEBI:30808"
    assert runtime.find_chebi_by_name("iron trichloride x 6 H2O", fuzzy_hydrate=True) is None
    assert runtime.find_chebi_by_xref("CHEBI:30808") is None
