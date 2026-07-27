"""Ontology utilities for category assignment and term processing."""

import gzip
import os
import re
import shutil
import sqlite3
import subprocess
import zlib
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
_GO_NAMESPACE_LOAD_FAILED: bool = False

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
# OBO release stamp, e.g. ``releases/2026-05-19/`` in a versionIRI.
_RELEASE_RE = re.compile(r"releases/(\d{4}-\d{2}-\d{2})")


def _obo_release_from_head(path: Path, nbytes: int = 2_000_000) -> Optional[str]:
    """
    Return the ``YYYY-MM-DD`` OBO release stamped near the top of an .owl/.json.

    Both OWL (``versionIRI rdf:resource=".../releases/DATE/..."``) and OBO-JSON
    (``meta`` versionInfo) carry the release near the file head, so a bounded
    read avoids parsing hundreds of MB. Returns None if unreadable / unstamped.
    """
    head = _read_head(path, nbytes)
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
    owl_release = _obo_release_from_head(owl_path)
    json_release = _obo_release_from_head(json_path)
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
    owl_release = _obo_release_from_head(Path(GO_SOURCE))
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
            raise RuntimeError(msg)
        print(f"WARNING: {msg}")


def _ncbitaxon_db_release(db_path: str) -> Optional[str]:
    """
    Return the NCBITaxon release (YYYY-MM-DD) recorded in a SemSQL ``.db``.

    Reads ``owl:versionInfo`` from the ``statements`` table (OAK/SemanticSQL
    stores the ontology's version there). Returns None on any read error or a
    missing/unparsable stamp.
    """
    try:
        conn = sqlite3.connect(db_path)
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
        conn = sqlite3.connect(db_path)
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
    owl_release = _obo_release_from_head(Path(NCBITAXON_SOURCE))
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
            raise RuntimeError(msg)
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


def _usable_db(db_path: str, min_size: int) -> bool:
    """
    Report whether a SemSQL DB at ``db_path`` is present and plausibly complete.

    For the **post-build** check only: a symlink here means ``semsql`` followed a
    stale link and the result landed somewhere else, so it is rejected. Use
    :func:`_present_db` on the "could not build; use what's there" exits, where a
    symlink is a legitimate way to supply a prebuilt DB.

    :param db_path: Path to the DB.
    :param min_size: Smallest plausible size for a complete build.
    :return: True if the file is a usable, locally-built DB.
    """
    return _present_db(db_path, min_size) and not os.path.islink(db_path)


