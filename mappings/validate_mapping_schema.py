#!/usr/bin/env python3
"""Schema/category validation gate for kg-microbe SSSOM-shaped mapping TSVs.

Complements the runtime-shared family-mismatch checker at
``mappings/validate_isolation_source_mappings.py`` (which uses
``kg_microbe.utils.isolation_source_mapping_utils.iter_validation_failures``)
with a different concern: instead of "does the row pass the loader's
family-compatibility rules", this script checks the SSSOM file's
schema, ontology-prefix allowlists, and lexical-drift heuristics that
catch a row's target term being too specific, too general, or in the
wrong ontology category.

Originally lived in the ``culturebotai-claw`` sibling repo as
``scripts/validate_isolation_source_mapping.py``; moved here on
2026-05-02 so the validator and the data it gates live in the same
repo.

Universal rules (applied in every profile):

  1. Every non-empty object_id is a valid CURIE (prefix:localpart)
  2. Every mapped row has a non-empty object_source
  3. object_source matches the prefix of object_id (only when
     object_source is itself a bare prefix; SSSOM files often use a
     fully-qualified source-CURIE/IRI like ``obo:chebi.owl`` and that
     is allowed without the equality check)
  4. predicate_id is a valid SKOS mapping predicate
  5. mapping_justification is a recognized semapv: term
  6. confidence is one of {high, medium, low} OR a numeric value in [0, 1]
  7. ontology category allow/disallow lists from the active profile
  8. unmapped rows (empty object_id) MUST have empty object_source +
     empty predicate_id
  9. NCBITaxon labels containing '<...>' homonym disambiguators
     (e.g. 'Calamus <ray-finned fishes>') are warned as too-specific
 10. closeMatch rows where the object label contains the subject as
     a token-prefix/-suffix plus a non-hedge extra token are warned
     as descendant drift

Profiles:

* ``isolation-source`` (default) — for ``isolation_source_to_ontology.tsv``.
  Allow: ENVO/UBERON/NCBITaxon/FOODON/BTO/PO/PATO/etc.
  Disallow: MONDO/DOID/HP (disease ontologies aren't places).
  Mixed: NCIT/mesh (warn on questionnaire/procedure/document hits).

* ``ingredient`` — for SSSOM-shaped ingredient mappings (e.g.
  ``mappings/ingredient_mappings.sssom.tsv``).
  Allow: CHEBI/FOODON/UBERON/ENVO/NCIT/MICRO/mesh/BTO/kgmicrobe.*/
         cas/registry/MIM/PO/FAO.
  Disallow: MONDO/DOID/HP/UO.
  Mixed: NCIT/mesh (same keyword warnings).

Skips lines starting with ``#`` (SSSOM YAML preamble).

Exits 2 on errors; 1 on warnings (only with ``--strict``); 0 if clean.

Usage::

    python3 mappings/validate_mapping_schema.py
    python3 mappings/validate_mapping_schema.py --profile ingredient
    python3 mappings/validate_mapping_schema.py --strict
    python3 mappings/validate_mapping_schema.py --path other.tsv

Or via the Makefile::

    make validate-isolation-source-schema
    make validate-ingredient-schema
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ISOLATION_PATH = REPO_ROOT / "mappings" / "isolation_source_to_ontology.tsv"
DEFAULT_INGREDIENT_PATH = REPO_ROOT / "mappings" / "ingredient_mappings.sssom.tsv"

_CURIE_RE = re.compile(r"^([A-Za-z][A-Za-z0-9._-]*):([^\s]+)$")

_VALID_PREDICATES = frozenset({
    "skos:exactMatch", "skos:closeMatch", "skos:narrowMatch",
    "skos:broadMatch", "skos:relatedMatch",
})

_VALID_JUSTIFICATIONS = frozenset({
    "semapv:LexicalMatching", "semapv:ManualMappingCuration",
    "semapv:UnspecifiedMatching", "semapv:CompositeMatching",
    "semapv:LogicalReasoning", "semapv:CrossSpeciesExactMatch",
    "",
})

_VALID_CONFIDENCE = frozenset({"high", "medium", "low", ""})


def _is_valid_confidence(value: str) -> bool:
    """Categorical labels OR a SSSOM-style numeric confidence in [0, 1]."""
    if value in _VALID_CONFIDENCE:
        return True
    try:
        n = float(value)
    except ValueError:
        return False
    return 0.0 <= n <= 1.0


# Conventional ontology "hedges" — generic taxonomic words that ontology
# labels append (or prepend) to disambiguate within the ontology, without
# narrowing the concept beyond the subject. e.g. UBERON labels anatomical
# entities as "X organ" or "X element"; ENVO labels environments as
# "X biome" / "X zone" / "X water body". A close-match where the only
# extra token(s) are hedges is NOT descendant drift.
_HEDGE_WORDS = frozenset({
    "organ", "element", "structure", "part", "parts", "system",
    "tissue", "cell", "fluid", "space", "lumen", "joint",
    "zone", "biome", "ecosystem", "environment",
    "material", "facility", "area", "region", "feature", "site",
    "body", "anatomical",
    "food", "product", "beverage",
    "device",
})

_HEDGE_PHRASES = (
    "water body",
    "anatomical part",
    "anatomical structure",
    "climatic zone",
    "food product",
)

_PARENS_RE = re.compile(r"\s*\([^)]*\)\s*$")


@dataclass(frozen=True)
class Profile:
    name: str
    allowed_prefixes: frozenset
    disallowed_prefixes: frozenset
    mixed_prefixes: frozenset
    non_target_keywords: tuple
    drift_whitelist_subjects: frozenset = field(default_factory=frozenset)
    disallow_reason: str = "off-domain ontology"
    keyword_warning: str = "label contains off-domain keyword"


ISOLATION_SOURCE_PROFILE = Profile(
    name="isolation-source",
    allowed_prefixes=frozenset({
        "ENVO", "UBERON", "NCBITaxon", "FOODON", "BTO", "PO", "PATO",
        "GENEPIO", "ExO", "FAO", "AGRO", "GO", "PCO", "PRIDE", "VariO",
        "UO", "METPO", "SNOMED", "CHEBI",
    }),
    disallowed_prefixes=frozenset({"MONDO", "DOID", "HP"}),
    mixed_prefixes=frozenset({"NCIT", "mesh"}),
    non_target_keywords=(
        "disease", "disorder", "syndrome", "lung disease",
        "questionnaire", "topical", "tablet", "capsule", "injection",
        "treatment", "therapy", "procedure",
        "organization", "company", "registry",
    ),
    drift_whitelist_subjects=frozenset({
        # Each pair has been manually reviewed; the subject → object
        # mapping is the curator-approved canonical even though the
        # lexical drift heuristic flags an extra modifier.
        "Indoor-Air", "Outdoor-Air",   # ENVO indoor/outdoor air
        "Aquaculture",                  # ENVO 'aquaculture farm' — sample IS the farm
        "Biopsy",                       # NCIT 'Biopsy Procedure' — sample IS the procedure
        "Bladder-stone",                # NCIT 'Urinary Bladder Stone' — only canonical type
        "Currency",                     # ENVO 'currency note' — paper currency = banknotes
        "Plaque",                       # UBERON 'dental plaque' — microbiology context
        "Sandy",                        # ENVO 'sandy desert' — dominant sandy iso-source
        "Tooth",                        # UBERON 'calcareous tooth' — synonym 'tooth'
        "Water-treatment-plant",        # ENVO 'drinking water treatment plant'
    }),
    disallow_reason="diseases/phenotypes are not isolation sources",
    keyword_warning="label contains non-isolation-source keyword",
)

INGREDIENT_PROFILE = Profile(
    name="ingredient",
    allowed_prefixes=frozenset({
        "CHEBI", "FOODON", "UBERON", "ENVO", "NCIT", "MICRO", "mesh",
        "BTO", "kgmicrobe.compound", "kgmicrobe.ingredient",
        "cas", "registry", "MIM", "PO", "FAO", "obo",
    }),
    disallowed_prefixes=frozenset({"MONDO", "DOID", "HP", "UO"}),
    mixed_prefixes=frozenset({"NCIT", "mesh"}),
    non_target_keywords=(
        "questionnaire", "procedure", "ability question",
        "organization", "company", "registry document",
        "syndrome", "disease",
    ),
    drift_whitelist_subjects=frozenset(),
    disallow_reason="diseases/phenotypes/units aren't valid ingredient targets",
    keyword_warning="label contains off-ingredient keyword",
)

PROFILES = {
    ISOLATION_SOURCE_PROFILE.name: ISOLATION_SOURCE_PROFILE,
    INGREDIENT_PROFILE.name: INGREDIENT_PROFILE,
}


def _normalize_for_drift(s: str) -> str:
    return s.replace("-", " ").replace("_", " ").strip().lower()


def _strip_trailing_parens(label: str) -> str:
    return _PARENS_RE.sub("", label).strip()


def _extras_after_subject(subject_norm: str, label_norm: str) -> list[str] | None:
    """Return the leftover tokens when subject is a prefix or suffix of label."""
    if not subject_norm or not label_norm or subject_norm == label_norm:
        return None
    if label_norm.startswith(subject_norm + " "):
        rest = label_norm[len(subject_norm) + 1:]
    elif label_norm.endswith(" " + subject_norm):
        rest = label_norm[: -(len(subject_norm) + 1)]
    else:
        return None
    for phrase in _HEDGE_PHRASES:
        rest = rest.replace(phrase, "_HEDGE_")
    return [t for t in rest.split() if t]


def _extra_tokens_are_hedges(extras: list[str]) -> bool:
    return bool(extras) and all(
        t in _HEDGE_WORDS or t == "_HEDGE_" for t in extras)


def _open_data_rows(path: Path):
    """Yield text lines, skipping a leading SSSOM YAML preamble (`#` lines)."""
    with open(path) as f:
        for line in f:
            if line.startswith("#"):
                continue
            yield line


def validate(path: Path, profile: Profile, strict: bool = False) -> int:
    if not path.is_file():
        print(f"ERROR: file not found: {path}", file=sys.stderr)
        return 2

    errors: list[str] = []
    warnings: list[str] = []

    reader = csv.DictReader(_open_data_rows(path), delimiter="\t")
    # Row indices are approximate (after preamble skip), but enough to grep.
    for i, row in enumerate(reader, 2):
        subj = row.get("subject_label") or row.get("subject_id") or ""
        oid = (row.get("object_id") or "").strip()
        osrc = (row.get("object_source") or "").strip()
        olabel = (row.get("object_label") or "").strip()
        pred = (row.get("predicate_id") or "").strip()
        justif = (row.get("mapping_justification") or "").strip()
        conf = (row.get("confidence") or "").strip()

        # Rule 8: unmapped rows must have empty mapping fields
        if not oid:
            if osrc or pred:
                errors.append(
                    f"row {i}: unmapped row '{subj}' has non-empty "
                    f"object_source={osrc!r} or predicate_id={pred!r}")
            continue

        # Rule 1: CURIE shape
        m = _CURIE_RE.match(oid)
        if not m:
            errors.append(
                f"row {i}: '{subj}' object_id={oid!r} is not a "
                f"valid CURIE")
            continue
        prefix = m.group(1)

        # Rule 2: mapped row must have object_source
        if not osrc:
            errors.append(
                f"row {i}: '{subj}' has object_id={oid!r} but no "
                f"object_source")

        # Rule 3: prefix consistency — applies only when object_source
        # is a bare ontology prefix (e.g. 'ENVO'). SSSOM files often use
        # a fully-qualified source-CURIE/IRI (e.g. 'obo:chebi.owl',
        # 'registry:cas') in which case there is no equality to enforce.
        osrc_is_bare_prefix = bool(osrc) and ":" not in osrc and "." not in osrc
        if osrc_is_bare_prefix and prefix.upper() != osrc.upper():
            errors.append(
                f"row {i}: '{subj}' object_id prefix={prefix!r} "
                f"!= object_source={osrc!r}")

        # Rule 4-6: vocab checks
        if pred and pred not in _VALID_PREDICATES:
            errors.append(
                f"row {i}: '{subj}' predicate_id={pred!r} not in "
                f"valid SKOS mapping predicates")
        if justif and justif not in _VALID_JUSTIFICATIONS:
            warnings.append(
                f"row {i}: '{subj}' mapping_justification={justif!r} "
                f"unusual")
        if conf and not _is_valid_confidence(conf):
            warnings.append(
                f"row {i}: '{subj}' confidence={conf!r} not in "
                f"{{high, medium, low}} or numeric [0,1]")

        # Rule 7: prefix allow/disallow per profile
        if prefix in profile.disallowed_prefixes:
            errors.append(
                f"row {i}: '{subj}' uses disallowed ontology "
                f"{prefix!r} ({profile.disallow_reason}): "
                f"{oid} ({olabel})")
        elif prefix in profile.mixed_prefixes:
            # Whitelisted subjects have been manually reviewed and the
            # NCIT/mesh hit on a "non-isolation-source" keyword is
            # accepted as the curator's intended mapping (e.g.
            # Biopsy → 'Biopsy Procedure'). Skip the keyword warning.
            if subj not in profile.drift_whitelist_subjects:
                low = olabel.lower()
                hit = next(
                    (k for k in profile.non_target_keywords if k in low),
                    None)
                if hit:
                    warnings.append(
                        f"row {i}: '{subj}' → {oid} ({olabel}) — "
                        f"{profile.keyword_warning} {hit!r}; review")
        elif prefix not in profile.allowed_prefixes:
            warnings.append(
                f"row {i}: '{subj}' → {oid}: ontology {prefix!r} "
                f"not on the {profile.name} allowlist; review")

        # Rule 9: NCBITaxon homonym-disambiguator hits
        if prefix == "NCBITaxon" and "<" in olabel:
            warnings.append(
                f"row {i}: '{subj}' → {oid} ({olabel}) — "
                f"NCBITaxon label contains '<>' homonym disambiguator; "
                f"often a too-specific lexical hit (use parent rank)")

        # Rule 10: descendant-drift on closeMatch rows
        if pred == "skos:closeMatch" and subj not in profile.drift_whitelist_subjects:
            ns = _normalize_for_drift(subj)
            no = _strip_trailing_parens(olabel.lower())
            extras = _extras_after_subject(ns, no)
            if extras and not _extra_tokens_are_hedges(extras):
                warnings.append(
                    f"row {i}: '{subj}' → {oid} ({olabel}) — "
                    f"object label looks like a descendant of subject "
                    f"(extra token(s) {extras!r}); review")

    print(f"profile: {profile.name}")
    print(f"path:    {path}")
    print(f"errors: {len(errors)}")
    print(f"warnings: {len(warnings)}")
    if errors:
        print("\n--- ERRORS ---", file=sys.stderr)
        for e in errors[:50]:
            print(f"  {e}", file=sys.stderr)
        if len(errors) > 50:
            print(f"  ... and {len(errors) - 50} more", file=sys.stderr)
    if warnings:
        print("\n--- WARNINGS ---", file=sys.stderr)
        for w in warnings[:30]:
            print(f"  {w}", file=sys.stderr)
        if len(warnings) > 30:
            print(f"  ... and {len(warnings) - 30} more", file=sys.stderr)

    if errors:
        return 2
    if strict and warnings:
        return 1
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--path", type=Path, default=None,
                    help="path to the mapping TSV (default chosen by --profile)")
    ap.add_argument("--profile", choices=sorted(PROFILES),
                    default="isolation-source",
                    help="validation profile (default: isolation-source)")
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 on warnings (default: warnings non-blocking)")
    args = ap.parse_args()
    profile = PROFILES[args.profile]
    path = args.path or (
        DEFAULT_INGREDIENT_PATH if profile.name == "ingredient"
        else DEFAULT_ISOLATION_PATH)
    return validate(path, profile, strict=args.strict)


if __name__ == "__main__":
    sys.exit(main())
