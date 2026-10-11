"""
Own a private, byte-bound BacDive ancestor-query authority.

The caller/shared OAK adapter identifies its actual selected SQLite file only;
no caller engine/session is queried, reset, or closed. Immutable SQLite mode
does not provide a filesystem snapshot: retained byte and locator checks bind
the independently owned query connection throughout its lifecycle.
"""

import hashlib
import inspect
import json
import os
import sqlite3
from pathlib import Path

from kg_microbe.merge_utils.source_admission import SourceAdmission
from kg_microbe.transform_utils.constants import RDFS_SUBCLASS_OF
from kg_microbe.utils.source_finalization import SourceFinalizationRequired

_SIDECARS = ("-wal", "-shm", "-journal")


def _fail(message):
    """Refuse an invalid native authority without converting it into an empty result."""
    raise SourceFinalizationRequired("BacDive ancestry authority: " + message)


def _json(value):
    """Encode detached structured evidence deterministically."""
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":"))


class FreshAncestryAuthority:
    """
    Keep one owned immutable-mode SQLite connection fixed for a query batch.

    ``immutable=1`` tells SQLite to avoid file locks and journals. It does NOT
    make the filesystem immutable. Hashes before opening and after the complete
    query batch, per-query file stamps, original lexical bindings, and absent
    sidecar checks are mandatory. Unsupported adapters are refused, not guessed.
    """

    def __init__(self, selected_path, *, admission=None):
        """Capture selected bytes before creating any private adapter connection."""
        # Local imports retain offline/basic import boundaries. No OAK selector,
        # downloader, builder, or global ontology-adapter cache is used here.
        from oaklib.implementations.sqldb.sql_implementation import SqlImplementation
        from oaklib.resource import OntologyResource
        from sqlalchemy import create_engine
        from sqlalchemy.exc import SQLAlchemyError
        from sqlalchemy.pool import StaticPool

        self.admission = admission or SourceAdmission()
        self.selected = Path(selected_path).absolute()
        self.resolved = self.selected.resolve()
        self._engine = None
        self._adapter = None
        self._session = None
        self._connection = None
        self._close_owned = None
        self._failed = False
        self._finished = False
        self._closed = False
        self._queries = []
        self._sealed_queries = None
        self._contract = None
        self._recorded_authority = None
        self.admission.capture_resolution(lambda: self._failed)
        self._sidecars = tuple(
            sorted({Path(str(path) + suffix) for path in (self.selected, self.resolved) for suffix in _SIDECARS})
        )
        try:
            self._check_sidecars()
            for path in self._sidecars:
                self.admission.capture(path, optional=True)
            self._identity = self.admission.capture(self.selected)
            self._implementation = Path(inspect.getfile(SqlImplementation)).absolute()
            implementation_identity = self.admission.capture(self._implementation)
            self._authority = _json(
                {
                    "selected_path": str(self.selected),
                    "resolved_path": str(self.resolved),
                    "identity": self._identity,
                    "absent_sqlite_sidecars": [str(path) for path in self._sidecars],
                    "implementation": {
                        "class": "oaklib.implementations.sqldb.sql_implementation.SqlImplementation",
                        "path": str(self._implementation),
                        **implementation_identity,
                    },
                    "connection_mode": "read_only_immutable_mode_not_filesystem_snapshot",
                }
            )
            self._read_cache = tuple(
                (str(path), _json(self.admission.identities[path]), self.admission.stamps[path])
                for path in (self.resolved, self._implementation.resolve())
            )
            self.admission.capture_resolution(self._authority_state)

            def connect_private():
                """Open only the already-admitted file; never reopen a shared caller handle."""
                self._verify_files()
                connection = sqlite3.connect(self.resolved.as_uri() + "?mode=ro&immutable=1", uri=True)
                try:
                    connection.execute("PRAGMA query_only=ON")
                except BaseException:
                    connection.close()
                    raise
                return connection

            self._engine = create_engine("sqlite://", creator=connect_private, poolclass=StaticPool)
            self._adapter = SqlImplementation(resource=OntologyResource(slug=str(self.resolved)), engine=self._engine)
            self._session = self._adapter.session
            self._connection = self._session.connection()
            owned_adapter, owned_session, owned_engine = self._adapter, self._session, self._engine

            def close_owned():
                """Close only captured owned handles even after a hostile reference replacement."""
                # Restore only fields on the adapter this constructor itself
                # allocated, so its eventual __del__ also owns the right objects.
                owned_adapter._session = owned_session
                owned_adapter.engine = owned_engine
                try:
                    owned_session.close()
                finally:
                    owned_engine.dispose()

            self._close_owned = close_owned
            self._database_list = self._read_database_list()
            expected = ((0, "main", str(self.resolved)),)
            if self._database_list != expected:
                _fail("private connection did not open exactly the admitted main database")
            self._native_version = _json(
                sorted(
                    (
                        dict(row)
                        for row in self._connection.exec_driver_sql(
                            "SELECT * FROM statements WHERE subject LIKE '%ncbitaxon%' "
                            "AND predicate IN ('owl:versionInfo', 'owl:versionIRI')"
                        ).mappings()
                    ),
                    key=_json,
                )
            )
            if not json.loads(self._native_version):
                _fail("actual NCBITaxon authority lacks native version statements")
            self._verify_files()
            self.admission.capture_resolution(self._live_connection_state)
            self.admission.capture_resolution(lambda: self._native_version)
        except (SQLAlchemyError, sqlite3.Error) as error:
            self._poison()
            self.close()
            raise SourceFinalizationRequired(
                "BacDive ancestry authority: native database connection or metadata query failed"
            ) from error
        except BaseException:
            self._poison()
            self.close()
            raise

    @classmethod
    def from_resolved_adapter(cls, adapter, *, admission=None):
        """Select the real resolved adapter engine's SQLite file, not configured ncbitaxon.db."""
        from oaklib.implementations.sqldb.sql_implementation import SqlImplementation

        if type(adapter) is not SqlImplementation or adapter.engine is None:
            _fail("unsupported resolved adapter; an exact SQLite authority cannot be established")
        engine = adapter.engine
        database = engine.url.database
        if (
            engine.dialect.name != "sqlite"
            or engine.url.query
            or not isinstance(database, str)
            or not database
            or database == ":memory:"
            or database.startswith("file:")
        ):
            _fail("unsupported adapter engine locator")
        if not Path(database).is_absolute():
            _fail("resolved adapter database must have an absolute lexical locator")
        original = (id(adapter), id(engine), str(engine.url), database)
        guard = cls(database, admission=admission)

        def selected_adapter():
            """Do not let later changes to the source selector masquerade as the same actual authority."""
            return id(adapter), id(adapter.engine), str(adapter.engine.url), adapter.engine.url.database

        try:
            if selected_adapter() != original:
                _fail("caller adapter selection changed while binding its actual input")
            guard.admission.capture_resolution(selected_adapter)
        except BaseException:
            guard._poison()
            guard.close()
            raise
        return guard

    @classmethod
    def from_recorded_authority(cls, recorded, *, admission=None):
        """
        Re-admit the original authority and replay with byte-identical installed query code.

        A different interpreter can have the same pinned OAK file at a different
        path. Preserve and rehash the original producer's implementation path;
        separately bind the current interpreter's actual imported code. Never
        describe that current replay origin as the original producer's import.
        """
        if (
            not isinstance(recorded, dict)
            or not isinstance(recorded.get("selected_path"), str)
            or not Path(recorded["selected_path"]).is_absolute()
        ):
            _fail("recorded actual ancestry authority missing")
        guard = cls(recorded["selected_path"], admission=admission)
        try:
            actual = json.loads(guard._authority)
            prior_impl = recorded.get("implementation")
            if not isinstance(prior_impl, dict) or set(prior_impl) != {"class", "path", "bytes", "sha256"}:
                _fail("recorded query implementation binding missing")
            prior_path = Path(prior_impl["path"])
            if not prior_path.is_absolute():
                _fail("recorded query implementation locator is not absolute")
            identity = guard.admission.capture(prior_path)
            if identity != {key: prior_impl[key] for key in ("bytes", "sha256")}:
                _fail("original producer query implementation changed")
            current_impl = actual["implementation"]
            if any(current_impl[key] != prior_impl[key] for key in ("class", "bytes", "sha256")):
                _fail("current replay query implementation differs from original producer")
            resolved_prior = prior_path.resolve()
            expected_identity, expected_stamp = _json(identity), guard.admission.stamps[resolved_prior]

            def original_import_binding():
                """Missing cache membership cannot erase the original producer's code obligation."""
                if (
                    guard.admission.bindings.get(prior_path.absolute()) != resolved_prior
                    or _json(guard.admission.identities.get(resolved_prior)) != expected_identity
                    or guard.admission.stamps.get(resolved_prior) != expected_stamp
                ):
                    _fail("original producer query-code admission binding was lost")
                return str(prior_path), str(resolved_prior), expected_identity, expected_stamp

            guard.admission.capture_resolution(original_import_binding)
            # All scientific authority/connection fields remain exact. Only the
            # separately verified, byte-identical import location may differ.
            actual["implementation"] = prior_impl
            if actual != recorded:
                _fail("recorded ancestry authority differs from actual selected input")
            guard._recorded_authority = _json(recorded)
            guard.admission.capture_resolution(lambda: guard._recorded_authority)
        except BaseException:
            guard._poison()
            guard.close()
            raise
        return guard

    def _check_sidecars(self):
        """Refuse live SQLite state at either lexical or resolved location."""
        for path in self._sidecars:
            if os.path.lexists(path):
                _fail("SQLite sidecar exists: " + str(path))

    def _poison(self):
        """Retain failure even when an outer catch later resets the visible boolean."""
        self._failed = True
        # Initial false and failed true are incompatible retained observations;
        # resetting this mutable flag cannot make both checkpoints pass.
        self.admission.capture_resolution(lambda: self._failed)

    def _authority_state(self):
        """Derive all absent-state obligations independently of the mutable admission cache."""
        if self.selected.resolve() != self.resolved or self.resolved.resolve() != self.resolved:
            _fail("original authority locator changed")
        expected = tuple(
            sorted({Path(str(path) + suffix) for path in (self.selected, self.resolved) for suffix in _SIDECARS})
        )
        if self._sidecars != expected:
            _fail("SQLite sidecar obligation changed")
        self._check_sidecars()
        for path in expected:
            if (
                path.resolve() not in self.admission.absent
                or self.admission.bindings.get(path.absolute()) != path.resolve()
            ):
                _fail("mandatory absent-sidecar guard was lost")
        for name, identity, stamp in self._read_cache:
            path = Path(name)
            if _json(self.admission.identities.get(path)) != identity or self.admission.stamps.get(path) != stamp:
                _fail("mandatory actual-input read binding was lost or replaced")
        if self.admission.bindings.get(self.selected) != self.resolved:
            _fail("original lexical authority binding was lost")
        if self.admission.bindings.get(self._implementation) != self._implementation.resolve():
            _fail("actual imported query implementation locator guard was lost")
        return self._authority, self.selected, self.resolved, self._implementation, self._read_cache

    def _read_database_list(self):
        """Read actual connection attachments for comparison with the admitted native file."""
        return tuple(tuple(row) for row in self._connection.exec_driver_sql("PRAGMA database_list"))

    def _live_connection_state(self):
        """Pin owned adapter/engine/session objects without executing a graph query in the guard."""
        return (
            id(self._adapter),
            id(self._engine),
            id(self._session),
            id(self._connection),
            id(self._adapter.engine),
            id(self._adapter._session),
        )

    def _verify_files(self, *, full=False):
        """Verify original authority bindings and file metadata during the query lifecycle."""
        self._check_sidecars()
        self.admission.verify(metadata_only=not full)

    def ancestors(self, identifier):
        """Run the unchanged OAK query and retain its computed, not asserted-native, result."""
        from sqlalchemy.exc import SQLAlchemyError

        try:
            if self._failed or self._finished or self._closed:
                _fail("ancestry queries require a live unchanged private connection")
            self._verify_files()
            if self._read_database_list() != self._database_list:
                _fail("private database attachment changed")
            values = list(self._adapter.ancestors([identifier], predicates=[RDFS_SUBCLASS_OF]))
            self._verify_files()
        except SourceFinalizationRequired:
            self._poison()
            raise
        except (SQLAlchemyError, sqlite3.Error) as error:
            self._poison()
            raise SourceFinalizationRequired("BacDive ancestry authority: native database query failed") from error
        except BaseException:
            # A genuinely unknown taxid already returns an empty result. A
            # broken query is never recorded as harmless unresolved taxonomy.
            self._poison()
            raise
        self._queries.append(
            {
                "subject": identifier,
                "predicates": [RDFS_SUBCLASS_OF],
                "reflexive": True,
                "exception_type": None,
                "computed_ancestors": sorted(values),
            }
        )
        return frozenset(values) - {identifier}

    def finish(self):
        """Seal the exact query batch and rehash authority bytes after all queries, before publication."""
        if self._failed or self._finished or self._closed:
            _fail("invalid ancestry completion state")
        try:
            if self._read_database_list() != self._database_list:
                _fail("private database attachment changed")
            self._verify_files(full=True)
            self._sealed_queries = _json(sorted(self._queries, key=_json))
            self._contract = _json(
                {
                    "version": 1,
                    "authority": json.loads(self._recorded_authority or self._authority),
                    "native_version_statements": json.loads(self._native_version),
                    "computed_queries": json.loads(self._sealed_queries),
                    "query_sha256": hashlib.sha256(self._sealed_queries.encode()).hexdigest(),
                    "asserted_native_parent_rows": False,
                }
            )
            self._finished = True
            self.admission.capture_resolution(lambda: (self._finished, self._contract, _json(self._queries)))
        except BaseException:
            self._poison()
            raise
        finally:
            self.close()
        return self.contract

    @property
    def contract(self):
        """Return only a successfully completed actual-query contract."""
        self.verify()
        if not self._finished:
            _fail("ancestry query batch is incomplete")
        return json.loads(self._contract)

    def verify(self, *, full=False):
        """Retain fatal failures, exact native identity and monotonic lifecycle after closure."""
        if self._failed:
            _fail("a previous ancestry checkpoint failed")
        try:
            self._verify_files(full=full)
        except BaseException:
            self._poison()
            raise

    def close(self):
        """Close only this object's owned connection/session on every normal or failure path."""
        if self._closed:
            return
        try:
            if self._close_owned is not None:
                self._close_owned()
            elif self._session is not None:
                self._session.close()
        finally:
            try:
                if self._close_owned is None and self._engine is not None:
                    self._engine.dispose()
            finally:
                self._closed = True
                self.admission.capture_resolution(lambda: self._closed)

    def __enter__(self):
        """Return the existing owned authority without selecting another adapter."""
        return self

    def __exit__(self, exc_type, _value, _traceback):
        """Close the owned handle on exit; require the caller to finish explicitly."""
        if exc_type is not None:
            self._poison()
        self.close()
