"""
Prospective, opt-in local native85 acceptance; do not run while the worktree is frozen.

This is bounded method/query conservation, not a fresh full producer or archive
review. The saved native72 parent-row ledger remains separately identified.
It does not retrospectively claim that old BacDive production consumed this DB.
"""

import gzip
import hashlib
import json
import os
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

import pytest
from oaklib.implementations.sqldb.sql_implementation import SqlImplementation
from oaklib.resource import OntologyResource
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from kg_microbe.merge_utils.source_admission import SourceAdmission
from kg_microbe.transform_utils.bacdive.ancestry_authority import FreshAncestryAuthority
from kg_microbe.transform_utils.bacdive.emission import resolve_deposit_parents
from kg_microbe.transform_utils.constants import RDFS_SUBCLASS_OF
from tests.native85_evidence import load_native85_cohort

COHORT_SHA = "5cea53ab90fde7f2f34d5a654a5fd7322fe623980363f19e594ac680d73c05bc"
NATIVE_PROOF_SHA = "f8c80fc66be4d4be93c70c49466981ee088e96653fd5ae3eb791849d18ee2503"
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.environ.get("BACDIVE_ANCESTRY_NATIVE_AUTHORITY"),
        reason="Requires separately authorized local native DB method replay, not a default unit-test read",
    ),
]


def _canonical(value):
    """Compare complete saved row witnesses without relying on dict or callback ordering."""
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":"))


def test_all85_old_and_fresh_choices_and_separate_native72_row_proof():
    """Every saved collapse is conserved under the same real OAK query through a fresh private handle."""
    admission = SourceAdmission()
    payload = load_native85_cohort(admission, COHORT_SHA)
    assert hashlib.sha256(payload).hexdigest() == COHORT_SHA
    evidence = json.loads(payload)
    assert evidence["deposit_count"] == len(evidence["cohort"]) == 85
    assert evidence["steps_joined"] == len(evidence["native_step_witnesses"]) == 72
    proof_path = Path(evidence["native_proof"]["path"])
    assert admission.capture(proof_path)["sha256"] == NATIVE_PROOF_SHA
    requested = {(item["row"]["subject"], item["row"]["object"]): item for item in evidence["native_step_witnesses"]}
    found = Counter()
    with gzip.open(proof_path, "rt") as stream:
        for line in stream:
            item = json.loads(line)
            key = item["row"]["subject"], item["row"]["object"]
            if key in requested:
                assert _canonical(item) == _canonical(requested[key])
                found[key] += 1
    assert found == Counter({key: 1 for key in requested})
    claims, expected = {}, {}
    for item in evidence["cohort"]:
        parents = defaultdict(list)
        for record_id, _token_index, _literal, target, _support, _relation in item["claims"]:
            parents[target].append(record_id)
        assert len(parents) > 1 and item["subject"] not in claims
        claims[item["subject"]] = dict(parents)
        expected[item["subject"]] = item["selected_parent"]
        for source, steps in item["paths"].items():
            current = source
            for child, parent in steps:
                assert current == child and (child, parent) in requested
                current = parent
            assert current == item["selected_parent"]

    path = Path(os.environ["BACDIVE_ANCESTRY_NATIVE_AUTHORITY"]).absolute()
    original_identity = admission.capture(path)
    for suffix in ("-wal", "-shm", "-journal"):
        assert not Path(str(path) + suffix).exists()
        admission.capture(Path(str(path) + suffix), optional=True)

    def read_only_connection():
        """Never open the native acceptance input in a writable SQLite mode."""
        return sqlite3.connect(path.resolve().as_uri() + "?mode=ro&immutable=1", uri=True)

    original = SqlImplementation(
        resource=OntologyResource(slug=str(path)),
        engine=create_engine("sqlite:///" + str(path), creator=read_only_connection, poolclass=StaticPool),
    )
    old_demand, new_demand, old_cache, new_cache = [], [], {}, {}

    def old(identifier):
        """Preserve the previous proper-ancestor/cache semantics on a newly bound read-only test adapter."""
        old_demand.append(identifier)
        if identifier not in old_cache:
            old_cache[identifier] = frozenset(original.ancestors([identifier], predicates=[RDFS_SUBCLASS_OF])) - {
                identifier
            }
        return old_cache[identifier]

    try:
        prior = resolve_deposit_parents(claims, ancestors_of=old, ancestry_failed=lambda _id: False)
        with FreshAncestryAuthority.from_resolved_adapter(original, admission=admission) as fresh:

            def new(identifier):
                """Observe actual demand and query at most once per ID exactly like the producer guard."""
                new_demand.append(identifier)
                if identifier not in new_cache:
                    new_cache[identifier] = fresh.ancestors(identifier)
                return new_cache[identifier]

            current = resolve_deposit_parents(claims, ancestors_of=new, ancestry_failed=lambda _id: False)
            receipt = fresh.finish()
        assert current == prior
        assert dict(current[0]) == expected
        assert len(current[1]) == 85
        assert old_cache == new_cache and Counter(old_demand) == Counter(new_demand)
        assert Counter(row["subject"] for row in receipt["computed_queries"]) == Counter(
            {identifier: 1 for identifier in new_cache}
        )
        assert receipt["authority"]["identity"] == original_identity
        assert receipt["native_version_statements"]
        assert receipt["asserted_native_parent_rows"] is False
        admission.verify()
    finally:
        if original._session is not None:
            original._session.close()
        original.engine.dispose()
