"""The ROBOT wrapper and jar must come from one pinned release."""

import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
DOWNLOAD_YAML = REPO_ROOT / "download.yaml"


def test_the_wrapper_and_the_jar_come_from_one_release():
    """
    The jar was pinned to v1.9.8 while the wrapper script tracked ROBOT's master branch.

    The ontology transforms run this pair from the raw directory, so an upstream
    change to the wrapper would reach every build with no change here.
    """
    entries = yaml.safe_load(DOWNLOAD_YAML.read_text(encoding="utf-8"))
    urls = {e["local_name"]: e["url"] for e in entries if isinstance(e, dict) and e.get("tag") == "tools"}
    jar = re.fullmatch(r"https://github\.com/ontodev/robot/releases/download/(v[\d.]+)/robot\.jar", urls["robot.jar"])
    assert jar, f"robot.jar must come from a tagged release: {urls['robot.jar']}"
    assert urls["robot"] == f"https://raw.githubusercontent.com/ontodev/robot/{jar.group(1)}/bin/robot"
