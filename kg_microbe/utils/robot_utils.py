"""Utility to implement ROBOT over ontology files."""

import itertools
import os
import re
import shlex
import shutil
import subprocess
import tempfile
import zipfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, List, Optional, Set, Union

from kg_microbe.transform_utils.constants import (
    ROBOT_EXTRACT_SUFFIX,
    ROBOT_REMOVED_SUFFIX,
)

DEFAULT_ROBOT_JAVA_ARGS = "-Xmx12g -XX:+UseG1GC"

# JDK 24 lowered seven JAXP processing limits (CSR JDK-8343006); Temurin 27
# rejects MicrO's ChEBI import module with "accumulated size of entities is
# 100,009 that exceeded the 100,000 limit set by jdk.xml.totalEntitySizeLimit",
# which fails ontologies_stubs and skips gold and microbedecoder behind it.
# These are the JDK 23 defaults for all seven: still bounded, so a pathological
# file fails rather than exhausting memory, but large enough for real
# ontologies. (OWLAPI sets its own entityExpansionLimit for its RDF/XML
# parser, but the parsers it falls back to use the JDK's.) A limit the user
# sets wins.
ROBOT_JAXP_LIMITS = (
    ("jdk.xml.totalEntitySizeLimit", "50000000"),
    ("jdk.xml.entityExpansionLimit", "64000"),
    ("jdk.xml.maxGeneralEntitySizeLimit", "0"),
    ("jdk.xml.maxParameterEntitySizeLimit", "1000000"),
    ("jdk.xml.entityReplacementLimit", "3000000"),
    ("jdk.xml.elementAttributeLimit", "10000"),
    ("jdk.xml.maxElementDepth", "0"),
)

# For a ROBOT run whose imports must all resolve locally (through a catalog):
# send any HTTP(S) request to a closed local port, so an import the catalog
# does not map fails instead of being fetched from a moving upstream branch.
ROBOT_OFFLINE_JAVA_ARGS = (
    "-Dhttp.proxyHost=127.0.0.1 -Dhttp.proxyPort=9 -Dhttps.proxyHost=127.0.0.1 -Dhttps.proxyPort=9"
)

# Older spellings the JDK still honours for two of the limits.
LEGACY_JAXP_NAMES = {
    "jdk.xml.entityExpansionLimit": "entityExpansionLimit",
    "jdk.xml.elementAttributeLimit": "elementAttributeLimit",
}

# Where else a user configures the ROBOT JVM. The appended -D flags outrank
# both, so a limit set there is treated as set.
USER_JVM_OPTION_VARIABLES = ("JAVA_TOOL_OPTIONS", "JDK_JAVA_OPTIONS")


def _configured_jaxp_limits(configured: str) -> Set[str]:
    """
    Return which of :data:`ROBOT_JAXP_LIMITS` the user already sets.

    Counts a ``-D`` flag under either spelling and a key in a JAXP
    configuration file named by ``-Djava.xml.config.file``. The JDK reads such
    a file only for limits no system property sets, so only those it leaves
    out are appended; a file that cannot be read sets nothing.
    """
    keys = set()
    match = re.search(r"-Djava\.xml\.config\.file=(\S+)", configured)
    if match:
        try:
            lines = Path(match.group(1)).read_text(encoding="utf-8").splitlines()
        except OSError:
            lines = []
        keys = {line.split("=", 1)[0].strip() for line in lines if "=" in line and not line.lstrip().startswith("#")}
    names = set()
    for name, _ in ROBOT_JAXP_LIMITS:
        spellings = (name, LEGACY_JAXP_NAMES[name]) if name in LEGACY_JAXP_NAMES else (name,)
        if any(f"-D{spelling}=" in configured or spelling in keys for spelling in spellings):
            names.add(name)
    return names


def robot_java_args(base: Optional[str] = None) -> str:
    """
    Return the JVM options for ROBOT: the configured ones plus any JAXP limit they leave unset.

    :param base: JVM options to start from; defaults to ``ROBOT_JAVA_ARGS`` or
        :data:`DEFAULT_ROBOT_JAVA_ARGS` when that is unset.
    """
    args = base if base is not None else os.environ.get("ROBOT_JAVA_ARGS", DEFAULT_ROBOT_JAVA_ARGS)
    configured = " ".join([args, *(os.environ.get(name, "") for name in USER_JVM_OPTION_VARIABLES)])
    preset = _configured_jaxp_limits(configured)
    extra = [f"-D{name}={value}" for name, value in ROBOT_JAXP_LIMITS if name not in preset]
    return " ".join([args, *extra]).strip()


def robot_env() -> dict:
    """Return a copy of the environment with ROBOT's JVM options set for every invocation."""
    env = dict(os.environ)
    env["ROBOT_JAVA_ARGS"] = robot_java_args()
    return env


