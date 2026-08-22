"""Tests for the object_label-vs-ontology check added for issue #777."""

import csv
import importlib.util
import sys
import tempfile
from pathlib import Path
from unittest import TestCase

_SPEC = importlib.util.spec_from_file_location(
    "validate_isolation_source_mappings",
    Path(__file__).parent.parent / "mappings" / "validate_isolation_source_mappings.py",
)
_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules["validate_isolation_source_mappings"] = _MODULE
_SPEC.loader.exec_module(_MODULE)

HEADER = [
    "subject_label",
    "subject_label_normalized",
    "object_id",
    "object_label",
    "object_source",
    "predicate_id",
    "confidence",
    "mapping_justification",
    "curator",
    "source_dataset",
    "notes",
    "verified_date",
]


def _nodes(path, rows):
    """Write a minimal KGX nodes.tsv extract."""
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t")
        writer.writerow(["id", "category", "name"])
        for curie, name in rows:
            writer.writerow([curie, "biolink:NamedThing", name])


def _mapping(tmp, rows):
    """Write a mapping TSV fixture."""
    path = Path(tmp) / "m.tsv"
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t")
        writer.writerow(HEADER)
        writer.writerows(rows)
    return path


def _row(subject, object_id, object_label, confidence="high", justification="semapv:ManualMappingCuration"):
    """Build a mapping row."""
    return [
        subject,
        subject.lower(),
        object_id,
        object_label,
        object_id.split(":")[0],
        "skos:exactMatch",
        confidence,
        justification,
        "test",
        "bacdive",
        "",
        "2026-08-14",
    ]


class LabelCheckTest(TestCase):
    """A row whose object_id denotes something other than its object_label must fail."""

    def setUp(self):
        """Point the validator at scratch ontology extracts."""
        self.tmp = tempfile.mkdtemp()
        onto = Path(self.tmp) / "ontologies"
        onto.mkdir()
        _nodes(
            onto / "envo_nodes.tsv",
            [
                ("ENVO:01000855", "area of mixed forest"),
                ("ENVO:01000008", "microbial mat"),
                # An imported term carrying a label older than the one UBERON defines.
                ("UBERON:0005409", "gastrointestinal tract"),
            ],
        )
        _nodes(onto / "uberon_nodes.tsv", [("UBERON:0005409", "alimentary part of gastrointestinal system")])
        stubs = Path(self.tmp) / "ontologies_stubs"
        stubs.mkdir()
        _nodes(stubs / "ncit_nodes.tsv", [("NCIT:C16403", "Cell Line")])
        self._orig = _MODULE.ONTOLOGY_NODES_DIRS
        _MODULE.ONTOLOGY_NODES_DIRS = (onto, stubs)

    def tearDown(self):
        """Restore the module-level paths."""
        _MODULE.ONTOLOGY_NODES_DIRS = self._orig

    def test_stub_ontologies_are_checked_too(self):
        """
        Issue #779: NCIT/mesh/BTO/PO/MICRO ids live in a sibling directory.

        Globbing only `ontologies/` left 38 of 280 mapped rows unjudgeable, and two
        of those were wrong — `Blood-culture` pointed at NCIT:C16403 "Cell Line",
        which put 75 bacdive edges on a cell line.
        """
        path = _mapping(self.tmp, [_row("Blood-culture", "NCIT:C16403", "Blood Culture")])
        failures = list(_MODULE.iter_validation_failures(path))
        self.assertEqual(len(failures), 1, failures)
        self.assertIn("Cell Line", failures[0][2])

    def test_the_defining_ontology_wins_over_an_importing_one(self):
        """
        Issue #782: 48 ids carry conflicting labels across extracts.

        `envo_nodes.tsv` sorts before `uberon_nodes.tsv`, so a first-seen-wins
        lookup would judge UBERON:0005409 by ENVO's imported copy and fail the
        correct row.
        """
        self.assertEqual(
            _MODULE.load_ontology_labels()["UBERON:0005409"],
            "alimentary part of gastrointestinal system",
        )
        path = _mapping(
            self.tmp,
            [_row("Gastrointestinal-tract", "UBERON:0005409", "alimentary part of gastrointestinal system")],
        )
        self.assertEqual(list(_MODULE.iter_validation_failures(path)), [])

    def test_a_mismatched_label_fails(self):
        """
        Reproduce the shape issue #777 found 14 times.

        `Indoor-Air` claimed ENVO:01000855 was "indoor air" when it denotes "area
        of mixed forest", and a downstream consumer shipped a habitat record
        labelled "area of mixed forest" as a result.
        """
        path = _mapping(self.tmp, [_row("Indoor-Air", "ENVO:01000855", "indoor air")])
        failures = list(_MODULE.iter_validation_failures(path))
        self.assertEqual(len(failures), 1, failures)
        self.assertIn("area of mixed forest", failures[0][2])

    def test_a_matching_label_passes(self):
        """The check must not fire on a correct row."""
        path = _mapping(self.tmp, [_row("Iron-mat", "ENVO:01000008", "microbial mat")])
        self.assertEqual(list(_MODULE.iter_validation_failures(path)), [])

    def test_case_differences_alone_do_not_fail(self):
        """Label comparison is case-insensitive; 'Waste' vs 'waste' is not a defect."""
        path = _mapping(self.tmp, [_row("Iron-mat", "ENVO:01000008", "Microbial Mat")])
        self.assertEqual(list(_MODULE.iter_validation_failures(path)), [])

    def test_an_untrusted_row_is_still_label_checked(self):
        """
        The label check must not inherit the trust gate.

        Other projects read this TSV directly — HabitatMech grounds habitat
        records from it — so a wrong id misleads them whether or not our loader
        trusts the row. 10 of the 14 rows in #777 were trusted, so the gate was
        never what hid them.
        """
        path = _mapping(
            self.tmp,
            [
                _row(
                    "Indoor-Air",
                    "ENVO:01000855",
                    "indoor air",
                    confidence="low",
                    justification="semapv:LexicalMatching",
                )
            ],
        )
        failures = list(_MODULE.iter_validation_failures(path))
        self.assertEqual(len(failures), 1, "an untrusted row with a wrong id must still be reported")

    def test_an_unresolvable_id_is_not_a_failure(self):
        """A term outside our extracts cannot be judged, and must not be guessed at."""
        path = _mapping(self.tmp, [_row("Something", "ENVO:99999999", "whatever")])
        self.assertEqual(list(_MODULE.iter_validation_failures(path)), [])

    def test_missing_extracts_skip_the_check_rather_than_failing(self):
        """The validator is stdlib-only for CI, where the extracts are not built."""
        _MODULE.ONTOLOGY_NODES_DIRS = (Path(self.tmp) / "does-not-exist",)
        self.assertEqual(_MODULE.load_ontology_labels(), {})
        path = _mapping(self.tmp, [_row("Indoor-Air", "ENVO:01000855", "indoor air")])
        self.assertEqual(list(_MODULE.iter_validation_failures(path)), [])
