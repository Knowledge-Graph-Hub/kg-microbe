"""
Unit tests for the local METPO alias override layer.

The ``mappings/metpo_alias_mappings.tsv`` file (under
``kg_microbe/transform_utils/metatraits/mappings/``) is loaded by
``_load_metpo_alias_overrides`` and overlaid on top of the remote-fetched
METPO sheet so curator edits take effect on the next transform run without
requiring an upstream berkeleybop/metpo release.

These tests exercise the loader in isolation (no network) by stubbing the
METPO tree with a minimal node set.
"""

from __future__ import annotations

from typing import Dict

from kg_microbe.utils.mapping_file_utils import (
    LOCAL_METPO_ALIAS_OVERRIDES_PATH,
    MetpoTreeNode,
    _load_metpo_alias_overrides,
)


def _stub_nodes(curies_in_tree: list[str]) -> Dict[str, MetpoTreeNode]:
    """Build a minimal METPO tree containing only the requested CURIEs."""
    nodes: Dict[str, MetpoTreeNode] = {}
    for curie in curies_in_tree:
        nodes[curie] = MetpoTreeNode(iri=curie, label=curie, biolink_equivalent="")
    return nodes


def test_overrides_applied_when_object_id_in_tree() -> None:
    """A high-confidence ManualMappingCuration row whose object_id is in
    the loaded METPO tree appears in the override dict."""
    nodes = _stub_nodes(["METPO:2000702", "METPO:2000703"])
    overrides = _load_metpo_alias_overrides(nodes, range_to_predicate={})

    assert "has growth temperature minimum" in overrides
    assert overrides["has growth temperature minimum"]["curie"] == "METPO:2000702"
    assert overrides["has growth temperature minimum"]["label"] == "has minimum temperature value"


def test_overrides_skipped_when_metpo_id_missing() -> None:
    """Rows whose object_id is not yet in the METPO tree (proposed-but-
    unminted) are silently skipped — the kgmicrobe.* placeholder path
    stays the correct destination for those terms."""
    nodes = _stub_nodes([])  # empty tree — every row should be skipped
    overrides = _load_metpo_alias_overrides(nodes, range_to_predicate={})
    assert overrides == {}


def test_normalized_and_raw_label_keys_both_emitted() -> None:
    """The override dict carries both ``subject_label_normalized`` and
    ``subject_label`` keys when they differ, so case-mismatched callers
    still find the override."""
    nodes = _stub_nodes(["METPO:2000708"])
    overrides = _load_metpo_alias_overrides(nodes, range_to_predicate={})
    # Row 3 of the TSV: subject_label='has NaCl concentration minimum',
    # subject_label_normalized='has nacl concentration minimum'.
    assert "has NaCl concentration minimum" in overrides
    assert "has nacl concentration minimum" in overrides
    assert overrides["has NaCl concentration minimum"]["curie"] == "METPO:2000708"


def test_override_file_exists_and_is_nonempty() -> None:
    """Sanity check: the override TSV is present in the repo and has rows.
    Without this the override layer is dead code."""
    assert LOCAL_METPO_ALIAS_OVERRIDES_PATH.is_file(), (
        f"Expected {LOCAL_METPO_ALIAS_OVERRIDES_PATH} to exist."
    )
    with LOCAL_METPO_ALIAS_OVERRIDES_PATH.open("r", encoding="utf-8") as fh:
        # 1 header + at least 1 data row
        assert sum(1 for _ in fh) >= 2
