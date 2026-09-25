"""
Curated, target-scoped exclusions for false ingredient identities.

These policies reject specific lexical groundings and equivalence pairs, never
an ontology identifier itself. Native ontology declarations/edges remain valid.
"""

import csv
import re
from functools import lru_cache
from pathlib import Path

IDENTITY_POLICY = Path(__file__).resolve().parents[2] / "mappings" / "ingredient_identity_exclusions.tsv"
NAME_SCOPE_POLICY = IDENTITY_POLICY.with_name("ingredient_name_scopes.tsv")


def _scope_key(value):
    """Normalize separators without removing chemical locants or suffixes."""
    return re.sub(r"[\s_-]+", " ", value.strip().casefold())


@lru_cache(maxsize=1)
def _ingredient_scope_policy():
    """Keep finite case-sensitive aliases out of the ordinary case-folded routes."""
    routes, cas, case_sensitive, normal_keys = {}, {}, {}, set()
    with NAME_SCOPE_POLICY.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if reader.fieldnames != ["kind", "query", "target_id", "reason"]:
            raise ValueError("Invalid ingredient name scope header")
        for row in reader:
            if None in row or any(not str(value or "").strip() for value in row.values()):
                raise ValueError("Incomplete ingredient name scope")
            if row["kind"] not in {"name", "cas", "case_sensitive_name"}:
                raise ValueError("Invalid ingredient name scope kind")
            query, target = row["query"].strip(), row["target_id"]
            if row["kind"] == "case_sensitive_name":
                if query in case_sensitive or _scope_key(query) in normal_keys:
                    raise ValueError("Duplicate or case-folded ingredient name scope")
                case_sensitive[query] = target
                continue
            if _scope_key(query) in normal_keys or query.casefold() in {key.casefold() for key in case_sensitive}:
                raise ValueError("Duplicate ingredient name scope")
            routes[query] = target
            normal_keys.add(_scope_key(query))
            if row["kind"] == "cas":
                match = re.fullmatch(r"cas:(\d{2,7})-(\d{2})-(\d)", query)
                if not match or sum(i * int(n) for i, n in enumerate((match[1] + match[2])[::-1], 1)) % 10 != int(
                    match[3]
                ):
                    raise ValueError("Invalid reviewed CAS annotation")
                cas[query] = target
                routes[query.removeprefix("cas:")] = target
                normal_keys.add(_scope_key(query.removeprefix("cas:")))
    return (
        routes,
        cas,
        case_sensitive,
        {query.casefold() for query in case_sensitive},
        {_scope_key(query): target for query, target in routes.items()},
    )


def ingredient_name_scopes():
    """Return existing (ordinary query routes, CAS annotations), excluding exact-case aliases."""
    routes, cas, _, _, _ = _ingredient_scope_policy()
    return routes, cas


ingredient_name_scopes.cache_clear = _ingredient_scope_policy.cache_clear


def ingredient_case_sensitive_name_scope(name):
    """Return (recognized family, exact-case target); unknown spelling in a family fails closed."""
    _, _, routes, families, _ = _ingredient_scope_policy()
    query = str(name or "").strip()
    # Punctuation erased by the shared name index must not permit a legacy
    # fallback for an otherwise unreviewed spelling of this finite family.
    family = re.sub(r"[^\w\s'-]", "", query.casefold())
    return family in families, routes.get(query)


def _normalized_scope_routes():
    """Index the small, immutable policy once for graph-scale name imports."""
    return _ingredient_scope_policy()[4]


def ingredient_name_target(name):
    """Return the reviewed target for an explicitly scoped query, if any."""
    recognized, target = ingredient_case_sensitive_name_scope(name)
    if recognized:
        return target
    return _normalized_scope_routes().get(_scope_key(str(name or "")))


def ingredient_cas_annotations(target):
    """Return verified CAS node annotations; these are not same_as claims."""
    return sorted(cas for cas, curie in ingredient_name_scopes()[1].items() if curie == target)


def accepted_name_scope(subject, target, resolved, explicit_target):
    """Accept only the reviewed generic/specific Xanthine distinction with both routes intact."""
    return subject == "MIM:Xanthine" and target == explicit_target == "CHEBI:17712" and resolved == "CHEBI:15318"


@lru_cache(maxsize=1)
def ingredient_identity_policy():
    """Read and validate immutable-in-process curated identity rules."""
    names, xrefs, labels = {}, set(), {}
    with IDENTITY_POLICY.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if reader.fieldnames != ["target_id", "authority_label", "kind", "value", "reason"]:
            raise ValueError(f"Invalid ingredient identity policy header: {IDENTITY_POLICY}")
        for row in reader:
            if None in row or any(not str(value or "").strip() for value in row.values()):
                raise ValueError(f"Incomplete ingredient identity policy: {row!r}")
            target = row["target_id"].casefold()
            label = row["authority_label"]
            if target in labels and labels[target] != label:
                raise ValueError(f"Conflicting authority label for {target}")
            labels[target] = label
            if row["kind"] == "name_pattern":
                pattern = re.compile(row["value"])
                if pattern.search(label):
                    raise ValueError(f"Identity policy rejects its authority label: {target}")
                names.setdefault(target, []).append(pattern)
            elif row["kind"] == "xref" and row["value"] != target:
                xrefs.add(frozenset((target, row["value"].casefold())))
            else:
                raise ValueError(f"Invalid ingredient identity policy kind/value: {row!r}")
    return names, xrefs, labels


def ingredient_mapping_allowed(name: str, target: str) -> bool:
    """Reject reviewed ingredient-name/target pairs without banning targets."""
    recognized, scoped_target = ingredient_case_sensitive_name_scope(name)
    if recognized and (scoped_target is None or scoped_target.casefold() != str(target or "").casefold()):
        return False
    patterns = ingredient_identity_policy()[0].get(str(target or "").casefold(), ())
    original = str(name or "").strip()
    # Producers normalize labels differently. In particular MetaTraits keys
    # and legacy ingredient names may use underscores or hyphens for spaces.
    # Match the lookup reader's punctuation removal as well: a source label
    # such as Trypt.one indexes as tryptone and must not bypass this guard.
    normalized = re.sub(r"[^\w\s-]", "", original)
    forms = (original, normalized, re.sub(r"[\s_-]+", " ", original), re.sub(r"[\s_-]+", " ", normalized))
    return not any(pattern.search(form) for pattern in patterns for form in forms)


def ingredient_xref_allowed(subject: str, target: str) -> bool:
    """Reject reviewed false equivalences in either serialization direction."""
    return (
        frozenset((str(subject or "").casefold(), str(target or "").casefold())) not in ingredient_identity_policy()[1]
    )


def ingredient_authority_label(target: str) -> str:
    """Return the authority label recorded with a reviewed exclusion."""
    return ingredient_identity_policy()[2].get(str(target or "").casefold(), "")
