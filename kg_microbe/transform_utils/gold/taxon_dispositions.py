"""
Retain native GOLD referents without unsupported taxonomic identity (#1316).

The source labels do not establish strains. This producer policy preserves
native declarations and taxon associations, with complete original assertions
in a mandatory audit. Lexical equality is diagnostic, never identity: source
records and their native observations are retained. Existing trims and taxid
remapping remain separate decisions. No graph is edited during admission.
"""

import csv
import hashlib
import io
import json
import os
import re
import sqlite3
import tarfile
import tempfile
from collections import Counter
from pathlib import Path

from kg_microbe.merge_utils.source_admission import SourceAdmission
from kg_microbe.transform_utils.constants import (
    GOLD,
    IN_TAXON_PREDICATE,
    KNOWLEDGE_ASSERTION,
    MANUAL_AGENT,
    NAMED_THING_CATEGORY,
    NCBI_CATEGORY,
    RDFS_SUBCLASS_OF,
    RELATED_TO_PREDICATE,
    SUBCLASS_PREDICATE,
)
from kg_microbe.transform_utils.gold import selected_taxon_aliases
from kg_microbe.transform_utils.gold.alias_observations import AliasObservations
from kg_microbe.transform_utils.gold.fold_restoration import (
    AUDIT_FILE as RESTORATION_AUDIT_FILE,
)
from kg_microbe.transform_utils.gold.fold_restoration import (
    AUDIT_HEADER as RESTORATION_AUDIT_HEADER,
)
from kg_microbe.transform_utils.gold.fold_restoration import FoldRestoration
from kg_microbe.utils.atomic_io import atomic_write
from kg_microbe.utils.graph_canonicalization import compact_identifier
from kg_microbe.utils.source_finalization import SourceFinalizationRequired
from kg_microbe.utils.tsv_io import tsv_writer

ROOT = Path(__file__).resolve().parents[3]
POLICY_PATH = ROOT / "mappings/gold_taxon_dispositions.json"
AUDIT_FILE = "gold_taxon_dispositions.tsv"
CONTRACT_KEY = "taxonomy_dispositions"
POLICY_ROLE = "gold_taxon_disposition_policy"
NCBI_ROLE = "gold_taxon_disposition_ncbi"
TAXDUMP_ROLE = "gold_taxon_disposition_taxdump"
REQUIRED_INPUTS = (POLICY_ROLE,)
NATIVE_CATEGORY = "biolink:IndividualOrganism"
NODE_HEADER = ("id", "category", "name", "description", "xref", "provided_by", "synonym", "deprecated", "same_as")
EDGE_HEADER = (
    "subject",
    "predicate",
    "object",
    "relation",
    "primary_knowledge_source",
    "knowledge_level",
    "agent_type",
    "original_object",
)
AUDIT_HEADER = (
    "id",
    "disposition",
    "native_node_json",
    "native_taxon_assertions_json",
    "rejected_node_json",
    "rejected_edges_json",
    "emitted_node_json",
    "emitted_edges_json",
    "taxid_remaps_json",
    "native_inputs_json",
)
POLICY = {
    "version": 2,
    "decision": "retain_unverified_native_referents_without_taxon_identity",
    "native_category": NATIVE_CATEGORY,
    "output_category": NAMED_THING_CATEGORY,
    "native_predicate": IN_TAXON_PREDICATE,
    "output_predicate": RELATED_TO_PREDICATE,
    "native_relation": "preserve_literal_source_relation",
    "accepted_strain_evidence": [],
    "folds": "disabled_lexical_equality_is_diagnostic_not_identity",
    "taxon_remapping": "selected_native_taxdump_and_reviewed_selected_ontology_aliases",
    "interpretation": (
        "Unresolved original GOLD referent, not a newly reified database record; "
        "names and xrefs do not prove strain identity."
    ),
    "issue": "https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1316",
}


def _json(value):
    """Use lossless ASCII JSON inside quote-free TSV audit cells."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _digest(value):
    """Bind complete values, not selected hand-picked evidence fields."""
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _proof_payload(row):
    """Retain the declaration and native witness without repeating shared audit inputs in memory."""
    return _json(
        {
            **{
                key: row[key] for key in ("id", "native_node_json", "native_taxon_assertions_json", "emitted_node_json")
            },
            "complete_audit_sha256": _digest(row),
        }
    )


def _proof_inventory(proofs):
    """Stream a stable proof-inventory digest instead of expanding it into a second giant JSON blob."""
    digest = hashlib.sha256()
    for identifier in sorted(proofs):
        digest.update((identifier + "\t" + hashlib.sha256(proofs[identifier].encode()).hexdigest() + "\n").encode())
    return {"count": len(proofs), "sha256": digest.hexdigest()}


def gold_reference_requests(node_paths, edge_paths, *, own_gold=False, quoting=csv.QUOTE_NONE, row_reader=None):
    """Derive the exact request set from actual explicit members, never trust a receipt's empty claim."""
    read_rows = _rows if row_reader is None else row_reader
    requested = set()
    for path in node_paths:
        for item in read_rows(path, ("id", "name"), quoting=quoting):
            row = item["row"]
            identifier = compact_identifier(row["id"])
            if identifier.startswith("gold:") and (not own_gold or not row["name"]):
                requested.add(identifier)
    if not own_gold:
        for path in edge_paths:
            for item in read_rows(path, ("subject", "object"), quoting=quoting):
                requested.update(
                    identifier
                    for key in ("subject", "object")
                    if (identifier := compact_identifier(item["row"][key])).startswith("gold:")
                )
    return requested


def _rows(path, fields, *, quoting=csv.QUOTE_MINIMAL):
    """Stream strict complete rows and retain physical native coordinates."""
    with Path(path).open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream, delimiter="\t", quoting=quoting, strict=True)
        header = reader.fieldnames or []
        if len(header) != len(set(header)) or not set(fields).issubset(header):
            raise SourceFinalizationRequired(f"Invalid GOLD disposition input header: {path}")
        for row in reader:
            if None in row or any(value is None for value in row.values()):
                raise SourceFinalizationRequired(f"Malformed GOLD disposition row: {path}:{reader.line_num}")
            yield {"row": row, "ending_physical_line": reader.line_num, "full_row_sha256": _digest(row)}


def _normalise_label(text):
    """Reproduce historical equality for audit only, never as identity or strain evidence."""
    folded = re.sub(r"[\s_/-]+", " ", text.strip().lower())
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", "", folded)).strip()


def _declaration(native):
    """Preserve literal source name, including the real nameless native referent."""
    return dict(
        zip(
            NODE_HEADER,
            (
                native["id"],
                NAMED_THING_CATEGORY,
                native.get("name", ""),
                "",
                native.get("xref", ""),
                native.get("provided_by", "") or f"infores:{GOLD}",
                "",
                "",
                "",
            ),
            strict=True,
        )
    )


def _association(native, target):
    """Retain the native taxonomy field as association, not identity or class inclusion."""
    return dict(
        zip(
            EDGE_HEADER,
            (
                native["subject"],
                RELATED_TO_PREDICATE,
                target,
                native.get("relation", ""),
                native.get("primary_knowledge_source", "") or f"infores:{GOLD}",
                KNOWLEDGE_ASSERTION,
                MANUAL_AGENT,
                "",
            ),
            strict=True,
        )
    )


