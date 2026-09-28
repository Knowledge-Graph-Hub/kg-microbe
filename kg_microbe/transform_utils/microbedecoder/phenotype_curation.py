"""
Resolve reviewed literal phenotypes for a non-graph normalization report.

Rules are exact source-column/literal normalizations, not global synonyms or
independent organism observations. The producer retains source attributes and
their original provenance tier. These rules do not authorize phenotype edges:
native endpoint categories do not satisfy the pinned has-phenotype signature.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, fields
from pathlib import Path
from urllib.parse import urlsplit

from kg_microbe.transform_utils.constants import (
    CATEGORY_COLUMN,
    DEPRECATED_COLUMN,
    ID_COLUMN,
    NAME_COLUMN,
)
from kg_microbe.transform_utils.microbedecoder.curation import TextInput, _read_input

DEFAULT_PHENOTYPE_MAPPINGS = (
    Path(__file__).resolve().parents[3] / "mappings" / "canonical" / "microbedecoder_phenotype_mappings.tsv"
)

# Only fields whose explicit textual meanings were reviewed in this cohort.
_SOURCE_COLUMNS = frozenset({"BacDive_Gram_stain", "BacDive_Cell_shape", "BacDive_Oxygen_tolerance"})


@dataclass(frozen=True)
class PhenotypeMapping:
    """Keep exact normalization evidence separate from the original observation."""

    source_column: str
    source_literal: str
    target_curie: str
    target_label: str
    target_category: str
    evidence_uri: str
    curation_rationale: str


class PhenotypeCuration:
    """
    Validate reviewed rules against the supplied native ontology declarations.

    The rules use the ontology owner's exported category without creating or
    retyping nodes. Their phenotype meaning and field-specific synonym provenance
    were reviewed against the pinned native ontology, not inferred from a label.
    """

    def __init__(self, mapping_input: TextInput, metpo_nodes_input: TextInput) -> None:
        """Validate both consumed inputs anew and fail closed on incompatible data."""
        self._rules = self._load_rules(mapping_input)
        self._validate_targets(metpo_nodes_input)

    def resolve(self, source_column: str, literal: str) -> PhenotypeMapping | None:
        """Resolve an exact field and literal without case, sign or value coercion."""
        return self._rules.get((source_column, literal))

    @staticmethod
    def _load_rules(mapping_input: TextInput) -> dict[tuple[str, str], PhenotypeMapping]:
        """Reject malformed rules and unreviewed field or predicate scopes."""
        expected_fields = {field.name for field in fields(PhenotypeMapping)}
        rules = {}
        with _read_input(mapping_input) as stream:
            reader = csv.DictReader(stream, delimiter="\t", quoting=csv.QUOTE_NONE)
            header = reader.fieldnames or []
            if len(header) != len(expected_fields) or set(header) != expected_fields:
                raise ValueError("Invalid MicrobeDecoder phenotype mapping columns")
            for line_number, row in enumerate(reader, start=2):
                location = f"phenotype mapping line {line_number}"
                if None in row or any(value is None or not value or value != value.strip() for value in row.values()):
                    raise ValueError(f"Incomplete or malformed phenotype mapping at {location}")
                rule = PhenotypeMapping(**row)
                if rule.source_column not in _SOURCE_COLUMNS:
                    raise ValueError(f"Invalid phenotype source column scope at {location}")
                if not re.fullmatch(r"METPO:1\d{6}", rule.target_curie):
                    raise ValueError(f"Expected a METPO class target at {location}")
                for reference in rule.evidence_uri.split("|"):
                    parsed = urlsplit(reference)
                    if parsed.scheme != "https" or not parsed.netloc or any(char.isspace() for char in reference):
                        raise ValueError(f"Invalid curation evidence URI at {location}")
                key = (rule.source_column, rule.source_literal)
                if key in rules:
                    raise ValueError(f"Duplicate or conflicting phenotype mapping for {key!r} at {location}")
                rules[key] = rule
        if not rules:
            raise ValueError("No MicrobeDecoder phenotype mappings")
        return rules

    def _validate_targets(self, metpo_nodes_input: TextInput) -> None:
        """Require a unique active authoritative declaration for each reviewed target."""
        expected = {}
        for rule in self._rules.values():
            declaration = (rule.target_label, rule.target_category)
            if rule.target_curie in expected and expected[rule.target_curie] != declaration:
                raise ValueError(f"Conflicting expected METPO declaration for {rule.target_curie}")
            expected[rule.target_curie] = declaration
        found = set()
        with _read_input(metpo_nodes_input) as stream:
            reader = csv.DictReader(stream, delimiter="\t", quoting=csv.QUOTE_NONE)
            header = reader.fieldnames or []
            required = {ID_COLUMN, NAME_COLUMN, CATEGORY_COLUMN, DEPRECATED_COLUMN}
            if not required.issubset(header) or len(header) != len(set(header)):
                raise ValueError("Missing or duplicate METPO declaration columns")
            for row in reader:
                curie = row[ID_COLUMN]
                if curie not in expected:
                    continue
                if curie in found:
                    raise ValueError(f"Duplicate METPO target declaration for {curie}")
                if None in row or any(row.get(column) is None for column in required):
                    raise ValueError(f"Malformed METPO target declaration for {curie}")
                if (row[NAME_COLUMN], row[CATEGORY_COLUMN]) != expected[curie]:
                    raise ValueError(f"Unexpected METPO target label/category for {curie}")
                if row[DEPRECATED_COLUMN].strip().lower() not in {"", "false", "0"}:
                    raise ValueError(f"Deprecated or invalid METPO target status for {curie}")
                found.add(curie)
        missing = sorted(set(expected) - found)
        if missing:
            raise ValueError(f"Missing authoritative METPO targets: {', '.join(missing)}")