def missing_robot(path: Union[str, Path]) -> List[str]:
    """
    Return what the pinned ROBOT under ``path`` needs but lacks: its files, or a ``java``.

    ``download.yaml`` pins ROBOT into the raw directory (tag ``tools``), and the
    ontology transforms run that copy rather than whatever ``robot`` is on PATH,
    so the version is the one this repository was tested with.

    :param path: Raw directory that ``kg download`` writes ROBOT into.
    :return: One message per problem; empty when ROBOT can run.
    """
    root = Path(path)
    problems = []
    fetch = f"Run `poetry run kg download -t tools -o {root}`."
    absent = [name for name in ("robot", "robot.jar") if not (root / name).is_file()]
    if absent:
        problems.append(f"pinned ROBOT missing from {root}: {', '.join(absent)}. {fetch}")
    elif not zipfile.is_zipfile(root / "robot.jar"):
        # A truncated download or an HTML error page saved under the jar's name.
        problems.append(f"{root / 'robot.jar'} is not a jar. {fetch}")
    if not _java_runs():
        problems.append("java on PATH does not run (no JDK installed?); ROBOT needs one.")
    return problems


def _java_runs() -> bool:
    """
    Say whether ``java -version`` succeeds.

    Finding ``java`` is not enough: macOS ships ``/usr/bin/java`` as a stub that
    exists whether or not a JDK is installed.
    """
    java = shutil.which("java")
    if java is None:
        return False
    try:
        return subprocess.run([java, "-version"], capture_output=True, timeout=60).returncode == 0  # noqa: S603
    except (OSError, subprocess.SubprocessError):
        return False


@contextmanager
def pinned_robot_on_path(path: Union[str, Path]) -> Iterator[dict]:
    """
    Yield an environment in which ``robot`` on PATH is the pinned ROBOT, run with :func:`robot_java_args`.

    For tools that call ROBOT themselves: SemSQL's Makefile runs ``robot`` from
    PATH, so without this a database build used whatever ``robot`` was there
    (or none) with the JDK's own limits, and failed on ChEBI under JDK 24+
    (#325). The downloaded wrapper is not executable, so the shim calls it
    through ``bash``. Without the pinned files PATH is left as it is.

    :param path: Raw directory that ``kg download`` writes ROBOT into.
    """
    env = robot_env()
    wrapper = Path(path).resolve() / "robot"
    if not wrapper.is_file():
        yield env
        return
    with tempfile.TemporaryDirectory() as shim_dir:
        shim = Path(shim_dir) / "robot"
        shim.write_text(f'#!/bin/sh\nexec bash {shlex.quote(str(wrapper))} "$@"\n', encoding="utf-8")
        shim.chmod(0o755)
        env["PATH"] = shim_dir + os.pathsep + env.get("PATH", "")
        yield env


def initialize_robot(path: str) -> list:
    """
    Initialize ROBOT with necessary configuration.

    :param path: Path to ROBOT files.
    :return: A list consisting of robot shell script name and environment variables.
    """
    # Declare variables
    robot_file = os.path.join(path, "robot")

    # Declare environment variables. G1 rather than ConcMarkSweep: JDK 10 and
    # over reject the old collector flags.
    env = robot_env()
    env["PATH"] = os.environ["PATH"]
    env["PATH"] += os.pathsep + path

    return [robot_file, env]


# Distinguishes concurrent writers, as in atomic_io. itertools.count is atomic
# under the GIL; os.getpid() covers separate processes.
_ROBOT_COUNTER = itertools.count()


def _run_robot(call: List[str], output_path: str, env: dict, output_flag_index: int) -> None:
    """
    Run a ROBOT command that writes ``output_path``, publishing only on success.

    ROBOT wrote straight to the final filename and its exit status was discarded,
    so an interrupted or out-of-space conversion left a partial file at the real
    path. That is unrecoverable rather than merely wrong: ROBOT emits the release
    metadata near the head, so a truncated derived JSON still reports the *current*
    release. The staleness check then sees matching stamps, the ``is_file()`` guard
    skips regeneration, and every later run hands KGX the same invalid file. The
    only way out was for someone to know which file to delete.

    The temp name keeps the final extension because ROBOT infers its output format
    from it — a bare ``.partial`` suffix would change what ROBOT writes.

    :param call: The ROBOT command, with ``output_path`` at ``output_flag_index``.
    :param output_path: Final destination for ROBOT's output.
    :param env: Environment for the subprocess.
    :param output_flag_index: Index in ``call`` holding the output path.
    :raises RuntimeError: If ROBOT fails or produces nothing.
    """
    final = Path(output_path)
    suffix = "".join(final.suffixes)
    tmp = final.with_name(f"{final.name}.{os.getpid()}.{next(_ROBOT_COUNTER)}.tmp{suffix}")
    call = list(call)
    call[output_flag_index] = str(tmp)
    try:
        result = subprocess.run(call, env=env, check=False)  # noqa: S603
        if result.returncode != 0:
            raise RuntimeError(f"ROBOT exited {result.returncode} while writing {final.name}")
        if not tmp.exists() or tmp.stat().st_size == 0:
            raise RuntimeError(f"ROBOT reported success but produced no {final.name}")
        os.replace(tmp, final)
    finally:
        # Cleanup on any unwind, including the fatal ontology errors, which are
        # BaseException — `finally` still runs for those.
        if tmp.exists():
            try:
                os.unlink(tmp)
            except OSError:
                pass


