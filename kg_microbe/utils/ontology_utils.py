"""Ontology utilities for category assignment and term processing."""

import fcntl
import gzip
import itertools
import os
import re
import shutil
import sqlite3
import subprocess
import threading
import time
import urllib.parse
import zlib
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
from typing import Dict, NamedTuple, Optional

from oaklib.interfaces import OboGraphInterface

from kg_microbe.transform_utils.constants import (
    BIOLOGICAL_PROCESS_CATEGORY,
    CELLULAR_COMPONENT_CATEGORY,
    EC_CATEGORY,
    EC_PREFIX,
    GENE_CATEGORY,
    GO_CATEGORY,
    GO_PREFIX,
    HGNC_NEW_PREFIX,
    MOLECULAR_ACTIVITY_CATEGORY,
    PROTEIN_CATEGORY,
    RHEA_CATEGORY,
    RHEA_NEW_PREFIX,
    ROLE_CATEGORY,
    SMALL_MOLECULE_CATEGORY,
    UNIPROT_PREFIX,
)

_GO_NAMESPACE_CACHE: Optional[Dict[str, str]] = None

# A healthy GO SemSQL DB is ~400 MB; anything below this is a truncated /
# 0-byte stub (the failure that miscategorized every GO term as
# biological_process this session).
_GO_DB_MIN_SIZE = 10_000_000

# Minimum plausible size for a healthy NCBITaxon SemSQL DB. A full build is
# ~13 GB; anything smaller is a partial extract/download or an interrupted
# `semsql make`, regardless of whether the SQLite header looks valid.
_NCBITAXON_DB_MIN_SIZE = 1_000_000_000  # 1 GB

# Minimum plausible size for a healthy ChEBI SemSQL DB. A full build is ~1-2 GB;
# the upstream distribution is ~800 MB compressed.
_CHEBI_DB_MIN_SIZE = 100_000_000  # 100 MB

# A complete ec.db is ~300 MB. The floor sits well below that but in the same
# proportion as the others (GO 10 MB/403 MB, ChEBI 100 MB/4.25 GB), so a
# half-written build is still caught.
_EC_DB_MIN_SIZE = 10_000_000  # 10 MB
# OBO release stamp, e.g. ``releases/2026-05-19/`` in a versionIRI.
_RELEASE_RE = re.compile(r"releases/(\d{4}-\d{2}-\d{2})")


def _obo_release_from_head(path: Path, nbytes: int = 2_000_000, *, prefer_archive: bool = False) -> Optional[str]:
    """
    Return the ``YYYY-MM-DD`` OBO release stamped near the top of an .owl/.json.

    Both OWL (``versionIRI rdf:resource=".../releases/DATE/..."``) and OBO-JSON
    (``meta`` versionInfo) carry the release near the file head, so a bounded
    read avoids parsing hundreds of MB. Returns None if unreadable / unstamped.

    ``prefer_archive`` is for downloaded sources only — see :func:`_read_head`.
    """
    head = _read_head(path, nbytes, prefer_archive=prefer_archive)
    if head is None:
        return None
    m = _RELEASE_RE.search(head)
    if m:
        return m.group(1)
    # OWL versionIRI whose date isn't under a ``releases/`` path — e.g. NCBITaxon's
    # ``versionIRI rdf:resource=".../ncbitaxon/2026-05-13/ncbitaxon.owl"``.
    m = re.search(r"versionIRI[^>]{0,160}?(\d{4}-\d{2}-\d{2})", head)
    if m:
        return m.group(1)
    # OBO-JSON versionInfo, e.g. {"pred": ".../versionInfo", "val": "2026-05-19"}
    # — allow the intervening `","val":` before the date (non-greedy, bounded).
    m = re.search(r"versionInfo.{0,40}?(\d{4}-\d{2}-\d{2})", head)
    return m.group(1) if m else None


def _derived_json_is_stale(owl_path: Path, json_path: Path) -> bool:
    """
    Return True when a derived OBO-JSON's release no longer matches its source OWL.

    Used by the ontologies transform to decide whether to re-run the ROBOT
    ``owl→json`` conversion: a single-source ontology (e.g. GO, whose go.json
    is derived from go.owl rather than downloaded) must regenerate the JSON
    when the OWL is refreshed to a new release. Conservative — only reports
    stale when *both* release stamps are readable and differ; an unstamped or
    unreadable pair yields False so unstamped ``.owl`` inputs keep the prior
    "convert only if missing" behavior.
    """
    # _read_head falls back to `<path>.gz`, so without this guard a *missing*
    # X.json beside a stray X.json.gz would read as stale and the caller would
    # unlink a path that does not exist.
    if not json_path.exists():
        return False
    # The OWL is downloaded, so its archive decides its release. The JSON is
    # *derived* — nothing refreshes a `<x>.json.gz`, so a stray leftover one must
    # never speak for the plain JSON the transform actually reads.
    owl_release = _obo_release_from_head(owl_path, prefer_archive=True)
    json_release = _obo_release_from_head(json_path)
    if not (owl_release and json_release):
        # ChEBI versions by integer, so neither date reader can answer and the
        # conservative "not stale" verdict applied to every ChEBI refresh.
        owl_release = _chebi_release_from_owl(owl_path, prefer_archive=True)
        json_release = _chebi_release_from_owl(json_path)
    return bool(owl_release and json_release and owl_release != json_release)


def _version_check_strict(env_var: str, strict: Optional[bool], default_strict: bool = True) -> bool:
    """
    Resolve a version-gate's strictness: explicit arg wins, else the env var.

    ``<env_var>`` may be ``strict`` (raise) or ``warn``; unset falls back to
    ``default_strict`` (which differs per gate — GO defaults strict because a
    mismatch silently corrupts categories, NCBITaxon defaults warn because
    owl/db release drift is common and low-risk).
    """
    if strict is not None:
        return strict
    val = os.environ.get(env_var, "").strip().lower()
    if val == "warn":
        return False
    if val == "strict":
        return True
    return default_strict


def assert_go_version_alignment(strict: Optional[bool] = None) -> None:
    """
    Guard that GO's derived ``go.json`` matches its single source ``go.owl``.

    Since fix 2 (#604) GO is single-source: ``go.owl`` is the only download, and
    ``go.json`` (transform output) and ``go.db`` (MF/BP/CC aspect map) are both
    derived from it — the transform regenerates a stale go.json and
    ``_ensure_go_db`` rebuilds a drifted go.db. This gate is the belt-and-braces
    check that the derived go.json actually tracks go.owl: a leftover pre-fix-2
    go.json, or a conversion that didn't re-run, would make MF/CC terms silently
    fall through to the ``biological_process`` default. Compare the two releases
    and, on mismatch, raise (``strict``) or warn loudly. No-op when either
    release stamp can't be read (e.g. a source is absent), so a missed versionIRI
    never false-alarms — only two readable-but-different stamps trip the gate.

    ``strict`` defaults to fail-loud (raise). Since the verdict rests on a
    release-stamp heuristic, ``KG_GO_VERSION_CHECK=warn`` downgrades to a
    warning — an escape hatch if the stamps ever disagree spuriously.
    """
    from kg_microbe.transform_utils.constants import GO_SOURCE

    strict = _version_check_strict("KG_GO_VERSION_CHECK", strict)
    if not GO_SOURCE:
        return
    json_path = Path(GO_SOURCE).with_suffix(".json")
    if not json_path.exists():
        # _read_head falls back to `<path>.gz`, so without this a *missing*
        # go.json beside a stray go.json.gz would read as stale — and this gate
        # defaults to strict, so it would abort over a file nothing reads (F8).
        return
    owl_release = _obo_release_from_head(Path(GO_SOURCE), prefer_archive=True)
    json_release = _obo_release_from_head(json_path)
    if owl_release and json_release and owl_release != json_release:
        msg = (
            f"GO source version mismatch: go.owl={owl_release} vs "
            f"go.json={json_release}. The aspect map (go.owl → go.db) will not "
            "match the terms in the transform output (go.json), silently "
            "miscategorizing MolecularActivity/CellularComponent GO terms as "
            "BiologicalProcess. Re-download GO so both are the same release "
            "(poetry run kg download), then rebuild go.db."
        )
        if strict:
            raise OntologyVersionMismatchError(msg)
        print(f"WARNING: {msg}")


def _read_only_connection(db_path: str) -> sqlite3.Connection:
    """
    Open a database strictly for reading, never creating it.

    A plain ``sqlite3.connect()`` creates the file when it is missing, so asking
    a *question* about a database had side effects: an absent path gained a 0-byte
    file, and a path that was a dangling symlink gained one at the link's target —
    which is exactly the 13 GB-in-the-wrong-place accident the build target
    clearing exists to prevent. Every release/identity reader goes through here so
    reading a database can never bring one into existence.

    The path is quoted because an unescaped ``?`` would start URI query
    parameters and ``#`` a fragment, silently opening a different file.

    :param db_path: Path to the database.
    :return: A read-only connection.
    """
    uri = f"file:{urllib.parse.quote(os.path.abspath(db_path))}?mode=ro"
    return sqlite3.connect(uri, uri=True)


def _ncbitaxon_db_release(db_path: str) -> Optional[str]:
    """
    Return the NCBITaxon release (YYYY-MM-DD) recorded in a SemSQL ``.db``.

    Reads ``owl:versionInfo`` from the ``statements`` table (OAK/SemanticSQL
    stores the ontology's version there). Returns None on any read error or a
    missing/unparsable stamp.
    """
    try:
        conn = _read_only_connection(db_path)
        try:
            # Target the ontology node's versionInfo (subject carries "ncbitaxon")
            # rather than any entity that happens to be annotated with one.
            row = conn.execute(
                "SELECT value FROM statements WHERE predicate = 'owl:versionInfo' "
                "AND subject LIKE '%ncbitaxon%' AND value IS NOT NULL LIMIT 1"
            ).fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        return None
    if not row or not row[0]:
        return None
    m = re.search(r"(\d{4}-\d{2}-\d{2})", str(row[0]))
    return m.group(1) if m else None


def _go_db_release(db_path: str) -> Optional[str]:
    """
    Return the GO release (YYYY-MM-DD) recorded in a SemSQL ``go.db``.

    SemSQL stamps the ontology node directly: ``obo:go.owl | owl:versionInfo |
    2026-05-19``. Match the GO ontology subject across the encodings different
    semsql/rdftab builds emit — the CURIE ``obo:go.owl`` / ``obo:go`` or the
    full IRI ``.../obo/go.owl`` — while still excluding GO *term* subjects
    (``GO:...``) that might carry a version-shaped value. Returns None on any
    read error / missing stamp; a None here makes ``_ensure_go_db`` conservatively
    reuse the existing db rather than force a spurious rebuild.
    """
    try:
        conn = _read_only_connection(db_path)
        try:
            row = conn.execute(
                "SELECT value FROM statements WHERE predicate = 'owl:versionInfo' "
                "AND value IS NOT NULL AND ("
                "subject IN ('obo:go.owl', 'obo:go') OR subject LIKE '%/go.owl'"
                ") LIMIT 1"
            ).fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        return None
    if not row or not row[0]:
        return None
    m = re.search(r"(\d{4}-\d{2}-\d{2})", str(row[0]))
    return m.group(1) if m else None


def assert_ncbitaxon_version_alignment(db_path: str, strict: Optional[bool] = None) -> None:
    """
    Guard that the NCBITaxon lookup DB matches the transform's OWL release.

    The metatraits transform looks taxa up in ``ncbitaxon.db`` (an OAK-fetched
    prebuilt SemSQL DB whose release is whatever OAK last downloaded) while its
    nodes are emitted from ``ncbitaxon.owl``. If the two are different releases,
    lookups can resolve against taxa that differ from those emitted. Compare the
    ``owl:versionInfo`` in ``db_path`` with ``ncbitaxon.owl``'s versionIRI and,
    on mismatch, warn (default) or raise. No-op when either stamp can't be read.

    Unlike the GO gate this **defaults to warn** — the OAK cache and the pinned
    ``ncbitaxon.owl`` legitimately drift (OAK auto-refreshes to the latest),
    and NCBITaxon labels/lineage are stable, so a mismatch is worth surfacing
    loudly but not aborting. Set ``KG_NCBITAXON_VERSION_CHECK=strict`` (or pass
    ``strict=True``) to fail loud instead.
    """
    from kg_microbe.transform_utils.constants import NCBITAXON_SOURCE

    strict = _version_check_strict("KG_NCBITAXON_VERSION_CHECK", strict, default_strict=False)
    if not NCBITAXON_SOURCE:
        return
    owl_release = _obo_release_from_head(Path(NCBITAXON_SOURCE), prefer_archive=True)
    db_release = _ncbitaxon_db_release(db_path)
    if owl_release and db_release and owl_release != db_release:
        msg = (
            f"NCBITaxon source version mismatch: ncbitaxon.owl={owl_release} vs "
            f"ncbitaxon.db={db_release}. The metatraits transform emits nodes from "
            "ncbitaxon.owl but looks taxa up in ncbitaxon.db; a release gap can "
            "resolve lookups against taxa the transform didn't emit. To realign, "
            "rebuild the DB from the OWL: rm data/raw/ncbitaxon.db and re-run, and "
            "the next transform rebuilds it via `semsql make`. Refreshing OAK's "
            "prebuilt cache instead does NOT close the gap — those builds lag the "
            "OBO release train by months. Do not delete ~/.data/oaklib/ncbitaxon.db "
            "while data/raw/ncbitaxon.db symlinks to it."
        )
        if strict:
            raise OntologyVersionMismatchError(msg)
        print(f"WARNING: {msg}")


