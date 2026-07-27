"""Tests for tag-filtered downloads (`kg download -t <tag>`)."""

from importlib import import_module
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

# kg_microbe/__init__.py does `from .download import download`, so the name
# kg_microbe.download resolves to the *function*, not the module. Fetch the
# module from sys.modules so patch.object targets the right object.
download_module = import_module("kg_microbe.download")

DOWNLOAD_YAML = Path(__file__).parent.parent / "download.yaml"

# Tags documented in download.yaml's header. Kept here so a typo'd tag on a new
# entry fails loudly instead of creating a near-duplicate group.
KNOWN_TAGS = {
    "tools",
    "ontologies",
    "stubs",
    "mappings",
    "bacdive",
    "mediadive",
    "madin",
    "rhea",
    "cog",
    "kegg",
    "gtdb",
    "metatraits",
    "metatraits_gtdb",
    "bactotraits",
    "schema",
}


def _entries():
    """Return the active (uncommented) resource entries in download.yaml."""
    with open(DOWNLOAD_YAML) as f:
        return yaml.safe_load(f) or []


class TestYamlTagging:

    """Every active download entry must be reachable via -t."""

    def test_every_entry_has_a_tag(self):
        """An untagged entry can never be selected by -t, so require one."""
        untagged = [e.get("local_name") or e.get("url") for e in _entries() if not e.get("tag")]
        assert untagged == [], f"download.yaml entries missing a tag: {untagged}"

    def test_tags_are_from_the_documented_set(self):
        """Guard against typos silently creating a new one-entry group."""
        used = {e["tag"] for e in _entries() if e.get("tag")}
        assert used - KNOWN_TAGS == set(), f"undocumented tag(s): {sorted(used - KNOWN_TAGS)}"

    def test_documented_tags_are_all_used(self):
        """A documented tag that matches nothing would be a dead option."""
        used = {e["tag"] for e in _entries() if e.get("tag")}
        assert KNOWN_TAGS - used == set(), f"documented but unused tag(s): {sorted(KNOWN_TAGS - used)}"

    def test_urls_have_no_surrounding_whitespace(self):
        """A stray space becomes part of the URL handed to urllib (#623)."""
        offenders = [e["local_name"] for e in _entries() if e["url"] != e["url"].strip()]
        assert offenders == [], f"entries with padded URLs: {offenders}"

    def test_local_names_have_no_surrounding_whitespace(self):
        """Same hazard for the destination path."""
        offenders = [e["local_name"] for e in _entries() if e["local_name"] != e["local_name"].strip()]
        assert offenders == []

    def test_mediadive_tag_matches_the_constant(self):
        """The bulk-download gate keys off this exact tag string."""
        tags = {e["tag"] for e in _entries() if e.get("tag")}
        assert download_module.MEDIADIVE_TAG in tags


