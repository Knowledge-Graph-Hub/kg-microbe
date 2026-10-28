"""Runtime authority errors must not become successful bare-ID graph labels."""

import errno
import sqlite3

import pytest
from sqlalchemy.exc import DBAPIError, OperationalError

from kg_microbe.utils.oak_utils import get_label
from kg_microbe.utils.ontology_utils import (
    FatalOntologyError,
    OntologyDbUnavailableError,
    OntologyVersionMismatchError,
)


class _Labels:
    """A small adapter exercising iteration, including failures after the first row."""

    def __init__(self, rows=(), error=None):
        """Keep exact results and the original error for identity assertions."""
        self.rows = rows
        self.error = error

    def labels(self, identifiers):
        """Yield results before any configured late database error."""
        assert identifiers == ["NCBITaxon:2696284"]
        yield from self.rows
        if self.error is not None:
            raise self.error


@pytest.mark.parametrize(
    "error",
    [
        sqlite3.OperationalError("database is locked"),
        sqlite3.DatabaseError("database disk image is malformed"),
        OperationalError("SELECT value FROM statements", {}, sqlite3.OperationalError("database is locked")),
        DBAPIError("SELECT value FROM statements", {}, sqlite3.DatabaseError("disk I/O error")),
        OSError(errno.EIO, "Input/output error"),
    ],
)
@pytest.mark.parametrize("rows", [(), (("NCBITaxon:2696284", "first result"),)])
def test_database_failure_escapes_per_record_fallback(error, rows):
    """Preflight success or one returned label cannot excuse a failed authority read."""
    with pytest.raises(FatalOntologyError) as caught:
        try:
            get_label(_Labels(rows, error), "NCBITaxon:2696284")
        except Exception:
            pytest.fail("authority failure was catchable as an ordinary per-record lookup miss")
    assert caught.value.__cause__ is error
    assert "NCBITaxon:2696284" in str(caught.value)


@pytest.mark.parametrize("error_type", [OntologyDbUnavailableError, OntologyVersionMismatchError])
def test_existing_fatal_error_retains_its_identity(error_type):
    """Already classified infrastructure failures propagate without reinterpretation."""
    error = error_type("authority unavailable")
    with pytest.raises(error_type) as caught:
        get_label(_Labels(error=error), "NCBITaxon:2696284")
    assert caught.value is error


def test_programming_error_is_not_a_missing_label():
    """An unexpected adapter error must not silently generate a numeric label."""
    error = ValueError("invalid adapter response")
    with pytest.raises(ValueError) as caught:
        get_label(_Labels(error=error), "NCBITaxon:2696284")
    assert caught.value is error


@pytest.mark.parametrize("label", ["A microbial taxon", None])
def test_successful_adapter_result_is_preserved(label):
    """Preserve the adapter's existing result semantics, including an explicit None."""
    assert get_label(_Labels((("NCBITaxon:2696284", label),)), "NCBITaxon:2696284") == label


def test_empty_lookup_retains_missing_term_fallback():
    """No matching term is not a broken database."""
    assert get_label(_Labels(), "NCBITaxon:2696284") == "2696284"