def _semsql_build_enabled() -> bool:
    """
    Report whether SemSQL DB builds are permitted in this run.

    Building ``ncbitaxon.db`` (~13 GB, hours) or ``chebi.db`` (30+ minutes) is the
    right default for a maintainer refreshing the KG, but it is triggered by
    ordinary ``kg transform`` commands, so anyone else needs a way to decline
    (see #613). ``KG_SEMSQL_BUILD=off`` (or ``false``/``0``/``no``) skips the
    build and uses whatever DB is already on disk, with the version gate warning
    about any resulting drift.

    Note the opt-out only helps when a usable DB already exists — it declines to
    *build* one, it does not conjure one. With no DB present, ChEBI category
    lookups still fail; supply a prebuilt ``chebi.db`` in that case.

    :return: False when the opt-out is set, True otherwise.
    """
    return os.environ.get("KG_SEMSQL_BUILD", "").strip().lower() not in {"off", "false", "0", "no"}


def _usable_db(db_path: str, min_size: int, *, ontology: Optional[str] = None, require_content: bool = True) -> bool:
    """
    Report whether a SemSQL DB at ``db_path`` is present and plausibly complete.

    For the **post-build** check only: a symlink here means ``semsql`` followed a
    stale link and the result landed somewhere else, so it is rejected. Use
    :func:`_present_db` on the "could not build; use what's there" exits, where a
    symlink is a legitimate way to supply a prebuilt DB.

    Checked deeply. This runs once per build, after a job that took minutes to
    hours, so walking the pages is affordable — and this is the verdict that
    decides whether the previous DB may be discarded, so a shallow "looks fine"
    is not good enough. A build that exits 0 having written a file corrupt past
    the schema page used to be accepted, and the old DB deleted on the strength
    of it.

    :param db_path: Path to the DB.
    :param min_size: Smallest plausible size for a complete build.
    :return: True if the file is a usable, locally-built DB.
    """
    if os.path.islink(db_path):
        return False
    if ontology is not None and _db_is_for_ontology(db_path, ontology) is False:
        print(f"  {db_path} does not hold {ontology}; refusing to accept it as a build result")
        return False
    # Keep-states rather than == DB_OK: a build that finished correctly but was
    # opened by another process classifies BUSY, and rejecting it discarded the
    # new database and restored the stale one over it.
    if _classify_db(db_path, min_size, deep=True) not in _DB_KEEP_STATES:
        return False
    # ...and a valid SQLite file is not necessarily a usable ontology DB.
    # None means "could not establish" (locked); accept the build rather than
    # throw away work, but see _build_semsql_db, which then keeps the .prev
    # because nothing has verified the replacement.
    return _has_semsql_schema(db_path, require_content) is not False


def _restored_db_usable(
    db_path: str,
    min_size: int,
    kept: "KeptTarget",
    *,
    ontology: Optional[str] = None,
    require_content: bool = True,
) -> bool:
    """
    Judge the target after a failed build, according to what is now there.

    If something was displaced and put back, it is the caller's own artifact —
    possibly a symlink to a prebuilt DB, which is supported — so the symlink-
    tolerant check applies. If nothing was displaced, whatever sits at the target
    came from the failed build itself, and a symlink there means it landed
    elsewhere.

    Tolerant of symlinks, not of doubt: this verdict is returned as ``usable``
    from three build-failure exits, so it has to answer "may the caller use
    this?", which :func:`_servable_db` answers and :func:`_reusable_db`
    deliberately does not.

    :param db_path: Path to the DB.
    :param min_size: Smallest plausible size for a complete build.
    :param kept: What :func:`_clear_build_target` displaced.
    :return: True if the file is usable.
    """
    return (
        _servable_db(db_path, min_size, ontology, require_content=require_content)
        if kept
        else _usable_db(db_path, min_size, ontology=ontology, require_content=require_content)
    )


def _present_db(db_path: str, min_size: int) -> bool:
    """
    Report whether a DB is present and plausibly complete, symlinks included.

    Enforcing the size floor here is what stops a 0-byte or truncated
    ``chebi.db`` from being accepted: it passes a bare ``os.path.exists``, yields
    an adapter with no ``entailed_edge`` table, and makes every ChEBI term fall
    through to the default category — the same silent miscategorisation
    ``_GO_DB_MIN_SIZE`` was introduced to prevent.

    Symlinks are accepted because pointing at a prebuilt DB is supported —
    :func:`get_chebi_adapter`'s own error text suggests doing exactly that.

    A DB held open by another writer counts as present: locking is not damage,
    and classifying it as corrupt meant moving a live writer's database aside
    and rebuilding over it. See :func:`_classify_db` for why this returns a
    coarse boolean while deletion decisions consult the finer classification.

    :param db_path: Path to the DB.
    :param min_size: Smallest plausible size for a complete build.
    :return: True if the file is present and not damaged.
    """
    return _classify_db(db_path, min_size) in _DB_KEEP_STATES


# How a DB on disk classifies. Deliberately more than a boolean: a single
# "is it good?" verdict driving both *rebuild* and *delete* decisions is what
# made the .prev data-loss bug recur four times. A wrong rebuild answer costs
# time; a wrong delete answer costs a 13 GB database.
DB_ABSENT = "absent"
DB_TOO_SMALL = "too_small"
DB_BUSY = "busy"
DB_CORRUPT = "corrupt"
DB_OK = "ok"

# States that must never be destroyed. BUSY is in here deliberately: another
# process holding a write lock is not corruption, and treating it as such meant
# moving a live writer's database aside and rebuilding over it.
_DB_KEEP_STATES = (DB_OK, DB_BUSY)

# States that positively justify throwing a file away. BUSY is deliberately
# absent: a locked database cannot be verified, and "cannot verify" must never
# be treated as "worthless" — that mistake unlinked a live DB and discarded a
# healthy fresh build.
_DB_DISCARDABLE_STATES = (DB_ABSENT, DB_TOO_SMALL, DB_CORRUPT)

# Short, so a locked DB is classified as BUSY promptly rather than after
# SQLite's multi-second default busy wait.
_DB_PROBE_TIMEOUT_SECONDS = 0.5

# A momentary lock should not abort a transform, so the serve check retries.
_DB_PROBE_RETRIES = 3


def _classify_db(db_path: str, min_size: int, deep: bool = False) -> str:
    """
    Classify a DB on disk, distinguishing "locked" from "corrupt".

    The shallow probe reads the schema page: enough to catch a truncated or
    non-SQLite file, cheap enough to run on every resolve (microseconds even on
    the 13 GB ncbitaxon.db). It cannot catch corruption in deeper pages, and
    that is an accepted limit — because this verdict no longer authorises
    deleting anything. A false "ok" now means a bad DB is reused, which is
    recoverable; it can no longer mean a good copy is destroyed.

    ``deep=True`` additionally runs ``PRAGMA quick_check(1)``, which does walk
    the pages. Reserved for the one decision where being wrong costs data — see
    :func:`_clear_build_target` — and for validating a finished build. Never on
    the hot path.

    :param db_path: Path to the DB.
    :param min_size: Smallest plausible size for a complete build.
    :param deep: Whether to also walk pages via ``quick_check``.
    :return: One of the ``DB_*`` constants.
    """
    if not os.path.exists(db_path):
        return DB_ABSENT
    try:
        if os.path.getsize(db_path) < min_size:
            return DB_TOO_SMALL
    except OSError:
        return DB_ABSENT
    try:
        # quote() the path: an unescaped "?" would start URI query parameters
        # and "#" a fragment, so SQLite would silently open a *different*
        # file than the one being checked.
        uri = f"file:{urllib.parse.quote(os.path.abspath(db_path))}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=_DB_PROBE_TIMEOUT_SECONDS)
        try:
            # Reads the schema page, not just the 100-byte header.
            conn.execute("SELECT name FROM sqlite_master LIMIT 1").fetchone()
            if deep:
                row = conn.execute("PRAGMA quick_check(1)").fetchone()
                if row and str(row[0]).lower() != "ok":
                    return DB_CORRUPT
        finally:
            conn.close()
    except sqlite3.OperationalError as e:
        # "database is locked" / "database table is locked" — a live writer, not
        # damage. Anything else from OperationalError is a genuine open failure.
        return DB_BUSY if "locked" in str(e).lower() or "busy" in str(e).lower() else DB_CORRUPT
    except (sqlite3.Error, OSError):
        return DB_CORRUPT
    return DB_OK


# Structural probes: the objects and the exact columns our queries select.
# `SELECT *` was not enough — a table declared `statements(predicate)` alone
# compiled fine while every consumer query failed with `no such column`. Naming
# the columns is what makes the probe mean anything. LIMIT 0 parses without
# scanning, so these stay in the low milliseconds even on the 14 GB DB.
# What our consumers actually read, captured by observation rather than
# recollection: SQLite's authorizer callback was attached while running every
# OAK operation this codebase performs (labels, ancestors, descendants,
# relationships, entity_metadata_map, basic_search) plus our own GO namespace
# query, and it recorded each table and column touched.
#
# Three earlier mechanisms failed. Enumerating objects from memory was found
# incomplete in four consecutive reviews — most damagingly node_to_value_statement,
# whose absence filed every molecular-function GO term as BiologicalProcess.
# Snapshotting all 100 objects of a real build fixed completeness but was
# version-brittle (a renamed diagnostic view nothing uses would reject every
# build, forever) and still shape-blind: owl_has_value with the wrong columns
# passed, then failed at runtime.
#
# Probing exactly what is read, with the columns, is both complete and tolerant:
# a semsql release may add or rename anything we do not use.
#
# The first trace missed the NER path: ner_utils.annotate falls back to
# annotate_text(matches_whole_text=False) when a term has no whole-text match,
# and that lazy branch builds a lexical index reading `node`, `deprecated_node`
# and five synonym views. None appeared until the fallback was actually
# exercised — a reminder that this method is only as complete as the operations
# the trace runs.
#
# Regenerate by attaching an authorizer to sqlite3.dbapi2.connect and running
# every consumer operation, including both annotate_text configurations, against
# a real DB. It takes a couple of minutes because annotation builds an index.
_STATEMENT_COLUMNS = (
    "stanza",
    "subject",
    "predicate",
    "object",
    "value",
    "datatype",
    "language",
    "graph",
)

_SEMSQL_CAPABILITY_CONTRACT = {
    "class_node": ("id",),
    "deprecated_node": ("id",),
    "edge": ("subject", "predicate", "object"),
    "entailed_edge": ("subject", "predicate", "object"),
    "has_broad_synonym_statement": _STATEMENT_COLUMNS,
    "has_exact_synonym_statement": _STATEMENT_COLUMNS,
    "has_narrow_synonym_statement": _STATEMENT_COLUMNS,
    "has_related_synonym_statement": _STATEMENT_COLUMNS,
    "has_synonym_statement": ("subject", "predicate", "object", "value", "datatype", "language"),
    "node": ("id",),
    "object_property_node": ("id",),
    "owl_has_value": ("id", "on_property", "filler"),
    "owl_some_values_from": ("id", "on_property", "filler"),
    "owl_subclass_of_some_values_from": ("subject", "predicate", "object"),
    "prefix": ("prefix", "base"),
    "rdf_type_statement": ("subject", "predicate", "object"),
    "rdfs_label_statement": ("subject", "predicate", "object", "value", "datatype", "language"),
    "rdfs_subclass_of_named_statement": ("subject", "predicate", "object"),
    "rdfs_subclass_of_statement": _STATEMENT_COLUMNS,
    "rdfs_subproperty_of_statement": ("subject", "predicate", "object"),
    "statements": _STATEMENT_COLUMNS,
    # Read by _load_go_namespace_map, which is our SQL rather than OAK's.
    "node_to_value_statement": ("subject", "predicate", "value"),
}

_SEMSQL_CAPABILITY_PROBES = tuple(
    # noqa justified: table and column names come from the literal above, never
    # from input. LIMIT 0 compiles the statement without reading any rows.
    f"SELECT {', '.join(columns)} FROM {table} LIMIT 0"  # noqa: S608
    for table, columns in sorted(_SEMSQL_CAPABILITY_CONTRACT.items())
)

