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


#: How each shipped config relates to ``merge.yaml``, as
#: ``{name: (extra dirs, missing dirs)}``. ``merge.yaml`` is the baseline and
#: ``merge.minimal.yaml`` is exempt — it is a deliberately tiny 3-source config,
#: not a variant of the standard graph.
#:
#: A table rather than one test per config, because the failure being fixed is
#: that coverage was opt-in: the relational invariants named the configs someone
#: remembered, and ``merge.no_metatraits.yaml`` — added later — inherited none
#: and drifted seven sources behind (#827). ``test_every_config_has_a_declared
#: _relationship`` closes that by making an undeclared config a failure.
CONFIG_RELATIONS = {
    "merge_bakta.yaml": ({"bakta", "cog", "kegg"}, set()),
    "merge.noprego.yaml": (set(), {"prego_habitat"}),
    "merge.prego-full.yaml": ({"prego"}, {"prego_habitat"}),
    "merge.no_metatraits.yaml": (set(), {"metatraits", "metatraits_gtdb"}),
}
BASELINE_CONFIG = "merge.yaml"
EXEMPT_CONFIGS = {"merge.minimal.yaml"}


def test_every_config_has_a_declared_relationship():
    """
    A config shipped without a declared relationship gets no drift coverage.

    This is the general defect behind #827, not just the one config that
    exhibited it: the relational invariants below enumerate configs by hand, so
    anything added later is silently uncovered. Deriving the expected set from
    the filesystem makes adding a config *force* a decision about what it is.
    """
    on_disk = {p.name for p in _configs()}
    declared = set(CONFIG_RELATIONS) | EXEMPT_CONFIGS | {BASELINE_CONFIG}
    assert on_disk - declared == set(), (
        f"merge configs with no declared relationship: {sorted(on_disk - declared)}. "
        "Add them to CONFIG_RELATIONS (or EXEMPT_CONFIGS if they are not variants "
        "of the standard graph), so they are covered by the drift check."
    )
    assert declared - on_disk - EXEMPT_CONFIGS - {BASELINE_CONFIG} == set(), (
        f"CONFIG_RELATIONS names configs that no longer exist: "
        f"{sorted(declared - on_disk - EXEMPT_CONFIGS - {BASELINE_CONFIG})}"
    )


@pytest.mark.parametrize("name", sorted(CONFIG_RELATIONS))
def test_each_variant_differs_from_the_standard_graph_only_as_declared(name):
    """
    Every variant is `merge.yaml` plus its extras, minus its exclusions.

    Both directions matter and the missing one is what bites: an *extra* is
    visible when the merge runs, whereas a source silently absent from a variant
    produces a graph that looks fine and is quietly incomplete. That is how
    `merge_bakta.yaml` and later `merge.no_metatraits.yaml` each fell seven
    sources behind.
    """
    standard = _active_dirs(REPO_ROOT / BASELINE_CONFIG)
    variant = _active_dirs(REPO_ROOT / name)
    expected_extra, expected_missing = CONFIG_RELATIONS[name]

    assert variant - standard == expected_extra, (
        f"{name} has unexpected extras: {sorted((variant - standard) - expected_extra)}"
    )
    assert standard - variant == expected_missing, (
        f"{name} has fallen behind {BASELINE_CONFIG}: missing {sorted((standard - variant) - expected_missing)}"
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


def test_stale_sibling_artifacts_are_reported(tmp_path, capsys):
    """
    `data/merged/` accumulates, and consumers read whatever is there (#828).

    A reviewer of #826 read `merged-kg_default_{nodes,edges}.tsv` — seven months
    old, 1.2 GB, beside the current tarball — and reported 1.51M/6.13M against
    the tarball's 2.85M/14.66M, flagging it as an unexplained discrepancy. Both
    were right about different files; only the mtime distinguished them.
    """
    from kg_microbe.merge_utils.merge_kg import _warn_about_stale_siblings

    written = tmp_path / "merged-kg.tar.gz"
    written.write_bytes(b"current")
    leftover = tmp_path / "merged-kg_default_nodes.tsv"
    leftover.write_bytes(b"old")

    _warn_about_stale_siblings(tmp_path, {written})
    out = capsys.readouterr().out
    assert "merged-kg_default_nodes.tsv" in out
    assert "merged-kg.tar.gz" not in out, "the artifact this run wrote must not be reported as stale"


def test_a_clean_output_directory_reports_nothing(tmp_path, capsys):
    """No warning when there is nothing to warn about — noise trains people to ignore it."""
    from kg_microbe.merge_utils.merge_kg import _warn_about_stale_siblings

    written = tmp_path / "merged-kg.tar.gz"
    written.write_bytes(b"current")
    _warn_about_stale_siblings(tmp_path, {written})
    assert capsys.readouterr().out == ""


def test_the_stats_yaml_is_not_reported_as_a_stale_artifact(tmp_path, capsys):
    """
    `merged-kg_stats.yaml` sits in the same directory and is not a graph copy.

    Reporting it would be a false positive on every single merge, which is the
    reliable way to get a warning ignored.
    """
    from kg_microbe.merge_utils.merge_kg import _warn_about_stale_siblings

    written = tmp_path / "merged-kg.tar.gz"
    written.write_bytes(b"current")
    (tmp_path / "merged-kg_stats.yaml").write_text("nodes: 1\n")
    _warn_about_stale_siblings(tmp_path, {written})
    assert capsys.readouterr().out == ""
