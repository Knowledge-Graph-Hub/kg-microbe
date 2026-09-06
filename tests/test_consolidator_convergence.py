"""The consolidator must say whether a run reached its fixed point (#948)."""

import importlib.util
import io
import unittest
from contextlib import redirect_stdout
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "consolidate_chemical_mappings.py"

_spec = importlib.util.spec_from_file_location("consolidate_chemical_mappings", SCRIPT)
ccm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ccm)


def _write(path, triples):
    """
    Write a minimal SSSOM set containing ``triples``.

    :param path: Destination ``.gz`` path.
    :param triples: ``(subject, predicate, object)`` tuples.
    :return: None.
    """
    with ccm.open_deterministic_gzip(path) as handle:
        handle.write("# curie_map:\n")
        handle.write("subject_id\tpredicate_id\tobject_id\tmapping_date\n")
        for subject, predicate, obj in triples:
            handle.write(f"{subject}\t{predicate}\t{obj}\t2026-01-01\n")


def _report(seed, written):
    """
    Run the reporter and capture what it printed.

    :param seed: Seed triples, or None.
    :param written: Path of the artifact just written.
    :return: Captured stdout.
    """
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        ccm._report_convergence(seed, written)
    return buffer.getvalue()


class ConvergenceReportTests(unittest.TestCase):
    """A reviewer must be able to tell a fixed point from one step short."""

    def test_a_fixed_point_says_so(self):
        """The seeding makes an empty diff the exception, so name it when it happens."""
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "out.sssom.tsv.gz"
            triples = {("A:1", "skos:exactMatch", "B:1"), ("A:2", "skos:closeMatch", "B:2")}
            _write(out, triples)
            output = _report(set(triples), out)
            self.assertIn("Converged", output)
            self.assertIn("2 triples", output)

    def test_a_moved_artifact_reports_both_directions_and_says_to_re_run(self):
        """
        A net count hides the shape, and the operator needs the instruction.

        Committing one step short is the failure this exists to prevent, and
        nothing else in the run surfaces which state the output is in.
        """
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "out.sssom.tsv.gz"
            _write(out, [("A:1", "skos:exactMatch", "B:1"), ("A:3", "skos:exactMatch", "B:3")])
            seed = {("A:1", "skos:exactMatch", "B:1"), ("A:2", "skos:exactMatch", "B:2")}
            output = _report(seed, out)
            self.assertIn("Not yet converged", output)
            self.assertIn("1 added", output)
            self.assertIn("1 removed", output)
            self.assertIn("re-run", output)

    def test_a_first_run_has_nothing_to_converge_against(self):
        """No previous artifact is not a failure to converge, and must not read as one."""
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "out.sssom.tsv.gz"
            _write(out, [("A:1", "skos:exactMatch", "B:1")])
            output = _report(None, out)
            self.assertIn("First run", output)
            self.assertNotIn("Not yet converged", output)


if __name__ == "__main__":
    unittest.main()
