"""Evidence-backed ontology metadata matching, without rewriting entity identifiers."""

from kg_microbe.utils.graph_canonicalization import compact_identifier

OBO_BASE = "http://purl.obolibrary.org/obo/"


def metadata_identifier(identifier: str) -> str:
    """
    Compare KGX's generic OBO CURIE with its exact authority IRI.

    The local entity registry deliberately has no generic OBO namespace.
    KGX nevertheless emits OBO:chebi/BRAND_NAME for the annotation property's
    IRI. Expand that representation only for metadata membership tests: this
    is neither an OBO namespace exclusion nor a graph identifier migration.
    """
    if identifier.startswith("OBO:"):
        identifier = OBO_BASE + identifier[len("OBO:") :]
    return compact_identifier(identifier)


def metadata_declaration_ids(nodes) -> tuple[set[str], set[str]]:
    """
    Collect explicit annotation and semantic declarations without discarding either.

    Inspect all declarations, including imports and other graphs. An explicit
    class, individual, object-property or data-property declaration protects
    the same identifier. Untyped reader stubs supply no contrary evidence.
    No labels, spelling patterns or biolink fallback categories are evidence.
    """
    annotations, entities = set(), set()
    for node in nodes:
        identifier = node.get("id")
        if not identifier:
            continue
        identifier = metadata_identifier(identifier)
        if node.get("type") == "PROPERTY" and node.get("propertyType") == "ANNOTATION":
            annotations.add(identifier)
        elif node.get("type") in {"CLASS", "INDIVIDUAL"} or (
            node.get("type") == "PROPERTY" and node.get("propertyType") in {"OBJECT", "DATA"}
        ):
            entities.add(identifier)
    return annotations, entities


def annotation_property_ids(nodes) -> set[str]:
    """Exclude only explicit annotation properties without an explicit semantic declaration."""
    annotations, entities = metadata_declaration_ids(nodes)
    return annotations - entities


def is_chebi_metadata_identifier(identifier: str) -> bool:
    """Select a bounded authority lookup, not an exclusion based on spelling."""
    identifier = metadata_identifier(identifier)
    return identifier.startswith((OBO_BASE + "chebi/", OBO_BASE + "chebi#"))


def obograph_is_deprecated(node) -> bool:
    """Read both explicit obsolete encodings without accepting malformed or conflicting flags."""
    identifier = node.get("id", "")
    meta = node.get("meta", {})
    flags = set()
    if "deprecated" in meta:
        deprecated = meta["deprecated"]
        if type(deprecated) is not bool:
            raise ValueError(f"Malformed obsolete flag for {identifier}")
        flags.add(deprecated)
    for annotation in meta.get("basicPropertyValues", []):
        if metadata_identifier(annotation.get("pred", "")) != "owl:deprecated":
            continue
        value = str(annotation.get("val", "")).strip().lower()
        if value not in {"true", "false", "1", "0"}:
            raise ValueError(f"Malformed obsolete flag for {identifier}")
        flags.add(value in {"true", "1"})
    if len(flags) > 1:
        raise ValueError(f"Conflicting obsolete flags for {identifier}")
    return True in flags


def reviewed_foodon_schema_property_ids(nodes, *, reviewed_ids=None) -> set[str]:
    """Exclude only reviewed native object-property declarations without entity punning."""
    if reviewed_ids is None:
        from kg_microbe.utils.foodon_classification import foodon_dispositions

        reviewed_ids = {
            identifier
            for identifier, row in foodon_dispositions().items()
            if row["disposition"] == "schema_object_property"
        }
    properties, protected = set(), set()
    for node in nodes:
        identifier = metadata_identifier(node.get("id", ""))
        if identifier not in reviewed_ids:
            continue
        if obograph_is_deprecated(node):
            protected.add(identifier)
        if node.get("type") in {"CLASS", "INDIVIDUAL"}:
            protected.add(identifier)
        elif node.get("type") == "PROPERTY" and node.get("propertyType") == "OBJECT":
            properties.add(identifier)
    return properties - protected
