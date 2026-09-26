"""Audit historical conflict quarantine without adjudicating chemical identities."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

from kg_microbe.utils.chemical_mapping_utils import _iter_sssom_rows
from kg_microbe.utils.sssom_identity_policy import classify_mapping_row


def _hash(path):
    """Fingerprint a streamed input without changing it."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _pair(row):
    """Match opposite identity directions while preserving original row payloads."""
    return tuple(sorted(row[key].strip() for key in ("subject_id", "object_id")))


def _payload(row):
    """Exclude only the added quarantine annotation when comparing original claims."""
    return {key: value for key, value in row.items() if key != "quarantine_reason"}


def _key(row):
    """Compare every original field, including provenance and mapping date."""
    return json.dumps(_payload(row), sort_keys=True, ensure_ascii=False)


def conflicting_claims(path):
    """Use two passes and retain only broader pairs and their exact counterparts."""
    nonidentity = defaultdict(list)
    for row in _iter_sssom_rows(path):
        route, _ = classify_mapping_row(row)
        if route == "broader" or (route == "nonidentity" and row["predicate_id"].strip() == "skos:relatedMatch"):
            nonidentity[_pair(row)].append(row)
    identities = defaultdict(list)
    if nonidentity:
        for row in _iter_sssom_rows(path):
            if _pair(row) in nonidentity and classify_mapping_row(row)[0] == "identity":
                identities[_pair(row)].append(row)
    return {
        pair: {"identity_rows": identities[pair], "nonidentity_rows": nonidentity[pair]} for pair in sorted(identities)
    }


def audit_historical_claims(*, baseline: Path, candidate: Path, quarantine: Path) -> dict:
    """Require complete historical provenance retention and a conflict-free candidate."""
    paths = {
        "baseline": Path(baseline).resolve(),
        "candidate": Path(candidate).resolve(),
        "quarantine": Path(quarantine).resolve(),
    }
    hashes = {name: _hash(path) for name, path in paths.items()}
    conflicts = conflicting_claims(baseline)
    required = Counter(
        _key(row)
        for claims in conflicts.values()
        for kind in ("identity_rows", "nonidentity_rows")
        for row in claims[kind]
    )
    retained, reasons = Counter(), defaultdict(set)
    for row in _iter_sssom_rows(quarantine):
        key = _key(row)
        if key in required:
            reason = row.get("quarantine_reason", "").strip()
            if not reason:
                raise ValueError("Historical conflict quarantine lacks a disposition reason")
            retained[key] += 1
            reasons[key].add(reason)
    missing = required - retained
    remaining = conflicting_claims(candidate)
    if missing:
        raise ValueError(f"Historical conflict quarantine lost {sum(missing.values())} original row(s)")
    if remaining:
        raise ValueError(f"Candidate retains {len(remaining)} contradictory identity/nonidentity pair(s)")
    if any(_hash(path) != hashes[name] for name, path in paths.items()):
        raise ValueError("Audit input changed during historical conflict review")
    return {
        "schema_version": 1,
        "status": "PASS",
        "baseline_conflicting_pairs": len(conflicts),
        "historical_rows_preserved_in_quarantine": sum(required.values()),
        "candidate_conflicting_pairs": 0,
        "input_sha256": hashes,
        "disposition": "historical_provenance_reset_not_scientific_adjudication",
        "promotion_authorized": False,
        "pairs": [
            {
                "endpoints": list(pair),
                **claims,
                "quarantine_reasons": sorted(
                    {reason for rows in claims.values() for row in rows for reason in reasons[_key(row)]}
                ),
            }
            for pair, claims in conflicts.items()
        ],
    }


def main(argv=None):
    """Write a new audit report without editing candidate or production mapping files."""
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("baseline", "candidate", "quarantine", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args(argv)
    report = audit_historical_claims(baseline=args.baseline, candidate=args.candidate, quarantine=args.quarantine)
    with args.output.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(f"Historical conflicts: {report['baseline_conflicting_pairs']}; candidate conflicts: 0")


if __name__ == "__main__":
    main()
