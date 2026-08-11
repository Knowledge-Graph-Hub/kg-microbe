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

What it deliberately does **not** change, because each needs a modelling decision
rather than a patch, and is reported instead:

* the 279,618 orphan ``MaterialSample`` nodes (drop them, or populate the join?);
* ``IndividualOrganism -related_to-> Study`` on 27.5% of edges (which predicate
  is actually meant?);
* the 23,695 GOLD-only taxa absent from the NCBITaxon output;
* the 78 taxon ``name`` disagreements with the ontologies output.
"""

import csv
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

        node_ids = self._write_nodes(nodes_in)
        self._write_edges(edges_in, node_ids)

    def _write_nodes(self, nodes_in: Path) -> set:
        """
        Write nodes in the standard column order, adding the missing columns.

        :param nodes_in: Upstream ``GOLD_nodes.tsv``.
        :return: The set of emitted node IDs, for the edge pass to check against.
        """
        emitted: set = set()
        counts: dict = {}
        with (
            nodes_in.open(newline="") as handle,
            self.output_node_file.open("w", newline="") as out,
        ):
            reader = csv.DictReader(handle, delimiter="\t")
            writer = csv.writer(out, delimiter="\t")
            writer.writerow(self.node_header)
            for row in reader:
                node_id = row["id"]
                category = row.get("category", "")
                if node_id.startswith(_ECOSYSTEM_PREFIX) and _ONTOLOGY_CLASS not in category:
                    category = f"{category}|{_ONTOLOGY_CLASS}" if category else _ONTOLOGY_CLASS
                counts[category] = counts.get(category, 0) + 1
                emitted.add(node_id)
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
        print(f"[gold] nodes emitted: {len(emitted):,}")
        return emitted

    def _write_edges(self, edges_in: Path, node_ids: set) -> None:
        """
        Write edges in the standard column order, adding the knowledge columns.

        Endpoints are checked against the emitted nodes. The shipped payload has
        none dangling, and a regression there is worth hearing about rather than
        discovering at merge time.

        :param edges_in: Upstream ``GOLD_edges.tsv``.
        :param node_ids: IDs emitted by :meth:`_write_nodes`.
        """
        incident: set = set()
        dangling = 0
        total = 0
        with (
            edges_in.open(newline="") as handle,
            self.output_edge_file.open("w", newline="") as out,
        ):
            reader = csv.DictReader(handle, delimiter="\t")
            writer = csv.writer(out, delimiter="\t")
            writer.writerow(self.edge_header)
            for row in reader:
                subject, obj = row["subject"], row["object"]
                total += 1
                if subject not in node_ids or obj not in node_ids:
                    dangling += 1
                    continue
                incident.add(subject)
                incident.add(obj)
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
        print(f"[gold] edges emitted: {total - dangling:,}" + (f" (dropped {dangling:,} dangling)" if dangling else ""))
        self._report_orphans(node_ids, incident)

    @staticmethod
    def _report_orphans(node_ids: set, incident: set) -> None:
        """
        Report nodes with no incident edge rather than silently shipping them.

        The upstream payload is 26.5% orphans, essentially all
        ``MaterialSample``. Whether to drop them is a modelling decision, so this
        surfaces the number instead of taking it.

        :param node_ids: All emitted node IDs.
        :param incident: IDs touched by at least one emitted edge.
        """
        orphans = node_ids - incident
        if not orphans:
            return
        share = 100 * len(orphans) / len(node_ids)
        by_prefix: dict = {}
        for node_id in orphans:
            prefix = node_id.split(":")[0]
            by_prefix[prefix] = by_prefix.get(prefix, 0) + 1
        top = ", ".join(f"{k}={v:,}" for k, v in sorted(by_prefix.items(), key=lambda kv: -kv[1])[:4])
        print(
            f"[gold] WARNING: {len(orphans):,} orphan nodes ({share:.1f}%) have no incident edge — {top}. "
            "See docs/GOLD_TRANSFORM_REVIEW.md; dropping them is a modelling decision, not taken here."
        )
