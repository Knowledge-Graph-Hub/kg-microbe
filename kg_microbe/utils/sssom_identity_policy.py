"""Route SSSOM rows before they can contribute chemical identity lookups."""

from collections.abc import Mapping

from kg_microbe.utils.ingredient_scope import validate_scope_row

_ANNOTATION_PREDICATES = frozenset({"oboInOwl:hasDbXref", "biolink:xref", "rdfs:seeAlso"})


def classify_mapping_row(row: Mapping[str, str], metadata: dict | None = None) -> tuple[str, str]:
    """
    Return an explicit consumer route and a diagnostic reason for a row.

    The legacy unified format has two lexical row shapes and a separately
    tagged recipe-equivalent hydrate relation. Neither exception authorizes
    arbitrary closeMatch rows to enter the identity xref index.
    """
    subject = (row.get("subject_id") or "").strip()
    predicate = (row.get("predicate_id") or "").strip()
    target = (row.get("object_id") or "").strip()
    comment = (row.get("comment") or "").strip()
    if not subject or not target or not predicate:
        return "quarantined", "missing_subject_predicate_or_object"
    if (row.get("predicate_modifier") or "").strip():
        return "quarantined", "unsupported_predicate_modifier"
    try:
        authorized = validate_scope_row(row, metadata or {})
    except ValueError as error:
        return "quarantined", str(error)
    if authorized is not None:
        if row.get("ext_scope_review_status") != "SUPPORTED":
            return "quarantined", "scope_review_not_supported"
        if not authorized and (predicate == "skos:exactMatch" or subject.startswith("kgm.name:")):
            return "nonidentity", "identity_not_authorized"
    if predicate in {"skos:broadMatch", "skos:narrowMatch"}:
        return "broader", ""
    if predicate in _ANNOTATION_PREDICATES:
        return "annotation", ""
    if subject.startswith("kgm.name:"):
        if predicate == "skos:exactMatch" and comment == "canonical_name":
            return "canonical_name", ""
        if predicate in {"skos:exactMatch", "skos:closeMatch"} and comment == "synonym":
            return "synonym", ""
        return "quarantined", "unsupported_lexical_row"
    if predicate == "skos:exactMatch":
        return ("attribute" if subject == target else "identity"), ""
    if predicate == "skos:closeMatch" and comment == "recipe_equivalent_hydrate":
        if subject.startswith("CHEBI:") and target.startswith("CHEBI:") and subject != target:
            return "hydrate", ""
        return "quarantined", "invalid_recipe_equivalent_hydrate"
    if predicate in {"skos:closeMatch", "skos:relatedMatch"}:
        return "nonidentity", ""
    return "quarantined", "unsupported_predicate"
