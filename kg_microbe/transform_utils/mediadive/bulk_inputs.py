"""Bind MediaDive's five required JSON reads to their original locators and bytes."""

from contextlib import contextmanager
from pathlib import Path

from kg_microbe.merge_utils.source_admission import SourceAdmission
from kg_microbe.utils.source_finalization import SourceFinalizationRequired

BULK_INPUTS = {
    "mediadive_media_detailed": "media_detailed.json",
    "mediadive_media_strains": "media_strains.json",
    "mediadive_solutions": "solutions.json",
    "mediadive_compounds": "compounds.json",
}
MEDIA_LIST_INPUT = "mediadive_media_list"
REQUIRED_BULK_INPUTS = (MEDIA_LIST_INPUT, *BULK_INPUTS)


def _raw_locator(input_dir):
    """Retain the selected directory's lexical identity, not only its resolved target."""
    if not isinstance(input_dir, (str, Path)):
        raise SourceFinalizationRequired("MediaDive bulk inputs require the selected raw directory")
    locator = Path(input_dir).absolute()
    if not locator.is_dir():
        raise SourceFinalizationRequired(f"MediaDive raw input directory is missing: {locator}")
    return locator


def _check_role_locator(name, locator, raw):
    """Four roles have fixed paths; the explicitly selected media-list path may be overridden."""
    if name not in REQUIRED_BULK_INPUTS:
        raise SourceFinalizationRequired(f"Undeclared MediaDive bulk input: {name!r}")
    if name in BULK_INPUTS and locator != raw / "mediadive" / BULK_INPUTS[name]:
        raise SourceFinalizationRequired(f"Wrong MediaDive bulk input locator for {name!r}: {locator}")


def _validate_contract(contract, snapshots, raw, guard):
    """Require complete role membership and agreement with the original immutable reads."""
    if (
        not isinstance(contract, dict)
        or set(contract) != {"version", "inputs"}
        or type(contract["version"]) is not int
        or contract["version"] != 1
        or not isinstance(contract["inputs"], dict)
        or set(contract["inputs"]) != set(REQUIRED_BULK_INPUTS)
        or not isinstance(snapshots, dict)
    ):
        raise SourceFinalizationRequired("Missing or malformed MediaDive bulk input contract; rerun the producer")
    guard.bind_path(raw)
    for name in REQUIRED_BULK_INPUTS:
        state = contract["inputs"][name]
        if (
            not isinstance(state, dict)
            or set(state) != {"locator", "resolved", "sha256"}
            or not isinstance(state["locator"], str)
            or not Path(state["locator"]).is_absolute()
            or not isinstance(state["resolved"], str)
            or not Path(state["resolved"]).is_absolute()
            or not isinstance(state["sha256"], str)
            or len(state["sha256"]) != 64
            or any(char not in "0123456789abcdef" for char in state["sha256"])
        ):
            raise SourceFinalizationRequired(f"Malformed MediaDive bulk input state: {name!r}")
        locator = Path(state["locator"])
        _check_role_locator(name, locator, raw)
        if str(locator.resolve()) != state["resolved"]:
            raise SourceFinalizationRequired(f"MediaDive bulk input locator changed: {name!r}")
        expected = {"path": state["resolved"], "sha256": state["sha256"]}
        if snapshots.get(name) != expected or guard.capture(locator)["sha256"] != state["sha256"]:
            raise SourceFinalizationRequired(f"MediaDive consumed bulk input changed: {name!r}")
    guard.verify(metadata_only=True)


@contextmanager
def snapshot_bulk_input(transform, name, path):
    """Guard the lexical path before and after consuming its immutable text snapshot."""
    try:
        if getattr(transform, "_consumed_input_error", None) is not None:
            raise SourceFinalizationRequired("A previous MediaDive input read failed; construct a new producer")
        raw = _raw_locator(transform.input_base_dir)
        locator = Path(path).absolute()
        _check_role_locator(name, locator, raw)
        if getattr(transform, "_bulk_input_admission", None) is None:
            transform._bulk_input_admission = SourceAdmission()
        if not hasattr(transform, "_bulk_input_states"):
            transform._bulk_input_states = {}
        guard = transform._bulk_input_admission
        guard.verify()
        guard.bind_path(raw)
        resolved = guard.bind_path(locator)
        identity = guard.capture(locator)
        state = {"locator": str(locator), "resolved": str(resolved), "sha256": identity["sha256"]}
        if transform._bulk_input_states.setdefault(name, state) != state:
            raise SourceFinalizationRequired(f"MediaDive bulk input selection changed within one producer: {name!r}")
        with transform.consume_input(name, locator) as reader:
            if transform.consumed_input_snapshots[name] != {"path": str(resolved), "sha256": identity["sha256"]}:
                raise SourceFinalizationRequired(f"MediaDive bulk input changed before immutable read: {name!r}")
            guard.verify()
            yield reader
        guard.verify()
    except BaseException as error:
        transform._consumed_input_error = str(error)
        raise


def verify_bulk_inputs(transform, *, byte_verified=False, output_dir=None):
    """Verify this instance's retained contract without replacing its original admission epoch."""
    del output_dir  # Native-hook signature compatibility; this contract concerns raw inputs only.
    try:
        if getattr(transform, "_consumed_input_error", None) is not None:
            raise SourceFinalizationRequired("A previous MediaDive input read failed; construct a new producer")
        guard = getattr(transform, "_bulk_input_admission", None)
        if guard is None:
            raise SourceFinalizationRequired("MediaDive bulk inputs were not admitted; run the producer")
        _validate_contract(
            transform.producer_native_inputs,
            transform.consumed_input_snapshots,
            _raw_locator(transform.input_base_dir),
            guard,
        )
        # The generic consumed-input checkpoint has already rehashed every
        # snapshot when byte_verified=True; locator/stamp verification still runs.
        guard.verify(metadata_only=byte_verified)
    except BaseException as error:
        transform._consumed_input_error = str(error)
        raise


def verify_recorded_bulk_inputs(report, report_path, *, admission=None):
    """Validate recorded raw roles within the shared recorded-input admission boundary."""
    if report_path is None:
        raise SourceFinalizationRequired("MediaDive bulk verification requires its completion-record path")
    raw_locator = report.get("raw_input_locator")
    raw_directory = report.get("raw_input_directory")
    if (
        not isinstance(raw_locator, str)
        or not Path(raw_locator).is_absolute()
        or not isinstance(raw_directory, str)
        or not Path(raw_directory).is_absolute()
    ):
        raise SourceFinalizationRequired("Missing MediaDive raw input directory binding; rerun the producer")
    raw = _raw_locator(raw_locator)
    if str(raw.resolve()) != raw_directory:
        raise SourceFinalizationRequired("MediaDive raw input directory changed; rerun the producer")
    guard = admission if admission is not None else SourceAdmission()
    # The same shared verification call subsequently checks the exact parsed
    # completion record (including duplicate keys) through MediaDive's optional
    # raw-input contract. Retain this record in that very same admission set.
    guard.capture(report_path)
    _validate_contract(report.get("producer_native_inputs"), report.get("consumed_inputs"), raw, guard)
    return guard
