"""
LPSN transform.

Ingests the LPSN GSS (Genus/Species/Subspecies) CSV bulk export into
KGX-format nodes and edges. Each row becomes a `biolink:OrganismTaxon`
node at `lpsn:<record_no>`, with `biolink:subclass_of` edges pointing
from species → genus and subspecies → species so that the LPSN
taxonomic tree is queryable in the merged KG.

The GSS CSV requires a free LPSN login to download. This transform
does NOT fetch it — place the downloaded file at
`data/raw/lpsn/lpsn_gss.csv` before running:

    poetry run kg transform -s lpsn

See ``kg_microbe/transform_utils/lpsn/README.md`` for the manual
download procedure.

MVP scope:
- Nodes for every LPSN record (family / genus / species / subspecies).
- subclass_of edges from subspecies → species → genus (only when the
  parent row is present in the same CSV — no LPSN API calls).
- Illegitimate / synonym rows carry ``deprecated=True``.
- Cross-references to NCBITaxon / GTDB / BacDive are deferred to a
  follow-up PR (see issue #484); they require a name-matching layer
  or the authenticated LPSN JSON API.
"""

import csv
from pathlib import Path
from typing import Dict, Optional, Union

from kg_microbe.transform_utils.constants import (
    CLOSE_MATCH_PREDICATE,
    ID_COLUMN,
    LPSN_SOURCE,
    NCBI_CATEGORY,
    RDFS_SUBCLASS_OF,
    SUBCLASS_PREDICATE,
)
from kg_microbe.transform_utils.transform import Transform

LPSN_PREFIX = "lpsn:"
LPSN_KNOWLEDGE_SOURCE = "infores:lpsn"

# LPSN GSS CSV column names (as published in the DSMZ export).
COL_GENUS = "genus_name"
COL_SP_EPITHET = "sp_epithet"
COL_SUBSP_EPITHET = "subsp_epithet"
COL_REFERENCE = "reference"
COL_STATUS = "status"
COL_AUTHORS = "authors"
COL_ADDRESS = "address"
COL_RECORD_NO = "record_no"
COL_RECORD_LNK = "record_lnk"

# Nomenclatural statuses that should mark a node as ``deprecated=True``.
DEPRECATED_STATUSES = frozenset(
    {
        "illegitimate name",
        "not validly published",
        "synonym",
        "rejected name",
        "later heterotypic synonym",
        "later homotypic synonym",
    }
)


