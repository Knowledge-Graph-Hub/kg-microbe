"""Tests for the shared LPSN accepted-name resolver."""

from unittest import TestCase

from kg_microbe.utils.lpsn_utils import LPSN_MAX_SYNONYM_HOPS, resolve_accepted_records

_CORRECT = "VP; sp. nov.; validly published under the ICNP; correct name"
_SYNONYM = "VP; sp. nov.; validly published under the ICNP; synonym"


def _rows(*specs):
    """Build a ``{record_no: gss_row}`` mapping from (no, status, link) triples."""
    return {no: {"record_no": no, "status": status, "record_lnk": link} for no, status, link in specs}


class ResolveAcceptedRecordsTest(TestCase):
    """One resolver, shared by bacdive (#684) and microbedecoder (#746)."""

    def test_a_synonym_resolves_to_its_accepted_record(self):
        """The base case both transforms need."""
        mapping = resolve_accepted_records(_rows(("1", _SYNONYM, "2"), ("2", _CORRECT, "")))
        self.assertEqual(mapping, {"1": "2"})

    def test_a_chain_is_followed(self):
        """250 synonyms need two hops on the shipped GSS and 2 need three."""
        mapping = resolve_accepted_records(_rows(("1", _SYNONYM, "2"), ("2", _SYNONYM, "3"), ("3", _CORRECT, "")))
        self.assertEqual(mapping["1"], "3")

    def test_a_correct_name_is_absent_from_the_mapping(self):
        """Most records are already current and must not be remapped."""
        self.assertEqual(resolve_accepted_records(_rows(("1", _CORRECT, ""))), {})

    def test_a_dead_end_is_absent_rather_than_guessed(self):
        """192 GSS rows are non-current with no link; there is nothing to point at."""
        self.assertEqual(resolve_accepted_records(_rows(("1", _SYNONYM, ""))), {})

    def test_a_cycle_terminates_and_yields_nothing(self):
        """No cycles exist in the shipped GSS, but a future release could add one."""
        self.assertEqual(resolve_accepted_records(_rows(("1", _SYNONYM, "2"), ("2", _SYNONYM, "1"))), {})

    def test_an_unbounded_chain_cannot_hang(self):
        """
        The hop cap is the backstop, not the cycle guard.

        An unbounded walk's failure mode is a hang, which costs a CI job its
        whole budget and reports a timeout instead of the defect (#742).
        """
        long_chain = [(str(i), _SYNONYM, str(i + 1)) for i in range(LPSN_MAX_SYNONYM_HOPS + 10)]
        mapping = resolve_accepted_records(_rows(*long_chain))
        self.assertEqual(mapping, {}, "a chain longer than the cap resolves to nothing, without hanging")

    def test_a_link_to_a_missing_record_is_survivable(self):
        """GSS links can dangle; that must not raise."""
        self.assertEqual(resolve_accepted_records(_rows(("1", _SYNONYM, "999"))), {})
