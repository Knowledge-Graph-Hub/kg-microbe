"""
Relation-aware KGX ingestion without conflating independent source assertions (#1054).

Import this adapter only at the merge boundary. KGX constructs a BMT toolkit
while importing; configure its pinned local inputs first, including in spawned
workers. The top-level parser remains pickleable and captures the real KGX
parser before the caller temporarily replaces ``cli_utils.parse_source``.
"""

import copy
import csv
import hashlib
import json
from pathlib import Path
from threading import RLock

from kg_microbe.merge_utils.local_context import local_prefix_context
from kg_microbe.transform_utils.constants import (
    CATEGORY_COLUMN,
    DEPRECATED_COLUMN,
    ID_COLUMN,
    OBJECT_COLUMN,
    PREDICATE_COLUMN,
    PRIMARY_KNOWLEDGE_SOURCE_COLUMN,
    PROVIDED_BY_COLUMN,
    PUBLICATIONS_COLUMN,
    RELATION_COLUMN,
    SOURCE_ASSERTION_ID_COLUMN,
    SUBJECT_COLUMN,
)
from kg_microbe.utils.biolink_model import prepare_kgx
from kg_microbe.utils.graph_canonicalization import compact_identifier
from kg_microbe.utils.graph_schema import CANONICAL_EDGE_HEADER, CANONICAL_NODE_HEADER, canonical_header
from kg_microbe.utils.provenance import (
    knowledge_source_tokens,
    serialize_knowledge_sources,
    validate_primary_source_and_publications,
)
from kg_microbe.utils.source_finalization import (
    SourceFinalizationRequired,
    validate_identifier,
    validate_node_representation,
)
from kg_microbe.utils.tsv_io import tsv_writer

prepare_kgx()

from bmt import Toolkit  # noqa: E402
from kgx import transformer as transformer_module  # noqa: E402
from kgx.cli import cli_utils as cli_utils_module  # noqa: E402
from kgx.cli.cli_utils import parse_source as _kgx_parse_source  # noqa: E402
from kgx.graph_operations.graph_merge import add_all_nodes  # noqa: E402
from kgx.sink.graph_sink import GraphSink  # noqa: E402
from kgx.sink.sink import Sink  # noqa: E402
from kgx.sink.tsv_sink import TsvSink  # noqa: E402
from kgx.source.graph_source import GraphSource  # noqa: E402
from kgx.source.tsv_source import TsvSource  # noqa: E402
from kgx.transformer import Transformer  # noqa: E402
from kgx.utils.kgx_utils import (  # noqa: E402
    column_types,
    prepare_data_dict,
    sentencecase_to_snakecase,
)

# Consult the pinned schema plus KGX's explicit TSV list types, never the
# runtime value type or prepare_data_dict's "unknown means multivalued" rule.
# Unknown extension fields remain scalar. PKS is always scalar, as declared
# by the pinned model; source-record evidence belongs in publications.
_MULTIVALUED_EDGE_PROPERTIES = (
    {sentencecase_to_snakecase(slot) for slot in Toolkit().get_all_multivalued_slots()}
    | {column for column, value_type in column_types.items() if value_type is list}
) - {PRIMARY_KNOWLEDGE_SOURCE_COLUMN}
_MULTIVALUED_NODE_PROPERTIES = _MULTIVALUED_EDGE_PROPERTIES | {PRIMARY_KNOWLEDGE_SOURCE_COLUMN}
# The canonical node contract includes deprecated, which KGX omits from its
# Boolean column table. Empty source declarations are not Boolean assertions.
_BOOLEAN_NODE_PROPERTIES = {DEPRECATED_COLUMN} | {
    column for column, value_type in column_types.items() if value_type is bool
}