def _merges(path):
    """Parse the actual selected archive, retaining the literal remap witness."""
    result, witnesses = {}, {}
    if path is None:
        return result, witnesses
    with tarfile.open(path, "r:gz") as archive:
        try:
            stream = archive.extractfile("merged.dmp")
        except KeyError:
            stream = None
        if stream is None:
            return result, witnesses
        for line_no, literal in enumerate(io.TextIOWrapper(stream, encoding="utf-8"), 1):
            fields = [value.strip() for value in literal.split("|")]
            if len(fields) >= 2 and fields[0].isdigit() and fields[1].isdigit():
                old, new = f"NCBITaxon:{fields[0]}", f"NCBITaxon:{fields[1]}"
                if old in result and result[old] != new:
                    raise SourceFinalizationRequired("Conflicting GOLD retired-taxid mapping")
                result[old] = new
                witnesses[old] = {"member": "merged.dmp", "line": line_no, "literal": literal, "target": new}
    return result, witnesses


class _NativeIndex:
    """Disk-backed native cohort rejoin; never hold complete graph TSVs in memory."""

    def __init__(self, nodes, edges, ncbi, taxdump, trim, *, resolver=None):
        """Index complete native records and their historical and resolved taxon targets."""
        self.native_nodes, self.native_edges = nodes, edges
        self.resolver = resolver
        self.directory = tempfile.TemporaryDirectory(prefix="kgm-gold-taxonomy-")
        self.db = sqlite3.connect(str(Path(self.directory.name) / "native.sqlite"))
        self.db.execute("CREATE TABLE records(id TEXT PRIMARY KEY, node TEXT, retained INTEGER DEFAULT 1)")
        self.db.execute("CREATE TABLE parents(id TEXT, target TEXT, native TEXT, historical_target TEXT)")
        self.db.execute("CREATE INDEX parent_ids ON parents(id)")
        self.db.execute("CREATE TABLE labels(id TEXT PRIMARY KEY, name TEXT)")
        self.merges, self.remap_witnesses = _merges(taxdump)
        self.trim = trim
        # Only the selected NCBI declaration file decides trim/folds when present.
        label_file = ncbi if ncbi is not None else nodes
        for item in _rows(label_file, ("id", "name")):
            row = item["row"]
            if row["id"].startswith("NCBITaxon:"):
                try:
                    self.db.execute("INSERT INTO labels VALUES (?, ?)", (row["id"], row["name"]))
                except sqlite3.IntegrityError as error:
                    raise SourceFinalizationRequired("Duplicate selected GOLD taxon label") from error
        if trim and not self.db.execute("SELECT 1 FROM labels LIMIT 1").fetchone():
            raise SourceFinalizationRequired("GOLD trimmed taxon authority has no NCBITaxon: rows")
        self.native_count = 0
        for item in _rows(nodes, ("id", "category", "name")):
            row = item["row"]
            if row["category"] != NATIVE_CATEGORY:
                continue
            if not row["id"].startswith("gold:"):
                raise SourceFinalizationRequired("Native GOLD unresolved referent has an unexpected identifier")
            try:
                self.db.execute("INSERT INTO records(id,node) VALUES (?, ?)", (row["id"], _json(item)))
            except sqlite3.IntegrityError as error:
                raise SourceFinalizationRequired("Duplicate native GOLD unresolved referent") from error
            self.native_count += 1
        for item in _rows(edges, ("subject", "predicate", "object")):
            row = item["row"]
            if row["predicate"] != IN_TAXON_PREDICATE:
                continue
            historical_target = self.merges.get(row["object"], row["object"])
            target = resolver.resolve(row["object"]) if resolver is not None else historical_target
            if not self.db.execute("SELECT 1 FROM records WHERE id=?", (row["subject"],)).fetchone():
                raise SourceFinalizationRequired(
                    "GOLD in_taxon subject lacks its native IndividualOrganism declaration"
                )
            if not target.startswith("NCBITaxon:"):
                raise SourceFinalizationRequired("GOLD native taxonomy association has a non-taxon target")
            self.db.execute(
                "INSERT INTO parents VALUES (?, ?, ?, ?)", (row["subject"], target, _json(item), historical_target)
            )
        self.db.commit()
        self.dropped, self.folded, self.historical_folds = set(), {}, {}
        if trim:
            self.dropped = {
                row[0]
                for row in self.db.execute(
                    "SELECT DISTINCT p.id FROM parents p LEFT JOIN labels l ON p.target=l.id WHERE l.id IS NULL"
                )
            }
        cursor = self.db.execute(
            "SELECT r.id,r.node,p.historical_target,l.name FROM records r JOIN parents p ON r.id=p.id "
            "JOIN labels l ON l.id=p.historical_target WHERE (SELECT COUNT(*) FROM parents p2 WHERE p2.id=r.id)=1"
        )
        for identifier, payload, target, label in cursor:
            name = json.loads(payload)["row"].get("name", "")
            if identifier not in self.dropped and name and label and _normalise_label(name) == _normalise_label(label):
                self.historical_folds[identifier] = target
        self.db.executemany("UPDATE records SET retained=0 WHERE id=?", ((i,) for i in self.dropped))
        self.orphaned = set()
        without_parents = {
            row[0]
            for row in self.db.execute(
                "SELECT id FROM records WHERE retained=1 AND NOT EXISTS(SELECT 1 FROM parents p WHERE p.id=records.id)"
            )
        }
        if without_parents:
            # Keep the pre-existing orphan-cleanup decision unchanged. This
            # branch is absent in the current 471,702-record production cohort,
            # but native environment-only records must not gain a new lifecycle.
            from kg_microbe.transform_utils.gold.gold import GOLDTransform

            resolution, _ = GOLDTransform._ecosystem_resolution(None, nodes, edges)
            excluded = GOLDTransform._category_drop_set(None, nodes) | self.dropped
            if trim:
                for item in _rows(nodes, ("id",)):
                    identifier = item["row"]["id"]
                    mapped = (
                        resolver.resolve(identifier)
                        if resolver is not None
                        else self.merges.get(identifier, identifier)
                    )
                    if (
                        identifier.startswith("NCBITaxon:")
                        and not self.db.execute("SELECT 1 FROM labels WHERE id=?", (mapped,)).fetchone()
                    ):
                        excluded.add(identifier)
            before, after = set(), set()
            for item in _rows(edges, ("subject", "predicate", "object")):
                row = item["row"]
                subject, target = row["subject"], row["object"]
                before.update({subject, target} & without_parents)
                if subject in excluded or target in excluded:
                    continue
                if row["predicate"] == "biolink:occurs_in" and target in resolution and resolution[target] is None:
                    continue
                after.update({subject, target} & without_parents)
            self.orphaned = before - after
            self.db.executemany("UPDATE records SET retained=0 WHERE id=?", ((i,) for i in self.orphaned))
        self.db.commit()
        self.restorations = FoldRestoration(self, nodes, edges, ncbi)
        self.alias_observations = AliasObservations(self)

    def close(self):
        """Remove only this index's own isolated temporary workspace."""
        self.db.close()
        self.directory.cleanup()

    def identifiers(self):
        """Yield the independently reconstructed retained cohort in stable order."""
        return (row[0] for row in self.db.execute("SELECT id FROM records WHERE retained=1 ORDER BY id"))

    def evidence(self, identifier):
        """Rejoin a complete native declaration with every native taxon assertion."""
        result = self.db.execute("SELECT node FROM records WHERE id=? AND retained=1", (identifier,)).fetchone()
        if result is None:
            return None
        native = json.loads(result[0])
        parents, emitted, remaps = [], {}, {}
        for target, payload in self.db.execute(
            "SELECT target,native FROM parents WHERE id=? ORDER BY native", (identifier,)
        ):
            parent = json.loads(payload)
            parents.append(parent)
            edge = _association(parent["row"], target)
            key = (edge["subject"], edge["predicate"], edge["object"])
            if key in emitted and emitted[key] != edge:
                raise SourceFinalizationRequired("Ambiguous native GOLD association metadata cannot be deduplicated")
            emitted[key] = edge
            old = parent["row"]["object"]
            if old in self.remap_witnesses:
                remaps[old] = self.remap_witnesses[old]
            if self.resolver is not None and (witness := self.resolver.evidence_for(old)) is not None:
                remaps[old] = {"taxdump": remaps.get(old), "selected_authority_alias": witness}
        declaration = _declaration(native["row"])
        rejected_node = {**declaration, "category": NCBI_CATEGORY}
        edges = sorted(emitted.values(), key=_json)
        rejected = [{**edge, "predicate": SUBCLASS_PREDICATE, "relation": RDFS_SUBCLASS_OF} for edge in edges]
        return {
            "id": identifier,
            "disposition": "unresolved_native_referent_with_audited_taxon_association",
            "native_node_json": _json(native),
            "native_taxon_assertions_json": _json(parents),
            "rejected_node_json": _json(rejected_node),
            "rejected_edges_json": _json(rejected),
            "emitted_node_json": _json(declaration),
            "emitted_edges_json": _json(edges),
            "taxid_remaps_json": _json(remaps),
        }


