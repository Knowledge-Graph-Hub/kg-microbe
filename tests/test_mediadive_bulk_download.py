"""Tests for mediadive_bulk_download utility."""

import inspect
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from importlib import import_module
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

from kg_microbe.utils.mediadive_bulk_download import (
    CACHE_FILENAME,
    DEFAULT_MAX_WORKERS,
    USER_AGENT,
    _delete_cache,
    _make_session,
    _reset_sessions,
    download_detailed_media,
    download_mediadive_bulk,
    download_medium_strains,
    get_json_from_api,
    setup_cache,
)

# kg_microbe/__init__.py does `from .download import download`, so the name
# kg_microbe.download resolves to the *function*, not the module. Fetch the
# module from sys.modules so patch.object targets the right object.
download_module = import_module("kg_microbe.download")


class TestDefaults:

    """Verify that DEFAULT_MAX_WORKERS and USER_AGENT are sensible values."""

    def test_default_max_workers_is_polite(self):
        """Default worker count should be low enough to be polite to small academic APIs."""
        assert DEFAULT_MAX_WORKERS <= 10, (
            f"DEFAULT_MAX_WORKERS={DEFAULT_MAX_WORKERS} is too aggressive for a small academic API"
        )

    def test_user_agent_identifies_project(self):
        """User-Agent must mention kg-microbe so the API operator can identify us."""
        assert "kg-microbe" in USER_AGENT.lower()

    def test_download_detailed_media_accepts_max_workers(self):
        """download_detailed_media must accept max_workers and pass it through."""
        media_list = [{"id": 1}]
        with patch("kg_microbe.utils.mediadive_bulk_download.get_json_from_api", return_value={"name": "test"}):
            result = download_detailed_media(media_list, max_workers=2)
        assert isinstance(result, dict)

    def test_download_medium_strains_accepts_max_workers(self):
        """download_medium_strains must accept max_workers and pass it through."""
        media_list = [{"id": 1}]
        with patch("kg_microbe.utils.mediadive_bulk_download.get_json_from_api", return_value=[{"strain": "A"}]):
            result = download_medium_strains(media_list, max_workers=2)
        assert isinstance(result, dict)


