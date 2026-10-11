"""Real zero-cohort native-RO contracts for inert dependency-chain fixtures."""

from kg_microbe.utils.native_ro_retention import AUDIT_FILE, NativeROPredicateRetention
from tests.foodon_kernel_fixtures import prepare_empty_foodon_kernel_contract
from tests.ontology_parent_fixtures import prepare_empty_parent_contract


def prepare_empty_native_ro_contract(transform):
    """Exercise the real policy reader and mandatory empty audit for a fixture with no RO assertions."""
    prepare_empty_foodon_kernel_contract(transform)
    prepare_empty_parent_contract(transform)
    from tests.upa_route_fixtures import prepare_empty_upa_route_contract

    prepare_empty_upa_route_contract(transform)
    with (transform.output_dir / AUDIT_FILE).open("w", encoding="utf-8", newline="") as stream:
        authority = NativeROPredicateRetention(transform, stream)
        authority.verify_complete()
    transform.record_producer_audit(AUDIT_FILE)
    return (
        "ontology_native_relation_policy",
        "ontology_foodon_kernel_policy",
        "ontology_parent_disposition_policy",
        "upa_route_policy",
    )
