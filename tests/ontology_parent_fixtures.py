"""Real empty parent-disposition input/audit for unrelated dependency fixtures."""

from kg_microbe.utils.ontology_parent_quarantine import AUDIT_FILE, POLICY_ROLE, OntologyParentQuarantine


def prepare_empty_parent_contract(transform):
    """Consume the actual policy and preserve truthful empty scope, without a fake producer run."""
    with (transform.output_dir / AUDIT_FILE).open("w", encoding="utf-8", newline="") as stream:
        authority = OntologyParentQuarantine(transform, stream)
        assert authority.member_names() == ()
        # Other independent producer policies may not have been read yet. The
        # caller's normal completion/finalization verifies the complete source.
        authority.verify_bindings()
    transform.record_producer_audit(AUDIT_FILE)
    return (POLICY_ROLE,)
