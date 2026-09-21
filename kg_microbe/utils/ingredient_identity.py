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
    patterns = ingredient_identity_policy()[0].get(str(target or "").casefold(), ())
    original = str(name or "")
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
