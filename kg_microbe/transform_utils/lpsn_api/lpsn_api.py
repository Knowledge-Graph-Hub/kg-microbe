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

    poetry run kg transform -s lpsn        # fast GSS-only (16 s), after gtdb and ontologies
    poetry run kg transform -s lpsn_api    # slow enrichment (hours)

The merge step then combines both nodes.tsv / edges.tsv files.
"""

import csv
import html
import json
import os
import re
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, Optional, Union

import requests
from dotenv import load_dotenv

from kg_microbe.merge_utils.source_admission import SourceAdmission
from kg_microbe.transform_utils.constants import (
    AGENT_TYPE_COLUMN,
    CATEGORY_COLUMN,
    CLOSE_MATCH_PREDICATE,
    DESCRIPTION_COLUMN,
    EXACT_MATCH,
    ID_COLUMN,
    KNOWLEDGE_ASSERTION,
    KNOWLEDGE_LEVEL_COLUMN,
    LPSN_API_SOURCE,
    MANUAL_AGENT,
    NAME_COLUMN,
    NCBI_CATEGORY,
    PROVIDED_BY_COLUMN,
    RDFS_SUBCLASS_OF,
    SAME_AS_PREDICATE,
    SUBCLASS_PREDICATE,
)
from kg_microbe.transform_utils.lpsn.lpsn import LPSN_KNOWLEDGE_SOURCE, LPSN_PREFIX
from kg_microbe.transform_utils.lpsn_api.native_inputs import (
    AUDIT_COLUMNS,
    AUDIT_FILE,
    GSS_ROLE,
    RECORD_ROLE_PREFIX,
    audit_rows,
    validate_record,
    validate_record_no,
    verify_native_contract,
    verify_record_audit,
)
from kg_microbe.transform_utils.transform import Transform
from kg_microbe.utils.atomic_io import atomic_write
from kg_microbe.utils.source_finalization import SourceFinalizationRequired
from kg_microbe.utils.tsv_io import tsv_writer

# JSON keys returned by the LPSN API (documented at
# https://lpsn.dsmz.de/text/lpsn-api). Kept as module constants so a
# future schema tweak surfaces as a single-file diff.
JSON_ID = "id"
JSON_FULL_NAME = "full_name"
JSON_AUTHORITY = "authority"
JSON_PUBLICATION_DOI = "publication_doi"
JSON_PUBLICATION_PMID = "publication_pmid"
JSON_PUBLICATION_TEXT = "publication_text"
JSON_IJSEM_LIST_DOI = "ijsem_list_doi"
JSON_IJSEM_LIST_TEXT = "ijsem_list_text"
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

# Names the JSON API does not serve at all: the 665 basonym targets in the
# 2026-09-10 graph are pre-Approved-Lists names ("not validly published,
# basonym of name in Approved Lists") and ``fetch/<id>`` returns an empty
# result set for every one of them by every route (#1004). LPSN's website
# still has a page per record number, unauthenticated, with the rank and
# name in the title. Those pages are cached here, apart from the API
# cache, so a web-derived record is never mistaken for an API record.
WEB_CACHE_SUBDIR = "lpsn/web_cache"
LPSN_TAXON_PAGE_URL = "https://lpsn.dsmz.de/taxon/{record_no}"
WEB_PAGE_TIMEOUT_S = 30
#: Marks a record dict assembled from the web page rather than the API.
WEB_RECORD_SOURCE_KEY = "kgmicrobe_source"
WEB_RECORD_SOURCE = "lpsn-web-page"
_TITLE_RE = re.compile(r"<title>\s*([A-Za-z ]+?)\s*:\s*(.+?)\s*</title>", re.IGNORECASE | re.DOTALL)
_STATUS_RE = re.compile(r"<b>\s*(Nomenclatural|Taxonomic) status:\s*</b>\s*(?:<[^>]*>\s*)*([^<]+)", re.IGNORECASE)

# Path (relative to ``input_base_dir``'s parent) to the GSS transform's
# output, which we read to know which record_no's to enrich.
GSS_NODES_RELPATH = "transformed/lpsn/nodes.tsv"


def fetch_taxon_page(record_no: str) -> Optional[str]:
    """
    Return the HTML of LPSN's web page for ``record_no``, or ``None``.

    Only reached for records the JSON API has no result for; the page is
    public and needs no credentials. Any transport or HTTP failure is
    reported and yields ``None`` so the caller falls back to a bare stub
    rather than aborting the run.
    """
    url = LPSN_TAXON_PAGE_URL.format(record_no=record_no)
    try:
        resp = requests.get(url, timeout=WEB_PAGE_TIMEOUT_S, headers={"User-Agent": "kg-microbe lpsn_api transform"})
    except requests.RequestException as e:
        print(f"[lpsn_api] web page fetch failed for {record_no}: {e}")
        return None
    if resp.status_code != 200:
        print(f"[lpsn_api] web page fetch for {record_no} returned HTTP {resp.status_code}")
        return None
    return resp.text


def parse_taxon_page(record_no: str, page: str) -> Optional[dict]:
    """
    Build an API-shaped record from an LPSN taxon page, or ``None``.

    The page title is ``<rank>: <name>`` (``Species: Bacterium sonnei``);
    that is the whole reason the page is worth fetching, so no title means
    no record. Nomenclatural and taxonomic status are taken when present.
    The dict carries :data:`WEB_RECORD_SOURCE_KEY` so consumers can tell
    it from an API record; it never carries ids to link to.
    """
    match = _TITLE_RE.search(page)
    if not match:
        return None
    rank, name = match.groups()
    name = html.unescape(re.sub(r"<[^>]+>", "", name)).strip().strip('"').strip()
    if not name:
        return None
    record = {
        "id": int(record_no) if record_no.isdigit() else record_no,
        "category": rank.strip().lower(),
        JSON_FULL_NAME: name,
        "lpsn_address": LPSN_TAXON_PAGE_URL.format(record_no=record_no),
        WEB_RECORD_SOURCE_KEY: WEB_RECORD_SOURCE,
    }
    for kind, text in _STATUS_RE.findall(page):
        key = JSON_NOMENCLATURAL_STATUS if kind.lower() == "nomenclatural" else JSON_LPSN_TAXONOMIC_STATUS
        record[key] = html.unescape(text).strip()
    return record


class LPSNAPITransform(Transform):
    """Fetch per-record LPSN JSON, emit enrichment nodes + edges."""

    #: Reads this transform's output; see Transform.TRANSFORM_INPUTS (#845).
    TRANSFORM_INPUTS = ("lpsn",)
    REQUIRED_CONSUMED_INPUTS = (GSS_ROLE,)
    REQUIRED_AUDIT_FILES = (AUDIT_FILE,)

    def __init__(
        self,
        input_dir: Optional[Path] = None,
        output_dir: Optional[Path] = None,
        client: Any = None,
        page_fetch: Optional[Callable[[str], Optional[str]]] = None,
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
        page_fetch:
            Fetches LPSN's web page for a record number the API has no
            record for (#1004). Defaults to :func:`fetch_taxon_page`;
            tests inject a fake so nothing touches the network.

        """
        super().__init__(LPSN_API_SOURCE, input_dir, output_dir)
        self.knowledge_source = LPSN_KNOWLEDGE_SOURCE
        self._client_override = client
        self._page_fetch = page_fetch or fetch_taxon_page
        self._web_cache_dir: Optional[Path] = None
        self._publication_citations: Dict[str, Dict[str, set]] = {}
        self._native_contract = None
        self._native_input_admission = None
        self._stats = {
            "fetched": 0,
            "from_cache": 0,
            "errors": 0,
            "api_misses": 0,
            "linked_declared": 0,
            "linked_from_web": 0,
            "linked_stubbed": 0,
        }

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
        self.begin_consumed_inputs()
        self._native_contract = None
        self._native_input_admission = SourceAdmission()

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
        self._web_cache_dir = Path(self.input_base_dir) / WEB_CACHE_SUBDIR
        self._web_cache_dir.mkdir(parents=True, exist_ok=True)

        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._publication_citations = {}
        raw = Path(self.input_base_dir).absolute()
        self._native_contract = {
            "version": 1,
            "raw_locator": str(raw),
            "raw_directory": str(self._native_input_admission.bind_path(raw)),
            "cache_directory": str(self._native_input_admission.bind_path(cache_dir)),
            "gss": {"locator": str(gss_nodes.absolute())},
            "records": {},
        }
        # Atomic: a crash mid-run must leave no nodes.tsv/edges.tsv at all. A
        # truncated pair reads as complete to the merge, and the lpsn transform
        # already publishes this way (#820, #981, #985).
        with (
            atomic_write(self.output_node_file, newline="") as node_fh,
            atomic_write(self.output_edge_file, newline="") as edge_fh,
            atomic_write(self.output_dir / AUDIT_FILE, newline="") as audit_fh,
        ):
            node_writer = tsv_writer(node_fh)
            edge_writer = tsv_writer(edge_fh)
            node_writer.writerow(self.node_header)
            edge_writer.writerow(self.edge_header)

            # Every record the GSS declares, plus every record this file links
            # to. The parent chain above genus and the basonym targets are not
            # in the GSS, and without a node row KGX invents a bare NamedThing
            # for each at merge time -- 1,344 of them in the 2026-09-08 graph
            # (#991). Same rule LPSN applies to deposits (#932).
            self._declared = set(self._iter_record_nos(gss_nodes))
            for record_no in sorted(self._declared):
                record = self._fetch(client, record_no, cache_dir)
                if record is None:
                    continue
                self._emit(record_no, record, node_writer, edge_writer)
                for ref in self._linked_record_nos(record_no, record):
                    self._ensure_declared(client, ref, cache_dir, node_writer, edge_writer)
            self._emit_publication_nodes(node_writer)
            audit_writer = csv.writer(audit_fh, delimiter="\t")
            audit_writer.writerow(AUDIT_COLUMNS)
            audit_writer.writerows(audit_rows(self._native_contract))
            # Abort atomic graph writes if any selected input drifted during the run.
            self._native_input_admission = verify_native_contract(
                self.producer_native_inputs,
                self.consumed_input_snapshots,
                raw,
                admission=self._native_input_admission,
            )

        self.record_producer_audit(AUDIT_FILE)
        self.verify_native_inputs()

        print(
            f"[lpsn_api] fetched={self._stats['fetched']:,} "
            f"cached={self._stats['from_cache']:,} "
            f"errors={self._stats['errors']:,} "
            f"api_misses={self._stats.get('api_misses', 0):,} "
            f"linked_records_declared={self._stats.get('linked_declared', 0):,} "
            f"linked_records_from_web={self._stats.get('linked_from_web', 0):,} "
            f"linked_records_stubbed={self._stats.get('linked_stubbed', 0):,}"
        )

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------
    @property
    def producer_native_inputs(self):
        """Return the selected API record inventory without exposing mutable producer state."""
        return deepcopy(self._native_contract)

    @producer_native_inputs.setter
    def producer_native_inputs(self, recorded):
        """Reject replacing actual reads with assertions copied from a completion report."""
        if recorded != self.producer_native_inputs:
            raise SourceFinalizationRequired("LPSN API native reads differ from recorded completion; run the producer")

    def verify_native_inputs(self, *, byte_verified=False, output_dir=None):
        """Require selected API record bytes, locators and the mandatory producer audit."""
        del byte_verified
        self._native_input_admission = verify_native_contract(
            self.producer_native_inputs,
            self.consumed_input_snapshots,
            self.input_base_dir,
            admission=self._native_input_admission,
        )
        # Finalization atomically republishes audits with identical bytes. Do
        # not keep output inodes or temporary staging paths in the input guard.
        verify_record_audit(self.producer_native_inputs, Path(output_dir or self.output_dir) / AUDIT_FILE)

    @classmethod
    def verify_recorded_native_inputs(cls, report, report_path, *, admission=None):
        """Bind saved API reads to their selected cache paths during read-only merge admission."""
        contract = report.get("producer_native_inputs")
        raw = contract.get("raw_locator") if isinstance(contract, dict) else None
        if (
            report_path is None
            or not isinstance(raw, str)
            or not Path(raw).is_absolute()
            or str(Path(raw).resolve()) != report.get("raw_input_directory")
        ):
            raise SourceFinalizationRequired("LPSN API validation requires its completion location and raw directory")
        return verify_native_contract(
            contract,
            report.get("consumed_inputs", {}),
            raw,
            audit_path=Path(report_path).parent / AUDIT_FILE,
            admission=admission,
        )

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
        self._native_input_admission.bind_path(gss_nodes)
        with self.consume_input(GSS_ROLE, gss_nodes) as fh:
            reader = csv.DictReader(fh, delimiter="\t")
            for row in reader:
                lpsn_curie = (row.get("id") or "").strip()
                if lpsn_curie.startswith(LPSN_PREFIX):
                    record_no = lpsn_curie[len(LPSN_PREFIX) :]
                    validate_record_no(record_no)
                    yield record_no
        self._native_contract["gss"].update(self._consumed_input_snapshots[GSS_ROLE])

    def _fetch(self, client: Any, record_no: str, cache_dir: Path) -> Optional[dict]:
        """
        Return the JSON record for ``record_no``, using disk cache when possible.

        On cache miss, calls ``client.search(id=record_no)`` then
        ``client.retrieve()`` (the lpsn 1.0.0 search-then-retrieve flow).
        Transport errors are counted; malformed or misidentified payloads abort
        before attribution. Every usable response is persisted and consumed from
        an immutable snapshot, including records fetched into a cold cache.
        """
        validate_record_no(record_no)
        cache_path = (cache_dir / f"{record_no}.json").absolute()
        self._native_input_admission.bind_path(cache_path)
        if cache_path.exists():
            record = self._consume_api_record(record_no, cache_path)
            self._stats["from_cache"] += 1
            return record

        try:
            # The lpsn client is search-then-retrieve. The 1.0.0 package
            # exposes a dedicated ``id=`` fast path on ``search(**params)``
            # (``search(id="1002")``) that primes the result set directly;
            # passing ``query=`` instead routes into advanced_search and
            # 400s with "unexpected parameter -> query". ``retrieve()`` then
            # yields records, each as a dict or an API client record object.
            client.search(id=record_no)
            records = list(client.retrieve())
        except Exception as e:  # noqa: BLE001 — LPSN raises varied exceptions
            self._stats["errors"] += 1
            print(f"[lpsn_api] fetch failed for {record_no}: {e}")
            self._record_absent_api_record(record_no, cache_path)
            return None

        if not records:
            # Not an error: the API answered and has no record. Counted apart
            # from transport/parse failures, because 665 of these are expected
            # (pre-Approved-Lists basonyms) and are then labelled from the web
            # page; reading them as errors next to 665 successes misled (#1020).
            self._stats["api_misses"] = self._stats.get("api_misses", 0) + 1
            print(f"[lpsn_api] no record returned for {record_no}")
            self._record_absent_api_record(record_no, cache_path)
            return None
        if len(records) != 1:
            raise SourceFinalizationRequired(f"LPSN API returned multiple payloads for requested record {record_no}")
        value = records[0]
        record = validate_record(value if isinstance(value, dict) else getattr(value, "__dict__", value), record_no)
        with atomic_write(cache_path) as fh:
            json.dump(record, fh)
        record = self._consume_api_record(record_no, cache_path)
        self._stats["fetched"] += 1
        return record

    def _consume_api_record(self, record_no, cache_path):
        """Parse and validate the same immutable bytes recorded for source completion."""
        role = RECORD_ROLE_PREFIX + record_no
        with self.consume_input(role, cache_path) as handle:
            record = validate_record(json.load(handle), record_no)
        snapshot = self._consumed_input_snapshots[role]
        self._native_contract["records"][record_no] = {"state": "present", "locator": str(cache_path), **snapshot}
        return record

    def _record_absent_api_record(self, record_no, cache_path):
        """Retain absent selected cache paths; this is not a snapshot of a remote API answer."""
        if self._native_input_admission.capture(cache_path, optional=True) is not None:
            raise SourceFinalizationRequired(f"LPSN API cache appeared during retrieval: {cache_path}")
        self._native_contract["records"][record_no] = {
            "state": "absent",
            "locator": str(cache_path),
            "path": str(cache_path.resolve()),
            "sha256": "",
        }

    #: How far up `lpsn_parent_id` to walk. LPSN's ranks stop at domain; a
    #: cycle in the data would otherwise be an infinite fetch loop.
    _MAX_LINK_DEPTH = 12

    @staticmethod
    def _linked_record_nos(record_no: str, record: dict) -> list:
        """
        Return the LPSN record numbers this record's edges point at.

        :param record_no: The record being emitted.
        :param record: Its JSON payload.
        :return: Parent and basonym record numbers, as strings, excluding self.
        """
        refs = []
        for key in (JSON_LPSN_PARENT_ID, JSON_BASONYM_ID):
            value = str(record.get(key) or "").strip()
            if value.isdigit() and value != record_no:
                refs.append(value)
        return refs

    def _ensure_declared(
        self, client: Any, record_no: str, cache_dir: Path, node_writer, edge_writer, depth: int = 0
    ) -> None:
        """
        Write a node row for a linked record the GSS does not cover, once.

        Fetches the record so the node carries LPSN's own name and status,
        emits its own parent/basonym edges, and walks up so the chain to the
        domain is declared end to end. When the API has nothing for it --
        every basonym that predates the Approved Lists, #1004 -- the name
        and rank come from LPSN's web page for the record instead, and the
        description says so. Only when that fails too does a bare stub
        declare the endpoint: an unnamed node in our own namespace beats one
        KGX invents, because it says where it came from.

        :param client: The LPSN client.
        :param record_no: The referenced record number.
        :param cache_dir: API cache directory.
        :param node_writer: Nodes writer.
        :param edge_writer: Edges writer.
        :param depth: Recursion depth, capped at :attr:`_MAX_LINK_DEPTH`.
        """
        if record_no in self._declared or depth > self._MAX_LINK_DEPTH:
            return
        self._declared.add(record_no)
        record = self._fetch(client, record_no, cache_dir)
        if record is None:
            web_record = self._fetch_from_web(record_no)
            if web_record is None:
                node_writer.writerow(self._stub_linked_node(record_no))
                self._stats["linked_stubbed"] = self._stats.get("linked_stubbed", 0) + 1
                return
            node_writer.writerow(self._make_web_linked_node(record_no, web_record))
            self._stats["linked_from_web"] = self._stats.get("linked_from_web", 0) + 1
            return
        node_writer.writerow(self._make_linked_node(record_no, record))
        self._stats["linked_declared"] = self._stats.get("linked_declared", 0) + 1
        self._emit_links(record_no, record, edge_writer)
        for ref in self._linked_record_nos(record_no, record):
            self._ensure_declared(client, ref, cache_dir, node_writer, edge_writer, depth + 1)

    def _emit(self, record_no: str, record: dict, node_writer, edge_writer) -> None:
        """Write enrichment rows for one LPSN record's JSON payload."""
        # Node update: description enriched with nomenclatural + taxonomic
        # status when present. We emit a NEW node row (KGX merge dedupes
        # on id; the GSS transform already emitted the base row, and the
        # merger keeps the union of columns).
        node_writer.writerow(self._make_enrichment_node(record_no, record))

        self._emit_links(record_no, record, edge_writer)

        # Publication cross-refs. LPSN populates one or both of DOI/PMID
        # per record for the valid publication of the name, plus (often)
        # a separate DOI for the IJSEM validation-list publication.
        for doi_key, text_key in (
            (JSON_PUBLICATION_DOI, JSON_PUBLICATION_TEXT),
            (JSON_IJSEM_LIST_DOI, JSON_IJSEM_LIST_TEXT),
        ):
            doi = (record.get(doi_key) or "").strip()
            if doi:
                # The associated source citation supplies a display label,
                # not an inferred paper title. Conflicts are resolved only
                # after all source records have contributed their evidence.
                edge_writer.writerow(
                    self._edge(record_no, CLOSE_MATCH_PREDICATE, f"{DOI_PREFIX}{doi}", "skos:closeMatch")
                )
                self._record_publication_citation(f"{DOI_PREFIX}{doi}", record_no, text_key, record.get(text_key))
        pmid = str(record.get(JSON_PUBLICATION_PMID) or "").strip()
        if pmid:
            edge_writer.writerow(
                self._edge(record_no, CLOSE_MATCH_PREDICATE, f"{PMID_PREFIX}{pmid}", "skos:closeMatch")
            )
            self._record_publication_citation(
                f"{PMID_PREFIX}{pmid}", record_no, JSON_PUBLICATION_TEXT, record.get(JSON_PUBLICATION_TEXT)
            )

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

    def _emit_links(self, record_no: str, record: dict, edge_writer) -> None:
        """
        Write the parent and basonym edges for one record.

        :param record_no: The record.
        :param record: Its JSON payload.
        :param edge_writer: Edges writer.
        """
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

    def _make_linked_node(self, record_no: str, record: dict) -> list:
        """
        Build a full node row for a linked record the GSS does not carry.

        :param record_no: The record.
        :param record: Its JSON payload; ``full_name`` becomes the label.
        :return: A row aligned to ``node_header``.
        """
        row = self._make_enrichment_node(record_no, record)
        headers = self.node_header
        if "name" in headers:
            row[headers.index("name")] = (record.get(JSON_FULL_NAME) or "").strip()
        return row

    def _fetch_from_web(self, record_no: str) -> Optional[dict]:
        """
        Return a record assembled from LPSN's web page, using the web cache.

        A cached ``None`` is not stored: a page that failed once is retried
        on the next run, the same as an API miss. Parse failures are
        reported so a changed page layout shows up as a count, not as a
        quiet return to 665 unnamed stubs.
        """
        cache_dir = self._web_cache_dir
        cache_path = cache_dir / f"{record_no}.json" if cache_dir is not None else None
        if cache_path is not None and cache_path.exists():
            try:
                with open(cache_path) as fh:
                    return json.load(fh)
            except (json.JSONDecodeError, OSError) as e:
                print(f"[lpsn_api] web cache read failed for {record_no}: {e}")
        page = self._page_fetch(record_no)
        if page is None:
            return None
        record = parse_taxon_page(record_no, page)
        if record is None:
            print(f"[lpsn_api] web page for {record_no} has no parsable title")
            return None
        if cache_path is not None:
            try:
                with open(cache_path, "w") as fh:
                    json.dump(record, fh)
            except OSError as e:
                print(f"[lpsn_api] web cache write failed for {record_no}: {e}")
        return record

    def _make_web_linked_node(self, record_no: str, record: dict) -> list:
        """
        Build a node row for a linked record labelled from its LPSN web page.

        Same shape as :meth:`_make_linked_node`; the description records
        that the API had no record and where the label came from.
        """
        row = self._make_linked_node(record_no, record)
        headers = self.node_header
        if "description" in headers:
            idx = headers.index("description")
            note = (
                "LPSN record linked from another record; not served by the LPSN JSON API, "
                f"name and rank taken from {record.get('lpsn_address', 'its LPSN web page')}"
            )
            row[idx] = f"{row[idx]}; {note}" if row[idx] else note
        return row

    def _stub_linked_node(self, record_no: str) -> list:
        """
        Build a bare node row for a linked record the API could not supply.

        :param record_no: The record.
        :return: A row aligned to ``node_header``.
        """
        headers = self.node_header
        row = [""] * len(headers)
        for col, val in {
            "id": f"{LPSN_PREFIX}{record_no}",
            "category": NCBI_CATEGORY,
            "description": (
                "LPSN record linked from another record; not retrievable from the LPSN API "
                "or its web page when this file was built"
            ),
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

    def _record_publication_citation(self, curie: str, record_no: str, field: str, value: Any) -> None:
        """Retain exact source-field attribution; malformed/missing text supplies no label."""
        citation = value.strip() if isinstance(value, str) else ""
        candidates = self._publication_citations.setdefault(curie, {})
        candidates.setdefault(citation, set()).add(f"{LPSN_PREFIX}{record_no}.{field}")

    def _emit_publication_nodes(self, writer) -> None:
        """Emit one stable node per publication, withholding conflicting citation labels."""
        for curie, candidates in sorted(self._publication_citations.items()):
            nonempty = [citation for citation in candidates if citation]
            label = nonempty[0] if len(nonempty) == 1 else ""
            if label:
                status = "Label is LPSN source citation text, not a separately verified publication title."
            elif nonempty:
                status = "Conflicting LPSN citation texts; publication label remains unresolved."
            else:
                status = "No usable LPSN source citation text; publication label remains unresolved."
            provenance = [
                {"citation": citation, "source_fields": sorted(locators)}
                for citation, locators in sorted(candidates.items())
            ]
            writer.writerow(
                self._stub_publication_node(curie, label, status + " " + json.dumps(provenance, sort_keys=True))
            )

    def _stub_publication_node(self, curie: str, label: str = "", description: str = "") -> list:
        """Build a DOI/PMID node carrying only unambiguous source-owned citation text."""
        headers = self.node_header
        row = [""] * len(headers)
        for col, val in {
            ID_COLUMN: curie,
            CATEGORY_COLUMN: "biolink:Publication",
            NAME_COLUMN: label,
            DESCRIPTION_COLUMN: description,
            PROVIDED_BY_COLUMN: LPSN_KNOWLEDGE_SOURCE,
        }.items():
            if col in headers:
                row[headers.index(col)] = val
        return row

    def _edge(self, subject_record_no: str, predicate: str, obj: str, relation: str) -> list:
        """
        Restate a curated LPSN hierarchy, name, publication or sequence link.

        API transport (or linked-record HTML fallback) is not the agent that
        originally asserted these source fields. Unlike GSS name matching, this
        layer does not infer cross-taxonomy associations (#1071).
        """
        headers = self.edge_header
        row = [""] * len(headers)
        for col, val in {
            "subject": f"{LPSN_PREFIX}{subject_record_no}",
            "predicate": predicate,
            "object": obj,
            "relation": relation,
            "primary_knowledge_source": LPSN_KNOWLEDGE_SOURCE,
            KNOWLEDGE_LEVEL_COLUMN: KNOWLEDGE_ASSERTION,
            AGENT_TYPE_COLUMN: MANUAL_AGENT,
        }.items():
            if col in headers:
                row[headers.index(col)] = val
        return row


# ``Dict`` kept in the imported set to satisfy the return-type hint on
# some Python versions that flag Dict as unused otherwise; kept explicit
# for readers.
_ = Dict
