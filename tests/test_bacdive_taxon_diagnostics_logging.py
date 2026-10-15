"""BacDive's per-record taxon diagnostics go to its logger, not stdout (#1596)."""

import logging

import pytest

from kg_microbe.transform_utils.bacdive import bacdive as module
from kg_microbe.transform_utils.bacdive.bacdive import BacDiveTransform


class _Parser:
    """Only the state the parsers below read; they never touch the transform's inputs."""

    def __init__(self):
        """Answer every label lookup with one taxon, as a found higher rank would."""
        self._search_ncbitaxon_by_label = lambda label: "NCBITaxon:356"
        self._create_node_row = lambda *args, **kwargs: list(args)


@pytest.mark.parametrize(
    "call, logged",
    [
        (
            lambda p: BacDiveTransform._normalize_special_taxon_names(p, "Rhizobiales (not further classified)"),
            "Extracted taxon name: Rhizobiales",
        ),
        (
            lambda p: BacDiveTransform._normalize_special_taxon_names(p, "Unidentified actinobacterium"),
            "Extracted taxon name: actinobacterium",
        ),
        (
            lambda p: BacDiveTransform._parse_genus_from_scientific_name(p, "Strep2 sp."),
            "Genus 'Strep2' contains non-alphabetic characters",
        ),
        (
            lambda p: BacDiveTransform._create_provisional_species_node(p, "Proactinomyces", "roseus", _Writer()),
            "Created provisional species node",
        ),
        (
            lambda p: BacDiveTransform._create_provisional_genus_node(p, "Proactinomyces", _Writer()),
            "Created provisional genus node",
        ),
        (
            lambda p: BacDiveTransform._search_higher_ranks_in_ncbitaxon(p, {module.ORDER: "Rhizobiales"}),
            "Found higher rank 'Rhizobiales'",
        ),
    ],
    ids=["not-further-classified", "unidentified", "genus", "provisional-species", "provisional-genus", "higher-rank"],
)
def test_taxon_diagnostics_are_debug_log_records_not_stdout(call, logged, capsys, caplog):
    """Finalization and freshness checks rerun these parsers, so a print reached every check's stdout."""
    with caplog.at_level(logging.DEBUG, logger=module.logger.name):
        call(_Parser())
    assert capsys.readouterr().out == ""
    (record,) = [r for r in caplog.records if logged in r.getMessage()]
    assert record.levelno == logging.DEBUG and record.name == module.logger.name


class _Writer:
    """Accept node rows without a file."""

    def writerow(self, row):
        """Discard the row."""
