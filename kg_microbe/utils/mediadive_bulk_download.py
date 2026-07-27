"""
MediaDive bulk download utility.

This module provides functionality to download all MediaDive data in bulk
to avoid repeated API calls during transforms.
"""

import json
import logging
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Dict, List, Optional

import requests
from requests_cache import CachedSession
from requests_cache.backends.sqlite import SQLiteCache
from tqdm import tqdm

# Default to 5 workers — still a large speedup over sequential but polite to
# MediaDive, which is a small academic REST API at DSMZ.
DEFAULT_MAX_WORKERS = 5

# Name of the HTTP response cache, stored alongside the bulk output files.
CACHE_FILENAME = "mediadive_bulk_cache.sqlite"

# Milliseconds a thread waits for the SQLite write lock before giving up. Each
# thread holds its own connection, so brief contention on writes is expected.
CACHE_BUSY_TIMEOUT_MS = 30_000

# Descriptive User-Agent so the API operator can identify traffic source.
USER_AGENT = "kg-microbe (Knowledge-Graph-Hub; https://github.com/Knowledge-Graph-Hub/kg-microbe)"

# Set up logging for API warnings (written to file, not stdout)
logger = logging.getLogger(__name__)

# MediaDive REST API base URL
MEDIADIVE_REST_API_BASE_URL = "https://mediadive.dsmz.de/rest/"

# API endpoints
MEDIA_ENDPOINT = "media"
MEDIUM_ENDPOINT = "medium/"
MEDIUM_STRAINS_ENDPOINT = "medium-strains/"  # Note: hyphen, not underscore

# Keys in JSON responses
DATA_KEY = "data"
ID_KEY = "id"
SOLUTIONS_KEY = "solutions"
RECIPE_KEY = "recipe"
COMPOUND_KEY = "compound"
COMPOUND_ID_KEY = "compound_id"
SOLUTION_ID_KEY = "solution_id"


# Per-thread HTTP sessions.
#
# requests_cache's SQLiteDict keeps a *single* sqlite3.Connection shared by every
# caller (backends/sqlite.py: `self._connection`, opened with
# check_same_thread=False) and deliberately takes no lock on reads:
#
#     # Read operations can be run in parallel (no lock or COMMIT)
#     else:
#         yield self._connection
#
# Driving one CachedSession from a ThreadPoolExecutor therefore runs concurrent
# execute() calls on one connection, which tramples its internal pager state and
# makes SQLite raise "database disk image is malformed" against a perfectly
# intact file. Giving each thread its own CachedSession gives each thread its own
# connection; multiple connections to one SQLite file is supported usage, and the
# cached responses are still shared because they live in the same database.
#
# The previous implementation used requests_cache.install_cache(), which
# monkeypatches requests.Session globally — every session in the process became a
# CachedSession as a side effect. Caching is now explicit and scoped to this
# module.
_thread_local = threading.local()

# Every session handed out, so _reset_sessions can close them. A thread-local
# alone is not enough: one thread cannot reach another's sessions to close them.
_live_sessions: List[requests.Session] = []
_sessions_lock = threading.Lock()

# Set by setup_cache(); None means "no HTTP caching" (plain sessions).
_cache_path: Optional[Path] = None


def setup_cache(
    cache_dir: Optional[Path] = None,
    migrate_legacy: bool = False,
    clear: bool = False,
) -> Optional[Path]:
    """
    Enable HTTP caching for subsequent sessions created by this module.

    Args:
    ----
        cache_dir: Directory to hold the cache database. If None, caching is
            disabled and plain (uncached) sessions are used.
        migrate_legacy: If True, adopt a cache database left in the current
            working directory by older versions of this module (which stored it
            there). Off by default: this *moves* a file outside cache_dir, so
            only the real download entry point should ask for it.
        clear: If True, discard any existing cached responses so every request
            goes back to the API. This is what `kg download --ignore-cache`
            needs; without it the bulk JSON files are rebuilt from cached HTTP
            responses and never actually refresh.

    Returns:
    -------
        Path to the cache database, or None if caching was disabled.

    """
    global _cache_path

    # Drop any sessions built against a previously configured cache.
    _reset_sessions()

    if cache_dir is None:
        _cache_path = None
        return None

    cache_dir.mkdir(parents=True, exist_ok=True)
    _cache_path = cache_dir / CACHE_FILENAME
    # Adopt the legacy cache before clearing, so a stale copy can't linger in
    # the CWD and get picked up by a later run that isn't clearing.
    if migrate_legacy:
        _migrate_legacy_cache(_cache_path)
    if clear:
        _delete_cache(_cache_path)

    # Create the tables up front so worker threads don't race on the initial
    # CREATE TABLE when they open their own connections. Closed immediately —
    # SQLiteDict opens its connection eagerly in __init__, so an unreferenced
    # backend would leave two connections open on a file a later clear() unlinks.
    warmup = _make_backend()
    warmup.close()
    print(f"HTTP cache enabled: {_cache_path}")
    return _cache_path


