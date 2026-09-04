"""Configure KGX/BMT to use KG-Microbe's pinned local Biolink model."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SCHEMA_PATH = REPO_ROOT / "data" / "raw" / "biolink-model.yaml"
DEFAULT_PREDICATE_MAP_PATH = REPO_ROOT / "data" / "raw" / "predicate_mapping.yaml"


def sibling_imports(schema_path: Path) -> list[Path]:
    """
    Return the files ``schema_path`` imports from its own directory.

    ``biolink-model.yaml`` declares ``imports: [linkml:types, attributes]``.
    A prefixed name such as ``linkml:types`` is resolved from the installed
    linkml runtime, but a bare one is a sibling file that must be downloaded
    alongside the model -- and ``attributes.yaml`` never was, so the pinned
    model raised ``FileNotFoundError`` from deep inside linkml on every load
    (#939). Reporting it here names the missing file and the fix instead.

    The list is read with a real YAML parser rather than a regex over the
    ``imports:`` block. A regex handles today's block style and silently returns
    nothing for the equally valid flow style, which would restore the #939
    failure with no signal that the guard had stopped working -- a silent
    degradation in the guard against silent degradation (#942). The parse costs
    about 50 ms with ``CSafeLoader`` against the 264 ms BMT already spends
    building a ``SchemaView`` from the same file, and runs once per pipeline
    invocation, not once per record.

    :param schema_path: Path to the local Biolink model YAML.
    :return: Paths the model expects beside itself, whether or not they exist.
    """
    if not schema_path.is_file():
        return []
    import yaml

    # CSafeLoader is the libyaml-backed equivalent of SafeLoader and constructs
    # no arbitrary objects; ruff's S506 cannot see that through getattr.
    loader = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
    model = yaml.load(schema_path.read_text(encoding="utf-8"), Loader=loader)  # noqa: S506
    if not isinstance(model, Mapping):
        return []
    declared = model.get("imports") or []
    if isinstance(declared, str):
        declared = [declared]
    names = [str(name) for name in declared if isinstance(name, str)]
    return [schema_path.parent / f"{name}.yaml" for name in names if name and ":" not in name]


def _configured_path(env_name: str, default: Path) -> Path:
    """Return an environment override or a repository-relative default."""
    return Path(os.environ.get(env_name, default)).expanduser().resolve()


def prepare_kgx() -> None:
    """
    Install a local-default BMT Toolkit before importing KGX.

    KGX 2.x creates ``Toolkit()`` at module import time. BMT's defaults are
    remote URLs for both its schema and predicate map, so importing KGX can
    otherwise perform network I/O. Replacing BMT's exported Toolkit class
    before KGX imports preserves explicit caller arguments while redirecting
    its no-argument construction to pinned repository files.
    """
    schema_path = _configured_path("KG_MICROBE_BIOLINK_MODEL", DEFAULT_SCHEMA_PATH)
    predicate_map_path = _configured_path("KG_MICROBE_BIOLINK_PREDICATE_MAP", DEFAULT_PREDICATE_MAP_PATH)
    required = [schema_path, predicate_map_path, *sibling_imports(schema_path)]
    missing = [path for path in required if not path.is_file()]
    if missing:
        formatted = ", ".join(str(path) for path in missing)
        raise FileNotFoundError(
            f"Pinned Biolink input(s) missing: {formatted}. Run `kg download -t schema` first "
            "or set KG_MICROBE_BIOLINK_MODEL and KG_MICROBE_BIOLINK_PREDICATE_MAP."
        )

    import bmt

    current = bmt.Toolkit
    if getattr(current, "_kg_microbe_local_defaults", None) == (
        str(schema_path),
        str(predicate_map_path),
    ):
        return

    class LocalToolkit(current):
        """BMT Toolkit whose omitted inputs resolve to pinned local files."""

        _kg_microbe_local_defaults = (str(schema_path), str(predicate_map_path))

        def __init__(
            self,
            schema: Any = None,
            predicate_map: Any = None,
            **kwargs: Any,
        ) -> None:
            """Substitute the pinned local files for any argument left unset."""
            resolved_schema = str(schema_path) if schema is None else schema
            resolved_predicate_map = predicate_map_path if predicate_map is None else predicate_map

            # BMT 1.4.8 (the version resolved by KGX 2.x in a clean install)
            # calls requests.get() for every string predicate map, including a
            # local path. Newer BMT releases accept local paths directly. Load
            # local/file/mapping inputs here so both versions stay offline-safe.
            predicate_payload = None
            if isinstance(resolved_predicate_map, Mapping):
                predicate_payload = dict(resolved_predicate_map)
            elif hasattr(resolved_predicate_map, "read"):
                import yaml

                predicate_payload = yaml.safe_load(resolved_predicate_map)
            elif isinstance(resolved_predicate_map, (str, os.PathLike)):
                local_path = Path(resolved_predicate_map)
                if local_path.is_file():
                    import yaml

                    predicate_payload = yaml.safe_load(local_path.read_text(encoding="utf-8"))

            if predicate_payload is not None:
                from linkml_runtime.utils.schemaview import SchemaView

                self.view = SchemaView(resolved_schema)
                self.pmap = predicate_payload
                return

            super().__init__(
                schema=resolved_schema,
                predicate_map=resolved_predicate_map,
                **kwargs,
            )

    bmt.Toolkit = LocalToolkit
