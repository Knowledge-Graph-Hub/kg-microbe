"""A changed pin must take effect on the next ordinary download (#911)."""

import json

import yaml

from kg_microbe.utils.download_manifest import (
    MANIFEST_NAME,
    drop_stale,
    manifest_path,
    read_manifest,
    record,
    stale_by_url,
)

URL_A = "https://example.org/refs/tags/2026-03-24/thing.json"
URL_B = "https://example.org/refs/tags/2026-06-12/thing.json"


def _config(tmp_path, entries):
    path = tmp_path / "download.yaml"
    path.write_text(yaml.safe_dump(entries, sort_keys=False), encoding="utf-8")
    return str(path)


def _artifact(tmp_path, name, text="payload"):
    (tmp_path / name).write_text(text, encoding="utf-8")
    return tmp_path / name


def test_an_unrecorded_artifact_is_never_treated_as_stale(tmp_path):
    """
    Unknown provenance is not wrong provenance.

    Every artifact predates this manifest, so treating "no record" as "stale"
    would re-fetch the whole corpus on the first run — including an hour of
    MediaDive crawling — to learn what is already on disk.
    """
    config = _config(tmp_path, [{"url": URL_A, "local_name": "thing.json", "tag": "t"}])
    _artifact(tmp_path, "thing.json")
    assert stale_by_url(config, str(tmp_path)) == []


def test_a_changed_url_makes_the_artifact_stale(tmp_path):
    """The whole point: the declared pin moved, so the cached bytes are wrong."""
    config = _config(tmp_path, [{"url": URL_A, "local_name": "thing.json", "tag": "t"}])
    _artifact(tmp_path, "thing.json")
    record(config, str(tmp_path))
    moved = _config(tmp_path, [{"url": URL_B, "local_name": "thing.json", "tag": "t"}])
    assert [p.name for p in stale_by_url(moved, str(tmp_path))] == ["thing.json"]


def test_an_unchanged_url_leaves_the_artifact_alone(tmp_path):
    """Re-downloading what already matches would undo the cache entirely."""
    config = _config(tmp_path, [{"url": URL_A, "local_name": "thing.json", "tag": "t"}])
    _artifact(tmp_path, "thing.json")
    record(config, str(tmp_path))
    assert stale_by_url(config, str(tmp_path)) == []


def test_dropping_stale_removes_only_the_moved_artifact(tmp_path):
    """A pin change must not invalidate its neighbours."""
    entries = [
        {"url": URL_A, "local_name": "moved.json", "tag": "t"},
        {"url": URL_A, "local_name": "kept.json", "tag": "t"},
    ]
    config = _config(tmp_path, entries)
    _artifact(tmp_path, "moved.json")
    _artifact(tmp_path, "kept.json")
    record(config, str(tmp_path))
    entries[0]["url"] = URL_B
    removed = drop_stale(_config(tmp_path, entries), str(tmp_path))
    assert [p.name for p in removed] == ["moved.json"]
    assert not (tmp_path / "moved.json").exists()
    assert (tmp_path / "kept.json").exists()


def test_a_tag_filtered_run_only_considers_its_own_entries(tmp_path):
    """`kg download -t ontologies` must not delete a mediadive artifact."""
    entries = [
        {"url": URL_A, "local_name": "onto.json", "tag": "ontologies"},
        {"url": URL_A, "local_name": "media.json", "tag": "mediadive"},
    ]
    config = _config(tmp_path, entries)
    _artifact(tmp_path, "onto.json")
    _artifact(tmp_path, "media.json")
    record(config, str(tmp_path))
    for entry in entries:
        entry["url"] = URL_B
    removed = drop_stale(_config(tmp_path, entries), str(tmp_path), tags=["ontologies"])
    assert [p.name for p in removed] == ["onto.json"]
    assert (tmp_path / "media.json").exists()


