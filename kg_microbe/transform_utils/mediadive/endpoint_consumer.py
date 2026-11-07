"""Keep typed MediaDive endpoint evidence through production and recorded admission."""

import csv
import hashlib
import io
import json
from pathlib import Path
from types import MappingProxyType

from kg_microbe.merge_utils.source_admission import SourceAdmission
from kg_microbe.transform_utils.constants import (
    MEDIADIVE_MEDIUM_PREFIX,
    MEDIADIVE_REST_API_BASE_URL,
    NCBI_TO_MEDIUM_EDGE,
    NCBI_TO_MEDIUM_NEGATIVE_EDGE,
)
from kg_microbe.utils.source_finalization import SourceFinalizationRequired

AUDIT_FILENAME = "mediadive_endpoint_outcomes.tsv"
GENERATION_INPUTS = {
    "mediadive_generation_pointer": "current.json",
    "mediadive_generation_manifest": "manifest.json",
    "mediadive_endpoint_outcomes": "endpoint-outcomes.json",
    "mediadive_unknown_policy": "unknown-policy.json",
    "mediadive_unknown_disposition_policy": None,
}
HEADER = ("endpoint", "requested_id", "state", "observation_id", "body_sha256", "observed_at")


def require(condition, message):
    """Refuse unsupported evidence without converting it to absent associations."""
    if not condition:
        raise SourceFinalizationRequired("MediaDive endpoint evidence: " + message)


def encoded(value):
    """Retain JSON types and stable detached contract identities."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def contracts_equal(recorded, expected):
    """Compare exact JSON types, never Python's boolean/integer container equality."""
    try:
        return encoded(recorded) == encoded(expected)
    except (TypeError, ValueError):
        return False


def _unique(pairs):
    """Reject repeated contract fields before a dictionary hides their disagreement."""
    result = {}
    for key, value in pairs:
        require(key not in result, f"duplicate field {key!r}")
        result[key] = value
    return result


def _load(root, *, consume_input=None, admission=None):
    """Use the acquisition owner's full persisted-body validator, never a consumer shortcut."""
    from kg_microbe.transform_utils.mediadive.endpoint_outcomes import load_generation

    try:
        return load_generation(root, consume_input=consume_input, admission=admission)
    except (ValueError, OSError) as error:
        raise SourceFinalizationRequired(f"MediaDive endpoint generation refused: {error}") from error


def _metadata_paths(view, root):
    """Name the four mandatory original reads, independently of recorded role labels."""
    from kg_microbe.transform_utils.mediadive.endpoint_outcomes import CURATED_UNKNOWN_POLICY

    return {
        role: (
            Path(CURATED_UNKNOWN_POLICY)
            if role == "mediadive_unknown_disposition_policy"
            else Path(root) / name
            if role == "mediadive_generation_pointer"
            else view.generation_dir / name
        )
        for role, name in GENERATION_INPUTS.items()
    }


def _verify_roles(snapshots, view, root):
    """Require actual consumed identities to agree with the fully validated generation."""
    for role, path in _metadata_paths(view, root).items():
        expected = {"path": str(path.resolve()), "sha256": view.admission.capture(path)["sha256"]}
        require(snapshots.get(role) == expected, f"missing or changed required read {role!r}")


def _rows(view):
    """Project exact classified endpoint heads into a portable, non-biological audit."""
    rows = []
    for endpoint, record in sorted(view.endpoint_records.items()):
        require(record["state"] == view.endpoint_states[endpoint], "endpoint state views disagree")
        row = {
            "endpoint": endpoint,
            "requested_id": endpoint.rsplit("/", 1)[-1],
            "state": record["state"],
            "observation_id": record.get("observation_id") or "",
            "body_sha256": record.get("body_sha256") or "",
            "observed_at": record.get("observed_at") or "",
        }
        require(
            all(isinstance(value, str) and not any(char in value for char in "\t\r\n") for value in row.values()),
            "endpoint audit contains unsupported scalar text",
        )
        rows.append(row)
    return rows


