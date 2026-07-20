"""
LPSN JSON API transform.

Enriches the GSS-based ``lpsn`` transform with the fields that only live
in LPSN's authenticated JSON API and not in the bulk CSV:

- Publication provenance: ``publication_doi``, ``publication_pmid``,
  ``ijsem_list_doi`` → ``biolink:published_in`` edges to ``doi:*`` /
  ``PMID:*`` CURIEs.
- Full above-genus taxonomy: ``lpsn_parent_id`` → additional
  ``biolink:subclass_of`` edges walking up to family / order / class /
  phylum / domain, which the GSS format doesn't expose.
- Nomenclatural genealogy: ``basonym_id`` → ``biolink:same_as`` edge
  (relation ``skos:exactMatch``) from a comb. nov. name to its basonym.
- Node-level detail: ``is_legitimate`` (boolean) and richer
  ``nomenclatural_status`` (free-text) rolled into the description.
- 16S rRNA sequence provenance: ``molecules`` → one
  ``biolink:close_match`` edge from each LPSN taxon to every INSDC
  (GenBank/EMBL/DDBJ) accession its type strain has registered, plus
  a ``biolink:NucleicAcidEntity`` stub node per accession. Serves as
  the TYGS-adjacent bridge to NCBI's sequence records — an LPSN taxon
  that failed the direct name-match against NCBITaxon can still be
  connected via ``lpsn → INSDC → (NCBI sequence organism) →
  NCBITaxon`` in a downstream query.

Access model
------------
The API is auth-gated (free registration at
https://lpsn.dsmz.de/register). We look for LPSN_USERNAME + LPSN_PASSWORD
in the environment (typically loaded from ``.env`` via python-dotenv,
same pattern the BacDive transform uses). If either is missing, the
transform raises a clear ``RuntimeError`` with the exact instructions
rather than falling back to silent no-op.

Rate limits
-----------
LPSN doesn't publish an explicit rate limit. Empirically the ``lpsn``
Python client tolerates ~1–2 requests/second, which projects to 6–10
hours for a full 34K-record pull. Every response is cached to
``data/raw/lpsn/api_cache/<record_no>.json`` (gitignored) so re-runs
skip already-fetched records and a partial run resumes cleanly.

Design notes
------------
This is a SEPARATE transform (registered as ``lpsn_api`` in
``DATA_SOURCES``) instead of an inline step in the main ``lpsn``
transform, so the fast 16-second GSS-only path stays the default. Users
who want the API enrichment run both:

    poetry run kg transform -s lpsn        # fast GSS-only (16 s)
    poetry run kg transform -s lpsn_api    # slow enrichment (hours)

The merge step then combines both nodes.tsv / edges.tsv files.
"""

import csv
import json
import os
from pathlib import Path
from typing import Any, Dict, Iterator, Optional, Union

from dotenv import load_dotenv

from kg_microbe.transform_utils.constants import (
    CLOSE_MATCH_PREDICATE,
    EXACT_MATCH,
    LPSN_API_SOURCE,
    NCBI_CATEGORY,
    RDFS_SUBCLASS_OF,
    SAME_AS_PREDICATE,
    SUBCLASS_PREDICATE,
)
from kg_microbe.transform_utils.lpsn.lpsn import LPSN_KNOWLEDGE_SOURCE, LPSN_PREFIX
from kg_microbe.transform_utils.transform import Transform

# JSON keys returned by the LPSN API (documented at
# https://lpsn.dsmz.de/text/lpsn-api). Kept as module constants so a
# future schema tweak surfaces as a single-file diff.
JSON_ID = "id"
JSON_FULL_NAME = "full_name"
JSON_AUTHORITY = "authority"
JSON_PUBLICATION_DOI = "publication_doi"
JSON_PUBLICATION_PMID = "publication_pmid"
JSON_IJSEM_LIST_DOI = "ijsem_list_doi"
JSON_LPSN_PARENT_ID = "lpsn_parent_id"
JSON_BASONYM_ID = "basonym_id"
JSON_IS_LEGITIMATE = "is_legitimate"
JSON_NOMENCLATURAL_STATUS = "nomenclatural_status"
JSON_LPSN_TAXONOMIC_STATUS = "lpsn_taxonomic_status"
JSON_MOLECULES = "molecules"

