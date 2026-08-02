"""Utility to implement ROBOT over ontology files."""

import itertools
import os
import subprocess
from pathlib import Path
from typing import List, Union

from kg_microbe.transform_utils.constants import (
    ROBOT_EXTRACT_SUFFIX,
    ROBOT_REMOVED_SUFFIX,
)


def initialize_robot(path: str) -> list:
    """
    Initialize ROBOT with necessary configuration.

    :param path: Path to ROBOT files.
    :return: A list consisting of robot shell script name and environment variables.
    """
    # Declare variables
    robot_file = os.path.join(path, "robot")

    # Declare environment variables
    env = dict(os.environ)
    # (JDK compatibility issue:
    # https://stackoverflow.com/questions/49962437/unrecognized-vm-option-useparnewgc-error-could-not-create-the-java-virtual) # noqa
    # env['ROBOT_JAVA_ARGS'] = '-Xmx8g -XX:+UseConcMarkSweepGC' # for JDK 9 and older
    # env["ROBOT_JAVA_ARGS"] = "-Xmx12g -XX:+UseG1GC"  # For JDK 10 and over
    env["ROBOT_JAVA_ARGS"] = (
        os.environ["ROBOT_JAVA_ARGS"] if "ROBOT_JAVA_ARGS" in os.environ else "-Xmx12g -XX:+UseG1GC"
    )  # noqa
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
