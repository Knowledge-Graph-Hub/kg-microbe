"""The release merger consumes finalized TSVs; it is not another transform stage."""

from kg_microbe.merge_utils.stats_provenance import STATS_OPERATION

# Empty legacy template placeholders are harmless, but active remapping or
# filtering belongs in a producer, with its source audit and fingerprint.
_TRANSFORM_OPTIONS = {
    "prefix_map",
    "reverse_prefix_map",
    "predicate_mappings",
    "reverse_predicate_mappings",
    "reverse_predicate_mapping",
    "node_property_predicates",
    "node_properties",
    "edge_properties",
    "curie_map",
    "property_types",
    "filters",
    "node_filters",
    "edge_filters",
}


def _no_transform_options(value, location):
    """Reject even currently ignored transform options instead of silently accepting them."""
    for key in _TRANSFORM_OPTIONS & value.keys():
        if value[key] not in (None, {}, []):
            raise ValueError(f"{location}.{key}: semantic editing belongs in upstream transforms, not merge")


def _operations(value, location, *, allow_stats=False):
    """Permit only the finite, read-only statistics operation at graph level."""
    operations = value.get("operations", [])
    if not isinstance(operations, list):
        raise ValueError(f"{location}.operations must be a list")
    for operation in operations:
        if (
            not allow_stats
            or not isinstance(operation, dict)
            or set(operation) != {"name", "args"}
            or operation["name"] != STATS_OPERATION
            or not isinstance(operation["args"], dict)
        ):
            raise ValueError(f"{location}.operations: only graph-level read-only statistics are allowed at merge")
        args = operation["args"]
        if not {"graph_name", "filename"} <= args.keys() or set(args) - {
            "graph_name",
            "filename",
            "node_facet_properties",
            "edge_facet_properties",
        }:
            raise ValueError(f"{location}.operations: unsupported statistics arguments")
        for key in ("graph_name", "filename"):
            if not isinstance(args[key], str) or not args[key].strip():
                raise ValueError(f"{location}.operations: statistics {key} must be a nonempty string")
        for key in ("node_facet_properties", "edge_facet_properties"):
            values = args.get(key)
            if values is not None and (
                not isinstance(values, list) or not all(isinstance(item, str) and item for item in values)
            ):
                raise ValueError(f"{location}.operations: statistics {key} must be a list of property names")


def validate_merge_semantics(config):
    """Fail before loading if a release configuration could transform source or merged rows."""
    configuration = config.get("configuration", {})
    graph = config["merged_graph"]
    if not isinstance(configuration, dict):
        raise ValueError("configuration must be a mapping")
    if configuration.get("checkpoint") not in (None, False):
        raise ValueError("configuration.checkpoint: release merges permit only staged destination outputs")
    _no_transform_options(configuration, "configuration")
    _operations(configuration, "configuration")
    _no_transform_options(graph, "merged_graph")
    _operations(graph, "merged_graph", allow_stats=True)
    sources = graph.get("source", {})
    if not isinstance(sources, dict):
        raise ValueError("merged_graph.source must be a mapping")
    for name, source in sources.items():
        location = f"merged_graph.source.{name}"
        if not isinstance(source, dict) or not isinstance(source.get("input"), dict):
            raise ValueError(f"{location}.input must be a mapping")
        _no_transform_options(source, location)
        _operations(source, location)
        inputs = source["input"]
        _no_transform_options(inputs, f"{location}.input")
        _operations(inputs, f"{location}.input")
        if inputs.get("format") != "tsv":
            raise ValueError(f"{location}.input.format: merge requires finalized TSVs, not another transform")
        unknown = set(inputs) - {"format", "filename", "compression", "operations"} - _TRANSFORM_OPTIONS
        if unknown:
            raise ValueError(f"{location}.input: unsupported overrides {sorted(unknown)}; finalize upstream")
    for name, destination in graph["destination"].items():
        _no_transform_options(destination, f"merged_graph.destination.{name}")
        _operations(destination, f"merged_graph.destination.{name}")
