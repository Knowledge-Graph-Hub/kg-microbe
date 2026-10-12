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


class RobotJavaArgsTest(TestCase):
    """Recent JDKs ship JAXP entity limits that reject real ontology imports."""

    def test_the_default_carries_every_jaxp_limit(self):
        """No ROBOT_JAVA_ARGS: the repo default plus each limit."""
        with mock.patch.dict(os.environ, {}, clear=True):
            args = robot_utils.robot_java_args()
        self.assertTrue(args.startswith(robot_utils.DEFAULT_ROBOT_JAVA_ARGS))
        for name, value in robot_utils.ROBOT_JAXP_LIMITS:
            self.assertIn(f"-D{name}={value}", args)

    def test_a_user_setting_wins_and_is_not_duplicated(self):
        """A limit set in ROBOT_JAVA_ARGS is kept as written; the others are still added."""
        configured = "-Xmx8G -Djdk.xml.totalEntitySizeLimit=0"
        with mock.patch.dict(os.environ, {"ROBOT_JAVA_ARGS": configured}, clear=True):
            args = robot_utils.robot_java_args()
        self.assertTrue(args.startswith(configured))
        self.assertEqual(args.count("-Djdk.xml.totalEntitySizeLimit="), 1)
        self.assertIn("-Djdk.xml.entityExpansionLimit=64000", args)

    def test_initialize_robot_uses_the_same_options(self):
        """The ontologies transform's ROBOT path gets the limits too, not only ontologies_stubs."""
        with mock.patch.dict(os.environ, {"PATH": "/usr/bin"}, clear=True):
            _, env = robot_utils.initialize_robot("robot-dir")
            self.assertEqual(env["ROBOT_JAVA_ARGS"], robot_utils.robot_java_args())
        self.assertTrue(env["PATH"].endswith(os.pathsep + "robot-dir"))

    def test_a_limit_set_in_another_jvm_option_variable_is_left_alone(self):
        """The appended -D flags outrank JAVA_TOOL_OPTIONS and JDK_JAVA_OPTIONS, so set there means set."""
        for variable in robot_utils.USER_JVM_OPTION_VARIABLES:
            env = {variable: "-Djdk.xml.totalEntitySizeLimit=0"}
            with mock.patch.dict(os.environ, env, clear=True):
                args = robot_utils.robot_java_args()
            self.assertNotIn("-Djdk.xml.totalEntitySizeLimit=", args, variable)
            self.assertIn("-Djdk.xml.maxElementDepth=0", args, variable)

    def test_a_user_jaxp_configuration_file_governs_every_limit(self):
        """The JDK reads java.xml.config.file only where no system property is set; append none."""
        env = {"ROBOT_JAVA_ARGS": "-Xmx8G -Djava.xml.config.file=/etc/jaxp-site.properties"}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(robot_utils.robot_java_args(), env["ROBOT_JAVA_ARGS"])


class MissingRobotTest(TestCase):
    """The ontology transforms run the ROBOT pinned into the raw directory, not one from PATH."""

    def test_absent_files_and_java_are_each_reported(self):
        """Both the pinned files and a JDK are needed; each absence says how to fix it."""
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(robot_utils.shutil, "which", return_value=None):
            problems = robot_utils.missing_robot(tmp)
        self.assertEqual(len(problems), 2)
        self.assertIn("robot, robot.jar", problems[0])
        self.assertIn("kg download -t tools", problems[0])
        self.assertIn("java not on PATH", problems[1])

    def test_the_pinned_files_and_a_java_are_enough(self):
        """Nothing is required of PATH except java."""
        with (
            tempfile.TemporaryDirectory() as tmp,
            mock.patch.object(robot_utils.shutil, "which", return_value="/usr/bin/java"),
        ):
            for name in ("robot", "robot.jar"):
                Path(tmp, name).write_text("stand-in", encoding="utf-8")
            self.assertEqual(robot_utils.missing_robot(tmp), [])