def _audit_bytes(rows):
    """Serialize a bounded evidence table without changing native response payloads."""
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=HEADER, delimiter="\t", quoting=csv.QUOTE_NONE, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def _identity(payload):
    """Describe immutable audit bytes without including the audit's own file name."""
    return {"bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}


def _check_audit(directory, expected, *, admission=None):
    """Reconstruct audit content rather than trusting a restamped outer receipt."""
    path = Path(directory) / AUDIT_FILENAME
    require(path.is_file() and not path.is_symlink(), "required endpoint audit is missing or linked")
    actual = admission.capture(path, retain=True) if admission is not None else path.read_bytes()
    require(actual == expected, "endpoint audit differs from native generation evidence")
    return _identity(expected)


def _check_omitted_assertions(path, states):
    """Forbid source-local growth claims for explicitly empty or unavailable endpoints."""
    omitted = {
        MEDIADIVE_MEDIUM_PREFIX + endpoint.rsplit("/", 1)[-1]
        for endpoint, state in states.items()
        if "/medium-strains/" in endpoint and state in {"explicit_empty", "unknown_unavailable"}
    }
    require(Path(path).is_file(), "source edge output is missing")
    with Path(path).open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream, delimiter="\t", quoting=csv.QUOTE_NONE):
            require(
                not (
                    row.get("object") in omitted
                    and row.get("predicate") in {NCBI_TO_MEDIUM_EDGE, NCBI_TO_MEDIUM_NEGATIVE_EDGE}
                ),
                "empty or unavailable endpoint gained an unsupported growth assertion",
            )


class EndpointConsumer:
    """Bind one producer to one sealed generation without replacing its read epoch."""

    def __init__(self, transform):
        """Read the active generation through actual consumed-input snapshots."""
        self.transform = transform
        self.root = Path(transform.bulk_data_dir)
        self.view = _load(self.root, consume_input=transform.consume_input, admission=SourceAdmission())
        self.admission = self.view.admission
        self._native_paths = MappingProxyType(dict(self.view.native_paths))
        self._generation = encoded(self.view.contract())
        self._qualification = encoded(self.view.qualification)
        self._records = encoded(self.view.endpoint_records)
        self._states = MappingProxyType(dict(self.view.endpoint_states))
        self._audit = _audit_bytes(_rows(self.view))
        self._sealed = False
        _verify_roles(transform.consumed_input_snapshots, self.view, self.root)

    @property
    def native_paths(self):
        """Return the generation's original native locators."""
        return dict(self._native_paths)

    def state(self, medium_id):
        """Return a recorded strain state; never infer empty from a missing JSON key."""
        endpoint = MEDIADIVE_REST_API_BASE_URL + "medium-strains/" + str(medium_id)
        require(endpoint in self._states, f"missing endpoint evidence for {medium_id!r}")
        state = self._states[endpoint]
        require(state in {"nonempty", "explicit_empty", "unknown_unavailable"}, f"unresolved endpoint {endpoint}")
        return state

    def contract(self):
        """Expose detached generation evidence plus the completed audit identity."""
        self._verify_cache()
        return {
            "version": 1,
            "generation": json.loads(self._generation),
            "audit": {"name": AUDIT_FILENAME, **_identity(self._audit)} if self._sealed else None,
            "sealed": self._sealed,
        }

    def _verify_cache(self):
        """Reject mutable view/contract substitutions under unchanged original input hashes."""
        require(dict(self.view.native_paths) == dict(self._native_paths), "native generation locators changed")
        require(encoded(self.view.contract()) == self._generation, "generation contract changed")
        require(encoded(self.view.qualification) == self._qualification, "coverage qualification changed")
        require(encoded(self.view.endpoint_records) == self._records, "endpoint record cache changed")
        require(dict(self.view.endpoint_states) == dict(self._states), "endpoint state cache changed")
        require(_audit_bytes(_rows(self.view)) == self._audit, "cached endpoint audit differs from native evidence")
        _verify_roles(self.transform.consumed_input_snapshots, self.view, self.root)

    def verify(self, *, output_dir=None, byte_verified=False):
        """Keep original inputs and completed audit fixed across every producer boundary."""
        self._verify_cache()
        self.admission.verify(metadata_only=byte_verified)
        require(output_dir is None or self._sealed, "endpoint audit was not completed by the producer")
        if self._sealed:
            directory = Path(output_dir) if output_dir is not None else self.transform.output_dir
            _check_audit(directory, self._audit)
            _check_omitted_assertions(directory / Path(self.transform.output_edge_file).name, self._states)

    def write(self):
        """Seal the mandatory audit only after the actual source graph obeys its omissions."""
        self._verify_cache()
        self.admission.verify()
        _check_omitted_assertions(self.transform.output_edge_file, self._states)
        path = self.transform.output_dir / AUDIT_FILENAME
        require(not path.is_symlink(), "endpoint audit output is linked")
        path.write_bytes(self._audit)
        self.transform.record_producer_audit(AUDIT_FILENAME)
        self._sealed = True
        self.verify()

    def restore(self, report_path):
        """Restore a completed checkpoint only from the current validated generation."""
        report = json.loads(Path(report_path).read_bytes(), object_pairs_hook=_unique)
        recorded = report.get("producer_native_inputs", {}).get("endpoint_coverage")
        expected = {
            "version": 1,
            "generation": json.loads(self._generation),
            "audit": {"name": AUDIT_FILENAME, **_identity(self._audit)},
            "sealed": True,
        }
        require(contracts_equal(recorded, expected), "checkpoint endpoint evidence differs from actual reads")
        _check_audit(self.transform.output_dir, self._audit)
        self._sealed = True
        self.verify()


