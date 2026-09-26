#!/usr/bin/env python3
"""
Refresh the vendored list of deprecated METPO CURIEs.

The guard in ``tests/test_no_deprecated_metpo_terms.py`` needs to know which
terms the pinned release has retired. Reading ``data/raw/metpo.json`` directly
means the check skips wherever that file is absent — which is CI, because
``/data/raw/**`` is gitignored, and is where the check most needs to run (#924).

So the set is vendored under ``tests/resources`` and refreshed by this script
whenever ``METPO_VERSION`` moves.

Usage:
    poetry run python scripts/refresh_deprecated_metpo_curies.py
"""

import json
import re
import sys
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEST = REPO_ROOT / "tests" / "resources" / "metpo_deprecated_curies.txt"
RELEASE_JSON = "https://raw.githubusercontent.com/berkeleybop/metpo/refs/tags/{release}/metpo.json"
_TERM_IRI = re.compile(r"https://w3id\.org/metpo/(\d+)$")


def main() -> int:
    """Fetch the pinned release and rewrite the vendored list."""
    sys.path.insert(0, str(REPO_ROOT))
    from kg_microbe.transform_utils.constants import METPO_VERSION

    url = RELEASE_JSON.format(release=METPO_VERSION)
    with urllib.request.urlopen(url, timeout=60) as response:  # noqa: S310
        payload = json.loads(response.read().decode("utf-8"))
    curies = sorted(
        "METPO:" + match.group(1)
        for node in payload["graphs"][0].get("nodes", [])
        if (match := _TERM_IRI.match(node.get("id", ""))) and (node.get("meta") or {}).get("deprecated")
    )
    DEST.write_text(
        "# METPO CURIEs deprecated in the pinned release. Vendored so the guard in\n"
        "# tests/test_no_deprecated_metpo_terms.py runs in CI, where data/raw is absent (#924).\n"
        "# Regenerate with: poetry run python scripts/refresh_deprecated_metpo_curies.py\n"
        f"# release: {METPO_VERSION}\n" + "\n".join(curies) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {len(curies):,} deprecated CURIEs for METPO {METPO_VERSION} to {DEST}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
