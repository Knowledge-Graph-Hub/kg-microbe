"""
LPSN transform.

Ingests the LPSN GSS (Genus/Species/Subspecies) CSV bulk export into
KGX-format nodes and edges. Each row becomes a `biolink:OrganismTaxon`
node at `lpsn:<record_no>`, with `biolink:subclass_of` edges pointing
from species → genus and subspecies → species so that the LPSN
taxonomic tree is queryable in the merged KG.

The GSS CSV requires a free LPSN login to download. This transform
does NOT fetch it — place the downloaded file at
`data/raw/lpsn_gss.csv` before running:

    poetry run kg transform -s lpsn

See ``kg_microbe/transform_utils/lpsn/README.md`` for the manual
download procedure.

Scope:
- Nodes for every LPSN record (family / genus / species / subspecies).
- subclass_of edges from subspecies → species → genus (only when the
  parent row is present in the same CSV — no LPSN API calls).
- close_match edges to `kgmicrobe.strain:*` for every culture-collection
  deposit named in ``nomenclatural_type``.
- close_match edges to `NCBITaxon:*` for every row (genus / species /
  subspecies) whose scientific name resolves to exactly one NCBITaxon
  via the local NCBI index. The index is pre-filtered to the bacterial
  and archaeal subtree, so multi-kingdom homonyms (``Bacillus`` the
  walking stick, ``Bacillus`` the mineral) are never candidates.
  Lookups match against both ``rdfs:label`` and ``oio:hasExactSynonym``,
  which is how genera resolve — NCBI stores each disambiguated genus's
  bare form as an exact synonym (``Bacillus <firmicutes>`` has
  ``hasExactSynonym Bacillus``). Skipped entirely when the adapter is
  absent (``data/raw/ncbitaxon.owl`` not on disk).
- same_as edges from historical names → correct-name LPSN taxon.
- Illegitimate / synonym rows carry ``deprecated=True``.

Deferred to a follow-up PR (issue #484):
- GTDB cross-refs (via ``data/transformed/gtdb/nodes.tsv`` name-matching).
- Full LPSN JSON API ingest (publication DOI/PMID, ``lpsn_parent_id``
  for the full taxonomic tree, 16S sequences).
"""

import csv
import re
from pathlib import Path
from typing import Any, Dict, Optional, Union

