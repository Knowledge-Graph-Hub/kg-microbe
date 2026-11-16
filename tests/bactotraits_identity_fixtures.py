"""Small synthetic policy inputs for BactoTraits emitter and generic lifecycle tests."""

import csv
import hashlib
import json
from pathlib import Path

from kg_microbe.transform_utils.bactotraits.identity_quarantine import (
    AUDIT_FILE,
    POLICY_ROLE,
    SOURCE_ROLE,
    IdentityQuarantine,
)
from kg_microbe.utils.source_finalization import snapshot_consumed_input

FIXTURES = Path(__file__).parent / "resources/bactotraits_identity"


def fixture_policy(source, *, reviewed=True):
    """Build an explicitly synthetic finite policy, separate from the production decision."""
    with source.open(encoding="ISO-8859-1", newline="") as stream:
        next(stream)
        next(stream)
        row = next(csv.DictReader(stream, delimiter=";"))
    decisions = []
    if reviewed:
        serialized = json.dumps(row, sort_keys=True, indent=2, ensure_ascii=False)
        decisions.append(
            {
                "rule_id": "synthetic-mixed-row",
                "reviewed_source_data_row": 1,
                "bacdive_id": row["Bacdive_ID"],
                "ncbitaxon_id": "NCBITaxon:1123071",
                "full_name": row["Full_name"],
                "culture_collection_codes": row["culture collection codes"],
                "row_sha256": hashlib.sha256(serialized.encode()).hexdigest(),
                "disposition": "quarantine_mixed_strain_row",
                "evidence_urls": ["https://example.invalid/synthetic-identity-witness"],
                "rationale": "Synthetic regression for withholding a previously reviewed mixed row.",
            }
        )
    return {
        "format": "kg-microbe-bactotraits-quarantine/v1",
        "reviewed_source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "decisions": decisions,
    }


def write_fixture_policy(source, destination, *, reviewed=True):
    """Persist a fixture policy whose selected source bytes are explicit."""
    destination.write_text(json.dumps(fixture_policy(source, reviewed=reviewed)), encoding="utf-8")
    return destination


def consume_empty_identity_fixture(transform):
    """Bind an explicit empty review cohort for generic fixture graphs, never bypass requirements."""
    raw = transform.input_base_dir / "bactotraits-identity-fixture.csv"
    raw.write_bytes(FIXTURES.joinpath("source.csv").read_bytes())
    policy = write_fixture_policy(raw, transform.input_base_dir / "identity-fixture-policy.json", reviewed=False)
    with transform.consume_input(POLICY_ROLE, policy) as stream:
        quarantine = IdentityQuarantine(stream.read())
    with snapshot_consumed_input(transform, SOURCE_ROLE, raw, binary=True) as stream:
        quarantine.preflight(stream.read())
    if AUDIT_FILE in type(transform).REQUIRED_AUDIT_FILES:
        with (transform.output_dir / AUDIT_FILE).open("w", encoding="utf-8", newline="") as stream:
            quarantine.write_audit(stream)
        transform.record_producer_audit(AUDIT_FILE)
    return POLICY_ROLE, SOURCE_ROLE
