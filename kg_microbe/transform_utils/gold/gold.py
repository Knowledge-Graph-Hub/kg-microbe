"""
Transform the GOLD (Genomes OnLine Database, JGI) pre-transformed KGX TSVs.

GOLD is unusual among our sources: it arrives **already in KGX shape**, so there
is nothing to parse. That makes a blind copy tempting and wrong. The modeling
review of the shipped payload (``docs/GOLD_TRANSFORM_REVIEW.md``) found nine
issues that a copy would carry straight into a merge — including 279,618
``MaterialSample`` nodes with no incident edge, and 4,220 ``subclass_of`` edges
that violate Biolink's domain/range.

So this is a *validating* passthrough. It conforms the schema to the KG-Microbe
standard, repairs what can be repaired mechanically, and reports the rest rather
than silently propagating it.

What it changes, and why each is safe:

* **Adds the standard columns.** Upstream nodes lack ``description``,
  ``synonym``, ``deprecated`` and ``same_as``; edges lack ``knowledge_level`` and
  ``agent_type``. Every other transform emits them, and they are how a consumer
  tells an assertion from a prediction. GOLD entries are curated submissions, so
  they are filled as ``knowledge_assertion`` / ``manual_agent``.
* **Drops the upstream edge ``id``.** The post-merge cleanup drops it anyway; not
  emitting it keeps the header standard.
* **Adds ``biolink:OntologyClass`` to ecosystem nodes.** ``subclass_of`` requires
  ``OntologyClass`` on both ends, and the GOLD ecosystem hierarchy is exactly
  that — a class hierarchy. Pipe-adding the category is the same device METPO
  nodes already use (``METPO:1001000|biolink:Procedure``). Without it those 4,220
  edges are a Biolink violation.

* **Applies the NCBITaxon trim.** KG-Microbe deliberately restricts NCBITaxon to
  microbes (``exclusion_branches.tsv`` removes Viruses, Viridiplantae, Metazoa
  and others). GOLD is a genome database covering all of life, so ingesting it
  unfiltered reintroduces 23,695 excluded taxa — phages, marine viruses,
  ``Picea glauca``, a starling — and the 76,034 organisms typed to them, undoing
  the trim the ontologies transform performs. Those, and the study nodes left
  holding nothing but them, are dropped.

* **Drops samples and studies.** KG-Microbe wants neither. ``MaterialSample``
  was 279,670 nodes with 242 incident edges, and ``Study`` was reachable only
  via ``IndividualOrganism -related_to-> Study``, a predicate asserting nothing
  usable (27.5% of the export). What the ingest is *for* — the organism to
  environment link, ``occurs_in`` — is kept. Measured: nodes 975,839 -> 637,286,
  edges 1,110,984 -> 823,250, and the pre-existing orphan warning falls from
  279,618 to 5. ``occurs_in`` ends at 287,706 rather than its upstream 286,725 —
  it *rises*, because organisms the taxid remap rescues keep their environment
  edges.
* **Remaps retired NCBI taxids** from ``merged.dmp`` in the taxonomy dump.
  GOLD's export carries taxa NCBI has since merged, and judging them by the
  retired id makes the trim drop them along with the organisms typed to them.
  Measured against the real payload: 611 taxa and 1,473 organisms retained that
  would otherwise have been discarded, with 561 nodes collapsing onto an
  existing id. Applied before the trim, since that is the point.

What it deliberately does **not** change, because each needs a modelling decision
rather than a patch, and is reported instead:

* the 23,695 GOLD-only taxa absent from the NCBITaxon output;
* the 78 taxon ``name`` disagreements with the ontologies output.

Still open upstream, unaffected by this transform: versioned filenames or a
published checksum, and the six ``Saccharomyces`` rows that lose their hybrid
``x`` marker.
"""

import csv
import io
import os
import tarfile
from pathlib import Path
from typing import Optional, Union

from kg_microbe.transform_utils.constants import (
    GOLD,
    KNOWLEDGE_ASSERTION,
    MANUAL_AGENT,
)
from kg_microbe.transform_utils.transform import Transform

