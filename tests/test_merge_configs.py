"""
Static checks over the shipped merge configs.

`test_merge_source_subset.py` tests the ``-s`` subset plumbing against a
synthetic config in ``tmp_path``; nothing validated the real YAMLs. Three things
went wrong for want of that, all in one change:

* **A config read a directory no transform writes.** ``merge.yaml`` was pointed at
  ``data/transformed/prego_habitat/`` while ``PREGO_SHAPES`` still defaulted to
  ``all``, which writes ``prego/``. KGX skips a missing input silently, so the
  default pipeline produced a graph with no PREGO edges and no warning.
* **A config stopped parsing.** ``merge_bakta.yaml`` was rebuilt by
  regex-uncommenting blocks, which also uncommented ``name:``/``input:``/
  ``filename:`` lines belonging to the MONDO and HP entries. Caught only by
  running ``yaml.safe_load`` by hand.
* **Two configs drifted.** ``merge_bakta.yaml`` is meant to be ``merge.yaml`` plus
  the genome-annotation cluster; it had silently fallen seven sources behind.

These run without any data on disk, so they hold in CI.
"""

import re
from pathlib import Path

import pytest
import yaml

from kg_microbe.transform import DATA_SOURCES

REPO_ROOT = Path(__file__).parent.parent

#: Output dirs that are not simply ``data/transformed/<registered source>/``.
#: Only ``prego_habitat``, written by ``PREGO_SHAPES=habitat``. ``bakta`` was listed
#: here too, which changed nothing — it is a registered ``DATA_SOURCES`` key — while
#: implying to a reader that it is not one.
KNOWN_VARIANT_DIRS = {"prego_habitat"}


def _configs():
    """
    Every shipped merge config.

    :return: Sorted list of ``merge*.yaml`` paths, excluding generated stats files.
    """
    return sorted(p for p in REPO_ROOT.glob("merge*.yaml") if "stats" not in p.name and "merged-kg" not in p.name)


def _active_dirs(path: Path) -> set:
    """
    Transform output dirs a config actually reads.

    Commented-out entries do not count — reading them is what made an earlier
    audit report 22 sources where the config had 14.

    The pattern is deliberately permissive about the characters in a directory
    name. An earlier ``[a-z_]+`` had to be followed by ``/``, so any name holding a
    digit, hyphen or capital matched *nothing* and became invisible — the guard
    then passed a config pointing at an unproducible directory, which is the exact
    thing it exists to catch. Better to over-capture and let the allowlist
    comparison report an unknown than to silently skip it.

    :param path: Merge config path.
    :return: Set of directory names under ``data/transformed/``.
    """
    dirs = set()
    for line in path.read_text().splitlines():
        if line.lstrip().startswith("#"):
            continue
        match = re.search(r"data/transformed/([^/\s]+)/", line)
        if match:
            dirs.add(match.group(1))
    return dirs


def test_at_least_one_config_is_present():
    """A glob that silently matches nothing would make every check below vacuous."""
    assert _configs(), "no merge*.yaml found — the other checks would pass on an empty set"


@pytest.mark.parametrize("config", _configs(), ids=lambda p: p.name)
def test_every_config_parses(config: Path):
    """A config that does not parse is not a config."""
    loaded = yaml.safe_load(config.read_text())
    assert isinstance(loaded, dict), f"{config.name} did not parse to a mapping"
    assert loaded.get("merged_graph", {}).get("source"), f"{config.name} declares no sources"


@pytest.mark.parametrize("config", _configs(), ids=lambda p: p.name)
def test_every_input_dir_is_producible(config: Path):
    """
    Every directory a config reads must be one some transform writes.

    This is the check that would have caught the PREGO mismatch: a config reading
    a directory nothing produces yields a silently smaller graph, because KGX
    skips missing inputs without complaint.
    """
    registered = set(DATA_SOURCES) | KNOWN_VARIANT_DIRS
    unknown = _active_dirs(config) - registered
    assert not unknown, (
        f"{config.name} reads {sorted(unknown)}, which no registered transform writes. "
        f"Registered: {sorted(DATA_SOURCES)}; known variants: {sorted(KNOWN_VARIANT_DIRS)}."
    )


