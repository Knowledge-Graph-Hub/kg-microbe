"""The one call into kghub-downloader must match the installed signature (#997)."""

import inspect
import unittest
from importlib import import_module
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

import yaml
from kghub_downloader.download_utils import download_from_yaml
from kghub_downloader.model import DownloadOptions

# kg_microbe/__init__.py re-exports the download *function* under the same name,
# so a plain import binds the function; go through import_module for the module.
download_module = import_module("kg_microbe.download")



class DownloaderContractTests(unittest.TestCase):
    """Every unit test mocks ``download_from_yaml``; this one binds the real signature."""

    def _capture(self, **flags):
        """
        Run ``download()`` and return the kwargs it handed to the downloader.

        :param flags: ``snippet_only`` / ``ignore_cache`` values to pass through.
        :return: The captured keyword arguments.
        """
        seen = {}

        def recorder(**kwargs):
            seen.update(kwargs)

        with TemporaryDirectory() as td:
            config = Path(td) / "download.yaml"
            config.write_text(yaml.safe_dump([{"url": "https://example.org/x.txt", "local_name": "x.txt", "tag": "t"}]))
            with (
                mock.patch.object(download_module, "download_from_yaml", side_effect=recorder),
                mock.patch.object(download_module, "_post_download_mediadive_bulk"),
            ):
                download_module.download(yaml_file=str(config), output_dir=td, tags=("t",), **flags)
        return seen

    def test_our_kwargs_bind_to_the_installed_signature(self):
        """
        0.3 → 0.5 turned ``snippet_only``/``ignore_cache`` into ``download_options``.

        A mock accepts any kwargs, so the only way a signature change fails
        before the next real ``kg download`` is to bind what we pass against
        what is installed.
        """
        seen = self._capture(snippet_only=False, ignore_cache=False)
        inspect.signature(download_from_yaml).bind(**seen)  # raises TypeError on drift

    def test_the_flags_reach_the_options_object(self):
        """Wrapping the flags must not drop them."""
        seen = self._capture(snippet_only=True, ignore_cache=True)
        options = seen["download_options"]
        self.assertIsInstance(options, DownloadOptions)
        self.assertTrue(options.snippet_only)
        self.assertTrue(options.ignore_cache)
        self.assertTrue(options.fail_on_error, "abort-on-first-failure must stay the default (#938 owns changing it)")


if __name__ == "__main__":
    unittest.main()
