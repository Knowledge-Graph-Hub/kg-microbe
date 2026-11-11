"""Normalize only reviewed PREGO habitat edge orientations into term/taxon pairs."""

HABITAT_PREFIXES = ("ENVO:", "BTO:", "FOODON:")
TAXON_PREFIX = "NCBITaxon:"


def habitat_pair(subject, predicate, obj, prefixes=HABITAT_PREFIXES):
    """Return (habitat, taxon) for exact legacy/current shapes; exclude all other assertions."""
    if predicate == "biolink:location_of":
        term, taxon = subject, obj
    elif predicate == "biolink:located_in":
        term, taxon = obj, subject
    else:
        return None
    if not any(term.startswith(prefix) and len(term) > len(prefix) for prefix in prefixes):
        return None
    if not taxon.startswith(TAXON_PREFIX) or len(taxon) == len(TAXON_PREFIX):
        return None
    return term, taxon
