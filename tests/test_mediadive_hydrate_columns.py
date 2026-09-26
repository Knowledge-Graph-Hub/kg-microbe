"""Supplied hydrate identities require native chemical-parent and scope evidence (#1168)."""

import csv
from pathlib import Path
from types import SimpleNamespace

import pytest

from kg_microbe.transform_utils.mediadive import mediadive as module

# Pinned native assertions, source lines and input hashes live in the immutable
# fixture and companion note. These are has_part assertions, never identities.
with (Path(__file__).parent / "resources" / "mediadive_hydrate_columns.tsv").open(encoding="utf-8") as stream:
    PAIRS = [
        (row["original"], row["base_id"], row["hydrated_id"], row["native_label"])
        for row in csv.DictReader(stream, delimiter="\t")
    ]
MAGNESIUM = next(pair for pair in PAIRS if pair[2] == "CHEBI:86345")
HEADERS = ["subject", "predicate", "object", "relation", "primary_knowledge_source"]


def write_tsv(path, rows, fields=None):
    """Write a small hermetic mapping or ontology evidence fixture."""
    fields = fields or list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, delimiter="\t", fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    return path


def mapping(pair=MAGNESIUM, **overrides):
    """Make one explicitly supplied base/hydrate mapping row."""
    name, base, target, label = pair
    return {"original": name, "mapped": base, "hydrated_chebi_id": target, "hydrated_chebi_label": label, **overrides}


@pytest.fixture
def resolver(tmp_path, monkeypatch):
    """Initialize only the offline runtime paths involved in hydrate admission."""
    value = module.MediaDiveTransform.__new__(module.MediaDiveTransform)
    value.chebi_labels = {target: label for _, _, target, label in PAIRS}
    value.chebi_labels.update({base: "anhydrous base" for _, base, _, _ in PAIRS})
    value.chebi_hydrate_names = {}
    value.chemical_loader = SimpleNamespace(find_chebi_by_name=lambda name: None)
    value.compound_mappings = {}
    value.compounds_data = {}
    value.solutions_data = {}
    value.using_bulk_data = True
    value.api_calls_avoided = 0
    value.translation_table = str.maketrans("", "", "()")
    edges = [
        dict(zip(HEADERS, [target, "biolink:has_part", base, "BFO:0000051", "infores:chebi"], strict=True))
        for _, base, target, _ in PAIRS
    ]
    monkeypatch.setattr(module, "CHEBI_EDGES_FILE", write_tsv(tmp_path / "native.tsv", edges))
    return value


@pytest.mark.parametrize("pair", PAIRS)
@pytest.mark.parametrize("route", ["compound", "solution"])
def test_supplied_native_backed_hydrates_reach_recipe_identity(resolver, tmp_path, pair, route):
    """Use an explicitly supplied hydrate, retaining quantitative recipe data."""
    name, _, target, _ = pair
    path = write_tsv(tmp_path / "mappings.tsv", [mapping(pair)])
    resolver.compound_mappings.update(resolver._load_mapping_file(path, "fixture"))
    assert resolver.compound_mappings == {name.lower(): target}
    resolver.solutions_data = {"1": {"recipe": [{route + "_id": 99, route: name, "amount": 2, "unit": "g"}]}}
    result = resolver.get_compounds_of_solution("1")[name]
    assert result == {"id": target, "amount": 2, "unit": "g", "g_l": None, "mmol_l": None}
    assert resolver.solutions_data["1"]["recipe"][0][route] == name


@pytest.mark.parametrize(
    "overrides",
    [
        {"hydrated_chebi_id": "CHEBI:999999"},
        {"hydrated_chebi_id": "CHEBI:86345.0"},
        {"hydrated_chebi_id": "CHEBI:٨٦٣٤٥"},
        {"hydrated_chebi_label": "cobalt chloride hexahydrate"},
        {"hydrated_chebi_label": ""},
        {"original": "MgCl2 x 5 H2O"},
        {"original": "MgCl2 x n H2O"},
        {"original": "magnesium chloride hydrate"},
        {"original": "MgCl2"},
        {"hydration_number": "5"},
        {"hydration_number": "unknown"},
        {"hydrated_chebi_id": "CHEBI:131523", "hydrated_chebi_label": "manganese(II) sulfate hexahydrate"},
    ],
)
def test_recovery_requires_consistent_supplied_and_native_evidence(resolver, tmp_path, overrides):
    """Matching water counts cannot manufacture a different base chemical identity."""
    path = write_tsv(tmp_path / "mappings.tsv", [mapping(**overrides)])
    assert resolver._load_mapping_file(path, "fixture") == {}


