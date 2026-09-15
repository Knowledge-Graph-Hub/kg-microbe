"""Scope KGX's TSV prefix context to the pinned local model, including spawned merge workers."""

from contextlib import contextmanager
from threading import RLock

_CONTEXT_LOCK = RLock()
_ABSENT = object()
_USERS = 0
_PREVIOUS = _ABSENT
_ACTIVE = None


def _pinned_prefix_map():
    """Resolve the model's bundled default maps and explicit prefix overrides without remote contexts."""
    from kg_microbe.utils.biolink_model import prepare_kgx

    prepare_kgx()
    from bmt import Toolkit

    # The explicit schema prefixes alone omit GO, CHEBI, NCBITaxon and RDF.
    # SchemaView follows the pinned default_curi_maps using prefixcommons'
    # installed local registry, then applies the schema's own overrides. In
    # particular, the pinned biolink URI wins; no older project-map overlay.
    view = Toolkit().view
    context = {str(prefix): str(uri) for prefix, uri in view.namespaces().items() if prefix and uri}
    if not context.get("biolink"):
        raise ValueError("Pinned Biolink model has no usable biolink namespace")
    return context


@contextmanager
def local_prefix_context():
    """Temporarily seed the real KGX reader, restoring its exact prior entry after nested users finish."""
    from kgx.config import jsonld_context_map

    global _USERS, _PREVIOUS, _ACTIVE
    context = _pinned_prefix_map()
    # Never hold a process-global lock over KGX's pool lifecycle: thread-pool
    # callers and forked workers must be able to enter their own parser scope.
    with _CONTEXT_LOCK:
        if _USERS == 0:
            _PREVIOUS = jsonld_context_map.get("biolink", _ABSENT)
            _ACTIVE = context
            jsonld_context_map["biolink"] = context
        elif context != _ACTIVE:
            raise ValueError("Concurrent merge prefix contexts use different pinned namespaces")
        _USERS += 1
    try:
        yield
    finally:
        with _CONTEXT_LOCK:
            _USERS -= 1
            if _USERS == 0:
                if _PREVIOUS is _ABSENT:
                    jsonld_context_map.pop("biolink", None)
                else:
                    jsonld_context_map["biolink"] = _PREVIOUS
                _PREVIOUS, _ACTIVE = _ABSENT, None