def _delete_cache(cache_path: Path) -> None:
    """Remove a cache database and its WAL sidecar files, if present."""
    removed = False
    for path in (cache_path, *(cache_path.with_name(cache_path.name + s) for s in ("-wal", "-shm"))):
        if path.exists():
            path.unlink()
            removed = True
    if removed:
        print(f"Cleared HTTP cache: {cache_path}")


def _migrate_legacy_cache(cache_path: Path) -> None:
    """
    Move a cache database left in the working directory to its new home.

    Older versions called requests_cache.install_cache(), which put the database
    in the CWD (normally the repo root). Adopting it avoids re-downloading
    thousands of already-cached MediaDive responses.
    """
    legacy_path = Path.cwd() / CACHE_FILENAME
    if cache_path.exists() or not legacy_path.exists() or legacy_path.resolve() == cache_path.resolve():
        return
    try:
        shutil.move(str(legacy_path), str(cache_path))
    except OSError as e:
        # Adopting the old cache is an optimisation; failing it (e.g. EXDEV when
        # data/ is on another filesystem) must not abort the whole download.
        print(f"Could not adopt {legacy_path} ({e}); continuing with a fresh cache")
        return
    # Move the WAL sidecars too. A cache this module created is WAL-enabled, so
    # leaving them behind would drop uncheckpointed responses and orphan the
    # files in the working directory (#622).
    for suffix in ("-wal", "-shm"):
        sidecar = legacy_path.with_name(legacy_path.name + suffix)
        if sidecar.exists():
            try:
                shutil.move(str(sidecar), str(cache_path.with_name(cache_path.name + suffix)))
            except OSError as e:
                print(f"Could not move {sidecar.name} ({e}); it can be deleted safely")
    print(f"Adopted existing HTTP cache: {legacy_path} -> {cache_path}")


def _make_backend() -> SQLiteCache:
    """Build a SQLiteCache backed by the configured cache path."""
    # WAL keeps readers from blocking writers across the worker threads, and
    # busy_timeout makes a thread wait for the write lock instead of failing.
    return SQLiteCache(str(_cache_path), wal=True, busy_timeout=CACHE_BUSY_TIMEOUT_MS)


def _reset_sessions() -> None:
    """
    Close and discard cached per-thread sessions (used by setup_cache and tests).

    Rebinding rather than clearing an attribute is deliberate: it makes *every*
    thread see a fresh local, which is what a cache reconfiguration needs. The
    sessions themselves must be closed explicitly, or each one's SQLite
    connection lingers until garbage collection (#617).
    """
    global _thread_local
    with _sessions_lock:
        for session in _live_sessions:
            try:
                session.close()
            except Exception as e:  # noqa: BLE001 — teardown must not mask the real work
                logger.debug(f"Ignoring error while closing a cached session: {e}")
        _live_sessions.clear()
    _thread_local = threading.local()


def _make_session() -> requests.Session:
    """
    Return this thread's HTTP session, creating it on first use.

    Must be called from the thread that will use the session — see the module
    comment above on why sessions are never shared across threads.
    """
    session = getattr(_thread_local, "session", None)
    if session is None:
        session = CachedSession(backend=_make_backend()) if _cache_path else requests.Session()
        session.headers.update({"User-Agent": USER_AGENT})
        _thread_local.session = session
        with _sessions_lock:
            _live_sessions.append(session)
    return session


