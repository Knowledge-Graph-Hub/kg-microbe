"""Genuine zero-cohort GOLD native contracts for inert dependency-chain fixtures."""

import os
import shutil
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from kg_microbe.transform_utils.gold.crosswalk_quarantine import REQUIRED_INPUTS, CrosswalkQuarantine
from kg_microbe.transform_utils.gold.selected_taxon_aliases import REQUIRED_INPUTS as ALIAS_REQUIRED_INPUTS
from kg_microbe.transform_utils.gold.taxon_dispositions import (
    REQUIRED_INPUTS as TAXON_REQUIRED_INPUTS,
)
from kg_microbe.transform_utils.gold.taxon_dispositions import (
    TaxonDispositions,
)

FIXTURES = Path(__file__).parent / "resources/gold_abscess"


def prepare_empty_gold_crosswalk_inputs(transform):
    """Read actual empty source files and real policies; never fabricate a reviewed cohort receipt."""
    raw = transform.input_base_dir / "gold"
    raw.mkdir(parents=True, exist_ok=True)
    for kind in ("nodes", "edges"):
        original, selected = FIXTURES / f"empty_{kind}.tsv", raw / f"GOLD_{kind}.tsv"
        if not selected.exists():
            shutil.copyfile(original, selected)
        assert selected.read_bytes() == original.read_bytes(), "Nonempty GOLD inputs require actual producer emission"
    transform._crosswalk_quarantine = None
    transform._recorded_crosswalk_inputs = None
    transform._recorded_native_guard = None
    transform._recorded_native_admission = None
    transform._native_publication_failed = False
    with ExitStack() as stack, patch.dict(os.environ, {"GOLD_APPLY_TAXON_TRIM": "false"}):
        scope = CrosswalkQuarantine(transform, stack, raw / "GOLD_nodes.tsv", raw / "GOLD_edges.tsv")
        assert not scope.active, "This inert fixture must contain no reviewed native observations"
        transform._crosswalk_quarantine = scope
        taxonomy = TaxonDispositions(transform, stack, scope)
        transform._taxon_dispositions = taxonomy
        # A real empty native selection has no output declarations or claims;
        # inert dependency graph members are already present at the caller.
        taxonomy.finish()
        scope.finish()
    transform.verify_consumed_inputs()
    return (*REQUIRED_INPUTS, *TAXON_REQUIRED_INPUTS, *ALIAS_REQUIRED_INPUTS)
