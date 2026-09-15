"""Enforce recorded producer/dependency freshness before KGX without changing transform contracts."""

import hashlib
import inspect
import json
from pathlib import Path

from kg_microbe.utils.source_finalization import (
    FINALIZATION_FILE,
    FINALIZATION_VERSION,
    SourceFinalizationRequired,
    _verify_recorded_consumed_inputs,
)
from kg_microbe.utils.transform_fingerprint import (
    FINGERPRINT_FILE,
    code_fingerprint,
    data_fingerprint,
    finalization_inputs_current,
    read_fingerprint,
    resolve_data_input,
    schema_fingerprint,
    shared_code_fingerprint,
    upstream_fingerprint,
)


class _SourceFreshness:
    """Cache streamed identities and recursive validations for one public merge request."""

    def __init__(self):
        """Resolve only local metadata, without constructing producers or ontology adapters."""
        from kg_microbe.transform import DATA_SOURCES

        self.registry = DATA_SOURCES
        self.root = Path(__file__).resolve().parents[2]
        self.shared = shared_code_fingerprint(self.root)
        self.schema = schema_fingerprint(self.root)
        self.identities = {}
        self.reports = {}
        self.checked = set()
        self.active = set()
        self.packages = {}

    def _identity(self, path):
        """Stream each graph, audit or authority at most once per gate invocation."""
        path = Path(path).resolve()
        if path not in self.identities:
            if not path.is_file():
                raise SourceFinalizationRequired(f"Required prepared input is missing: {path}")
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(block)
            self.identities[path] = {"bytes": path.stat().st_size, "sha256": digest.hexdigest()}
        return self.identities[path]

    def _load(self, path):
        """Read completion metadata strictly; unsupported records cannot supply upstream evidence."""
        if path not in self.reports:
            try:
                report = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as error:
                raise SourceFinalizationRequired(
                    f"Missing/unreadable whole-source finalization record: {path}"
                ) from error
            if not isinstance(report, dict) or report.get("version") != FINALIZATION_VERSION:
                raise SourceFinalizationRequired(f"Unsupported source finalization record: {path}")
            self.reports[path] = report
        return self.reports[path]

    def _producer(self, report):
        """Identify registered code from finalization metadata, never a config key or output folder."""
        producer = report.get("producer_code") or {}
        directory = Path(producer.get("directory", "")).resolve()
        source = directory.name
        registered = self.registry.get(source)
        if registered is None or directory != self.root / "kg_microbe/transform_utils" / source:
            raise SourceFinalizationRequired(
                f"Unsupported producer metadata for {report.get('source')!r}; rerun a registered kg transform "
                "or explicitly use configuration.allow_unfinalized_sources for diagnostics"
            )
        if source not in self.packages:
            cls = getattr(registered, "transform_class", registered)
            actual_directory = Path(inspect.getsourcefile(cls)).resolve().parent
            if actual_directory != directory:
                raise SourceFinalizationRequired(f"Producer metadata does not match registered source {source}")
            self.packages[source] = (cls, directory, code_fingerprint(directory, self.root))
        cls, directory, fingerprint = self.packages[source]
        if producer.get("fingerprint") != fingerprint:
            raise SourceFinalizationRequired(f"{source}: producer code changed; rerun kg transform")
        return source, cls, directory, fingerprint

    def _scoped_ontology(self, path, report, source):
        """Recognize only the explicitly supported single-ontology completion protocol."""
        if path.name == FINALIZATION_FILE:
            return False
        from kg_microbe.transform import _ontology_map

        prefix = path.name.removesuffix(FINALIZATION_FILE)
        ontology = prefix.removesuffix("_")
        expected = {f"{prefix}nodes.tsv", f"{prefix}edges.tsv"}
        if source != "ontologies" or ontology not in _ontology_map() or set(report.get("members", {})) != expected:
            raise SourceFinalizationRequired(f"Unsupported scoped source finalization record: {path}")
        return True

    def _check_record(self, path, report):
        """Tie candidate selection to exact current graph/audit/authority bytes, including scoped alternatives."""
        source, cls, directory, fingerprint = self._producer(report)
        _verify_recorded_consumed_inputs(report)
        if report.get("finalizer_code") != self.shared:
            raise SourceFinalizationRequired(f"{path}: source-finalization code changed")
        members = report.get("members", {})
        if not members:
            raise SourceFinalizationRequired(f"{path}: missing prepared graph members")
        for name, expected in members.items():
            if Path(name).name != name or self._identity(path.parent / name) != expected:
                raise SourceFinalizationRequired(f"{path}: prepared graph member changed: {name}")
        prefix = "" if path.name == FINALIZATION_FILE else path.name.removesuffix(FINALIZATION_FILE)
        audits = report.get("audit_members", {})
        required = {
            f"{prefix}{name}.tsv"
            for name in ("source_canonicalization", "source_reference_resolution", "go_reference_resolution")
        }
        if not required.issubset(audits):
            raise SourceFinalizationRequired(f"{path}: missing mandatory audit identities")
        for name, expected in audits.items():
            if Path(name).name != name or self._identity(path.parent / name) != expected:
                raise SourceFinalizationRequired(f"{path}: mandatory audit changed: {name}")
        for authority in report.get("inputs", []):
            if self._identity(authority["path"])["sha256"] != authority["sha256"]:
                raise SourceFinalizationRequired(f"{path}: consumed authority changed: {authority['path']}")
        return source, cls, directory, fingerprint

    def _check_marker(self, report_path, report, source, cls, code):
        """Validate declared and recorded inputs, then recursively require current whole upstream evidence."""
        directory = report_path.parent
        # Bakta's explicit dataset API publishes individual finalization records
        # but its dispatcher writes one producer marker beside those datasets.
        if source == "bakta" and not (directory / FINGERPRINT_FILE).is_file():
            directory = directory.parent
        marker = read_fingerprint(directory)
        if marker is None:
            if source == "ontologies":
                raise SourceFinalizationRequired(
                    f"ontologies: missing/unsupported whole producer/schema fingerprint in {directory}; "
                    "run poetry run kg transform -s ontologies before production merge, or explicitly use "
                    "configuration.allow_unfinalized_sources for diagnostics"
                )
            raise SourceFinalizationRequired(f"{source}: missing/unsupported producer fingerprint in {directory}")
        if (
            not isinstance(self.schema, dict)
            or self.schema.get("version") in (None, "", "unknown")
            or not self.schema.get("digest")
        ):
            raise SourceFinalizationRequired(
                f"{source}: pinned schema identity is unknown; restore the local pinned schema and rerun kg transform"
            )
        raw_value = report.get("raw_input_directory")
        if not isinstance(raw_value, str) or not Path(raw_value).is_dir():
            raise SourceFinalizationRequired(f"{source}: missing selected raw directory evidence")
        raw = Path(raw_value)
        for declaration in cls.DATA_INPUTS:
            selected = resolve_data_input(self.root, declaration, raw)
            if not selected.is_file():
                raise SourceFinalizationRequired(f"{source}: declared input missing: {selected}")
        expected = {
            "code": code,
            "shared": self.shared,
            "data": data_fingerprint(self.root, cls.DATA_INPUTS, input_dir=raw),
            "schema": self.schema,
        }
        for key, current in expected.items():
            if key not in marker or marker[key] != current:
                raise SourceFinalizationRequired(
                    f"{source}: producer fingerprint stale versus {key}; rerun kg transform"
                )
        if not finalization_inputs_current(marker, self.root):
            raise SourceFinalizationRequired(f"{source}: recorded consumed inputs changed; rerun kg transform")
        for upstream in cls.TRANSFORM_INPUTS:
            upstream_record = directory.parent / upstream / FINALIZATION_FILE
            try:
                self.validate_record(upstream_record, upstream=True, expected_source=upstream)
            except SourceFinalizationRequired as error:
                raise SourceFinalizationRequired(f"{source}: invalid upstream {upstream}: {error}") from error
        if marker.get("upstream") != upstream_fingerprint(directory.parent, cls.TRANSFORM_INPUTS):
            raise SourceFinalizationRequired(f"{source}: upstream fingerprint changed; rerun kg transform")

    def validate_record(self, path, *, upstream=False, expected_source=None):
        """Validate one candidate with cycle detection; scoped records never establish a full upstream."""
        path = Path(path).resolve()
        key = (path, upstream, expected_source)
        if key in self.checked:
            return
        if path in self.active:
            raise SourceFinalizationRequired(f"Cyclic upstream dependency at {path}")
        self.active.add(path)
        try:
            report = self._load(path)
            source, cls, _, code = self._check_record(path, report)
            if expected_source is not None and source != expected_source:
                raise SourceFinalizationRequired(f"Expected upstream {expected_source}, not {source}, at {path}")
            scoped = self._scoped_ontology(path, report, source)
            if scoped and upstream:
                raise SourceFinalizationRequired(f"Scoped ontology record cannot establish a whole upstream: {path}")
            self._check_marker(path, report, source, cls, code)
            self.checked.add(key)
        finally:
            self.active.remove(path)

    def validate_path(self, path):
        """Accept a configured member only through a current applicable completion record."""
        path = Path(path).resolve()
        errors = []
        for record_path in sorted(path.parent.glob(f"*{FINALIZATION_FILE}")):
            try:
                report = self._load(record_path)
                if path.name not in report.get("members", {}):
                    continue
                self.validate_record(record_path)
                return
            except SourceFinalizationRequired as error:
                errors.append(str(error))
        detail = "; ".join(errors) or "no applicable producer completion record"
        raise SourceFinalizationRequired(f"{path}: {detail}")


def verify_source_freshness(paths):
    """Reject stale selected sources and declared dependencies before staging or running KGX."""
    gate = _SourceFreshness()
    for path in paths:
        gate.validate_path(path)
