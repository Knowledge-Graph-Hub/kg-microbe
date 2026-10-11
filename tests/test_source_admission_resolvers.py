"""Resolution guards reject genuine drift without masking no-argument failures (#1324)."""

import pytest

from kg_microbe.merge_utils.source_admission import SourceAdmission
from kg_microbe.transform_utils.transform import Transform
from kg_microbe.utils.source_finalization import SourceFinalizationRequired


@pytest.mark.parametrize("metadata_only", [False, True])
@pytest.mark.parametrize("with_argument", [False, True])
def test_resolution_drift_reports_expected_failure_with_or_without_arguments(metadata_only, with_argument):
    """Unchanged selections remain valid; changed selections always fail as admission errors."""
    admission = SourceAdmission()
    state = {"selected": "first"}
    if with_argument:
        admission.capture_resolution(lambda key: state[key], "selected")
    else:
        admission.capture_resolution(lambda: state["selected"])
    admission.verify(metadata_only=metadata_only)
    admission.verify(metadata_only=metadata_only)
    state["selected"] = "second"
    with pytest.raises(SourceFinalizationRequired, match="input resolution changed"):
        admission.verify(metadata_only=metadata_only)


def test_resolver_failure_is_not_swallowed_or_replaced():
    """A failing authority resolver propagates its real error, never a substitution of current state."""
    admission = SourceAdmission()
    state = {"selected": "first"}
    admission.capture_resolution(lambda: state["selected"])
    del state["selected"]
    with pytest.raises(KeyError, match="selected"):
        admission.verify()


def test_new_transform_run_discards_previous_gold_guard(tmp_path):
    """A previous run's source authority cannot be silently reused in a new producer run."""
    transform = Transform("fixture", tmp_path / "raw", tmp_path / "transformed")
    transform._gold_declaration_guard = object()
    transform.begin_consumed_inputs()
    assert transform._gold_declaration_guard is None
