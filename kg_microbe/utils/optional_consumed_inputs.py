"""Exact producer-read contracts for declared optional repository and effective-raw inputs."""

import json
import os
from contextlib import contextmanager
from pathlib import Path


def has_optional_inputs(producer):
    """Recognize both explicit locator modes without relocating repository inputs."""
    return bool(
        getattr(producer, "OPTIONAL_CONSUMED_INPUTS", ()) or getattr(producer, "OPTIONAL_RAW_CONSUMED_INPUTS", ())
    )


def optional_input_paths(producer, *, input_dir=None):
    """Resolve repository roles at the repository and raw roles at the selected lexical directory."""
    from kg_microbe.utils.source_finalization import SourceFinalizationRequired
    from kg_microbe.utils.transform_fingerprint import _repo_root

    paths = {}
    repository = getattr(producer, "OPTIONAL_CONSUMED_INPUTS", ())
    raw = getattr(producer, "OPTIONAL_RAW_CONSUMED_INPUTS", ())
    if raw and input_dir is None:
        raise SourceFinalizationRequired("Optional raw inputs require the selected raw directory")
    declarations = [
        *((name, relative, _repo_root()) for name, relative in repository),
        *((name, relative, Path(input_dir)) for name, relative in raw),
    ]
    for name, relative, base in declarations:
        if (
            not isinstance(name, str)
            or not name
            or name in paths
            or not isinstance(relative, str)
            or not relative
            or Path(relative).is_absolute()
            or ".." in Path(relative).parts
        ):
            raise SourceFinalizationRequired("Invalid optional consumed-input declaration")
        paths[name] = (base / relative).absolute()
    return paths


def verify_optional_inputs(producer, contract, snapshots, *, admission=None, input_dir=None):
    """Check declared membership, locator, original bytes or absence, retaining the same guards."""
    from kg_microbe.merge_utils.source_admission import SourceAdmission
    from kg_microbe.utils.source_finalization import SourceFinalizationRequired

    paths = optional_input_paths(producer, input_dir=input_dir)
    if not paths and contract is None:
        return
    if (
        not isinstance(contract, dict)
        or set(contract) != {"version", "inputs"}
        or type(contract["version"]) is not int
        or contract["version"] != 1
        or not isinstance(contract["inputs"], dict)
        or set(contract["inputs"]) != set(paths)
        or not isinstance(snapshots, dict)
    ):
        raise SourceFinalizationRequired("Missing or malformed optional consumed-input contract; rerun the producer")
    guard = admission if admission is not None else SourceAdmission()
    for name, locator in paths.items():
        state = contract["inputs"][name]
        if (
            not isinstance(state, dict)
            or set(state) != {"locator", "resolved", "sha256"}
            or state["locator"] != str(locator)
            or not isinstance(state["resolved"], str)
            or not Path(state["resolved"]).is_absolute()
            or str(locator.resolve()) != state["resolved"]
            or (
                state["sha256"] is not None
                and (
                    not isinstance(state["sha256"], str)
                    or len(state["sha256"]) != 64
                    or any(char not in "0123456789abcdef" for char in state["sha256"])
                )
            )
        ):
            raise SourceFinalizationRequired(f"Invalid or changed optional input locator: {name}; rerun the producer")
        if state["sha256"] is None:
            if name in snapshots or os.path.lexists(locator):
                raise SourceFinalizationRequired(f"Optional input {name!r} appeared or has conflicting evidence")
            guard.capture(locator, optional=True)
        else:
            expected = {"path": state["resolved"], "sha256": state["sha256"]}
            if snapshots.get(name) != expected or guard.capture(locator)["sha256"] != state["sha256"]:
                raise SourceFinalizationRequired(f"Optional consumed input {name!r} changed; rerun the producer")
    # capture() hashes newly admitted files; existing admitted hashes are guarded
    # by their original stamps and the caller's final full verification. Avoid
    # rehashing unrelated graph-scale members in a shared public admission here.
    guard.verify(metadata_only=True)


@contextmanager
def snapshot_optional_input(transform, name):
    """Read immutable captured text, or yield None only for explicitly observed optional absence."""
    from kg_microbe.merge_utils.source_admission import SourceAdmission
    from kg_microbe.utils.source_finalization import SourceFinalizationRequired

    try:
        paths = optional_input_paths(type(transform), input_dir=transform.input_base_dir)
        if name not in paths:
            raise SourceFinalizationRequired(f"Undeclared optional consumed input: {name!r}")
        if transform._optional_input_admission is None:
            transform._optional_input_admission = SourceAdmission()
        guard = transform._optional_input_admission
        guard.verify()
        locator = paths[name]
        resolved = guard.bind_path(locator)
        if not locator.exists() and os.path.lexists(locator):
            raise SourceFinalizationRequired(f"Unreadable optional input locator: {locator}")
        identity = guard.capture(locator, optional=True)
        state = {
            "locator": str(locator),
            "resolved": str(resolved),
            "sha256": identity["sha256"] if identity is not None else None,
        }
        if transform._optional_input_states.setdefault(name, state) != state:
            raise SourceFinalizationRequired(f"Optional input {name!r} changed within one producer run")
        if identity is None:
            yield None
        else:
            with transform.consume_input(name, locator) as reader:
                if transform.consumed_input_snapshots[name] != {"path": str(resolved), "sha256": identity["sha256"]}:
                    raise SourceFinalizationRequired(f"Optional input {name!r} changed before immutable read")
                guard.verify()
                yield reader
        guard.verify()
    except BaseException as error:
        transform._consumed_input_error = str(error)
        raise


def verify_recorded_optional_inputs(producer, report, *, report_path=None, admission=None):
    """Use the same contract for standalone, public and diagnostic recorded-source checks."""
    from kg_microbe.merge_utils.source_admission import SourceAdmission
    from kg_microbe.utils.source_finalization import SourceFinalizationRequired

    if has_optional_inputs(producer):
        if report_path is None:
            raise SourceFinalizationRequired("Optional input verification requires its actual completion record")
        guard = admission if admission is not None else SourceAdmission()

        def unique_object(pairs):
            """Reject ambiguous metadata instead of letting duplicate keys erase evidence."""
            value = {}
            for key, item in pairs:
                if key in value:
                    raise SourceFinalizationRequired(f"Duplicate optional-input completion key: {key}")
                value[key] = item
            return value

        def invalid_constant(value):
            """Keep completion evidence finite JSON rather than implementation-specific constants."""
            raise SourceFinalizationRequired(f"Nonfinite optional-input completion value: {value}")

        parsed = json.loads(
            guard.capture(report_path, retain=True), object_pairs_hook=unique_object, parse_constant=invalid_constant
        )
        if parsed != report:
            raise SourceFinalizationRequired("Optional input completion record changed while reading")
        admission = guard
    raw_locator = None
    if getattr(producer, "OPTIONAL_RAW_CONSUMED_INPUTS", ()):
        raw_locator = report.get("raw_input_locator")
        raw_directory = report.get("raw_input_directory")
        if (
            not isinstance(raw_locator, str)
            or not Path(raw_locator).is_absolute()
            or not isinstance(raw_directory, str)
            or not Path(raw_directory).is_absolute()
            or not Path(raw_locator).is_dir()
            or str(Path(raw_locator).resolve()) != raw_directory
        ):
            raise SourceFinalizationRequired("Missing or changed optional raw input directory; rerun the producer")
        admission.bind_path(raw_locator)
    verify_optional_inputs(
        producer,
        report.get("optional_consumed_inputs"),
        report.get("consumed_inputs", {}),
        admission=admission,
        input_dir=raw_locator,
    )