#: Upstream filenames inside ``data/raw/gold/``.
GOLD_NODES_FILE = "GOLD_nodes.tsv"
GOLD_EDGES_FILE = "GOLD_edges.tsv"

#: Ecosystem nodes form a class hierarchy, so `subclass_of` needs them to be
#: ontology classes. Biolink requires OntologyClass on both ends of that
#: predicate; without this the edges are a domain/range violation.
_ECOSYSTEM_PREFIX = "gold.ecosystem:"
_ONTOLOGY_CLASS = "biolink:OntologyClass"

#: Categories dropped outright. GOLD ships 279,670 ``MaterialSample`` nodes with
#: 242 incident edges — 279,428 disconnected — and 60,433 ``Study`` nodes whose
#: only tie to anything is ``IndividualOrganism -related_to-> Study``, a
#: predicate that asserts nothing usable (289,946 edges, 27.5% of the export).
#: KG-Microbe wants neither samples nor studies; it wants the organism to
#: environment link, which is ``occurs_in`` and is unaffected.
_DROP_CATEGORIES = ("biolink:MaterialSample", "biolink:Study")

#: NCBI's retired-to-current taxid map lives in this member of the taxdump.
_TAXDUMP_ARCHIVE = "taxdump.tar.gz"
_MERGED_DMP = "merged.dmp"

#: The trimmed NCBITaxon set, produced by the ontologies transform. GOLD must run
#: after it. Same shape of dependency as PREGO's on ``mondo_nodes.tsv``.
_NCBITAXON_NODES = "ncbitaxon_nodes.tsv"

#: Set false to ingest GOLD unfiltered, for debugging what the trim removes.
_APPLY_TRIM_ENV = "GOLD_APPLY_TAXON_TRIM"

_IN_TAXON = "biolink:in_taxon"
_TAXON_PREFIX = "NCBITaxon:"


