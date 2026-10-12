"""Real pinned Rhea reads for inert graph fixtures, not native-emitter acceptance."""

import gzip
import hashlib
import json
import sqlite3
from pathlib import Path

from kg_microbe.transform_utils.rhea_mappings.label_inputs import (
    LABEL_DATABASES,
    REQUIRED_LABEL_INPUTS,
    external_label_lookup,
)
from kg_microbe.transform_utils.rhea_mappings.legacy_xrefs import (
    AUDIT_FILE as LEGACY_AUDIT_FILE,
)
from kg_microbe.transform_utils.rhea_mappings.legacy_xrefs import (
    AUDIT_HEADER as LEGACY_AUDIT_HEADER,
)
from kg_microbe.transform_utils.rhea_mappings.legacy_xrefs import (
    REQUIRED_INPUTS as LEGACY_INPUTS,
)
from kg_microbe.transform_utils.rhea_mappings.legacy_xrefs import (
    load_legacy_xref_audit,
)
from kg_microbe.transform_utils.rhea_mappings.native_inputs import REQUIRED_INPUTS, load_pinned_inputs
from kg_microbe.transform_utils.rhea_mappings.reaction_families import RHEA_RDF_BASE
from kg_microbe.transform_utils.rhea_mappings.rhea_mappings import REACTION_AUDIT
from kg_microbe.utils.tsv_io import tsv_dict_writer
from tests.rhea_legacy_fixtures import empty_legacy_policy

FIXTURE = Path(__file__).parent / "resources" / "rhea" / "native-small.rdf"
LABEL_FIXTURE = FIXTURE.with_name("external-labels.json")


def stage_rhea_label_databases(raw_dir):
    """Create exact, minimal prepared label DBs only in the caller's isolated fixture root."""
    labels = json.loads(LABEL_FIXTURE.read_text())
    raw_dir = Path(raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)
    for filename, _, ontology in LABEL_DATABASES.values():
        path = raw_dir / filename
        if path.exists():
            continue  # Existing test authorities belong to the surrounding fixture.
        with sqlite3.connect(path) as connection:
            connection.execute("CREATE TABLE statements (subject TEXT, predicate TEXT, object TEXT, value TEXT)")
            connection.execute("CREATE INDEX statements_spv ON statements (subject, predicate, value)")
            connection.execute(
                "INSERT INTO statements VALUES (?, 'rdf:type', 'owl:Ontology', NULL)", (f"obo:{ontology}.owl",)
            )
            connection.executemany("INSERT INTO statements VALUES (?, 'rdfs:label', NULL, ?)", labels[ontology].items())


def _stage(path, payload):
    """Never silently overwrite an existing fixture input with different bytes."""
    if path.exists():
        assert path.read_bytes() == payload, f"Changed Rhea fixture input: {path}"
    else:
        path.write_bytes(payload)


def prepare_rhea_native_inputs(transform):
    """Bind a genuine tiny native cohort while keeping generic graph rows explicitly unrelated."""
    raw = transform.input_base_dir / "rhea"
    raw.mkdir(parents=True, exist_ok=True)
    payloads = {
        "rhea-directions.tsv": b"RHEA_ID_MASTER\tRHEA_ID_LR\tRHEA_ID_RL\tRHEA_ID_BI\n100\t101\t102\t103\n",
        "rhea.rdf.gz": gzip.compress(FIXTURE.read_bytes(), mtime=0),
    }
    for name, payload in payloads.items():
        _stage(raw / name, payload)
    policy = {
        "schema_version": 2,
        "snapshot_id": "hermetic-merge-admission-inputs",
        "archive": {
            "url": "https://example.org/rhea/fixture.tar.bz2",
            "members": {
                "rhea-directions.tsv": "fixture/tsv/rhea-directions.tsv",
                "rhea.rdf.gz": "fixture/rdf/rhea.rdf.gz",
            },
        },
        "files": {
            name: {"sha256": hashlib.sha256(payload).hexdigest(), "bytes": len(payload)}
            for name, payload in payloads.items()
        },
    }
    policy_path = raw / "fixture_release.json"
    _stage(policy_path, (json.dumps(policy, sort_keys=True) + "\n").encode("utf-8"))
    actual_policy, families, native, cohort = load_pinned_inputs(transform, policy_path=policy_path)
    assert actual_policy == policy
    assert cohort == {
        "families": 1,
        "members": 4,
        "family_status_counts": {"Approved": 1, "Preliminary": 0},
        "obsolete_ids": (),
    }
    assert type(transform).REQUIRED_AUDIT_FILES == (REACTION_AUDIT, LEGACY_AUDIT_FILE)
    legacy_path = raw / "fixture_legacy_policy.json"
    _stage(legacy_path, (json.dumps(empty_legacy_policy(policy), sort_keys=True) + "\n").encode("utf-8"))
    legacy_rows = load_legacy_xref_audit(transform, policy, native, policy_path=legacy_path)
    assert legacy_rows == ()  # No historical cohort is claimed for this genuinely different tiny input.
    with (transform.output_dir / LEGACY_AUDIT_FILE).open("w", encoding="utf-8", newline="") as stream:
        writer = tsv_dict_writer(stream, LEGACY_AUDIT_HEADER)
        writer.writeheader()
    transform.record_producer_audit(LEGACY_AUDIT_FILE)
    with (transform.output_dir / REACTION_AUDIT).open("w", encoding="utf-8", newline="") as stream:
        writer = tsv_dict_writer(
            stream, ("reaction_id", "master_id", "direction", "native_status", "disposition", "snapshot_id")
        )
        writer.writeheader()
        for family in families:
            for identifier, direction in family.members:
                writer.writerow(
                    {
                        "reaction_id": identifier,
                        "master_id": family.master,
                        "direction": direction,
                        "native_status": native.reactions[identifier][RHEA_RDF_BASE + "status"][0].removeprefix(
                            RHEA_RDF_BASE
                        ),
                        # These rows audit fixture inputs, not emitted reactions:
                        # the generic merge fixtures contain fixture:1/fixture:2.
                        "disposition": "fixture_validated_input_only",
                        "snapshot_id": policy["snapshot_id"],
                    }
                )
    transform.record_producer_audit(REACTION_AUDIT)
    stage_rhea_label_databases(transform.input_base_dir)
    with external_label_lookup(transform):
        pass  # Generic graph fixtures consume label authorities, not native reaction rows.
    return (*REQUIRED_INPUTS, *REQUIRED_LABEL_INPUTS, *LEGACY_INPUTS)