# Content probes: indexed lookups establishing the DB actually holds data.
# Deliberately NOT universal. Requiring a row is right for the hierarchical,
# labelled ontologies this pipeline ships, but as a general invariant it would
# reject a legitimately flat or property-only source on every run, restore the
# previous copy, and rebuild again forever. Wrongly rejecting a good build costs
# an endless loop; wrongly accepting one costs a database — so content is
# demanded only where it is known to apply.
_SEMSQL_CONTENT_PROBES = (
    "SELECT 1 FROM statements WHERE predicate = 'rdfs:label' LIMIT 1",
    "SELECT 1 FROM entailed_edge LIMIT 1",
)

# Content policy is passed explicitly by each _ensure_*_db rather than inferred
# from a display label. Deriving it from `label` failed open: "ChEBI" enabled
# content validation and "ChEBI ontology" silently disabled it, so a typo would
# have quietly weakened the check rather than breaking anything visibly.


# The subject each ontology's own release row uses. An exact match on an indexed
# column, so this costs microseconds where a LIKE scan for term prefixes costs
# 1.6 s on ncbitaxon.db. Note EC's is `eccode`, not `ec`.
_ONTOLOGY_IDENTITY_SUBJECT = {
    "ncbitaxon": "obo:ncbitaxon.owl",
    "chebi": "obo:chebi.owl",
    "go": "obo:go.owl",
    "ec": "obo:eccode.owl",
}


def _db_is_for_ontology(db_path: str, ontology: str) -> Optional[bool]:
    """
    Report whether a DB actually contains the ontology we asked for.

    Everything else about a SemSQL database is generic: schema, columns, size and
    content look identical whichever ontology built it. So `ncbitaxon.db` pointing
    at a copy of `chebi.db` passed every check — schema, content, size, and
    metatraits' own validation — while taxon lookups silently returned nothing and
    the transform accumulated unresolved taxa.

    :param db_path: Path to the DB.
    :param ontology: Ontology key it is supposed to hold.
    :return: True if the ontology's own release row is present, False if it is
        demonstrably absent, None when the answer cannot be established.
    """
    subject = _ONTOLOGY_IDENTITY_SUBJECT.get(ontology)
    if subject is None:
        return None
    try:
        uri = f"file:{urllib.parse.quote(os.path.abspath(db_path))}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=_DB_PROBE_TIMEOUT_SECONDS)
        try:
            row = conn.execute("SELECT 1 FROM statements WHERE subject = ? LIMIT 1", (subject,)).fetchone()
        finally:
            conn.close()
    except sqlite3.OperationalError as e:
        return _probe_verdict(db_path, f"identity of {ontology}", e)
    except (sqlite3.Error, OSError):
        return False
    if row is None:
        print(f"  {db_path} does not contain {ontology} (no `{subject}` row)")
        return False
    return True


def _is_transient_db_error(error: BaseException) -> bool:
    """
    Report whether a database error means "ask again later" rather than "bad".

    Lock contention is the normal condition on a shared filesystem — an HPC array
    runs several transforms against the same ontology databases — and it says
    nothing about the database's contents. Distinguishing it matters wherever a
    failure is *cached*: latching a permanent verdict on a momentary lock turns a
    healthy database into an unusable one for the rest of the process.

    :param error: The exception raised by a probe or query.
    :return: True if retrying could plausibly succeed.
    """
    message = str(error).lower()
    return "locked" in message or "busy" in message


def _probe_verdict(db_path: str, sql: Optional[str], error: Exception) -> Optional[bool]:
    """
    Decide what a probe failure proves about a database, and say so.

    Only a missing table or column is evidence that a database cannot serve our
    queries. A lock means "ask later" and is handled by the caller; anything else
    — a disk error, a permission problem — means the probe established nothing.
    Reporting False for those would send a healthy multi-gigabyte database off to
    be rebuilt.

    One classifier, used at every site that can see an ``OperationalError``. The
    first version was applied to the structural probe loop alone, so the same
    disk error was read as "schema is bad" during content probing and during
    ``connect()``, but as "cannot tell" during structural probing.

    :param db_path: Database being probed, for the message.
    :param sql: The probe that failed, or None when the failure was in connect().
    :param error: The exception raised.
    :return: False when the schema is demonstrably wrong, None when nothing was
        established.
    """
    message = str(error).lower()
    definitive = "no such table" in message or "no such column" in message
    where = f"`{sql}`" if sql else "connect()"
    if definitive:
        print(f"  {db_path} cannot serve {where}: {error}")
        return False
    print(f"  Could not probe {db_path} ({where}): {error}")
    return None


def _has_semsql_schema(db_path: str, require_content: bool = True) -> Optional[bool]:
    """
    Report whether a DB can answer the queries this codebase makes.

    Structure is checked against the complete object set a real ``semsql make``
    produces, plus the columns our consumers select. Content — a label row and a
    hierarchy row — is checked only when the caller says the source should have
    some, because demanding it universally would reject a legitimately flat or
    property-only ontology on every run and rebuild it forever.

    :param db_path: Path to the DB.
    :param require_content: Whether to also require label and hierarchy rows.
    :return: True if every check passes, False if one demonstrably fails, and
        None when the answer cannot be established — a locked DB, say — so
        callers can decline to act on an unknown.
    """
    try:
        uri = f"file:{urllib.parse.quote(os.path.abspath(db_path))}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=_DB_PROBE_TIMEOUT_SECONDS)
        try:
            for sql in _SEMSQL_CAPABILITY_PROBES:
                try:
                    conn.execute(sql).fetchall()
                except sqlite3.OperationalError as probe_error:
                    return _probe_verdict(db_path, sql, probe_error)
            if require_content:
                for sql in _SEMSQL_CONTENT_PROBES:
                    try:
                        if conn.execute(sql).fetchone() is None:
                            return False
                    except sqlite3.OperationalError as probe_error:
                        return _probe_verdict(db_path, sql, probe_error)
        finally:
            conn.close()
    except sqlite3.OperationalError as e:
        # Reached for connect() failures and anything re-raised above. Classified
        # the same way: applying the rule to only one of the three sites meant an
        # identical disk error was read as "schema is bad" or "cannot tell"
        # depending on which probe happened to hit it.
        return _probe_verdict(db_path, None, e)
    except (sqlite3.DatabaseError, OSError):
        # A corrupt or unreadable file is evidence about the database itself.
        return False
    except sqlite3.Error:
        # Anything else establishes nothing.
        return None
    return True


def _servable_db(db_path: str, min_size: int, ontology: Optional[str], *, require_content: bool = True) -> bool:
    """
    Report whether queries may be run against this DB.

    Stricter than :func:`_reusable_db`, and deliberately so. "Do not destroy
    this" and "answer questions from this" are different decisions, and treating
    an unverifiable answer as usable conflated them: a locked go.db probed as
    None, was reported usable, and every per-term query then failed inside
    bakta's broad handler, defaulting biological-process terms to
    molecular_function. Declining to rebuild was right; authorising queries was
    not.

    A brief lock is retried rather than treated as fatal, since another process
    holding the DB for a moment should not abort a multi-hour transform.

    :param db_path: Path to the DB.
    :param min_size: Smallest plausible size for a complete build.
    :param ontology: Ontology the DB is supposed to hold.
    :param require_content: Whether label and hierarchy rows are required.
    :return: True only if the DB is positively verified as usable.
    """
    if not _present_db(db_path, min_size):
        return False
    for attempt in range(_DB_PROBE_RETRIES):
        verdict = _has_semsql_schema(db_path, require_content)
        if verdict is not None:
            break
        if attempt + 1 < _DB_PROBE_RETRIES:
            time.sleep(_DB_PROBE_TIMEOUT_SECONDS)
    if verdict is not True:
        return False
    # Retried and *required*, symmetrically with the schema probe above. Accepting
    # an indeterminate verdict here contradicted this function's contract: a
    # database that could not be shown to hold the right ontology was authorised
    # for queries, which is the case where every lookup returns nothing and the
    # per-item handlers quietly supply defaults. Declining to rebuild on an
    # unverifiable answer stays correct — that is `_reusable_db`'s job, and it
    # still accepts None.
    if ontology is None:
        # No ontology named, so there is no identity to confirm. None of the four
        # ensure paths reach here — they all name one — but the build helpers
        # carry it as Optional, and answering False would refuse every database
        # rather than skip a check that does not apply.
        return True
    for attempt in range(_DB_PROBE_RETRIES):
        identity = _db_is_for_ontology(db_path, ontology)
        if identity is not None:
            return identity
        if attempt + 1 < _DB_PROBE_RETRIES:
            time.sleep(_DB_PROBE_TIMEOUT_SECONDS)
    print(f"  Refusing to serve {db_path}: could not confirm it holds {ontology}")
    return False


def _reusable_db(db_path: str, min_size: int, *, ontology: Optional[str] = None, require_content: bool = True) -> bool:
    """
    Report whether a DB is worth *keeping*.

    Present, intact, and not demonstrably unable to answer our queries. This is
    the preservation predicate: it decides whether an existing database or a
    ``.prev`` may be discarded, where an unverifiable answer must mean "keep it" —
    a wrong answer here costs a 13 GB database.

    A schema answer of None (locked, unverifiable) therefore counts as
    acceptable. That is exactly why this must **not** answer "may the caller use
    it?": every exit reporting usability once returned this predicate, so a
    locked database that :func:`_servable_db` had just rejected was reported
    usable one line later and handed to OAK, and the per-item handlers then
    supplied a default category for every term. Serving goes through
    :func:`_servable_db`; keeping comes here.

    :param db_path: Path to the DB.
    :param min_size: Smallest plausible size for a complete build.
    :return: True if the DB may be reported usable.
    """
    if not _present_db(db_path, min_size):
        return False
    if _has_semsql_schema(db_path, require_content) is False:
        return False
    # Identity belongs here, not only on the serving path. Ranking, fallback,
    # opt-out and restore all decide whether a file is worth keeping or handing
    # back, and a database holding the wrong ontology is worth neither — it once
    # displaced the only correct .prev and was then served in its place.
    return ontology is None or _db_is_for_ontology(db_path, ontology) is not False


def _db_is_readable(db_path: str) -> bool:
    """
    Report whether SQLite can open a DB, treating a locked one as readable.

    :param db_path: Path to the DB.
    :return: True unless the file is missing or damaged.
    """
    return _classify_db(db_path, 0) in _DB_KEEP_STATES


def _read_head(path: Path, nbytes: int, *, prefer_archive: bool = False) -> Optional[str]:
    """
    Read the head of ``path``, transparently falling back to ``path`` + ``.gz``.

    Release stamps live in the first few KB, and the downloads ship compressed
    (``chebi.owl.gz``, ``ncbitaxon.owl.gz``) while the ``*_SOURCE`` constants name
    the uncompressed path. Without this fallback the release reads return None on
    a fresh checkout, which makes both the drift check and the version gate
    silently no-op — leaving an old DB in place, the exact drift this module
    exists to catch.

    ``prefer_archive`` is a statement about *provenance*, so it is per-call rather
    than global. It belongs to downloaded OWL sources, where ``kg download``
    refreshes ``<x>.gz`` and leaves any previously decompressed ``<x>`` alone, so
    the archive is the artifact of record. Making that the blanket rule here broke
    the two callers for which it is wrong: the comparator whose entire job is to
    tell the two forms apart read the archive for *both* operands and so could
    never see a difference, and the derived-JSON staleness check let a stray
    leftover ``go.json.gz`` vouch for a stale ``go.json`` that the transform was
    actually reading.

    :param path: Path to read; a ``.gz`` name is read as an archive directly.
    :param nbytes: How many characters to read.
    :param prefer_archive: Read ``<path>.gz`` first when both forms exist.
    :return: The head as text, or None if neither form is readable.
    """
    if path.name.endswith(".gz"):
        # An archive named outright. Callers comparing the two forms pass the
        # archive path itself, and text-opening gzip bytes yields mojibake in
        # which no stamp matches — a silent "no difference".
        candidates = ((gzip.open, path),)
    else:
        archive = path.with_name(path.name + ".gz")
        candidates = (
            ((gzip.open, archive), (open, path))
            if prefer_archive and archive.exists()
            else ((open, path), (gzip.open, archive))
        )
    for opener, target in candidates:
        if not target.exists():
            continue
        try:
            with opener(target, "rt", encoding="utf-8", errors="ignore") as fh:
                return fh.read(nbytes)
        except (OSError, EOFError, zlib.error):
            return None
    return None


