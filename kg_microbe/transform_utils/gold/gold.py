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

What it deliberately does **not** change, because each needs a modelling decision
rather than a patch, and is reported instead:

* the 279,618 orphan ``MaterialSample`` nodes (drop them, or populate the join?);
* ``IndividualOrganism -related_to-> Study`` on 27.5% of edges (which predicate
  is actually meant?);
* the 23,695 GOLD-only taxa absent from the NCBITaxon output;
* the 78 taxon ``name`` disagreements with the ontologies output.
"""

import csv
import os
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

#: Reported, not repaired — see the module docstring.
_REPORTED_CATEGORIES = ("biolink:MaterialSample",)

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

        dropped, seen_before = self._taxon_drop_set(nodes_in, edges_in)
        incident = self._write_edges(edges_in, dropped)
        self._write_nodes(nodes_in, dropped, seen_before, incident)

    def _trimmed_taxa(self) -> Optional[set]:
        """
        Load the taxon IDs that survived the NCBITaxon trim.

        :return: The permitted ``NCBITaxon:`` IDs, or None when filtering is off.
        :raises FileNotFoundError: If the ontologies output is absent while
            filtering is on — silently skipping the trim would reintroduce every
            excluded branch with nothing to show it had happened.
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
            return {row["id"] for row in csv.DictReader(handle, delimiter="\t")}

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
                    seen_before.add(row["subject"])
                    seen_before.add(row["object"])
            return set(), seen_before

        with nodes_in.open(newline="") as handle:
            excluded = {
                row["id"]
                for row in csv.DictReader(handle, delimiter="\t")
                if row["id"].startswith(_TAXON_PREFIX) and row["id"] not in permitted
            }
        organisms: set = set()
        with edges_in.open(newline="") as handle:
            for row in csv.DictReader(handle, delimiter="\t"):
                seen_before.add(row["subject"])
                seen_before.add(row["object"])
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
                subject, obj = row["subject"], row["object"]
                if subject in dropped or obj in dropped:
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
        print(f"[gold] edges emitted: {kept:,}" + (f" (dropped {removed:,} by the trim)" if removed else ""))
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
        emitted = removed = newly_orphaned = 0
        pre_existing_orphans: set = set()
        with (
            nodes_in.open(newline="") as handle,
            self.output_node_file.open("w", newline="") as out,
        ):
            reader = csv.DictReader(handle, delimiter="\t")
            writer = csv.writer(out, delimiter="\t")
            writer.writerow(self.node_header)
            for row in reader:
                node_id = row["id"]
                if node_id in dropped:
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
