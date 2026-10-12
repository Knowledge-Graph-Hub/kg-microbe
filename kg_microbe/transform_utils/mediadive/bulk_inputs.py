"""Bind MediaDive's five required JSON reads to their original locators and bytes."""

import hashlib
import json
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

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
PAYLOAD_ATTRIBUTES = {
    "mediadive_media_detailed": "media_detailed",
    "mediadive_media_strains": "media_strains",
    "mediadive_solutions": "solutions_data",
    "mediadive_compounds": "compounds_data",
}


@dataclass(frozen=True)
class _ParsedPayload:
    """Read-bound semantic identity, independent of mutable producer lookup caches."""

    source_path: str
    source_sha256: str
    sha256: str
    records: MappingProxyType


def _payload_digest(payload):
    """Preserve JSON value types and list positions without allocating a second serialized tree."""
    # json.dumps silently coerces tuple to list and non-string dictionary keys
    # to strings. Neither is an unchanged value from the native JSON parser.
    pending, seen = [payload], set()
    while pending:
        value = pending.pop()
        if type(value) in {dict, list}:
            if id(value) in seen:
                continue
            seen.add(id(value))
        if type(value) is dict:
            if any(type(key) is not str for key in value):
                raise SourceFinalizationRequired("MediaDive cached JSON object has a non-string key")
            pending.extend(value.values())
        elif type(value) is list:
            pending.extend(value)
        elif value is not None and type(value) not in {str, bool, int, float}:
            raise SourceFinalizationRequired("MediaDive cached payload is not an exact JSON value")
    digest = hashlib.sha256()
    encoder = json.JSONEncoder(ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))
    try:
        for piece in encoder.iterencode(payload):
            digest.update(piece.encode("utf-8"))
    except (ValueError, TypeError) as error:
        raise SourceFinalizationRequired("MediaDive cached payload cannot be encoded as native JSON") from error
    return digest.hexdigest()


def _unique_native_object(pairs):
    """Reject duplicate catalog IDs and record fields before any graph emission (#1319)."""
    result = {}
    for key, value in pairs:
        if key in result:
            raise SourceFinalizationRequired(f"MediaDive native duplicate JSON key: {key!r}")
        result[key] = value
    return result


def load_bulk_payload(transform, name, path):
    """Parse and bind payload identity inside its actual immutable native-read boundary (#1299)."""
    try:
        with snapshot_bulk_input(transform, name, path) as reader:
            payload = json.load(reader, object_pairs_hook=_unique_native_object)
            if not isinstance(payload, dict):
                raise ValueError(f"MediaDive {name} must contain a JSON object")
            snapshot = transform.consumed_input_snapshots[name]
            binding = _ParsedPayload(
                snapshot["path"],
                snapshot["sha256"],
                _payload_digest(payload),
                MappingProxyType({key: _payload_digest(value) for key, value in payload.items()}),
            )
            if not hasattr(transform, "_bulk_payload_bindings"):
                transform._bulk_payload_bindings = {}
                transform._bulk_parsed_payloads = {}
            if transform._bulk_payload_bindings.setdefault(name, binding) != binding:
                raise SourceFinalizationRequired(f"MediaDive parsed bulk input changed within one producer: {name!r}")
            # Retain the list object too: it is local to _run, unlike four public
            # caches. A later repeated read must not erase an already changed object.
            previous = transform._bulk_parsed_payloads.get(name)
            if previous is not None and _payload_digest(previous) != binding.sha256:
                raise SourceFinalizationRequired(f"MediaDive previously parsed bulk payload changed: {name!r}")
            transform._bulk_parsed_payloads[name] = payload
        return payload
    except BaseException as error:
        transform._consumed_input_error = str(error)
        raise


def _bound_payload(transform, name):
    """Use the public dictionary currently selected by the producer, including whole-cache replacements."""
    if name in PAYLOAD_ATTRIBUTES:
        return getattr(transform, PAYLOAD_ATTRIBUTES[name], None)
    return getattr(transform, "_bulk_parsed_payloads", {}).get(name)


def verify_bulk_payloads(transform):
    """Recheck every cached payload at run/finalization boundaries, never rebaseline its identity."""
    try:
        if getattr(transform, "_consumed_input_error", None) is not None:
            raise SourceFinalizationRequired("A previous MediaDive input read failed; construct a new producer")
        bindings = getattr(transform, "_bulk_payload_bindings", {})
        if set(bindings) != set(REQUIRED_BULK_INPUTS):
            raise SourceFinalizationRequired("MediaDive parsed bulk input bindings are incomplete; rerun the producer")
        for name, binding in bindings.items():
            expected = {"path": binding.source_path, "sha256": binding.source_sha256}
            if transform.consumed_input_snapshots.get(name) != expected:
                raise SourceFinalizationRequired(f"MediaDive parsed payload differs from its read identity: {name!r}")
            payload = _bound_payload(transform, name)
            if not isinstance(payload, dict) or _payload_digest(payload) != binding.sha256:
                raise SourceFinalizationRequired(f"MediaDive cached native payload changed: {name!r}")
    except BaseException as error:
        transform._consumed_input_error = str(error)
        raise


def verify_bulk_record(transform, name, key):
    """Verify one actual parsed record before lookup, without rehashing the complete source tree."""
    # Lookup-only callers can supply dictionaries without claiming a producer
    # completion. Actual admitted producers may never omit their read binding.
    if getattr(transform, "_bulk_input_admission", None) is None:
        return
    try:
        if getattr(transform, "_consumed_input_error", None) is not None:
            raise SourceFinalizationRequired("A previous MediaDive input read failed; construct a new producer")
        binding = getattr(transform, "_bulk_payload_bindings", {}).get(name)
        payload = _bound_payload(transform, name)
        if binding is None or not isinstance(payload, dict):
            raise SourceFinalizationRequired(f"MediaDive parsed bulk input binding is missing: {name!r}")
        if transform.consumed_input_snapshots.get(name) != {
            "path": binding.source_path,
            "sha256": binding.source_sha256,
        }:
            raise SourceFinalizationRequired(f"MediaDive record differs from its read identity: {name!r}")
        expected = binding.records.get(key)
        if (key in payload) != (expected is not None) or (
            expected is not None and _payload_digest(payload[key]) != expected
        ):
            raise SourceFinalizationRequired(f"MediaDive cached native record changed: {name!r}, {key!r}")
    except BaseException as error:
        transform._consumed_input_error = str(error)
        raise


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
        or set(contract) != {"version", "inputs", "recipe_identity"}
        or type(contract["version"]) is not int
        or contract["version"] != 2
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
        verify_bulk_payloads(transform)
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
