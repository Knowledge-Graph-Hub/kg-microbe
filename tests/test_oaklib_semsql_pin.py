"""
The oaklib pin must keep `sqlite:obo:` off the retired semantic-sql S3 bucket (#962).

INCATools/semantic-sql removed public read from the raw S3 bucket
(semantic-sql#112). oaklib below 0.7.2 resolves `sqlite:obo:` selectors against
it; 0.7.2 moved the default to the CDN. This repo stayed on 0.6.23 — the last
pre-CDN release — long enough for the bucket to start answering 403.

First-party transforms build their SemSQL DBs from the OWL they ship
(``kg_microbe/utils/ontology_utils.py``, the #604 single-source rule), so they
do not hit the bucket themselves. But the pin decides what ``runoak -i
sqlite:obo:...`` and every ad-hoc ``get_adapter("sqlite:obo:...")`` on a
developer's machine resolves to, and an old lock quietly re-points them at a
dead host. The reversion is invisible until a cache miss.

These assert the floor, not the installed version: CI installs from the lock,
and a developer may legitimately be ahead.

Ported from MediaIngredientMech's guard of the same name.
"""

from __future__ import annotations

import re
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib

REPO = Path(__file__).resolve().parent.parent

# 0.7.2 introduced the CDN default. This project caps python at <3.13, so
# 0.7.2's own `<3.14` ceiling is not the reason for 0.7.3 here; 0.7.3 is the
# floor the KG-Microbe Mechs share, and pinning the same number keeps the
# family on one resolution.
#
# This constant is deliberately the DECLARED FLOOR, not the release that first
# carried the CDN. A constant set to 0.7.2 here would still accept a pyproject
# lowered to 0.7.2 and quietly undo the alignment.
MIN_OAKLIB = (0, 7, 3)

S3_HOST = "s3.amazonaws.com"


def _spec() -> str:
    data = tomllib.loads((REPO / "pyproject.toml").read_text())
    return data["tool"]["poetry"]["dependencies"]["oaklib"]


def test_the_pin_floor_keeps_the_cdn_default():
    """The declared floor is at or above the release that moved off the bucket."""
    spec = _spec()
    match = re.search(r">=\s*(\d+)\.(\d+)\.(\d+)", spec)
    assert match, (
        f"no lower bound in {spec!r} — below 0.7.2, `sqlite:obo:` resolves against "
        "the raw S3 bucket semantic-sql retired"
    )
    assert tuple(int(g) for g in match.groups()) >= MIN_OAKLIB, (
        f"{spec!r} is below {'.'.join(map(str, MIN_OAKLIB))}, the floor the KG-Microbe Mechs share"
    )


def test_the_lockfile_agrees_with_the_floor():
    """A floor the lock does not satisfy is a floor in name only."""
    lock = (REPO / "poetry.lock").read_text()
    match = re.search(r'\[\[package\]\]\nname = "oaklib"\nversion = "(\d+)\.(\d+)\.(\d+)"', lock)
    assert match, "oaklib absent from poetry.lock"
    assert tuple(int(g) for g in match.groups()) >= MIN_OAKLIB


def test_the_resolved_default_is_not_the_retired_bucket():
    """
    Pin the property, not a proxy for it.

    The two tests above track a version number, which is what we can control but
    not what we care about. This reads the constant oaklib will actually use, so
    it keeps working if upstream renames or re-defaults it again.
    """
    from oaklib.constants import SEMSQL_SQLITE_URL_BASE

    assert S3_HOST not in SEMSQL_SQLITE_URL_BASE, (
        f"oaklib resolves sqlite:obo: against {SEMSQL_SQLITE_URL_BASE}, the raw S3 "
        "bucket INCATools/semantic-sql retired (semantic-sql#112)"
    )
    assert SEMSQL_SQLITE_URL_BASE.startswith("https://"), SEMSQL_SQLITE_URL_BASE