def convert_to_json(path: str, ont: str):
    """
    Convert OWL to JSON using ROBOT and the subprocess library.

    :param path: Path to ROBOT and the input OWL files.
    :param ont: Ontology
    :return: None
    """
    robot_file, env = initialize_robot(path)
    input_owl = os.path.join(path, ont.lower() + ".owl")
    output_json = os.path.join(path, ont.lower() + ".json")
    if not os.path.isfile(output_json):
        # Setup the arguments for ROBOT through subprocess
        call = [
            "bash",
            robot_file,
            "convert",
            "--input",
            input_owl,
            "--output",
            output_json,
            "-f",
            "json",
        ]

        _run_robot(call, output_json, env, call.index(output_json))

    return None


def extract_convert_to_json(path: str, ont_name: str, terms: Union[str, Path], mode: str):
    """
    Extract all children of provided CURIE.

    ROBOT Method options:

    -   STAR: The STAR-module contains mainly the terms in the seed and the
    inter-relations between them (not necessarily sub- and super-classes).

    -   TOP: The TOP-module contains mainly the terms in the seed, plus all
    their sub-classes and the inter-relations between them.

    -   BOT: The BOT, or BOTTOM, -module contains mainly the terms in the seed,
    plus all their super-classes and the inter-relations between them.

    -   MIREOT : The MIREOT method preserves the hierarchy of the input ontology
    (subclass and subproperty relationships), but does not try to preserve the
    full set of logical entailments.

    :param path: path of file to be converted
    :param ont_name: Name of the ontology
    :param terms: Either CURIE or a file of CURIEs list
    :param mode: Method options as listed below.
    :return: None
    """
    robot_file, env = initialize_robot(path)
    input_owl = os.path.join(path, ont_name.lower() + ".owl")
    output_json = os.path.join(path, ont_name.lower() + ROBOT_EXTRACT_SUFFIX + ".json")

    if ":" in terms:
        call = [
            "bash",
            robot_file,
            "extract",
            "--method",
            mode,
            "--input",
            input_owl,
            "--term",
            terms,
            "convert",
            "--output",
            output_json,
            "-f",
            "json",
        ]
    else:
        call = [
            "bash",
            robot_file,
            "extract",
            "--method",
            mode,
            "--input",
            input_owl,
            "--term-file",
            terms,
            "convert",
            "--output",
            output_json,
            "-f",
            "json",
        ]

    # Same treatment as its two siblings: a partial extract JSON carries the
    # current release in its head and would be accepted forever.
    _run_robot(call, output_json, env, call.index(output_json))

    return None


def remove_convert_to_json(path: str, ont_name: str, terms: Union[List, Path]):
    """
    Remove all children of provided CURIE(s).

    :param path: path of file to be converted
    :param ont_name: Name of the ontology
    :param terms: Either CURIE or a file of CURIEs list.
    :return: None
    """
    robot_file, env = initialize_robot(path)
    input_owl = os.path.join(path, ont_name.lower() + ".owl")
    output_json = os.path.join(path, ont_name.lower() + ROBOT_REMOVED_SUFFIX + ".json")

    input_file = input_owl

    print(f"remove_convert_to_json {input_file}")

    if isinstance(terms, list):
        terms_param = [
            item
            for sublist in zip(["--term"] * len(terms), terms, strict=True)
            for item in sublist  # noqa
        ]
        call = [
            "bash",
            robot_file,
            "remove",
            "--input",
            input_file,
            *terms_param,
            "--select",
            "'self descendants'",
            "convert",
            "--output",
            output_json,
        ]
    else:
        call = [
            "bash",
            robot_file,
            "remove",
            "--input",
            input_file,
            "--term-file",
            terms,
            "--select",
            "'self descendants'",
            "convert",
            "--output",
            output_json,
        ]

    print(f"call {call}")
    _run_robot(call, output_json, env, call.index(output_json))

    return None
