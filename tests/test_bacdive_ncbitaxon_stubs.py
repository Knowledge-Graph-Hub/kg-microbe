"""Trusted NCBITaxon isolation-source targets must have a typed node (#790)."""

import csv
from pathlib import Path
from unittest import TestCase

from kg_microbe.transform_utils.constants import NCBI_CATEGORY
from kg_microbe.utils.isolation_source_mapping_utils import load_isolation_source_mappings

REPO_ROOT = Path(__file__).resolve().parents[1]
MAPPING_FILE = REPO_ROOT / "mappings" / "isolation_source_to_ontology.tsv"
NCBITAXON_NODES = REPO_ROOT / "data" / "transformed" / "ontologies" / "ncbitaxon_nodes.tsv"


def _trimmed_taxon_ids():
    """
    Ids present in the trimmed NCBITaxon extract.

    :return: Set of CURIEs, empty when the extract has not been built.
    """
    if not NCBITAXON_NODES.is_file():
        return set()
    ids = set()
    with NCBITAXON_NODES.open(encoding="utf-8") as handle:
        handle.readline()
        for line in handle:
            curie = line.split("\t", 1)[0]
            if curie.startswith("NCBITaxon:"):
                ids.add(curie)
    return ids


def _output_predates(output: Path, tracked_input: Path) -> bool:
    """
    Report whether an output was built before its tracked input last changed.

    Uses the input's git commit time, not its mtime: `git checkout` rewrites
    mtimes without changing content (#797).

    :param output: Build artifact to test.
    :param tracked_input: Tracked source file it depends on.
    :return: True when the output is older, or when the comparison is impossible.
    """
    import subprocess

    try:
        out = subprocess.run(  # noqa: S603 - fixed argv, paths built by this module
            ["/usr/bin/git", "log", "-1", "--format=%ct", "--", str(tracked_input)],  # noqa: S607
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return False
    if not out:
        return False
    return output.stat().st_mtime < int(out)


class NcbiTaxonStubTest(TestCase):
    """The trim drops host taxa the isolation-source mapping still points at."""

    def test_the_category_used_for_stubs_is_organism_taxon(self):
        """
        A taxon typed as an ontology class fails Biolink's domain check.

        `biolink:location_of` expects a biological entity; `OntologyClass` — the
        category used for the mesh/NCIT/BTO stubs — is not one. These are taxa,
        so they get the taxon category.
        """
        self.assertEqual(NCBI_CATEGORY, "biolink:OrganismTaxon")

    def test_some_trusted_targets_really_are_missing_from_the_trim(self):
        """
        Pin the premise, so the fix cannot outlive its reason.

        If the trim ever starts carrying these, this test fails and the stub
        path can be reconsidered rather than left as dead code nobody dares
        remove.
        """
        trimmed = _trimmed_taxon_ids()
        if not trimmed:
            self.skipTest("NCBITaxon extract not built")
        trusted = {v[0] for v in load_isolation_source_mappings(MAPPING_FILE).values() if v[0].startswith("NCBITaxon:")}
        self.assertTrue(trusted, "expected some trusted NCBITaxon targets in the mapping")
        missing = trusted - trimmed
        self.assertTrue(
            missing,
            "no trusted NCBITaxon target is missing from the trim — if this is now true, "
            "the stub path in bacdive.py is dead and should be removed",
        )

    def test_no_trusted_ncbitaxon_target_is_left_without_a_node(self):
        """
        Assert every trusted target is either in the trim or stubbed by bacdive.

        Before the fix, 8 of 22 were in neither and reached the merged graph as
        `biolink:NamedThing` with no label. They were invisible to the
        dangling-edge check, because KGX materialises a row for any referenced
        endpoint — the signal is the missing category, not a missing node.
        """
        trimmed = _trimmed_taxon_ids()
        bacdive_nodes = REPO_ROOT / "data" / "transformed" / "bacdive" / "nodes.tsv"
        if not trimmed or not bacdive_nodes.is_file():
            self.skipTest("transform outputs not built")
        # The assertion is about the *output*, so it cannot pass until the
        # transform has run since both the mapping and the emit code last
        # changed. Skipping with a reason beats xfail: this re-arms itself after
        # the next rebuild instead of needing someone to remember to flip it
        # back (#812).
        #
        # Both inputs matter, and for different reasons. The mapping decides
        # *which* taxa are referenced; the transform decides whether a stub is
        # written for the ones the trim dropped. A run that predates either one
        # cannot demonstrate the invariant.
        transform_src = REPO_ROOT / "kg_microbe" / "transform_utils" / "bacdive" / "bacdive.py"
        if _output_predates(bacdive_nodes, MAPPING_FILE):
            self.skipTest(
                "data/transformed/bacdive/nodes.tsv predates the current "
                "isolation-source mapping; re-run `poetry run kg transform -s bacdive`"
            )
        if bacdive_nodes.stat().st_mtime < transform_src.stat().st_mtime:
            self.skipTest(
                "data/transformed/bacdive/nodes.tsv predates the current bacdive.py; "
                "re-run `poetry run kg transform -s bacdive`"
            )

        emitted = set()
        with bacdive_nodes.open(encoding="utf-8") as handle:
            for row in csv.reader(handle, delimiter="\t"):
                if row and row[0].startswith("NCBITaxon:"):
                    emitted.add(row[0])

        trusted = {v[0] for v in load_isolation_source_mappings(MAPPING_FILE).values() if v[0].startswith("NCBITaxon:")}
        orphaned = sorted(trusted - trimmed - emitted)
        self.assertEqual(
            orphaned,
            [],
            f"trusted NCBITaxon targets with no node from either source: {orphaned}. "
            "Re-run `poetry run kg transform -s bacdive` if this list is stale.",
        )