class FatalOntologyError(BaseException):

    """
    An ontology is unusable and no per-item fallback is honest.

    Deliberately **not** an ``Exception``. Adapters resolve lazily, so the first
    attribute access — and therefore the failure — lands wherever the transform
    happens to touch the adapter first, which is almost always inside a ``try``
    whose ``except Exception`` was written to absorb a per-item lookup miss. A
    missing DB is not a lookup miss: swallowing it means every ChEBI node gets
    the default category, every GO term becomes molecular_function, every label
    becomes a bare numeric ID, and the run exits 0 with a systematically wrong
    graph. Those handlers are individually reasonable, and patching each one was
    tried — it regressed three times, because the next broad handler someone
    writes re-opens the hole.

    Inheriting ``BaseException`` makes that structural instead of a convention:
    no ``except Exception``, here or in oaklib/pandas, can turn a fatal ontology
    failure into wrong data. ``finally`` blocks still run, so cleanup is intact.

    One constraint this imposes: a ``BaseException`` raised inside a
    ``multiprocessing.Pool`` worker is not caught by the worker loop and can hang
    the pool. The metatraits pool resolves NCBITaxon eagerly in the parent
    (``_ensure_ncbitaxon_db_ready``) through its own module-local adapter, so no
    worker ever resolves one of these proxies — keep it that way.
    """


class OntologyDbUnavailableError(FatalOntologyError):

    """
    No usable SemSQL DB could be produced for an ontology.

    Distinct from :class:`OntologyVersionMismatchError` so callers can degrade on
    "no DB at all" without also swallowing a deliberate ``*_VERSION_CHECK=strict``
    abort — ``get_chebi_category`` relies on exactly that distinction.
    """


class OntologyVersionMismatchError(FatalOntologyError):

    """
    A DB and the OWL it must track are stamped with different releases.

    Raised only by the ``assert_*_version_alignment`` gates under ``strict``. The
    whole point is to abort rather than emit a graph built from two releases, so
    this must not be catchable as ``Exception``: under the old plain
    ``RuntimeError`` a strict ChEBI abort was swallowed per-row by
    ``get_chebi_category`` and a strict GO abort by ``oak_utils.get_label``.
    """


# Historical name; the ChEBI path is the one with existing callers.
ChebiDbUnavailableError = OntologyDbUnavailableError


class KeptTarget(NamedTuple):

    """
    What :func:`_clear_build_target` displaced, so it can be put back.

    A real file is moved aside to ``<db>.prev``; a symlink is recorded by its
    target and recreated on restore. Recording the link matters: pointing at a
    prebuilt DB with a symlink is a supported way to supply one, and a failed
    build used to delete it irrecoverably while telling the user to supply a
    prebuilt DB (F1).
    """

    prev_path: Optional[str] = None
    link_target: Optional[str] = None

    def __bool__(self) -> bool:
        """Report whether something was displaced and can be restored."""
        return bool(self.prev_path or self.link_target)


class DbEnsureResult(NamedTuple):

    """
    Outcome of an ``_ensure_*_db`` call.

    ``usable`` keeps the historical truthiness (callers write
    ``if _ensure_chebi_db(...)``), while ``built`` says whether *this call*
    produced a new DB. Callers need that distinction and cannot infer it: a
    restored ``.prev`` or an adopted orphan also makes a file appear where there
    was none, which is what made an earlier fingerprint-based guess misreport a
    restore as a fresh build (F2).
    """

    usable: bool
    built: bool = False

    def __bool__(self) -> bool:
        """Report whether a usable DB is at the target path."""
        return self.usable


def _note_orphaned_prev(db_path: str) -> None:
    """
    Mention a leftover ``<db>.prev`` so it cannot sit unnoticed.

    When the DB at the target is reused, ``_clear_build_target`` never runs, so a
    ``.prev`` left by an interrupted build is never consulted — for NCBITaxon
    that is 14 GB sitting unreferenced. We cannot tell a complete DB from a
    partial one that clears the size floor, so this reports rather than acts.

    :param db_path: The DB path whose sibling to check.
    """
    kept = f"{db_path}.prev"
    if os.path.lexists(kept):
        size = os.path.getsize(kept) if os.path.exists(kept) else 0
        print(
            f"  Note: {kept} ({size / 1e9:.1f} GB) is left over from an interrupted "
            "build. Delete it if the current DB is good."
        )


def _clear_build_target(
    db_path: str, min_size: int, *, ontology: Optional[str] = None, require_content: bool = True
) -> KeptTarget:
    """
    Clear the SemSQL build target, preserving whatever it displaced.

    ``os.path.exists`` follows symlinks and is False for a dangling one, so a
    stale link would survive and ``semsql make`` — which opens the target name for
    writing — would follow it and deposit the multi-GB result at the link's
    target instead, with the closing size check following the link too and
    reporting success.

    A real file is moved aside to ``<db>.prev`` and a symlink's target is
    recorded, so a build that fails can restore either. The governing rule when
    both a target and a ``.prev`` exist is **never trade a usable copy for an
    unusable one**: a build killed part-way leaves a partial file at the target,
    and blindly moving it aside used to overwrite — and destroy — the good
    multi-GB DB sitting in ``.prev`` (#634).

    Peak disk during a rebuild is old + new, plus the decompressed OWL
    (~2 GB for NCBITaxon) and the relation-graph intermediate.

    :param db_path: Build target to clear.
    :param min_size: Smallest plausible size for a complete DB, used to decide
        which of the target and ``.prev`` is worth keeping.
    :return: What was displaced, for :func:`_restore_build_target`.
    """
    kept = f"{db_path}.prev"
    # Ranking uses the same "can this answer our queries" test as every other
    # decision. Integrity alone ranked a physically valid but schema-less target
    # equal to a SemSQL-valid .prev, so an interrupted build's leftovers could
    # displace the good copy and a subsequent failure would restore the wrong
    # one. Ranking decides what is destroyed, so it is the last place that
    # should use a weaker test than the rest.
    prev_usable = os.path.lexists(kept) and _reusable_db(
        kept, min_size, ontology=ontology, require_content=require_content
    )
    target_is_link = os.path.islink(db_path)
    target_present = os.path.lexists(db_path)
    # Symlinks are ranked on what they resolve to, not dismissed for being links.
    # Excluding them made a *current* prebuilt symlink lose to any usable .prev,
    # however old: the link was detached, the stale .prev became canonical, and a
    # failed build then restored that older ontology and reported it usable —
    # which NCBITaxon's and ChEBI's warn-level gates let the transform run
    # against. A dangling link still ranks as unusable, since it resolves to
    # nothing, so the recovery below still clears it.
    target_usable = target_present and _reusable_db(
        db_path, min_size, ontology=ontology, require_content=require_content
    )

    recovered_link: Optional[str] = None

    if prev_usable and not target_usable:
        # The .prev is the good copy: the target is absent, a symlink, or the
        # partial remains of a killed build. Recover rather than overwrite.
        if target_is_link:
            recovered_link = os.readlink(db_path)
            os.remove(db_path)
            print(f"  Recovering {kept} left by an interrupted build (was symlinked to {recovered_link})")
        elif target_present:
            print(f"  Discarding the partial {db_path} and recovering {kept}")
            os.remove(db_path)
        else:
            print(f"  Recovering {kept} left by an interrupted build")
        os.replace(kept, db_path)
        # Fall through so the recovered DB is moved aside for this build. The
        # symlink case used to `return` here, leaving the recovered DB sitting at
        # the build target for `semsql make` to overwrite — and since the result
        # recorded only the link, a failed build restored the dangling symlink
        # and the good copy was gone. That is #634 for the third time: the rule
        # is never trade a usable copy for an unusable one, on *every* branch.

    if os.path.islink(db_path):
        target = os.readlink(db_path)
        os.remove(db_path)
        return KeptTarget(link_target=target)
    if not os.path.lexists(db_path):
        if prev_usable:
            # An unreferenced but usable .prev with nothing at the target: say so
            # rather than leaving 13 GB silently stranded through a build that
            # will never look at it.
            _note_orphaned_prev(db_path)
        return KeptTarget(link_target=recovered_link)
    if os.path.lexists(kept):
        # About to overwrite the .prev with the target. This is the one decision
        # where being wrong destroys data, so it is the one place that pays for a
        # deep check: the shallow probe reads only the schema page, and a target
        # corrupt in deeper pages would otherwise pass as "at least as good" and
        # take the good .prev's place (round-3 finding 1).
        # Only a *positively bad* verdict may discard the target. Comparing
        # `!= DB_OK` treated BUSY as bad, so a database another process had open
        # was unlinked — reintroducing, at the deep check, exactly the data loss
        # the shallow path was restructured to prevent. "Cannot verify" is not
        # "worthless".
        if prev_usable and _classify_db(db_path, min_size, deep=True) in _DB_DISCARDABLE_STATES:
            print(
                f"  Keeping {kept}: it is usable and {db_path} did not pass a deep check. "
                "Discarding the target instead of trading a good copy for a doubtful one."
            )
            os.remove(db_path)
            # prev_path is still reported: the good copy lives at .prev, so a
            # failed build must move it back to the target, and a successful one
            # may discard it.
            return KeptTarget(prev_path=kept, link_target=recovered_link)
        os.remove(kept)
    os.replace(db_path, kept)
    return KeptTarget(prev_path=kept, link_target=recovered_link)


def _restore_build_target(db_path: str, kept: KeptTarget) -> None:
    """
    Put back whatever :func:`_clear_build_target` displaced, after a failed build.

    :param db_path: Original DB path.
    :param kept: Value returned by :func:`_clear_build_target`.
    """
    if kept.prev_path and os.path.lexists(kept.prev_path):
        os.replace(kept.prev_path, db_path)
        print(f"  Restored the previous {db_path} after the failed build")
    elif kept.link_target:
        if os.path.lexists(db_path):
            os.remove(db_path)
        os.symlink(kept.link_target, db_path)
        print(f"  Restored the {db_path} -> {kept.link_target} symlink after the failed build")


def _discard_kept_target(kept: KeptTarget) -> None:
    """
    Delete the moved-aside DB once a build has succeeded.

    :param kept: Value returned by :func:`_clear_build_target`.
    """
    if kept.prev_path and os.path.lexists(kept.prev_path):
        os.remove(kept.prev_path)


def _archive_release_differs(owl_source: Path) -> bool:
    """
    Report whether ``<owl>.gz`` holds a different release than the plain ``<owl>``.

    `kg download` refreshes the archive, not the decompressed copy, so a stale
    plain OWL beside a newly downloaded one defeated the entire single-source
    guarantee: _read_head prefers the plain file, the DB was declared aligned
    against the old release, and the decompression step refused to run because a
    plain file already existed. The refresh was therefore invisible.

    :param owl_source: Path to the plain OWL.
    :return: True when both forms exist and their release stamps differ.
    """
    archive = owl_source.with_name(owl_source.name + ".gz")
    if not (archive.exists() and owl_source.exists()):
        return False
    plain_head = None
    try:
        with open(owl_source, "rt", encoding="utf-8", errors="ignore") as handle:
            plain_head = handle.read(2_000_000)
    except OSError:
        return False
    try:
        with gzip.open(archive, "rt", encoding="utf-8", errors="ignore") as handle:
            archive_head = handle.read(2_000_000)
    except (OSError, EOFError, zlib.error):
        return False
    plain = _RELEASE_RE.search(plain_head) or re.search(r"versionIRI[^>]{0,160}?(\d{4}-\d{2}-\d{2})", plain_head)
    packed = _RELEASE_RE.search(archive_head) or re.search(r"versionIRI[^>]{0,160}?(\d{4}-\d{2}-\d{2})", archive_head)
    if not (plain and packed):
        # ChEBI versions by integer rather than date; fall back to that reader.
        # Both operands are read from the exact path named: with the archive
        # preferred, both calls resolved to the archive and every ChEBI refresh
        # compared identical to itself, so the build kept running from the stale
        # plain OWL and repeated its 30-minute rebuild on every invocation.
        plain_value = _chebi_release_from_owl(owl_source)
        packed_value = _chebi_release_from_owl(archive)
        return bool(plain_value and packed_value and plain_value != packed_value)
    return plain.group(1) != packed.group(1)


def _decompress_atomically(archive: Path, destination: Path) -> bool:
    """
    Decompress a ``.gz`` archive to ``destination`` via a temp file + rename.

    Writing straight to the destination leaves a truncated file at the real
    filename if interrupted (#615) — and a truncated OWL is not detectable
    downstream, because the version stamp lives in the head and still parses.

    :param archive: Source ``.gz`` file.
    :param destination: Path to place the decompressed file at.
    :return: True if destination now holds the complete contents.
    """
    # Per-writer, like atomic_write. A shared "<name>.partial" is not atomic
    # across processes: B opens and truncates the same inode A is filling, A then
    # completes from its advanced offset and publishes a file with a zero-filled
    # gap, and semsql may start reading it.
    tmp = destination.with_name(f"{destination.name}.{os.getpid()}.{next(_DECOMPRESS_COUNTER)}.partial")
    try:
        with gzip.open(archive, "rb") as src, open(tmp, "wb") as dst:
            shutil.copyfileobj(src, dst)
        os.replace(tmp, destination)
    # A truncated archive raises EOFError and a corrupt one zlib.error, neither of
    # which is an OSError — catching OSError alone let those escape, defeating the
    # "degrades gracefully" contract and orphaning a multi-GB .partial.
    except (OSError, EOFError, zlib.error) as e:
        print(f"Warning: failed to decompress {archive}: {e}")
        tmp.unlink(missing_ok=True)
        return False
    return True


