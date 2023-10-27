"""Utility to implement ROBOT over ontology files."""
import os
import subprocess
from pathlib import Path
from typing import List, Union

from kg_microbe.transform_utils.constants import (
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
    env["ROBOT_JAVA_ARGS"] = "-Xmx12g -XX:+UseG1GC"  # For JDK 10 and over
    env["PATH"] = os.environ["PATH"]
    env["PATH"] += os.pathsep + path

    return [robot_file, env]


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

        subprocess.call(call, env=env)  # noqa

    return None


def extract_convert_to_json(path: str, ont_name: str, terms: str, mode: str):
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
    output_json = os.path.join(path, ont_name.lower() + ".json")
    output_owl = os.path.join(path, ont_name.lower() + "_extracted_subset.owl")

    if ":" in terms:
        call = [
            "bash",
            robot_file,
            "extract",
            "--method",
            mode,
            "--input",
            input_owl,
            "--output",
            output_owl,
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
            "--output",
            output_owl,
            "--term-file",
            terms,
            "convert",
            "--output",
            output_json,
            "-f",
            "json",
        ]

    subprocess.call(call, env=env)  # noqa

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

    if isinstance(terms, List):
        terms_param = [
            item for sublist in zip(["--term"] * len(terms), terms, strict=True) for item in sublist
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

    subprocess.call(call, env=env)  # noqa

    return None
