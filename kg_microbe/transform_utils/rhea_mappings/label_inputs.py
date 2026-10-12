"""Project exact external labels from consumed, prepared DBs in Rhea's selected raw root."""

import sqlite3
from contextlib import ExitStack, contextmanager
from functools import lru_cache
from pathlib import Path

from kg_microbe.transform_utils.constants import CHEBI_PREFIX, EC_PREFIX, GO_PREFIX
from kg_microbe.utils.source_finalization import SourceFinalizationRequired

LABEL_DATABASES = {
    "rhea_chebi_labels": ("chebi.db", CHEBI_PREFIX, "chebi"),
    "rhea_go_labels": ("go.db", GO_PREFIX, "go"),
    "rhea_ec_labels": ("ec.db", EC_PREFIX, "eccode"),
}
REQUIRED_LABEL_INPUTS = tuple(LABEL_DATABASES)
LABEL_CONTRACT = {"version": 1, "kind": "rhea-prepared-local-labels"}


def validate_label_contract(recorded):
    """Require an exact versioned reader contract, not Python's Boolean/integer equality."""
    if not isinstance(recorded, dict) or type(recorded.get("version")) is not int or recorded != LABEL_CONTRACT:
        raise SourceFinalizationRequired("Rhea label input contract changed; rerun the producer")


def _require_standalone(path):
    """Reject unconsumed SQLite journal or WAL state outside the main-file hash."""
    path = Path(path)
    for selected in {path.absolute(), path.resolve()}:
        for suffix in ("-wal", "-shm", "-journal"):
            sidecar = Path(str(selected) + suffix)
            if sidecar.exists():
                raise SourceFinalizationRequired(f"Rhea label DB must be quiescent; SQLite sidecar exists: {sidecar}")


def verify_label_bindings(raw_dir, snapshots):
    """Keep each consumed role rooted in the explicitly selected prepared authority."""
    for role, (filename, _, _) in LABEL_DATABASES.items():
        path = Path(raw_dir) / filename
        expected = snapshots.get(role, {})
        if expected.get("path") != str(path.resolve()):
            raise SourceFinalizationRequired(f"Rhea label role {role} is not bound to selected raw root: {path}")
        _require_standalone(path)


def _validate_schema(connection, ontology):
    """Require the SemSQL columns actually read and an explicit matching ontology declaration."""
    fields = {row[1] for row in connection.execute('PRAGMA table_info("statements")')}
    if not {"subject", "predicate", "object", "value"} <= fields:
        raise SourceFinalizationRequired("Rhea label authority lacks the required SemSQL statements columns")
    indices = [
        [column[0] for column in connection.execute("SELECT name FROM pragma_index_info(?) ORDER BY seqno", (row[1],))]
        for row in connection.execute('PRAGMA index_list("statements")')
        if not row[4]  # A partial index cannot guarantee every exact-ID lookup is indexed.
    ]
    if not any(set(columns[:2]) == {"subject", "predicate"} for columns in indices):
        raise SourceFinalizationRequired("Rhea label authority lacks an exact subject/predicate index")
    subjects = (f"obo:{ontology}.owl", f"obo:{ontology}", f"http://purl.obolibrary.org/obo/{ontology}.owl")
    identity = connection.execute(
        "SELECT 1 FROM statements WHERE subject IN (?, ?, ?) "
        "AND predicate='rdf:type' AND object='owl:Ontology' LIMIT 1",
        subjects,
    ).fetchone()
    if identity is None:
        raise SourceFinalizationRequired(f"Rhea label authority does not declare the expected ontology: {ontology}")


@contextmanager
def external_label_lookup(transform):
    """Read immutable DB snapshots only; never build, download, remap IDs, or invent missing labels."""
    with ExitStack() as stack:
        connections = {}
        missing_counts = {prefix: 0 for _, prefix, _ in LABEL_DATABASES.values()}
        for role, (filename, prefix, ontology) in LABEL_DATABASES.items():
            path = Path(transform.input_base_dir) / filename
            stream = stack.enter_context(transform.consume_input(role, path))
            _require_standalone(path)
            connection = sqlite3.connect(Path(stream.name).as_uri() + "?mode=ro&immutable=1", uri=True)
            stack.callback(connection.close)
            connection.execute("PRAGMA query_only=ON")
            _validate_schema(connection, ontology)
            connections[prefix] = connection

        @lru_cache(maxsize=None)
        def lookup(identifier):
            """Keep one literal exact-ID label; an absent annotation is explicitly absent."""
            prefix = next((prefix for prefix in connections if identifier.startswith(prefix)), None)
            if prefix is None:
                raise ValueError(f"Unsupported Rhea external label namespace: {identifier}")
            values = set()
            for obj, value in connections[prefix].execute(
                "SELECT object, value FROM statements WHERE subject=? AND predicate='rdfs:label'", (identifier,)
            ):
                if obj not in (None, "") or (value is not None and not isinstance(value, str)):
                    raise SourceFinalizationRequired(f"Nonliteral Rhea external label: {identifier}")
                if value:
                    values.add(value)
            if len(values) > 1:
                raise SourceFinalizationRequired(f"Ambiguous Rhea external label: {identifier}")
            if not values:
                missing_counts[prefix] += 1
            return next(iter(values), "")

        lookup.missing_counts = missing_counts
        yield lookup
        # This check and consume_input's final hash checks finish before the
        # producer's enclosing atomic graph writers publish any output.
        verify_label_bindings(transform.input_base_dir, transform.consumed_input_snapshots)