class TestPendingHosting:

    """
    Sources with a placeholder URL must be skipped, not attempted.

    kghub-downloader aborts the whole run on the first download error, so leaving
    a REPLACE_ME_ URL in the config would break `kg download` for everyone.
    """

    # The mechanism is exercised against a synthetic config rather than
    # download.yaml, which normally has no placeholders left: every file is
    # hosted. Tying these to the real file made them pass only while something
    # happened to be unhosted.
    @staticmethod
    def _config(tmp_path, *, pending=True):
        """Write a small config with one ready entry and optionally one pending."""
        entries = [{"url": "https://example.org/ready.tsv", "local_name": "ready.tsv", "tag": "ontologies"}]
        if pending:
            entries.append(
                {
                    "url": f"gdrive:{download_module.PENDING_HOSTING_MARKER}thing",
                    "local_name": "unhosted.tsv.gz",
                    "tag": "metatraits_gtdb",
                }
            )
        path = tmp_path / "config.yaml"
        with open(path, "w") as f:
            yaml.safe_dump(entries, f, sort_keys=False)
        return str(path)

    def _run(self, tmp_path, config, **kwargs):
        """Run download() against `config`, capturing what the downloader saw."""
        captured = {}

        def record(**call_kwargs):
            """Parse the config file while it still exists."""
            captured["path"] = call_kwargs["yaml_file"]
            with open(call_kwargs["yaml_file"]) as f:
                captured["entries"] = yaml.safe_load(f)

        with patch.object(download_module, "download_from_yaml", side_effect=record):
            download_module.download(
                yaml_file=config,
                output_dir=str(tmp_path / "out"),
                snippet_only=False,
                **kwargs,
            )
        return captured

    def test_real_config_pending_entries_are_tagged(self):
        """Any placeholder left in download.yaml still needs a tag."""
        pending = [e for e in _entries() if download_module.PENDING_HOSTING_MARKER in e["url"]]
        assert [e["local_name"] for e in pending if not e.get("tag")] == []

    def test_pending_entries_are_filtered_out(self, tmp_path):
        """The config handed to the downloader must contain no placeholder URL."""
        seen = self._run(tmp_path, self._config(tmp_path))
        assert [e["local_name"] for e in seen["entries"]] == ["ready.tsv"]

    def test_filtered_entries_keep_their_fields(self, tmp_path):
        """Round-tripping the config must not lose url/local_name/tag."""
        seen = self._run(tmp_path, self._config(tmp_path))
        assert all({"url", "local_name", "tag"} <= set(e) for e in seen["entries"])

    def test_temp_config_is_cleaned_up(self, tmp_path):
        """The filtered copy is a temp file; it must not be left behind."""
        config = self._config(tmp_path)
        seen = self._run(tmp_path, config)
        assert seen["path"] != config
        assert not Path(seen["path"]).exists()

    def test_temp_config_cleaned_up_on_error(self, tmp_path):
        """A failed download must not leak the temp config either."""
        seen = {}

        def boom(**kwargs):
            """Record the config path, then fail like a dead URL would."""
            seen["yaml"] = kwargs["yaml_file"]
            raise RuntimeError("download exploded")

        with patch.object(download_module, "download_from_yaml", side_effect=boom):
            with pytest.raises(RuntimeError, match="exploded"):
                download_module.download(
                    yaml_file=self._config(tmp_path),
                    output_dir=str(tmp_path / "out"),
                    snippet_only=False,
                )
        assert not Path(seen["yaml"]).exists()

    def test_skipped_sources_are_reported(self, tmp_path, capsys):
        """A silent skip looks like a download of a file that never arrived."""
        self._run(tmp_path, self._config(tmp_path))
        out = capsys.readouterr().out
        assert "not hosted yet" in out
        assert "unhosted.tsv.gz" in out

    def test_no_placeholders_means_original_config(self, tmp_path):
        """With everything hosted, no filtered copy is made at all."""
        config = self._config(tmp_path, pending=False)
        seen = self._run(tmp_path, config)
        assert seen["path"] == config

    def test_unaffected_tag_run_uses_the_original_config(self, tmp_path):
        """A run selecting no pending entry needs no filtered copy."""
        config = self._config(tmp_path)
        seen = self._run(tmp_path, config, tags=("ontologies",))
        assert seen["path"] == config

    def test_pending_tag_is_still_a_valid_tag(self, tmp_path):
        """A tag whose only entries are unhosted must be accepted, not rejected as unknown."""
        config = self._config(tmp_path)
        # Reaching the downloader at all proves _validate_tags accepted the tag;
        # a rejection would have raised ValueError before this point.
        seen = self._run(tmp_path, config, tags=("metatraits_gtdb",))
        assert "path" in seen, "download_from_yaml should still have been called"
        names = [e["local_name"] for e in seen["entries"]]
        assert "unhosted.tsv.gz" not in names, "the pending entry must be filtered out"


class TestCliErrorHandling:

    """The CLI must report bad tags as usage errors without hiding real crashes."""

    def test_unknown_tag_is_a_usage_error(self, tmp_path):
        """A bad -t is user error: exit 2, no traceback."""
        from click.testing import CliRunner

        from kg_microbe.run import download as download_cmd

        result = CliRunner().invoke(download_cmd, ["-y", str(DOWNLOAD_YAML), "-o", str(tmp_path), "-t", "nosuchtag"])
        assert result.exit_code == 2
        assert "Unknown download tag" in result.output

    def test_unrelated_valueerror_is_not_mislabelled(self, tmp_path):
        """
        A ValueError from deep in the download must not be reported as a bad tag.

        JSONDecodeError and pydantic's ValidationError are both ValueError
        subclasses, so a blanket `except ValueError` turned a corrupt
        mediadive.json into 'Error: Invalid value: ...' against -t, swallowing the
        traceback that pointed at the real cause.
        """
        from click.testing import CliRunner

        from kg_microbe.run import download as download_cmd

        with patch.object(download_module, "download_from_yaml", side_effect=ValueError("boom in json")):
            result = CliRunner().invoke(download_cmd, ["-y", str(DOWNLOAD_YAML), "-o", str(tmp_path)])
        assert result.exit_code != 2, "should not be reported as a usage error"
        assert isinstance(result.exception, ValueError)
        assert "boom in json" in str(result.exception)