# Independent multiprocessing workers never share this lock. It also makes
# scoped overrides safe for callers that use a ThreadPool for tiny merges.
_SOURCE_MAP_LOCK = RLock()
_RELATION_IRI_PREFIXES = {
    "http://www.w3.org/2000/01/rdf-schema#": "rdfs:",
    "http://www.w3.org/1999/02/22-rdf-syntax-ns#": "rdf:",
    "http://www.w3.org/2002/07/owl#": "owl:",
    "http://www.w3.org/2004/02/skos/core#": "skos:",
}


def _compact_relation(identifier):
    """Recognize standard RDF vocabulary IRIs not in the project's domain prefix map."""
    for iri, prefix in _RELATION_IRI_PREFIXES.items():
        if identifier.startswith(iri):
            return prefix + identifier[len(iri) :]
    return compact_identifier(identifier)


def canonical_relation(value) -> str:
    """Accept one relation, collapsing only exact repeats and registered IRI aliases."""
    values = value if isinstance(value, (list, tuple, set)) else [value]
    relations = {_compact_relation(part.strip()) for item in values for part in (item or "").split("|") if part.strip()}
    if len(relations) > 1:
        raise ValueError(
            f"Ambiguous source relation {value!r}: distinct relations must be separate source rows, "
            "each retaining its own evidence and provenance."
        )
    return next(iter(relations), "")


