"""
Resolve reviewed MicrobeDecoder process terms within their source field.

These rules normalize an existing source assertion; they neither establish an
independent organism-level observation nor provide global lexical synonyms.
Authoritative METPO and GO declarations remain owned by the ontology transform.
"""

from __future__ import annotations

import csv
import re
from contextlib import nullcontext
from dataclasses import dataclass, fields
from pathlib import Path
from typing import TextIO
from urllib.parse import urlsplit

from kg_microbe.transform_utils.constants import (
    BIOLOGICAL_PROCESS_CATEGORY,
    CAPABLE_OF,
    CAPABLE_OF_PREDICATE,
    CATEGORY_COLUMN,
    COMPUTATIONAL_MODEL,
    DEPRECATED_COLUMN,
    ID_COLUMN,
    KNOWLEDGE_ASSERTION,
    MANUAL_AGENT,
    NAME_COLUMN,
    PREDICTION,
)
from kg_microbe.transform_utils.microbedecoder.source_annotations import is_reported_metabolism_annotation
from kg_microbe.transform_utils.microbedecoder.utils import METABOLISM_GROUPS

DEFAULT_PROCESS_MAPPINGS = (
    Path(__file__).resolve().parents[3] / "mappings" / "canonical" / "microbedecoder_process_mappings.tsv"
)

# Bind the transform's internal role keys to the actual raw source columns.
# Other roles and the independent FAPROTAX2 vocabulary are outside this review.
_SOURCE_COLUMNS = {
    f"{group['group_label']}:type_of_metabolism": group["columns"]["type_of_metabolism"] for group in METABOLISM_GROUPS
}

TextInput = str | Path | TextIO


def _read_input(source: TextInput):
    """Keep caller-owned fingerprinting streams open for their owning context."""
    if hasattr(source, "read"):
        return nullcontext(source)
    return Path(source).open(encoding="utf-8", newline="")


@dataclass(frozen=True)
class ProcessMapping:
    """Retain one exact source-term rule and its separate curation evidence."""

    source_key: str
    source_column: str
    source_literal: str
    target_curie: str
    target_label: str
    target_category: str
    predicate: str
    relation: str
    knowledge_level: str
    agent_type: str
    evidence_type: str
    evidence_uri: str
    curation_rationale: str


