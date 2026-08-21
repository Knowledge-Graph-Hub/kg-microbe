"""Configure KGX/BMT to use KG-Microbe's pinned local Biolink model."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SCHEMA_PATH = REPO_ROOT / "data" / "raw" / "biolink-model.yaml"
DEFAULT_PREDICATE_MAP_PATH = REPO_ROOT / "data" / "raw" / "predicate_mapping.yaml"


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
    predicate_map_path = _configured_path(
        "KG_MICROBE_BIOLINK_PREDICATE_MAP", DEFAULT_PREDICATE_MAP_PATH
    )
    missing = [path for path in (schema_path, predicate_map_path) if not path.is_file()]
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
            super().__init__(
                schema=str(schema_path) if schema is None else schema,
                predicate_map=str(predicate_map_path) if predicate_map is None else predicate_map,
                **kwargs,
            )

    bmt.Toolkit = LocalToolkit
