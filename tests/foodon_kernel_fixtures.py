"""Real empty reviewed FOODON contract for unrelated-source dependency fixtures."""

from kg_microbe.utils.foodon_kernel_producer import FoodonKernelQuarantine
from kg_microbe.utils.foodon_kernel_quarantine import AUDIT_FILE


def prepare_empty_foodon_kernel_contract(transform):
    """Consume the reviewed policy and emit an honestly header-only mandatory audit."""
    path = transform.output_dir / AUDIT_FILE
    with path.open("w", encoding="utf-8", newline="") as stream:
        scope = FoodonKernelQuarantine(transform, stream)
        assert not scope.prepared and scope.evidence is None
    transform.record_producer_audit(AUDIT_FILE)
    return scope
