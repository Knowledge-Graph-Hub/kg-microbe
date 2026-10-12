"""Keep immutable deposit indexing cheap at query checkpoints without losing native occurrence checks."""

from collections.abc import Mapping
from types import MappingProxyType

import pytest

from kg_microbe.transform_utils.bacdive import taxonomy_evidence as taxonomy
from kg_microbe.utils.source_finalization import SourceFinalizationRequired
from tests.test_bacdive_taxonomy_evidence import produce


def test_real_native_queries_and_repeated_admission_never_serialize_whole_deposit_indexes(tmp_path, monkeypatch):
    """Actual resolver queries retain the native guard while avoiding new source-wide index hashing."""
    actual_json = taxonomy._json
    actual_resolve = taxonomy.TaxonomyEvidence.resolve_deposits
    actual_ancestors = taxonomy.FreshAncestryAuthority.ancestors
    observed = {"guard": None, "queries": 0, "checkpoints": 0, "touched_deposit_hashes": 0}

    def track_json(value):
        """Reject whole-index serialization, including same-content copied mappings, not small touched tuples."""
        guard = observed["guard"]
        if guard is not None:
            for index in (guard._deposit_occurrences, guard._deposit_occurrence_seals):
                if value is index or isinstance(value, Mapping) and dict(value) == dict(index):
                    raise AssertionError("whole native deposit index serialized at a query/admission checkpoint")
            if any(value is pairs for pairs in guard._deposit_occurrences.values()):
                observed["touched_deposit_hashes"] += 1
        return actual_json(value)

    def resolve(self, *args, **kwargs):
        """Start instrumentation after one-time native indexing, before any actual deposit query."""
        observed["guard"] = self
        assert len(self._deposit_occurrences) > 1
        return actual_resolve(self, *args, **kwargs)

    def ancestors(self, *args, **kwargs):
        """Count actual owned authority calls and retain their original results and query evidence."""
        observed["queries"] += 1
        for _ in range(3):
            self.admission.verify(metadata_only=True)
            observed["checkpoints"] += 1
        return actual_ancestors(self, *args, **kwargs)

    monkeypatch.setattr(taxonomy, "_json", track_json)
    monkeypatch.setattr(taxonomy.TaxonomyEvidence, "resolve_deposits", resolve)
    monkeypatch.setattr(taxonomy.FreshAncestryAuthority, "ancestors", ancestors)
    transform, _, _, _ = produce(tmp_path, monkeypatch)
    guard = transform._taxonomy_evidence_guard
    assert observed["guard"] is guard
    assert observed["queries"] > 0
    assert guard.contract["ancestry"]["actual_queries"]["computed_queries"]
    assert guard.contract["ancestry"]["callback_demand_counts"]
    for _ in range(40):
        guard.admission.verify(metadata_only=True)
        observed["checkpoints"] += 1
    assert observed["checkpoints"] == 40 + 3 * observed["queries"]
    assert observed["touched_deposit_hashes"] > 0
    # This genuine full checkpoint still verifies all native evidence and the
    # exact output; only the newly introduced index's repeated hashing is barred.
    transform.verify_consumed_inputs()


def test_deposit_index_and_all_nested_occurrence_values_are_immutable(tmp_path, monkeypatch):
    """A caller cannot alter an original mapping, tuple list, pair or per-deposit digest in place."""
    transform, _, _, _ = produce(tmp_path, monkeypatch)
    guard = transform._taxonomy_evidence_guard
    index, seals = guard._deposit_occurrences, guard._deposit_occurrence_seals
    assert isinstance(index, MappingProxyType) and isinstance(seals, MappingProxyType)
    assert index and set(index) == set(seals)
    for pairs in index.values():
        assert type(pairs) is tuple and pairs
        assert all(type(pair) is tuple and len(pair) == 2 for pair in pairs)
        assert all(type(value) is int for pair in pairs for value in pair)
    subject = next(iter(index))
    original = dict(index)
    with pytest.raises(TypeError):
        index[subject] = ()
    with pytest.raises(AttributeError):
        index[subject].append((0, 0))
    with pytest.raises(TypeError):
        index[subject][0][0] = 99
    with pytest.raises(TypeError):
        seals[subject] = "0" * 64
    assert dict(index) == original
    transform.verify_consumed_inputs()


@pytest.mark.parametrize("field", ["_deposit_occurrences", "_deposit_occurrence_seals"])
@pytest.mark.parametrize("damage", ["equal-proxy", "equal-dict", "none", "deleted"])
def test_public_producer_checkpoint_retains_original_index_objects(tmp_path, monkeypatch, field, damage):
    """Equal copied contents cannot redefine the captured original native index binding."""
    transform, _, _, _ = produce(tmp_path, monkeypatch)
    guard = transform._taxonomy_evidence_guard
    original = getattr(guard, field)
    if damage == "equal-proxy":
        replacement = MappingProxyType(dict(original))
        assert dict(replacement) == dict(original) and replacement is not original
        setattr(guard, field, replacement)
    elif damage == "equal-dict":
        setattr(guard, field, dict(original))
    elif damage == "none":
        setattr(guard, field, None)
    else:
        delattr(guard, field)
    with pytest.raises(SourceFinalizationRequired, match="(resolution changed|occurrence binding)"):
        transform.verify_consumed_inputs()
    # Restoring a reference after a public failed checkpoint does not heal the
    # failure. A genuine new run, not ad-hoc rebinding, owns reconstruction.
    setattr(guard, field, original)
    with pytest.raises(SourceFinalizationRequired):
        transform.verify_consumed_inputs()


@pytest.mark.parametrize("damage", ["missing", "replacement"])
def test_public_checkpoint_retains_original_occurrence_binder_and_sticky_failure(tmp_path, monkeypatch, damage):
    """A missing or always-successful replacement callback cannot stand in for the original binder."""
    transform, _, _, _ = produce(tmp_path, monkeypatch)
    guard = transform._taxonomy_evidence_guard
    original = guard._deposit_occurrence_binding
    assert callable(original) and original() == (True, True)
    guard._deposit_occurrence_binding = None if damage == "missing" else lambda: (True, True)
    with pytest.raises(SourceFinalizationRequired, match="resolution changed"):
        transform.verify_consumed_inputs()
    guard._deposit_occurrence_binding = original
    assert original() == (True, True)
    with pytest.raises(SourceFinalizationRequired):
        transform.verify_consumed_inputs()


@pytest.mark.parametrize("damage", ["record-reference", "deposit-token"])
def test_touched_record_evidence_is_still_validated_before_contributor_use(tmp_path, monkeypatch, damage):
    """An immutable index is not a waiver for mutable original records or their exact token coordinates."""
    transform, _, _, _ = produce(tmp_path, monkeypatch)
    guard = transform._taxonomy_evidence_guard
    subject = next(iter(guard._deposit_occurrences))
    ordinal, token_index = guard._deposit_occurrences[subject][0]
    claims = guard.native_deposit_claims()[subject]
    index = guard._deposit_occurrences
    native = guard.records[ordinal]
    if damage == "record-reference":
        native["references"] = {"unreviewed": "changed after native capture"}
    else:
        native["deposits"][token_index]["literal_token"] += " altered"
    assert guard._deposit_occurrences is index
    with pytest.raises(SourceFinalizationRequired, match="captured native record witness changed"):
        guard._claim_occurrences(subject, claims)
    with pytest.raises(SourceFinalizationRequired):
        transform.verify_consumed_inputs()
