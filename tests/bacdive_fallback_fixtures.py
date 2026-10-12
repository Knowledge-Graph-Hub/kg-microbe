"""
Unexecuted offline fixture materialization for the reviewed fallback native reader.

The93 source records and native class statements are literal extracted evidence.
The small SQLite container and its version declaration are explicitly synthetic;
its bytes are NEVER represented as the complete13GB original NCBI database.
"""

import csv
import hashlib
import json
import sqlite3
from contextlib import closing, contextmanager
from pathlib import Path

from oaklib.implementations.sqldb.sql_implementation import SqlImplementation
from oaklib.resource import OntologyResource

from kg_microbe.merge_utils.source_admission import SourceAdmission
from kg_microbe.transform_utils.bacdive.bacdive import BacDiveTransform
from kg_microbe.transform_utils.bacdive.fallback_evidence import FallbackEvidence
from kg_microbe.transform_utils.bacdive.taxonomy_evidence import RAW_ROLE, _native_record
from kg_microbe.transform_utils.transform import Transform

RESOURCE = Path(__file__).parent / "resources/bacdive_fallback"


def native_payload():
    """Require exact independently extracted native fixtures before using any scientific fact."""
    native = RESOURCE / "native_compatibility.json"
    extra = RESOURCE / "additional_unresolved.json"
    selected = RESOURCE / "selected_nodes.tsv"
    assert (
        hashlib.sha256(native.read_bytes()).hexdigest()
        == "fcb19469ed9c98719a60eb8670bb449a583dedb63301bf06fbcca01dfde19916"
    )
    assert (
        hashlib.sha256(extra.read_bytes()).hexdigest()
        == "f2395f529618b27d4db9d56ab04ae4304f26b80e08251fa1cbc2578e770ee9da"
    )
    assert (
        hashlib.sha256(selected.read_bytes()).hexdigest()
        == "ad031ecd8496179e9a15ed6da88b7dd06774a3c7c888f3f8080d2dec5c3cdd0d"
    )
    return json.loads(native.read_text()), json.loads(extra.read_text())


def records_by_id():
    """Rejoin full93 native records without stripping evidence or changing source taxonomy fields."""
    native, extra = native_payload()
    entries = {key: value["source_context"] for key, value in native["records"].items()}
    for key, value in extra["records"].items():
        assert key not in entries
        entries[key] = value["native"]
    assert len(entries) == 93
    for entry in entries.values():
        encoded = json.dumps(entry["record"], sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        assert hashlib.sha256(encoded.encode()).hexdigest() == entry["canonical_record_sha256"]
    return entries


def native_database(path):
    """Use exact native class/rank/label/ancestor rows in an honest small synthetic SemSQL container."""
    native, _ = native_payload()
    columns = ("stanza", "subject", "predicate", "object", "value", "datatype", "language", "graph")
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute(
            "CREATE TABLE statements(stanza TEXT,subject TEXT,predicate TEXT,object TEXT,"
            "value TEXT,datatype TEXT,language TEXT,graph TEXT)"
        )
        connection.execute("CREATE INDEX statements_spv ON statements(subject,predicate,value)")
        connection.execute("CREATE INDEX statements_p ON statements(predicate)")
        connection.execute("CREATE TABLE entailed_edge(subject TEXT,predicate TEXT,object TEXT)")
        for statements in native["literal_native_declarations"].values():
            connection.executemany(
                "INSERT INTO statements VALUES (?,?,?,?,?,?,?,?)",
                [tuple(row.get(column) for column in columns) for row in statements],
            )
        connection.execute(
            "INSERT INTO statements(subject,predicate,value) VALUES "
            "('obo:ncbitaxon.owl','owl:versionInfo','explicit-test-excerpt-not-the-full-native-epoch')"
        )
        # Only test-created materialized edges are used by deposit ancestry;
        # fallback identity uses the literal native statements above exclusively.
        declarations = native["literal_native_declarations"]
        for subject in declarations:
            seen, pending = set(), [subject]
            while pending:
                node = pending.pop()
                if node in seen:
                    continue
                seen.add(node)
                pending.extend(row["object"] for row in declarations[node] if row["predicate"] == "rdfs:subClassOf")
            connection.executemany(
                "INSERT INTO entailed_edge VALUES (?,?,?)",
                [(subject, "rdfs:subClassOf", target) for target in sorted(seen)],
            )
    return path


def adapter(path):
    """Select the exact test-local SQL file directly, without any downloader/cache builder."""
    return SqlImplementation(resource=OntologyResource(slug=str(path.absolute())))


def close_adapter(value):
    """Close only the original test-owned adapter; the production guard owns another connection."""
    if value._session is not None:
        value._session.close()
    value.engine.dispose()


def stage(tmp_path, records, *, selected=True):
    """Execute genuine consumed-input snapshots and native selection, never fabricated role receipts."""
    raw = tmp_path / "raw"
    raw.mkdir(parents=True)
    path = raw / "bacdive_strains.json"
    path.write_text(json.dumps(records, ensure_ascii=True))
    transform = BacDiveTransform.__new__(BacDiveTransform)
    Transform.__init__(transform, "bacdive", raw, tmp_path / "transformed")
    transform.begin_consumed_inputs()
    with transform.consume_input(RAW_ROLE, path) as stream:
        actual = json.load(stream)
    snapshots = transform.consumed_input_snapshots
    nodes = tmp_path / "selected_nodes.tsv"
    if selected:
        nodes.write_bytes((RESOURCE / "selected_nodes.tsv").read_bytes())
    db = native_database(raw / "test-native-excerpt.db")
    original = adapter(db)

    @contextmanager
    def opener(role, locator):
        """Expose only the actual immutable stream under the consumer's real named role."""
        with transform.consume_input(role, locator) as stream:
            snapshots[role] = transform.consumed_input_snapshots[role]
            yield stream

    entries = [_native_record(index, record) for index, record in enumerate(actual)]
    try:
        guard = FallbackEvidence(
            entries,
            snapshots,
            raw_role=RAW_ROLE,
            selected_path=nodes,
            opener=opener,
            adapter_selector=lambda: original,
            admission=SourceAdmission(),
        )
    finally:
        close_adapter(original)
    return transform, guard, entries, snapshots, nodes, db


def write_rows(path, rows, *, quoting=csv.QUOTE_NONE):
    """Mutate only test outputs using their actual producer/finalized TSV dialect."""
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=list(rows[0]),
            delimiter="\t",
            quoting=quoting,
            quotechar=None if quoting == csv.QUOTE_NONE else '"',
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)