def verify_recorded_endpoints(report, report_path, *, admission=None):
    """Recompute recorded source qualifications from full persisted native evidence."""
    raw = report.get("raw_input_locator")
    require(isinstance(raw, str) and Path(raw).is_absolute(), "missing original raw locator")
    root = Path(raw) / "mediadive"
    guard = admission if admission is not None else SourceAdmission()
    view = _load(root, admission=guard)
    _verify_roles(report.get("consumed_inputs", {}), view, root)
    payload = _audit_bytes(_rows(view))
    expected = {
        "version": 1,
        "generation": view.contract(),
        "audit": {"name": AUDIT_FILENAME, **_identity(payload)},
        "sealed": True,
    }
    require(
        contracts_equal(report.get("producer_native_inputs", {}).get("endpoint_coverage"), expected),
        "recorded endpoint contract differs",
    )
    _check_audit(Path(report_path).parent, payload, admission=guard)
    edge_names = [name for name in report.get("members", {}) if name.endswith("edges.tsv")]
    require(len(edge_names) == 1, "unexpected MediaDive graph member scope")
    edge_path = Path(report_path).parent / edge_names[0]
    guard.capture(edge_path)
    _check_omitted_assertions(edge_path, view.endpoint_states)
    guard.verify(metadata_only=True)
    return view


def register_qualification(report_path, view):
    """Expose verified selected-source evidence to merge without changing shared admission code."""
    guard = view.admission
    path = Path(report_path).resolve()
    audit = path.parent / AUDIT_FILENAME
    report = json.loads(guard.capture(path, retain=True), object_pairs_hook=_unique)
    value = {
        "source": "mediadive",
        "graph_paths": [str(path.parent / name) for name in sorted(report["members"])],
        "generation": view.contract(),
        "summary": json.loads(encoded(view.qualification)),
        "audit": {"name": AUDIT_FILENAME, "path": str(audit), **guard.capture(audit)},
    }
    if not hasattr(guard, "source_qualifications"):
        guard.source_qualifications = {}
    previous = guard.source_qualifications.setdefault(str(path), value)
    require(contracts_equal(previous, value), "source qualification changed within admission")