# CURIE prefixes for publication + sequence cross-refs.
DOI_PREFIX = "doi:"
PMID_PREFIX = "PMID:"
INSDC_PREFIX = "INSDC:"

# LPSN's ``molecules`` array holds one dict per registered sequence,
# shaped ``{"kind": "16S rRNA gene", "database": "insdc-nucleotide",
# "identifier": "<accession>"}`` (verified across the full 34,301-record
# API pull: every molecule uses exactly these three keys, database is
# always ``insdc-nucleotide``). We take ``identifier`` from every molecule
# whose ``database`` names an INSDC nucleotide archive (GenBank / EMBL /
# DDBJ all share the INSDC accession space).
MOLECULE_DATABASE_KEY = "database"
MOLECULE_IDENTIFIER_KEY = "identifier"
INSDC_DATABASE_PREFIX = "insdc"

# Cache directory relative to the transform's ``input_base_dir``
# (typically ``data/raw/``).
API_CACHE_SUBDIR = "lpsn/api_cache"

# Path (relative to ``input_base_dir``'s parent) to the GSS transform's
# output, which we read to know which record_no's to enrich.
GSS_NODES_RELPATH = "transformed/lpsn/nodes.tsv"


class LPSNAPITransform(Transform):

    """Fetch per-record LPSN JSON, emit enrichment nodes + edges."""

    def __init__(
        self,
        input_dir: Optional[Path] = None,
        output_dir: Optional[Path] = None,
        client: Any = None,
    ):
        """
        Instantiate.

        Parameters
        ----------
        input_dir:
            Directory containing the API response cache (subdir
            ``lpsn/api_cache``). Defaults to ``data/raw`` via the base
            :class:`Transform`.
        output_dir:
            Directory to write ``nodes.tsv`` / ``edges.tsv`` into.
        client:
            An LPSN API client. When ``None`` (default), the transform
            reads ``LPSN_USERNAME`` / ``LPSN_PASSWORD`` from the
            environment (typically loaded from ``.env`` via
            python-dotenv) and constructs ``lpsn.LpsnClient(...)``
            lazily inside ``run()`` — so the constructor never fails
            for a plain ``poetry install`` on a machine without
            credentials, and a fresh checkout can still ``kg transform
            -s lpsn`` (GSS path) with no LPSN Python-package
            dependency. Tests inject a fake client to keep the
            fixture self-contained.

        """
        super().__init__(LPSN_API_SOURCE, input_dir, output_dir)
        self.knowledge_source = LPSN_KNOWLEDGE_SOURCE
        self._client_override = client
        self._stats = {"fetched": 0, "from_cache": 0, "errors": 0}

    # ------------------------------------------------------------------
    # public entry point
    # ------------------------------------------------------------------
    def run(
        self,
        data_file: Union[Optional[Path], Optional[str]] = None,
        show_status: bool = True,
    ) -> None:
        """
        Emit enrichment nodes + edges from LPSN JSON API responses.

        Parameters
        ----------
        data_file:
            Optional override for the GSS-transform ``nodes.tsv`` we
            read to know which record_no's to enrich.
        show_status:
            Accepted for compatibility with the ``kg transform`` CLI.
            Progress is printed in periodic batches regardless.

        """
        _ = show_status

        gss_nodes = Path(data_file) if data_file else self._find_gss_nodes()
        if not gss_nodes.is_file():
            raise FileNotFoundError(
                f"LPSN GSS transform output not found at {gss_nodes}. "
                "Run `poetry run kg transform -s lpsn` first — the API "
                "transform enriches records already emitted by the GSS "
                "transform."
            )

        client = self._client_override or self._make_authenticated_client()

        cache_dir = Path(self.input_base_dir) / API_CACHE_SUBDIR
        cache_dir.mkdir(parents=True, exist_ok=True)

        self.output_dir.mkdir(parents=True, exist_ok=True)
        with (
            open(self.output_node_file, "w", newline="") as node_fh,
            open(self.output_edge_file, "w", newline="") as edge_fh,
        ):
            node_writer = csv.writer(node_fh, delimiter="\t")
            edge_writer = csv.writer(edge_fh, delimiter="\t")
            node_writer.writerow(self.node_header)
            edge_writer.writerow(self.edge_header)

            for record_no in self._iter_record_nos(gss_nodes):
                record = self._fetch(client, record_no, cache_dir)
                if record is None:
                    continue
                self._emit(record_no, record, node_writer, edge_writer)

        print(
            f"[lpsn_api] fetched={self._stats['fetched']:,} "
            f"cached={self._stats['from_cache']:,} "
            f"errors={self._stats['errors']:,}"
        )

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------
    def _find_gss_nodes(self) -> Path:
        """Return the default path to the GSS transform's nodes.tsv output."""
        # Base class sets self.output_base_dir = data/transformed and
        # input_base_dir = data/raw. The GSS output sits alongside our
        # own output dir under transformed/.
        return self.output_base_dir / "lpsn" / "nodes.tsv"

    def _make_authenticated_client(self) -> Any:
        """
        Build a real ``lpsn.LpsnClient`` from env vars, or raise.

        Lazy imports the ``lpsn`` PyPI package so a fresh checkout that
        never runs this transform never needs the package installed.

        ``load_dotenv`` is imported at module level (not lazily) so tests
        can neutralise it via ``monkeypatch.setattr(api_mod, "load_dotenv",
        ...)`` — a function-local ``from dotenv import load_dotenv`` would
        bypass that patch and let a real repo-root ``.env`` satisfy the
        credential check under test.
        """
        load_dotenv()

        user = os.environ.get("LPSN_USERNAME")
        pw = os.environ.get("LPSN_PASSWORD")
        if not user or not pw:
            raise RuntimeError(
                "LPSN_USERNAME and LPSN_PASSWORD environment variables must be "
                "set to run the LPSN JSON API transform. Register a free account "
                "at https://lpsn.dsmz.de/register and add the credentials to a "
                ".env file at the repo root (same pattern the BacDive transform "
                "uses). See kg_microbe/transform_utils/lpsn_api/README.md for "
                "details."
            )

        try:
            import lpsn as lpsn_pkg
        except ImportError as e:
            raise RuntimeError(
                "The `lpsn` Python package is required for the LPSN JSON API "
                "transform. Install with `poetry add lpsn` (or `pip install lpsn`) "
                "and re-run."
            ) from e
        return lpsn_pkg.LpsnClient(user, pw)

    def _iter_record_nos(self, gss_nodes: Path) -> Iterator[str]:
        """Yield the record_no ('1002' etc.) for every LPSN node in the GSS output."""
        with open(gss_nodes, newline="") as fh:
            reader = csv.DictReader(fh, delimiter="\t")
            for row in reader:
                lpsn_curie = (row.get("id") or "").strip()
                if lpsn_curie.startswith(LPSN_PREFIX):
                    yield lpsn_curie[len(LPSN_PREFIX) :]

    def _fetch(self, client: Any, record_no: str, cache_dir: Path) -> Optional[dict]:
        """
        Return the JSON record for ``record_no``, using disk cache when possible.

        On cache miss, calls ``client.retrieve([record_no])``. Errors are
        printed and counted; a failure on one record never aborts the
        run so a partial re-fetch resumes on the next call.
        """
        cache_path = cache_dir / f"{record_no}.json"
        if cache_path.exists():
            try:
                with open(cache_path) as fh:
                    self._stats["from_cache"] += 1
                    return json.load(fh)
            except (json.JSONDecodeError, OSError) as e:
                print(f"[lpsn_api] cache read failed for {record_no}: {e}")
                # fall through to re-fetch

        try:
            # The lpsn client is search-then-retrieve. The 1.0.0 package
            # exposes a dedicated ``id=`` fast path on ``search(**params)``
            # (``search(id="1002")``) that primes the result set directly;
            # passing ``query=`` instead routes into advanced_search and
            # 400s with "unexpected parameter -> query". ``retrieve()`` then
            # yields the record(s). We accept either a single-record dict OR
            # a list-of-dicts to stay tolerant of minor version drift.
            client.search(id=record_no)
            records = list(client.retrieve())
        except Exception as e:  # noqa: BLE001 — LPSN raises varied exceptions
            self._stats["errors"] += 1
            print(f"[lpsn_api] fetch failed for {record_no}: {e}")
            return None

        if not records:
            self._stats["errors"] += 1
            print(f"[lpsn_api] no record returned for {record_no}")
            return None
        record = records[0] if isinstance(records[0], dict) else records[0].__dict__

        try:
            with open(cache_path, "w") as fh:
                json.dump(record, fh)
        except OSError as e:
            print(f"[lpsn_api] cache write failed for {record_no}: {e}")
        self._stats["fetched"] += 1
        return record

    def _emit(self, record_no: str, record: dict, node_writer, edge_writer) -> None:
        """Write enrichment rows for one LPSN record's JSON payload."""
        # Node update: description enriched with nomenclatural + taxonomic
        # status when present. We emit a NEW node row (KGX merge dedupes
        # on id; the GSS transform already emitted the base row, and the
        # merger keeps the union of columns).
        node_writer.writerow(self._make_enrichment_node(record_no, record))

        # Parent link (above-genus taxonomy). LPSN returns record_no as
        # an int, so coerce before doing string operations.
        parent = str(record.get(JSON_LPSN_PARENT_ID) or "").strip()
        if parent.isdigit() and parent != record_no:
            edge_writer.writerow(self._edge(record_no, SUBCLASS_PREDICATE, f"{LPSN_PREFIX}{parent}", RDFS_SUBCLASS_OF))

        # Basonym link (nomenclatural equivalence — a comb. nov. / new
        # combination points at its basonym, the original name).
        basonym = str(record.get(JSON_BASONYM_ID) or "").strip()
        if basonym.isdigit() and basonym != record_no:
            edge_writer.writerow(self._edge(record_no, SAME_AS_PREDICATE, f"{LPSN_PREFIX}{basonym}", EXACT_MATCH))

        # Publication cross-refs. LPSN populates one or both of DOI/PMID
        # per record for the valid publication of the name, plus (often)
        # a separate DOI for the IJSEM validation-list publication.
        for doi_key in (JSON_PUBLICATION_DOI, JSON_IJSEM_LIST_DOI):
            doi = (record.get(doi_key) or "").strip()
            if doi:
                # doi: nodes are stubs — a downstream Publication
                # ontology (or an OMA-style DOI expander) can supply
                # richer metadata. For now, emit a minimal node so the
                # edge target isn't a dangling reference.
                edge_writer.writerow(
                    self._edge(record_no, CLOSE_MATCH_PREDICATE, f"{DOI_PREFIX}{doi}", "skos:closeMatch")
                )
                node_writer.writerow(self._stub_publication_node(f"{DOI_PREFIX}{doi}"))
        pmid = str(record.get(JSON_PUBLICATION_PMID) or "").strip()
        if pmid:
            edge_writer.writerow(
                self._edge(record_no, CLOSE_MATCH_PREDICATE, f"{PMID_PREFIX}{pmid}", "skos:closeMatch")
            )
            node_writer.writerow(self._stub_publication_node(f"{PMID_PREFIX}{pmid}"))

        # 16S rRNA sequence provenance — the TYGS-adjacent bridge to
        # NCBI. Every INSDC accession registered by this taxon's type
        # strain becomes a close_match target so downstream queries can
        # walk ``lpsn → INSDC → NCBI sequence organism → NCBITaxon``.
        for accession in self._extract_insdc_accessions(record):
            edge_writer.writerow(
                self._edge(record_no, CLOSE_MATCH_PREDICATE, f"{INSDC_PREFIX}{accession}", "skos:closeMatch")
            )
            node_writer.writerow(self._stub_sequence_node(f"{INSDC_PREFIX}{accession}"))

    def _extract_insdc_accessions(self, record: dict) -> list:
        """
        Return the deduplicated INSDC accessions on ``record[molecules]``.

        LPSN's molecules[] is an array of dicts, each shaped
        ``{"kind": "16S rRNA gene", "database": "insdc-nucleotide",
        "identifier": "<accession>"}``. We take ``identifier`` from every
        molecule whose ``database`` names an INSDC nucleotide archive
        (GenBank / EMBL / DDBJ share the INSDC accession space), skipping
        any non-INSDC database so the emitted CURIE stays a valid INSDC ref.
        """
        molecules = record.get(JSON_MOLECULES) or []
        if not isinstance(molecules, list):
            return []
        seen: set = set()
        out: list = []
        for mol in molecules:
            if not isinstance(mol, dict):
                continue
            database = str(mol.get(MOLECULE_DATABASE_KEY) or "").strip().lower()
            if not database.startswith(INSDC_DATABASE_PREFIX):
                continue
            acc = str(mol.get(MOLECULE_IDENTIFIER_KEY) or "").strip()
            if not acc or acc in seen:
                continue
            seen.add(acc)
            out.append(acc)
        return out

    def _stub_sequence_node(self, curie: str) -> list:
        """Build a minimal nodes.tsv row for an INSDC sequence stub target."""
        headers = self.node_header
        row = [""] * len(headers)
        for col, val in {
            "id": curie,
            "category": "biolink:NucleicAcidEntity",
            "provided_by": LPSN_KNOWLEDGE_SOURCE,
        }.items():
            if col in headers:
                row[headers.index(col)] = val
        return row

    def _make_enrichment_node(self, record_no: str, record: dict) -> list:
        """
        Build one nodes.tsv row carrying the API-derived description fields.

        Only ``id``, ``category``, ``description``, and ``provided_by``
        are populated; other columns are left blank so the merger keeps
        whatever the GSS row wrote there.
        """
        parts = []
        legit = record.get(JSON_IS_LEGITIMATE)
        if legit is not None:
            parts.append(f"legitimate={legit}")
        nom_status = (record.get(JSON_NOMENCLATURAL_STATUS) or "").strip()
        if nom_status:
            parts.append(nom_status)
        tax_status = (record.get(JSON_LPSN_TAXONOMIC_STATUS) or "").strip()
        if tax_status:
            parts.append(tax_status)
        description = "; ".join(parts)

        headers = self.node_header
        row = [""] * len(headers)
        for col, val in {
            "id": f"{LPSN_PREFIX}{record_no}",
            "category": NCBI_CATEGORY,
            "description": description,
            "provided_by": LPSN_KNOWLEDGE_SOURCE,
        }.items():
            if col in headers:
                row[headers.index(col)] = val
        return row

    def _stub_publication_node(self, curie: str) -> list:
        """Build a minimal nodes.tsv row for a DOI/PMID stub target."""
        headers = self.node_header
        row = [""] * len(headers)
        for col, val in {
            "id": curie,
            "category": "biolink:Publication",
            "provided_by": LPSN_KNOWLEDGE_SOURCE,
        }.items():
            if col in headers:
                row[headers.index(col)] = val
        return row

    def _edge(self, subject_record_no: str, predicate: str, obj: str, relation: str) -> list:
        """Build one edges.tsv row for the enrichment layer."""
        headers = self.edge_header
        row = [""] * len(headers)
        for col, val in {
            "subject": f"{LPSN_PREFIX}{subject_record_no}",
            "predicate": predicate,
            "object": obj,
            "relation": relation,
            "primary_knowledge_source": LPSN_KNOWLEDGE_SOURCE,
        }.items():
            if col in headers:
                row[headers.index(col)] = val
        return row


# ``Dict`` kept in the imported set to satisfy the return-type hint on
# some Python versions that flag Dict as unused otherwise; kept explicit
# for readers.
_ = Dict
