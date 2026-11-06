"""Explicit synthetic generation preparation for finite MediaDive consumer fixtures."""

import copy
import hashlib
import json
from pathlib import Path

from kg_microbe.utils.mediadive_bulk_download import extract_compounds_from_media, extract_solutions_from_media
from kg_microbe.utils.source_finalization import SourceFinalizationRequired

CARRIER_MEDIUM = "fixture_catalogue_claims"
CARRIER_SOLUTION = "900000000"


def prepare_synthetic_exports(raw, *, catalogue_claims=None):
    """Derive consistent test exports while retaining every original copied fixture byte."""
    raw = Path(raw)
    names = ("media_detailed.json", "media_strains.json", "solutions.json", "compounds.json")
    paths = [raw / "mediadive.json", *(raw / "mediadive" / name for name in names)]
    originals = raw / "consumer-fixture-originals"
    originals.mkdir()
    before = {}
    for path in paths:
        relative = str(path.relative_to(raw))
        destination = originals / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        payload = path.read_bytes()
        destination.write_bytes(payload)
        before[relative] = hashlib.sha256(payload).hexdigest()
    catalogue = json.loads((raw / "mediadive.json").read_bytes())
    payloads = {name: json.loads((raw / "mediadive" / name).read_bytes()) for name in names}
    detailed = payloads["media_detailed.json"]
    solutions = payloads["solutions.json"]
    for medium in catalogue["data"]:
        key = str(medium["id"])
        detail = detailed[key]
        detail.setdefault("medium", copy.deepcopy(medium))
        if "solutions" in detail:
            expanded = []
            for reference in detail["solutions"]:
                value = copy.deepcopy(solutions[str(reference["id"])])
                for name, item in reference.items():
                    value.setdefault(name, item)
                if "recipe" in value and not isinstance(value["recipe"], list):
                    raise SourceFinalizationRequired("Synthetic endpoint fixture contains a malformed recipe list")
                expanded.append(value)
            detail["solutions"] = expanded
    if catalogue_claims:
        # This deliberately separate synthetic context establishes catalogue first
        # occurrences without inserting claimed catalogue metadata into target recipes.
        template = copy.deepcopy(catalogue["data"][0])
        template.update(
            id=CARRIER_MEDIUM,
            name="Explicit synthetic first-occurrence compound catalogue context",
            source="Synthetic offline test evidence",
        )
        carrier = []
        for key, original in catalogue_claims.items():
            row = copy.deepcopy(original)
            row.setdefault("compound_id", int(key))
            if str(row["compound_id"]) != str(key):
                raise SourceFinalizationRequired("Synthetic catalogue claim has a conflicting compound ID")
            if "compound" not in row:
                if not isinstance(row.get("name"), str) or not row["name"]:
                    raise SourceFinalizationRequired("Synthetic catalogue carrier needs an explicit compound label")
                # Only this separate synthetic recipe gets the catalogue label;
                # the caller's exact target recipe and original claims stay intact.
                row["compound"] = row["name"]
            carrier.append(row)
        catalogue["data"].insert(0, template)
        detailed[CARRIER_MEDIUM] = {
            "medium": template,
            "solutions": [{"id": int(CARRIER_SOLUTION), "name": "Synthetic catalogue context", "recipe": carrier}],
        }
    ordered = {str(medium["id"]): detailed[str(medium["id"])] for medium in catalogue["data"]}
    strains = payloads["media_strains.json"]
    for key, value in list(strains.items()):
        if value == {}:
            del strains[key]  # The caller separately requests explicit synthetic empty HTTP evidence.
        elif not isinstance(value, list):
            raise SourceFinalizationRequired("Synthetic strain fixture has a malformed association value")
    outputs = {
        raw / "mediadive.json": catalogue,
        raw / "mediadive/media_detailed.json": ordered,
        raw / "mediadive/media_strains.json": strains,
        raw / "mediadive/solutions.json": extract_solutions_from_media(ordered),
        raw / "mediadive/compounds.json": extract_compounds_from_media(ordered),
    }
    for path, value in outputs.items():
        path.write_text(json.dumps(value, indent=2) + "\n")
    report = {
        "kind": "explicit_synthetic_finite_fixture_generation",
        "originals": before,
        "derived": {str(path.relative_to(raw)): hashlib.sha256(path.read_bytes()).hexdigest() for path in outputs},
        "catalogue_claim_carrier": CARRIER_MEDIUM if catalogue_claims else None,
        "meaning": (
            "Original immutable test resources remain unchanged. Native target recipe records are retained; "
            "exports are reconstructed consistently for this finite synthetic acquisition scope."
        ),
    }
    (originals / "derivation.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")


def seal_consumer_fixture(raw, monkeypatch, *, catalogue_claims=None):
    """Build real sealed evidence and explicitly select its test-only reviewed-policy locator."""
    from kg_microbe.transform_utils.mediadive import endpoint_outcomes
    from tests.mediadive_generation_fixtures import seal_fixture_raw

    prepare_synthetic_exports(raw, catalogue_claims=catalogue_claims)
    generation = seal_fixture_raw(raw, missing_strains="explicit_empty")
    monkeypatch.setattr(endpoint_outcomes, "CURATED_UNKNOWN_POLICY", generation.curated_policy_path)
    return generation
