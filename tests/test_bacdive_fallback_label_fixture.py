"""The real fallback fixture supports OAK label queries without suppressing database failures."""

import sqlite3
from contextlib import closing

import pytest
from sqlalchemy.exc import OperationalError

from kg_microbe.utils.oak_utils import get_label
from kg_microbe.utils.ontology_utils import FatalOntologyError
from tests.bacdive_fallback_fixtures import adapter, close_adapter, native_database


def test_native_label_view_returns_literal_evidence_and_a_successful_miss(tmp_path):
    """Read actual fixture statements through OAK; unrelated statement predicates are not labels."""
    implementation = adapter(native_database(tmp_path / "native.db"))
    try:
        assert list(implementation.labels(["NCBITaxon:2"])) == [("NCBITaxon:2", "Bacteria")]
        assert get_label(implementation, "NCBITaxon:2745") == "Halomonas"
        assert list(implementation.labels(["NCBITaxon:999999999"], allow_none=False)) == []
        assert get_label(implementation, "NCBITaxon:999999999") is None
    finally:
        close_adapter(implementation)


def test_missing_label_view_is_still_a_fatal_database_failure(tmp_path):
    """Reproduce the incomplete fixture as a negative control, not a legitimate missing label."""
    path = native_database(tmp_path / "native.db")
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("DROP VIEW rdfs_label_statement")
    implementation = adapter(path)
    try:
        with pytest.raises(FatalOntologyError) as caught:
            get_label(implementation, "NCBITaxon:2")
        assert isinstance(caught.value.__cause__, OperationalError)
        assert "rdfs_label_statement" in str(caught.value)
    finally:
        close_adapter(implementation)