class LPSNTransform(Transform):

    """Transform LPSN GSS CSV bulk export into KGX nodes + edges."""

    def __init__(
        self,
        input_dir: Optional[Path] = None,
        output_dir: Optional[Path] = None,
    ):
        """
        Instantiate.

        Parameters
        ----------
        input_dir:
            Directory holding ``lpsn_gss.csv``. Defaults to ``data/raw/lpsn``
            resolved by the base :class:`Transform` class.
        output_dir:
            Directory to write ``nodes.tsv`` / ``edges.tsv`` into. Defaults
            to ``data/transformed/lpsn`` resolved by the base class.

        """
        super().__init__(LPSN_SOURCE, input_dir, output_dir)
        self.knowledge_source = LPSN_KNOWLEDGE_SOURCE

    # ------------------------------------------------------------------
    # public entry point
    # ------------------------------------------------------------------
    def run(self, data_file: Union[Optional[Path], Optional[str]] = None) -> None:
        """
        Emit ``nodes.tsv`` and ``edges.tsv`` from the LPSN GSS CSV.

        Parameters
        ----------
        data_file:
            Optional override for the input CSV path. If ``None``, uses
            ``self.input_base_dir / "lpsn_gss.csv"``.

        """
        input_file = Path(data_file) if data_file else Path(self.input_base_dir) / "lpsn_gss.csv"
        if not input_file.is_file():
            raise FileNotFoundError(
                f"LPSN GSS CSV not found at {input_file}. "
                "Log in to https://lpsn.dsmz.de/downloads (free registration), "
                "download the GSS CSV, and place it at "
                "data/raw/lpsn/lpsn_gss.csv. "
                "See kg_microbe/transform_utils/lpsn/README.md for details."
            )

        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Parse in a single pass into an in-memory dict keyed by record_no
        # so we can wire subclass_of edges without a second read.
        rows_by_id = self._parse_csv(input_file)

        # Build a (genus_name, sp_epithet, subsp_epithet) -> record_no
        # lookup so subspecies/species can find their parent record.
        parent_lookup = self._build_parent_lookup(rows_by_id)

        # Emit nodes + edges.
        with (
            open(self.output_node_file, "w", newline="") as node_fh,
            open(self.output_edge_file, "w", newline="") as edge_fh,
        ):
            node_writer = csv.writer(node_fh, delimiter="\t")
            edge_writer = csv.writer(edge_fh, delimiter="\t")

            node_writer.writerow(self.node_header)
            edge_writer.writerow(self.edge_header)

            for record_no, row in rows_by_id.items():
                node_writer.writerow(self._make_node_row(record_no, row))
                parent_id = self._find_parent(row, parent_lookup)
                if parent_id and parent_id != record_no:
                    edge_writer.writerow(self._make_subclass_edge(record_no, parent_id))

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------
    def _parse_csv(self, input_file: Path) -> Dict[str, dict]:
        """
        Read the LPSN GSS CSV into a dict keyed by ``record_no``.

        Rows missing ``record_no`` or ``genus_name`` are skipped with a
        warning printed to stdout (consistent with other transforms).
        """
        rows: Dict[str, dict] = {}
        with open(input_file, newline="") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                record_no = (row.get(COL_RECORD_NO) or "").strip()
                genus = (row.get(COL_GENUS) or "").strip()
                if not record_no:
                    print(f"[lpsn] skipping row without record_no: {row}")
                    continue
                if not genus:
                    print(f"[lpsn] skipping row {record_no} without genus_name")
                    continue
                rows[record_no] = row
        return rows

    def _build_parent_lookup(self, rows_by_id: Dict[str, dict]) -> Dict[tuple, str]:
        """
        Return a ``(genus, sp_epithet, subsp_epithet)`` → record_no lookup.

        The lookup key is normalized so a species row keys as
        ``(genus, sp_epithet, "")`` and a genus row keys as
        ``(genus, "", "")``.
        """
        lookup: Dict[tuple, str] = {}
        for record_no, row in rows_by_id.items():
            key = (
                (row.get(COL_GENUS) or "").strip(),
                (row.get(COL_SP_EPITHET) or "").strip(),
                (row.get(COL_SUBSP_EPITHET) or "").strip(),
            )
            lookup[key] = record_no
        return lookup

    def _find_parent(self, row: dict, parent_lookup: Dict[tuple, str]) -> Optional[str]:
        """
        Return the LPSN record_no of ``row``'s immediate parent, or None.

        A subspecies row's parent is the species row with the same
        genus + sp_epithet and empty subsp_epithet. A species row's
        parent is the genus row with the same genus and empty
        sp_epithet/subsp_epithet. A genus row has no in-CSV parent.
        """
        genus = (row.get(COL_GENUS) or "").strip()
        sp = (row.get(COL_SP_EPITHET) or "").strip()
        subsp = (row.get(COL_SUBSP_EPITHET) or "").strip()

        if subsp:
            return parent_lookup.get((genus, sp, ""))
        if sp:
            return parent_lookup.get((genus, "", ""))
        return None

    def _make_node_row(self, record_no: str, row: dict) -> list:
        """
        Build one nodes.tsv row for an LPSN record.

        Node fields:
            id            = ``lpsn:<record_no>``
            category      = ``biolink:OrganismTaxon``
            name          = full scientific name assembled from
                            genus/sp_epithet/subsp_epithet
            description   = ``authors`` (author citation + year)
            xref          = ``record_lnk`` (canonical LPSN page URL)
            provided_by   = infores:lpsn
            deprecated    = True if ``status`` matches a DEPRECATED_STATUS
        """
        genus = (row.get(COL_GENUS) or "").strip()
        sp = (row.get(COL_SP_EPITHET) or "").strip()
        subsp = (row.get(COL_SUBSP_EPITHET) or "").strip()
        name_parts = [p for p in (genus, sp, subsp) if p]
        name = " ".join(name_parts)

        description = (row.get(COL_AUTHORS) or "").strip()
        xref = (row.get(COL_RECORD_LNK) or row.get(COL_ADDRESS) or "").strip()

        status = (row.get(COL_STATUS) or "").strip().lower()
        deprecated_flag = "True" if status in DEPRECATED_STATUSES else ""

        # node_header is [id, category, name, description, xref,
        # provided_by, synonym, same_as, iri, deprecated, ...]
        # Fill in known columns, blank the rest.
        headers = self.node_header
        row_out = [""] * len(headers)
        for col, val in {
            "id": f"{LPSN_PREFIX}{record_no}",
            "category": NCBI_CATEGORY,
            "name": name,
            "description": description,
            "xref": xref,
            "provided_by": LPSN_KNOWLEDGE_SOURCE,
            "deprecated": deprecated_flag,
        }.items():
            if col in headers:
                row_out[headers.index(col)] = val
        return row_out

    def _make_subclass_edge(self, child_record_no: str, parent_record_no: str) -> list:
        """
        Build one edges.tsv row for a subclass_of relation.

        Emits ``subject=lpsn:<child> predicate=biolink:subclass_of
        object=lpsn:<parent> relation=rdfs:subClassOf
        primary_knowledge_source=infores:lpsn``.
        """
        headers = self.edge_header
        row_out = [""] * len(headers)
        for col, val in {
            "subject": f"{LPSN_PREFIX}{child_record_no}",
            "predicate": SUBCLASS_PREDICATE,
            "object": f"{LPSN_PREFIX}{parent_record_no}",
            "relation": RDFS_SUBCLASS_OF,
            "primary_knowledge_source": LPSN_KNOWLEDGE_SOURCE,
        }.items():
            if col in headers:
                row_out[headers.index(col)] = val
        return row_out


# Silence flake8 F401 for CLOSE_MATCH_PREDICATE reserved for the
# follow-up cross-ref PR (issue #484).
_ = CLOSE_MATCH_PREDICATE
_ = ID_COLUMN