class GOLDTransform(Transform):

    """Conform the pre-transformed GOLD KGX TSVs to the KG-Microbe standard."""

    def __init__(self, input_dir: Optional[Path] = None, output_dir: Optional[Path] = None):
        """
        Instantiate the transform.

        :param input_dir: Directory holding ``gold/``.
        :param output_dir: Transform output directory.
        """
        super().__init__(GOLD, input_dir, output_dir)
        self._merges: Optional[dict] = None

    def run(self, data_file: Union[Optional[Path], Optional[str]] = None, show_status: bool = True) -> None:
        """
        Conform the upstream TSVs and write standard nodes/edges.

        :param data_file: Unused; the filenames are fixed by the download entry.
        :param show_status: Unused; retained for the base-class signature.
        :raises FileNotFoundError: If either upstream file is missing.
        """
        raw = self.input_base_dir / GOLD
        nodes_in, edges_in = raw / GOLD_NODES_FILE, raw / GOLD_EDGES_FILE
        for path in (nodes_in, edges_in):
            if not path.exists():
                raise FileNotFoundError(f"{path} is missing; run `poetry run kg download -t gold` first.")

        # Order matters: remap retired taxids first, so a taxon NCBI has merged
        # into a current one is judged by the trim on the id it actually means.
        # Judging it on the retired id drops ~950 taxa, many of them bacteria.
        self._taxid_merges()
        dropped = self._category_drop_set(nodes_in)
        taxon_dropped, seen_before = self._taxon_drop_set(nodes_in, edges_in)
        dropped |= taxon_dropped
        incident = self._write_edges(edges_in, dropped)
        self._write_nodes(nodes_in, dropped, seen_before, incident)

    def _trimmed_taxa(self) -> Optional[set]:
        """
        Load the taxon IDs that survived the NCBITaxon trim.

        :return: The permitted ``NCBITaxon:`` IDs, or None when filtering is off.
        :raises FileNotFoundError: If the ontologies output is absent while
            filtering is on — silently skipping the trim would reintroduce every
            excluded branch with nothing to show it had happened.
        :raises ValueError: If the ontologies output carries no ``NCBITaxon:``
            rows. An empty permitted set is never a legitimate trim: it makes
            every GOLD taxon "excluded", drops every organism typed to one, and
            cascades to an empty graph reported as a successful run. A
            header-only or truncated derived file is a known failure mode in this
            repo — ``atomic_io`` exists for it — and the ontologies output
            predates that work, so it carries no completion marker to check.
        """
        if os.environ.get(_APPLY_TRIM_ENV, "true").strip().lower() in ("false", "0", "no"):
            print(f"[gold] {_APPLY_TRIM_ENV} is off — emitting excluded-branch taxa unfiltered")
            return None
        path = self.output_base_dir / "ontologies" / _NCBITAXON_NODES
        if not path.exists():
            raise FileNotFoundError(
                f"{path} is missing, so the NCBITaxon trim cannot be applied. Run "
                f"`poetry run kg transform -s ontologies` first, or set {_APPLY_TRIM_ENV}=false "
                "to ingest GOLD unfiltered (which reintroduces viruses, plants and metazoa)."
            )
        with path.open(newline="") as handle:
            permitted = {row["id"] for row in csv.DictReader(handle, delimiter="\t")}
        taxa = {node_id for node_id in permitted if node_id.startswith(_TAXON_PREFIX)}
        if not taxa:
            raise ValueError(
                f"{path} has no {_TAXON_PREFIX} rows ({len(permitted):,} rows total), so the trim "
                "would exclude every GOLD taxon and emit an empty graph. Re-run "
                f"`poetry run kg transform -s ontologies`, or set {_APPLY_TRIM_ENV}=false to "
                "ingest GOLD unfiltered."
            )
        return taxa

    def _taxid_merges(self) -> dict:
        """
        NCBI's retired-taxid to current-taxid map, from ``merged.dmp``.

        GOLD's export carries roughly 950 taxa NCBI has since merged. Left
        alone they point at ids no longer in NCBITaxon, so the trim drops them
        along with the organisms typed to them — losing bacteria we would
        otherwise keep, which is the opposite of what the trim is for.

        Read straight out of the tarball; NCBI publishes no standalone
        ``merged.dmp``. Absence is non-fatal: without it the remap is a no-op
        and the affected taxa are dropped as before, which is the pre-existing
        behaviour rather than a new failure.

        :return: ``{"NCBITaxon:<old>": "NCBITaxon:<new>"}``, empty if unavailable.
        """
        if self._merges is not None:
            return self._merges

        merges: dict = {}
        archive = self.input_base_dir / _TAXDUMP_ARCHIVE
        if not archive.is_file():
            print(
                f"[gold] {archive} not found — retired NCBI taxids will not be remapped; "
                "run `poetry run kg download -t gold`"
            )
            self._merges = merges
            return merges

        with tarfile.open(archive, "r:gz") as tar:
            member = tar.extractfile(_MERGED_DMP)
            if member is None:
                print(f"[gold] {_MERGED_DMP} missing from {archive.name}; no remap applied")
                self._merges = merges
                return merges
            for raw in io.TextIOWrapper(member, encoding="utf-8"):
                # merged.dmp rows look like:  old_id\t|\tnew_id\t|
                parts = [f.strip() for f in raw.split("|")]
                if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
                    merges[f"{_TAXON_PREFIX}{parts[0]}"] = f"{_TAXON_PREFIX}{parts[1]}"
        print(f"[gold] loaded {len(merges):,} NCBI taxid merges from {_MERGED_DMP}")
        self._merges = merges
        return merges

    def _remap(self, node_id: str) -> str:
        """
        Rewrite a retired NCBI taxid to its current one.

        :param node_id: Any node id; non-taxon ids pass through untouched.
        :return: The current id, or the input when there is no merge record.
        """
        return self._taxid_merges().get(node_id, node_id)

    def _category_drop_set(self, nodes_in: Path) -> set:
        """
        Ids whose category KG-Microbe does not ingest.

        :param nodes_in: Upstream ``GOLD_nodes.tsv``.
        :return: Ids of sample and study nodes.
        """
        with nodes_in.open(newline="") as handle:
            drop = {
                row["id"]
                for row in csv.DictReader(handle, delimiter="\t")
                if any(c in (row.get("category") or "") for c in _DROP_CATEGORIES)
            }
        print(f"[gold] dropping {len(drop):,} sample/study nodes and every edge touching them")
        return drop

    def _taxon_drop_set(self, nodes_in: Path, edges_in: Path) -> tuple:
        """
        Decide what the trim removes, before anything is written.

        Three things go: taxa outside the trimmed set, the organisms typed to
        them — an organism whose taxon is a spruce or a starling does not belong
        in a microbial graph — and the studies left holding nothing else. The
        last is a condition we create, so we clean it up; the orphans already in
        the upstream payload are a separate modelling question and are left alone.

        :param nodes_in: Upstream ``GOLD_nodes.tsv``.
        :param edges_in: Upstream ``GOLD_edges.tsv``.
        :return: ``(ids_to_drop, ids_that_had_an_edge_upstream)``.
        """
        permitted = self._trimmed_taxa()
        seen_before: set = set()
        if permitted is None:
            with edges_in.open(newline="") as handle:
                for row in csv.DictReader(handle, delimiter="\t"):
                    # Remap here too. The writers remap unconditionally, so
                    # recording raw ids would desync the orphan bookkeeping and
                    # drop nodes that do still have a surviving edge.
                    seen_before.add(self._remap(row["subject"]))
                    seen_before.add(self._remap(row["object"]))
            return set(), seen_before

        with nodes_in.open(newline="") as handle:
            excluded = {
                row["id"]
                for row in csv.DictReader(handle, delimiter="\t")
                if row["id"].startswith(_TAXON_PREFIX) and self._remap(row["id"]) not in permitted
            }
        organisms: set = set()
        with edges_in.open(newline="") as handle:
            for row in csv.DictReader(handle, delimiter="\t"):
                seen_before.add(self._remap(row["subject"]))
                seen_before.add(self._remap(row["object"]))
                if row["predicate"] == _IN_TAXON and row["object"] in excluded:
                    organisms.add(row["subject"])
        print(
            f"[gold] NCBITaxon trim: dropping {len(excluded):,} taxa outside the trimmed set "
            f"and {len(organisms):,} organisms typed to them"
        )
        return excluded | organisms, seen_before

    def _write_edges(self, edges_in: Path, dropped: set) -> set:
        """
        Write surviving edges in the standard column order.

        :param edges_in: Upstream ``GOLD_edges.tsv``.
        :param dropped: IDs removed by the trim.
        :return: IDs incident to at least one surviving edge.
        """
        incident: set = set()
        kept = removed = 0
        with (
            edges_in.open(newline="") as handle,
            self.output_edge_file.open("w", newline="") as out,
        ):
            reader = csv.DictReader(handle, delimiter="\t")
            writer = csv.writer(out, delimiter="\t")
            writer.writerow(self.edge_header)
            for row in reader:
                subject, obj = self._remap(row["subject"]), self._remap(row["object"])
                if row["subject"] in dropped or row["object"] in dropped or subject in dropped or obj in dropped:
                    removed += 1
                    continue
                incident.add(subject)
                incident.add(obj)
                kept += 1
                writer.writerow(
                    [
                        subject,
                        row["predicate"],
                        obj,
                        row.get("relation", ""),
                        row.get("primary_knowledge_source", "") or f"infores:{GOLD}",
                        KNOWLEDGE_ASSERTION,
                        MANUAL_AGENT,
                    ]
                )
        # "dropped" spans both reasons — the taxon trim and the sample/study
        # categories — so do not attribute it to the trim alone.
        print(f"[gold] edges emitted: {kept:,}" + (f" (dropped {removed:,})" if removed else ""))
        return incident

    def _write_nodes(self, nodes_in: Path, dropped: set, seen_before: set, incident: set) -> None:
        """
        Write surviving nodes in the standard column order, adding missing columns.

        A node goes if the trim removed it, or if it had an edge upstream and has
        none left — that second case is orphaning *we* caused, so we clean it up.
        Nodes that were already edgeless upstream are kept and reported, because
        whether to drop those is a modelling decision for GOLD, not ours.

        :param nodes_in: Upstream ``GOLD_nodes.tsv``.
        :param dropped: IDs removed by the trim.
        :param seen_before: IDs incident to an edge in the upstream payload.
        :param incident: IDs incident to a surviving edge.
        """
        emitted = removed = newly_orphaned = remapped_collisions = 0
        pre_existing_orphans: set = set()
        # Which ids the upstream file carries verbatim, so a retired row can
        # defer to its replacement's own row rather than donating a stale name.
        with nodes_in.open(newline="") as handle:
            verbatim_ids = {row["id"] for row in csv.DictReader(handle, delimiter="\t")}
        with (
            nodes_in.open(newline="") as handle,
            self.output_node_file.open("w", newline="") as out,
        ):
            reader = csv.DictReader(handle, delimiter="\t")
            writer = csv.writer(out, delimiter="\t")
            writer.writerow(self.node_header)
            written: set = set()
            for row in reader:
                original_id = row["id"]
                node_id = self._remap(original_id)
                if original_id != node_id and node_id in verbatim_ids:
                    # Both the retired id and its replacement are present
                    # upstream. Skip the retired row and let the replacement's
                    # own row supply the node, so the surviving node does not
                    # carry the merged-away taxon's name: 232 of 420 collisions
                    # would otherwise label NCBITaxon:296995 "Exiguobacterium
                    # enclense" instead of "Exiguobacterium indicum", because
                    # the retired row happens to come first in the file.
                    remapped_collisions += 1
                    continue
                if node_id in written:
                    # Several retired ids can merge into one target that is not
                    # itself present upstream; the first is as good as any.
                    remapped_collisions += 1
                    continue
                if original_id in dropped or node_id in dropped:
                    removed += 1
                    continue
                if node_id in seen_before and node_id not in incident:
                    newly_orphaned += 1
                    removed += 1
                    continue
                if node_id not in seen_before:
                    pre_existing_orphans.add(node_id)
                category = row.get("category", "")
                if node_id.startswith(_ECOSYSTEM_PREFIX) and _ONTOLOGY_CLASS not in category:
                    category = f"{category}|{_ONTOLOGY_CLASS}" if category else _ONTOLOGY_CLASS
                emitted += 1
                written.add(node_id)
                writer.writerow(
                    [
                        node_id,
                        category,
                        row.get("name", ""),
                        "",  # description — not supplied upstream
                        row.get("xref", ""),
                        row.get("provided_by", "") or f"infores:{GOLD}",
                        "",  # synonym
                        "",  # deprecated
                        "",  # same_as
                    ]
                )
        print(f"[gold] nodes emitted: {emitted:,}" + (f" (dropped {removed:,})" if removed else ""))
        if newly_orphaned:
            print(f"[gold]   of which {newly_orphaned:,} were left edgeless by the trim and cleaned up")
        if remapped_collisions:
            print(
                f"[gold]   {remapped_collisions:,} node(s) collapsed onto an existing id after the retired-taxid remap"
            )
        self._report_orphans(pre_existing_orphans, emitted)

    @staticmethod
    def _report_orphans(orphans: set, emitted: int) -> None:
        """
        Report nodes that were already edgeless upstream.

        The upstream payload is 26.5% orphans, essentially all ``MaterialSample``.
        Whether to drop them is a modelling decision for GOLD, so this surfaces
        the number rather than taking it — unlike the orphaning the trim causes,
        which is ours and is cleaned up.

        :param orphans: IDs that had no edge in the upstream payload.
        :param emitted: Total nodes written.
        """
        if not orphans:
            return
        by_prefix: dict = {}
        for node_id in orphans:
            prefix = node_id.split(":")[0]
            by_prefix[prefix] = by_prefix.get(prefix, 0) + 1
        top = ", ".join(f"{k}={v:,}" for k, v in sorted(by_prefix.items(), key=lambda kv: -kv[1])[:4])
        print(
            f"[gold] WARNING: {len(orphans):,} of {emitted:,} emitted nodes ({100 * len(orphans) / emitted:.1f}%) "
            f"had no incident edge upstream — {top}. See docs/GOLD_TRANSFORM_REVIEW.md; dropping them is a "
            "modelling decision for GOLD, not taken here."
        )