class TestTagPlumbing:

    """Tags must reach kghub-downloader, and gate the MediaDive bulk step."""

    def _run(self, tmp_path, **kwargs):
        """Call download() with both downstream side effects mocked out."""
        with (
            patch.object(download_module, "download_from_yaml") as mock_yaml,
            patch.object(download_module, "_post_download_mediadive_bulk") as mock_bulk,
        ):
            download_module.download(
                yaml_file=str(DOWNLOAD_YAML),
                output_dir=str(tmp_path),
                snippet_only=False,
                **kwargs,
            )
        return mock_yaml, mock_bulk

    def test_tags_are_forwarded(self, tmp_path):
        """-t values must be handed to download_from_yaml."""
        mock_yaml, _ = self._run(tmp_path, tags=("ontologies", "gtdb"))
        assert mock_yaml.call_args.kwargs["tags"] == ["ontologies", "gtdb"]

    def test_no_tags_means_everything(self, tmp_path):
        """Omitting -t must not filter (None, not an empty list)."""
        mock_yaml, _ = self._run(tmp_path)
        assert mock_yaml.call_args.kwargs["tags"] is None

    def test_empty_tags_tuple_means_everything(self, tmp_path):
        """Click passes () when -t is absent; that must mean 'all', not 'none'."""
        mock_yaml, _ = self._run(tmp_path, tags=())
        assert mock_yaml.call_args.kwargs["tags"] is None

    def test_mediadive_bulk_skipped_when_tag_excluded(self, tmp_path):
        """`-t ontologies` must not start an hour of MediaDive API calls."""
        _, mock_bulk = self._run(tmp_path, tags=("ontologies",))
        mock_bulk.assert_not_called()

    def test_mediadive_bulk_runs_when_tag_included(self, tmp_path):
        """`-t mediadive` must still do the follow-on bulk download."""
        _, mock_bulk = self._run(tmp_path, tags=("mediadive",))
        mock_bulk.assert_called_once()

    def test_mediadive_bulk_runs_without_tags(self, tmp_path):
        """An unfiltered run keeps its existing behaviour."""
        _, mock_bulk = self._run(tmp_path)
        mock_bulk.assert_called_once()

    def test_unknown_tag_raises(self, tmp_path):
        """An unknown tag downloads nothing, which looks like success — so fail."""
        with patch.object(download_module, "download_from_yaml") as mock_yaml:
            with pytest.raises(ValueError, match="Unknown download tag"):
                download_module.download(
                    yaml_file=str(DOWNLOAD_YAML),
                    output_dir=str(tmp_path),
                    snippet_only=False,
                    tags=("ontolgies",),  # typo
                )
        mock_yaml.assert_not_called()

    def test_error_lists_available_tags(self, tmp_path):
        """The message should tell the user what they could have typed."""
        with patch.object(download_module, "download_from_yaml"):
            with pytest.raises(ValueError, match="ontologies"):
                download_module.download(
                    yaml_file=str(DOWNLOAD_YAML),
                    output_dir=str(tmp_path),
                    snippet_only=False,
                    tags=("nope",),
                )

    def test_snippet_mode_still_skips_bulk(self, tmp_path):
        """Snippet mode skipped the bulk step before tags existed; keep that."""
        with (
            patch.object(download_module, "download_from_yaml"),
            patch.object(download_module, "_post_download_mediadive_bulk") as mock_bulk,
        ):
            download_module.download(
                yaml_file=str(DOWNLOAD_YAML),
                output_dir=str(tmp_path),
                snippet_only=True,
                tags=("mediadive",),
            )
        mock_bulk.assert_not_called()