def get_json_from_api(
    url: str,
    retry_count: int = 3,
    retry_delay: float = 2.0,
    verbose: bool = False,
    session: Optional[requests.Session] = None,
) -> Dict:
    """
    Get JSON data from MediaDive API with retry logic.

    Respects Retry-After headers on 429 responses.

    Args:
    ----
        url: Full API URL to fetch
        retry_count: Number of retries on failure
        retry_delay: Delay in seconds between retries (overridden by Retry-After on 429)
        verbose: If True, log empty responses (useful for debugging)
        session: Optional requests Session to reuse (uses this thread's session if None)

    Returns:
    -------
        Dictionary with API response data (empty dict on failure or empty response)

    """
    requester = session or _make_session()
    for attempt in range(retry_count):
        try:
            r = requester.get(url, timeout=30)
            r.raise_for_status()
            data_json = r.json()
            result = data_json.get(DATA_KEY, {})
            # Distinguish empty API response from failure (for debugging)
            if not result and verbose:
                print(f"  Empty response from API: {url}")
            return result
        except requests.exceptions.HTTPError as e:
            if e.response is not None and e.response.status_code == 429:
                wait = float(e.response.headers.get("Retry-After", retry_delay))
                logger.debug(f"429 Too Many Requests — waiting {wait}s (URL: {url})")
                time.sleep(wait)
                continue
            if attempt < retry_count - 1:
                logger.debug(f"Retry {attempt + 1}/{retry_count} after error: {e} (URL: {url})")
                time.sleep(retry_delay)
            else:
                logger.warning(f"Request failed after {retry_count} attempts: {e} (URL: {url})")
                return {}
        except requests.exceptions.RequestException as e:
            if attempt < retry_count - 1:
                logger.debug(f"Retry {attempt + 1}/{retry_count} after error: {e} (URL: {url})")
                time.sleep(retry_delay)
            else:
                # Log to file instead of stdout - 404s are expected for media without strains
                logger.warning(f"Request failed after {retry_count} attempts: {e} (URL: {url})")
                return {}


def load_basic_media_list(basic_file: str) -> List[Dict]:
    """
    Load basic media list from already downloaded file.

    Args:
    ----
        basic_file: Path to mediadive.json file

    Returns:
    -------
        List of media records with basic info

    """
    print(f"Loading basic media list from {basic_file}")
    with open(basic_file) as f:
        data = json.load(f)
        media_list = data.get(DATA_KEY, [])
        print(f"Found {len(media_list)} media records")
        return media_list


def _fetch_medium_detail(
    medium: Dict,
    session: requests.Session,
    rate_limiter: threading.Semaphore,
    retry_count: int,
    retry_delay: float,
) -> tuple[str, dict]:
    """Fetch detailed recipe for a single medium. Returns (medium_id, data)."""
    medium_id = str(medium.get(ID_KEY))
    url = MEDIADIVE_REST_API_BASE_URL + MEDIUM_ENDPOINT + medium_id
    with rate_limiter:
        return medium_id, get_json_from_api(url, retry_count=retry_count, retry_delay=retry_delay, session=session)


def _fetch_medium_strains(
    medium: Dict,
    session: requests.Session,
    rate_limiter: threading.Semaphore,
    retry_count: int,
    retry_delay: float,
) -> tuple[str, dict]:
    """Fetch strain associations for a single medium. Returns (medium_id, data)."""
    medium_id = str(medium.get(ID_KEY))
    url = MEDIADIVE_REST_API_BASE_URL + MEDIUM_STRAINS_ENDPOINT + medium_id
    with rate_limiter:
        return medium_id, get_json_from_api(url, retry_count=retry_count, retry_delay=retry_delay, session=session)


def download_detailed_media(
    media_list: List[Dict],
    max_workers: int = DEFAULT_MAX_WORKERS,
    retry_count: int = 3,
    retry_delay: float = 2.0,
    requests_per_second: float = 10.0,
) -> Dict[str, Dict]:
    """
    Download detailed recipe information for all media.

    Args:
    ----
        media_list: List of basic media records
        max_workers: Number of parallel download threads
        retry_count: Number of retries on request failure
        retry_delay: Seconds between retries (overridden by Retry-After on 429)
        requests_per_second: Maximum sustained request rate (smooths bursts)

    Returns:
    -------
        Dictionary mapping medium_id -> detailed_recipe_data

    """
    print(f"\nDownloading detailed recipes for {len(media_list)} media...")
    detailed_data: Dict[str, Dict] = {}
    rate_limiter = threading.Semaphore(max_workers)

    def fetch(medium: Dict) -> tuple[str, dict]:
        """Fetch detail for a single medium using this thread's session and the rate limiter."""
        # _make_session() runs inside the worker thread so each thread gets its own.
        return _fetch_medium_detail(medium, _make_session(), rate_limiter, retry_count, retry_delay)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        for medium_id, data in tqdm(
            executor.map(fetch, media_list),
            total=len(media_list),
            desc="Downloading medium details",
        ):
            if data:
                detailed_data[medium_id] = data

    print(f"Downloaded {len(detailed_data)} detailed medium recipes")
    return detailed_data


