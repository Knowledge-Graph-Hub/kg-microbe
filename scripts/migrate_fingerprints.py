#!/usr/bin/env python3
"""
Rewrite scheme-2 ``source_fingerprint.json`` markers as scheme 3 where they still hold.

Scheme 3 (#1002, #983) folds shared first-party code into every transform's
fingerprint and hashes by repo-relative name. Bumping the scheme makes every
older marker unreadable, which would send a freshly rebuilt tree back to
timestamp comparison until each source ran again. A scheme-2 marker whose
digests still match its inputs vouches for the same output under scheme 3,
so it is rewritten; a stale one is left for a real rerun.

Usage: ``poetry run python scripts/migrate_fingerprints.py``
"""

import inspect
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

#: Sources whose output lives in a directory not named after the source.
OUTPUT_DIR_ALIASES = {"prego": ("prego_habitat", "prego")}


def main() -> int:
    """
    Migrate every registered source's marker and report what happened.

    :return: Process exit code.
    """
    from kg_microbe.transform import DATA_SOURCES
    from kg_microbe.utils.transform_fingerprint import migrate_markers

    transformed = REPO_ROOT / "data" / "transformed"
    sources = []
    for name, lazy in DATA_SOURCES.items():
        try:
            cls = lazy.transform_class
        except AttributeError:
            continue  # optional dependency missing; nothing to migrate for it
        candidates = OUTPUT_DIR_ALIASES.get(name, (name,))
        output_dir = next((c for c in candidates if (transformed / c).is_dir()), candidates[-1])
        sources.append(
            {
                "name": name,
                "output_dir": output_dir,
                "code_dir": Path(inspect.getsourcefile(cls)).parent,
                "data_inputs": tuple(getattr(cls, "DATA_INPUTS", ()) or ()),
                "transform_inputs": tuple(getattr(cls, "TRANSFORM_INPUTS", ()) or ()),
            }
        )
    outcome = migrate_markers(transformed, REPO_ROOT, sources)
    for name in sorted(outcome):
        print(f"{name:28s} {outcome[name]}")
    migrated = sum(1 for v in outcome.values() if v == "migrated")
    print(f"migrated {migrated} of {len(outcome)} markers")
    return 0


if __name__ == "__main__":
    sys.exit(main())