def _chebi_release_from_owl(path: Path, nbytes: int = 2_000_000, *, prefer_archive: bool = False) -> Optional[str]:
    """
    Return the ChEBI release recorded near the top of ``chebi.owl``.

    ChEBI does not use OBO's ``YYYY-MM-DD`` stamp — it versions by an
    incrementing integer (``versionIRI .../obo/chebi/253/chebi.owl``,
    ``<owl:versionInfo>253</owl:versionInfo>``). :func:`_obo_release_from_head`
    only recognises dates, so it silently returns None for ChEBI and any gate
    built on it no-ops. Hence this separate reader.

    :param path: Path to ``chebi.owl``.
    :param nbytes: Bytes to read from the head (ChEBI OWL is ~1 GB uncompressed).
    :param prefer_archive: Read ``<path>.gz`` first — downloaded sources only.
    :return: Release as a string (e.g. ``"253"``), or None if unreadable/unstamped.
    """
    head = _read_head(path, nbytes, prefer_archive=prefer_archive)
    if head is None:
        return None
    m = re.search(r"versionIRI[^>]{0,160}?/chebi/(\d+)/", head)
    if m:
        return m.group(1)
    m = re.search(r"<owl:versionInfo>\s*(\d+)\s*</owl:versionInfo>", head)
    if m:
        return m.group(1)
    # ROBOT's OBO-JSON records the release as a bare `"version"` IRI with no
    # `versionIRI` key, so the patterns above return None for chebi.json — which
    # made every ChEBI staleness comparison unanswerable and therefore "fresh".
    m = re.search(r"/chebi/(\d+)/chebi\.owl", head)
    return m.group(1) if m else None


def _chebi_db_release(db_path: str) -> Optional[str]:
    """
    Return the ChEBI release recorded in a SemSQL ``chebi.db``.

    Mirrors :func:`_go_db_release` but accepts ChEBI's bare integer stamp
    instead of a date. Restricted to the ontology subject so a version-shaped
    value on a ``CHEBI:...`` term subject can't be mistaken for the release.

    :param db_path: Path to ``chebi.db``.
    :return: Release as a string, or None on read error / missing stamp.
    """
    try:
        conn = _read_only_connection(db_path)
        try:
            row = conn.execute(
                "SELECT value FROM statements WHERE predicate = 'owl:versionInfo' "
                "AND value IS NOT NULL AND ("
                "subject IN ('obo:chebi.owl', 'obo:chebi') OR subject LIKE '%/chebi.owl'"
                ") LIMIT 1"
            ).fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        return None
    if not row or not row[0]:
        return None
    m = re.search(r"(\d+)", str(row[0]))
    return m.group(1) if m else None


def assert_chebi_version_alignment(db_path: str, strict: Optional[bool] = None) -> None:
    """
    Guard that the ChEBI lookup DB matches the transform's OWL release.

    ``chebi.db`` decides each ChEBI node's Biolink category (SmallMolecule vs
    ChemicalRole vs macromolecule) via ancestor lookups, while the nodes
    themselves are emitted from ``chebi.owl``. A release gap means a term the
    transform emits may be absent from the DB, so its category silently falls
    back to the default — the same failure mode the GO gate exists to prevent.

    Defaults to **warn** rather than raise: when ``semsql`` is unavailable the
    pipeline legitimately falls back to a prebuilt ``chebi.db`` of a different
    release, and aborting the run would be worse than mis-categorising a handful
    of terms. Set ``KG_CHEBI_VERSION_CHECK=strict`` (or pass ``strict=True``) to
    fail loud. No-op when either stamp can't be read.

    :param db_path: Path to ``chebi.db``.
    :param strict: Override the env var / default strictness.
    :raises RuntimeError: On mismatch when strict.
    """
    from kg_microbe.transform_utils.constants import CHEBI_SOURCE

    strict = _version_check_strict("KG_CHEBI_VERSION_CHECK", strict, default_strict=False)
    if not CHEBI_SOURCE:
        return
    owl_release = _chebi_release_from_owl(Path(CHEBI_SOURCE), prefer_archive=True)
    db_release = _chebi_db_release(db_path)
    if owl_release and db_release and owl_release != db_release:
        msg = (
            f"ChEBI source version mismatch: chebi.owl={owl_release} vs "
            f"chebi.db={db_release}. Node categories are resolved against "
            "chebi.db but nodes are emitted from chebi.owl; a release gap can "
            "leave emitted terms uncategorised. To realign, rebuild the DB from "
            "the OWL (rm data/raw/chebi.db; the next run rebuilds via `semsql make`)."
        )
        if strict:
            raise OntologyVersionMismatchError(msg)
        print(f"WARNING: {msg}")


@contextmanager
def _build_file_lock(db_path: str):
    """
    Hold an exclusive, cross-process lock for one database's build.

    The per-ontology threading lock orders threads within an interpreter and
    nothing else. This repository ships an HPC array that starts several
    transform processes, each resolving ontologies independently, so on a missing
    or drifted database they could clear the same target, shuffle the same
    ``.prev`` and run ``semsql make`` on the same basename at once.

    Blocking rather than failing: waiting for another process to finish a build we
    also want is exactly the right outcome, and the caller re-checks afterwards
    rather than rebuilding.

    :param db_path: Database being built; the lock file sits beside it.
    :yield: Nothing; the lock is held for the duration of the block.
    """
    lock_path = f"{db_path}.buildlock"
    os.makedirs(os.path.dirname(os.path.abspath(lock_path)) or ".", exist_ok=True)
    handle = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o644)
    try:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            print(f"  Waiting for another process to finish building {db_path}...")
            fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)
    finally:
        os.close(handle)


def _build_semsql_db(
    owl_source: Optional[Path],
    db_path: str,
    min_size: int,
    label: str,
    cost_note: str,
    reuse_on_failure: bool = True,
    require_content: bool = True,
    ontology: Optional[str] = None,
    expected_release: Optional[str] = None,
) -> DbEnsureResult:
    """
    Run the guarded ``semsql make`` for one ontology.

    The body every ``_ensure_*_db`` shares once its own reuse/drift decision has
    been made: honour the opt-out, require ``semsql``, decompress a ``.gz`` source
    if that is all we have, move the existing DB aside, build, and restore it on
    any failure. Keeping this in one place is what makes "guarded build" mean the
    same thing for every ontology — the alternative is four copies of logic that
    took several review rounds to get right.

    :param owl_source: Plain OWL to build from; ``<source>.gz`` is decompressed
        when only the archive is present.
    :param db_path: Target DB path.
    :param min_size: Smallest plausible size for a complete build.
    :param label: Ontology name for messages.
    :param cost_note: One line telling the user what this build will cost them.
    :param reuse_on_failure: Whether an existing DB is still reported usable when
        a demanded build does not produce one — whether it could not start (no
        ``semsql``, missing OWL, failed decompression) or ran and failed. GO
        passes False: its gate is strict because a release mismatch silently
        miscategorises MF/CC terms as BiologicalProcess, so a drifted go.db that
        cannot be rebuilt must be rejected however the rebuild fell over. An
        explicit ``KG_SEMSQL_BUILD=off`` is not covered by this — a deliberate
        opt-out always reuses what is on disk.
    :return: Whether a usable DB exists, and whether this call built it.
    """

    def _fallback() -> DbEnsureResult:
        """Report the existing DB, or refuse it when the caller demands a build."""
        return DbEnsureResult(
            _servable_db(db_path, min_size, ontology, require_content=require_content) if reuse_on_failure else False
        )

    if not _semsql_build_enabled():
        # An explicit opt-out always reuses what is on disk, even for GO: the
        # user asked to skip the build, not to have categorisation refuse to run.
        print(f"Skipping {label} SemSQL build (KG_SEMSQL_BUILD opt-out); using {db_path} as-is")
        return DbEnsureResult(_servable_db(db_path, min_size, ontology, require_content=require_content))
    # Checked before decompressing: without semsql there is nothing to build, and
    # unpacking GB of OWL only to then bail out is pure waste.
    if shutil.which("semsql") is None:
        print(f"Warning: `semsql` not on PATH; cannot build {db_path}")
        return _fallback()
    if not (owl_source and (owl_source.exists() or owl_source.with_name(owl_source.name + ".gz").exists())):
        print(f"Warning: cannot build {db_path} — {label} OWL source {owl_source} is missing")
        return _fallback()
    # Cross-process, not just cross-thread. The per-ontology threading lock only
    # orders threads inside one interpreter, and this repository ships an HPC
    # array (hpc/run_parallel_transform.slurm) that starts several transform
    # processes which each resolve ontologies independently. Without a file lock
    # they can clear the same target, shuffle the same .prev and run `semsql make`
    # on the same basename simultaneously.
    with _build_file_lock(db_path):
        # Decompression happens under the lock, not before it: two processes
        # otherwise raced on the same destination. A stale plain OWL is replaced
        # rather than trusted — `kg download` refreshes the archive only, and
        # preferring whatever plain file happened to exist made an ontology
        # refresh invisible to both the release gate and the build.
        archive = owl_source.with_name(owl_source.name + ".gz")
        if archive.exists() and (not owl_source.exists() or _archive_release_differs(owl_source)):
            reason = "missing" if not owl_source.exists() else "a different release than the archive"
            print(f"Decompressing {archive} for the {label} build ({owl_source.name} is {reason})...")
            if not _decompress_atomically(archive, owl_source):
                return _fallback()
        if not owl_source.exists():
            print(f"Warning: cannot build {db_path} — {label} OWL source {owl_source} is missing")
            return _fallback()
        # Coalesce, but only on the question that actually prompted the build.
        # A generic "is it usable?" re-check here silently skipped every drift
        # rebuild, because a drifted database is usable by every measure except
        # the one that mattered. Asking whether the release we need is now present
        # is safe: if another process just produced it, ten queued HPC jobs stop
        # running ten sequential multi-hour builds that each replace the last.
        reader = _DB_RELEASE_READERS.get(ontology or "")
        if expected_release and reader and reader(db_path) == expected_release:
            if _servable_db(db_path, min_size, ontology, require_content=require_content):
                print(f"  {db_path} is already at {expected_release}; another process built it")
                return DbEnsureResult(True)
        return _run_semsql_build(
            owl_source,
            db_path,
            min_size,
            label,
            cost_note,
            reuse_on_failure=reuse_on_failure,
            require_content=require_content,
            ontology=ontology,
            expected_release=expected_release,
        )


def _report_release_shortfall(db_path: str, ontology: Optional[str], expected_release: Optional[str]) -> None:
    """
    Say so when a completed build did not produce the release that was asked for.

    Acceptance is deliberately still generic — schema, content, identity and size.
    A complete database of the wrong release is a real database, and refusing it
    would leave the caller with nothing. But saying nothing was worse than either:
    the caller rebuilds precisely because the database's release differs from the
    source's, so a build that reproduces the old release rebuilds again on the
    next invocation, and forever after, with no hint as to why. The cause is
    always upstream — a stale source, or one whose stamp cannot be read — and
    naming both releases points straight at it.

    :param db_path: The database just built.
    :param ontology: Ontology it holds, or None if unknown.
    :param expected_release: Release the source was read as.
    """
    reader = _DB_RELEASE_READERS.get(ontology or "")
    if not (expected_release and reader):
        return
    built_release = reader(db_path)
    if built_release is None or built_release == expected_release:
        return
    print(
        f"Warning: built {db_path} at release {built_release}, but {ontology}'s source "
        f"reads as {expected_release}. The build ran against a source that is not the "
        "one the release gate compared, so this rebuild will repeat on every run until "
        "the two agree. Check for a stale decompressed OWL beside its .gz."
    )


def _build_confirmed(db_path: str, ontology: Optional[str], require_content: bool) -> Optional[bool]:
    """
    Judge a finished build, tri-state, before anything irreversible happens.

    This verdict gates :func:`_discard_kept_target`, which deletes the previous
    database — so it has to be the strongest check in the module, not merely the
    structural one. Confirming only the schema meant a complete database *for the
    wrong ontology* was accepted whenever its identity probe came back
    indeterminate — a transient lock is enough — and the known-good ``.prev`` was
    deleted for it. ``_usable_db`` does not close this: it rejects a demonstrably
    wrong ontology but, being a preservation predicate, accepts one it cannot
    establish.

    :param db_path: The database just built.
    :param ontology: Ontology it must hold, or None if not applicable.
    :param require_content: Whether label and hierarchy rows are required.
    :return: True if confirmed good, False if demonstrably bad, None if neither
        could be established.
    """
    schema = _has_semsql_schema(db_path, require_content)
    if schema is not True or ontology is None:
        return schema
    return _db_is_for_ontology(db_path, ontology)