def download_medium_strains(
    media_list: List[Dict],
    max_workers: int = DEFAULT_MAX_WORKERS,
    retry_count: int = 3,
    retry_delay: float = 2.0,
    requests_per_second: float = 10.0,
) -> Dict[str, List]:
    """
    Download strain associations for all media.

    Args:
    ----
        media_list: List of basic media records
        max_workers: Number of parallel download threads
        retry_count: Number of retries on request failure
        retry_delay: Seconds between retries (overridden by Retry-After on 429)
        requests_per_second: Maximum sustained request rate (smooths bursts)

    Returns:
    -------
        Dictionary mapping medium_id -> list_of_strain_data

    """
    print(f"\nDownloading strain associations for {len(media_list)} media...")
    strain_data: Dict[str, List] = {}
    rate_limiter = threading.Semaphore(max_workers)

    def fetch(medium: Dict) -> tuple[str, dict]:
        """Fetch strain associations for a single medium using this thread's session."""
        # _make_session() runs inside the worker thread so each thread gets its own.
        return _fetch_medium_strains(medium, _make_session(), rate_limiter, retry_count, retry_delay)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        for medium_id, data in tqdm(
            executor.map(fetch, media_list),
            total=len(media_list),
            desc="Downloading medium-strain associations",
        ):
            if data:
                strain_data[medium_id] = data

    # Count total strain associations, handling different data types
    total_strains = 0
    for medium_id, v in strain_data.items():
        if isinstance(v, list):
            total_strains += len(v)
        elif isinstance(v, dict):
            total_strains += len(v)
        else:
            print(f"Warning: Unexpected strain data type for medium {medium_id}: {type(v).__name__}")

    print(f"Downloaded strain associations for {len(strain_data)} media ({total_strains} total associations)")
    return strain_data


def extract_solutions_from_media(detailed_media: Dict[str, Dict]) -> Dict[str, Dict]:
    """
    Extract solution data from embedded structure in detailed_media.

    Instead of making API calls, extract solutions directly from media_detailed.json.

    Args:
    ----
        detailed_media: Dictionary of detailed medium recipes

    Returns:
    -------
        Dictionary mapping solution_id -> solution_data

    """
    solutions_data = {}

    for medium_data in detailed_media.values():
        if SOLUTIONS_KEY in medium_data and isinstance(medium_data[SOLUTIONS_KEY], list):
            for solution in medium_data[SOLUTIONS_KEY]:
                if isinstance(solution, dict) and ID_KEY in solution:
                    sol_id = str(solution[ID_KEY])
                    # Only add if not already present (avoid duplicates)
                    if sol_id not in solutions_data:
                        solutions_data[sol_id] = solution

    return solutions_data


def extract_compounds_from_media(detailed_media: Dict[str, Dict]) -> Dict[str, Dict]:
    """
    Extract compound data from embedded structure in detailed_media.

    Instead of making API calls, extract compound info directly from media_detailed.json.

    Args:
    ----
        detailed_media: Dictionary of detailed medium recipes

    Returns:
    -------
        Dictionary mapping compound_id -> compound_data

    """
    compounds_data = {}

    for medium_data in detailed_media.values():
        if SOLUTIONS_KEY in medium_data and isinstance(medium_data[SOLUTIONS_KEY], list):
            for solution in medium_data[SOLUTIONS_KEY]:
                if isinstance(solution, dict) and RECIPE_KEY in solution:
                    recipe = solution[RECIPE_KEY]
                    if isinstance(recipe, list):
                        for ingredient in recipe:
                            if isinstance(ingredient, dict) and COMPOUND_ID_KEY in ingredient:
                                comp_id = str(ingredient[COMPOUND_ID_KEY])
                                # Only add if not already present (avoid duplicates)
                                if comp_id not in compounds_data:
                                    # Store the ingredient data (has compound, compound_id, etc.)
                                    compounds_data[comp_id] = ingredient

    return compounds_data


