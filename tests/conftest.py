"""
Shared pytest fixtures for kg-microbe.

Currently provides one autouse session fixture that ensures
``data/raw/metpo.json`` is present before any metatraits test runs. The
metatraits transform's discrete-trait pathway depends on METPO label/synonym
lookups loaded from this file (see ``MetaTraitsTransform._load_metpo_lookups``).
On a fresh clone or in CI, ``data/raw/metpo.json`` is not committed — it is a
``download.yaml`` artifact normally produced by ``poetry run kg download``.
This fixture fetches the file once per test session into ``data/raw/`` so the
tests don't fail with a misleading "METPO JSON not found" warning.

Production transform code intentionally does NOT do this fallback — the
network fetch lives in test setup so production runs without ``data/raw/
metpo.json`` fail loudly with a clear missing-prerequisite error rather than
silently making external HTTP requests at transform time. (Copilot review
finding #558: production transforms should not reach external services.)
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
RAW_DATA_DIR = REPO_ROOT / "data" / "raw"
METPO_JSON_PATH = RAW_DATA_DIR / "metpo.json"
METPO_JSON_URL = "https://raw.githubusercontent.com/berkeleybop/metpo/main/metpo.json"


@pytest.fixture(scope="session", autouse=True)
def ensure_metpo_json_for_tests():
    """
    Download metpo.json into ``data/raw/`` once per session if missing.

    Honors a ``KG_MICROBE_TESTS_NO_NETWORK`` environment variable: set it to a
    truthy value to disable the fetch (the metatraits trait-resolution tests
    will then skip / xfail naturally on the missing-data warning instead).
    """
    if METPO_JSON_PATH.exists():
        return  # already present — fast path

    if os.environ.get("KG_MICROBE_TESTS_NO_NETWORK"):
        return  # opt-out for fully-offline test runs

    try:
        import requests

        response = requests.get(METPO_JSON_URL, timeout=60)
        response.raise_for_status()
        RAW_DATA_DIR.mkdir(parents=True, exist_ok=True)
        METPO_JSON_PATH.write_bytes(response.content)
    except Exception:
        # Silently leave the file absent; tests that depend on METPO lookups
        # will then surface their own clearer skip/failure messages.
        return