class TestCacheThreadSafety:

    """
    Verify HTTP sessions are never shared across threads.

    requests_cache's SQLiteDict holds one sqlite3.Connection for all callers and
    takes no lock on reads, so sharing a CachedSession across a ThreadPoolExecutor
    raises "database disk image is malformed" against an intact database. Each
    thread must get its own session, and therefore its own connection.
    """

    def teardown_method(self):
        """Disable caching and drop per-thread sessions between tests."""
        setup_cache(None)

    def test_setup_cache_creates_db_in_given_dir(self, tmp_path):
        """The cache database belongs next to the bulk output, not in the CWD."""
        cache_path = setup_cache(tmp_path)
        assert cache_path == tmp_path / CACHE_FILENAME
        assert cache_path.exists()

    # These assert injectivity (no object seen from two different threads) rather
    # than an exact count. ThreadPoolExecutor spawns workers lazily, so with fast
    # tasks fewer than max_workers threads ever run and `== n_threads` failed
    # ~75% of runs in isolation while passing under a slower full-suite run.
    def test_each_thread_gets_its_own_session(self, tmp_path):
        """_make_session must never hand the same session to two threads."""
        setup_cache(tmp_path)
        n_threads = 5

        def grab(_):
            """Return (thread id, session) for this call."""
            session = _make_session()
            return threading.get_ident(), session

        with ThreadPoolExecutor(max_workers=n_threads) as executor:
            results = list(executor.map(grab, range(n_threads * 20)))

        owners = {}
        for tid, session in results:
            owners.setdefault(id(session), set()).add(tid)
        shared = {sid: tids for sid, tids in owners.items() if len(tids) > 1}
        assert shared == {}, f"sessions shared across threads: {shared}"
        assert len({tid for tid, _ in results}) > 1, "test did not exercise concurrency"
        assert all(s.headers["User-Agent"] == USER_AGENT for _, s in results)

    def test_each_session_has_its_own_sqlite_connection(self, tmp_path):
        """A sqlite3.Connection must never be reached from two threads."""
        setup_cache(tmp_path)
        n_threads = 4

        def open_connection(_):
            """Force this thread's backend to open its connection; return (tid, id)."""
            session = _make_session()
            with session.cache.responses.connection() as con:
                return threading.get_ident(), id(con)

        with ThreadPoolExecutor(max_workers=n_threads) as executor:
            results = list(executor.map(open_connection, range(n_threads * 20)))

        owners = {}
        for tid, con_id in results:
            owners.setdefault(con_id, set()).add(tid)
        shared = {cid: tids for cid, tids in owners.items() if len(tids) > 1}
        assert shared == {}, f"connections shared across threads: {shared}"
        assert len({tid for tid, _ in results}) > 1, "test did not exercise concurrency"

    def test_reset_closes_sessions_from_other_threads(self, tmp_path):
        """Discarded sessions must be closed, not left to garbage collection (#617)."""
        setup_cache(tmp_path)
        closed = []

        def build_and_track(_):
            """Create this thread's session and wrap close() to record the call."""
            session = _make_session()
            original = session.close

            def close():
                """Record that close was called, then really close."""
                closed.append(id(session))
                original()

            session.close = close
            return id(session)

        with ThreadPoolExecutor(max_workers=3) as executor:
            ids = set(executor.map(build_and_track, range(9)))

        _reset_sessions()
        assert set(closed) == ids, "every per-thread session should have been closed"

    def test_repeated_calls_reuse_the_same_thread_session(self, tmp_path):
        """Within one thread, _make_session must be idempotent (no session churn)."""
        setup_cache(tmp_path)
        assert _make_session() is _make_session()

    def test_caching_is_not_installed_globally(self, tmp_path):
        """setup_cache must not monkeypatch requests.Session for the whole process."""
        setup_cache(tmp_path)
        assert type(requests.Session()) is requests.Session
        assert not hasattr(requests.Session(), "cache")

    def test_disabled_cache_yields_plain_sessions(self):
        """With caching off, sessions are plain requests.Session objects."""
        setup_cache(None)
        _reset_sessions()
        assert type(_make_session()) is requests.Session

    def test_existing_cache_is_adopted_when_requested(self, tmp_path, monkeypatch):
        """With migrate_legacy=True, a cache left in the CWD by the old code is reused."""
        cwd = tmp_path / "cwd"
        cwd.mkdir()
        monkeypatch.chdir(cwd)
        legacy = cwd / CACHE_FILENAME
        legacy.write_bytes(b"")

        cache_path = setup_cache(tmp_path / "out", migrate_legacy=True)

        assert cache_path.exists()
        assert not legacy.exists(), "legacy cache should be moved, not left behind"

    def test_clear_discards_cached_responses(self, tmp_path):
        """clear=True must drop cached responses so the API is re-queried."""
        setup_cache(tmp_path)
        session = _make_session()
        session.cache.responses["some-key"] = "cached-value"
        assert len(session.cache.responses) == 1

        setup_cache(tmp_path, clear=True)

        assert len(_make_session().cache.responses) == 0

    def test_clear_removes_wal_sidecar_files(self, tmp_path):
        """
        WAL mode leaves -wal/-shm files behind; clearing must not orphan them.

        Asserts on the state right after _delete_cache. Going through
        setup_cache(clear=True) instead would be vacuous: it calls _make_backend()
        immediately afterwards, which reopens the DB in WAL mode and recreates the
        sidecars, so the assertion passed even with the deletion reverted.
        """
        cache_path = setup_cache(tmp_path)
        for suffix in ("-wal", "-shm"):
            cache_path.with_name(cache_path.name + suffix).write_bytes(b"stale")

        _delete_cache(cache_path)

        assert not cache_path.exists()
        for suffix in ("-wal", "-shm"):
            sidecar = cache_path.with_name(cache_path.name + suffix)
            assert not sidecar.exists(), f"{sidecar.name} survived the clear"

    def test_clear_is_off_by_default(self, tmp_path):
        """Without clear=True, an existing cache survives setup_cache."""
        setup_cache(tmp_path)
        _make_session().cache.responses["keep-me"] = "cached-value"

        setup_cache(tmp_path)

        assert "keep-me" in _make_session().cache.responses

    def test_migration_moves_wal_sidecars(self, tmp_path, monkeypatch):
        """WAL sidecars must travel with the DB, not be orphaned in the CWD (#622)."""
        cwd = tmp_path / "cwd"
        cwd.mkdir()
        monkeypatch.chdir(cwd)
        legacy = cwd / CACHE_FILENAME
        legacy.write_bytes(b"")
        for suffix in ("-wal", "-shm"):
            legacy.with_name(legacy.name + suffix).write_bytes(b"sidecar")

        cache_path = setup_cache(tmp_path / "out", migrate_legacy=True)

        for suffix in ("-wal", "-shm"):
            assert not legacy.with_name(legacy.name + suffix).exists(), f"{suffix} orphaned in CWD"
        assert cache_path.exists()

    def test_cwd_cache_is_untouched_by_default(self, tmp_path, monkeypatch):
        """
        setup_cache must not move files outside cache_dir unless asked.

        Regression guard: an unconditional migration meant any setup_cache call —
        including from a test suite — would relocate a real cache sitting in the CWD.
        """
        cwd = tmp_path / "cwd"
        cwd.mkdir()
        monkeypatch.chdir(cwd)
        bystander = cwd / CACHE_FILENAME
        bystander.write_bytes(b"do not move me")

        setup_cache(tmp_path / "out")

        assert bystander.exists(), "default setup_cache must not touch the CWD"
        assert bystander.read_bytes() == b"do not move me"