def save_json_file(data: Dict, filepath: Path, description: str):
    """Save data to JSON file with logging."""
    filepath.parent.mkdir(parents=True, exist_ok=True)
    with open(filepath, "w") as f:
        json.dump(data, f, indent=2)
    file_size_mb = filepath.stat().st_size / (1024 * 1024)
    print(f"Saved {description} to {filepath} ({file_size_mb:.2f} MB)")


def download_mediadive_bulk(
    basic_file: str,
    output_dir: str,
    max_workers: int = DEFAULT_MAX_WORKERS,
    retry_count: int = 3,
    retry_delay: float = 2.0,
    ignore_cache: bool = False,
):
    """
    Download all MediaDive data in bulk.

    This is the main entry point called from kg_microbe.download.

    Args:
    ----
        basic_file: Path to mediadive.json (basic media list)
        output_dir: Directory to save bulk data files
        max_workers: Number of parallel download threads (default: 5, polite for small APIs)
        retry_count: Number of retries on request failure
        retry_delay: Seconds between retries (overridden by Retry-After on 429)
        ignore_cache: If True, discard cached HTTP responses and re-fetch from
            the API. Rebuilding the bulk files from a warm cache would otherwise
            reproduce the old data byte for byte.

    """
    output_path = Path(output_dir)

    # Create output directory
    output_path.mkdir(parents=True, exist_ok=True)

    # Set up file logging for API warnings (not printed to stdout)
    log_file = output_path / "mediadive_download.log"
    file_handler = logging.FileHandler(log_file, mode="w")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
    logger.addHandler(file_handler)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False  # Prevent propagation to root logger and stdout
    print(f"API warnings will be logged to: {log_file}")
    print(f"Using {max_workers} parallel workers")

    # Set up HTTP caching (stored alongside the bulk output, not in the CWD)
    setup_cache(output_path, migrate_legacy=True, clear=ignore_cache)

    # Wrapped so an interrupted or failing run still closes its sessions:
    # otherwise every per-thread SQLite connection stays open, which is exactly
    # the case where a stale handle on a cache file matters most.
    try:
        # Step 1: Load basic media list
        print("\n[1/5] Loading basic media list...")
        media_list = load_basic_media_list(basic_file)

        # Step 2: Download detailed medium recipes
        print("\n[2/5] Downloading detailed medium recipes...")
        detailed_media = download_detailed_media(
            media_list, max_workers=max_workers, retry_count=retry_count, retry_delay=retry_delay
        )
        save_json_file(detailed_media, output_path / "media_detailed.json", "detailed media recipes")

        # Step 3: Download medium-strain associations
        print("\n[3/5] Downloading medium-strain associations...")
        media_strains = download_medium_strains(
            media_list, max_workers=max_workers, retry_count=retry_count, retry_delay=retry_delay
        )
        save_json_file(media_strains, output_path / "media_strains.json", "medium-strain associations")

        # Step 4: Extract solutions from embedded structure
        print("\n[4/5] Extracting solutions from embedded structure...")
        solutions_data = extract_solutions_from_media(detailed_media)
        print(f"Extracted {len(solutions_data)} unique solutions from embedded data")
        save_json_file(solutions_data, output_path / "solutions.json", "solution data")

        # Step 5: Extract compounds from embedded structure
        # Compound data is embedded in the recipe structure of detailed media
        # The transform will use MicroMediaParam mappings and fall back to mediadive.ingredient: prefix
        print("\n[5/5] Extracting compounds from embedded structure...")
        compounds_data = extract_compounds_from_media(detailed_media)
        print(f"Extracted {len(compounds_data)} compounds from embedded data")
        save_json_file(compounds_data, output_path / "compounds.json", "compound data")

        # Summary
        print("\n" + "=" * 80)
        print("MediaDive bulk download summary:")
        print("=" * 80)
        print(f"Output directory: {output_path}")
        print(f"  - {len(media_list)} media records (basic)")
        print(f"  - {len(detailed_media)} media recipes (detailed)")
        print(f"  - {len(media_strains)} media-strain associations")
        print(f"  - {len(solutions_data)} solutions")
        print(f"  - {len(compounds_data)} compounds")
        print(f"\nAPI warnings logged to: {output_path / 'mediadive_download.log'}")
        print("These files will be used by the MediaDive transform to avoid API calls.")

    finally:
        # Close every per-thread session; the worker threads are gone but
        # _live_sessions still holds their connections open.
        _reset_sessions()

    print("=" * 80)
