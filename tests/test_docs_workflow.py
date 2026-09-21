"""Regression checks for the documentation deployment workflow."""

import subprocess
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
DOCS_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "deploy-docs.yml"


def test_docs_python_version_preserves_minor_version() -> None:
    """Keep Python 3.10 as a string rather than the YAML number 3.1 (#1056)."""
    workflow = yaml.safe_load(DOCS_WORKFLOW.read_text(encoding="utf-8"))
    setup_steps = [
        step
        for step in workflow["jobs"]["build-docs"]["steps"]
        if step.get("uses", "").startswith("actions/setup-python@")
    ]
    assert len(setup_steps) == 1
    version = setup_steps[0]["with"]["python-version"]
    assert isinstance(version, str), "Quote the Python version to preserve its minor version"
    assert version == "3.10"


def test_docs_config_imports_checkout_without_installed_package(tmp_path: Path) -> None:
    """Sphinx must find its checkout when dependencies are installed with --no-root."""
    docs = tmp_path / "docs"
    docs.mkdir()
    config = docs / "conf.py"
    config.write_text((REPO_ROOT / "docs" / "conf.py").read_text(encoding="utf-8"), encoding="utf-8")
    package = tmp_path / "kg_microbe"
    package.mkdir()
    (package / "__init__.py").write_text('__version__ = "docs-test-version"\n', encoding="utf-8")

    result = subprocess.run(  # noqa: S603 - interpreter and script are test-controlled
        [
            sys.executable,
            "-I",
            "-S",
            "-c",
            "import runpy, sys; settings = runpy.run_path(sys.argv[1]); "
            "assert settings['release'] == 'docs-test-version'",
            str(config),
        ],
        cwd=docs,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
