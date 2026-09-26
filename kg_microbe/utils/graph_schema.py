"""One published KGX TSV schema shared by source finalization and merge serialization."""

import csv
from pathlib import Path

from kg_microbe.transform_utils.constants import (
    AGENT_TYPE_COLUMN,
    CATEGORY_COLUMN,
    DEPRECATED_COLUMN,
    DESCRIPTION_COLUMN,
    ID_COLUMN,
    KNOWLEDGE_LEVEL_COLUMN,
    NAME_COLUMN,
    OBJECT_COLUMN,
    PREDICATE_COLUMN,
    PRIMARY_KNOWLEDGE_SOURCE_COLUMN,
    PROVIDED_BY_COLUMN,
    PUBLICATIONS_COLUMN,
    RELATION_COLUMN,
    SAME_AS_COLUMN,
    SUBJECT_COLUMN,
    SYNONYM_COLUMN,
    XREF_COLUMN,
)
from kg_microbe.utils.ingredient_kgx import validate_ingredient_fields
from kg_microbe.utils.provenance import validate_primary_source_and_publications

CANONICAL_NODE_HEADER = [
    ID_COLUMN,
    CATEGORY_COLUMN,
    NAME_COLUMN,
    DESCRIPTION_COLUMN,
    XREF_COLUMN,
    PROVIDED_BY_COLUMN,
    SYNONYM_COLUMN,
    DEPRECATED_COLUMN,
    SAME_AS_COLUMN,
]
CANONICAL_EDGE_HEADER = [
    SUBJECT_COLUMN,
    PREDICATE_COLUMN,
    OBJECT_COLUMN,
    RELATION_COLUMN,
    PRIMARY_KNOWLEDGE_SOURCE_COLUMN,
    KNOWLEDGE_LEVEL_COLUMN,
    AGENT_TYPE_COLUMN,
]
REQUIRED_NODE_COLUMNS = {ID_COLUMN, CATEGORY_COLUMN, NAME_COLUMN, DESCRIPTION_COLUMN, PROVIDED_BY_COLUMN}
REQUIRED_EDGE_COLUMNS = set(CANONICAL_EDGE_HEADER)
FORBIDDEN_EDGE_COLUMNS = {ID_COLUMN, "key", "knowledge_source"}


def canonical_header(header, is_node):
    """Order required and present optional columns, retaining all extensions deterministically."""
    canonical = CANONICAL_NODE_HEADER if is_node else CANONICAL_EDGE_HEADER
    required = REQUIRED_NODE_COLUMNS if is_node else REQUIRED_EDGE_COLUMNS
    columns = set(header) | required
    if any(
        not isinstance(column, str) or not column or any(char in column for char in "\t\r\n\x00") for column in columns
    ):
        raise ValueError("Missing or malformed graph column name")
    return [column for column in canonical if column in columns] + sorted(columns - set(canonical))


def validate_canonical_tsv(path, *, is_node):
    """Stream a literal LF TSV contract without changing headers, values, or provenance."""
    count = 0
    with Path(path).open(encoding="utf-8", newline="") as stream:

        def lines():
            """Reject transport defects rather than rewriting finalized graph bytes."""
            for line in stream:
                if "\x00" in line:
                    raise ValueError(f"{path}: NUL bytes are forbidden in canonical TSV records")
                if "\r" in line or not line.endswith("\n"):
                    raise ValueError(f"{path}: canonical TSV requires LF-terminated records without carriage returns")
                yield line

        reader = csv.reader(lines(), delimiter="\t", quoting=csv.QUOTE_NONE)
        header = next(reader, [])
        if not header or len(header) != len(set(header)) or header != canonical_header(header, is_node):
            raise ValueError(f"{path}: missing, duplicate, or noncanonical TSV header")
        if not is_node and FORBIDDEN_EDGE_COLUMNS.intersection(header):
            raise ValueError(f"{path}: legacy/internal edge columns require source finalization")
        ingredient_fields = any(column.startswith("ingredient_") for column in header)
        for line, values in enumerate(reader, 2):
            if len(values) != len(header):
                raise ValueError(f"{path}:{line}: malformed TSV field count")
            row = dict(zip(header, values, strict=True))
            if ingredient_fields:
                validate_ingredient_fields(row, is_node=is_node)
            identity = (ID_COLUMN,) if is_node else (SUBJECT_COLUMN, PREDICATE_COLUMN, OBJECT_COLUMN)
            if any(not row[column] for column in identity):
                raise ValueError(f"{path}:{line}: empty graph identity")
            if not is_node:
                validate_primary_source_and_publications(
                    row[PRIMARY_KNOWLEDGE_SOURCE_COLUMN], row.get(PUBLICATIONS_COLUMN)
                )
            count += 1
    return count