class TaxonDispositions:
    """Bind source selection once, audit it, and protect completed output through finalization."""

    def __init__(self, transform, stack, crosswalk):
        """Bind actual selected native inputs before constructing the complete cohort."""
        self.transform, self.stack, self.crosswalk = transform, stack, crosswalk
        self.admission = SourceAdmission()
        self.snapshots = {}
        self.finished = False
        policy_path = self.consume(POLICY_ROLE, POLICY_PATH)
        if json.loads(policy_path.read_text()) != POLICY:
            raise SourceFinalizationRequired("GOLD unresolved-referent policy changed; review required")
        self.trim = os.environ.get("GOLD_APPLY_TAXON_TRIM", "true").strip().lower() not in ("false", "0", "no")
        selected_ncbi = transform.output_base_dir / "ontologies/ncbitaxon_nodes.tsv"
        selected_taxdump = transform.input_base_dir / "taxdump.tar.gz"
        self.optional = []
        self.ncbi = self._optional(NCBI_ROLE, selected_ncbi)
        self.taxdump = self._optional(TAXDUMP_ROLE, selected_taxdump)
        if self.trim and self.ncbi is None:
            raise FileNotFoundError("GOLD trim requires the selected NCBITaxon output")
        self.aliases = selected_taxon_aliases.prepare(
            transform, stack, crosswalk.nodes_path, crosswalk.edges_path, self.ncbi, self.taxdump
        )
        self.index = _NativeIndex(
            crosswalk.nodes_path, crosswalk.edges_path, self.ncbi, self.taxdump, self.trim, resolver=self.aliases
        )
        self.admission.capture_resolution(
            lambda: (id(self.index.alias_observations), id(self.index.alias_observations.verify_graph))
        )
        self._contract_json = None
        self._audit_identity = None
        self._restoration_identity = None

    def consume(self, role, path):
        """Keep actual original role receipts separate from caller-mutable snapshots."""
        self.admission.capture(path)
        stream = self.stack.enter_context(self.transform.consume_input(role, path))
        self.snapshots[role] = dict(self.transform.consumed_input_snapshots[role])
        return Path(stream.name)

    def _optional(self, role, path):
        """Bind presence/absence and lexical locator, not only bytes of a found file."""
        lexical = Path(path).absolute()
        present = lexical.is_file()
        expected = (str(lexical.resolve()), present)
        self.optional.append({"role": role, "path": str(lexical), "resolved": expected[0], "present": present})
        self.admission.capture_resolution(lambda: (str(lexical.resolve()), lexical.is_file()))
        return self.consume(role, lexical) if present else None

    def verify(self, *, output_dir=None, metadata_only=False):
        """Check active role bindings and original audit even on repeat/late publication."""
        self.index.restorations.verify_native_context()
        self.aliases.verify(self.transform.consumed_input_snapshots, output_dir=output_dir, metadata_only=metadata_only)
        for role, snapshot in self.snapshots.items():
            if self.transform.consumed_input_snapshots.get(role) != snapshot:
                raise SourceFinalizationRequired(f"GOLD taxonomy consumed role missing or rebound: {role}")
        self.crosswalk.verify_bindings(byte_verified=metadata_only)
        self.admission.verify(metadata_only=metadata_only)
        if self.finished:
            directory = Path(output_dir) if output_dir is not None else self.transform.output_dir
            self.index.alias_observations.verify_graph(directory / "edges.tsv", quoting=csv.QUOTE_MINIMAL)
            if _file_identity(directory / AUDIT_FILE) != self._audit_identity:
                raise SourceFinalizationRequired("GOLD taxonomy audit changed after source emission")
            if _file_identity(directory / RESTORATION_AUDIT_FILE) != self._restoration_identity:
                raise SourceFinalizationRequired("GOLD restoration audit changed after source emission")
            if self.contract() != json.loads(self._contract_json):
                raise SourceFinalizationRequired("GOLD taxonomy completed contract changed")

    def contract(self):
        """Return an independent serialization; zero cohorts still have a real audit."""
        if self._contract_json is None:
            raise SourceFinalizationRequired("GOLD taxonomy producer has not completed its mandatory audit")
        return json.loads(self._contract_json)

    def finish(self):
        """Verify exact emitted declarations/associations before publishing the mandatory audit."""
        self.aliases.finish(self.transform.output_dir)
        self.verify()
        output = self.transform.output_dir
        _verify_graph(self.index, output / "nodes.tsv", output / "edges.tsv")
        self.index.restorations.verify_graph(output / "edges.tsv", quoting=csv.QUOTE_MINIMAL)
        native_inputs = {
            role: snapshot
            for role, snapshot in self.transform.consumed_input_snapshots.items()
            if role in {"gold_native_nodes", "gold_native_edges", POLICY_ROLE, NCBI_ROLE, TAXDUMP_ROLE}
        }
        count, edge_count, digest = 0, 0, hashlib.sha256()
        with atomic_write(output / AUDIT_FILE, encoding="utf-8", newline="") as stream:
            writer = tsv_writer(stream, quoting=csv.QUOTE_NONE, quotechar=None)
            writer.writerow(AUDIT_HEADER)
            for identifier in self.index.identifiers():
                item = self.index.evidence(identifier)
                item["native_inputs_json"] = _json(native_inputs)
                writer.writerow([item[key] for key in AUDIT_HEADER])
                digest.update((_json(item) + "\n").encode())
                count += 1
                edge_count += len(json.loads(item["emitted_edges_json"]))
        self._audit_identity = _file_identity(output / AUDIT_FILE)
        restoration = _write_restoration_audit(self.index, output, native_inputs)
        self._restoration_identity = restoration["audit"]
        self._contract_json = _json(
            {
                "version": 2,
                "policy_sha256": _digest(POLICY),
                "apply_taxon_trim": self.trim,
                "native_count": self.index.native_count,
                "retained_count": count,
                "association_count": edge_count,
                "trimmed_count": len(self.index.dropped),
                "folded_count": len(self.index.folded),
                "historical_fold_count": len(self.index.historical_folds),
                "lexical_fold_restorations": restoration,
                "orphaned_count": len(self.index.orphaned),
                "cohort_sha256": digest.hexdigest(),
                "audit": self._audit_identity,
                "native_inputs": native_inputs,
                "optional_inputs": self.optional,
            }
        )
        self.finished = True
        self.verify()
        self.transform.record_producer_audit(AUDIT_FILE)
        self.transform.record_producer_audit(RESTORATION_AUDIT_FILE)
        self.transform.record_producer_audit(selected_taxon_aliases.AUDIT_FILE)


