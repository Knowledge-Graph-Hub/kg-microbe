"""The ontologies output a fixture needs beside a source that declares it (#1511)."""

from pathlib import Path
from typing import Optional


def prepare_declared_ontologies_output(transform) -> Optional[Path]:
    """
    Give a source that lists ``ontologies`` in ``TRANSFORM_INPUTS`` that output beside its own.

    Finalization reads the ontologies output's declarations for such a source
    and refuses to run without them. This one is header-only, so it declares
    nothing and the fixture's external references resolve as they would
    against an ontologies output that does not mention them.

    A fixture that needs the merge gate to accept the upstream must build a
    finalized one instead (``prepare_source(tmp_path, "ontologies")``); this
    leaves any ontologies output already there alone.

    :param transform: The producer a fixture is about to finalize.
    :return: The nodes file written, or None if none was needed.
    """
    if "ontologies" not in getattr(type(transform), "TRANSFORM_INPUTS", ()):
        return None
    directory = Path(transform.output_base_dir) / "ontologies"
    if any(directory.glob("*nodes.tsv")):
        return None
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "fixture_nodes.tsv"
    if not path.exists():
        path.write_text("id\tcategory\tname\n", encoding="utf-8")
    return path
