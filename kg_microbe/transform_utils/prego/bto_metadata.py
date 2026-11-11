"""Read BTO class labels from the selected, byte-bound SemSQL distribution."""

import gzip
import re
import shutil
import sqlite3
import tempfile
from pathlib import Path

from kg_microbe.utils.source_finalization import snapshot_consumed_input

ROLE = "prego_bto_metadata"
FILENAME = "bto.db.gz"
AUDIT_FILE = "prego_bto_metadata.tsv"
AUDIT_COLUMNS = ("id", "status", "name", "deprecated", "authority_sha256", "version_iri")
_IDENTIFIER = re.compile(r"BTO:[0-9]{7}\Z")


def load_bto_metadata(transform):
    """Read only declared classes; fail on malformed or contradictory source metadata."""
    with snapshot_consumed_input(transform, ROLE, transform.input_base_dir / FILENAME, binary=True) as source:
        with tempfile.TemporaryDirectory(prefix=".bto-metadata-", dir=transform.output_dir) as temporary:
            database = Path(temporary) / "bto.db"
            with gzip.GzipFile(fileobj=source) as compressed, database.open("wb") as target:
                shutil.copyfileobj(compressed, target)
            with sqlite3.connect(database.resolve().as_uri() + "?mode=ro&immutable=1", uri=True) as connection:
                classes = {
                    row[0]
                    for row in connection.execute(
                        "SELECT DISTINCT subject FROM statements WHERE predicate='rdf:type' AND object='owl:Class'"
                    )
                    if _IDENTIFIER.fullmatch(row[0] or "")
                }
                if not classes:
                    raise ValueError("BTO metadata authority has no declared BTO classes")
                labels, deprecated = {}, {}
                for identifier, predicate, value in connection.execute(
                    "SELECT subject,predicate,value FROM statements WHERE predicate IN ('rdfs:label','owl:deprecated')"
                ):
                    if identifier not in classes:
                        continue
                    if predicate == "rdfs:label":
                        if not isinstance(value, str) or not value.strip():
                            continue
                        if any(character in value for character in "\t\r\n\x00"):
                            raise ValueError(f"Invalid BTO source label: {identifier}")
                        if identifier in labels and labels[identifier] != value:
                            raise ValueError(f"Conflicting BTO source labels: {identifier}")
                        labels[identifier] = value
                    else:
                        if value not in {"true", "false", "1", "0"}:
                            raise ValueError(f"Invalid BTO deprecation flag: {identifier}")
                        flag = value in {"true", "1"}
                        if identifier in deprecated and deprecated[identifier] != flag:
                            raise ValueError(f"Conflicting BTO deprecation flags: {identifier}")
                        deprecated[identifier] = flag
                versions = sorted(
                    {
                        row[0]
                        for row in connection.execute(
                            "SELECT object FROM statements WHERE subject='obo:bto.owl' AND predicate='owl:versionIRI'"
                        )
                        if row[0]
                    }
                )
                if len(versions) > 1:
                    raise ValueError("Conflicting BTO source versions")
    return (
        {
            identifier: {"name": labels.get(identifier, ""), "deprecated": deprecated.get(identifier, False)}
            for identifier in classes
        },
        versions[0] if versions else "",
    )
