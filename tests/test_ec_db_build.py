"""
Tests for building ec.db from the ec.owl we ship, and detecting release drift.

Fourth application of the single-source rule (#604), after GO, NCBITaxon, and
ChEBI. EC was the last hold-out — earlier revisions of ``_ensure_ec_db``
claimed EC had no reliable release stamp, so an existing ``ec.db`` was reused
indefinitely. In fact ``eccode.owl`` carries a ``versionIRI`` with a
``YYYY-MM-DD`` release, and the semsql build stamps the same IRI into
``owl:versionIRI`` on the ``obo:eccode.owl`` subject — so `kg download`
refreshing ``ec.owl.gz`` was silently leaving the old ``ec.db`` in place,
missing whatever labels the new release added or changed.

These tests pin the EC release reader and the drift-realign behavior. No test
runs a real `semsql make`: the build is mocked and size thresholds shrunk.
"""

from pathlib import Path

from kg_microbe.utils import ontology_utils as ou
from tests.db_helpers import write_semsql_db

_OWL = (
    '<?xml version="1.0"?>\n<rdf:RDF>\n'
    '<owl:Ontology rdf:about="http://purl.obolibrary.org/obo/eccode.owl">\n'
    '<owl:versionIRI rdf:resource="http://purl.obolibrary.org/obo/eccode/{d}/eccode.owl"/>\n'
    "</owl:Ontology>\n</rdf:RDF>\n"
)


def _make_ec_db(tmp_path: Path, release, name: str = "ec.db") -> str:
    """Write a minimal SemSQL-shaped ec.db stamping obo:eccode.owl versionIRI."""
    path = str(tmp_path / name)
    extra = []
    if release is not None:
        extra.append(
            (
                "INSERT INTO statements (subject, predicate, object, value) "
                "VALUES ('obo:eccode.owl', 'owl:versionIRI', ?, NULL)",
                (f"obo:eccode/{release}/eccode.owl",),
            )
        )
    write_semsql_db(path, extra_statements=extra)
    return path


class TestEcReleaseReader:
    """EC's versionIRI-object stamp must be read where the value-column reader cannot."""

    def test_reads_versioniri_date(self, tmp_path):
        """The release comes out of the versionIRI object."""
        assert ou._ec_db_release(_make_ec_db(tmp_path, "2024-10-02")) == "2024-10-02"

    def test_ignores_decoy_subject(self, tmp_path):
        """A version-shaped value on a non-ontology subject must not be picked."""
        path = str(tmp_path / "ec.db")
        write_semsql_db(
            path,
            extra_statements=[
                (
                    "INSERT INTO statements (subject, predicate, object, value) "
                    "VALUES ('obo:eccode/1.1.1.1', 'owl:versionIRI', 'obo:eccode/1999-01-01/eccode.owl', NULL)",
                    (),
                ),
                (
                    "INSERT INTO statements (subject, predicate, object, value) "
                    "VALUES ('obo:eccode.owl', 'owl:versionIRI', 'obo:eccode/2024-10-02/eccode.owl', NULL)",
                    (),
                ),
            ],
        )
        assert ou._ec_db_release(path) == "2024-10-02"

    def test_none_when_absent_or_corrupt(self, tmp_path):
        """A missing / unstamped / corrupt file yields None (no crash)."""
        assert ou._ec_db_release(_make_ec_db(tmp_path, None)) is None
        assert ou._ec_db_release(str(tmp_path / "nope.db")) is None
        corrupt = tmp_path / "corrupt.db"
        corrupt.write_bytes(b"not a sqlite file")
        assert ou._ec_db_release(str(corrupt)) is None

    def test_reads_full_iri_subject(self, tmp_path):
        """SemSQL variants that store the full IRI as subject must still resolve."""
        path = str(tmp_path / "ec.db")
        write_semsql_db(
            path,
            extra_statements=[
                (
                    "INSERT INTO statements (subject, predicate, object, value) "
                    "VALUES ('http://purl.obolibrary.org/obo/eccode.owl', 'owl:versionIRI', "
                    "'http://purl.obolibrary.org/obo/eccode/2024-10-02/eccode.owl', NULL)",
                    (),
                ),
            ],
        )
        assert ou._ec_db_release(path) == "2024-10-02"


