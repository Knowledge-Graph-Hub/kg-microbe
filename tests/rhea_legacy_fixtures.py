"""Explicit synthetic no-history policy for small native Rhea fixtures, never production pins."""

import io
import json

from kg_microbe.transform_utils.rhea_mappings.legacy_xrefs import read_legacy_policy


def empty_legacy_policy(release_policy):
    """Return a validated zero-history contract for a genuinely different hermetic RDF snapshot."""
    document = {
        "schema_version": 1,
        "expected_count": 0,
        "scope_note": "Synthetic fixture has no historical cross-reference cohort; no production exclusions claimed.",
        "historical_snapshot": None,
        "selected_snapshot": {
            "snapshot_id": release_policy["snapshot_id"],
            "rdf": {key: release_policy["files"]["rhea.rdf.gz"][key] for key in ("bytes", "sha256")},
        },
        "legacy_sources": {},
        "exclusions": [],
        "preserved_directional_go_annotations": [],
    }
    # Validation is real even for fixture setup: a production identity may not
    # acquire an empty history merely because the caller used this convenience.
    read_legacy_policy(io.StringIO(json.dumps(document)))
    return document