class TestBulkDownloadEndToEnd:

    """
    Exercise download_mediadive_bulk against a local HTTP server.

    The rest of the suite mocks at or above download_mediadive_bulk, so the
    behaviour that actually matters — cache warm/cold, --ignore-cache really
    re-fetching, sessions torn down — was verifiable only by hand. Mutating
    `clear=ignore_cache` to `clear=False` left the whole suite green (#630).
    """

    @staticmethod
    def _serve(hits):
        """Start a local HTTP server that answers every MediaDive path, counting hits."""
        import http.server
        import threading as th

        class Handler(http.server.BaseHTTPRequestHandler):

            """Answer any path with a MediaDive-shaped payload."""

            def do_GET(self):  # noqa: N802 — BaseHTTPRequestHandler's API
                """Return a minimal MediaDive-shaped payload and count the request."""
                hits.append(self.path)
                body = json.dumps({"data": {"id": 1, "solutions": []}}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                """Silence the default stderr logging."""

        server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        th.Thread(target=server.serve_forever, daemon=True).start()
        return server

    @pytest.fixture
    def runner(self, tmp_path, monkeypatch):
        """
        Yield a callable that runs the bulk download against one local server.

        The server must outlive every run in a test: a fresh port would change the
        request URLs, and the HTTP cache is keyed by URL — so a second run would
        "miss" for the wrong reason and the test would prove nothing.
        """
        hits = []
        server = self._serve(hits)
        monkeypatch.setattr(
            "kg_microbe.utils.mediadive_bulk_download.MEDIADIVE_REST_API_BASE_URL",
            f"http://127.0.0.1:{server.server_port}/",
        )
        basic = tmp_path / "mediadive.json"
        basic.write_text(json.dumps({"data": [{"id": i} for i in range(5)]}))
        out = tmp_path / "mediadive"

        def run(*, ignore_cache=False):
            """Run once; return how many requests reached the server."""
            hits.clear()
            download_mediadive_bulk(str(basic), str(out), ignore_cache=ignore_cache)
            return len(hits)

        try:
            yield run
        finally:
            server.shutdown()

    def test_second_run_is_served_from_cache(self, runner):
        """A warm HTTP cache means no network on the second run."""
        first = runner()
        assert first > 0, "the first run must actually fetch"
        assert runner() == 0, "the second run must hit the cache"

    def test_ignore_cache_really_refetches(self, runner):
        """--ignore-cache must clear the response cache, not just rebuild the JSON."""
        first = runner()
        assert runner() == 0, "cache should be warm"
        assert runner(ignore_cache=True) == first, "--ignore-cache must re-fetch everything"

    def test_sessions_are_torn_down(self, runner):
        """The finally: _reset_sessions() teardown must leave nothing open."""
        from kg_microbe.utils import mediadive_bulk_download as mb

        runner()
        assert mb._live_sessions == [], "every per-thread session should be closed"

    def test_cache_db_lands_beside_the_output(self, runner, tmp_path):
        """The cache belongs in the output dir, not the working directory."""
        runner()
        assert (tmp_path / "mediadive" / CACHE_FILENAME).exists()
        assert not (Path.cwd() / CACHE_FILENAME).exists()


class TestIgnoreCachePlumbing:

    """
    Verify `kg download --ignore-cache` reaches the HTTP response cache.

    Rebuilding the bulk JSON files from a warm HTTP cache reproduces the old
    data byte for byte, so --ignore-cache has to clear that cache too.
    """

    def _write_basic_media(self, tmp_path):
        """Create the mediadive.json that _post_download_mediadive_bulk looks for."""
        (tmp_path / "mediadive.json").write_text('{"data": [{"id": 1}]}')

    def test_ignore_cache_is_forwarded(self, tmp_path):
        """ignore_cache=True must reach download_mediadive_bulk."""
        self._write_basic_media(tmp_path)
        with patch.object(download_module, "download_mediadive_bulk") as mock_bulk:
            download_module._post_download_mediadive_bulk(str(tmp_path), ignore_cache=True)
        assert mock_bulk.call_args.kwargs["ignore_cache"] is True

    def test_default_leaves_cache_intact(self, tmp_path):
        """Without --ignore-cache, cached HTTP responses must be reused."""
        self._write_basic_media(tmp_path)
        with patch.object(download_module, "download_mediadive_bulk") as mock_bulk:
            download_module._post_download_mediadive_bulk(str(tmp_path))
        assert mock_bulk.call_args.kwargs["ignore_cache"] is False

    def test_bulk_download_accepts_ignore_cache(self):
        """download_mediadive_bulk must expose ignore_cache for the CLI to pass."""
        assert "ignore_cache" in inspect.signature(download_mediadive_bulk).parameters


class TestRetryAfter:

    """Verify that 429 responses with Retry-After headers are honoured."""

    def test_respects_retry_after_header(self):
        """On 429, should wait the Retry-After duration before retrying."""
        mock_429 = MagicMock(spec=requests.Response)
        mock_429.status_code = 429
        mock_429.headers = {"Retry-After": "0.05"}

        mock_ok = MagicMock(spec=requests.Response)
        mock_ok.status_code = 200
        mock_ok.json.return_value = {"data": {"id": 1}}

        http_error = requests.exceptions.HTTPError(response=mock_429)

        call_times = []

        def fake_get(url, timeout=30):
            """Simulate a session.get that raises 429 on the first call, then succeeds."""
            call_times.append(time.monotonic())
            if len(call_times) == 1:
                raise http_error
            return mock_ok

        session = MagicMock()
        session.get.side_effect = fake_get

        result = get_json_from_api("http://example.com/test", retry_count=3, retry_delay=5.0, session=session)
        assert result == {"id": 1}
        # Should have waited ~0.05s (the Retry-After value), not 5s (retry_delay)
        assert len(call_times) == 2
        assert call_times[1] - call_times[0] < 1.0, "Should have used Retry-After (0.05s), not retry_delay (5s)"


class TestRetryParameters:

    """Verify retry_count and retry_delay flow from download functions into get_json_from_api."""

    def test_retry_count_is_configurable(self):
        """download_detailed_media should pass custom retry_count through to get_json_from_api."""
        calls = []

        def fake_api(url, retry_count=3, retry_delay=2.0, verbose=False, session=None):
            """Capture retry_count passed through from download_detailed_media."""
            calls.append(retry_count)
            return {}

        media_list = [{"id": 1}]
        with patch("kg_microbe.utils.mediadive_bulk_download.get_json_from_api", side_effect=fake_api):
            download_detailed_media(media_list, max_workers=1, retry_count=7)

        assert all(c == 7 for c in calls), f"Expected retry_count=7, got {calls}"

    def test_retry_delay_is_configurable(self):
        """download_medium_strains should pass custom retry_delay through to get_json_from_api."""
        delays = []

        def fake_api(url, retry_count=3, retry_delay=2.0, verbose=False, session=None):
            """Capture retry_delay passed through from download_medium_strains."""
            delays.append(retry_delay)
            return {}

        media_list = [{"id": 1}]
        with patch("kg_microbe.utils.mediadive_bulk_download.get_json_from_api", side_effect=fake_api):
            download_medium_strains(media_list, max_workers=1, retry_delay=0.5)

        assert all(d == 0.5 for d in delays), f"Expected retry_delay=0.5, got {delays}"


class TestRateLimiter:

    """Verify the Semaphore rate limiter bounds concurrency."""

    def test_concurrency_bounded_by_max_workers(self):
        """Concurrent in-flight requests must never exceed max_workers."""
        max_workers = 3
        active = []
        peak = []
        lock = threading.Lock()

        def fake_api(url, retry_count=3, retry_delay=2.0, verbose=False, session=None):
            """Simulate a slow API call to allow measuring peak concurrency."""
            with lock:
                active.append(1)
                peak.append(len(active))
            time.sleep(0.01)
            with lock:
                active.pop()
            return {"name": "x"}

        media_list = [{"id": i} for i in range(10)]
        with patch("kg_microbe.utils.mediadive_bulk_download.get_json_from_api", side_effect=fake_api):
            download_detailed_media(media_list, max_workers=max_workers)

        assert max(peak) <= max_workers, f"Peak concurrency {max(peak)} exceeded max_workers={max_workers}"
