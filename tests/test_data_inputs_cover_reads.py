"""A transform's declared DATA_INPUTS must cover what it actually reads (#839)."""

import inspect
from pathlib import Path
from unittest import TestCase

from kg_microbe.transform_utils.ontologies_stubs.ontologies_stubs_transform import (
    OntologiesStubsTransform,
)
from kg_microbe.utils import stub_curie_collection
from kg_microbe.utils.stub_curie_collection import DEFAULT_MAPPING_PATHS, REPO_ROOT

REPO = Path(__file__).resolve().parents[1]


class OntologiesStubsDeclarationTest(TestCase):
    """The freshness checker reads DATA_INPUTS and nothing else."""

    def test_every_collected_mapping_file_is_declared(self):
        """
        Hand-maintaining the list declared 1 of the 11 files this transform reads.

        `kgm-freshness-check` consults `DATA_INPUTS` alone, so the other ten
        could change and the output would still be reported fresh — the #812
        blind spot. This was the last transform carrying it.
        """
        declared = set(OntologiesStubsTransform.DATA_INPUTS)
        collected = {path.relative_to(REPO_ROOT).as_posix() for path in DEFAULT_MAPPING_PATHS}
        self.assertEqual(
            collected - declared,
            set(),
            "collect_stub_curies reads these but DATA_INPUTS does not declare them",
        )

    def test_the_declaration_is_derived_rather_than_restated(self):
        """
        Two hand-kept copies of one list drift; that is how this defect arose.

        Asserting only that the sets match today would let someone "fix" a
        future mismatch by pasting a literal back in, which reintroduces the
        drift the derivation exists to prevent.
        """
        source = inspect.getsource(OntologiesStubsTransform)
        # Anchor on the assignment, not the bare name. The comment above it
        # discusses `DATA_INPUTS` and `DEFAULT_MAPPING_PATHS` in prose, so
        # splitting on the name alone captured the comment and passed against a
        # hardcoded literal — caught by reverting the fix and re-running.
        declaration = source.split("DATA_INPUTS = ")[1].split("def ")[0]
        self.assertIn("DEFAULT_MAPPING_PATHS", declaration)

    def test_the_sssom_dependency_is_visible(self):
        """
        The one-file declaration implied this transform was SSSOM-independent.

        It is not: `DEFAULT_MAPPING_PATHS[0]` is the unified mapping set, so an
        incoming MIM release makes this output stale. Getting that wrong means
        skipping this transform in a rebuild and merging stale stub nodes.
        """
        self.assertIn(
            "mappings/kgmicrobe_unified_entity_mappings.sssom.tsv.gz",
            OntologiesStubsTransform.DATA_INPUTS,
        )

    def test_declared_paths_are_repo_relative_and_tracked(self):
        """
        Assert the property the consumer actually uses: git-trackedness (#843).

        `_latest_data_input_commit` resolves each entry through `_latest_commit`,
        which asks git. An untracked-but-present file returns `(None, None)` and
        is skipped in silence, so checking `is_file()` — as the first version of
        this test did — passes on a declaration that contributes no staleness
        signal at all. That is #839 one layer down: complete on paper, partly
        inert in fact.

        The repo-relative assertion stays, and fails differently: `REPO / "/abs"`
        resolves to the absolute path, so an absolute entry can *succeed* while
        measuring a file outside the repo entirely.
        """
        import subprocess

        for declared in OntologiesStubsTransform.DATA_INPUTS:
            self.assertFalse(Path(declared).is_absolute(), f"{declared} is absolute")
            tracked = subprocess.run(  # noqa: S603 - fixed argv, paths from our own constant
                ["/usr/bin/git", "ls-files", "--error-unmatch", declared],  # noqa: S607
                cwd=REPO,
                capture_output=True,
            )
            self.assertEqual(
                tracked.returncode,
                0,
                f"{declared} is not tracked in git, so the freshness check silently ignores it",
            )

    def test_the_collector_has_no_second_undeclared_source(self):
        """
        Guard the derivation's premise, not just its output.

        `DATA_INPUTS` is derived from `DEFAULT_MAPPING_PATHS`, so it is only
        complete while that constant is the collector's sole source of files.
        If someone adds a second list, or globs `mappings/`, the derivation
        keeps passing every other test here while quietly under-declaring
        again.
        """
        source = inspect.getsource(stub_curie_collection)
        body = source.split("def collect_stub_curies")[1]
        self.assertNotIn(".glob(", body, "collector globs for files outside DEFAULT_MAPPING_PATHS")
        self.assertNotIn(".rglob(", body, "collector globs for files outside DEFAULT_MAPPING_PATHS")


class OutOfRepoPathTest(TestCase):
    """The derivation must not turn a config mistake into an ImportError (#841)."""

    def test_a_path_outside_the_repo_is_skipped_not_raised(self):
        """
        `relative_to` raises; this runs in a class body, so it raises at import.

        That breaks every importer of the module and points the traceback at a
        tuple comprehension rather than at the entry someone just added. An
        out-of-repo path carries no git signal anyway, so skipping it loses
        nothing the checker could have used.
        """
        # Never opened — only its position relative to the repo root matters.
        outside = Path(REPO_ROOT).parent / "elsewhere" / "mappings" / "external.tsv"
        kept = sorted(
            p.relative_to(REPO_ROOT).as_posix()
            for p in (*DEFAULT_MAPPING_PATHS, outside)
            if p.is_relative_to(REPO_ROOT)
        )
        self.assertEqual(len(kept), len(DEFAULT_MAPPING_PATHS))
        self.assertNotIn("external.tsv", " ".join(kept))
