"""
Load reviewed local process meanings without asserting ontology identity.

The source version identifies the reviewed vocabulary, not a demonstrated build
of the saved organism assignment CSV. Original prediction provenance is separate
and must be retained by consumers. This module never fetches or rewrites inputs.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
from dataclasses import dataclass, fields
from pathlib import Path
from urllib.parse import urlsplit

from kg_microbe.transform_utils.constants import MICROBEDECODER, PATHWAY_PREFIX
from kg_microbe.transform_utils.microbedecoder.curation import TextInput, _read_input
from kg_microbe.transform_utils.microbedecoder.source_annotations import is_reported_metabolism_annotation
from kg_microbe.transform_utils.microbedecoder.utils import slugify_label

DEFAULT_PROCESS_SCOPE_DEFINITIONS = (
    Path(__file__).resolve().parents[3] / "mappings" / "canonical" / "microbedecoder_process_scope_definitions.tsv"
)


@dataclass(frozen=True)
class ProcessScope:
    """One field-scoped local process definition and its reviewed source witness."""

    source_column: str
    source_literal: str
    scope_definition: str
    evidence_uri: str
    source_version: str
    archive_sha256: str
    member_sha256: str
    source_first_line: str

    @property
    def curie(self) -> str:
        """Identify one exact source-column/literal meaning without global slug collisions."""
        identity = json.dumps(
            [MICROBEDECODER, self.source_column, self.source_literal], ensure_ascii=False, separators=(",", ":")
        )
        digest = hashlib.sha256(identity.encode("utf-8", errors="surrogateescape")).hexdigest()
        return f"{PATHWAY_PREFIX}{MICROBEDECODER}_{slugify_label(self.source_column)}_{digest}"

    @property
    def description(self) -> str:
        """Keep semantic-review evidence distinct from organism assignment evidence."""
        return (
            f"Reviewed source-local process meaning for {self.source_column}={self.source_literal}: "
            f"{self.scope_definition} "
            "This is not an ontology identity mapping or independent confirmation of an organism prediction. "
            f"Reviewed vocabulary: {self.source_version}; evidence: {self.evidence_uri}; "
            f"archive SHA-256: {self.archive_sha256}; member SHA-256: {self.member_sha256}; "
            f"source first line: {self.source_first_line}. "
            "The reviewed vocabulary version does not establish the generating version of the saved organism CSV."
        )


class ProcessScopeCuration:
    """Validate the complete finite table; fail closed instead of dropping bad rows."""

    def __init__(self, definitions_input: TextInput = DEFAULT_PROCESS_SCOPE_DEFINITIONS) -> None:
        """Read each supplied snapshot anew and preserve ownership of open streams."""
        self._rules = self._load_rules(definitions_input)

    @property
    def rules(self) -> tuple[ProcessScope, ...]:
        """Expose immutable declarations for cross-policy conflict validation."""
        return tuple(self._rules.values())

    def resolve(self, source_column: str, literal: str) -> ProcessScope | None:
        """Match the exact source field and token without additional normalization."""
        return self._rules.get((source_column, literal))

    @staticmethod
    def _load_rules(definitions_input: TextInput) -> dict[tuple[str, str], ProcessScope]:
        expected = {field.name for field in fields(ProcessScope)}
        rules = {}
        with _read_input(definitions_input) as stream:
            reader = csv.DictReader(stream, delimiter="\t", quoting=csv.QUOTE_NONE)
            header = reader.fieldnames or []
            if len(header) != len(expected) or set(header) != expected:
                raise ValueError("Invalid MicrobeDecoder process scope columns")
            for line_number, row in enumerate(reader, start=2):
                location = f"process scope line {line_number}"
                if None in row or any(
                    value is None or not value or value != value.strip() or any(ord(char) < 32 for char in value)
                    for value in row.values()
                ):
                    raise ValueError(f"Incomplete or malformed process scope at {location}")
                rule = ProcessScope(**row)
                if rule.source_column != "FAPROTAX_Type_of_metabolism":
                    raise ValueError(f"Invalid process scope source column at {location}")
                if is_reported_metabolism_annotation(rule.source_column, rule.source_literal):
                    raise ValueError(f"Non-process source annotation cannot have a process scope at {location}")
                if not re.fullmatch(r"FAPROTAX_[1-9][0-9]*\.[0-9]+\.[0-9]+", rule.source_version):
                    raise ValueError(f"Invalid process scope source version at {location}")
                if not all(re.fullmatch(r"[0-9a-f]{64}", value) for value in (rule.archive_sha256, rule.member_sha256)):
                    raise ValueError(f"Invalid process scope evidence SHA-256 at {location}")
                if not re.fullmatch(r"[1-9][0-9]*", rule.source_first_line):
                    raise ValueError(f"Invalid process scope source line at {location}")
                for reference in rule.evidence_uri.split("|"):
                    parsed = urlsplit(reference)
                    if (
                        parsed.scheme != "https"
                        or not parsed.netloc
                        or not parsed.hostname
                        or parsed.username is not None
                        or parsed.password is not None
                        or any(char.isspace() for char in reference)
                    ):
                        raise ValueError(f"Invalid process scope evidence URI at {location}")
                key = (rule.source_column, rule.source_literal)
                if key in rules:
                    raise ValueError(f"Duplicate or conflicting process scope for {key!r} at {location}")
                rules[key] = rule
        if not rules:
            raise ValueError("No MicrobeDecoder process scope definitions")
        return rules