class ProcessCuration:
    """
    Load exact rules and fail closed against the supplied ontology export.

    Both METPO and GO rules require ontology-owned
    ``biolink:BiologicalProcess`` declarations. Reviewed definitions support
    process meaning, not a source-created stub or category override. Missing
    declarations, changed labels/categories and deprecated targets require a
    reviewed update before these rules can run.
    """

    def __init__(
        self, mapping_input: TextInput, metpo_nodes_input: TextInput, go_nodes_input: TextInput | None = None
    ) -> None:
        """Validate fresh snapshots; require GO authority when a rule targets GO."""
        self._rules = self._load_rules(mapping_input)
        self._validate_targets(metpo_nodes_input, "METPO")
        if any(rule.target_curie.startswith("GO:") for rule in self._rules.values()):
            if go_nodes_input is None:
                raise ValueError("Missing authoritative GO input for GO process mappings")
            self._validate_targets(go_nodes_input, "GO")

    def resolve(self, source_key: str, literal: str) -> ProcessMapping | None:
        """Resolve only the exact role key and literal, without normalization."""
        return self._rules.get((source_key, literal))

    @staticmethod
    def _load_rules(mapping_input: TextInput) -> dict[tuple[str, str], ProcessMapping]:
        """Reject malformed, incomplete, duplicate and conflicting rule rows."""
        rules = {}
        expected_fields = {field.name for field in fields(ProcessMapping)}
        with _read_input(mapping_input) as stream:
            reader = csv.DictReader(stream, delimiter="\t", quoting=csv.QUOTE_NONE)
            header = reader.fieldnames or []
            if len(header) != len(expected_fields) or set(header) != expected_fields:
                raise ValueError("Invalid MicrobeDecoder process mapping columns")
            for line_number, row in enumerate(reader, start=2):
                location = f"process mapping line {line_number}"
                if None in row or any(value is None or not value or value != value.strip() for value in row.values()):
                    raise ValueError(f"Incomplete or malformed process mapping at {location}")
                rule = ProcessMapping(**row)
                if _SOURCE_COLUMNS.get(rule.source_key) != rule.source_column:
                    raise ValueError(f"Invalid source column/role scope at {location}")
                if is_reported_metabolism_annotation(rule.source_column, rule.source_literal):
                    raise ValueError(f"Non-process source annotation cannot be a process mapping at {location}")
                if not re.fullmatch(r"(?:METPO:1\d{6}|GO:\d{7})", rule.target_curie):
                    raise ValueError(f"Expected a METPO class or GO class target at {location}")
                if rule.target_category != BIOLOGICAL_PROCESS_CATEGORY:
                    raise ValueError(
                        f"Expected a {rule.target_curie.split(':')[0]} biological process target at {location}"
                    )
                if rule.predicate != CAPABLE_OF_PREDICATE or rule.relation != CAPABLE_OF:
                    raise ValueError(f"Invalid process predicate/relation at {location}")
                predicted = rule.source_key == "faprotax:type_of_metabolism"
                expected_provenance = (
                    (PREDICTION, COMPUTATIONAL_MODEL) if predicted else (KNOWLEDGE_ASSERTION, MANUAL_AGENT)
                )
                if (rule.knowledge_level, rule.agent_type) != expected_provenance:
                    raise ValueError(f"Invalid source evidence provenance at {location}")
                if rule.evidence_type != "source_term_normalization":
                    raise ValueError(f"Invalid curation evidence type at {location}")
                for reference in rule.evidence_uri.split("|"):
                    parsed = urlsplit(reference)
                    if parsed.scheme != "https" or not parsed.netloc or any(char.isspace() for char in reference):
                        raise ValueError(f"Invalid curation evidence URI at {location}")
                key = (rule.source_key, rule.source_literal)
                if key in rules:
                    raise ValueError(f"Duplicate or conflicting process mapping for {key!r} at {location}")
                rules[key] = rule
        if not rules:
            raise ValueError("No MicrobeDecoder process mappings")
        return rules

    def _validate_targets(self, nodes_input: TextInput, ontology: str) -> None:
        """Stream authoritative nodes and require one consistent active declaration."""
        expected = {}
        for rule in self._rules.values():
            if not rule.target_curie.startswith(f"{ontology}:"):
                continue
            declaration = (rule.target_label, rule.target_category)
            if rule.target_curie in expected and expected[rule.target_curie] != declaration:
                raise ValueError(f"Conflicting expected {ontology} declaration for {rule.target_curie}")
            expected[rule.target_curie] = declaration
        found = set()
        with _read_input(nodes_input) as stream:
            reader = csv.DictReader(stream, delimiter="\t", quoting=csv.QUOTE_NONE)
            header = reader.fieldnames or []
            required = {ID_COLUMN, NAME_COLUMN, CATEGORY_COLUMN, DEPRECATED_COLUMN}
            if not required.issubset(header) or len(header) != len(set(header)):
                raise ValueError(f"Missing or duplicate {ontology} declaration columns")
            for row in reader:
                curie = row[ID_COLUMN]
                if curie not in expected:
                    continue
                if curie in found:
                    raise ValueError(f"Duplicate {ontology} target declaration for {curie}")
                if None in row or any(row.get(column) is None for column in required):
                    raise ValueError(f"Malformed {ontology} target declaration for {curie}")
                if (row[NAME_COLUMN], row[CATEGORY_COLUMN]) != expected[curie]:
                    raise ValueError(f"Unexpected {ontology} target label/category for {curie}")
                if row[DEPRECATED_COLUMN].strip().lower() not in {"", "false", "0"}:
                    raise ValueError(f"Deprecated or invalid {ontology} target status for {curie}")
                found.add(curie)
        missing = sorted(set(expected) - found)
        if missing:
            raise ValueError(f"Missing authoritative {ontology} targets: {', '.join(missing)}")
