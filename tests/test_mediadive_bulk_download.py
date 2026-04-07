"""Tests for mediadive_bulk_download utility."""

import threading
import time
from unittest.mock import MagicMock, patch

import pytest
import requests

from kg_microbe.utils.mediadive_bulk_download import (
    DEFAULT_MAX_WORKERS,
    USER_AGENT,
    _fetch_medium_detail,
    _fetch_medium_strains,
    download_detailed_media,
    download_medium_strains,
    get_json_from_api,
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