def relation_aware_key(subject: str, predicate: str, obj: str, relation: str) -> str:
    """Hash the unambiguous four-field assertion identity, independent of source order."""
    identity = json.dumps([subject, predicate, obj, relation], ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def canonical_assertion(record):
    """Normalize one observation without pooling its scalars or changing evidence pairing."""
    result = {}
    if record.get("knowledge_source"):
        raise SourceFinalizationRequired("Legacy knowledge_source requires audited source finalization")
    source, publications = validate_primary_source_and_publications(
        record.get(PRIMARY_KNOWLEDGE_SOURCE_COLUMN), record.get(PUBLICATIONS_COLUMN)
    )
    for column, value in record.items():
        if column in {"key", ID_COLUMN, "knowledge_source", PRIMARY_KNOWLEDGE_SOURCE_COLUMN, PUBLICATIONS_COLUMN}:
            continue
        if value is None or value == "" or (isinstance(value, (list, tuple, set)) and not value):
            continue
        if column in _MULTIVALUED_EDGE_PROPERTIES:
            result[column] = sorted(knowledge_source_tokens(value))
        elif column_types.get(column) is bool:
            if isinstance(value, (list, tuple, set)):
                values = knowledge_source_tokens(value)
                if len(values) != 1:
                    raise ValueError(f"Pooled scalar {column}={value!r}; rebuild from original source observations")
                value = values[0]
            if isinstance(value, str):
                if value.lower() not in {"true", "false", "1", "0"}:
                    raise ValueError(f"Invalid boolean assertion field {column}={value!r}")
                value = value.lower() in {"true", "1"}
            result[column] = bool(value)
        elif isinstance(value, (list, tuple, set)):
            values = knowledge_source_tokens(value)
            if len(values) > 1:
                raise ValueError(
                    f"Pooled scalar {column}={value!r}; rebuild from original source observations, "
                    "because their evidence associations cannot be reconstructed"
                )
            if values:
                result[column] = values[0]
        else:
            result[column] = value
    result[RELATION_COLUMN] = canonical_relation(result.get(RELATION_COLUMN, ""))
    if source:
        result[PRIMARY_KNOWLEDGE_SOURCE_COLUMN] = source
    if publications:
        result[PUBLICATIONS_COLUMN] = sorted(publications)
    return result


def assertion_key(record) -> str:
    """Hash the entire normalized observation, including provider, context, and evidence."""
    return _hash_assertion(canonical_assertion(record))


def _hash_assertion(normalized) -> str:
    """Hash an already normalized payload without repeating graph-scale normalization."""
    payload = json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _add_assertion(graph, record):
    """Collapse only a fully identical observation; every conflicting attribute changes its key."""
    data = canonical_assertion(record)
    key = _hash_assertion(data)
    data[ID_COLUMN] = key
    graph.add_edge(data[SUBJECT_COLUMN], data[OBJECT_COLUMN], edge_key=key, **data)


def merge_assertion_graphs(graphs, preserve=True):
    """Retain KGX node merging, but never pool independent observations across source graphs."""
    graphs = list(graphs)
    if not graphs:
        raise ValueError("Cannot merge an empty graph list")
    largest = max(range(len(graphs)), key=lambda index: graphs[index].number_of_edges())
    result = graphs.pop(largest)
    for graph in graphs:
        add_all_nodes(result, graph, preserve)
        for _, _, data in graph.edges(data=True):
            _add_assertion(result, data)
    return result


class RelationAwareTsvSource(TsvSource):
    """Validate finalized syntax before keying distinct source assertions."""

    def read_node(self, node):
        """Reject source semantic drift; merge only unions already canonical declarations."""
        normalized = dict(node)
        if normalized.get(ID_COLUMN):
            validate_node_representation(normalized[ID_COLUMN], normalized.get(CATEGORY_COLUMN, ""))
        result = super().read_node(normalized)
        if result is None:
            return None
        identifier, data = result
        # KGX assumes unknown properties are lists and splits literal pipes.
        # Only model-declared list fields have that representation contract.
        for column, value in normalized.items():
            if column not in _MULTIVALUED_NODE_PROPERTIES:
                data[column] = value
        # An explicitly blank finalized provider is not permission to invent
        # the input filename as provenance (notably for anonymous stubs).
        if PROVIDED_BY_COLUMN in normalized:
            data[PROVIDED_BY_COLUMN] = knowledge_source_tokens(normalized[PROVIDED_BY_COLUMN])
        return identifier, data

    def read_edge(self, edge):
        """Keep one canonical provider/context/evidence bundle per observation."""
        normalized = dict(edge)
        for column in (SUBJECT_COLUMN, PREDICATE_COLUMN, OBJECT_COLUMN):
            if normalized.get(column):
                validate_identifier(normalized[column])
        relation = canonical_relation(normalized.get(RELATION_COLUMN, ""))
        if relation != normalized.get(RELATION_COLUMN, ""):
            raise SourceFinalizationRequired("Noncanonical source relation; rerun source finalization")
        normalized[RELATION_COLUMN] = relation
        original_id = normalized.get(ID_COLUMN)
        normalized = canonical_assertion(normalized)
        if original_id and original_id != assertion_key(normalized):
            normalized[SOURCE_ASSERTION_ID_COLUMN] = original_id
        result = super().read_edge(normalized)
        if result is None:
            return None
        subject, obj, _, data = result
        # Retain only supplied assertion attributes, not KGX's autogenerated
        # knowledge_source=filename. Also restore raw scalar pipe text rather
        # than confusing it with a pooled list. Keep KGX's explicit bool type.
        data = {
            column: data.get(column, value) if column_types.get(column) is bool else value
            for column, value in normalized.items()
        }
        data = canonical_assertion(data)
        key = _hash_assertion(data)
        # GraphSink discards the tuple key and regenerates a triple-only key
        # unless the record itself carries it. Both boundaries need this key.
        data["key"] = key
        data[ID_COLUMN] = key
        data[RELATION_COLUMN] = relation
        self.edge_properties.update(data)
        return subject, obj, key, data


class RelationAwareGraphSink(GraphSink):
    """Preserve relation identity both during ingestion and KGX's intermediate export."""

    def write_node(self, record):
        """Union provenance when canonical identifier aliases converge within a source."""
        node_id = record[ID_COLUMN]
        if node_id in self.graph.nodes():
            record = prepare_data_dict(copy.deepcopy(self.graph.nodes()[node_id]), copy.deepcopy(record), preserve=True)
        super().write_node(record)

    def write_edge(self, record):
        """Preserve distinct observations within one source and at intermediate export."""
        _add_assertion(self.graph, record)


class RelationAwareGraphSource(GraphSource):
    """Retain provenance collections when reading merged graph edges for export."""

    def read_nodes(self):
        """Keep literal scalar node text through KGX's intermediate graph export."""
        for identifier, data in super().read_nodes():
            original = self.graph.nodes()[identifier]
            for column, value in original.items():
                if column not in _MULTIVALUED_NODE_PROPERTIES:
                    data[column] = value
            yield identifier, data

    def read_edges(self):
        """Restore canonical scalar metadata after KGX's generic graph sanitization."""
        for subject, obj, key, data in self.graph.edges(keys=True, data=True):
            validated = self.validate_edge(dict(data))
            if not validated:
                continue
            edge = canonical_assertion(validated)
            # The graph already carries source provenance. Export must not
            # inject a filename or the literal "Graph" as another provider.
            edge[ID_COLUMN] = _hash_assertion(edge)
            if self.check_edge_filter(edge):
                self.edge_properties.update(edge)
                yield subject, obj, key, edge


def _canonical_node_boolean(column, value):
    """Collapse identical flags and absent declarations without resolving disagreements."""
    values = value if isinstance(value, (list, tuple, set)) else [value]
    flags = set()
    for item in values:
        if item is None or item == "":
            continue
        if isinstance(item, bool):
            flags.add(item)
        elif isinstance(item, str) and item.lower() in {"true", "false", "1", "0"}:
            flags.add(item.lower() in {"true", "1"})
        elif type(item) is int and item in {0, 1}:
            flags.add(bool(item))
        else:
            raise ValueError(f"Invalid Boolean node field {column}={value!r}")
    if len(flags) > 1:
        raise ValueError(f"Conflicting Boolean node field {column}={value!r}; reconcile source declarations")
    return next(iter(flags), "")


class RelationAwareTsvSink(TsvSink):
    """Write the canonical schema once, preserving literal finalized text and extensions."""

    def __init__(self, owner, filename, format, compression=None, **kwargs):
        """Bypass KGX's generated-column header and content-altering export sanitizer."""
        Sink.__init__(self, owner)
        if format not in {"tsv", "csv"}:
            raise ValueError(f"Unsupported canonical tabular format: {format}")
        modes = {None: None, "tar": "w", "tar.gz": "w:gz"}
        if compression not in modes:
            raise ValueError(f"Unsupported canonical tabular compression: {compression}")
        self.mode = modes[compression]
        self.delimiter = "\t" if format == "tsv" else ","
        self.list_delimiter = kwargs.get("list_delimiter", "|")
        self.extension = format
        base = Path(filename).absolute()
        base.parent.mkdir(parents=True, exist_ok=True)
        self.dirname, self.basename = str(base.parent), base.name
        self.nodes_file_basename = f"{base.name}_nodes.{format}"
        self.edges_file_basename = f"{base.name}_edges.{format}"
        self.nodes_file_name = str(base.parent / self.nodes_file_basename)
        self.edges_file_name = str(base.parent / self.edges_file_basename)
        self.node_properties.update(kwargs.get("node_properties", CANONICAL_NODE_HEADER))
        self.edge_properties.update(kwargs.get("edge_properties", CANONICAL_EDGE_HEADER))
        self.edge_properties.difference_update({ID_COLUMN, "key", "knowledge_source"})
        self.ordered_node_columns = canonical_header(self.node_properties, is_node=True)
        self.ordered_edge_columns = canonical_header(self.edge_properties, is_node=False)
        self.NFH = open(self.nodes_file_name, "w", encoding="utf-8", newline="")
        try:
            self.EFH = open(self.edges_file_name, "w", encoding="utf-8", newline="")
        except BaseException:
            self.NFH.close()
            raise
        quoting = csv.QUOTE_NONE if format == "tsv" else csv.QUOTE_MINIMAL
        dialect = {"delimiter": self.delimiter, "quoting": quoting, "quotechar": None if format == "tsv" else '"'}
        self._node_writer = tsv_writer(self.NFH, **dialect)
        self._edge_writer = tsv_writer(self.EFH, **dialect)
        self._node_writer.writerow(self.ordered_node_columns)
        self._edge_writer.writerow(self.ordered_edge_columns)

    def _write_record(self, record, columns, writer):
        """Serialize collections without stripping quotes or silently editing text controls."""
        unexpected = {key for key, value in record.items() if key not in columns and value not in (None, "", [])}
        if unexpected:
            raise ValueError(f"Unannounced KGX serialization properties: {sorted(unexpected)}")
        values = []
        for column in columns:
            value = record.get(column)
            if isinstance(value, (list, tuple, set)):
                value = self.list_delimiter.join(str(item) for item in sorted(value, key=str))
            elif isinstance(value, bool):
                value = "true" if value else "false"
            else:
                value = "" if value is None else str(value)
            if any(control in value for control in ("\t", "\r", "\n", "\x00")):
                raise ValueError(f"Embedded control in canonical {column}; rerun source finalization")
            values.append(value)
        writer.writerow(values)

    def write_node(self, record):
        """Preserve provenance and literal text while keeping Boolean flags scalar."""
        data = {
            column: _canonical_node_boolean(column, value) if column in _BOOLEAN_NODE_PROPERTIES else value
            for column, value in record.items()
        }
        self._write_record(data, self.ordered_node_columns, self._node_writer)

    def write_edge(self, record):
        """Publish observation fields, never KGX's private transport keys."""
        data = canonical_assertion(record)
        for column in _MULTIVALUED_EDGE_PROPERTIES:
            values = data.get(column)
            if isinstance(values, (list, tuple, set)):
                data[column] = serialize_knowledge_sources(
                    sorted(knowledge_source_tokens(values, self.list_delimiter)), delimiter=self.list_delimiter
                )
        self._write_record(data, self.ordered_edge_columns, self._edge_writer)


def _preserve_node_sources(values=None):
    """Keep explicit providers verbatim and never invent provenance for a stub."""
    return values or []


class ProvenancePreservingTransformer(Transformer):
    """Keep graph-export provenance in a module-level class safe to return from workers."""

    def transform(self, input_args, *args, **kwargs):
        """Override graph provenance without changing ordinary TSV ingestion defaults."""
        if input_args.get("format") == "graph":
            input_args = {**input_args, PROVIDED_BY_COLUMN: _preserve_node_sources}
        return super().transform(input_args, *args, **kwargs)


def parse_source(
    key,
    source,
    output_directory,
    prefix_map=None,
    node_property_predicates=None,
    predicate_mappings=None,
    checkpoint=False,
):
    """Delegate to KGX under a worker-local, exception-safe TSV/CSV source override."""
    with _SOURCE_MAP_LOCK, local_prefix_context():
        original = {format_name: transformer_module.SOURCE_MAP[format_name] for format_name in ("tsv", "csv", "graph")}
        original_sink = transformer_module.GraphSink
        original_tsv_sinks = {format_name: transformer_module.SINK_MAP[format_name] for format_name in ("tsv", "csv")}
        original_transformer = cli_utils_module.Transformer
        try:
            transformer_module.SOURCE_MAP.update(
                {"tsv": RelationAwareTsvSource, "csv": RelationAwareTsvSource, "graph": RelationAwareGraphSource}
            )
            transformer_module.GraphSink = RelationAwareGraphSink
            transformer_module.SINK_MAP.update(
                {format_name: RelationAwareTsvSink for format_name in original_tsv_sinks}
            )
            cli_utils_module.Transformer = ProvenancePreservingTransformer
            return _kgx_parse_source(
                key,
                source,
                output_directory,
                prefix_map,
                node_property_predicates,
                predicate_mappings,
                checkpoint,
            )
        finally:
            transformer_module.SOURCE_MAP.update(original)
            transformer_module.GraphSink = original_sink
            transformer_module.SINK_MAP.update(original_tsv_sinks)
            cli_utils_module.Transformer = original_transformer