def _write_restoration_audit(index, output, native_inputs):
    """Persist complete old/new claim projections for every restored source record."""
    digest, count, dispositions = hashlib.sha256(), 0, Counter()
    path = output / RESTORATION_AUDIT_FILE
    with atomic_write(path, encoding="utf-8", newline="") as stream:
        writer = tsv_writer(stream, quoting=csv.QUOTE_NONE, quotechar=None)
        writer.writerow(RESTORATION_AUDIT_HEADER)
        for identifier in sorted(index.historical_folds):
            item = index.restorations.evidence(identifier)
            item["native_inputs_json"] = _json(native_inputs)
            writer.writerow([item[key] for key in RESTORATION_AUDIT_HEADER])
            digest.update((_json(item) + "\n").encode())
            count += 1
            dispositions.update(claim["disposition"] for claim in json.loads(item["claim_dispositions_json"]))
    return {
        "count": count,
        "cohort_sha256": digest.hexdigest(),
        "claim_dispositions": dict(dispositions),
        "audit": _file_identity(path),
    }


def _verify_restoration_audit(index, report, directory, native, admission, *, quoting):
    """Independently rejoin every saved restored claim to the consumed native snapshots."""
    contract = report["producer_native_inputs"][CONTRACT_KEY].get("lexical_fold_restorations")
    if not isinstance(contract, dict):
        raise SourceFinalizationRequired("Missing mandatory GOLD restoration contract")
    path = directory / RESTORATION_AUDIT_FILE
    if path.is_symlink() or admission.capture(path) != contract.get("audit"):
        raise SourceFinalizationRequired("GOLD mandatory restoration audit changed")
    for collection in ("producer_audit_members", "audit_members"):
        if report.get(collection, {}).get(RESTORATION_AUDIT_FILE) != contract["audit"]:
            raise SourceFinalizationRequired("GOLD restoration audit absent from mandatory inventory")
    identifiers = iter(sorted(index.historical_folds))
    count, digest, dispositions = 0, hashlib.sha256(), Counter()
    for item in _rows(path, RESTORATION_AUDIT_HEADER, quoting=csv.QUOTE_NONE):
        row = item["row"]
        identifier = next(identifiers, None)
        if row["id"] != identifier:
            raise SourceFinalizationRequired("GOLD restoration cohort incomplete, duplicated or reordered")
        expected = index.restorations.evidence(identifier)
        expected["native_inputs_json"] = _json(native)
        if row != expected:
            raise SourceFinalizationRequired("GOLD restoration audit disagrees with complete native evidence")
        digest.update((_json(row) + "\n").encode())
        count += 1
        dispositions.update(claim["disposition"] for claim in json.loads(row["claim_dispositions_json"]))
    if next(identifiers, None) is not None or contract != {
        "count": count,
        "cohort_sha256": digest.hexdigest(),
        "claim_dispositions": dict(dispositions),
        "audit": contract["audit"],
    }:
        raise SourceFinalizationRequired("GOLD restoration contract disagrees with complete native cohort")
    index.restorations.verify_graph(directory / "edges.tsv", quoting=quoting)


def _file_identity(path):
    """Hash regular exact audit bytes without following a substituted audit symlink."""
    if Path(path).is_symlink():
        raise SourceFinalizationRequired(f"GOLD audit is symlinked: {path}")
    return SourceAdmission().capture(path)


def _identity_strength(row):
    """Recognize finite identity/class predicates in either assertion field, including native IRIs."""
    identities = {
        "biolink:same_as",
        "biolink:exact_match",
        "biolink:close_match",
        SUBCLASS_PREDICATE,
        RDFS_SUBCLASS_OF,
        "owl:sameAs",
        "owl:equivalentClass",
        "skos:exactMatch",
        "skos:closeMatch",
    }
    for field in ("predicate", "relation"):
        value = row.get(field, "")
        # Recognize only these exact W3C identity vocabulary spellings. This
        # does not create a general HTTPS namespace or external ID rewrite.
        if value.startswith(
            (
                "https://www.w3.org/2002/07/owl#",
                "https://www.w3.org/2004/02/skos/core#",
                "https://www.w3.org/2000/01/rdf-schema#",
            )
        ):
            value = "http://" + value[len("https://") :]
        if compact_identifier(value) in identities:
            return True
    return False


def _verify_graph(index, nodes, edges, *, quoting=csv.QUOTE_MINIMAL):
    """Reconcile every native cohort member and association, not only headline counts."""
    index.alias_observations.verify_graph(edges, quoting=quoting)

    def retained(identifier):
        """Distinguish excluded native records from unrelated ecosystem/external declarations."""
        return index.db.execute("SELECT retained FROM records WHERE id=?", (identifier,)).fetchone()

    alias_declarations = {}
    if index.resolver is not None:
        for original in selected_taxon_aliases.FINITE_IDS:
            witness = index.resolver.evidence_for(original)
            if witness is not None:
                selected = json.loads(witness["selected_declaration_json"])["row"]
                alias_declarations[selected["id"]] = {key: selected.get(key, "") for key in NODE_HEADER}
        if alias_declarations:
            for item in _rows(index.native_nodes, ("id",)):
                # A native replacement row remains the existing producer's
                # authority. Only absent-target fallbacks use selected metadata.
                alias_declarations.pop(item["row"]["id"], None)
    seen_aliases = set()

    index.db.execute("CREATE TEMP TABLE IF NOT EXISTS observed_nodes(id TEXT PRIMARY KEY)")
    index.db.execute("CREATE TEMP TABLE IF NOT EXISTS observed_edges(id TEXT, edge TEXT, PRIMARY KEY(id,edge))")
    index.db.execute("DELETE FROM observed_nodes")
    index.db.execute("DELETE FROM observed_edges")
    for item in _rows(nodes, ("id", "category", "name"), quoting=quoting):
        row = item["row"]
        if row["id"] in alias_declarations:
            if (
                row["id"] in seen_aliases
                or {key: row.get(key, "") for key in NODE_HEADER} != alias_declarations[row["id"]]
            ):
                raise SourceFinalizationRequired("GOLD selected alias target declaration changed")
            seen_aliases.add(row["id"])
        expected = index.evidence(row["id"])
        if expected is None:
            native = retained(compact_identifier(row["id"]))
            if native is not None or (
                compact_identifier(row["id"]).startswith("gold:") and NAMED_THING_CATEGORY in row["category"].split("|")
            ):
                raise SourceFinalizationRequired(f"GOLD declaration is outside the audited native cohort: {row['id']}")
            continue
        if {key: row.get(key, "") for key in NODE_HEADER} != json.loads(expected["emitted_node_json"]):
            raise SourceFinalizationRequired(f"GOLD native declaration was changed: {row['id']}")
        try:
            index.db.execute("INSERT INTO observed_nodes VALUES (?)", (row["id"],))
        except sqlite3.IntegrityError as error:
            raise SourceFinalizationRequired("Duplicate unresolved GOLD declaration") from error
    if seen_aliases != alias_declarations.keys():
        raise SourceFinalizationRequired("GOLD selected alias target declaration missing")
    for item in _rows(edges, ("subject", "predicate", "object"), quoting=quoting):
        row = item["row"]
        native_endpoints = {endpoint: retained(compact_identifier(row[endpoint])) for endpoint in ("subject", "object")}
        if any(native is not None and not native[0] for native in native_endpoints.values()):
            raise SourceFinalizationRequired("GOLD assertion references an excluded native referent")
        if any(native is not None for native in native_endpoints.values()) and _identity_strength(row):
            raise SourceFinalizationRequired("Unsupported identity or class assertion on unresolved GOLD referent")
        expected = index.evidence(row["subject"])
        if expected is None or not row["object"].startswith("NCBITaxon:"):
            continue
        assertion = {key: row.get(key, "") for key in EDGE_HEADER}
        if assertion not in json.loads(expected["emitted_edges_json"]):
            raise SourceFinalizationRequired(f"Unsupported GOLD taxon assertion: {row['subject']}")
        try:
            index.db.execute("INSERT INTO observed_edges VALUES (?,?)", (row["subject"], _json(assertion)))
        except sqlite3.IntegrityError as error:
            raise SourceFinalizationRequired("Duplicate unresolved GOLD taxon association") from error
    for identifier in index.identifiers():
        if not index.db.execute("SELECT 1 FROM observed_nodes WHERE id=?", (identifier,)).fetchone():
            raise SourceFinalizationRequired(f"Missing unresolved native GOLD declaration: {identifier}")
        expected = index.evidence(identifier)
        observed = [row[0] for row in index.db.execute("SELECT edge FROM observed_edges WHERE id=?", (identifier,))]
        if Counter(observed) != Counter(_json(edge) for edge in json.loads(expected["emitted_edges_json"])):
            raise SourceFinalizationRequired(f"Missing GOLD taxon association: {identifier}")