def _db_has_active_writer(db_path: str) -> bool:
    """
    Report whether another process currently holds a write lock on ``db_path``.

    A blocked *read* is not the test. SQLite's RESERVED lock — what an ordinary
    ``BEGIN IMMEDIATE`` takes, and what a writer holds for the whole of its
    transaction — deliberately permits readers, so the classification says ``ok``
    and a live writer's database was renamed to ``.prev``, rebuilt over, and the
    ``.prev`` deleted on success. Only an EXCLUSIVE lock, taken briefly at commit,
    blocks readers, so classifying on readability caught a writer only in the
    instant it was finishing.

    The reliable question is the one a writer itself asks: try to take the write
    lock. Failing to get it means someone else holds it.

    Racy by construction — a writer may start immediately after this returns — and
    that is accepted. It closes the window that matters, a *concurrent long-lived*
    writer, which is the case that loses committed data. Nothing here is a
    substitute for the build lock, which is what stops two of our own builds from
    colliding.

    :param db_path: Path to the DB.
    :return: True if another process holds a write lock.
    """
    if not os.path.lexists(db_path):
        return False
    if os.path.islink(db_path) and not os.path.exists(db_path):
        # A dangling link has no writer, and connecting read-write would *create*
        # the file at the link's target — the accident `_read_only_connection`
        # exists to prevent.
        return False
    try:
        conn = sqlite3.connect(db_path, timeout=_DB_PROBE_TIMEOUT_SECONDS)
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("ROLLBACK")
        finally:
            conn.close()
    except sqlite3.OperationalError as exc:
        if _is_transient_db_error(exc):
            return True
        # Read-only file, read-only filesystem, or something else that stops us
        # writing. Not a writer, and not this function's problem to report — the
        # build will fail on its own terms and restore what it displaced.
        return False
    except sqlite3.Error:
        return False
    # The write lock was ours to take, so nobody else held it.
    return False


def _run_semsql_build(
    owl_source: Path,
    db_path: str,
    min_size: int,
    label: str,
    cost_note: str,
    *,
    reuse_on_failure: bool,
    require_content: bool,
    ontology: Optional[str],
    expected_release: Optional[str] = None,
) -> DbEnsureResult:
    """
    Clear the target, run ``semsql make``, and judge the result.

    Split out of :func:`_build_semsql_db` so the whole destructive sequence —
    clear, build, validate, restore or discard — sits inside one file lock.

    :param owl_source: Plain OWL to build from.
    :param db_path: Target DB path.
    :param min_size: Smallest plausible size for a complete build.
    :param label: Ontology name for messages.
    :param cost_note: One line telling the user what this build will cost.
    :param reuse_on_failure: Whether an existing DB may still be reported usable.
    :param require_content: Whether label and hierarchy rows are required.
    :param ontology: Ontology the DB must hold.
    :param expected_release: Release the source was read as, for reporting a build
        that did not produce it.
    :return: Whether a usable DB exists, and whether this call built it.
    """
    if _db_has_active_writer(db_path):
        # Another process holds a write transaction. Every later step here is
        # destructive — rename to .prev, build at the original path, discard .prev
        # on success — and the writer's commits would land on the moved inode and
        # then be thrown away with it. `_present_db` already documents that a live
        # writer's database must not be moved aside; the clear path never enforced
        # it, because BUSY counts as present and present meant "safe to displace".
        # Nothing is touched: no rename, no build, no deletion.
        print(
            f"Warning: not rebuilding {db_path} — another process is writing to it. "
            "Re-run once that process has finished."
        )
        return DbEnsureResult(_servable_db(db_path, min_size, ontology, require_content=require_content))
    kept = _clear_build_target(db_path, min_size, ontology=ontology, require_content=require_content)
    print(f"Building {db_path} from {owl_source} via `semsql make`.\n  {cost_note}")
    try:
        subprocess.run(  # noqa: S603
            ["semsql", "make", os.path.basename(db_path)],  # noqa: S607
            cwd=str(owl_source.parent),
            check=True,
        )
    except (subprocess.CalledProcessError, OSError) as e:
        # Expected build failures degrade: restore the old DB and report on it.
        print(f"Warning: failed to build {db_path}: {e}")
        _restore_build_target(db_path, kept)
        # A restored artifact is judged leniently: it may legitimately be a
        # symlink the user supplied, which _usable_db rejects by design. But a
        # caller that passed reuse_on_failure=False wants the *rebuild*, so the
        # restored copy is refused here exactly as it is at the preflight exits.
        return DbEnsureResult(
            reuse_on_failure
            and _restored_db_usable(db_path, min_size, kept, ontology=ontology, require_content=require_content)
        )
    except BaseException:  # noqa: BLE001 — KeyboardInterrupt must not strand .prev
        # Ctrl-C during a build previously left the DB gone and a multi-GB .prev
        # orphaned. This cannot help against SIGKILL or an unhandled SIGTERM,
        # which do not unwind — _clear_build_target's recovery covers those.
        _restore_build_target(db_path, kept)
        raise
    if _usable_db(db_path, min_size, ontology=ontology, require_content=require_content):
        # Re-validate in full, not just the schema. Between the integrity check
        # and here the file can have been replaced by something schema-valid but
        # undersized or damaged, and confirming only the schema discarded the
        # previous copy for it.
        confirmed = (
            _build_confirmed(db_path, ontology, require_content)
            if _usable_db(db_path, min_size, ontology=ontology, require_content=require_content)
            else False
        )
        if confirmed:
            _report_release_shortfall(db_path, ontology, expected_release)
            _discard_kept_target(kept)
            return DbEnsureResult(True, built=True)
        if confirmed is False:
            # Not merely unverified — demonstrably bad. Treat it as a failed
            # build: leaving it at the canonical path while reporting success
            # meant the reuse fast-path then accepted it, with the good copy
            # sitting dormant at .prev.
            print(f"Warning: {db_path} lacks a usable SemSQL schema; restoring the previous DB")
            _restore_build_target(db_path, kept)
            return DbEnsureResult(
                reuse_on_failure
                and _restored_db_usable(db_path, min_size, kept, ontology=ontology, require_content=require_content)
            )
        # None: the schema could not be established (locked). Keeping the previous
        # copy is right — nothing has shown the replacement to be usable — but
        # that is the *preservation* answer, and this exit was returning it as the
        # serving answer too. Round 18 tightened every other exit that reports
        # usability and left this one: a build whose result could not be verified
        # was handed to OAK unchecked, where per-term handlers turn the resulting
        # lookup errors into default categories. Keep .prev, and let the serving
        # predicate decide what the caller may do with what was built.
        print(
            f"  Keeping {kept}: {db_path} was built but its SemSQL schema could not be "
            "verified (locked?). Delete the .prev once the new DB is confirmed good."
        )
        return DbEnsureResult(_servable_db(db_path, min_size, ontology, require_content=require_content), built=True)
    # The rejected artifact is deliberately left in place. Removing it looked
    # like the fix for "the next run adopts it", but that harm belongs to the
    # reuse fast-path, which now checks the schema itself — and deleting it
    # turned metatraits' hard error on a freshly built invalid DB into a silent
    # fallback to the OAK cache.
    print(f"Warning: {db_path} is not a complete build; restoring the previous DB")
    _restore_build_target(db_path, kept)
    return DbEnsureResult(
        reuse_on_failure
        and _restored_db_usable(db_path, min_size, kept, ontology=ontology, require_content=require_content)
    )


def _ensure_chebi_db(db_path: str) -> DbEnsureResult:
    """
    Build the ChEBI SemSQL DB from ``chebi.owl``; return True if usable.

    Third application of the GO single-source rule (#604), after GO and
    NCBITaxon. Previously ``chebi.db`` was whatever OAK had fetched or a copy
    carried over from an older ``data/raw``, with no gate — and unlike the other
    two it could not even be checked, because ChEBI's integer release stamp is
    invisible to the date-based reader.

    Decompresses ``chebi.owl.gz`` when only the archive is present, since
    ``semsql make`` needs the plain OWL beside it. Rebuilds on release drift and
    degrades to a warning (keeping any existing DB) when the OWL or ``semsql`` is
    unavailable.

    :param db_path: Target path for ``chebi.db``.
    :return: Whether a usable DB exists at db_path, and whether this call built it.
    """
    from kg_microbe.transform_utils.constants import CHEBI_SOURCE

    min_size = _CHEBI_DB_MIN_SIZE
    owl_source = Path(CHEBI_SOURCE) if CHEBI_SOURCE else None
    owl_release = _chebi_release_from_owl(owl_source, prefer_archive=True) if owl_source else None
    _note_orphaned_prev(db_path)
    if _servable_db(db_path, min_size, "chebi"):
        db_release = _chebi_db_release(db_path)
        if not (owl_release and db_release and owl_release != db_release):
            return DbEnsureResult(True)
        print(
            f"Rebuilding {db_path}: release {db_release} drifted from "
            f"chebi.owl {owl_release} (single-source realign)..."
        )
    return _build_semsql_db(
        owl_source,
        db_path,
        min_size,
        "ChEBI",
        "ChEBI runs relation-graph: expect 30+ minutes and several GB of RAM. "
        "Set KG_SEMSQL_BUILD=off to skip and use a prebuilt DB instead.",
        require_content=True,
        ontology="chebi",
        expected_release=owl_release,
    )


# Every ontology adapter in the pipeline is obtained through this table, so
# "guarded build" means the same thing everywhere. Before it, seven transforms
# called get_adapter(f"sqlite:{X_SOURCE}") with an *OWL* path — which OAK
# silently interprets as "build the SemSQL DB for this OWL" and runs its own
# unannounced `semsql make`, bypassing the opt-out, the size floor, the
# keep-aside and the version gates.
_ONTOLOGY_DB_NAMES = {
    "ncbitaxon": ("NCBITAXON_SOURCE", "ncbitaxon.db"),
    "chebi": ("CHEBI_SOURCE", "chebi.db"),
    "go": ("GO_SOURCE", "go.db"),
    "ec": ("EC_SOURCE", "ec.db"),
}


def ontology_db_path(ontology: str) -> str:
    """
    Return the SemSQL DB path for an ontology, beside its OWL source.

    :param ontology: One of ``ncbitaxon``, ``chebi``, ``go``, ``ec``.
    :return: Absolute path to the ``.db``.
    :raises KeyError: For an unknown ontology name.
    """
    from kg_microbe.transform_utils import constants

    source_attr, db_name = _ONTOLOGY_DB_NAMES[ontology]
    return str(Path(getattr(constants, source_attr)).parent / db_name)


def _ensure_and_gate(ontology: str, db_path: str) -> bool:
    """
    Build/realign one ontology's DB and run its version gate.

    :param ontology: Ontology key.
    :param db_path: Target DB path.
    :return: Whether a usable DB is present afterwards.
    """
    ensure = {
        "ncbitaxon": _ensure_ncbitaxon_db,
        "chebi": _ensure_chebi_db,
        "go": _ensure_go_db,
        "ec": _ensure_ec_db,
    }[ontology]
    if not ensure(db_path):
        return False
    # Only DB-vs-OWL gates belong here. assert_go_version_alignment compares
    # go.owl to go.json — a transform-output concern, checked where go.json is
    # actually consumed. Running it for every GO adapter user made a stale
    # go.json raise in rhea/uniprot and, in bakta (whose caller catches
    # Exception), silently collapse every GO term to molecular_function — the
    # opposite of what that gate exists for. go.db-vs-go.owl drift is already
    # handled inside _ensure_go_db.
    if ontology == "chebi":
        assert_chebi_version_alignment(db_path)
    elif ontology == "ncbitaxon":
        assert_ncbitaxon_version_alignment(db_path)
    return True


# One lock per ontology, guarding the ensure+open critical section. A dict rather
# than a single global lock so a slow NCBITaxon build does not block an unrelated
# EC resolve; _ADAPTER_LOCKS_GUARD only covers creating the per-ontology entry.
# Release readers by ontology, used to answer "did the process we waited for
# produce the release we need?". EC has no reliable stamp and is a minutes-long
# build, so it simply rebuilds.
_DB_RELEASE_READERS = {
    "ncbitaxon": lambda path: _ncbitaxon_db_release(path),
    "chebi": lambda path: _chebi_db_release(path),
    "go": lambda path: _go_db_release(path),
}

_DECOMPRESS_COUNTER = itertools.count()

_ADAPTER_LOCKS: Dict[str, threading.Lock] = {}
_ADAPTER_LOCKS_GUARD = threading.Lock()


def _adapter_lock(ontology: str) -> threading.Lock:
    """
    Return the lock guarding one ontology's resolution.

    :param ontology: Ontology key.
    :return: A process-wide lock unique to that ontology.
    """
    with _ADAPTER_LOCKS_GUARD:
        return _ADAPTER_LOCKS.setdefault(ontology, threading.Lock())


