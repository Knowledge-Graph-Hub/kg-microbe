"""
Regression tests for the MediaDive stale-cache guard.

``data/transformed/mediadive/edges.tsv`` was once produced by a transform
launched while ``kg download`` was still fetching ``data/raw/mediadive/``.
With the bulk JSONs absent, medium lookups fell back to the YAML cache under
``tmp/medium_yaml`` (files dated 2023) and compound lookups to
``requests_cache``, which is installed with no expiry. The run exited 0 and
emitted a graph built from superseded recipes: MediaDive has since inserted
wrapper solutions, so e.g. ``solution:1878`` linked straight to ``1885``
instead of to the wrapper ``6570`` that now holds it, and ``1885`` was
labelled "Solution F" rather than "Ferrous chloride solution (5.2%)".

The guard turns that silent degradation into a refusal at ``run()`` — the
point where the stale artifact would be written — while leaving construction
cheap so unrelated tests can still instantiate the transform.
"""

import pytest

from kg_microbe.transform_utils.mediadive.mediadive import MediaDiveTransform


def _bare_transform(tmp_path, using_bulk_data: bool) -> MediaDiveTransform:
    """
    Return a MediaDiveTransform with only the fields the guard reads.

    ``__init__`` is skipped: it installs the HTTP cache and loads the ChEBI
    category table, neither of which the guard touches.
    """
    transform = MediaDiveTransform.__new__(MediaDiveTransform)
    transform.using_bulk_data = using_bulk_data
    transform.bulk_data_dir = tmp_path / "mediadive"
    return transform


def test_missing_bulk_data_refuses_to_run(tmp_path, monkeypatch):
    """Absent bulk data must raise rather than fall through to the undated caches."""
    monkeypatch.delenv("KG_MEDIADIVE_ALLOW_STALE_CACHE", raising=False)
    transform = _bare_transform(tmp_path, using_bulk_data=False)
    with pytest.raises(FileNotFoundError) as excinfo:
        transform._assert_bulk_data_available()
    message = str(excinfo.value)
    # The message has to name the remedy; this failure is most likely to be hit
    # by someone who started the transform before the download finished.
    assert "kg download" in message
    assert "KG_MEDIADIVE_ALLOW_STALE_CACHE" in message


def test_bulk_data_present_is_a_no_op(tmp_path, monkeypatch):
    """The normal path must not raise."""
    monkeypatch.delenv("KG_MEDIADIVE_ALLOW_STALE_CACHE", raising=False)
    transform = _bare_transform(tmp_path, using_bulk_data=True)
    transform._assert_bulk_data_available()


@pytest.mark.parametrize("value", ["true", "TRUE", "1", "yes"])
def test_explicit_opt_out_allows_cache_only_run(tmp_path, monkeypatch, capsys, value):
    """An explicit opt-out proceeds, but must say so on stdout."""
    monkeypatch.setenv("KG_MEDIADIVE_ALLOW_STALE_CACHE", value)
    transform = _bare_transform(tmp_path, using_bulk_data=False)
    transform._assert_bulk_data_available()
    assert "WARNING" in capsys.readouterr().out


def test_unrelated_env_value_still_refuses(tmp_path, monkeypatch):
    """Only the documented truthy values count as an opt-out."""
    monkeypatch.setenv("KG_MEDIADIVE_ALLOW_STALE_CACHE", "maybe")
    transform = _bare_transform(tmp_path, using_bulk_data=False)
    with pytest.raises(FileNotFoundError):
        transform._assert_bulk_data_available()


def test_run_invokes_the_guard(tmp_path, monkeypatch):
    """
    ``run()`` must call the guard, not merely define it.

    Asserting only on ``_assert_bulk_data_available`` in isolation leaves
    the wiring untested — deleting the call from ``run()`` would keep every
    other test in this file green while restoring the silent-stale-output
    behaviour this guard exists to prevent. The guard also has to fire
    before ``run()`` touches any input path, so this must raise
    ``FileNotFoundError`` from the guard rather than from a missing
    ``mediadive.json``.
    """
    monkeypatch.delenv("KG_MEDIADIVE_ALLOW_STALE_CACHE", raising=False)
    transform = _bare_transform(tmp_path, using_bulk_data=False)
    with pytest.raises(FileNotFoundError) as excinfo:
        transform.run()
    assert "KG_MEDIADIVE_ALLOW_STALE_CACHE" in str(excinfo.value)
