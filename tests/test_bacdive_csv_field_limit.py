"""csv_field_limit_at_least raises CSV's limit for one read and always restores the caller's (#1575)."""

import csv

import pytest

from kg_microbe.transform_utils.bacdive.csv_field_limit import csv_field_limit_at_least


@pytest.fixture(autouse=True)
def default_limit():
    """Start each test at CSV's default and leave the caller's limit as it was."""
    previous = csv.field_size_limit(131_072)
    yield
    csv.field_size_limit(previous)


def test_the_limit_is_raised_inside_the_block_and_restored_after():
    """A file larger than the default lifts the limit to its size, for the block only."""
    with csv_field_limit_at_least(500_000):
        assert csv.field_size_limit() == 500_000
    assert csv.field_size_limit() == 131_072


def test_a_higher_caller_limit_is_never_lowered():
    """A small file does not shrink a limit the caller already raised."""
    csv.field_size_limit(1_000_000)
    with csv_field_limit_at_least(10):
        assert csv.field_size_limit() == 1_000_000
    assert csv.field_size_limit() == 1_000_000


def test_the_limit_is_restored_when_the_read_fails():
    """A verification failure inside the block does not leave the limit raised."""
    with pytest.raises(ValueError, match="read failed"), csv_field_limit_at_least(500_000):
        raise ValueError("read failed")
    assert csv.field_size_limit() == 131_072