class _RejoinedAudit:
    """Request-local completed rejoin, sealed to the exact admitted bytes and original proof payloads."""

    def __init__(self, report, report_path, proofs, requested_ids, admission):
        """Seal completed native rejoin evidence within one retained admission."""
        self._report = _json(report)
        self._path = Path(report_path).absolute()
        self._proofs = dict(proofs)
        self._looked_up = set(requested_ids)
        original_report, original_path = self._report, self._path
        original_proofs, original_lookups = dict(proofs), set(requested_ids)
        blank_ids = {
            key for key, payload in proofs.items() if not json.loads(json.loads(payload)["emitted_node_json"])["name"]
        }

        def verify():
            """Reject replacement or mutation of the original rejoin cache."""
            if (
                self._report != original_report
                or self._path != original_path
                or self._proofs != original_proofs
                or self._looked_up != original_lookups
                or self.select is not select
            ):
                raise SourceFinalizationRequired("GOLD completed native rejoin cache changed")
            return True

        def select(current_report, requested):
            """Load additional proofs only from the exact already-admitted audit bytes."""
            admission.verify(metadata_only=True)
            verify()
            if _json(current_report) != original_report:
                raise SourceFinalizationRequired("GOLD completed rejoin report was rebound or restamped")
            missing = set(requested) - original_lookups - self._proofs.keys()
            if missing:
                # These exact audit bytes already passed a complete native
                # rejoin in this admission. Only retain new requested proofs.
                for item in _rows(original_path.parent / AUDIT_FILE, AUDIT_HEADER, quoting=csv.QUOTE_NONE):
                    row = item["row"]
                    if row["id"] in missing:
                        original_proofs[row["id"]] = self._proofs[row["id"]] = _proof_payload(row)
                original_lookups.update(missing)
                self._looked_up.update(missing)
            admission.verify(metadata_only=True)
            selected = set(requested) | blank_ids
            return {key: value for key, value in self._proofs.items() if key in selected}

        self.select = select
        admission.capture_resolution(verify)


def _verify_contract(report, report_path, admission, *, requested_ids=()):
    """Reuse only a fully verified exact report within this retained admission."""
    admission.verify(metadata_only=True)
    registry = getattr(admission, "_gold_taxon_rejoins", None)
    if registry is None:
        registry = {}
        admission._gold_taxon_rejoins = registry
        admission.capture_resolution(lambda: id(getattr(admission, "_gold_taxon_rejoins", None)))
    key = str(Path(report_path).absolute())
    if key not in registry:
        proofs = _rejoin_contract(report, report_path, admission, requested_ids=requested_ids)
        cache = _RejoinedAudit(report, report_path, proofs, requested_ids, admission)
        registry[key] = cache
        admission.capture_resolution(lambda: id(registry.get(key)))
    return registry[key].select(report, requested_ids)


