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

# These are lexical scope markers, not a chemical formula parser. Comparing
# them may reject an existing mapping; it must never create a new identity.
_HYDRATE_FORMULA = re.compile(r"[x·*.]\s*(?P<count>\d+(?:\.\d+)?|n|x)?\s*h2o\s*$", re.IGNORECASE)
_HYDRATE_WORD = re.compile(
    r"\b(?P<count>mono|di|tri|tetra|penta|hexa|hepta|octa|nona|deca|undeca|dodeca|octadeca|hemi|sesqui)?hydrate\b",
    re.IGNORECASE,
)
_HYDRATE_COUNTS = {
    "mono": 1,
    "di": 2,
    "tri": 3,
    "tetra": 4,
    "penta": 5,
    "hexa": 6,
    "hepta": 7,
    "octa": 8,
    "nona": 9,
    "deca": 10,
    "undeca": 11,
    "dodeca": 12,
    "octadeca": 18,
    "hemi": 0.5,
    "sesqui": 1.5,
}


def _hydration_scope(name):
    """Read an explicit lexical water count; unknown hydrates have unresolved scope."""
    text = str(name or "").strip()
    match = _HYDRATE_FORMULA.search(text)
    if match:
        count = match["count"] or "1"
        return "unknown" if count.lower() in {"n", "x"} else float(count)
    match = _HYDRATE_WORD.search(text)
    if match:
        return _HYDRATE_COUNTS.get((match["count"] or "").lower(), "unknown")
    if re.search(r"\bhydrated\b", text, re.IGNORECASE):
        return "unknown"
    return None


def ingredient_hydration_compatible(name, authority_label, authority_names=()):
    """
    Reject hydration-scope changes without asserting a replacement chemical identity.

    A separately supplied mapping still establishes the base identity. An
    explicit hydrate additionally needs a declared target label with the same
    water count. Independently native synonyms may refine an unspecified target
    hydrate only when their numeric scopes agree. Two unspecified hydrate scopes
    are compatible, but neither authorizes a specific water count. Missing
    evidence fails closed. Native labels remain queryable.
    """
    query, label = str(name or "").strip(), str(authority_label or "").strip()
    lower_query, lower_label = query.casefold(), label.casefold()
    if not any(marker in text for text in (lower_query, lower_label) for marker in ("hydrat", "h2o")):
        return True  # The common graph-scale path needs no regex parsing.
    identifier = re.fullmatch(r"(?:cas(?:-rn)?:)?(\d{2,7})-(\d{2})-(\d)", query, re.IGNORECASE)
    if identifier and sum(i * int(n) for i, n in enumerate((identifier[1] + identifier[2])[::-1], 1)) % 10 == int(
        identifier[3]
    ):
        # An existing exact CAS lookup supplies identity without a lexical water
        # count. This exception does not create or choose any CAS mapping.
        return True
    if label and lower_query == lower_label:
        return True
    query_scope, target_scope = _hydration_scope(query), _hydration_scope(label)
    if target_scope == "unknown":
        numeric = {_hydration_scope(value) for value in authority_names} - {None, "unknown"}
        if len(numeric) > 1:
            return False
        if numeric:
            target_scope = numeric.pop()
    if query_scope is None and target_scope is None:
        return True
    return query_scope is not None and query_scope == target_scope


def _policy_target_key(value):
    """Recognize finite legacy namespace spellings, without inferring chemical identity."""
    value = str(value or "").strip().casefold()
    prefix, separator, local = value.partition(":")
    # MediaDive still returns these historical prefixes before source
    # finalization. They must not bypass canonical policy keys (#1155).
    prefix = {"pubchem": "pubchem.compound", "cas-rn": "cas"}.get(prefix, prefix)
    return prefix + separator + local


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
            target = _policy_target_key(row["target_id"])
            label = row["authority_label"]
            if target in labels and labels[target] != label:
                raise ValueError(f"Conflicting authority label for {target}")
            labels[target] = label
            if row["kind"] == "name_pattern":
                pattern = re.compile(row["value"])
                if pattern.search(label):
                    raise ValueError(f"Identity policy rejects its authority label: {target}")
                names.setdefault(target, []).append(pattern)
            elif row["kind"] == "xref" and _policy_target_key(row["value"]) != target:
                xrefs.add(frozenset((target, _policy_target_key(row["value"]))))
            else:
                raise ValueError(f"Invalid ingredient identity policy kind/value: {row!r}")
    return names, xrefs, labels


def ingredient_mapping_allowed(name: str, target: str) -> bool:
    """Reject reviewed ingredient-name/target pairs without banning targets."""
    recognized, scoped_target = ingredient_case_sensitive_name_scope(name)
    if recognized and (scoped_target is None or _policy_target_key(scoped_target) != _policy_target_key(target)):
        return False
    patterns = ingredient_identity_policy()[0].get(_policy_target_key(target), ())
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
    return frozenset((_policy_target_key(subject), _policy_target_key(target))) not in ingredient_identity_policy()[1]


def ingredient_authority_label(target: str) -> str:
    """Return the authority label recorded with a reviewed exclusion."""
    return ingredient_identity_policy()[2].get(_policy_target_key(target), "")
