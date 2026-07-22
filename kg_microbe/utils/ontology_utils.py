"""Ontology utilities for category assignment and term processing."""

import os
import re
import shutil
import sqlite3
import subprocess
from pathlib import Path
from typing import Dict, Optional

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
# OBO release stamp, e.g. ``releases/2026-05-19/`` in a versionIRI.
_RELEASE_RE = re.compile(r"releases/(\d{4}-\d{2}-\d{2})")


def _obo_release_from_head(path: Path, nbytes: int = 2_000_000) -> Optional[str]:
    """
    Return the ``YYYY-MM-DD`` OBO release stamped near the top of an .owl/.json.

    Both OWL (``versionIRI rdf:resource=".../releases/DATE/..."``) and OBO-JSON
    (``meta`` versionInfo) carry the release near the file head, so a bounded
    read avoids parsing hundreds of MB. Returns None if unreadable / unstamped.
    """
    try:
        with open(path, encoding="utf-8", errors="ignore") as fh:
            head = fh.read(nbytes)
    except OSError:
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


def _version_check_strict(env_var: str, strict: Optional[bool]) -> bool:
    """
    Resolve a version-gate's strictness: explicit arg wins, else the env var.

    Defaults to fail-loud (raise). ``<env_var>=warn`` downgrades to a warning —
    an escape hatch when the release-stamp heuristic disagrees spuriously.
    """
    if strict is not None:
        return strict
    return os.environ.get(env_var, "strict").strip().lower() != "warn"


def assert_go_version_alignment(strict: Optional[bool] = None) -> None:
    """
    Guard that GO's aspect-map source (go.owl→go.db) matches the transform's (go.json).

    The GO transform TSV is built from ``go.json`` while the MF/BP/CC aspect map
    is read from ``go.db`` (built from ``go.owl``). If a ``kg download`` straddles
    a GO release boundary the two diverge and MF/CC terms silently fall through
    to the ``biological_process`` default. Compare the two releases and, on
    mismatch, raise (``strict``) or warn loudly. No-op when either release stamp
    can't be read (e.g. a source is absent), so a missed versionIRI never
    false-alarms — only two readable-but-different stamps trip the gate.

    ``strict`` defaults to fail-loud (raise). Since the verdict rests on a
    release-stamp heuristic, ``KG_GO_VERSION_CHECK=warn`` downgrades to a
    warning — an escape hatch if the stamps ever disagree spuriously.
    """
    from kg_microbe.transform_utils.constants import GO_SOURCE

    strict = _version_check_strict("KG_GO_VERSION_CHECK", strict)
    if not GO_SOURCE:
        return
    owl_release = _obo_release_from_head(Path(GO_SOURCE))
    json_release = _obo_release_from_head(Path(GO_SOURCE).with_suffix(".json"))
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
    missing/unparseable stamp.
    """
    try:
        conn = sqlite3.connect(db_path)
        try:
            row = conn.execute(
                "SELECT value FROM statements WHERE predicate = 'owl:versionInfo' "
                "AND value IS NOT NULL LIMIT 1"
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

    metatraits/lpsn/bacdive do label + lineage lookups against ``ncbitaxon.db``
    (an OAK-fetched prebuilt SemSQL DB whose release is whatever OAK last
    downloaded), while the NCBITaxon transform output is built from
    ``ncbitaxon.owl``. If the two are different releases, lookups can resolve
    against taxa that differ from those emitted by the transform. Compare the
    ``owl:versionInfo`` in ``db_path`` with ``ncbitaxon.owl``'s versionIRI and,
    on mismatch, raise (default) or warn. No-op when either stamp can't be read.

    ``KG_NCBITAXON_VERSION_CHECK=warn`` downgrades the default fail-loud to a
    warning (release-stamp heuristic escape hatch).
    """
    from kg_microbe.transform_utils.constants import NCBITAXON_SOURCE

    strict = _version_check_strict("KG_NCBITAXON_VERSION_CHECK", strict)
    if not NCBITAXON_SOURCE:
        return
    owl_release = _obo_release_from_head(Path(NCBITAXON_SOURCE))
    db_release = _ncbitaxon_db_release(db_path)
    if owl_release and db_release and owl_release != db_release:
        msg = (
            f"NCBITaxon source version mismatch: ncbitaxon.owl={owl_release} vs "
            f"ncbitaxon.db={db_release}. metatraits/lpsn/bacdive look taxa up in "
            "ncbitaxon.db while the transform emits nodes from ncbitaxon.owl; the "
            "two releases must match. Re-download NCBITaxon and refresh the OAK "
            "SemSQL DB so both are the same release "
            "(rm ~/.data/oaklib/ncbitaxon.db; poetry run python -c "
            "'from oaklib import get_adapter; get_adapter(\"sqlite:obo:ncbitaxon\")')."
        )
        if strict:
            raise RuntimeError(msg)
        print(f"WARNING: {msg}")


def _ensure_go_db(go_db_path: str) -> bool:
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

    if os.path.exists(go_db_path) and os.path.getsize(go_db_path) >= _GO_DB_MIN_SIZE:
        return True
    if not (GO_SOURCE and Path(GO_SOURCE).exists()):
        print(f"Warning: cannot build {go_db_path} — GO OWL source {GO_SOURCE} is missing")
        return False
    if shutil.which("semsql") is None:
        print(f"Warning: `semsql` not on PATH; cannot build {go_db_path}")
        return False
    # Remove a truncated/0-byte stub so semsql rebuilds cleanly.
    if os.path.exists(go_db_path):
        os.remove(go_db_path)
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
        return False
    return os.path.exists(go_db_path) and os.path.getsize(go_db_path) >= _GO_DB_MIN_SIZE


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

    # Create adapter if not provided
    if chebi_adapter is None:
        try:
            from oaklib import get_adapter

            from kg_microbe.transform_utils.constants import CHEBI_SOURCE

            chebi_adapter = get_adapter(f"sqlite:{CHEBI_SOURCE}")
        except Exception:
            from oaklib import get_adapter

            chebi_adapter = get_adapter("sqlite:data/raw/chebi.db")

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