def _rejoin_contract(report, report_path, admission, *, requested_ids=()):
    """Independently rejoin the complete saved audit to actual selected native bytes."""
    contract = report.get("producer_native_inputs", {}).get(CONTRACT_KEY)
    if (
        not isinstance(contract, dict)
        or contract.get("version") != 2
        or contract.get("policy_sha256") != _digest(POLICY)
    ):
        raise SourceFinalizationRequired("Missing reviewed GOLD taxonomy contract")
    snapshots = report.get("consumed_inputs", {})
    native = contract.get("native_inputs", {})
    required = {POLICY_ROLE, "gold_native_nodes", "gold_native_edges"}
    if not isinstance(native, dict) or not required.issubset(native):
        raise SourceFinalizationRequired("Missing GOLD taxonomy native receipts")
    for role, expected in native.items():
        if snapshots.get(role) != expected or admission.capture(expected["path"])["sha256"] != expected["sha256"]:
            raise SourceFinalizationRequired(f"GOLD native receipt changed: {role}")
    raw = Path(report.get("raw_input_directory", ""))
    origins = {
        POLICY_ROLE: POLICY_PATH,
        "gold_native_nodes": raw / "gold/GOLD_nodes.tsv",
        "gold_native_edges": raw / "gold/GOLD_edges.tsv",
    }
    for role, expected in origins.items():
        if Path(native[role]["path"]).resolve() != expected.resolve():
            raise SourceFinalizationRequired(f"GOLD native receipt origin changed: {role}")
    if json.loads(admission.capture(POLICY_PATH, retain=True)) != POLICY:
        raise SourceFinalizationRequired("GOLD unresolved-referent policy changed")
    directory = Path(report_path).parent
    optional = contract.get("optional_inputs")
    if not isinstance(optional, list) or len(optional) != 2:
        raise SourceFinalizationRequired("GOLD taxonomy optional-input state missing")
    paths = {NCBI_ROLE: directory.parent / "ontologies/ncbitaxon_nodes.tsv", TAXDUMP_ROLE: raw / "taxdump.tar.gz"}
    selected = {}
    for role, path in paths.items():
        items = [item for item in optional if item.get("role") == role]
        if len(items) != 1:
            raise SourceFinalizationRequired("GOLD taxonomy optional-input roles changed")
        item = items[0]
        lexical = Path(item.get("path", ""))
        actual = (str(lexical.resolve()), lexical.is_file())
        if lexical.absolute() != path.absolute() or actual != (item.get("resolved"), item.get("present")):
            raise SourceFinalizationRequired("GOLD taxonomy selected optional input changed")
        admission.capture_resolution(lambda p=lexical: (str(p.resolve()), p.is_file()))
        if item["present"]:
            if role not in native or Path(native[role]["path"]).resolve() != path.resolve():
                raise SourceFinalizationRequired("GOLD taxonomy actual optional read missing")
            selected[role] = path
        elif role in native or role in snapshots:
            raise SourceFinalizationRequired("GOLD taxonomy absent input has a contradictory receipt")
    if set(native) != required | selected.keys() or not isinstance(contract.get("apply_taxon_trim"), bool):
        raise SourceFinalizationRequired("GOLD taxonomy native input inventory changed")
    if contract["apply_taxon_trim"] and NCBI_ROLE not in selected:
        raise SourceFinalizationRequired("GOLD trimmed cohort lacks its selected NCBI authority")
    audit = directory / AUDIT_FILE
    if audit.is_symlink() or admission.capture(audit) != contract.get("audit"):
        raise SourceFinalizationRequired("GOLD mandatory taxonomy audit changed")
    for collection in ("producer_audit_members", "audit_members"):
        if report.get(collection, {}).get(AUDIT_FILE) != contract["audit"]:
            raise SourceFinalizationRequired("GOLD taxonomy audit absent from mandatory inventory")
    resolver = selected_taxon_aliases.restore_recorded(report, report_path, admission=admission)
    alias_identity = admission.capture(directory / selected_taxon_aliases.AUDIT_FILE)
    for collection in ("producer_audit_members", "audit_members"):
        if report.get(collection, {}).get(selected_taxon_aliases.AUDIT_FILE) != alias_identity:
            raise SourceFinalizationRequired("GOLD selected alias audit absent from mandatory inventory")
    index = _NativeIndex(
        origins["gold_native_nodes"],
        origins["gold_native_edges"],
        selected.get(NCBI_ROLE),
        selected.get(TAXDUMP_ROLE),
        contract["apply_taxon_trim"],
        resolver=resolver,
    )
    proofs, count, edge_count, digest = {}, 0, 0, hashlib.sha256()
    requested = set(requested_ids)
    try:
        expected_ids = iter(index.identifiers())
        for item in _rows(audit, AUDIT_HEADER, quoting=csv.QUOTE_NONE):
            row = item["row"]
            identifier = next(expected_ids, None)
            if row["id"] != identifier:
                raise SourceFinalizationRequired("GOLD taxonomy audit cohort incomplete, duplicated or reordered")
            expected = index.evidence(identifier)
            expected["native_inputs_json"] = _json(native)
            if row != expected:
                raise SourceFinalizationRequired(
                    f"GOLD taxonomy audit disagrees with complete native evidence: {identifier}"
                )
            digest.update((_json(row) + "\n").encode())
            count += 1
            edge_count += len(json.loads(row["emitted_edges_json"]))
            declaration = json.loads(row["emitted_node_json"])
            if identifier in requested or not declaration["name"]:
                proofs[identifier] = _proof_payload(row)
        if next(expected_ids, None) is not None:
            raise SourceFinalizationRequired("GOLD taxonomy audit omits native retained referents")
        expected_counts = {
            "native_count": index.native_count,
            "retained_count": count,
            "association_count": edge_count,
            "trimmed_count": len(index.dropped),
            "folded_count": len(index.folded),
            "historical_fold_count": len(index.historical_folds),
            "cohort_sha256": digest.hexdigest(),
            "orphaned_count": len(index.orphaned),
        }
        if any(contract.get(key) != value for key, value in expected_counts.items()):
            raise SourceFinalizationRequired("GOLD taxonomy cohort contract disagrees with actual native/audit rows")
        members = report.get("members", {})
        for name in ("nodes.tsv", "edges.tsv"):
            if admission.capture(directory / name) != members.get(name):
                raise SourceFinalizationRequired("GOLD admitted output member changed")
        _verify_graph(index, directory / "nodes.tsv", directory / "edges.tsv", quoting=csv.QUOTE_NONE)
        _verify_restoration_audit(index, report, directory, native, admission, quoting=csv.QUOTE_NONE)
        from kg_microbe.transform_utils.gold.crosswalk_quarantine import verify_record_owned_locations

        verify_record_owned_locations(index, directory, report=report, admission=admission)
    finally:
        index.close()
    admission.verify(metadata_only=True)
    return proofs


class VerifiedGoldDeclaration:
    """Data-bearing native witness, with copied accessors rather than mutable admitted state."""

    def __init__(self, payload):
        """Copy a declaration payload selected by the independently verified native rejoin."""
        self._payload = payload
        self._expected = payload

    def _row(self):
        if self._payload != self._expected:
            raise SourceFinalizationRequired("Admitted GOLD proof was mutated")
        return json.loads(self._expected)

    @property
    def identifier(self):
        """Return the exact source-owned native identifier."""
        return self._row()["id"]

    @property
    def declaration(self):
        """Return an independent copy of all approved semantic fields."""
        return json.loads(self._row()["emitted_node_json"])

    @property
    def original_node(self):
        """Expose complete original native fields and their physical source locator."""
        return json.loads(self._row()["native_node_json"])

    @property
    def native_taxon_assertions(self):
        """Expose all original native taxon assertions, not a selected parent guess."""
        return json.loads(self._row()["native_taxon_assertions_json"])

    @property
    def evidence_sha256(self):
        """Bind the complete disposition, including original and rejected claims."""
        return self._row()["complete_audit_sha256"]

    @property
    def declaration_sha256(self):
        """Bind the approved semantic declaration."""
        return _digest(self.declaration)

    def matches(self, row, *, merged=False):
        """Permit only the exact native declaration; no prefix or nameless-ID waiver."""
        expected = self.declaration
        # This provider deliberately admits no additional provider tokens:
        # consumers copy GOLD's native declaration, so provenance union is the
        # same singleton. A later additional provider needs its own admission.
        return all(row.get(key, "") == value for key, value in expected.items()) and not any(
            value for key, value in row.items() if key not in expected
        )


