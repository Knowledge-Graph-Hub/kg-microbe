"""A completed ontologies output, for tests of the sources that declare it (#1511, #1554)."""

import hashlib
import json
from pathlib import Path

from kg_microbe.utils.source_finalization import FINALIZATION_FILE, FINALIZATION_VERSION
from kg_microbe.utils.transform_fingerprint import FINGERPRINT_FILE


def write_completed_ontologies_output(directory: Path, nodes: str, name: str = "chebi_nodes.tsv") -> Path:
    """
    Write one ontology node file with the whole-source record and marker a completed run leaves.

    The record lists the file with its exact bytes, which is what finalization
    checks before it reads another source's declarations. It is not a real
    ontology build: tests that need the merge gate to accept the upstream build
    one with ``prepare_source(tmp_path, "ontologies")`` instead.

    :param directory: The ontologies output directory.
    :param nodes: The node file's TSV text, header included.
    :param name: The node file's name.
    :return: The node file.
    """
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(nodes, encoding="utf-8")
    member = {"bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    record = {"version": FINALIZATION_VERSION, "members": {name: member}}
    (directory / FINALIZATION_FILE).write_text(json.dumps(record), encoding="utf-8")
    (directory / FINGERPRINT_FILE).write_text("{}", encoding="utf-8")
    return path
