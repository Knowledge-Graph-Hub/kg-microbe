"""Tests that ROBOT conversions cannot leave a partial file at the real path."""

import os
import subprocess
import tempfile
from pathlib import Path
from unittest import TestCase, mock

from kg_microbe.utils import robot_utils

_PARTIAL = '{"meta":{"basicPropertyValues":[{"pred":"versionInfo","val":"2026-07-12"}]}},TRUNCATED'


class RobotAtomicOutputTest(TestCase):
    """ROBOT wrote to the final filename and its exit status was discarded."""

    def test_a_failed_conversion_publishes_nothing(self):
        """
        A partial derived JSON is unrecoverable, not merely wrong.

        ROBOT emits the release metadata near the head, so a truncated file still
        reports the current release: the staleness check sees matching stamps, the
        is_file() guard skips regeneration, and every later run hands KGX the same
        invalid file until someone knows which file to delete.
        """
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "go.owl").write_text("<owl/>", encoding="utf-8")
            target = Path(tmp, "go.json")

            def failing_robot(call, env=None, check=False):
                """Write a partial output, then report failure."""
                Path(call[call.index("--output") + 1]).write_text(_PARTIAL, encoding="utf-8")
                return subprocess.CompletedProcess(call, 1)

            with mock.patch.object(robot_utils.subprocess, "run", failing_robot):
                with self.assertRaises(RuntimeError):
                    robot_utils.convert_to_json(tmp, "go")

            self.assertFalse(target.exists(), "no partial may be published")
            self.assertEqual(list(Path(tmp).glob("*.tmp.json")), [], "and no temp may survive")

    def test_a_silent_no_output_is_caught(self):
        """ROBOT exiting 0 without writing anything used to look like success."""
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "go.owl").write_text("<owl/>", encoding="utf-8")

            with mock.patch.object(
                robot_utils.subprocess, "run", lambda call, env=None, check=False: subprocess.CompletedProcess(call, 0)
            ):
                with self.assertRaises(RuntimeError):
                    robot_utils.convert_to_json(tmp, "go")

    def test_a_successful_conversion_is_published(self):
        """The happy path must still land at the real filename."""
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "go.owl").write_text("<owl/>", encoding="utf-8")
            target = Path(tmp, "go.json")

            def working_robot(call, env=None, check=False):
                """Write a complete output and report success."""
                Path(call[call.index("--output") + 1]).write_text('{"graphs":[]}', encoding="utf-8")
                return subprocess.CompletedProcess(call, 0)

            with mock.patch.object(robot_utils.subprocess, "run", working_robot):
                robot_utils.convert_to_json(tmp, "go")

            self.assertEqual(target.read_text(encoding="utf-8"), '{"graphs":[]}')
            self.assertEqual(list(Path(tmp).glob("*.tmp.json")), [])

    def test_the_temp_name_keeps_the_json_extension(self):
        """ROBOT infers its output format from the extension, so `.partial` would change it."""
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "go.owl").write_text("<owl/>", encoding="utf-8")
            seen = []

            def recording_robot(call, env=None, check=False):
                """Record the output path ROBOT was handed."""
                out = call[call.index("--output") + 1]
                seen.append(out)
                Path(out).write_text("{}", encoding="utf-8")
                return subprocess.CompletedProcess(call, 0)

            with mock.patch.object(robot_utils.subprocess, "run", recording_robot):
                robot_utils.convert_to_json(tmp, "go")

            self.assertTrue(seen[0].endswith(".json"), seen[0])
            self.assertIn(str(os.getpid()), seen[0], "the temp must be per-writer")