@lru_cache(maxsize=None)
def _ontology_adapter_for(ontology: str, db_path: str):
    """
    Ensure, gate and open one ontology's adapter, once per process.

    :param ontology: Ontology key.
    :param db_path: Target DB path.
    :return: OAK adapter, or None when no usable DB could be produced. Returned
        rather than raised so ``lru_cache`` memoises the failure — otherwise a
        failing path re-runs the whole ensure, potentially a multi-hour build,
        on every call.
    """
    from oaklib import get_adapter

    # lru_cache does not hold a lock across the wrapped call, so two threads that
    # miss concurrently both execute this body. Without serialising, both would
    # enter _ensure_and_gate and race each other through .prev move-aside,
    # decompression and `semsql make` on the same paths — two builds writing one
    # file. The second thread re-runs _ensure_and_gate once the first releases,
    # which is then the cheap reuse fast-path.
    with _adapter_lock(ontology):
        if not _ensure_and_gate(ontology, db_path):
            return None
        return get_adapter(f"sqlite:{db_path}")


def get_ontology_adapter(ontology: str):
    """
    Return an OAK adapter for one ontology, building its DB if needed.

    The single entry point transforms should use. Never pass an ``.owl`` path to
    ``get_adapter`` directly: OAK treats that as a request to build, outside
    every guard this module provides.

    :param ontology: One of ``ncbitaxon``, ``chebi``, ``go``, ``ec``.
    :return: OAK adapter over the ontology's SemSQL DB.
    :raises OntologyDbUnavailableError: If no usable DB could be produced.
    """
    db_path = ontology_db_path(ontology)
    adapter = _ontology_adapter_for(ontology, db_path)
    if adapter is None:
        raise OntologyDbUnavailableError(
            f"No usable {ontology} SemSQL DB at {db_path}. Install `semsql` and place "
            f"the OWL (or its .gz) in data/raw so it can be built, or supply a prebuilt "
            f"{Path(db_path).name}. See the warning above for which step failed."
        )
    return adapter


get_ontology_adapter.cache_clear = _ontology_adapter_for.cache_clear


class _LazyOntologyAdapter:

    """
    An ontology adapter that resolves on first use, not on construction.

    Transforms build their adapters in ``__init__``. Resolving eagerly there
    means merely *constructing* a transform can raise when a DB is absent — which
    broke every transform-constructor test on a machine without ``data/raw``
    populated — and, worse, can kick off a multi-hour ``semsql`` build before the
    transform has done anything. Deferring to first attribute access keeps the
    guard while making construction free.
    """

    def __init__(self, ontology: str):
        """
        Record which ontology to resolve, without touching the disk.

        :param ontology: Ontology key.
        """
        self._ontology = ontology
        self._resolved = None

    def resolve(self):
        """
        Ensure, gate and open the adapter, once.

        :return: The underlying OAK adapter.
        :raises OntologyDbUnavailableError: If no usable DB could be produced.
        """
        if self._resolved is None:
            self._resolved = get_ontology_adapter(self._ontology)
        return self._resolved

    def __getattr__(self, name):
        """
        Forward public attributes to the resolved adapter.

        Private and dunder names are refused without resolving. ``pickle`` and
        ``copy`` probe ``__getstate__``/``__setstate__``/``__deepcopy__`` on the
        instance: answering those resolved the adapter, so merely *serialising* a
        proxy could start a multi-hour build — and because they construct via
        ``object.__new__`` with no ``__init__``, reading ``self._resolved`` from
        inside ``__getattr__`` recursed until the stack blew.

        :param name: Attribute being accessed.
        :return: The attribute from the real adapter.
        :raises AttributeError: For private and dunder names.
        """
        if name.startswith("_"):
            raise AttributeError(name)
        return getattr(self.resolve(), name)

    def __bool__(self) -> bool:
        """
        Report truthy without resolving.

        Implicit dunder lookup goes to the type, not ``__getattr__``, so without
        this the proxy was truthy by default and ``if not adapter:`` guards
        written for the old "returns None when unavailable" contract silently
        never fired. Answering True is the honest contract now: an unavailable
        ontology raises :class:`OntologyDbUnavailableError` on first use rather
        than yielding a falsy adapter, so such guards should be deleted, not
        satisfied. Resolving here instead would mean a truthiness test could
        start a multi-hour build.

        :return: Always True.
        """
        return True


def resolve_adapter(adapter):
    """
    Force a lazily-resolved adapter to resolve now; pass anything else through.

    Use this at the top of a function that is about to open an output file or
    start a long loop. Resolution is otherwise deferred to the first attribute
    access, which can be well after work has begun — and a fatal failure there
    aborts mid-write. The atomic-write helper stops that from leaving a poisoned
    artifact, but surfacing the failure before any work starts is cheaper and
    reads better in a log.

    :param adapter: A lazy proxy, a real OAK adapter, or None.
    :return: The resolved adapter (or the argument unchanged).
    """
    if isinstance(adapter, _LazyOntologyAdapter):
        return adapter.resolve()
    return adapter


def get_ncbitaxon_adapter():
    """Return a lazily-resolved guarded NCBITaxon adapter. :return: adapter proxy."""
    return _LazyOntologyAdapter("ncbitaxon")


def get_go_adapter():
    """Return a lazily-resolved guarded GO adapter. :return: adapter proxy."""
    return _LazyOntologyAdapter("go")


def get_ec_adapter():
    """Return a lazily-resolved guarded EC adapter. :return: adapter proxy."""
    return _LazyOntologyAdapter("ec")


def get_chebi_adapter():
    """
    Return a lazily-resolved guarded ChEBI adapter.

    Kept as a named accessor because ChEBI has the most callers; it is now the
    same lazy proxy the other ontologies use, over the shared cache.

    :return: adapter proxy.
    """
    return _LazyOntologyAdapter("chebi")


get_chebi_adapter.cache_clear = _ontology_adapter_for.cache_clear


def _ensure_ncbitaxon_db(db_path: str) -> DbEnsureResult:
    """
    Build the NCBITaxon SemSQL DB from ``ncbitaxon.owl``; return True if usable.

    Applies the GO single-source rule (#604) to NCBITaxon. The alternative — OAK's
    ``sqlite:obo:ncbitaxon``, which fetches whatever prebuilt SemSQL the upstream
    CDN last published — cannot be kept aligned: those builds lag the OBO release
    train by months (checked 2026-07-26, the newest ``ncbitaxon.db.gz`` upstream
    was built 2026-05-24 while ``ncbitaxon.owl`` was at 2026-07-12), so refreshing
    the cache does not close a gap, it only re-downloads 2.3 GB. Building from the
    OWL we actually ship makes the lookup DB and the emitted nodes the same
    release by construction.

    Rebuilds when the DB's release stamp has drifted from the OWL's, mirroring
    :func:`_ensure_go_db`. Degrades gracefully (warn + report current state) when
    the OWL source or ``semsql`` is unavailable, so a machine without the build
    toolchain still falls back to whatever DB is already present.

    :param db_path: Target path for ``ncbitaxon.db``.
    :return: Whether a usable DB exists at db_path, and whether this call built it.
    """
    from kg_microbe.transform_utils.constants import NCBITAXON_SOURCE

    min_size = _NCBITAXON_DB_MIN_SIZE
    owl_source = Path(NCBITAXON_SOURCE) if NCBITAXON_SOURCE else None
    owl_release = _obo_release_from_head(owl_source, prefer_archive=True) if owl_source else None
    _note_orphaned_prev(db_path)
    if _servable_db(db_path, min_size, "ncbitaxon"):
        db_release = _ncbitaxon_db_release(db_path)
        if not (owl_release and db_release and owl_release != db_release):
            return DbEnsureResult(True)
        print(
            f"Rebuilding {db_path}: release {db_release} drifted from "
            f"ncbitaxon.owl {owl_release} (single-source realign)..."
        )
    return _build_semsql_db(
        owl_source,
        db_path,
        min_size,
        "NCBITaxon",
        "NCBITaxon is the heaviest source in the pipeline: expect hours and a "
        "~13 GB result. Set KG_SEMSQL_BUILD=off to skip.",
        require_content=True,
        ontology="ncbitaxon",
        expected_release=owl_release,
    )


def _ensure_go_db(go_db_path: str) -> DbEnsureResult:
    """
    Build the GO SemSQL DB from ``go.owl`` if missing/empty; return True if usable.

    Unlike ``chebi.db`` (built on demand by OAK's ``sqlite:`` adapter), the GO
    aspect map is read with a raw ``sqlite3`` query (to bypass OAK's curies
    converter, which chokes on GO's case-collision prefixes), so nothing builds
    ``go.db`` — a fresh checkout / cleaned ``data/raw`` leaves a 0-byte stub.
    Build it once with ``semsql make`` (the same toolchain that produces
    ``chebi.db``). Degrades gracefully (warn + return current state) when the
    OWL source or ``semsql`` is unavailable.
    """
    from kg_microbe.transform_utils.constants import GO_SOURCE

    owl_release = _obo_release_from_head(Path(GO_SOURCE), prefer_archive=True) if GO_SOURCE else None
    _note_orphaned_prev(go_db_path)
    if _servable_db(go_db_path, _GO_DB_MIN_SIZE, "go"):
        # An existing, non-stub go.db is reused — unless it has drifted from the
        # source OWL's release (single-source invariant, fix 2 #604): a refreshed
        # go.owl must rebuild go.db, else the aspect map lags the transform output
        # and MF/CC terms silently fall through to BiologicalProcess. Only rebuild
        # when both release stamps are readable and differ (an unreadable stamp
        # never forces a costly spurious rebuild).
        db_release = _go_db_release(go_db_path)
        if not (owl_release and db_release and owl_release != db_release):
            return DbEnsureResult(True)
        print(
            f"Rebuilding {go_db_path}: release {db_release} drifted from "
            f"go.owl {owl_release} (single-source realign)..."
        )
    return _build_semsql_db(
        Path(GO_SOURCE) if GO_SOURCE else None,
        go_db_path,
        _GO_DB_MIN_SIZE,
        "GO",
        "A full GO SemSQL build runs relation-graph and can take 10-30+ minutes "
        "/ several GB RAM. Set KG_SEMSQL_BUILD=off to skip.",
        reuse_on_failure=False,
        require_content=True,
        ontology="go",
        expected_release=owl_release,
    )


def _ensure_ec_db(db_path: str) -> DbEnsureResult:
    """
    Build the EC SemSQL DB from ``ec.owl``; return whether one is usable.

    EC had no builder, so ``get_adapter("sqlite:<ec.owl>")`` delegated to OAK's
    own build — unannounced, unguarded, and outside the opt-out. EC is small, so
    the build is quick, but it goes through the same guarded path as the others
    for consistency.

    :param db_path: Target path for ``ec.db``.
    :return: Whether a usable DB exists, and whether this call built it.
    """
    from kg_microbe.transform_utils.constants import EC_SOURCE

    owl_source = Path(EC_SOURCE) if EC_SOURCE else None
    _note_orphaned_prev(db_path)
    if _servable_db(db_path, _EC_DB_MIN_SIZE, "ec"):
        # EC's OWL carries no reliable release stamp, so there is no drift check
        # to make: an existing DB is reused.
        return DbEnsureResult(True)
    return _build_semsql_db(
        owl_source,
        db_path,
        _EC_DB_MIN_SIZE,
        "EC",
        "EC is small; this build usually takes a couple of minutes.",
        require_content=True,
        ontology="ec",
    )


# Attempts for the one-time GO namespace read, with a linear backoff between
# them (~5 s in total at the default probe timeout). More generous than
# _DB_PROBE_RETRIES because this read's failure is fatal rather than advisory.
_GO_NAMESPACE_READ_ATTEMPTS = 5


def _query_go_namespaces(go_db_path: str) -> Dict[str, str]:
    """
    Read the GO id → OBO namespace rows, retrying while the database is locked.

    Split out so the retry is around the read alone. A lock is the routine
    condition on shared storage — the HPC array runs several transforms against
    one ``data/raw`` — and without a retry a momentary one produced an empty map,
    which files every MF and CC term as BiologicalProcess. Retrying costs
    milliseconds against a multi-hour transform.

    :param go_db_path: Path to ``go.db``.
    :return: The namespace map as read.
    :raises sqlite3.Error: If the read fails for a reason retrying cannot fix, or
        remains locked after the last attempt.
    """
    for attempt in range(_GO_NAMESPACE_READ_ATTEMPTS):
        try:
            conn = _read_only_connection(go_db_path)
            try:
                cur = conn.execute(
                    "SELECT subject, value FROM node_to_value_statement "
                    "WHERE predicate = 'oio:hasOBONamespace' AND subject LIKE 'GO:%'"
                )
                return {row[0]: row[1] for row in cur}
            finally:
                conn.close()
        except sqlite3.Error as exc:
            if not _is_transient_db_error(exc) or attempt + 1 == _GO_NAMESPACE_READ_ATTEMPTS:
                raise
            print(f"  {go_db_path} is locked; retrying the GO namespace read")
            # Backs off, unlike the probe loop. Exhausting this budget aborts the
            # run, so waiting a few seconds for a concurrent reader to finish is
            # plainly worth it against a multi-hour transform.
            time.sleep(_DB_PROBE_TIMEOUT_SECONDS * (attempt + 1))
    raise AssertionError("unreachable: the loop either returns or raises")


