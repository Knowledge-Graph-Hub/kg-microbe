"""Ontology transform module."""

import csv
import json
import re
from collections import defaultdict
from contextlib import ExitStack
from itertools import chain
from os import makedirs
from pathlib import Path
from typing import Optional, Union

import pandas as pd

from kg_microbe.transform_utils.constants import (
    AGENT_TYPE_COLUMN,
    CATEGORY_COLUMN,
    DEPRECATED_COLUMN,
    DESCRIPTION_COLUMN,
    EXCLUSION_TERMS_FILE,
    GO_PREFIX,
    HAS_PART,
    HAS_PART_PREDICATE,
    ID_COLUMN,
    IRI_COLUMN,
    KNOWLEDGE_ASSERTION,
    KNOWLEDGE_LEVEL_COLUMN,
    MANUAL_AGENT,
    MONDO_XREFS_FILEPATH,
    NCBITAXON_PREFIX,
    OBJECT_COLUMN,
    ONTOLOGIES,
    ONTOLOGIES_XREFS_DIR,
    PART_OF_PREDICATE,
    PREDICATE_COLUMN,
    PRIMARY_KNOWLEDGE_SOURCE_COLUMN,
    PROVIDED_BY_COLUMN,
    PUBLICATIONS_COLUMN,
    RDFS_SUBCLASS_OF,
    RELATED_TO_PREDICATE,
    RELATED_TO_RELATION,
    RELATION_COLUMN,
    RHEA_NEW_PREFIX,
    ROBOT_REMOVED_SUFFIX,
    SAME_AS_COLUMN,
    SPECIAL_PREFIXES,
    SUBCLASS_PREDICATE,
    SUBJECT_COLUMN,
    SUBSETS_COLUMN,
    TREMBL_PREFIX,
    UNIPATHWAYS_ENZYMATIC_REACTION_PREFIX,
    UNIPATHWAYS_INCLUDE_PAIRS,
    UNIPATHWAYS_PATHWAY_PREFIX,
    UNIPATHWAYS_REACTION_PREFIX,
    UNIPATHWAYS_XREFS_FILEPATH,
    UNIPROT_PREFIX,
    XREF_COLUMN,
)
from kg_microbe.utils.atomic_io import atomic_write
from kg_microbe.utils.graph_canonicalization import canonical_node_category, compact_identifier
from kg_microbe.utils.ontology_utils import (
    _decompress_atomically,
    _derived_json_is_stale,
    _derived_json_is_unusable,
    replace_category_ontology,
)
from kg_microbe.utils.pandas_utils import (
    drop_duplicates,
    establish_transitive_relationship,
    establish_transitive_relationship_multiple,
)
from kg_microbe.utils.robot_utils import (
    convert_to_json,
    remove_convert_to_json,
)
from kg_microbe.utils.unipathways_utils import (
    check_wanted_pairs,
    remove_unwanted_prefixes_from_edges,
    remove_unwanted_prefixes_from_node_xrefs,
    replace_category_for_unipathways,
    replace_id_with_xref,
    replace_triples_with_labels,
)

from ..transform import Transform

ONTOLOGIES_MAP = {
    "ncbitaxon": "ncbitaxon.owl.gz",
    "chebi": "chebi.owl.gz",
    "envo": "envo.json",
    # GO is single-source (fix 2, #604): the transform derives go.json from
    # go.owl (ROBOT owl→json), the same OWL that go.db is built from — so the
    # aspect map (go.db) and the transform output (go.json) share one release.
    "go": "go.owl",
    ## "rhea": "rhea.json.gz", # Redundant to RheaMappingsTransform
    # EC is single-source (round 29 of #604): the transform derives ec.json
    # from ec.owl.gz (ROBOT owl→json), the same OWL that ec.db is built from
    # — so `rhea_mappings` label enrichment against ec.db and the node
    # emission this transform performs share one release. A prior revision
    # downloaded ec.json separately from w3id.org/biopragmatics; that JSON
    # drifted on its own schedule and could reference terms that were absent
    # from ec.owl (and therefore from ec.db), so rhea_mappings emitted blank
    # labels for them. Do NOT re-add a standalone ec.json download.
    "ec": "ec.owl.gz",
    "upa": "upa.owl",
    "mondo": "mondo.json",
    "hp": "hp.json",
    "metpo": "metpo.owl",
    "uberon": "uberon.owl",
    "foodon": "foodon.owl",
    "pato": "pato.owl",
    "ro": "ro.owl",
    "taxrank": "taxrank.owl",  # Taxonomic Rank — NCBITaxon transform rank annotations
    # NOTE: PO (Plant Ontology) and MICRO (Microbial Conditions Ontology)
    # used to be full-load entries here. The merged KG only references a
    # handful of CURIEs from each (~6-8 PO, ~34 MICRO) — both ontologies
    # are now per-CURIE imports via the OntologiesStubsTransform
    # (kg_microbe/transform_utils/ontologies_stubs/), which emits one
    # labelled stub node per referenced CURIE instead of pulling in
    # ~2,170 + ~17,600 unrelated nodes. Both go through ROBOT MIREOT against
    # the OWL (owl_mireot): PO from data/raw/po.owl, MICRO from
    # data/raw/micro.owl. Neither uses a SemSQL .db — MICRO's bbop-sqlite
    # distribution is a truncated placeholder, and PO's was downloaded but
    # never read, so it was dropped from download.yaml (#604).
}


# Ontology metamodel axioms the KGX OBO-JSON loader emits verbatim: a
# relation's inverse (owl:inverseOf), a property hierarchy (rdfs:subPropertyOf),
# and rdf:type assertions. These are property-level / typing statements with raw
# RDF/OWL predicate CURIEs — not biolink entity relationships — so they clutter
# the merged KG (kgxval flags them as non-biolink) without carrying queryable
# entity data. Dropped from the edge output; nodes are left untouched.
#: Prefixes of the annotation and metadata vocabulary an OWL file annotates
#: *with* -- never anything it defines. KGX's OBO-JSON loader emits a node for
#: each one it encounters, so `rdfs:label`, `owl:deprecated`, `dc:title` and
#: `dcterms:license` arrived as biolink:OntologyClass nodes connected to
#: nothing: 55 distinct ids, 172 rows across ten ontologies, 0 edges, 36 of
#: them in the shipped graph (#1023). Matching on the id column of a *nodes*
#: file only -- `skos:closeMatch` as a relation value is legitimate and lives
#: in a different column of a different file.
METAMODEL_NODE_PREFIXES = frozenset(
    {"dc", "dct", "dcterms", "terms", "doap", "foaf", "oio", "owl", "pav", "rdf", "rdfs", "skos"}
)

METAMODEL_EDGE_PREDICATES = frozenset(
    {
        "rdfs:subPropertyOf",
        "owl:inverseOf",
        "rdf:type",
    }
)

# Explicit provenance annotation predicates, not a namespace-wide entity ban.
_CONTRIBUTOR_ANNOTATIONS = frozenset(
    f"http://purl.org/dc/{namespace}/{role}"
    for namespace in ("elements/1.1", "terms")
    for role in ("creator", "contributor")
)
_RAW_TYPE_PREDICATES = frozenset({"type", "rdf:type", "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"})

# Reviewed query-graph exclusions, not a blanket assertion that class-level
# partonomy or every reflexive ontology relation is biologically invalid.
SELF_LOOP_EXCLUSIONS_FILE = Path(__file__).resolve().parents[3] / "mappings/ontology_self_loop_exclusions.tsv"


def _self_loop_exclusions() -> dict:
    """Read exact, evidence-bearing exclusions; fail rather than silently ignore invalid policy."""
    columns = [SUBJECT_COLUMN, PREDICATE_COLUMN, OBJECT_COLUMN, RELATION_COLUMN, "reason"]
    supported = {(HAS_PART_PREDICATE, HAS_PART), (SUBCLASS_PREDICATE, RDFS_SUBCLASS_OF)}
    exclusions = {}
    with SELF_LOOP_EXCLUSIONS_FILE.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream, delimiter="\t")
        if reader.fieldnames != columns:
            raise ValueError(f"Invalid self-loop exclusion header: {SELF_LOOP_EXCLUSIONS_FILE}")
        for row in reader:
            if None in row or any(not (row.get(column) or "").strip() for column in columns):
                raise ValueError(f"Incomplete self-loop exclusion at line {reader.line_num}")
            key = tuple(row[column] for column in columns[:-1])
            if any(value != value.strip() for value in key):
                raise ValueError(f"Invalid self-loop exclusion whitespace at line {reader.line_num}: {key}")
            if key[0] != key[2] or (key[1], key[3]) not in supported or key in exclusions:
                raise ValueError(f"Invalid or duplicate self-loop exclusion at line {reader.line_num}: {key}")
            exclusions[key] = row["reason"]
    return exclusions


