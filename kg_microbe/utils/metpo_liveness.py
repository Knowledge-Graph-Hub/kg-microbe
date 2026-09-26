"""
Check that the METPO terms this repo asserts still exist upstream.

A CURIE hardcoded in a constant keeps being emitted long after the ontology
stops declaring it: nothing errors, nothing looks different, and the graph
quietly asserts a term that no longer means anything. That is how
``METPO:2000511`` came to carry 706,765 shipped edges after being obsoleted, and
``METPO:1001000`` to sit in 503 node categories (#909).

The pinned ``metpo.json`` is the authority. It is pinned (#900), so this check
answers "does the release we build against still declare this", not "does some
newer release", which is the question that matters for what we ship.
"""

import json
import re
from pathlib import Path
from typing import Dict, Optional, Set

from kg_microbe.transform_utils.constants import RAW_DATA_DIR

_TERM_IRI = re.compile(r"https://w3id\.org/metpo/(\d+)$")

#: METPO CURIEs this repo still emits despite upstream deprecation, each with the
#: issue that tracks removing it. An entry here is a debt, not an exemption: it
#: says someone looked, found no live replacement, and recorded why. Adding one
#: without an issue defeats the check.
KNOWN_DEPRECATED: Dict[str, str] = {
    # Organism -> assay. Upstream obsoleted it with IAO:0000226 and declared no
    # successor; no live METPO property covers organism-to-assay, and biolink's
    # nearest match ("has procedure") is a node-property slot, not an association
    # predicate. Tracked by #909, pending the upstream modelling in metpo#461.
    "METPO:2000511": "#909",
    # Both are assigned as predicates in metatraits' growth-observation parsers.
    # Neither produces an edge on the current data -- the patterns they key off do
    # not fire -- but they are live code, not comments, and would emit an obsolete
    # predicate if they did. Same root cause and same blocker as METPO:2000511.
    "METPO:2000054": "#909",
    "METPO:2000508": "#909",
}


def metpo_json_path() -> Path:
    """
    Return the pinned metpo.json this repo builds against.

    :return: Path to the downloaded ontology, which may not exist.
    """
    return Path(RAW_DATA_DIR) / "metpo.json"


def deprecated_metpo_terms(path: Optional[Path] = None) -> Set[str]:
    """
    Return every METPO CURIE the pinned release marks deprecated.

    :param path: Override for the ontology path, for tests.
    :return: Set of CURIEs; empty when the ontology is not available locally.
    """
    source = path or metpo_json_path()
    if not source.is_file():
        return set()
    payload = json.loads(source.read_text(encoding="utf-8"))
    graphs = payload.get("graphs") or [{}]
    deprecated = set()
    for node in graphs[0].get("nodes", []):
        match = _TERM_IRI.match(node.get("id", ""))
        if match and (node.get("meta") or {}).get("deprecated"):
            deprecated.add("METPO:" + match.group(1))
    return deprecated