@pytest.mark.parametrize("defect", ["reverse", "wrong_provenance", "wrong_predicate", "wrong_relation", "missing_pair"])
def test_native_part_evidence_has_required_direction_and_provenance(resolver, tmp_path, defect):
    """Unrelated, reversed or non-native assertions do not prove a supplied hydrate."""
    row = dict(
        zip(HEADERS, ["CHEBI:86345", "biolink:has_part", "CHEBI:6636", "BFO:0000051", "infores:chebi"], strict=True)
    )
    if defect == "reverse":
        row["subject"], row["object"] = row["object"], row["subject"]
    elif defect == "wrong_provenance":
        row["primary_knowledge_source"] = "infores:mediadive"
    elif defect == "wrong_predicate":
        row["predicate"] = "biolink:close_match"
    elif defect == "wrong_relation":
        row["relation"] = "skos:exactMatch"
    else:
        row["object"] = "CHEBI:86360"
    write_tsv(module.CHEBI_EDGES_FILE, [row])
    path = write_tsv(tmp_path / "mappings.tsv", [mapping()])
    assert resolver._load_mapping_file(path, "fixture") == {}


@pytest.mark.parametrize("defect", ["absent", "header", "row"])
def test_native_infrastructure_failure_aborts(resolver, tmp_path, defect):
    """Native evidence failures are never swallowed as optional mapping warnings."""
    if defect == "absent":
        module.CHEBI_EDGES_FILE.unlink()
    elif defect == "header":
        module.CHEBI_EDGES_FILE.write_text("subject\tobject\n")
    else:
        module.CHEBI_EDGES_FILE.write_text("\t".join(HEADERS) + "\nCHEBI:86345\tbiolink:has_part\n")
    path = write_tsv(tmp_path / "mappings.tsv", [mapping()])
    with pytest.raises((FileNotFoundError, ValueError)):
        resolver._load_mapping_file(path, "fixture")


@pytest.mark.parametrize("reverse", [False, True])
def test_contradictory_rows_cannot_choose_by_input_order(resolver, tmp_path, reverse):
    """One valid and one contradictory explicit hydrate claim keep the source local."""
    rows = [mapping(), mapping(hydrated_chebi_label="unrelated hexahydrate")]
    path = write_tsv(tmp_path / "mappings.tsv", rows[::-1] if reverse else rows)
    assert resolver._load_mapping_file(path, "fixture") == {}
    strict = write_tsv(tmp_path / "strict.tsv", [{"original": MAGNESIUM[0], "mapped": MAGNESIUM[2]}])
    assert resolver._load_mapping_file(strict, "strict fallback") == {}


@pytest.mark.parametrize("strict_first", [False, True])
def test_conflicting_priority_files_cannot_reinstate_identity(resolver, tmp_path, strict_first):
    """A contradiction removes even an already-installed legacy mapping."""
    name = MAGNESIUM[0]
    hydrate = write_tsv(tmp_path / "hydrate.tsv", [mapping()])
    # This separately supplied native target has the same water count, but is
    # a different chemical; it is not allowed to win by either file order.
    strict = write_tsv(tmp_path / "strict.tsv", [{"original": name, "mapped": "CHEBI:131523"}])
    for path in [strict, hydrate] if strict_first else [hydrate, strict]:
        resolver.compound_mappings.update(resolver._load_mapping_file(path, "fixture"))
    assert resolver.compound_mappings == {}


def test_native_alias_and_unique_native_count_can_refine_generic_label(resolver, tmp_path):
    """An independently native synonym can support a generic hydrate's water count."""
    resolver.chebi_labels["CHEBI:86345"] = "magnesium dichloride hydrate"
    resolver.chebi_hydrate_names["CHEBI:86345"] = ("magnesium dichloride hexahydrate",)
    path = write_tsv(tmp_path / "mappings.tsv", [mapping(hydration_number="6")])
    assert resolver._load_mapping_file(path, "fixture") == {MAGNESIUM[0].lower(): "CHEBI:86345"}


def test_conflicting_native_counts_withhold_recovery(resolver, tmp_path):
    """Native generic hydrate evidence must not have incompatible numeric aliases."""
    resolver.chebi_labels["CHEBI:86345"] = "magnesium dichloride hydrate"
    resolver.chebi_hydrate_names["CHEBI:86345"] = ("magnesium dichloride hexahydrate", "magnesium dichloride dihydrate")
    path = write_tsv(tmp_path / "mappings.tsv", [mapping()])
    assert resolver._load_mapping_file(path, "fixture") == {}


def test_duplicate_same_identity_and_existing_declared_hydrate_remain_usable(resolver, tmp_path):
    """Repeated corroborated claims and an already-correct mapped target are not conflicts."""
    rows = [mapping(), mapping(mapped="CHEBI:86345")]
    path = write_tsv(tmp_path / "mappings.tsv", rows)
    assert resolver._load_mapping_file(path, "fixture") == {MAGNESIUM[0].lower(): "CHEBI:86345"}


def test_blank_hydrate_column_does_not_invent_identity(resolver, tmp_path):
    """An optional empty field preserves existing admitted mappings but cannot strip water."""
    path = write_tsv(tmp_path / "mappings.tsv", [mapping(hydrated_chebi_id="", hydrated_chebi_label="")])
    assert resolver._load_mapping_file(path, "fixture") == {}