def _run_kgx_transform(*, inputs, input_format, output, output_format) -> None:
    """Stream one OBOJSON to TSV without the CLI's relation-losing SPO graph store."""
    import ijson

    from kg_microbe.merge_utils.local_context import local_prefix_context
    from kg_microbe.utils.biolink_model import prepare_kgx

    if input_format != "obojson" or output_format != "tsv" or len(inputs) != 1:
        raise ValueError("Ontology conversion supports one uncompressed OBOJSON input and TSV output only")
    source = Path(inputs[0])
    if source.suffix != ".json":
        raise ValueError("Ontology conversion requires an uncompressed .json input")
    prepare_kgx()
    from kgx.sink.tsv_sink import DEFAULT_EDGE_COLUMNS, DEFAULT_NODE_COLUMNS, TsvSink
    from kgx.transformer import Transformer
    from kgx.utils.kgx_utils import GraphEntityType, knowledge_provenance_properties

    # KGX's default streaming node columns omit several OBO reader outputs.
    node_columns = set(DEFAULT_NODE_COLUMNS) | {
        XREF_COLUMN,
        SAME_AS_COLUMN,
        DEPRECATED_COLUMN,
        IRI_COLUMN,
        SUBSETS_COLUMN,
        PROVIDED_BY_COLUMN,
    }
    base_edge_columns = set(DEFAULT_EDGE_COLUMNS) | {"meta", "key"}
    optional_edge_columns = set(knowledge_provenance_properties) | {
        KNOWLEDGE_LEVEL_COLUMN,
        AGENT_TYPE_COLUMN,
        PRIMARY_KNOWLEDGE_SOURCE_COLUMN,
        PUBLICATIONS_COLUMN,
        DESCRIPTION_COLUMN,
        XREF_COLUMN,
    }
    allowed_raw = {"sub", "pred", "obj"} | base_edge_columns | optional_edge_columns
    present = set()
    # Preserve absent-vs-blank semantics: declaring empty KL/AT/PKS columns
    # would suppress the existing ontology metadata defaults/legacy rename.
    with source.open("rb") as stream:
        for edge in ijson.items(stream, "graphs.item.edges.item"):
            unknown = set(edge) - allowed_raw
            if unknown:
                raise ValueError(f"Undeclared OBOJSON edge fields in {source}: {sorted(unknown)}")
            present.update(edge)
    edge_columns = base_edge_columns | (present & optional_edge_columns)

    def inspect_columns(kind, record):
        """Abort before a streaming sink could silently discard an emitted property."""
        columns = node_columns if kind == GraphEntityType.NODE else edge_columns
        unknown = set(record[-1]) - columns
        if unknown:
            raise ValueError(f"Undeclared KGX {kind.value} fields in {source}: {sorted(unknown)}")

    with local_prefix_context():
        transformer = Transformer(stream=True)
        owned_sinks = []

        def capture_sink(**sink_args):
            """Capture this instance's native sink before initialization can open either handle."""
            if sink_args.get("format") != "tsv" or sink_args.get("compression"):
                raise ValueError("Ontology conversion requires an uncompressed TSV sink")
            sink = TsvSink.__new__(TsvSink)
            owned_sinks.append(sink)
            TsvSink.__init__(sink, transformer, **sink_args)
            return sink

        # No global KGX factory/graph patches: only this local Transformer owns
        # the override. Native transform lacks a finally around sink.finalize().
        transformer.get_sink = capture_sink
        try:
            transformer.transform(
                input_args={"filename": [str(source)], "format": "obojson"},
                output_args={
                    "filename": str(output),
                    "format": "tsv",
                    "node_properties": node_columns,
                    "edge_properties": edge_columns,
                },
                inspector=inspect_columns,
            )
        finally:
            with ExitStack() as cleanup:
                for sink in owned_sinks:
                    for attribute in ("NFH", "EFH"):
                        handle = getattr(sink, attribute, None)
                        if handle is not None and not handle.closed:
                            cleanup.callback(handle.close)


