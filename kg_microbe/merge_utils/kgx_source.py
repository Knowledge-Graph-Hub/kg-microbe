"""
Relation-aware KGX ingestion without conflating independent source assertions (#1054).

Import this adapter only at the merge boundary. KGX constructs a BMT toolkit
while importing; configure its pinned local inputs first, including in spawned
workers. The top-level parser remains pickleable and captures the real KGX
parser before the caller temporarily replaces ``cli_utils.parse_source``.
"""

import copy
import hashlib
import json
from threading import RLock

from kg_microbe.transform_utils.constants import (
    CATEGORY_COLUMN,
    ID_COLUMN,
    OBJECT_COLUMN,
    PREDICATE_COLUMN,
    PROVIDED_BY_COLUMN,
    RELATION_COLUMN,
    SUBJECT_COLUMN,
)
from kg_microbe.utils.biolink_model import prepare_kgx
from kg_microbe.utils.graph_canonicalization import canonical_node_category, compact_identifier

prepare_kgx()

from kgx import transformer as transformer_module  # noqa: E402
from kgx.cli import cli_utils as cli_utils_module  # noqa: E402
from kgx.cli.cli_utils import parse_source as _kgx_parse_source  # noqa: E402
from kgx.sink.graph_sink import GraphSink  # noqa: E402
from kgx.sink.tsv_sink import TsvSink  # noqa: E402
from kgx.source.graph_source import GraphSource  # noqa: E402
from kgx.source.tsv_source import TsvSource  # noqa: E402
from kgx.transformer import Transformer  # noqa: E402
from kgx.utils.kgx_utils import knowledge_provenance_properties, prepare_data_dict, sanitize_import  # noqa: E402

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


class RelationAwareTsvSource(TsvSource):
    """Canonicalize before keying, keeping distinct relations and their evidence apart."""

    def read_node(self, node):
        """Coalesce IRI/CURIE aliases without overwriting their source provenance."""
        normalized = dict(node)
        if normalized.get(ID_COLUMN):
            normalized[ID_COLUMN] = compact_identifier(normalized[ID_COLUMN])
            category = canonical_node_category(normalized[ID_COLUMN], normalized.get(CATEGORY_COLUMN, ""))
            if category or CATEGORY_COLUMN in normalized:
                normalized[CATEGORY_COLUMN] = category
        return super().read_node(normalized)

    def read_edge(self, edge):
        """Set the sink's explicit key and union evidence for exact repeated assertions."""
        normalized = dict(edge)
        for column in (SUBJECT_COLUMN, PREDICATE_COLUMN, OBJECT_COLUMN):
            if normalized.get(column):
                normalized[column] = compact_identifier(normalized[column])
        relation = canonical_relation(normalized.get(RELATION_COLUMN, ""))
        normalized[RELATION_COLUMN] = relation
        result = super().read_edge(normalized)
        if result is None:
            return None
        subject, obj, _, data = result
        key = relation_aware_key(subject, data[PREDICATE_COLUMN], obj, relation)
        # GraphSink discards the tuple key and regenerates a triple-only key
        # unless the record itself carries it. Both boundaries need this key.
        data["key"] = key
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
        """Keep exact-repeat evidence, without passing a duplicate ``key`` kwarg to NxGraph."""
        data = dict(record)
        relation = canonical_relation(data.get(RELATION_COLUMN, ""))
        subject, predicate, obj = (data[column] for column in (SUBJECT_COLUMN, PREDICATE_COLUMN, OBJECT_COLUMN))
        key = relation_aware_key(subject, predicate, obj, relation)
        # NxGraph passes its own key= argument to NetworkX, so the record's
        # transport key must not also be passed through **data.
        data.pop("key", None)
        if self.graph.has_edge(subject, obj, key):
            data = prepare_data_dict(copy.deepcopy(self.graph.get_edge(subject, obj, key)), copy.deepcopy(data), True)
        data[RELATION_COLUMN] = relation
        self.graph.add_edge(subject, obj, edge_key=key, **data)


class RelationAwareGraphSource(GraphSource):
    """Retain provenance collections when reading merged graph edges for export."""

    def read_edges(self):
        """Do not stringify primary-source lists before applying provenance rules."""
        for subject, obj, key, data in self.graph.edges(keys=True, data=True):
            validated = self.validate_edge(dict(data))
            if not validated:
                continue
            edge = sanitize_import(validated)
            # KGX types primary_knowledge_source as str during ingestion but
            # unions it into a list at merge time. Its GraphSource then turns
            # that list into a Python repr, losing the machine-readable union.
            for column in knowledge_provenance_properties:
                value = validated.get(column)
                if isinstance(value, (list, tuple, set)):
                    edge[column] = list(value)
            edge[RELATION_COLUMN] = canonical_relation(edge.get(RELATION_COLUMN, ""))
            self.set_edge_provenance(edge)
            if self.check_edge_filter(edge):
                self.edge_properties.update(edge)
                yield subject, obj, key, edge


class RelationAwareTsvSink(TsvSink):
    """Serialize merged provenance collections as KGX lists, never Python repr strings."""

    def write_edge(self, record):
        """Override only merged knowledge-source collections before normal TSV export."""
        data = dict(record)
        for column in knowledge_provenance_properties:
            values = data.get(column)
            if isinstance(values, (list, tuple, set)):
                data[column] = self.list_delimiter.join(sorted({str(value) for value in values}))
        super().write_edge(data)


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
    with _SOURCE_MAP_LOCK:
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
