"""A separator inside brackets is not a separator (#838)."""

import pytest

from kg_microbe.transform_utils.microbedecoder.utils import (
    split_multivalue,
    split_multivalue_comma_only,
)

#: The four labels #838 found cut in half, with their occurrence counts. Each
#: paired exactly with a fragment carrying an orphan `)` — same count, same
#: source column — which is what proved they were one string each.
SPLIT_IN_HALF = [
    ("O/129 (2,4-diamino-6,7-di-iso-propylpteridine phosphate)", 1212, "Antibiotic_resistance/sensitivity"),
    ("#Herbaceous plants (Grass, Crops)", 1021, "Isolation_category_3"),
    ("#Bovinae (Cow, Cattle)", 200, "Isolation_category_3"),
    ("#Suidae (Pig, Swine)", 156, "Isolation_category_3"),
]


@pytest.mark.parametrize("label,occurrences,column", SPLIT_IN_HALF, ids=lambda v: str(v)[:28])
def test_a_bracketed_comma_does_not_split_the_label(label, occurrences, column):
    """
    2,589 occurrences across four labels, each becoming two unmappable "terms".

    MediaIngredientMech hit the same defect on the ingredient side (its #308)
    and had to tombstone the fragments after the fact — evidence that repairing
    downstream is the expensive way to handle this.
    """
    assert split_multivalue(label) == [label], f"{column} label was split ({occurrences} occurrences affected)"


def test_genuine_multi_values_still_split():
    """
    The fix must not turn the splitter off.

    Bergey / VPI end-product columns really are comma-separated lists, and
    collapsing them would silently drop every value after the first.
    """
    assert split_multivalue("acetate, lactate, ethanol") == ["acetate", "lactate", "ethanol"]
    assert split_multivalue("acetate; lactate") == ["acetate", "lactate"]


def test_a_separator_after_a_closed_bracket_still_splits():
    """Depth returns to zero, so the list continues normally."""
    assert split_multivalue("#Bovinae (Cow, Cattle), acetate") == ["#Bovinae (Cow, Cattle)", "acetate"]


def test_nested_brackets_are_tracked():
    """One closer must not re-open splitting inside an outer bracket."""
    assert split_multivalue("a (b (c, d), e), f") == ["a (b (c, d), e)", "f"]


def test_an_unclosed_bracket_keeps_the_remainder_whole():
    """
    Conservative on malformed input.

    With the structure broken we cannot tell where a value ends, and inventing
    a boundary is exactly what produced the orphan fragments.
    """
    assert split_multivalue("foo (bar, baz") == ["foo (bar, baz"]


def test_a_stray_closer_does_not_disable_later_splitting():
    """
    Depth is clamped at zero.

    Letting it go negative would make every subsequent separator look nested,
    silently collapsing the rest of the cell into one value.
    """
    assert split_multivalue("foo) , bar") == ["foo)", "bar"]


def test_the_comma_only_variant_still_preserves_gtdb_semicolons():
    """
    `GTDB_ID` uses semicolons as rank separators (#655).

    Splitting on them shredded one CURIE into three orphans, which is why the
    comma-only variant exists; the bracket change must not disturb it.
    """
    lineage = "d__Bacteria;g__Bacillus;s__Bacillus subtilis"
    assert split_multivalue_comma_only(lineage) == [lineage]


def test_the_comma_only_variant_is_also_bracket_aware():
    """Both splitters share the walk, so neither can regress independently."""
    assert split_multivalue_comma_only("#Bovinae (Cow, Cattle)") == ["#Bovinae (Cow, Cattle)"]


@pytest.mark.parametrize("empty", ["", "  ", "NA", "na", None])
def test_empty_markers_still_yield_nothing(empty):
    """The rewrite must not turn a blank cell into a one-element list."""
    assert split_multivalue(empty) == []