class OntologiesTransform(Transform):
    """OntologyTransform parses an Obograph JSON form of an Ontology into nodes nad edges."""

    DATA_INPUTS = ("mappings/foodon_model_dispositions.tsv", "mappings/ontology_self_loop_exclusions.tsv")

    # Mapping of ontology names to InforES standard knowledge sources
    # (po and micro removed — now emitted as per-CURIE stubs via
    # OntologiesStubsTransform; see ONTOLOGIES_MAP note above)
    ONTOLOGY_KNOWLEDGE_SOURCES = {
        "chebi": "infores:chebi",
        "envo": "infores:envo",
        "go": "infores:go",
        "ncbitaxon": "infores:ncbitaxon",
        "uberon": "infores:uberon",
        "hp": "infores:hp",
        "mondo": "infores:mondo",
        "upa": "infores:upa",
        "ec": "infores:ec",
        "metpo": "infores:metpo",
        "foodon": "infores:foodon",
        "pato": "infores:pato",
        "ro": "infores:ro",
        "taxrank": "infores:taxrank",
    }

    def __init__(self, input_dir: Optional[Path] = None, output_dir: Optional[Path] = None):
        """Instantiate object."""
        source_name = ONTOLOGIES
        super().__init__(source_name, input_dir, output_dir)

    def run(self, data_file: Union[Optional[Path], Optional[str]] = None, show_status: bool = True) -> None:
        """
        Transform an ontology.

        :param data_file: data file to parse
        :return: None.
        """
        if data_file:
            k = str(data_file).split(".")[0]
            data_file = self.input_base_dir / data_file
            self.parse(k, data_file, k)
        else:
            # load all ontologies
            for k in ONTOLOGIES_MAP.keys():
                data_file = self.input_base_dir / ONTOLOGIES_MAP[k]
                self.parse(k, data_file, k)

    def parse(self, name: str, data_file: Optional[Path], source: str) -> None:
        """
        Process the data_file.

        :param name: Name of the ontology.
        :param data_file: data file to parse.
        :param source: Source name.
        :return: None.
        """
        if not data_file.suffix == ".json":
            if data_file.suffixes == [".owl", ".gz"]:
                # if NCBITAXON_PREFIX.strip(":").lower() in str(data_file):
                # or CHEBI_PREFIX.strip(":").lower() in str(data_file):
                if NCBITAXON_PREFIX.strip(":").lower() in str(data_file):
                    json_path = str(data_file).replace(".owl.gz", ROBOT_REMOVED_SUFFIX + ".json")
                    self._drop_stale_derived_json(data_file, Path(json_path))
                    if not Path(json_path).is_file():
                        self.decompress(data_file)
                        with open(str(self.input_base_dir / EXCLUSION_TERMS_FILE), "r") as f:
                            terms = [line.strip() for line in f if line.lower().startswith(name.lower())]
                        remove_convert_to_json(str(self.input_base_dir), name, terms)
                    # elif CHEBI_PREFIX.strip(":").lower() in str(data_file):
                    #     json_path = str(data_file).replace(".owl.gz", ROBOT_EXTRACT_SUFFIX + ".json")
                    #     owl_path = str(data_file).strip(".gz")
                    #     # Convert CHEBI owl => JSON each time to handle varying terms (if any) in CHEBI_NODES_FILENAME
                    #     if not Path(owl_path).is_file():
                    #         self.decompress(data_file)
                    #     terms = str(self.input_base_dir / CHEBI_NODES_FILENAME)
                    #     extract_convert_to_json(str(self.input_base_dir), name, terms, "BOT")
                else:
                    json_path = str(data_file).replace("owl.gz", "json")
                    self._drop_stale_derived_json(data_file, Path(json_path))
                    if not Path(json_path).is_file():
                        # Unzip the file
                        self.decompress(data_file)
                        print(f"Converting {data_file} to obojson...")
                    convert_to_json(str(self.input_base_dir), name)

                data_file = json_path
            elif data_file.suffixes == [".json", ".gz"]:
                json_path = str(data_file).replace(".json.gz", ".json")
                if not Path(json_path).is_file():
                    self.decompress(data_file)
                data_file = json_path
            elif data_file.suffix == ".owl":
                json_path = str(data_file).replace(".owl", ".json")
                # Regenerate the derived JSON when it's missing, drifted, or a
                # zero-byte / truncated leftover. For single-source ontologies
                # (fix 2 #604: GO derives go.json from go.owl) release-alignment
                # keeps the transform output locked to the OWL (and go.db,
                # built from it), so a refreshed go.owl can't leave a stale
                # go.json behind. convert_to_json is a no-op when the target
                # already exists, so either condition must remove the file
                # first — otherwise a stale run silently keeps the old release
                # and a crash-truncated file traps future runs forever.
                if _derived_json_is_stale(data_file, Path(json_path)) or _derived_json_is_unusable(Path(json_path)):
                    Path(json_path).unlink(missing_ok=True)
                if not Path(json_path).is_file():
                    convert_to_json(str(self.input_base_dir), name)
                data_file = json_path
            elif data_file.suffix == ".obo":
                json_path = str(data_file).replace(".obo", ".json")
                # Same unusable-leftover guard: a JSON truncated mid-conversion
                # otherwise persists across runs because convert_to_json skips
                # existing targets.
                if _derived_json_is_unusable(Path(json_path)):
                    Path(json_path).unlink(missing_ok=True)
                if not Path(json_path).is_file():
                    convert_to_json(str(self.input_base_dir), name)
                data_file = json_path
            else:
                raise ValueError(f"Unsupported file format: {data_file}")

        # Drop malformed synonym entries that crash KGX's obograph reader.
        # Some upstream OWL→JSON conversions emit synonym annotations
        # without a literal value (e.g. MICRO:0003152 has a hasRelatedSynonym
        # entry with `pred` but no `val`); KGX's obograph_source assumes
        # every synonym carries `val` and raises KeyError on the missing
        # key. We post-process the converted JSON in place to drop those
        # entries so the load proceeds.
        self._sanitize_obograph_synonyms(Path(data_file))

        # Drop owl:deprecated (obsolete) classes so retired terms do not enter
        # the KG as orphan nodes. METPO, for example, retains ~1,200 deprecated
        # classes from an ID-scheme migration alongside its ~370 active terms;
        # ingesting all of them inflates the graph with disconnected obsolete
        # nodes. Removal happens before the KGX load so neither the nodes nor
        # any edges touching them reach the output.
        self._drop_deprecated_terms(Path(data_file))

        _run_kgx_transform(
            inputs=[data_file],
            input_format="obojson",
            output=self.output_dir / name,
            output_format="tsv",
        )
        # Apply post-processing for ontologies that need IRI removal and URL conversion
        # (all ontologies benefit from these cleanups)
        self.post_process(name)

    def _drop_stale_derived_json(self, source: Path, json_path: Path) -> None:
        """
        Remove a derived JSON whose release no longer matches its source.

        The ``.owl`` branch below has done this since fix 2 (#604), but the two
        compressed sources — ncbitaxon and chebi — regenerated only when the JSON
        was *absent*, and both ``convert_to_json`` and ``remove_convert_to_json``
        are no-ops when their target exists. So an ordinary ``kg download``, which
        refreshes ``<x>.owl.gz`` in place, left the transform emitting nodes from
        the previous release while the SemSQL builders — which do read the
        refreshed archive — rebuilt from the new one. The version gates compare
        the DB against the OWL, never against the JSON that is actually consumed,
        so nothing caught it: ChEBI categories were resolved against terms that
        differed from those emitted, and NCBITaxon lookups could resolve taxa
        absent from the emitted nodes.

        Also unlinks a zero-byte / truncated leftover from a mid-conversion
        crash: without this, ``convert_to_json`` / ``remove_convert_to_json``
        see a file at the target, no-op, and every subsequent run keeps
        reading the corrupt JSON.

        :param source: The downloaded source (``.owl`` or ``.owl.gz``).
        :param json_path: The derived JSON to check.
        """
        if _derived_json_is_unusable(json_path):
            print(f"{json_path.name} is empty or truncated; regenerating it.")
            json_path.unlink(missing_ok=True)
            return
        if not _derived_json_is_stale(source, json_path):
            return
        print(f"{json_path.name} is from an older release than {source.name}; regenerating it.")
        # Only the JSON is removed. Deleting the plain OWL as well — to force a
        # refresh — destroyed the last good copy of it: when the archive's head
        # reported the new release but the archive was truncated further in, a
        # complete plain OWL already at that release was removed and the
        # decompression that was meant to replace it then failed, leaving neither
        # OWL nor JSON. No deletion is needed anyway: `decompress` runs whenever
        # the JSON is absent and republishes the plain OWL atomically.
        json_path.unlink(missing_ok=True)

    def decompress(self, data_file):
        """Unzip file."""
        print(f"Decompressing {data_file}...")
        # Temp file + rename: writing straight to the real filename left a
        # truncated OWL there if interrupted, and a truncated OWL is not
        # detectable downstream — its version stamp lives in the head and still
        # parses, so both ROBOT and the SemSQL build would accept it.
        destination = data_file.parent / data_file.stem
        if not _decompress_atomically(Path(data_file), destination):
            raise OSError(f"Failed to decompress {data_file} to {destination}")

    def _sanitize_obograph_synonyms(self, json_path: Path) -> None:
        """
        Drop synonym entries that lack a literal ``val`` field.

        KGX's obograph reader assumes every ``meta.synonyms`` entry carries
        a ``val`` key and crashes with ``KeyError: 'val'`` on malformed
        entries. Some OWL→JSON conversions (notably MICRO:0003152) emit
        synonym annotations with only a ``pred`` field. This routine
        rewrites the JSON in place to drop those entries so the load
        proceeds; well-formed synonyms are unchanged.
        """
        if not json_path.is_file() or json_path.suffix != ".json":
            return
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            return  # let downstream KGX raise the more informative error

        dropped = 0
        for graph in data.get("graphs", []) or []:
            for node in graph.get("nodes", []) or []:
                meta = node.get("meta")
                if not meta:
                    continue
                syns = meta.get("synonyms")
                if not syns:
                    continue
                kept = [s for s in syns if isinstance(s, dict) and "val" in s]
                if len(kept) != len(syns):
                    dropped += len(syns) - len(kept)
                    meta["synonyms"] = kept

        if dropped:
            print(f"  Dropped {dropped} malformed synonym entries (missing 'val') from {json_path.name}")
            # Atomic: ROBOT publishes this file atomically and then these
            # post-processors rewrote it in place, so an interrupted or
            # out-of-disk rewrite truncated the published JSON. Nothing recovers
            # from that — the staleness check reads a release stamp from the head
            # and still sees a current one, `is_file()` then blocks reconversion,
            # and KGX fails on every later run until someone deletes the file.
            with atomic_write(json_path, encoding="utf-8") as f:
                json.dump(data, f)

    @staticmethod
    def _is_deprecated_node(node: dict) -> bool:
        """
        Return True if an obograph node is flagged ``owl:deprecated true``.

        Obograph JSON encodes deprecation either as a top-level
        ``meta.deprecated`` boolean or as a ``meta.basicPropertyValues`` entry
        whose predicate is ``owl#deprecated`` with the literal value ``"true"``.
        Both forms are checked.
        """
        meta = node.get("meta") or {}
        if meta.get("deprecated") is True:
            return True
        for bpv in meta.get("basicPropertyValues", []) or []:
            pred = str(bpv.get("pred", ""))
            if pred.endswith("owl#deprecated") and str(bpv.get("val", "")).lower() == "true":
                return True
        return False

    @staticmethod
    def _annotation_only_individuals(graphs: list) -> set:
        """
        Find declared contributor individuals with no retained logical role (#1074).

        Creator/contributor annotations are retained in the raw ontology. Only
        their redundant graph nodes are excluded; namespace membership alone
        is insufficient. Any class declaration, non-type edge, or other axiom
        referencing the individual protects it, including across graphs.
        """
        individuals = set()
        protected = set()
        contributors = set()
        for graph in graphs:
            for node in graph.get("nodes", []) or []:
                if node.get("type") == "INDIVIDUAL":
                    individuals.add(node.get("id"))
                else:
                    protected.add(node.get("id"))
            for item in chain((graph,), graph.get("nodes", []) or [], graph.get("edges", []) or []):
                for annotation in (item.get("meta") or {}).get("basicPropertyValues", []) or []:
                    if annotation.get("pred") in _CONTRIBUTOR_ANNOTATIONS and isinstance(annotation.get("val"), str):
                        contributors.add(annotation.get("val"))
        candidates = (individuals & contributors) - protected - {None}
        if not candidates:
            return set()

        def referenced_candidates(value):
            """Visit only logical fields; metadata annotations are not entity axioms."""
            if isinstance(value, str):
                if value in candidates:
                    protected.add(value)
            elif isinstance(value, dict):
                for key, child in value.items():
                    if key != "meta":
                        referenced_candidates(child)
            elif isinstance(value, list):
                for child in value:
                    referenced_candidates(child)

        for graph in graphs:
            for edge in graph.get("edges", []) or []:
                if edge.get("pred") not in _RAW_TYPE_PREDICATES:
                    referenced_candidates(edge)
            for key, value in graph.items():
                if key not in {"nodes", "edges", "meta", "id"}:
                    referenced_candidates(value)
            for node in graph.get("nodes", []) or []:
                for key, value in node.items():
                    if key not in {"id", "type", "propertyType", "lbl", "meta"}:
                        referenced_candidates(value)
        return {compact_identifier(identifier) for identifier in candidates - protected}

    def _drop_deprecated_terms(self, json_path: Path) -> None:
        """
        Remove ``owl:deprecated`` (obsolete) classes from an obograph JSON in place.

        Retired terms are dropped before the KGX load so they never become KG
        nodes, and any edges referencing a dropped term are removed too so no
        dangling edges remain. Active terms are untouched. The file is only
        rewritten when something is actually removed.
        """
        # Remember actual annotation declarations while this JSON is already
        # in memory. A prefix allowlist alone misses custom metadata such as
        # QUDT's ucumCode and GO's applies-pattern (#1054). Reset per ontology
        # so declarations cannot leak into the next source in a batch.
        self._annotation_property_ids = set()
        self._annotation_individual_ids = set()
        if not json_path.is_file() or json_path.suffix != ".json":
            return
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            return  # let downstream KGX raise the more informative error

        self._annotation_individual_ids = self._annotation_only_individuals(data.get("graphs", []) or [])
        dropped_nodes = 0
        dropped_edges = 0
        for graph in data.get("graphs", []) or []:
            self._annotation_property_ids.update(
                compact_identifier(node["id"])
                for node in graph.get("nodes", []) or []
                if node.get("id") and node.get("propertyType") == "ANNOTATION"
            )
            deprecated_ids = {
                node["id"] for node in graph.get("nodes", []) or [] if node.get("id") and self._is_deprecated_node(node)
            }
            if not deprecated_ids:
                continue
            kept_nodes = [n for n in graph.get("nodes", []) or [] if n.get("id") not in deprecated_ids]
            dropped_nodes += len(graph.get("nodes", []) or []) - len(kept_nodes)
            graph["nodes"] = kept_nodes

            edges = graph.get("edges", []) or []
            kept_edges = [e for e in edges if e.get("sub") not in deprecated_ids and e.get("obj") not in deprecated_ids]
            dropped_edges += len(edges) - len(kept_edges)
            graph["edges"] = kept_edges

        if dropped_nodes:
            print(
                f"  Dropped {dropped_nodes} deprecated (owl:deprecated) terms "
                f"and {dropped_edges} edges touching them from {json_path.name}"
            )
            # Atomic: ROBOT publishes this file atomically and then these
            # post-processors rewrote it in place, so an interrupted or
            # out-of-disk rewrite truncated the published JSON. Nothing recovers
            # from that — the staleness check reads a release stamp from the head
            # and still sees a current one, `is_file()` then blocks reconversion,
            # and KGX fails on every later run until someone deletes the file.
            with atomic_write(json_path, encoding="utf-8") as f:
                json.dump(data, f)

    def _drop_metamodel_edges(self, df: pd.DataFrame) -> tuple:
        """
        Return ``(filtered_df, dropped_count)`` with ontology metamodel edges removed.

        Drops rows whose predicate is in ``METAMODEL_EDGE_PREDICATES``
        (``rdfs:subPropertyOf`` / ``owl:inverseOf`` / ``rdf:type``) — the
        property-level / typing statements the KGX OBO-JSON loader passes
        through verbatim. Pure DataFrame transform (no I/O) so it can share the
        single read/write in :meth:`_add_kgx_metadata_to_edges`; returns the
        frame unchanged when the predicate column is absent.
        """
        if PREDICATE_COLUMN not in df.columns:
            return df, 0
        before = len(df)
        df = df[~df[PREDICATE_COLUMN].isin(METAMODEL_EDGE_PREDICATES)]
        return df, before - len(df)

    def _drop_metamodel_nodes(self, df: pd.DataFrame) -> tuple:
        """
        Return ``(filtered_df, dropped_count)`` with annotation-only nodes removed.

        Drops declared annotation properties collected from obograph JSON as
        well as ids in :data:`METAMODEL_NODE_PREFIXES` -- the vocabulary an
        ontology annotates with rather than anything it defines. Pure
        DataFrame transform (no I/O), mirroring
        :meth:`_drop_metamodel_edges`; returns the frame unchanged when the id
        column is absent.
        """
        if ID_COLUMN not in df.columns:
            return df, 0
        before = len(df)
        prefixes = df[ID_COLUMN].astype(str).str.split(":", n=1).str[0]
        annotation_ids = getattr(self, "_annotation_property_ids", set())
        contributor_ids = getattr(self, "_annotation_individual_ids", set())
        normalized_ids = df[ID_COLUMN].astype(str).map(compact_identifier)
        df = df[~(prefixes.isin(METAMODEL_NODE_PREFIXES) | normalized_ids.isin(annotation_ids | contributor_ids))]
        return df, before - len(df)

    def _add_kgx_metadata_to_edges(self, edges_file_path: Path):
        """
        Add knowledge_level and agent_type columns to ontology edge files.

        All ontology edges use knowledge_assertion + manual_agent since ontologies
        are manually curated by domain expert curators (GO, ChEBI, ENVO, etc.).
        The relationships represent definitional assertions made by experts.
        """
        df = pd.read_csv(edges_file_path, sep="\t", low_memory=False)

        # Add columns if they don't exist
        if KNOWLEDGE_LEVEL_COLUMN not in df.columns:
            df[KNOWLEDGE_LEVEL_COLUMN] = KNOWLEDGE_ASSERTION
        if AGENT_TYPE_COLUMN not in df.columns:
            df[AGENT_TYPE_COLUMN] = MANUAL_AGENT

        # Write back
        df.to_csv(edges_file_path, sep="\t", index=False)

    def _fix_node_categories(self, nodes_file_path: Path, ontology_name: str):
        """
        Fix node categories for specific ontologies.

        - GO: Apply aspect-based categorization (MF/BP/CC)
        - ChEBI: Detect roles/macromolecules; default small molecules to CHEBI_CATEGORY
          (biolink:ChemicalEntity — KG-Microbe project convention, see constants.py)
        - UBERON: Ensure all terms are AnatomicalEntity
        - NCBITaxon: Ensure all terms are OrganismTaxon

        Args:
        ----
            nodes_file_path: Path to nodes TSV file
            ontology_name: Name of the ontology (e.g., "go", "chebi", "uberon", "ncbitaxon")

        """
        from kg_microbe.utils.ontology_utils import (
            assert_go_version_alignment,
            get_chebi_category,
            get_foodon_category,
            get_go_category_by_aspect,
            get_ncbitaxon_category,
            get_pato_category,
            get_uberon_category,
            replace_deprecated_categories,
        )

        print(f"Fixing node categories for {ontology_name}...")

        df = pd.read_csv(nodes_file_path, sep="\t", low_memory=False)

        if ontology_name == "go":
            # Fail loudly if go.owl (→ go.db aspect map) and go.json (→ this TSV)
            # are different releases — otherwise MF/CC terms silently become
            # BiologicalProcess.
            from kg_microbe.utils.go_authority import load_go_authority

            assert_go_version_alignment(raw_dir=self.input_base_dir)
            go_authority = load_go_authority(self.input_base_dir)
            # Apply GO aspect-based categorization (cached in-memory dict, no OAK).
            print("  Applying GO aspect-based categorization...")

            def fix_go_category(row):
                """Fix GO category based on aspect (namespace)."""
                go_id = row["id"]
                if pd.notna(go_id) and go_id.startswith("GO:"):
                    return get_go_category_by_aspect(go_id, authority=go_authority)
                return replace_deprecated_categories(str(row["category"]))

            df["category"] = df.apply(fix_go_category, axis=1)

        elif ontology_name == "chebi":
            # Fix ChEBI categories: detect roles/macromolecules;
            # small molecules default to CHEBI_CATEGORY (biolink:ChemicalEntity)
            print("  Fixing ChEBI categories (detecting roles/macromolecules; default → CHEBI_CATEGORY)...")

            # Create ChEBI adapter once to avoid file descriptor leaks. Goes
            # through get_chebi_adapter so chebi.db is built from (and checked
            # against) the chebi.owl these nodes are emitted from.
            from kg_microbe.utils.ontology_utils import get_chebi_adapter

            chebi_adapter = get_chebi_adapter()

            def fix_chebi_category(row):
                """Fix ChEBI category (SmallMolecule/ChemicalRole) and replace deprecated categories."""
                chebi_id = row["id"]
                if pd.notna(chebi_id) and chebi_id.startswith("CHEBI:"):
                    # Get appropriate category (SmallMolecule or ChemicalRole)
                    # Pass the adapter to avoid creating new connections
                    return get_chebi_category(chebi_id, chebi_adapter)
                # For non-CHEBI IDs, just replace deprecated categories
                return replace_deprecated_categories(str(row["category"]))

            df["category"] = df.apply(fix_chebi_category, axis=1)

        elif ontology_name == "uberon":
            # Fix UBERON categories: all UBERON terms should be AnatomicalEntity
            print("  Fixing UBERON categories (all terms → AnatomicalEntity)...")

            def fix_uberon_category(row):
                """Fix UBERON category (all terms should be AnatomicalEntity)."""
                uberon_id = row["id"]
                if pd.notna(uberon_id) and uberon_id.startswith("UBERON:"):
                    return get_uberon_category(uberon_id)
                return replace_deprecated_categories(str(row["category"]))

            df["category"] = df.apply(fix_uberon_category, axis=1)

        elif ontology_name == "foodon":
            print("  Fixing FOODON categories (asserted organism branches; food material → Food)...")

            def fix_foodon_category(row):
                """Separate whole-organism classes from food materials."""
                foodon_id = row["id"]
                if pd.notna(foodon_id) and foodon_id.startswith("FOODON:"):
                    return get_foodon_category(foodon_id)
                return replace_deprecated_categories(str(row["category"]))

            df["category"] = df.apply(fix_foodon_category, axis=1)

        elif ontology_name == "pato":
            # PATO terms are qualities; madin_etal types them PhenotypicQuality (#1015).
            print("  Fixing PATO categories (all terms → PhenotypicQuality)...")

            def fix_pato_category(row):
                """Fix PATO category (all PATO terms are PhenotypicQuality; imports keep theirs)."""
                pato_id = row["id"]
                if pd.notna(pato_id) and pato_id.startswith("PATO:"):
                    return get_pato_category(pato_id)
                return replace_deprecated_categories(str(row["category"]))

            df["category"] = df.apply(fix_pato_category, axis=1)

        elif ontology_name == "ncbitaxon":
            # Fix NCBITaxon categories: all NCBITaxon terms should be OrganismTaxon
            print("  Fixing NCBITaxon categories (all terms → OrganismTaxon)...")

            def fix_ncbitaxon_category(row):
                """Fix NCBITaxon category (all terms should be OrganismTaxon)."""
                ncbitaxon_id = row["id"]
                if pd.notna(ncbitaxon_id) and ncbitaxon_id.startswith("NCBITaxon:"):
                    return get_ncbitaxon_category(ncbitaxon_id)
                return replace_deprecated_categories(str(row["category"]))

            df["category"] = df.apply(fix_ncbitaxon_category, axis=1)

        elif ontology_name == "ec":
            # Preserve the repository's EC activity/protein classification;
            # RHEA cross-references no longer pretend to be physical enablement.
            from kg_microbe.transform_utils.constants import EC_CATEGORY, EC_PREFIX

            print(f"  Fixing EC categories (all terms → {EC_CATEGORY})...")

            def fix_ec_category(row):
                """Force EC nodes to the EC category, else replace deprecated categories."""
                ec_id = row["id"]
                if pd.notna(ec_id) and ec_id.startswith(EC_PREFIX):
                    return EC_CATEGORY
                return replace_deprecated_categories(str(row["category"]))

            df["category"] = df.apply(fix_ec_category, axis=1)

        else:
            # For other ontologies, just replace deprecated categories
            print(f"  Replacing deprecated categories in {ontology_name}...")
            df["category"] = df["category"].apply(lambda x: replace_deprecated_categories(str(x)) if pd.notna(x) else x)

        # Write back
        df.to_csv(nodes_file_path, sep="\t", index=False)
        print(f"  Fixed categories for {ontology_name}")

    def post_process(self, name: str):
        """Post process specific nodes and edges files."""
        nodes_file = self.output_dir / f"{name}_nodes.tsv"
        edges_file = self.output_dir / f"{name}_edges.tsv"

        # Add knowledge_level/agent_type columns. (Metamodel-axiom edges are
        # dropped later in _normalize_schema, after KGX's biolink:->rdfs/owl/rdf
        # predicate remap, so the CURIE filter actually matches.)
        self._add_kgx_metadata_to_edges(edges_file)

        # Fix node categories: specialized handlers for go/chebi/uberon/ncbitaxon,
        # and a generic deprecated-category scrub for every other ontology so
        # imported xref rows (e.g. FOODON referencing CHEBI) don't leak
        # biolink:ChemicalSubstance/Macromolecule through to the merged KG.
        if nodes_file.exists():
            self._fix_node_categories(nodes_file, name)

        # Compile a regex pattern that matches any key in SPECIAL_PREFIXES
        pattern = re.compile("|".join(re.escape(key) for key in SPECIAL_PREFIXES.keys()))

        def _replace_special_prefixes(line):
            """Use the pattern to replace all occurrences of the keys with their values."""
            return pattern.sub(lambda match: SPECIAL_PREFIXES[match.group(0)], line)

        def _replace_quotation_marks(line, description_index):
            """Replace single and double quotation marks."""
            parts = line.split("\t")
            parts = [i.strip() for i in parts]
            parts[description_index] = parts[description_index].replace('"', "").replace("'", "")
            new_line = "\t".join(parts)
            return new_line

        # NOTE: ChEBI xref generation was removed here. ChEBI xrefs are now provided
        # by the unified chemical mappings file (unified_chemical_mappings.tsv.gz)
        # managed via the mappings/ directory and used by transforms through
        # ChemicalMappingLoader. See mappings/README.md for details.
        if name == "upa" or name == "mondo":
            makedirs(ONTOLOGIES_XREFS_DIR, exist_ok=True)
            # Get two columns from the nodes file: 'id' and 'xref'
            # The xref column is | separated and contains different prefixes
            # We need to make a 1-to-1 mapping between the prefixes and the id
            if name == "upa":
                xref_filepath = UNIPATHWAYS_XREFS_FILEPATH
                unipathways_xref_dict = {}
            elif name == "mondo":
                xref_filepath = MONDO_XREFS_FILEPATH
            with open(nodes_file, "r") as nf, open(xref_filepath, "w") as xref_file:
                for line in nf:
                    if line.startswith("id"):
                        # get the index for the term 'xref'
                        xref_index = line.strip().split("\t").index("xref")
                        xref_file.write("id\txref\n")
                        continue
                    line = _replace_special_prefixes(line)
                    parts = line.strip().split("\t")
                    subject = parts[0]
                    xrefs = parts[xref_index].split("|") if parts[xref_index] != "" else None
                    if xrefs and subject not in xrefs:
                        for xref in xrefs:
                            # Write a new tsv file with header ["id", "xref"]
                            xref_file.write(f"{subject}\t{xref}\n")
                            # Use unipathways xrefs elsewhere so write to dict
                            if name == "upa":
                                unipathways_xref_dict[subject] = xref

        if name == "mondo":
            with open(nodes_file, "r") as nf, open(edges_file, "r") as ef:
                # Update prefixes in nodes file
                new_nf_lines = []
                for line in nf:
                    if line.startswith("id"):
                        # get the index for the term 'id'
                        id_index = line.strip().split("\t").index(ID_COLUMN)
                        # get the index for the term 'category'
                        category_index = line.strip().split("\t").index(CATEGORY_COLUMN)
                        description_index = line.strip().split("\t").index(DESCRIPTION_COLUMN)
                        new_nf_lines.append(line)
                    else:
                        line = _replace_special_prefixes(line)
                        line = replace_category_ontology(line, id_index, category_index, raw_dir=self.input_base_dir)
                        line = _replace_quotation_marks(line, description_index)
                        new_nf_lines.append(line + "\n")
            # Rewrite nodes file
            with open(nodes_file, "w") as new_nf:
                for line in new_nf_lines:
                    new_nf.write(line)

        if name == "upa":
            # Keep track of new node IDs for edges file
            nodes_dictionary = defaultdict(list)
            with open(nodes_file, "r") as nf:
                add_lines = []
                for line in nf:
                    if line.startswith("id"):
                        # KGX's own header for this file. Kept so each row can be
                        # projected onto self.node_header by column name: KGX
                        # leaks subsets/meta/iri onto node rows, and padding
                        # positionally left those extra fields under a canonical
                        # 9-column header, producing a file pandas could not read
                        # (#1033).
                        source_header = line.strip().split("\t")
                        # get the index for the term 'id'
                        id_index = source_header.index(ID_COLUMN)
                        # get the index for the term 'xref'
                        xref_index = source_header.index(XREF_COLUMN)
                        # get the index for the term 'category'
                        category_index = source_header.index(CATEGORY_COLUMN)
                    else:
                        line = remove_unwanted_prefixes_from_node_xrefs(line, xref_index)
                        # For Reactions only
                        if any(
                            substring in line for substring in [UNIPATHWAYS_REACTION_PREFIX]
                        ):  # UNIPATHWAYS_COMPOUND_PREFIX,UNIPATHWAYS_ENZYMATIC_REACTION_PREFIX]):
                            new_lines, nodes_dictionary = replace_id_with_xref(
                                line,
                                xref_index,
                                id_index,
                                category_index,
                                nodes_dictionary,
                                self.node_header,
                                source_header,
                            )
                            for new_line in new_lines:
                                if len(new_line) > 0:
                                    new_line = _replace_special_prefixes(new_line)
                                    add_lines.append(new_line + "\n")
                        # Add category only for nodes that are not added by another ingest, only Pathways
                        elif any(
                            substring in line for substring in [UNIPATHWAYS_PATHWAY_PREFIX]
                        ):  # ,UNIPATHWAYS_LINEAR_SUB_PATHWAY_PREFIX]):
                            new_line = replace_category_for_unipathways(
                                line, id_index, category_index, self.node_header, source_header
                            )
                            if len(new_line) > 0:
                                add_lines.append(new_line + "\n")
                        # Not adding any other node types except what is specified
                        # else:
                        #    add_line = line + "\n"
            # Rewrite nodes file
            with open(nodes_file, "w") as new_nf:
                new_nf.write("\t".join(self.node_header) + "\n")
                for line in add_lines:
                    new_nf.write(line)

            edges_df = pd.DataFrame(columns=self.edge_header)
            # These legacy helpers use positional fields and strip whitespace.
            # Project by header name first, so an optional/blank KGX id or any
            # extra emitted metadata cannot shift biological or source fields.
            subject_index = self.edge_header.index(SUBJECT_COLUMN)
            predicate_index = self.edge_header.index(PREDICATE_COLUMN)
            object_index = self.edge_header.index(OBJECT_COLUMN)
            relation_index = self.edge_header.index(RELATION_COLUMN)
            with open(edges_file, "r", newline="") as ef:
                reader = csv.DictReader(ef, delimiter="\t")
                source_header = reader.fieldnames or []
                if not {SUBJECT_COLUMN, PREDICATE_COLUMN, OBJECT_COLUMN, RELATION_COLUMN} <= set(source_header):
                    raise ValueError(f"UPA intermediate edge file has an invalid header: {edges_file}")
                for original in reader:
                    if None in original or any(value is None for value in original.values()):
                        raise ValueError(f"UPA intermediate edge row does not match its header: {edges_file}")
                    row = {column: original.get(column, "") for column in self.edge_header}
                    # A present modern column, including an explicit blank,
                    # takes precedence. This matches _normalize_schema below.
                    if PRIMARY_KNOWLEDGE_SOURCE_COLUMN not in source_header:
                        row[PRIMARY_KNOWLEDGE_SOURCE_COLUMN] = original.get("knowledge_source", "")
                    line = check_wanted_pairs("\t".join(row.values()), subject_index, object_index)
                    if not line:
                        continue
                    for edge_line in replace_triples_with_labels(
                        line, subject_index, object_index, predicate_index, relation_index, nodes_dictionary
                    ):
                        parts = edge_line.rstrip("\r\n").split("\t")
                        if len(parts) > len(self.edge_header):
                            raise ValueError(f"UPA rewritten edge exceeds its canonical header: {edges_file}")
                        # The unchanged helper can strip trailing empty fields.
                        parts.extend([""] * (len(self.edge_header) - len(parts)))
                        df = pd.DataFrame([parts], columns=self.edge_header)
                        edges_df = pd.concat([edges_df, df], ignore_index=True)
            # First write existing edges to file before establishing transitive relationships
            edges_df.to_csv(edges_file, sep="\t", index=False)

            # Add edges between GO and pathways using enzymatic reactions GO xrefs
            transitive_df_uer_go = establish_transitive_relationship(
                edges_file,
                UNIPATHWAYS_INCLUDE_PAIRS[1][0],
                UNIPATHWAYS_INCLUDE_PAIRS[1][1],
                PART_OF_PREDICATE,
                UNIPATHWAYS_INCLUDE_PAIRS[2][1],
            )
            # Replace UER with GO. Keep PART_OF — after substitution the edge
            # reads "GO molecular function part_of UPA pathway", which respects
            # biolink domain/range. Using ENABLED_BY here was wrong: enabled_by
            # expects Protein/Gene as object, not a pathway.
            transitive_df_uer_go = transitive_df_uer_go[
                (transitive_df_uer_go[SUBJECT_COLUMN].str.contains(UNIPATHWAYS_ENZYMATIC_REACTION_PREFIX))
                & (transitive_df_uer_go[OBJECT_COLUMN].str.contains(UNIPATHWAYS_PATHWAY_PREFIX))
            ]
            transitive_df_uer_go = transitive_df_uer_go.map(lambda x: unipathways_xref_dict.get(x, x))

            # Only add GO relations, not EC
            transitive_df_uer_go = transitive_df_uer_go[transitive_df_uer_go[SUBJECT_COLUMN].str.contains(GO_PREFIX)]

            # Add the list as a new row to the DataFrame
            edges_df = pd.concat([edges_df, transitive_df_uer_go], ignore_index=True)

            # These late-added curated xrefs need their own metadata (#1071).
            upa_go_df = self._make_upa_go_xref_edges(unipathways_xref_dict)
            # Add the list as a new row to the DataFrame
            edges_df = pd.concat([edges_df, upa_go_df], ignore_index=True)
            # Write existing edges to file before establishing more transitive relationships
            edges_df.to_csv(edges_file, sep="\t", index=False)

            # Consolidate paths into 1 edge
            # For triples with rhea prefix for reactions, get rhea to pathway edge
            transitive_df_rhea = establish_transitive_relationship_multiple(
                edges_file,
                RHEA_NEW_PREFIX,
                [UNIPATHWAYS_INCLUDE_PAIRS[0][1], UNIPATHWAYS_INCLUDE_PAIRS[1][1]],
                [PART_OF_PREDICATE, PART_OF_PREDICATE],
                [[UNIPATHWAYS_INCLUDE_PAIRS[1][1]], [UNIPATHWAYS_INCLUDE_PAIRS[2][1]]],
            )
            # For triples with Unipathways reaction prefix for reactions
            transitive_df_uni = establish_transitive_relationship_multiple(
                edges_file,
                UNIPATHWAYS_INCLUDE_PAIRS[0][0],
                [UNIPATHWAYS_INCLUDE_PAIRS[0][1], UNIPATHWAYS_INCLUDE_PAIRS[1][1]],
                [PART_OF_PREDICATE, PART_OF_PREDICATE],
                [[UNIPATHWAYS_INCLUDE_PAIRS[1][1]], [UNIPATHWAYS_INCLUDE_PAIRS[2][1]]],
            )
            transitive_df = pd.concat([transitive_df_rhea, transitive_df_uni], ignore_index=True)
            # Remove unnecessary edges between intermediate prefixes
            transitive_df = remove_unwanted_prefixes_from_edges(transitive_df)
            # Rewrite edges file
            transitive_df.to_csv(edges_file, sep="\t", index=False)
            drop_duplicates(edges_file)
            # Rewrite prefixes
            new_edge_lines = []
            with open(edges_file, "r") as ef:
                # Write a new edges tsv file with same edge header
                for line in ef:
                    new_edge_lines.append(_replace_special_prefixes(line))
            # Rewrite edges file
            with open(edges_file, "w") as new_ef:
                for line in new_edge_lines:
                    new_ef.write(line)

        if name == "ec":  # or name == "rhea":
            with open(nodes_file, "r") as nf, open(edges_file, "r") as ef:
                # Update prefixes in nodes file
                new_nf_lines = []
                for line in nf:
                    if line.startswith("id"):
                        # get the index for the term 'id'
                        id_index = line.strip().split("\t").index(ID_COLUMN)
                        # get the index for the term 'category'
                        category_index = line.strip().split("\t").index(CATEGORY_COLUMN)
                        new_nf_lines.append(line)
                    else:
                        line = _replace_special_prefixes(line)
                        line = replace_category_ontology(line, id_index, category_index, raw_dir=self.input_base_dir)
                        new_nf_lines.append(line + "\n")
                # Retain the actual intermediate column order while rewriting
                # values. Replacing it with the seven canonical column names
                # shifts every field when KGX emits id/category/meta columns.
                # The final _normalize_schema step owns name-based projection.
                incoming_edge_header = ef.readline()
                if not {SUBJECT_COLUMN, PREDICATE_COLUMN, OBJECT_COLUMN, RELATION_COLUMN} <= set(
                    incoming_edge_header.rstrip("\r\n").split("\t")
                ):
                    raise ValueError(f"EC intermediate edge file has an invalid header: {edges_file}")
                new_ef_lines = []
                for line in ef:
                    line = _replace_special_prefixes(line)
                    new_ef_lines.append(line)
            if name == "ec":
                # Remove UniProt and TrEMBL nodes since accounted for elsewhere
                protein_prefixes = [UNIPROT_PREFIX, TREMBL_PREFIX]
                new_nf_lines = [line for line in new_nf_lines if not any(prefix in line for prefix in protein_prefixes)]
                new_ef_lines = [line for line in new_ef_lines if not any(prefix in line for prefix in protein_prefixes)]
            # elif name == "rhea":
            #     # Remove debio nodes that account for direction, since already there in inverse triples
            #     # Note that CHEBI and EC predicates do not match Rhea pyobo, so removing them
            #     rhea_exclusions = ["debio", UNIPROT_PREFIX, CHEBI_PREFIX, EC_PREFIX]
            #     new_nf_lines = [
            #         line for line in new_nf_lines if not any(sub in line for sub in rhea_exclusions)
            #     ]
            #     new_ef_lines = [
            #         line for line in new_ef_lines if not any(sub in line for sub in rhea_exclusions)
            #     ]
            # Rewrite nodes file
            with open(nodes_file, "w") as new_nf:
                for line in new_nf_lines:
                    new_nf.write(line)

            # Rewrite edges file
            with open(edges_file, "w") as new_ef:
                new_ef.write(incoming_edge_header)
                for line in new_ef_lines:
                    new_ef.write(line)

        else:
            # Process and write the nodes file
            with open(nodes_file, "r") as nf, open(nodes_file.with_suffix(".temp.tsv"), "w") as new_nf:
                for line in nf:
                    new_nf.write(_replace_special_prefixes(line))

            # Replace the original file with the modified one
            nodes_file.with_suffix(".temp.tsv").replace(nodes_file)

            # Process and write the edges file
            with open(edges_file, "r") as ef, open(edges_file.with_suffix(".temp.tsv"), "w") as new_ef:
                for line in ef:
                    new_ef.write(_replace_special_prefixes(line))

            # Replace the original file with the modified one
            edges_file.with_suffix(".temp.tsv").replace(edges_file)

        # Remove IRI column that KGX may have auto-generated
        self._remove_iri_column(nodes_file)

        # Convert URL-formatted node IDs to CURIEs
        self._convert_urls_to_curies(nodes_file, edges_file)

        # Normalize schema to canonical node_header / edge_header shape
        self._normalize_schema(nodes_file, edges_file)

    def _make_upa_go_xref_edges(self, xrefs: dict) -> pd.DataFrame:
        """
        Project curated UPA pathway GO xrefs, with explicit metadata (#1071).

        These rows are added after the initial ontology metadata pass. They
        restate supplied cross-references, unlike transitive path deductions;
        use the existing curated-ontology assertion policy here, not a late
        blanket fill that could overwrite metadata on other edge families.
        """
        edges = pd.DataFrame(list(xrefs.items()), columns=[ID_COLUMN, XREF_COLUMN])
        edges = edges.loc[edges[ID_COLUMN].str.contains("UPA:UPA") & edges[XREF_COLUMN].str.contains(GO_PREFIX)].copy()
        edges.rename(columns={XREF_COLUMN: SUBJECT_COLUMN, ID_COLUMN: OBJECT_COLUMN}, inplace=True)
        edges[PREDICATE_COLUMN] = RELATED_TO_PREDICATE
        edges[RELATION_COLUMN] = RELATED_TO_RELATION
        edges[PRIMARY_KNOWLEDGE_SOURCE_COLUMN] = self.ONTOLOGY_KNOWLEDGE_SOURCES.get("upa", "infores:upa")
        edges[KNOWLEDGE_LEVEL_COLUMN] = KNOWLEDGE_ASSERTION
        edges[AGENT_TYPE_COLUMN] = MANUAL_AGENT
        return edges

    def _remove_iri_column(self, nodes_file: Path) -> None:
        """Remove IRI column from nodes file since it's not used downstream."""
        import pandas as pd

        # Read nodes file
        df = pd.read_csv(nodes_file, sep="\t", low_memory=False)

        # Remove IRI column if it exists (KGX may auto-generate it)
        if "iri" in df.columns:
            df = df.drop(columns=["iri"])
            df.to_csv(nodes_file, sep="\t", index=False)

    def _normalize_schema(self, nodes_file: Path, edges_file: Path) -> None:
        """
        Enforce canonical KGX-TSV schema on KGX-generated ontology outputs.

        Why this step exists: the native KGX OBO reader and streaming TsvSink
        retain obograph artifacts in the intermediate output. This includes
        three categories of columns that are not part of the KGX-TSV spec
        (https://github.com/biolink/kgx/blob/master/specification/kgx-format.md):

          * Nodes: `subsets`, `meta` (obograph-only), `iri` (RDF roundtrip)
          * Edges: `id` (biolink 3.x optional; not emitted by other KG-Microbe
            transforms), `meta` (obograph-only), and the deprecated
            `knowledge_source` column (superseded by `primary_knowledge_source`
            in biolink 3.x).

        Conversion preserves reader-emitted fields until this explicit
        canonical source projection. The normalization below retains the
        existing column policy and is intentionally idempotent: already
        canonical headers do not require another projection change.

        Resulting shape:
          * nodes: exactly `self.node_header` (base Transform canonical shape)
          * edges: exactly `self.edge_header` (renames knowledge_source →
            primary_knowledge_source when only the former is present)
        """
        if nodes_file.is_file():
            df = pd.read_csv(nodes_file, sep="\t", low_memory=False)
            dropped_node_cols = [c for c in ("subsets", "meta", "iri") if c in df.columns]
            added_node_cols = [c for c in self.node_header if c not in df.columns]
            for extra in dropped_node_cols:
                df = df.drop(columns=[extra])
            for col in added_node_cols:
                df[col] = ""
            df = df[self.node_header]
            # Apply namespace-owned categories to imported terms too. The
            # per-file handlers cannot fix FOODON/PATO rows in ENVO, UBERON,
            # etc., and KGX later unions their stale OntologyClass category.
            df[CATEGORY_COLUMN] = [
                canonical_node_category(str(identifier), category)
                for identifier, category in zip(df[ID_COLUMN], df[CATEGORY_COLUMN], strict=True)
            ]
            before_metadata_filter = df
            df, dropped_metamodel_nodes = self._drop_metamodel_nodes(df)
            excluded = before_metadata_filter.loc[~before_metadata_filter.index.isin(df.index), [ID_COLUMN]].copy()
            individual_ids = getattr(self, "_annotation_individual_ids", set())
            property_ids = getattr(self, "_annotation_property_ids", set())
            excluded[ID_COLUMN] = excluded[ID_COLUMN].astype(str).map(compact_identifier)
            excluded["reason"] = [
                "annotation_only_contributor"
                if identifier in individual_ids
                else "declared_annotation_property"
                if identifier in property_ids
                else "metamodel_vocabulary"
                for identifier in excluded[ID_COLUMN]
            ]
            # Always write the header, so a later clean run cannot leave a
            # stale exclusion report from a previous ontology build.
            report_name = nodes_file.stem.removesuffix("_nodes") + "_metadata_exclusions.tsv"
            with atomic_write(nodes_file.with_name(report_name), encoding="utf-8", newline="") as report:
                excluded.to_csv(report, sep="\t", index=False, lineterminator="\n")
            df.to_csv(nodes_file, sep="\t", index=False)
            if dropped_metamodel_nodes:
                print(
                    f"  [_normalize_schema] {nodes_file.name}: dropped "
                    f"{dropped_metamodel_nodes} annotation-only node(s) (#1023/#1074); see {report_name}"
                )
            if dropped_node_cols or added_node_cols:
                print(f"  [_normalize_schema] {nodes_file.name}: dropped={dropped_node_cols} added={added_node_cols}")

        if edges_file.is_file():
            df = pd.read_csv(edges_file, sep="\t", dtype=str, keep_default_na=False)
            original_edges = df.copy()
            # Backstop against a header line reaching the body. The producer
            # fix lives in the ec branch above; this catches a leak from any
            # ontology and any future producer, and costs ~35 ms on the
            # 925 K-row ncbitaxon file.
            #
            # Filtered by content, not position: position is what failed
            # before. No real edge has "subject" as its subject — verified
            # across all 14 ontology edge files, ~1.7 M rows.
            if SUBJECT_COLUMN in df.columns:
                stray = df[SUBJECT_COLUMN].astype(str) == SUBJECT_COLUMN
                if stray.any():
                    print(f"  [_normalize_schema] {edges_file.name}: dropped {int(stray.sum())} stray header row(s)")
                    df = df[~stray]
            dropped_edge_cols = []
            renamed = False
            if "id" in df.columns:
                df = df.drop(columns=["id"])
                dropped_edge_cols.append("id")
            if "meta" in df.columns:
                df = df.drop(columns=["meta"])
                dropped_edge_cols.append("meta")
            if "knowledge_source" in df.columns and PRIMARY_KNOWLEDGE_SOURCE_COLUMN not in df.columns:
                df = df.rename(columns={"knowledge_source": PRIMARY_KNOWLEDGE_SOURCE_COLUMN})
                renamed = True
            elif "knowledge_source" in df.columns:
                df = df.drop(columns=["knowledge_source"])
                dropped_edge_cols.append("knowledge_source")
            added_edge_cols = [c for c in self.edge_header if c not in df.columns]
            for col in added_edge_cols:
                df[col] = ""
            df = df[self.edge_header]

            ontology_name = edges_file.stem.removesuffix("_edges")
            source = self.ONTOLOGY_KNOWLEDGE_SOURCES.get(ontology_name)
            if source:
                aliases = {"", f"{ontology_name}.json", f"{ontology_name}_removed_subset.json"}
                df[PRIMARY_KNOWLEDGE_SOURCE_COLUMN] = (
                    df[PRIMARY_KNOWLEDGE_SOURCE_COLUMN]
                    .fillna("")
                    .map(lambda value: source if value in aliases else value)
                )
            # RO has_role is specifically chemical role, not a generic attribute.
            # Preserve the exact originating relation and every unrelated edge.
            role_edges = (df[PREDICATE_COLUMN] == "biolink:has_attribute") & (df[RELATION_COLUMN] == "RO:0000087")
            df.loc[role_edges, PREDICATE_COLUMN] = "biolink:has_chemical_role"
            if ontology_name == "foodon":
                from kg_microbe.utils.foodon_classification import foodon_dispositions

                dispositions = foodon_dispositions()
                bad_targets = {
                    identifier: row["evidence"]
                    for identifier, row in dispositions.items()
                    if row["disposition"] == "invalid_in_taxon_target"
                }
                invalid = (
                    (df[PREDICATE_COLUMN] == "biolink:in_taxon")
                    & (df[RELATION_COLUMN] == "RO:0002162")
                    & df[OBJECT_COLUMN].isin(bad_targets)
                )
                quarantine = original_edges.loc[df.index[invalid]].copy()
                quarantine["reason"] = quarantine[OBJECT_COLUMN].map(bad_targets)
                with atomic_write(
                    edges_file.with_name("foodon_model_quarantine.tsv"), encoding="utf-8", newline=""
                ) as stream:
                    quarantine.to_csv(stream, sep="\t", index=False, lineterminator="\n")
                df = df.loc[~invalid]

            # KGX/obograph emits OWL/RDF meta-predicates under the `biolink:`
            # namespace by default (e.g. `biolink:subPropertyOf`). Those are
            # not valid biolink predicates. Remap to their proper namespaces
            # in both the `predicate` and `relation` columns so the output
            # validates cleanly and round-trips back to OWL semantics.
            owl_meta_predicate_map = {
                "biolink:subPropertyOf": "rdfs:subPropertyOf",
                "biolink:inverseOf": "owl:inverseOf",
                "biolink:type": "rdf:type",
            }
            # Bare tokens that may appear in the `relation` column (OAK emits
            # just the local name when it cannot find an RO mapping).
            owl_meta_relation_map = {
                "subPropertyOf": "rdfs:subPropertyOf",
                "inverseOf": "owl:inverseOf",
                "type": "rdf:type",
            }
            if "predicate" in df.columns:
                df["predicate"] = df["predicate"].replace(owl_meta_predicate_map)
                # Belt-and-braces: obograph can emit bare local names (e.g.
                # ``subPropertyOf``) rather than the biolink:-prefixed form, so
                # normalise those too before the metamodel drop below.
                df["predicate"] = df["predicate"].replace(owl_meta_relation_map)
            if "relation" in df.columns:
                df["relation"] = df["relation"].replace(owl_meta_relation_map)
                # Also catch cases where `relation` mistakenly got the biolink
                # prefix too (belt-and-braces — same-row consistency).
                df["relation"] = df["relation"].replace(owl_meta_predicate_map)

            # Drop ontology metamodel-axiom edges now that predicates are in
            # their final CURIE form (post the biolink:->rdfs/owl/rdf remap
            # above). These property-level / typing statements are not biolink
            # entity relationships. Nodes are left untouched.
            df, dropped_metamodel = self._drop_metamodel_edges(df)
            annotation_ids = getattr(self, "_annotation_property_ids", set()) | getattr(
                self, "_annotation_individual_ids", set()
            )
            if annotation_ids:
                # Annotation *predicates* remain in metadata. Only graph
                # endpoints purporting to describe an annotation as an
                # entity are removed with their non-entity node.
                before = len(df)
                df = df[
                    ~(
                        df[SUBJECT_COLUMN].astype(str).map(compact_identifier).isin(annotation_ids)
                        | df[OBJECT_COLUMN].astype(str).map(compact_identifier).isin(annotation_ids)
                    )
                ]
                dropped_metamodel += before - len(df)

            df = self._quarantine_reviewed_self_loops(df, original_edges, edges_file)
            df.to_csv(edges_file, sep="\t", index=False)
            if dropped_metamodel:
                print(
                    f"  [_normalize_schema] {edges_file.name}: dropped "
                    f"{dropped_metamodel} metamodel edge(s) "
                    "(rdfs:subPropertyOf/owl:inverseOf/rdf:type)"
                )
            if dropped_edge_cols or added_edge_cols or renamed:
                rename_note = " rename(knowledge_source→primary_knowledge_source)" if renamed else ""
                print(
                    f"  [_normalize_schema] {edges_file.name}: "
                    f"dropped={dropped_edge_cols} added={added_edge_cols}{rename_note}"
                )

    def _quarantine_reviewed_self_loops(
        self, edges: pd.DataFrame, original_edges: pd.DataFrame, edges_file: Path
    ) -> pd.DataFrame:
        """Exclude only reviewed signatures and retain every original pre-projection row in an audit."""
        columns = [SUBJECT_COLUMN, PREDICATE_COLUMN, OBJECT_COLUMN, RELATION_COLUMN]
        reasons = pd.Series("", index=edges.index, dtype=str)
        for signature, reason in _self_loop_exclusions().items():
            matched = edges[columns].eq(signature).all(axis=1)
            reasons.loc[matched] = reason
        excluded = reasons.ne("")
        report = edges_file.with_name(edges_file.stem.removesuffix("_edges") + "_self_loop_exclusions.tsv")
        fields = ["source_file", *columns, PRIMARY_KNOWLEDGE_SOURCE_COLUMN, "reason", "original_record_json"]
        # A clean rebuild must replace any earlier report with a header-only
        # file. Auditing precedes the graph write so audit failures abort the
        # exclusion. Nodes, raw ontologies and other relations stay untouched.
        with atomic_write(report, encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields, delimiter="\t", lineterminator="\n")
            writer.writeheader()
            for index, row in edges.loc[excluded].iterrows():
                writer.writerow(
                    {
                        "source_file": edges_file.name,
                        **{column: row[column] for column in [*columns, PRIMARY_KNOWLEDGE_SOURCE_COLUMN]},
                        "reason": reasons.loc[index],
                        "original_record_json": json.dumps(original_edges.loc[index].to_dict(), ensure_ascii=False),
                    }
                )
        if excluded.any():
            print(
                f"  [_normalize_schema] {edges_file.name}: quarantined {int(excluded.sum())} "
                f"reviewed self-loop edge(s); see {report.name}"
            )
        return edges.loc[~excluded]

    def _convert_urls_to_curies(self, nodes_file: Path, edges_file: Path) -> None:
        """Compact URLs and verified CURIE aliases consistently in node and edge files."""
        import pandas as pd

        from kg_microbe.utils.mapping_file_utils import uri_to_curie

        # Process nodes file
        df_nodes = pd.read_csv(nodes_file, sep="\t", low_memory=False)

        # Convert URL IDs to CURIEs
        if "id" in df_nodes.columns:
            for idx, node_id in df_nodes["id"].items():
                if isinstance(node_id, str):
                    curie = uri_to_curie(node_id)
                    df_nodes.at[idx, "id"] = curie

        # Save updated nodes file
        df_nodes.to_csv(nodes_file, sep="\t", index=False)

        # Edge-only references must compact as well: another ontology may own
        # the corresponding node, so a local node lookup is not sufficient.
        if edges_file.is_file():
            df_edges = pd.read_csv(edges_file, sep="\t", low_memory=False)

            # Update subject and object columns
            for col in ["subject", "object"]:
                if col in df_edges.columns:
                    df_edges[col] = df_edges[col].apply(lambda x: uri_to_curie(x) if isinstance(x, str) else x)

            # Save updated edges file
            df_edges.to_csv(edges_file, sep="\t", index=False)
