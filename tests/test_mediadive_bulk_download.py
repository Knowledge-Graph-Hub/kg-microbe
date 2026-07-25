"""Tests for mediadive_bulk_download utility."""

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock, patch

import requests

from kg_microbe.utils.mediadive_bulk_download import (
    CACHE_FILENAME,
    DEFAULT_MAX_WORKERS,
    USER_AGENT,
    _make_session,
    _reset_sessions,
    download_detailed_media,
    download_medium_strains,
    get_json_from_api,
    setup_cache,
)


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

    def test_each_thread_gets_its_own_session(self, tmp_path):
        """_make_session must return a distinct session per calling thread."""
        setup_cache(tmp_path)
        n_threads = 5

        def grab(_):
            """Return this thread's session object."""
            return _make_session()

        with ThreadPoolExecutor(max_workers=n_threads) as executor:
            sessions = list(executor.map(grab, range(n_threads * 4)))

        by_thread = {id(s) for s in sessions}
        assert len(by_thread) == n_threads, "sessions must not be shared between threads"
        assert all(s.headers["User-Agent"] == USER_AGENT for s in sessions)

    def test_each_session_has_its_own_sqlite_connection(self, tmp_path):
        """Distinct sessions must not end up sharing one sqlite3.Connection."""
        setup_cache(tmp_path)
        n_threads = 4

        def open_connection(_):
            """Force this thread's backend to open its connection, and return it."""
            session = _make_session()
            with session.cache.responses.connection() as con:
                return id(con)

        with ThreadPoolExecutor(max_workers=n_threads) as executor:
            connection_ids = set(executor.map(open_connection, range(n_threads * 4)))

        assert len(connection_ids) == n_threads

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
