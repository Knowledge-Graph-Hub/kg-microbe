"""
Separate scalar information-resource provenance from public record evidence.

Biolink 4.4.2 explicitly includes public web pages in ``publications``. BacDive
record pages belong there, while ``primary_knowledge_source`` remains a single
information resource. Legacy source/record list and pipe cells are migrated
without inventing a new primary provider or duplicating ambiguous evidence.
"""

import ast

from kg_microbe.transform_utils.constants import BACDIVE_PREFIX

RESOURCE_ALIASES = {
    "MediaDive": "infores:mediadive",
    "mediadive": "infores:mediadive",
    "bacdive": "infores:bacdive",
    "chebi.json": "infores:chebi",
    "ncbitaxon_removed_subset.json": "infores:ncbitaxon",
    "ncbitaxon.json": "infores:ncbitaxon",
    "ec.json": "infores:ec",
    "envo.json": "infores:envo",
    "go.json": "infores:go",
    "upa.json": "infores:upa",
    "metpo.json": "infores:metpo",
    "uberon.json": "infores:uberon",
    "foodon.json": "infores:foodon",
    "pato.json": "infores:pato",
    "hp.json": "infores:hp",
    "mondo.json": "infores:mondo",
    "ro.json": "infores:ro",
    "taxrank.json": "infores:taxrank",
}


def bacdive_record_url(record_id: str) -> str:
    """Return the public evidence page for a numeric BacDive record or its CURIE."""
    identifier = str(record_id).removeprefix(BACDIVE_PREFIX)
    if not identifier.isdigit():
        raise ValueError(f"Not a BacDive record identifier: {record_id!r}")
    return f"https://bacdive.dsmz.de/strain/{identifier}"


def primary_source_and_publications(value, publications=None):
    """Migrate unambiguous legacy BacDive attribution; refuse pooled primary providers."""
    if isinstance(value, str) and value.strip().startswith("["):
        try:
            parsed = ast.literal_eval(value)
        except (SyntaxError, ValueError) as error:
            raise ValueError("Malformed primary-source list; rebuild from unmerged source TSVs") from error
        if not isinstance(parsed, list) or not all(isinstance(item, str) for item in parsed):
            raise ValueError("Primary-source lists must contain only source/record identifier strings")
        value = parsed
    tokens = knowledge_source_tokens(value)
    records = [token for token in tokens if token.startswith(BACDIVE_PREFIX)]
    resources = [token for token in tokens if token not in records]
    # These are existing, unambiguous producer aliases, not inferred providers.
    resources = knowledge_source_tokens([RESOURCE_ALIASES.get(token, token) for token in resources])
    if records and not resources:
        resources = ["infores:bacdive"]
    if len(resources) > 1:
        raise ValueError(
            f"Multiple primary information resources {resources!r}; rebuild from unmerged source TSVs "
            "to retain each provider's observation and evidence pairing"
        )
    if resources and not resources[0].startswith(("infores:", "http://", "https://")):
        raise ValueError(f"Primary knowledge source must identify an information resource: {resources[0]!r}")
    evidence = knowledge_source_tokens([publications, [bacdive_record_url(record) for record in records]])
    return (resources[0] if resources else ""), evidence


def validate_primary_source_and_publications(value, publications=None):
    """Validate canonical provider/evidence identity; permit only KGX collection representation."""
    if isinstance(value, (list, tuple)):
        if len(value) != 1:
            raise ValueError("Canonical primary knowledge source requires exactly one provider")
        value = value[0]
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or "|" in value
        or not value.startswith(("infores:", "http://", "https://"))
        or any(control in value for control in "\t\r\n\x00")
        or value in {"infores:", "http://", "https://"}
    ):
        raise ValueError(f"Noncanonical primary knowledge source {value!r}; rerun source finalization")
    if publications is None or publications == "" or publications == []:
        return value, []
    evidence = publications.split("|") if isinstance(publications, str) else publications
    if not isinstance(evidence, (list, tuple)) or any(
        not isinstance(item, str)
        or not item
        or item != item.strip()
        or any(control in item for control in "|\t\r\n\x00")
        for item in evidence
    ):
        raise ValueError("Noncanonical publication evidence; rerun source finalization")
    if len(evidence) != len(set(evidence)):
        raise ValueError("Duplicate publication evidence requires source finalization")
    return value, list(evidence)


def knowledge_source_tokens(value, delimiter: str = "|") -> list[str]:
    """Flatten collections and pipe tokens, keeping first occurrence order."""
    values = value if isinstance(value, (list, tuple, set)) else [value]
    tokens = []
    for item in values:
        if item is None:
            continue
        if isinstance(item, (list, tuple, set)):
            parts = knowledge_source_tokens(item, delimiter)
        else:
            parts = [part.strip() for part in str(item).split(delimiter) if part.strip()]
        for part in parts:
            if part not in tokens:
                tokens.append(part)
    return tokens


def serialize_knowledge_sources(*values, delimiter: str = "|") -> str:
    """Serialize explicitly multivalued provenance or publication tokens, never scalar PKS."""
    return delimiter.join(knowledge_source_tokens(values, delimiter))
