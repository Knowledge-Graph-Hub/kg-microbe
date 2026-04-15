#!/usr/bin/env python3
"""
Fix Tier 1 contamination in unified_chemical_mappings.tsv.gz.

Background
----------
When special_chemical_mappings.tsv had wrong CHEBI IDs (e.g. propane-1,2-diol
mapped to CHEBI:16240 = hydrogen peroxide), building unified_chemical_mappings
added those chemical names as synonyms to the wrong CHEBI rows.  A prior fix
session corrected the 16 rows that had genuinely wrong synonyms and tagged
them `metatraits_special_chemicals[corrected_2026-04-08]`.

The 13 remaining rows tagged `metatraits_special_chemicals[manual_2026-04-07]`
had *correct* CHEBI IDs all along — their synonyms are legitimate.  This
script marks them as reviewed by updating the source tag to
`metatraits_special_chemicals[corrected_2026-04-08]`.

Verification: all 29 metatraits_special_chemicals rows end up tagged
`corrected_2026-04-08` when done.
"""

import gzip
import shutil
import tempfile
from pathlib import Path

MAPPINGS_FILE = Path(__file__).parent / "unified_chemical_mappings.tsv.gz"
OLD_TAG = "metatraits_special_chemicals[manual_2026-04-07]"
NEW_TAG = "metatraits_special_chemicals[corrected_2026-04-08]"


def main() -> None:
    """Run the fix."""
    rows_updated = 0
    rows_total = 0

    tmp = tempfile.NamedTemporaryFile(suffix=".tsv.gz", delete=False)
    tmp_path = Path(tmp.name)

    with (
        gzip.open(MAPPINGS_FILE, "rt") as fin,
        gzip.open(tmp_path, "wt") as fout,
    ):
        # Pass header through unchanged
        header = fin.readline()
        fout.write(header)
        col_names = header.rstrip("\n").split("\t")
        sources_idx = col_names.index("sources")

        for line in fin:
            rows_total += 1
            if OLD_TAG in line:
                line = line.replace(OLD_TAG, NEW_TAG)
                rows_updated += 1
            fout.write(line)

    # Atomic replace
    shutil.move(tmp_path, MAPPINGS_FILE)
    print(f"Rows updated: {rows_updated} / {rows_total}")
    print(f"  {OLD_TAG!r} → {NEW_TAG!r}")

    # Verify
    remaining = 0
    total_special = 0
    with gzip.open(MAPPINGS_FILE, "rt") as f:
        f.readline()  # skip header
        for line in f:
            if "metatraits_special_chemicals" in line:
                total_special += 1
                if "manual_2026-04-07" in line:
                    remaining += 1
    print(f"\nPost-fix metatraits_special_chemicals rows: {total_special}")
    print(f"  Still manual_2026-04-07: {remaining}")
    if remaining == 0:
        print("  ✅ All metatraits_special_chemicals rows are now corrected_2026-04-08")
    else:
        print("  ⚠️  Some rows still need review")


if __name__ == "__main__":
    main()
