"""Scope KGX conversion/merge prefix contexts to the pinned local model, including spawned workers."""

from contextlib import contextmanager
from threading import RLock

_CONTEXT_LOCK = RLock()
_ABSENT = object()
_CONTEXT_NAMES = ("biolink", "monarch_context", "obo_context")
_USERS = 0
_PREVIOUS = {}
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
    """Seed all real KGX prefix readers, restoring exact prior entries after nested users finish."""
    from kgx.config import jsonld_context_map

    global _USERS, _PREVIOUS, _ACTIVE
    context = _pinned_prefix_map()
    # Never hold a process-global lock over KGX's pool lifecycle: thread-pool
    # callers and forked workers must be able to enter their own parser scope.
    with _CONTEXT_LOCK:
        if _USERS == 0:
            _PREVIOUS = {name: jsonld_context_map.get(name, _ABSENT) for name in _CONTEXT_NAMES}
            _ACTIVE = context
            # KGX contract/expand eagerly load both fallback contexts even
            # when an explicit prefix map already resolves the identifier.
            # All three use the same selected schema/default-map precedence.
            for name in _CONTEXT_NAMES:
                jsonld_context_map[name] = context
        elif context != _ACTIVE:
            raise ValueError("Concurrent KGX prefix contexts use different pinned namespaces")
        _USERS += 1
    try:
        yield
    finally:
        with _CONTEXT_LOCK:
            _USERS -= 1
            if _USERS == 0:
                for name, previous in _PREVIOUS.items():
                    if previous is _ABSENT:
                        jsonld_context_map.pop(name, None)
                    else:
                        jsonld_context_map[name] = previous
                _PREVIOUS, _ACTIVE = {}, None