from kg_microbe.transform_utils.constants import (
    CLOSE_MATCH_PREDICATE,
    CLOSE_MATCH_RELATION,
    EXACT_MATCH,
    ID_COLUMN,
    LPSN_SOURCE,
    NCBI_CATEGORY,
    NCBITAXON_SOURCE,
    RDFS_SUBCLASS_OF,
    SAME_AS_PREDICATE,
    STRAIN_PREFIX,
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
COL_NOMENCLATURAL_TYPE = "nomenclatural_type"
COL_RECORD_NO = "record_no"
COL_RECORD_LNK = "record_lnk"

# Split ``nomenclatural_type`` on the standard separators used across
# culture-collection deposit lists in LPSN. Real strings look like
# "ATCC 11775 = DSM 30083 = JCM 1649 = NCTC 9001".
_TYPE_STRAIN_SPLIT = re.compile(r"\s*(?:=|;|,)\s*")

# A single culture-collection designation looks like "<PREFIX><whitespace/dashes><digits/letters>",
# e.g. "ATCC 11775", "DSM-30083", "NCTC 9001". This regex extracts those tokens
# from a raw ``nomenclatural_type`` value that may have additional prose.
_CULTURE_CODE = re.compile(
    r"\b(?:ATCC|DSM|JCM|LMG|NCTC|NRRL|NBRC|CCUG|CCTM|CIP|IAM|IFO|KCTC)"
    r"[\s\-:]*[A-Z]*[\s\-]*[0-9]+[A-Za-z0-9\-]*"
)

# Nomenclatural / taxonomic status tokens that mark a row as ``deprecated=True``.
#
# LPSN's ``status`` column is a SEMICOLON-DELIMITED LIST — a typical value is
# ``"VP; sp. nov.; validly published under the ICNP"`` for a valid current
# species, and ``"VP; sp. nov.; validly published under the ICNP; synonym"``
# or ``"VP; sp. nov.; misspelling, not recommended for medical use"`` for a
# non-current name. We flag as ``deprecated`` any row whose semicolon-split
# tokens intersect this set. Sourced from the real distribution of tokens in
# the 2026-07-03 GSS CSV — see the profiling script in tests/ if this needs
# to be updated for a future LPSN schema change.
DEPRECATED_STATUSES = frozenset(
    {
        "synonym",
        "synonym, not recommended for medical use",
        "synonym of its species",
        "misspelling",
        "misspelling, not recommended for medical use",
        "inaccurate spelling",
        "illegitimate name",
        "rejected name",
        "later heterotypic synonym",
        "later homotypic synonym",
        "not validly published",
        "inappropriate correction",
        "in need of a replacement",
    }
)


class _GTDBRankNameIndex:

    """
    Pre-load GTDB nodes.tsv into a ``(rank_prefix, name) -> [CURIE, ...]`` map.

    Wraps the map behind a single ``curies_by_rank_name(rank, name)``
    method so callers (and tests) inject either a real load or a fake
    dict without noticing the difference.

    GTDB CURIEs look like ``GTDB:s__Escherichia_coli``; we split on the
    two-letter rank prefix and restore spaces, storing
    ``("s__", "Escherichia coli")`` → ``["GTDB:s__Escherichia_coli"]``.
    Multi-character names with underscores in them
    (``s__Escherichia_flexneri_boydii`` → ``"Escherichia flexneri boydii"``)
    end up under a longer normalized name that LPSN's two-word species
    names won't match, which naturally filters out GTDB's placeholder
    variants (``s__Escherichia_coli_E``, ``_F`` etc.) from LPSN's
    canonical ``Escherichia coli``.
    """

    def __init__(self, gtdb_nodes_path: Path):
        """Load ``data/transformed/gtdb/nodes.tsv`` into the index."""
        self._map: Dict[tuple, list] = {}
        with open(gtdb_nodes_path, newline="") as fh:
            reader = csv.DictReader(fh, delimiter="\t")
            for row in reader:
                curie = (row.get("id") or "").strip()
                if not curie.startswith("GTDB:"):
                    continue
                body = curie[len("GTDB:") :]
                # A GTDB body starts with the rank code and a double
                # underscore ("s__", "g__", "f__", ...). Guard against
                # anything shorter than 4 chars (rank + "__" + 1 char).
                if len(body) < 4 or body[1:3] != "__":
                    continue
                rank = body[:3]
                name = body[3:].replace("_", " ")
                self._map.setdefault((rank, name), []).append(curie)
        print(f"[lpsn] GTDB index loaded: {len(self._map):,} distinct (rank, name) keys")

    def curies_by_rank_name(self, rank: str, name: str) -> list:
        """Return the GTDB CURIEs matching ``(rank, name)``, empty list if none."""
        return list(self._map.get((rank, name), []))


class _NCBILabelIndex:

    """
    Pre-load NCBITaxon labels + exact synonyms, filtered to bacteria + archaea.

    Wraps a ``dict[name] -> list[CURIE]`` behind the same one-method
    API OAK's SqlImplementation exposes so callers (and tests) inject
    either without noticing the difference.

    On construction:

    1. BFS the ``rdfs:subClassOf`` edges from ``NCBITaxon:2`` (Bacteria)
       and ``NCBITaxon:2157`` (Archaea) to build the prokaryotic subtree
       (~620 K CURIEs). Every subsequent lookup is filtered against
       this set, which resolves the homonym problem end-to-end:
       ``Bacillus`` disambiguates to ``NCBITaxon:1386``
       ``Bacillus <firmicutes>`` and never to ``NCBITaxon:55087``
       ``Bacillus <walking sticks>``.
    2. Load ``rdfs:label`` (~2.7 M rows) and ``oio:hasExactSynonym``
       (~115 K rows) into a single ``name -> [CURIE, ...]`` map. NCBI
       stores every disambiguated genus's bare form as an exact
       synonym (``Bacillus <firmicutes>`` has ``hasExactSynonym Bacillus``),
       so adding synonyms fixes BOTH the homonym miss AND boosts the
       overall match rate on species/subspecies where LPSN and NCBI
       label the record differently.

    Total build cost: ~5 s for the full DB, once at transform startup.
    Per-lookup: O(1) dict access.
    """

    def __init__(self, db_path):
        """Populate the subtree filter + name index from ``db_path``."""
        import sqlite3

        con = sqlite3.connect(db_path)
        try:
            # 1) Bacterial + archaeal subtree via BFS over subClassOf.
            children: Dict[str, list] = {}
            cur = con.execute(
                "SELECT subject, object FROM statements "
                "WHERE predicate = 'rdfs:subClassOf' "
                "AND subject LIKE 'NCBITaxon:%' AND object LIKE 'NCBITaxon:%'"
            )
            for child, parent in cur:
                children.setdefault(parent, []).append(child)
            subtree: set = set()
            stack = ["NCBITaxon:2", "NCBITaxon:2157"]
            while stack:
                node = stack.pop()
                if node in subtree:
                    continue
                subtree.add(node)
                stack.extend(children.get(node, []))
            self._subtree = subtree

            # 2) Names: rdfs:label ∪ oio:hasExactSynonym, filtered to subtree.
            self._map: Dict[str, list] = {}
            cur = con.execute(
                "SELECT subject, value FROM statements "
                "WHERE predicate IN ('rdfs:label', 'oio:hasExactSynonym') "
                "AND subject LIKE 'NCBITaxon:%'"
            )
            for curie, name in cur:
                if not name or curie not in subtree:
                    continue
                bucket = self._map.setdefault(name, [])
                if curie not in bucket:
                    bucket.append(curie)
        finally:
            con.close()
        print(
            f"[lpsn] NCBI index loaded: {len(subtree):,} bacterial/archaeal CURIEs, "
            f"{len(self._map):,} distinct labels+synonyms"
        )

    def curies_by_label(self, label: str) -> list:
        """Return the list of NCBITaxon CURIEs matching ``label`` (bacteria+archaea only)."""
        return list(self._map.get(label, []))


class LPSNTransform(Transform):

    """Transform LPSN GSS CSV bulk export into KGX nodes + edges."""

    def __init__(
        self,
        input_dir: Optional[Path] = None,
        output_dir: Optional[Path] = None,
        ncbi_impl: Any = None,
        gtdb_index: Any = None,
    ):
        """
        Instantiate.

        Parameters
        ----------
        input_dir:
            Directory holding ``lpsn_gss.csv``. Defaults to
            ``data/raw`` resolved by the base :class:`Transform` class.
        output_dir:
            Directory to write ``nodes.tsv`` / ``edges.tsv`` into.
            Defaults to ``data/transformed/lpsn`` resolved by the base
            class.
        ncbi_impl:
            NCBITaxon name → CURIE lookup. See ``_load_ncbi_adapter``.
        gtdb_index:
            GTDB (rank, normalized_name) → CURIE lookup. When
            ``None`` (the default), the constructor auto-loads
            ``data/transformed/gtdb/nodes.tsv`` if that file exists;
            otherwise GTDB enrichment is silently skipped (so a fresh
            checkout that hasn't run the GTDB transform yet still
            produces a valid — GTDB-less — LPSN output). Tests inject a
            mock here to keep the fixture self-contained.

        """
        super().__init__(LPSN_SOURCE, input_dir, output_dir)
        self.knowledge_source = LPSN_KNOWLEDGE_SOURCE
        self.ncbi_impl = ncbi_impl if ncbi_impl is not None else self._load_ncbi_adapter()
        self.gtdb_index = gtdb_index if gtdb_index is not None else self._load_gtdb_index()
        # Track cross-ref outcomes for the end-of-run summary.
        self._ncbi_stats = {"matched": 0, "unmatched": 0, "ambiguous": 0}
        self._gtdb_stats = {"matched": 0, "unmatched": 0, "ambiguous": 0}

    @staticmethod
    def _load_gtdb_index() -> Any:
        """
        Return a ``_GTDBRankNameIndex`` over ``data/transformed/gtdb/nodes.tsv``, or None.

        GTDB CURIEs carry the rank as a leading two-letter code
        (``d__``, ``p__``, ``c__``, ``o__``, ``f__``, ``g__``,
        ``s__``) and the name with spaces replaced by underscores.
        The index normalizes both sides — strip prefix, restore
        spaces — so LPSN's ``full_name`` (e.g. ``"Escherichia coli"``)
        looks up directly against the correct rank slot without
        collisions between species and genera of the same name.
        """
        default_path = Path("data/transformed/gtdb/nodes.tsv")
        if not default_path.is_file():
            print(
                f"[lpsn] {default_path} not found; GTDB cross-refs skipped. "
                "Run `poetry run kg transform -s gtdb` to enable them."
            )
            return None
        return _GTDBRankNameIndex(default_path)

    @staticmethod
    def _load_ncbi_adapter() -> Any:
        """
        Return a fast in-memory NCBITaxon label index, or None.

        NCBITaxon has ~2.7 M labels. OAK's SqlImplementation issues one
        SQL round-trip per ``curies_by_label`` call (~50 ms), which
        blows up to hours for 34 K LPSN lookups. Instead, we build the
        label → CURIE map once via a direct SQL query on the semsql
        ``statements`` table (~2 s for the full 2.7 M-row build). The
        wrapper class exposes the same one-method API OAK does so tests
        can inject mocks unchanged.

        Returns ``None`` — leaving NCBITaxon enrichment silently
        disabled — if either the OWL file at ``NCBITAXON_SOURCE`` or
        the paired semsql SQLite DB is absent. Absence is expected on
        fresh checkouts and in CI, so this is not fatal.
        """
        if not NCBITAXON_SOURCE.exists():
            print(
                f"[lpsn] {NCBITAXON_SOURCE} not found; NCBITaxon cross-refs skipped. "
                "Run `poetry run kg download` to fetch NCBITaxon."
            )
            return None
        # semsql layout: the .db file lives next to the .owl file.
        db_path = NCBITAXON_SOURCE.with_suffix(".db")
        if not db_path.exists():
            print(f"[lpsn] {db_path} not found (needed for fast label lookup); NCBITaxon cross-refs skipped.")
            return None
        return _NCBILabelIndex(db_path)

    # ------------------------------------------------------------------
    # public entry point
    # ------------------------------------------------------------------
    def run(
        self,
        data_file: Union[Optional[Path], Optional[str]] = None,
        show_status: bool = True,
    ) -> None:
        """
        Emit ``nodes.tsv`` and ``edges.tsv`` from the LPSN GSS CSV.

        Parameters
        ----------
        data_file:
            Optional override for the input CSV path. If ``None``, uses
            ``self.input_base_dir / "lpsn_gss.csv"``.
        show_status:
            Accepted for compatibility with the ``kg transform`` CLI
            (see ``transform.py``). Currently unused because LPSN parsing
            is fast enough (< 1 s per 34K rows) that a progress bar isn't
            worth pulling ``tqdm`` in.

        """
        _ = show_status  # accepted for CLI compatibility; see docstring
        input_file = Path(data_file) if data_file else Path(self.input_base_dir) / "lpsn_gss.csv"
        if not input_file.is_file():
            raise FileNotFoundError(
                f"LPSN GSS CSV not found at {input_file}. "
                "Log in to https://lpsn.dsmz.de/downloads (free registration), "
                "download the GSS CSV, and place it at "
                "data/raw/lpsn_gss.csv. "
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
                # Non-current names (synonyms / misspellings / illegitimate
                # names) carry a numeric ``record_lnk`` pointing at the
                # correct name's ``record_no``. Emit an edge so downstream
                # queries can resolve any historical name to its current
                # authoritative version.
                correct_no = (row.get(COL_RECORD_LNK) or "").strip()
                if correct_no.isdigit() and correct_no != record_no:
                    edge_writer.writerow(self._make_same_as_edge(record_no, correct_no))
                # Only species and subspecies rows carry a culture-collection
                # type-strain designation worth cross-referencing. Genus rows'
                # ``nomenclatural_type`` is the record_no of the type species
                # (a numeric link within the table, not a strain deposit) and
                # is skipped.
                if (row.get(COL_SP_EPITHET) or "").strip():
                    for strain_curie in self._extract_strain_curies(row):
                        edge_writer.writerow(self._make_close_match_edge(record_no, strain_curie))
                # NCBITaxon cross-ref: every rank (genus / species /
                # subspecies) is attempted because the index is filtered to
                # the bacterial + archaeal subtree, so multi-kingdom
                # homonyms (``Bacillus`` the insect, ``Bacillus`` the
                # mineral) are never reachable and can't create false
                # positives. Genera match via exact-synonym lookup because
                # NCBI stores every disambiguated genus's bare form
                # (``Bacillus <firmicutes>`` has ``hasExactSynonym
                # Bacillus``).
                ncbi_curie = self._lookup_ncbi(row)
                if ncbi_curie:
                    edge_writer.writerow(self._make_close_match_edge(record_no, ncbi_curie))
                # GTDB cross-ref: rank-aware name match against a
                # pre-loaded (rank, name) index of data/transformed/gtdb/
                # nodes.tsv. GTDB is bacteria+archaea only so no subtree
                # filter is needed, but rank pairing matters (LPSN genus
                # → GTDB g__, LPSN species → GTDB s__). Subspecies rows
                # are skipped because GTDB has no subspecies rank; the
                # subclass_of chain from LPSN subspecies → species → GTDB
                # gives downstream queries the same reachability in two
                # hops.
                gtdb_curie = self._lookup_gtdb(row)
                if gtdb_curie:
                    edge_writer.writerow(self._make_close_match_edge(record_no, gtdb_curie))

        # End-of-run summary — useful diff signal when NCBI / GTDB
        # dumps are refreshed and match rates shift.
        print(
            f"[lpsn] NCBITaxon cross-refs: "
            f"{self._ncbi_stats['matched']:,} matched, "
            f"{self._ncbi_stats['unmatched']:,} unmatched, "
            f"{self._ncbi_stats['ambiguous']:,} ambiguous"
        )
        print(
            f"[lpsn] GTDB cross-refs:      "
            f"{self._gtdb_stats['matched']:,} matched, "
            f"{self._gtdb_stats['unmatched']:,} unmatched, "
            f"{self._gtdb_stats['ambiguous']:,} ambiguous"
        )

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
            xref          = ``address`` (canonical LPSN page URL)
            provided_by   = infores:lpsn
            deprecated    = True if any semicolon-delimited token of
                            ``status`` intersects DEPRECATED_STATUSES
        """
        genus = (row.get(COL_GENUS) or "").strip()
        sp = (row.get(COL_SP_EPITHET) or "").strip()
        subsp = (row.get(COL_SUBSP_EPITHET) or "").strip()
        name_parts = [p for p in (genus, sp, subsp) if p]
        name = " ".join(name_parts)

        description = (row.get(COL_AUTHORS) or "").strip()
        xref = (row.get(COL_ADDRESS) or "").strip()

        # ``status`` is a semicolon-delimited list, e.g.
        # ``"VP; sp. nov.; validly published under the ICNP; synonym"``.
        # A row is deprecated if any token intersects DEPRECATED_STATUSES.
        raw_status = (row.get(COL_STATUS) or "").lower()
        status_tokens = {t.strip() for t in raw_status.split(";") if t.strip()}
        deprecated_flag = "True" if status_tokens & DEPRECATED_STATUSES else ""

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

    def _extract_strain_curies(self, row: dict) -> list:
        """
        Turn ``row[nomenclatural_type]`` into a list of ``kgmicrobe.strain:*`` CURIEs.

        LPSN's ``nomenclatural_type`` for a species / subspecies row is one or
        more culture-collection deposits separated by ``=`` / ``;`` / ``,``,
        e.g. ``"ATCC 11775 = DSM 30083 = JCM 1649"``. Each deposit is
        normalized with the same rule BacDive uses (see ``bacdive.py:2503``):
        strip whitespace, replace spaces and colons with hyphens. That way
        LPSN's cross-refs land on the same ``kgmicrobe.strain:<code>`` CURIEs
        that BacDive is already emitting, so the merge step reconciles both
        sides without extra plumbing.

        Returns an empty list if the field is blank, whitespace, or contains
        only a taxon name (no culture-collection prefix).
        """
        raw = (row.get(COL_NOMENCLATURAL_TYPE) or "").strip()
        if not raw:
            return []

        curies: list = []
        seen: set = set()
        # First split on the standard deposit separators, then within each
        # part scan for culture-collection tokens. A single part typically
        # contains exactly one deposit; the second pass is defensive against
        # rare "ATCC 11775 (T)" annotations or trailing prose.
        for part in _TYPE_STRAIN_SPLIT.split(raw):
            for match in _CULTURE_CODE.finditer(part):
                token = match.group(0).strip()
                cleaned = token.replace(" ", "-").replace(":", "-")
                if len(cleaned) <= 3:
                    # Same guard BacDive applies — tokens of 3 chars or fewer
                    # are typos, not real deposits.
                    continue
                curie = f"{STRAIN_PREFIX}{cleaned}"
                if curie in seen:
                    continue
                seen.add(curie)
                curies.append(curie)
        return curies

    def _lookup_ncbi(self, row: dict) -> Optional[str]:
        """
        Return the single matching ``NCBITaxon:X`` CURIE for ``row``, or None.

        Uses the OAK adapter's ``curies_by_label`` on the assembled
        scientific name (``genus + sp_epithet [+ subsp_epithet]``).
        Emits at most one edge per row, and only when the lookup
        returns exactly one CURIE. Zero-hit and multi-hit rows are
        counted for the end-of-run summary but do NOT produce an edge:

        - Zero hits: NCBITaxon doesn't index this name (recently
          published, orphaned, or NCBI hasn't harmonized yet).
        - Multi-hit: ambiguous / homonym across kingdoms (rare for
          full species names, more common for genera — one reason
          the caller restricts this to species/subspecies rank).
        """
        if self.ncbi_impl is None:
            return None

        genus = (row.get(COL_GENUS) or "").strip()
        sp = (row.get(COL_SP_EPITHET) or "").strip()
        subsp = (row.get(COL_SUBSP_EPITHET) or "").strip()
        name = " ".join(p for p in (genus, sp, subsp) if p)
        if not name:
            return None

        hits = list(self.ncbi_impl.curies_by_label(name))
        if len(hits) == 1:
            self._ncbi_stats["matched"] += 1
            return hits[0]
        if not hits:
            self._ncbi_stats["unmatched"] += 1
        else:
            self._ncbi_stats["ambiguous"] += 1
        return None

    def _lookup_gtdb(self, row: dict) -> Optional[str]:
        """
        Return the single matching ``GTDB:*`` CURIE for ``row``, or None.

        Uses the pre-loaded (rank, name) index. Only genus and species
        rows are attempted:

        - LPSN genus row (``sp_epithet`` empty) → GTDB ``g__``
        - LPSN species row (``sp_epithet`` set, ``subsp_epithet`` empty)
          → GTDB ``s__``
        - LPSN subspecies rows (``subsp_epithet`` set) → SKIPPED. GTDB
          has no subspecies rank; the LPSN subclass_of chain from
          subspecies → species → GTDB gives downstream queries the same
          reachability in two hops without introducing spurious
          equivalences.

        Emits at most one edge per row, and only when the lookup returns
        exactly one CURIE. Zero-hit and multi-hit rows are counted for
        the end-of-run summary but do NOT produce an edge (GTDB
        placeholder variants like ``s__Escherichia_coli_E`` naturally
        fall out of the exact-name match — see ``_GTDBRankNameIndex``).
        """
        if self.gtdb_index is None:
            return None

        genus = (row.get(COL_GENUS) or "").strip()
        sp = (row.get(COL_SP_EPITHET) or "").strip()
        subsp = (row.get(COL_SUBSP_EPITHET) or "").strip()

        if subsp:
            return None  # no GTDB rank for subspecies
        if sp:
            rank, name = "s__", f"{genus} {sp}"
        elif genus:
            rank, name = "g__", genus
        else:
            return None

        hits = self.gtdb_index.curies_by_rank_name(rank, name)
        if len(hits) == 1:
            self._gtdb_stats["matched"] += 1
            return hits[0]
        if not hits:
            self._gtdb_stats["unmatched"] += 1
        else:
            self._gtdb_stats["ambiguous"] += 1
        return None

    def _make_same_as_edge(self, record_no: str, correct_record_no: str) -> list:
        """
        Build one edges.tsv row linking a non-current name to its correct name.

        Emits ``subject=lpsn:<record_no> predicate=biolink:same_as
        object=lpsn:<correct_record_no> relation=skos:exactMatch
        primary_knowledge_source=infores:lpsn``. LPSN populates
        ``record_lnk`` on every synonym / misspelling / illegitimate name
        with the ``record_no`` of the currently-authoritative name, and
        this edge preserves that link in the KG so historical names
        resolve to their current version in a single hop.
        """
        headers = self.edge_header
        row_out = [""] * len(headers)
        for col, val in {
            "subject": f"{LPSN_PREFIX}{record_no}",
            "predicate": SAME_AS_PREDICATE,
            "object": f"{LPSN_PREFIX}{correct_record_no}",
            "relation": EXACT_MATCH,
            "primary_knowledge_source": LPSN_KNOWLEDGE_SOURCE,
        }.items():
            if col in headers:
                row_out[headers.index(col)] = val
        return row_out

    def _make_close_match_edge(self, record_no: str, strain_curie: str) -> list:
        """
        Build one edges.tsv row linking an LPSN taxon to a culture-collection strain.

        Emits ``subject=lpsn:<record_no> predicate=biolink:close_match
        object=kgmicrobe.strain:<code> relation=skos:closeMatch
        primary_knowledge_source=infores:lpsn``. BacDive's transform emits
        the same ``kgmicrobe.strain:*`` CURIE for every culture-collection
        deposit it sees, so the merge step reconciles both sides.
        """
        headers = self.edge_header
        row_out = [""] * len(headers)
        for col, val in {
            "subject": f"{LPSN_PREFIX}{record_no}",
            "predicate": CLOSE_MATCH_PREDICATE,
            "object": strain_curie,
            "relation": CLOSE_MATCH_RELATION,
            "primary_knowledge_source": LPSN_KNOWLEDGE_SOURCE,
        }.items():
            if col in headers:
                row_out[headers.index(col)] = val
        return row_out


# Silence flake8 F401 for ID_COLUMN reserved for future enrichment
# (NCBITaxon / GTDB cross-refs — see issue #484).
_ = ID_COLUMN