class GoldDeclarationGuard:
    """Retain exact proof bytes and selected authority through source/merge publication."""

    def __init__(self, proofs, admission=None, *, transform=None, authority=None, requested_ids=()):
        """Retain the exact proof inventory and independently selected authority."""
        self._proofs = dict(proofs)
        self._original_proofs = dict(proofs)
        self._sealed = _proof_inventory(proofs)
        self.admission = admission or SourceAdmission()
        self.transform = transform
        self.authority = authority
        self.requested_ids = tuple(sorted(set(requested_ids)))
        self._requested = self.requested_ids
        self._members = ((), ())
        self._bound_members = None
        self._snapshots = {}
        self._authority_json = _json(authority)
        self.admission.capture_resolution(self._state)

    def _state(self):
        """Detect lost or rebound public cache entries at late admission."""
        if (
            _proof_inventory(self._proofs) != self._sealed
            or self.requested_ids != self._requested
            or _json(self.authority) != self._authority_json
        ):
            raise SourceFinalizationRequired("GOLD admitted declaration/cache state changed")
        if self._bound_members is not None and self._members != self._bound_members:
            raise SourceFinalizationRequired("GOLD admitted member scope changed")
        return _json(self._sealed), self._requested, self._authority_json

    def declaration_for(self, identifier):
        """Never resolve an unknown ID during merge or infer a category from its prefix."""
        payload = self._proofs.get(identifier)
        if payload != self._original_proofs.get(identifier):
            raise SourceFinalizationRequired("Admitted GOLD declaration entry changed")
        return VerifiedGoldDeclaration(payload) if payload is not None else None

    def bind_members(self, node_members, edge_members):
        """Bind explicit admitted bundle members, excluding unrelated neighboring ontologies."""
        names = (tuple(sorted(Path(p).name for p in node_members)), tuple(sorted(Path(p).name for p in edge_members)))
        if any(Path(name).name != name or not name for group in names for name in group):
            raise SourceFinalizationRequired("Invalid GOLD declaration member binding")
        if self._members != ((), ()) and self._members != names:
            raise SourceFinalizationRequired("GOLD declaration source members rebound")
        self._members = names
        self._bound_members = names
        self.admission.capture_resolution(lambda: self._members)

    def contract(self):
        """Save explicit members and proof inventory with the selected finalized authority."""
        self._state()
        return {
            "version": 1,
            "authority": json.loads(self._authority_json),
            "requested_ids": list(self._requested),
            "proof_inventory": dict(self._sealed),
            "node_members": list(self._members[0]),
            "edge_members": list(self._members[1]),
        }

    def verify(self, *, output_dir=None, metadata_only=False):
        """Check the selected authority and originally consumed roles through terminal publication."""
        self._state()
        if self.transform is not None:
            for role, expected in self._snapshots.items():
                if self.transform.consumed_input_snapshots.get(role) != expected:
                    raise SourceFinalizationRequired(f"GOLD declaration consumed role missing or rebound: {role}")
        self.admission.verify(metadata_only=metadata_only)
        if output_dir is not None and self._members[0]:
            actual = gold_reference_requests(
                [Path(output_dir) / name for name in self._members[0]],
                [Path(output_dir) / name for name in self._members[1]],
                own_gold=(self.authority or {}).get("kind") == "own_native_producer",
            )
            if actual != set(self._requested):
                raise SourceFinalizationRequired("GOLD admitted request inventory differs from actual source members")
            for name in self._members[0]:
                for item in _rows(Path(output_dir) / name, ("id", "category", "name"), quoting=csv.QUOTE_NONE):
                    row = item["row"]
                    proof = self.declaration_for(row["id"])
                    if proof is not None and row["category"] != NAMED_THING_CATEGORY:
                        raise SourceFinalizationRequired("Imported GOLD referent regained an unsupported category")
                    if proof is not None and not proof.matches(row):
                        raise SourceFinalizationRequired(
                            "GOLD referent differs from its exact admitted native declaration"
                        )
            if (self.authority or {}).get("kind") != "own_native_producer":
                for name in self._members[1]:
                    for item in _rows(
                        Path(output_dir) / name, ("subject", "predicate", "object"), quoting=csv.QUOTE_NONE
                    ):
                        row = item["row"]
                        affected = any(self.declaration_for(row[key]) is not None for key in ("subject", "object"))
                        if affected and _identity_strength(row):
                            raise SourceFinalizationRequired(
                                "Imported unresolved GOLD referent regained an unsupported identity/hierarchy claim"
                            )

    def native_node_input(self):
        """Expose the exact already-admitted native source identity for reference-resolution auditing."""
        if (self.authority or {}).get("kind") == "own_native_producer" and self.transform is not None:
            return dict(self.transform._taxon_dispositions.contract()["native_inputs"]["gold_native_nodes"])
        selected = (self.authority or {}).get("report_path")
        if selected:
            native_report = self.admission.read_json(selected)
            return dict(native_report["producer_native_inputs"][CONTRACT_KEY]["native_inputs"]["gold_native_nodes"])
        raise SourceFinalizationRequired("GOLD declaration lacks an admitted native authority locator")


def _bind_record_guard(admission, attribute, key, guard):
    """Bind one immutable report/request scope without confusing other admitted producers."""
    registry = getattr(admission, attribute, None)
    if registry is None:
        registry = {}
        setattr(admission, attribute, registry)
        admission.capture_resolution(lambda: id(getattr(admission, attribute, None)))
    previous = registry.get(key)
    if previous is not None:
        if previous.contract() != guard.contract():
            raise SourceFinalizationRequired("GOLD same-record declaration scope changed")
        previous._state()
        return previous
    registry[key] = guard
    admission.capture_resolution(lambda: (id(registry.get(key)), guard._state()))
    return guard


class _NativeDeclarations:
    """Aggregate separately guarded native reports for the narrow merge-time blank lookup."""

    def __init__(self, admission):
        """Attach an independently checked provider registry to the admission."""
        self.admission = admission
        self._providers = {}
        self._original = {}
        admission.capture_resolution(self._state)

    def _state(self):
        if self._providers.keys() != self._original.keys() or any(
            self._providers[key] is not provider for key, provider in self._original.items()
        ):
            raise SourceFinalizationRequired("GOLD native declaration provider inventory changed")
        for provider in self._original.values():
            provider._state()
        return True

    def add(self, key, provider):
        """Register one exact native provider without replacing an existing binding."""
        self._state()
        if key in self._original and self._original[key] is not provider:
            raise SourceFinalizationRequired("GOLD native declaration provider rebound")
        self._providers[key] = self._original[key] = provider

    def declaration_for(self, identifier):
        """Return the admitted declaration only when all contributing providers agree."""
        self._state()
        result = None
        for provider in self._original.values():
            proof = provider.declaration_for(identifier)
            if proof is not None:
                if result is not None and result.declaration != proof.declaration:
                    raise SourceFinalizationRequired("Conflicting admitted native GOLD declarations")
                result = proof
        return result

    def verify(self, *, metadata_only=False):
        """Check all original provider bindings and retained admission guards."""
        self._state()
        self.admission.verify(metadata_only=metadata_only)


def verify_recorded_taxon_inputs(report, report_path, *, admission=None, requested_ids=()):
    """Attach a nameless-only provider while checking the complete native cohort once."""
    admission = admission or SourceAdmission()
    proofs = _verify_contract(report, report_path, admission, requested_ids=requested_ids)
    provider = GoldDeclarationGuard(proofs, admission)
    key = (str(Path(report_path).absolute()), tuple(sorted(requested_ids)))
    provider = _bind_record_guard(admission, "_gold_native_record_guards", key, provider)
    collection = getattr(admission, "gold_native_declarations", None)
    if collection is None:
        collection = _NativeDeclarations(admission)
        admission.gold_native_declarations = collection
        admission.capture_resolution(lambda: id(getattr(admission, "gold_native_declarations", None)))
    collection.add(key, provider)
    return admission


def _admit_selected_report(report, report_path, admission):
    """Require current registered authoring code and retain its actual package/file guards."""
    from kg_microbe.merge_utils.source_freshness import _SourceFreshness
    from kg_microbe.utils.source_finalization import _validate_finalization_record_shape

    _validate_finalization_record_shape(report, report_path)
    freshness = _SourceFreshness(admission)
    # Fail before a large native rejoin when authoring is already stale.
    freshness._producer(report)
    if report.get("finalizer_code") != freshness.shared:
        raise SourceFinalizationRequired("Selected GOLD source-finalization code changed; rerun kg transform")
    freshness._check_record(report_path, report)


