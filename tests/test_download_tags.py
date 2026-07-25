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

    def test_mediadive_tag_matches_the_constant(self):
        """The bulk-download gate keys off this exact tag string."""
        tags = {e["tag"] for e in _entries() if e.get("tag")}
        assert download_module.MEDIADIVE_TAG in tags


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