def _restored_db_usable(db_path: str, min_size: int, kept: "KeptTarget") -> bool:
    """
    Judge the target after a failed build, according to what is now there.

    If something was displaced and put back, it is the caller's own artifact —
    possibly a symlink to a prebuilt DB, which is supported — so the lenient
    check applies. If nothing was displaced, whatever sits at the target came
    from the failed build itself, and a symlink there means it landed elsewhere.

    :param db_path: Path to the DB.
    :param min_size: Smallest plausible size for a complete build.
    :param kept: What :func:`_clear_build_target` displaced.
    :return: True if the file is usable.
    """
    return _present_db(db_path, min_size) if kept else _usable_db(db_path, min_size)


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

    :param db_path: Path to the DB.
    :param min_size: Smallest plausible size for a complete build.
    :return: True if the file is usable.
    """
    return os.path.exists(db_path) and os.path.getsize(db_path) >= min_size


def _read_head(path: Path, nbytes: int) -> Optional[str]:
    """
    Read the head of ``path``, transparently falling back to ``path`` + ``.gz``.

    Release stamps live in the first few KB, and the downloads ship compressed
    (``chebi.owl.gz``, ``ncbitaxon.owl.gz``) while the ``*_SOURCE`` constants name
    the uncompressed path. Without this fallback the release reads return None on
    a fresh checkout, which makes both the drift check and the version gate
    silently no-op — leaving an old DB in place, the exact drift this module
    exists to catch.

    :param path: Uncompressed path to read.
    :param nbytes: How many characters to read.
    :return: The head as text, or None if neither form is readable.
    """
    for opener, target in ((open, path), (gzip.open, path.with_name(path.name + ".gz"))):
        if not target.exists():
            continue
        try:
            with opener(target, "rt", encoding="utf-8", errors="ignore") as fh:
                return fh.read(nbytes)
        except (OSError, EOFError, zlib.error):
            return None
    return None


class ChebiDbUnavailableError(RuntimeError):

    """
    No usable ChEBI SemSQL DB could be produced.

    Distinct from the version gate's RuntimeError so the standalone
    ``get_chebi_category`` can degrade on the former without also swallowing a
    deliberate ``KG_CHEBI_VERSION_CHECK=strict`` abort (F6).
    """


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


def _clear_build_target(db_path: str, min_size: int) -> KeptTarget:
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
    prev_usable = os.path.lexists(kept) and _present_db(kept, min_size)
    target_is_link = os.path.islink(db_path)
    target_present = os.path.lexists(db_path)
    target_usable = target_present and not target_is_link and _present_db(db_path, min_size)

    if prev_usable and not target_usable:
        # The .prev is the good copy: the target is absent, a symlink, or the
        # partial remains of a killed build. Recover rather than overwrite.
        if target_is_link:
            target = os.readlink(db_path)
            os.remove(db_path)
            print(f"  Recovering {kept} left by an interrupted build (was symlinked to {target})")
            os.replace(kept, db_path)
            return KeptTarget(link_target=target)
        if target_present:
            print(f"  Discarding the partial {db_path} and recovering {kept}")
            os.remove(db_path)
        else:
            print(f"  Recovering {kept} left by an interrupted build")
        os.replace(kept, db_path)
        # Fall through so the recovered DB is moved aside for this build.

    if os.path.islink(db_path):
        target = os.readlink(db_path)
        os.remove(db_path)
        return KeptTarget(link_target=target)
    if not os.path.lexists(db_path):
        return KeptTarget()
    if os.path.lexists(kept):
        # Only reached when the target is at least as good as the .prev.
        os.remove(kept)
    os.replace(db_path, kept)
    return KeptTarget(prev_path=kept)


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
    tmp = destination.with_name(destination.name + ".partial")
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


def _chebi_release_from_owl(path: Path, nbytes: int = 2_000_000) -> Optional[str]:
    """
    Return the ChEBI release recorded near the top of ``chebi.owl``.

    ChEBI does not use OBO's ``YYYY-MM-DD`` stamp — it versions by an
    incrementing integer (``versionIRI .../obo/chebi/253/chebi.owl``,
    ``<owl:versionInfo>253</owl:versionInfo>``). :func:`_obo_release_from_head`
    only recognises dates, so it silently returns None for ChEBI and any gate
    built on it no-ops. Hence this separate reader.

    :param path: Path to ``chebi.owl``.
    :param nbytes: Bytes to read from the head (ChEBI OWL is ~1 GB uncompressed).
    :return: Release as a string (e.g. ``"253"``), or None if unreadable/unstamped.
    """
    head = _read_head(path, nbytes)
    if head is None:
        return None
    m = re.search(r"versionIRI[^>]{0,160}?/chebi/(\d+)/", head)
    if m:
        return m.group(1)
    m = re.search(r"<owl:versionInfo>\s*(\d+)\s*</owl:versionInfo>", head)
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
        conn = sqlite3.connect(db_path)
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
    owl_release = _chebi_release_from_owl(Path(CHEBI_SOURCE))
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
            raise RuntimeError(msg)
        print(f"WARNING: {msg}")


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
    _note_orphaned_prev(db_path)
    if _present_db(db_path, min_size):
        owl_release = _chebi_release_from_owl(owl_source) if owl_source else None
        db_release = _chebi_db_release(db_path)
        if not (owl_release and db_release and owl_release != db_release):
            return DbEnsureResult(True)
        print(
            f"Rebuilding {db_path}: release {db_release} drifted from "
            f"chebi.owl {owl_release} (single-source realign)..."
        )
    if not _semsql_build_enabled():
        print(f"Skipping ChEBI SemSQL build (KG_SEMSQL_BUILD opt-out); using {db_path} as-is")
        return DbEnsureResult(_present_db(db_path, min_size))
    # Checked before decompressing: without semsql there is nothing to build, and
    # unpacking ~1 GB only to then bail out is pure waste (#10).
    if shutil.which("semsql") is None:
        print(f"Warning: `semsql` not on PATH; cannot build {db_path}")
        return DbEnsureResult(_present_db(db_path, min_size))
    if owl_source and not owl_source.exists():
        # semsql needs the plain OWL; the download ships chebi.owl.gz.
        archive = owl_source.with_suffix(owl_source.suffix + ".gz")
        if archive.exists():
            print(f"Decompressing {archive} for the ChEBI SemSQL build...")
            if not _decompress_atomically(archive, owl_source):
                return DbEnsureResult(_present_db(db_path, min_size))
    if not (owl_source and owl_source.exists()):
        print(f"Warning: cannot build {db_path} — ChEBI OWL source {owl_source} is missing")
        return DbEnsureResult(_present_db(db_path, min_size))
    kept = _clear_build_target(db_path, min_size)
    print(
        f"Building {db_path} from {owl_source} via `semsql make`.\n"
        "  ChEBI runs relation-graph: expect 30+ minutes and several GB of RAM.\n"
        "  Set KG_SEMSQL_BUILD=off to skip and use a prebuilt DB instead."
    )
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
        # symlink the user supplied, which _usable_db rejects by design.
        return DbEnsureResult(_restored_db_usable(db_path, min_size, kept))
    except BaseException:  # noqa: BLE001 — KeyboardInterrupt must not strand .prev
        # Ctrl-C during a multi-hour build previously left the DB gone and a
        # 14 GB .prev orphaned. Note this cannot help against SIGKILL or an
        # unhandled SIGTERM, which do not unwind — _clear_build_target's
        # recovery is what covers those.
        _restore_build_target(db_path, kept)
        raise
    if _usable_db(db_path, min_size):
        _discard_kept_target(kept)
        return DbEnsureResult(True, built=True)
    # semsql can exit 0 having produced a short/misplaced file. Restore, then
    # report on what is actually at db_path now — not the pre-restore verdict.
    print(f"Warning: {db_path} is not a complete build; restoring the previous DB")
    _restore_build_target(db_path, kept)
    return DbEnsureResult(_restored_db_usable(db_path, min_size, kept))


@lru_cache(maxsize=None)
def _chebi_adapter_for(db_path: str):
    """
    Build/realign ``chebi.db``, gate its release, and open an adapter over it.

    Cached per path so the ensure + gate work (a 2 MB head read of ``chebi.owl``
    plus a SQLite open) happens once per process rather than per call (#618).
    Call :func:`get_chebi_adapter.cache_clear` to reset.

    :param db_path: Path to ``chebi.db``.
    :return: OAK adapter over ``chebi.db``.
    :raises RuntimeError: If no usable DB could be produced.
    """
    from oaklib import get_adapter

    if not _ensure_chebi_db(db_path):
        # Returned, not raised: lru_cache does not memoise exceptions, so raising
        # here would re-run the whole ensure — including a 30-minute `semsql make`
        # — on every subsequent call. get_chebi_adapter turns this into the error.
        return None
    assert_chebi_version_alignment(db_path)
    return get_adapter(f"sqlite:{db_path}")


def get_chebi_adapter():
    """
    Return an OAK adapter for ChEBI, building/realigning ``chebi.db`` first.

    Single entry point so the category-fixing code paths cannot diverge on how
    the DB is obtained (they previously each did ``get_adapter("sqlite:<owl>")``
    with an untested fallback to ``sqlite:data/raw/chebi.db``, which quietly
    accepted whatever DB happened to be on disk).

    :return: OAK adapter over ``chebi.db``.
    :raises RuntimeError: If no usable DB could be produced.
    """
    from kg_microbe.transform_utils.constants import CHEBI_SOURCE

    db_path = str(Path(CHEBI_SOURCE).parent / "chebi.db")
    adapter = _chebi_adapter_for(db_path)
    if adapter is None:
        raise ChebiDbUnavailableError(
            f"No usable ChEBI SemSQL DB at {db_path}. Install `semsql` and place "
            "chebi.owl (or chebi.owl.gz) in data/raw so it can be built, or supply "
            "a prebuilt chebi.db. See the warning above for which step failed."
        )
    return adapter


get_chebi_adapter.cache_clear = _chebi_adapter_for.cache_clear


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
    _note_orphaned_prev(db_path)
    if _present_db(db_path, min_size):
        owl_release = _obo_release_from_head(owl_source) if owl_source else None
        db_release = _ncbitaxon_db_release(db_path)
        if not (owl_release and db_release and owl_release != db_release):
            return DbEnsureResult(True)
        print(
            f"Rebuilding {db_path}: release {db_release} drifted from "
            f"ncbitaxon.owl {owl_release} (single-source realign)..."
        )
    if not _semsql_build_enabled():
        print(f"Skipping NCBITaxon SemSQL build (KG_SEMSQL_BUILD opt-out); using {db_path} as-is")
        return DbEnsureResult(_present_db(db_path, min_size))
    # Checked before decompressing: without semsql there is nothing to build, and
    # unpacking ~2 GB only to then bail out is pure waste (#10).
    if shutil.which("semsql") is None:
        print(f"Warning: `semsql` not on PATH; cannot build {db_path}")
        return DbEnsureResult(_present_db(db_path, min_size))
    if owl_source and not owl_source.exists():
        # semsql needs the plain OWL, but the download ships ncbitaxon.owl.gz and
        # NCBITAXON_SOURCE names the uncompressed path — without this a fresh
        # checkout skips the build and silently falls back to OAK's prebuilt DB,
        # defeating the single-source guarantee (#620).
        archive = owl_source.with_suffix(owl_source.suffix + ".gz")
        if archive.exists():
            print(f"Decompressing {archive} for the NCBITaxon SemSQL build...")
            if not _decompress_atomically(archive, owl_source):
                return DbEnsureResult(_present_db(db_path, min_size))
    if not (owl_source and owl_source.exists()):
        print(f"Warning: cannot build {db_path} — NCBITaxon OWL source {owl_source} is missing")
        return DbEnsureResult(_present_db(db_path, min_size))
    kept = _clear_build_target(db_path, min_size)
    print(
        f"Building {db_path} from {owl_source} via `semsql make`.\n"
        "  NCBITaxon is the heaviest source in the pipeline: expect hours and a\n"
        "  ~13 GB result. Set KG_SEMSQL_BUILD=off to skip and use the prebuilt\n"
        "  OAK cache instead (the version gate will warn about any drift)."
    )
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
        # symlink the user supplied, which _usable_db rejects by design.
        return DbEnsureResult(_restored_db_usable(db_path, min_size, kept))
    except BaseException:  # noqa: BLE001 — KeyboardInterrupt must not strand .prev
        # Ctrl-C during a multi-hour build previously left the DB gone and a
        # 14 GB .prev orphaned. Note this cannot help against SIGKILL or an
        # unhandled SIGTERM, which do not unwind — _clear_build_target's
        # recovery is what covers those.
        _restore_build_target(db_path, kept)
        raise
    if _usable_db(db_path, min_size):
        _discard_kept_target(kept)
        return DbEnsureResult(True, built=True)
    # semsql can exit 0 having produced a short/misplaced file. Restore, then
    # report on what is actually at db_path now — not the pre-restore verdict.
    print(f"Warning: {db_path} is not a complete build; restoring the previous DB")
    _restore_build_target(db_path, kept)
    return DbEnsureResult(_restored_db_usable(db_path, min_size, kept))


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

    if _present_db(go_db_path, _GO_DB_MIN_SIZE):
        # An existing, non-stub go.db is reused — unless it has drifted from the
        # source OWL's release (single-source invariant, fix 2 #604): a refreshed
        # go.owl must rebuild go.db, else the aspect map lags the transform output
        # and MF/CC terms silently fall through to BiologicalProcess. Only rebuild
        # when both release stamps are readable and differ (an unreadable stamp
        # never forces a costly spurious rebuild).
        owl_release = _obo_release_from_head(Path(GO_SOURCE)) if GO_SOURCE else None
        db_release = _go_db_release(go_db_path)
        if not (owl_release and db_release and owl_release != db_release):
            return DbEnsureResult(True)
        print(
            f"Rebuilding {go_db_path}: release {db_release} drifted from "
            f"go.owl {owl_release} (single-source realign)..."
        )
    if not _semsql_build_enabled():
        print(f"Skipping GO SemSQL build (KG_SEMSQL_BUILD opt-out); using {go_db_path} as-is")
        return DbEnsureResult(_present_db(go_db_path, _GO_DB_MIN_SIZE))
    if not (GO_SOURCE and Path(GO_SOURCE).exists()):
        print(f"Warning: cannot build {go_db_path} — GO OWL source {GO_SOURCE} is missing")
        return DbEnsureResult(False)
    if shutil.which("semsql") is None:
        print(f"Warning: `semsql` not on PATH; cannot build {go_db_path}")
        return DbEnsureResult(False)
    kept = _clear_build_target(go_db_path, _GO_DB_MIN_SIZE)
    print(
        f"Building {go_db_path} from {GO_SOURCE} via `semsql make` "
        "(one-time; a full GO SemSQL build runs relation-graph and can take "
        "10-30+ minutes / several GB RAM)..."
    )
    try:
        subprocess.run(  # noqa: S603
            ["semsql", "make", os.path.basename(go_db_path)],  # noqa: S607
            cwd=str(Path(GO_SOURCE).parent),
            check=True,
        )
    except (subprocess.CalledProcessError, OSError) as e:
        print(f"Warning: failed to build {go_db_path}: {e}")
        _restore_build_target(go_db_path, kept)
        # A restored artifact is judged leniently: it may legitimately be a
        # symlink the user supplied, which _usable_db rejects by design.
        return DbEnsureResult(_restored_db_usable(go_db_path, _GO_DB_MIN_SIZE, kept))
    except BaseException:  # noqa: BLE001 — an interrupt must not strand .prev
        _restore_build_target(go_db_path, kept)
        raise
    if _usable_db(go_db_path, _GO_DB_MIN_SIZE):
        _discard_kept_target(kept)
        return DbEnsureResult(True, built=True)
    print(f"Warning: {go_db_path} is not a complete build; restoring the previous DB")
    _restore_build_target(go_db_path, kept)
    return DbEnsureResult(_restored_db_usable(go_db_path, _GO_DB_MIN_SIZE, kept))


def _load_go_namespace_map(go_db_path: str) -> Dict[str, str]:
    """
    Read GO id → OBO namespace from semantic-sql sqlite directly.

    Bypasses OAK's curies converter, which fails to build when the upstream
    GO sqlite contains case-collision prefix rows (e.g. both 'CHR' and 'chr'
    → 'obo/CHR_'). Newer `curies` rejects duplicate URI prefixes strictly,
    so every entity_metadata_map call would otherwise throw and fall through
    to the BiologicalProcess fallback for every GO node.

    Caches both success (the dict) and failure (an empty dict + a flag) so a
    missing / unreadable sqlite file does not retry per call.
    """
    global _GO_NAMESPACE_CACHE, _GO_NAMESPACE_LOAD_FAILED
    if _GO_NAMESPACE_CACHE is not None:
        return _GO_NAMESPACE_CACHE
    if _GO_NAMESPACE_LOAD_FAILED:
        return {}
    # Build go.db from go.owl if it's missing/empty — nothing else does, so a
    # 0-byte stub would otherwise miscategorize every GO term (see _ensure_go_db).
    _ensure_go_db(go_db_path)
    try:
        conn = sqlite3.connect(go_db_path)
        try:
            cur = conn.execute(
                "SELECT subject, value FROM node_to_value_statement "
                "WHERE predicate = 'oio:hasOBONamespace' AND subject LIKE 'GO:%'"
            )
            _GO_NAMESPACE_CACHE = {row[0]: row[1] for row in cur}
        finally:
            conn.close()
        return _GO_NAMESPACE_CACHE
    except Exception as exc:
        print(f"Warning: failed to load GO namespace map from {go_db_path}: {exc}")
        _GO_NAMESPACE_LOAD_FAILED = True
        return {}


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
            chebi_adapter = get_chebi_adapter()
        except ChebiDbUnavailableError as e:
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