def _load_go_namespace_map(go_db_path: str) -> Dict[str, str]:
    """
    Read GO id → OBO namespace from semantic-sql sqlite directly.

    Bypasses OAK's curies converter, which fails to build when the upstream
    GO sqlite contains case-collision prefix rows (e.g. both 'CHR' and 'chr'
    → 'obo/CHR_'). Newer `curies` rejects duplicate URI prefixes strictly,
    so every entity_metadata_map call would otherwise throw and fall through
    to the BiologicalProcess fallback for every GO node.

    Caches success only. A failed read raises rather than returning an empty map:
    an empty map is not a weaker answer but a wrong one, since every MF and CC
    term in it silently becomes a BiologicalProcess. Contention is absorbed by the
    retry budget in :func:`_query_go_namespaces`, not by degrading.

    :param go_db_path: Path to ``go.db``.
    :return: GO id → namespace.
    :raises OntologyDbUnavailableError: If the map cannot be read.
    """
    global _GO_NAMESPACE_CACHE
    if _GO_NAMESPACE_CACHE is not None:
        return _GO_NAMESPACE_CACHE
    # Build go.db from go.owl if it's missing/empty — nothing else does, so a
    # 0-byte stub would otherwise miscategorize every GO term (see _ensure_go_db).
    #
    # The result is not optional. Discarding it meant a failed ensure fell
    # through to sqlite3.connect(), which *creates* an empty file, whose failed
    # query was cached as an empty map — and every GO term then became
    # BiologicalProcess. That is the failure this whole change exists to prevent,
    # reached through the one path that never checked.
    if not _ensure_go_db(go_db_path):
        raise OntologyDbUnavailableError(
            f"No usable GO SemSQL DB at {go_db_path}, so GO aspects cannot be read. "
            "Install `semsql` and place go.owl (or its .gz) in data/raw, or supply a "
            "prebuilt go.db. Continuing would file every MF/CC term as BiologicalProcess."
        )
    try:
        namespaces = _query_go_namespaces(go_db_path)
        if not namespaces:
            # Schema, identity, labels and hierarchy can all be present while
            # the namespace rows are not, and an empty map sends every term
            # to the BiologicalProcess default — the miscategorisation this
            # work exists to prevent, arrived at through a database that
            # passed every generic check. The real go.db holds ~48k of these
            # rows; zero means the build cannot answer the question.
            raise OntologyDbUnavailableError(
                f"{go_db_path} has no oio:hasOBONamespace rows, so GO aspects cannot be "
                "read. Rebuild go.db from go.owl (delete it and re-run), or supply a "
                "prebuilt one. Continuing would file every MF/CC term as "
                "BiologicalProcess."
            )
        # Published only once validated. Assigning the map before the emptiness
        # check meant that if anything ever caught the error above and carried on,
        # the cache already held `{}` and served it to every later call.
        _GO_NAMESPACE_CACHE = namespaces
        return _GO_NAMESPACE_CACHE
    except Exception as exc:
        # An empty map is not a degraded answer, it is a wrong one: every MF and
        # CC term in it becomes a BiologicalProcess. Not latching a transient
        # failure fixed the *later* calls but left this one still returning {},
        # so a lock outliving the retries silently miscategorised every term
        # processed while it was held. There is no honest fallback here, which is
        # what this error class is for — and it cannot be swallowed by the broad
        # per-item handlers, so the run stops instead of emitting a wrong graph.
        raise OntologyDbUnavailableError(
            f"Could not read GO namespaces from {go_db_path}: {exc}. Every MF and CC "
            "term would be filed as BiologicalProcess, so this run cannot continue. "
            "Retry if another process holds the database, or rebuild go.db from go.owl."
        ) from exc


def replace_category_ontology(line, id_index, category_index):
    """
    Replace node category according to prefix that has already been fixed.

    :param line: A line from the original triples.
    :type line: str
    """
    parts = line.split("\t")
    parts = [i.strip() for i in parts]
    if EC_PREFIX in parts[id_index]:
        new_category = EC_CATEGORY
        parts[category_index] = new_category
    if GO_PREFIX in parts[id_index]:
        new_category = GO_CATEGORY
        parts[category_index] = new_category
    if UNIPROT_PREFIX in parts[id_index]:
        new_category = PROTEIN_CATEGORY
        parts[category_index] = new_category
    if RHEA_NEW_PREFIX in parts[id_index]:
        new_category = RHEA_CATEGORY
        parts[category_index] = new_category
    if HGNC_NEW_PREFIX in parts[id_index]:
        new_category = GENE_CATEGORY
        parts[category_index] = new_category
    new_line = "\t".join(parts)
    return new_line


def get_go_category_by_aspect(go_term_id: str, go_adapter: Optional[OboGraphInterface] = None) -> str:
    """
    Return Biolink category based on GO aspect (namespace).

    GO terms have three aspects (namespaces):
    - molecular_function → biolink:MolecularActivity
    - biological_process → biolink:BiologicalProcess
    - cellular_component → biolink:CellularComponent

    Args:
    ----
        go_term_id: GO term ID (e.g., "GO:0004096")
        go_adapter: Unused (kept for backward compatibility with existing callers).
            Namespace lookup uses a cached direct sqlite query against GO_SOURCE.

    Returns:
    -------
        Biolink category string

    Examples:
    --------
        >>> get_go_category_by_aspect("GO:0004096")  # catalase activity
        'biolink:MolecularActivity'

        >>> get_go_category_by_aspect("GO:0006091")  # generation of precursor metabolites
        'biolink:BiologicalProcess'

    """
    del go_adapter  # see docstring
    from kg_microbe.transform_utils.constants import GO_SOURCE

    go_db_path = str(GO_SOURCE.with_suffix(".db")) if GO_SOURCE else "data/raw/go.db"

    try:
        ns_map = _load_go_namespace_map(go_db_path)
    except Exception as e:
        print(f"Warning: Could not load GO namespace map from {go_db_path}: {e}")
        return BIOLOGICAL_PROCESS_CATEGORY

    namespace = ns_map.get(go_term_id, "")
    if namespace == "molecular_function":
        return MOLECULAR_ACTIVITY_CATEGORY
    if namespace == "biological_process":
        return BIOLOGICAL_PROCESS_CATEGORY
    if namespace == "cellular_component":
        return CELLULAR_COMPONENT_CATEGORY

    return BIOLOGICAL_PROCESS_CATEGORY


def get_chebi_category(chebi_term_id: str, chebi_adapter: Optional[OboGraphInterface] = None) -> str:
    """
    Return appropriate Biolink category for ChEBI term.

    ChEBI terms can be:
    - Macromolecules (proteins, nucleic acids, polysaccharides) → biolink:MacromolecularComplex
    - Roles (e.g., "antioxidant", "inhibitor") → biolink:ChemicalRole
    - Small molecules (default) → CHEBI_CATEGORY (biolink:ChemicalEntity, see constants.py)

    Args:
    ----
        chebi_term_id: ChEBI term ID (e.g., "CHEBI:16828")
        chebi_adapter: Optional OAK adapter for ChEBI ontology

    Returns:
    -------
        Biolink category string

    """
    from kg_microbe.transform_utils.constants import MACROMOLECULE_CATEGORY

    # Create adapter if not provided. A standalone call degrades to the default
    # category when no DB can be produced, matching the behaviour before the
    # adapter was centralised; the bulk transform path passes an adapter it built
    # itself, so there the failure stays loud.
    if chebi_adapter is None:
        try:
            # Resolved here, not lazily: the strict version gate raises during
            # resolution, and it must surface before the broad `except Exception`
            # around the lookups below would quietly turn it into a default.
            chebi_adapter = get_ontology_adapter("chebi")
        except OntologyDbUnavailableError as e:
            # Only the "no DB" case degrades. A strict version-gate failure is a
            # deliberate abort and must propagate (F6).
            print(f"WARNING: {e}\n  Falling back to the default ChEBI category.")
            return SMALL_MOLECULE_CATEGORY

    try:
        ancestors = list(chebi_adapter.ancestors(chebi_term_id))

        # FIRST: Check if this is a macromolecule (more specific than role)
        # CHEBI:33839 is the parent class for all macromolecules
        if "CHEBI:33839" in ancestors:
            return MACROMOLECULE_CATEGORY

        # SECOND: Check if this is a role term using name-based detection
        # This is more reliable than checking ancestry because "role" is a very general parent
        label = chebi_adapter.label(chebi_term_id)

        if label:
            label_lower = label.lower()

            # ChEBI roles have specific patterns in their names
            # Check for role terms (as suffix or complete word)
            role_suffixes = [
                "inhibitor",
                "agonist",
                "antagonist",
                "activator",
                "inducer",
                "agent",
                "cofactor",
                "coenzyme",
                "catalyst",
                "ligand",
                "substrate",
                "product",
                "intermediate",
                "donor",
                "acceptor",
            ]

            # Standalone role terms (the term itself IS a role)
            standalone_roles = [
                "antioxidant",
                "drug",
                "pharmaceutical",
                "metabolite",
                "nutrient",
                "toxin",
                "poison",
                "mutagen",
                "carcinogen",
            ]

            # Check if the term itself is a standalone role
            if label_lower in standalone_roles:
                return ROLE_CATEGORY

            # Check for role suffixes at end of name
            if any(label_lower.endswith(suffix) for suffix in role_suffixes):
                return ROLE_CATEGORY

            # Check for role suffixes with space prefix (e.g., "enzyme inhibitor")
            if any(f" {suffix}" in label_lower for suffix in role_suffixes):
                return ROLE_CATEGORY

            # Check for "role" in the name itself
            if " role" in label_lower or label_lower.endswith("role"):
                return ROLE_CATEGORY

            # Check for specific role parent classes (direct children of CHEBI:50906)
            # These are more specific role categories
            specific_role_parents = [
                "CHEBI:50906",  # role
                "CHEBI:23888",  # drug
                "CHEBI:64047",  # chromophore
                "CHEBI:52217",  # pharmaceutical
            ]

            # Only categorize as role if it's a close descendant of specific role classes
            # (not just any distant ancestor)
            parents = list(chebi_adapter.relationships(chebi_term_id, predicates=["rdfs:subClassOf"]))
            parent_ids = [str(p[2]) for p in parents]

            if any(role_parent in parent_ids for role_parent in specific_role_parents):
                return ROLE_CATEGORY

    except Exception as e:
        print(f"Warning: Could not determine ChEBI category for {chebi_term_id}: {e}")

    # Default to SmallMolecule for most ChEBI terms (chemical compounds)
    return SMALL_MOLECULE_CATEGORY


def get_uberon_category(uberon_term_id: str) -> str:
    """
    Return appropriate Biolink category for UBERON anatomical terms.

    UBERON is an anatomy ontology, so all terms should be AnatomicalEntity.
    This handles edge cases where UBERON terms have multiple categories.

    Args:
    ----
        uberon_term_id: UBERON term ID (e.g., "UBERON:0000178")

    Returns:
    -------
        Biolink category string (always AnatomicalEntity for UBERON)

    Examples:
    --------
        >>> get_uberon_category("UBERON:0000178")  # blood
        'biolink:AnatomicalEntity'

        >>> get_uberon_category("UBERON:0001970")  # bile
        'biolink:AnatomicalEntity'

    """
    from kg_microbe.transform_utils.constants import ANATOMICAL_ENTITY_CATEGORY

    # All UBERON terms are anatomical entities
    return ANATOMICAL_ENTITY_CATEGORY


def get_ncbitaxon_category(ncbitaxon_id: str) -> str:
    """
    Return appropriate Biolink category for NCBITaxon terms.

    NCBITaxon is a taxonomy, so all terms should be OrganismTaxon.
    This handles edge cases like NCBITaxon:1 (root).

    Args:
    ----
        ncbitaxon_id: NCBITaxon term ID (e.g., "NCBITaxon:1")

    Returns:
    -------
        Biolink category string (always OrganismTaxon for NCBITaxon)

    Examples:
    --------
        >>> get_ncbitaxon_category("NCBITaxon:1")  # root
        'biolink:OrganismTaxon'

    """
    from kg_microbe.transform_utils.constants import NCBI_CATEGORY

    # All NCBITaxon terms are organism taxa
    return NCBI_CATEGORY


def replace_deprecated_categories(category_str: str) -> str:
    """
    Replace deprecated Biolink categories with current equivalents.

    Args:
    ----
        category_str: Category string (may be pipe-delimited)

    Returns:
    -------
        Updated category string with deprecated categories replaced

    """
    if not category_str or category_str == "":
        return category_str

    # Map of deprecated → current categories (removed in biolink 4.x).
    deprecated_map: dict = {
        "biolink:ChemicalSubstance": "biolink:ChemicalEntity",
        "biolink:Macromolecule": "biolink:MacromolecularComplex",
    }

    updated_category = category_str
    for old_cat, new_cat in deprecated_map.items():
        updated_category = updated_category.replace(old_cat, new_cat)

    return updated_category
