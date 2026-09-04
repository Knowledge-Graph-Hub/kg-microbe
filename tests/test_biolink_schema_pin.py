"""The pinned Biolink schema must be complete and internally consistent (#939, #940)."""

import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
DOWNLOAD_YAML = REPO_ROOT / "download.yaml"

#: Files that together make up the local Biolink schema. `biolink-model.yaml`
#: declares `imports: [linkml:types, attributes]`, so `attributes.yaml` is not
#: optional -- without it the model cannot be loaded at all (#939).
REQUIRED_SCHEMA_FILES = {"biolink-model.yaml", "attributes.yaml"}


def _biolink_entries():
    """
    Every biolink/biolink-model entry in download.yaml.

    :return: List of download entries as dicts.
    """
    entries = yaml.safe_load(DOWNLOAD_YAML.read_text(encoding="utf-8"))
    return [e for e in entries if isinstance(e, dict) and "biolink/biolink-model" in str(e.get("url", ""))]


def test_download_yaml_declares_every_file_the_model_imports():
    """
    A declared model that cannot be loaded is worse than no pin at all.

    `attributes.yaml` was never declared, so `data/raw` never held it and the
    pinned local model raised `FileNotFoundError` on every load -- while
    `prepare_kgx` told the caller to run `kg download -t schema`, the one
    command that could not supply it (#939).
    """
    declared = {e.get("local_name") for e in _biolink_entries()}
    missing = REQUIRED_SCHEMA_FILES - declared
    assert not missing, f"download.yaml does not fetch: {sorted(missing)}"


def test_every_biolink_artifact_is_pinned_to_the_same_version():
    """
    Half a schema at one version and half at another is worse than either version.

    `attributes.yaml` supplies slots the model's import closure resolves against,
    so a version skew between the two silently changes what validates.
    """
    versions = {re.search(r"/biolink-model/(v[^/]+)/", e["url"]).group(1) for e in _biolink_entries()}
    assert len(versions) == 1, f"download.yaml pins mixed Biolink versions: {sorted(versions)}"


def test_every_biolink_artifact_is_pinned_to_a_tag():
    """An unpinned fetch changes what the pipeline validates against with no record."""
    unpinned = [e["url"] for e in _biolink_entries() if not re.search(r"/biolink-model/v[^/]+/", e["url"])]
    assert not unpinned, f"Biolink artifacts must be fetched from a tag: {unpinned}"


def _write_model(tmp_path, imports):
    """
    Write a minimal model declaring ``imports`` and a predicate map beside it.

    :param tmp_path: pytest temporary directory.
    :param imports: Import names to declare.
    :return: ``(schema_path, predicate_map_path)``.
    """
    block = "\n".join(f"  - {name}" for name in imports)
    schema = tmp_path / "biolink-model.yaml"
    schema.write_text(f"id: https://example.org/test\nname: test\nimports:\n{block}\n", encoding="utf-8")
    predicate_map = tmp_path / "predicate_mapping.yaml"
    predicate_map.write_text("predicate mappings: []\n", encoding="utf-8")
    return schema, predicate_map


def test_sibling_imports_ignores_prefixed_imports(tmp_path):
    """``linkml:types`` comes from the installed runtime, not from ``data/raw``."""
    from kg_microbe.utils.biolink_model import sibling_imports

    schema, _ = _write_model(tmp_path, ["linkml:types", "attributes"])
    assert [p.name for p in sibling_imports(schema)] == ["attributes.yaml"]


def test_the_real_pinned_model_declares_the_files_download_yaml_fetches():
    """
    The guard is only worth having if it reads the model we actually ship.

    A hand-written fixture would keep passing after Biolink adds a second
    sibling import, which is the case this is meant to catch.
    """
    from kg_microbe.utils.biolink_model import DEFAULT_SCHEMA_PATH, sibling_imports

    if not DEFAULT_SCHEMA_PATH.is_file():
        import pytest

        pytest.skip("data/raw/biolink-model.yaml not downloaded")
    declared = {e.get("local_name") for e in _biolink_entries()}
    for path in sibling_imports(DEFAULT_SCHEMA_PATH):
        assert path.name in declared, f"model imports {path.name}, download.yaml does not fetch it"


def test_prepare_kgx_names_the_missing_import_rather_than_failing_inside_linkml(tmp_path, monkeypatch):
    """
    The old preflight passed, then linkml raised a bare path with no guidance.

    Worse, the message it did emit pointed at `kg download -t schema` -- the one
    command that could not supply the file, because it was never declared (#939).
    """
    import pytest

    from kg_microbe.utils.biolink_model import prepare_kgx

    schema, predicate_map = _write_model(tmp_path, ["linkml:types", "attributes"])
    monkeypatch.setenv("KG_MICROBE_BIOLINK_MODEL", str(schema))
    monkeypatch.setenv("KG_MICROBE_BIOLINK_PREDICATE_MAP", str(predicate_map))
    with pytest.raises(FileNotFoundError, match="attributes.yaml"):
        prepare_kgx()


def test_sibling_imports_reads_flow_style_too(tmp_path):
    """
    A regex over the ``imports:`` block returned nothing for this form.

    Both spellings are valid YAML and mean the same thing, so a guard that reads
    one and silently returns ``[]`` for the other restores the #939 failure with
    no signal that it stopped working (#942).
    """
    from kg_microbe.utils.biolink_model import sibling_imports

    schema = tmp_path / "biolink-model.yaml"
    schema.write_text("id: https://example.org/t\nname: t\nimports: [linkml:types, attributes]\n", encoding="utf-8")
    assert [p.name for p in sibling_imports(schema)] == ["attributes.yaml"]


def test_sibling_imports_tolerates_a_model_with_no_imports(tmp_path):
    """A model that imports nothing is not an error, and must not be one."""
    from kg_microbe.utils.biolink_model import sibling_imports

    schema = tmp_path / "biolink-model.yaml"
    schema.write_text("id: https://example.org/t\nname: t\n", encoding="utf-8")
    assert sibling_imports(schema) == []