class TestEcDbBuild:
    """`_ensure_ec_db` must realign on release drift, not serve stale forever."""

    def test_aligned_db_is_reused(self, tmp_path, monkeypatch):
        """Matching releases skip the build entirely."""
        monkeypatch.setattr(ou, "_EC_DB_MIN_SIZE", 8)
        owl = tmp_path / "ec.owl"
        owl.write_text(_OWL.format(d="2024-10-02"), encoding="utf-8")
        monkeypatch.setattr("kg_microbe.transform_utils.constants.EC_SOURCE", owl)
        db = _make_ec_db(tmp_path, "2024-10-02")
        calls = []
        monkeypatch.setattr(ou.shutil, "which", lambda _: "/usr/bin/semsql")
        monkeypatch.setattr(ou.subprocess, "run", lambda *a, **k: calls.append(a))

        assert ou._ensure_ec_db(db)
        assert calls == [], "no rebuild when releases align"

    def test_drifted_db_is_rebuilt(self, tmp_path, monkeypatch, capsys):
        """
        A refreshed ec.owl must trigger a rebuild of ec.db.

        Before this fix, `_ensure_ec_db` claimed EC had no reliable release
        stamp and reused any servable ec.db indefinitely. `kg download`
        refreshing `ec.owl.gz` was therefore invisible to the pipeline: new
        or changed EC terms received missing/stale labels in `rhea_mappings`
        until somebody manually deleted ec.db.
        """
        monkeypatch.setattr(ou, "_EC_DB_MIN_SIZE", 8)
        owl = tmp_path / "ec.owl"
        owl.write_text(_OWL.format(d="2026-07-31"), encoding="utf-8")
        monkeypatch.setattr("kg_microbe.transform_utils.constants.EC_SOURCE", owl)
        db = _make_ec_db(tmp_path, "2024-10-02")  # drifted stamp
        calls = []
        monkeypatch.setattr(ou.shutil, "which", lambda _: "/usr/bin/semsql")

        def build(cmd, **kwargs):
            """Emit a fresh ec.db stamped with the new release."""
            calls.append(cmd)
            _make_ec_db(Path(kwargs["cwd"]), "2026-07-31", name="ec.db")

        monkeypatch.setattr(ou.subprocess, "run", build)

        assert ou._ensure_ec_db(db)
        assert calls, "a drifted ec.db must trigger a rebuild"
        assert "drifted" in capsys.readouterr().out

    def test_unreadable_stamp_does_not_force_rebuild(self, tmp_path, monkeypatch):
        """
        An unreadable stamp is not a rebuild trigger — matches GO/ChEBI/NCBITaxon.

        The write-side strict gate is what stops an unverified build from
        being served; the reuse fast-path stays conservative because a
        transient SQLite lock on the stamp read shouldn't force a costly
        spurious rebuild every time the pipeline runs.
        """
        monkeypatch.setattr(ou, "_EC_DB_MIN_SIZE", 8)
        owl = tmp_path / "ec.owl"
        owl.write_text(_OWL.format(d="2026-07-31"), encoding="utf-8")
        monkeypatch.setattr("kg_microbe.transform_utils.constants.EC_SOURCE", owl)
        db = _make_ec_db(tmp_path, None)  # unstamped
        calls = []
        monkeypatch.setattr(ou.shutil, "which", lambda _: "/usr/bin/semsql")
        monkeypatch.setattr(ou.subprocess, "run", lambda *a, **k: calls.append(a))

        assert ou._ensure_ec_db(db)
        assert calls == [], "an unreadable stamp must not force a spurious rebuild"