def test_the_default_merge_reads_what_the_default_transform_writes():
    """
    The two defaults have to agree about PREGO.

    They disagreed: `merge.yaml` read `prego_habitat/` while `PREGO_SHAPES`
    defaulted to `all`, which writes `prego/`. Nothing failed — KGX skips the
    missing input — so `kg transform` followed by `kg merge` produced a graph with
    no PREGO edges at all.
    """
    from kg_microbe.transform_utils.prego.prego import PregoTransform

    default_dir = PregoTransform(input_dir=REPO_ROOT / "data" / "raw", output_dir=REPO_ROOT / "data" / "transformed")
    merge_dirs = _active_dirs(REPO_ROOT / "merge.yaml")
    prego_dirs = {d for d in merge_dirs if d.startswith("prego")}

    assert prego_dirs == {default_dir.output_dir.name}, (
        f"merge.yaml reads {sorted(prego_dirs)} but the default transform writes {default_dir.output_dir.name!r}"
    )


def test_the_bakta_config_is_the_standard_graph_plus_the_annotation_cluster():
    """
    `merge_bakta.yaml` is defined as `merge.yaml` plus bakta/cog/kegg.

    Stated in its header and nowhere enforced, it had drifted seven sources
    behind: no gtdb, lpsn, lpsn_api, metatraits, metatraits_gtdb, microbedecoder
    or prego.
    """
    standard = _active_dirs(REPO_ROOT / "merge.yaml")
    bakta = _active_dirs(REPO_ROOT / "merge_bakta.yaml")

    assert bakta - standard == {"bakta", "cog", "kegg"}, f"unexpected extras: {sorted(bakta - standard)}"
    assert not standard - bakta, f"merge_bakta.yaml has fallen behind merge.yaml: missing {sorted(standard - bakta)}"


def test_the_prego_variants_differ_only_in_the_prego_source():
    """
    `merge.prego-full.yaml` and `merge.noprego.yaml` are `merge.yaml` ± PREGO.

    Keeping that true is what stops a source added to the standard graph from
    quietly missing out of the variants.
    """
    standard = _active_dirs(REPO_ROOT / "merge.yaml")
    full = _active_dirs(REPO_ROOT / "merge.prego-full.yaml")
    none = _active_dirs(REPO_ROOT / "merge.noprego.yaml")

    assert full - standard == {"prego"}, f"prego-full extras: {sorted(full - standard)}"
    assert standard - full == {"prego_habitat"}, f"prego-full is missing: {sorted(standard - full)}"
    assert not none - standard, f"noprego extras: {sorted(none - standard)}"
    assert standard - none == {"prego_habitat"}, f"noprego differs by more than PREGO: {sorted(standard - none)}"


@pytest.mark.parametrize("odd_dir", ["kegg2", "go-terms", "Ontologies"], ids=["digit", "hyphen", "capital"])
def test_an_oddly_named_unproducible_dir_is_caught(tmp_path, odd_dir):
    """
    The extractor must not go blind on names outside ``[a-z_]``.

    With the original pattern each of these matched nothing, so a config reading
    them passed the producibility check silently.
    """
    config = tmp_path / "merge.odd.yaml"
    config.write_text(
        "merged_graph:\n  source:\n    x:\n      input:\n        filename:\n"
        f"          - data/transformed/{odd_dir}/nodes.tsv\n"
    )
    assert _active_dirs(config) == {odd_dir}, "the dir must be visible to the guard"
    assert odd_dir not in set(DATA_SOURCES) | KNOWN_VARIANT_DIRS, "and recognised as unproducible"