def load_gold_declarations(transform, requested_ids, *, admission=None):
    """Select only the sibling GOLD authority; genuine zero references require no authority."""
    requested = {identifier for identifier in requested_ids if identifier.startswith("gold:")}
    previous = getattr(transform, "_gold_declaration_guard", None)
    if previous is not None and set(previous._requested) == requested:
        previous.verify(metadata_only=True)
        # A producer run may hand its unbound, already-admitted authority to
        # the first finalization. A subsequent finalization is a new member
        # scope, not permission to rebind the old admitted scope.
        if previous._members == ((), ()):
            return previous
    if not requested:
        guard = GoldDeclarationGuard(
            {},
            admission,
            transform=transform,
            authority={"kind": "own_native_producer"} if transform.source_name == GOLD else None,
        )
        transform._gold_declaration_guard = guard
        return guard
    producer_scope = getattr(transform, "_taxon_dispositions", None)
    if transform.source_name == GOLD and producer_scope is not None:
        if not producer_scope.finished:
            raise SourceFinalizationRequired("GOLD declarations requested before mandatory native audit completion")
        producer_scope.verify(metadata_only=True)
        proofs = {}
        native_inputs = producer_scope.contract()["native_inputs"]
        for identifier in sorted(requested):
            item = producer_scope.index.evidence(identifier)
            if item is not None:
                item["native_inputs_json"] = _json(native_inputs)
                proofs[identifier] = _proof_payload(item)
        guard = GoldDeclarationGuard(
            proofs, admission, transform=transform, authority={"kind": "own_native_producer"}, requested_ids=requested
        )
        guard.admission.capture_resolution(lambda: producer_scope.verify(metadata_only=True))
    else:
        report_path = transform.output_base_dir / GOLD / "source_finalization.json"
        admitted = admission or SourceAdmission()
        report = admitted.read_json(report_path)
        if report.get("source") != GOLD:
            raise SourceFinalizationRequired("Selected sibling authority is not finalized GOLD")
        # Validate the selected source's existing registered producer/audit
        # contracts, not a production-global path or a current raw fallback.
        _admit_selected_report(report, report_path, admitted)
        # The registered verifier admits nameless proofs; the same complete
        # native rejoin also selects consumer-requested declarations here.
        proofs = _verify_contract(report, report_path, admitted, requested_ids=requested)
        proofs = {key: value for key, value in proofs.items() if key in requested}
        authority = {
            "kind": "selected_sibling_gold",
            # Resolved, like the consumed-input snapshots admission compares below:
            # an unresolved locator under a symlinked root never matches again.
            "report_path": str(report_path.resolve()),
            "report_identity": admitted.capture(report_path),
        }
        guard = GoldDeclarationGuard(
            proofs, admitted, transform=transform, authority=authority, requested_ids=requested
        )
        for role, path in (
            ("gold_reference_report", report_path),
            ("gold_reference_nodes", report_path.parent / "nodes.tsv"),
            ("gold_reference_audit", report_path.parent / AUDIT_FILE),
        ):
            with transform.consume_input(role, path):
                pass
            guard._snapshots[role] = dict(transform.consumed_input_snapshots[role])
    transform._gold_declaration_guard = guard
    return guard


def verify_recorded_gold_declarations(report, report_path, *, admission=None):
    """Rejoin explicit consumer members and the exact selected GOLD proof contract."""
    admission = admission or SourceAdmission()
    contract = report.get("gold_reference_declarations")
    if not isinstance(contract, dict) or contract.get("version") != 1:
        raise SourceFinalizationRequired("Missing GOLD reference declaration contract")
    requested = contract.get("requested_ids")
    if not isinstance(requested, list) or requested != sorted(set(requested)):
        raise SourceFinalizationRequired("Invalid GOLD reference request inventory")
    members = report.get("members", {})
    node_names = sorted(name for name in members if name.endswith("nodes.tsv"))
    edge_names = sorted(name for name in members if name.endswith("edges.tsv"))
    if contract.get("node_members") != node_names or contract.get("edge_members") != edge_names:
        raise SourceFinalizationRequired("GOLD reference declaration member scope changed")
    actual_requested = gold_reference_requests(
        [Path(report_path).parent / name for name in node_names],
        [Path(report_path).parent / name for name in edge_names],
        own_gold=report.get("source") == GOLD,
    )
    if actual_requested != set(requested):
        raise SourceFinalizationRequired("GOLD recorded request inventory differs from actual source members")
    if not requested:
        guard = GoldDeclarationGuard(
            {}, admission, authority={"kind": "own_native_producer"} if report.get("source") == GOLD else None
        )
    elif report.get("source") == GOLD:
        # Existing producer verification has already checked this exact report;
        # repeat rejoin admits the requested proof inventory without recursion.
        proofs = _verify_contract(report, report_path, admission, requested_ids=requested)
        guard = GoldDeclarationGuard(
            {k: v for k, v in proofs.items() if k in requested},
            admission,
            authority={"kind": "own_native_producer"},
            requested_ids=requested,
        )
    else:
        authority = contract.get("authority", {})
        selected = Path(report_path).parent.parent / GOLD / "source_finalization.json"
        if (
            authority.get("kind") != "selected_sibling_gold"
            or Path(authority.get("report_path", "")).resolve() != selected.resolve()
        ):
            raise SourceFinalizationRequired("GOLD consumer authority locator differs from selected sibling")
        if admission.capture(selected) != authority.get("report_identity"):
            raise SourceFinalizationRequired("GOLD consumer authority report changed")
        native_report = admission.read_json(selected)
        _admit_selected_report(native_report, selected, admission)
        proofs = _verify_contract(native_report, selected, admission, requested_ids=requested)
        guard = GoldDeclarationGuard(
            {k: v for k, v in proofs.items() if k in requested}, admission, authority=authority, requested_ids=requested
        )
        for role, path in (
            ("gold_reference_report", selected),
            ("gold_reference_nodes", selected.parent / "nodes.tsv"),
            ("gold_reference_audit", selected.parent / AUDIT_FILE),
        ):
            snapshot = report.get("consumed_inputs", {}).get(role, {})
            if (
                Path(snapshot.get("path", "")).resolve() != path.resolve()
                or snapshot.get("sha256") != admission.capture(path)["sha256"]
            ):
                raise SourceFinalizationRequired("GOLD consumer actual authority receipt missing or changed")
    guard.bind_members(node_names, edge_names)
    if guard.contract() != contract:
        raise SourceFinalizationRequired("GOLD reference proof contract changed")
    guard.verify(output_dir=Path(report_path).parent, metadata_only=True)
    key = str(Path(report_path).absolute())
    _bind_record_guard(admission, "_gold_reference_record_guards", key, guard)
    return admission


def restore_gold_declarations(transform, report, report_path, *, admission=None):
    """Retain live role checks after fresh-instance repeat finalization."""
    admission = verify_recorded_gold_declarations(report, report_path, admission=admission)
    guard = admission._gold_reference_record_guards[str(Path(report_path).absolute())]
    guard.transform = transform
    guard._snapshots = {
        key: dict(value)
        for key, value in report.get("consumed_inputs", {}).items()
        if key.startswith("gold_reference_")
    }
    transform._gold_declaration_guard = guard
    return guard


def admitted_gold_declarations(report, report_path, requested_ids, *, admission):
    """Provide explicitly requested native declarations without altering an admitted graph."""
    proofs = _verify_contract(report, report_path, admission, requested_ids=requested_ids)
    return GoldDeclarationGuard(
        {key: value for key, value in proofs.items() if key in set(requested_ids)},
        admission,
        requested_ids=requested_ids,
    )
