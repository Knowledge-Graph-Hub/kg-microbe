"""Finite transport recovery requires a verified unchanged one-endpoint predecessor."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from scripts.adhoc import kgm_mediadive_resolution_20261105 as helper


def _parent(count):
    """Represent only the independently admitted parent view at this orchestration boundary."""
    return SimpleNamespace(
        endpoint_states={f"https://mediadive.dsmz.de/rest/medium-strains/{i}": "transport_error" for i in range(count)}
    )


@pytest.mark.parametrize(
    "step,stage,count,resolved",
    [
        ("batch", "seed", 49, False),
        ("batch", "canary", 49, False),
        ("batch", "canary", 49, True),
        ("canary", "seed", 632, False),
    ],
)
def test_no_bulk_retry_without_resolved_one_endpoint_canary(monkeypatch, step, stage, count, resolved):
    """Wrong predecessor or unresolved canary refuses before generation creation or network use."""
    from kg_microbe.transform_utils.mediadive import acquisition

    receipt = {"runtime": {"bound": "same"}, "step": stage, "selected_count": 1, "canary_resolved": resolved}
    monkeypatch.setattr(helper, "previous_view", lambda *_args: (receipt, _parent(count)))
    start = Mock(side_effect=AssertionError("Must refuse before creating a generation"))
    monkeypatch.setattr(acquisition, "start_generation", start)
    args = SimpleNamespace(step=step, previous_receipt="receipt", previous_sha256="pinned", generation_id="next")
    with pytest.raises(ValueError):
        helper.retry(args, {"bound": "same"})
    start.assert_not_called()


def test_changed_producer_requires_new_canary(monkeypatch):
    """A canary receipt cannot certify a changed executable or production implementation."""
    from kg_microbe.transform_utils.mediadive import acquisition

    receipt = {"runtime": {"bound": "old"}, "step": "canary", "selected_count": 1, "canary_resolved": True}
    monkeypatch.setattr(helper, "previous_view", lambda *_args: (receipt, _parent(48)))
    start = Mock(side_effect=AssertionError("No acquisition under stale canary evidence"))
    monkeypatch.setattr(acquisition, "start_generation", start)
    args = SimpleNamespace(step="batch", previous_receipt="receipt", previous_sha256="pinned", generation_id="next")
    with pytest.raises(ValueError, match="runtime changed"):
        helper.retry(args, {"bound": "new"})
    start.assert_not_called()


def test_unsafe_label_refused_before_evidence_or_runtime(monkeypatch):
    """An output label cannot escape the owned generation/evidence roots."""
    runtime = Mock(side_effect=AssertionError("Validate before performing runtime work"))
    monkeypatch.setattr(helper, "runtime", runtime)
    with pytest.raises(ValueError, match="Unsafe generation"):
        helper.run(SimpleNamespace(generation_id="../../other-session"))
    runtime.assert_not_called()