def test_a_missing_artifact_is_not_reported_stale(tmp_path):
    """There is nothing to invalidate, and the download will fetch it anyway."""
    config = _config(tmp_path, [{"url": URL_A, "local_name": "thing.json", "tag": "t"}])
    record(config, str(tmp_path))
    moved = _config(tmp_path, [{"url": URL_B, "local_name": "thing.json", "tag": "t"}])
    assert stale_by_url(moved, str(tmp_path)) == []


def test_only_artifacts_that_exist_are_recorded(tmp_path):
    """A skipped or failed entry must not gain a provenance claim it did not earn."""
    config = _config(
        tmp_path,
        [
            {"url": URL_A, "local_name": "present.json", "tag": "t"},
            {"url": URL_A, "local_name": "absent.json", "tag": "t"},
        ],
    )
    _artifact(tmp_path, "present.json")
    record(config, str(tmp_path))
    recorded = read_manifest(str(tmp_path))
    assert set(recorded) == {"present.json"}


def test_a_corrupt_manifest_never_blocks_a_download(tmp_path):
    """
    Provenance is an optimisation; losing it must not stop work.

    A manifest that cannot be parsed is treated as no manifest, which degrades
    to today's behaviour rather than to an error.
    """
    manifest_path(str(tmp_path)).write_text("{not json", encoding="utf-8")
    config = _config(tmp_path, [{"url": URL_A, "local_name": "thing.json", "tag": "t"}])
    _artifact(tmp_path, "thing.json")
    assert read_manifest(str(tmp_path)) == {}
    assert stale_by_url(config, str(tmp_path)) == []


def test_the_manifest_is_written_atomically_and_sorted(tmp_path):
    """A half-written manifest would claim provenance for artifacts arbitrarily."""
    config = _config(
        tmp_path,
        [
            {"url": URL_B, "local_name": "b.json", "tag": "t"},
            {"url": URL_A, "local_name": "a.json", "tag": "t"},
        ],
    )
    _artifact(tmp_path, "a.json")
    _artifact(tmp_path, "b.json")
    record(config, str(tmp_path))
    payload = json.loads((tmp_path / MANIFEST_NAME).read_text(encoding="utf-8"))
    assert list(payload["artifacts"]) == ["a.json", "b.json"]


def test_an_entry_without_local_name_falls_back_to_the_url_basename(tmp_path):
    """download.yaml does not require local_name; the downloader derives it too."""
    config = _config(tmp_path, [{"url": URL_A, "tag": "t"}])
    _artifact(tmp_path, "thing.json")
    record(config, str(tmp_path))
    assert set(read_manifest(str(tmp_path))) == {"thing.json"}


def test_a_pending_hosting_entry_gains_no_provenance(tmp_path):
    """
    Its artifact is placed by hand, so it never came from the URL in the config (#929).

    `_report_pending` tells the user to copy these from a reference directory, so
    the file usually exists while the config still holds a `REPLACE_ME_`
    placeholder. Recording that as its provenance answers "what produced this
    file" with something that produced nothing — worse than answering nothing,
    since `stale_by_url` already treats "no record" as "leave alone".
    """
    config = _config(
        tmp_path,
        [
            {"url": URL_A, "local_name": "real.json", "tag": "t"},
            {"url": "REPLACE_ME_pending", "local_name": "handplaced.json", "tag": "t"},
        ],
    )
    _artifact(tmp_path, "real.json")
    _artifact(tmp_path, "handplaced.json")
    record(config, str(tmp_path), skip_names=["handplaced.json"])
    recorded = read_manifest(str(tmp_path))
    assert set(recorded) == {"real.json"}
    assert "handplaced.json" not in recorded


def test_download_excludes_pending_entries_when_recording():
    """
    Pin the wiring, not just the helper.

    The exclusion is only useful if `download()` actually passes the pending
    names through; the ternary it replaced looked like it chose a config and
    always returned the same one.
    """
    import inspect

    from kg_microbe.download import download

    source = inspect.getsource(download)
    assert "skip_names=[_local_name_of(e) for e in pending]" in source
    assert "effective_yaml if effective_yaml == yaml_file else yaml_file" not in source
