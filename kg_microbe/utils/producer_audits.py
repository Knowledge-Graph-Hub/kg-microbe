"""Preserve mandatory producer disposition reports through finalization and merge."""

from pathlib import Path


def required_producer_audits(producer):
    """Allow only distinct local sidecars, never graph or finalizer-owned members."""
    from kg_microbe.utils.source_finalization import SourceFinalizationRequired

    names = getattr(producer, "REQUIRED_AUDIT_FILES", ())
    if (
        not isinstance(names, tuple)
        or any(
            not isinstance(name, str)
            or not name
            or Path(name).name != name
            or "\\" in name
            or not name.endswith(".tsv")
            or name.endswith(
                (
                    "nodes.tsv",
                    "edges.tsv",
                    "source_canonicalization.tsv",
                    "source_reference_resolution.tsv",
                    "go_reference_resolution.tsv",
                )
            )
            for name in names
        )
        or len(set(names)) != len(names)
    ):
        raise SourceFinalizationRequired("Invalid mandatory producer audit declaration")
    return names


def _identity(path):
    """Require a regular non-symlink report and bind its exact bytes."""
    from kg_microbe.merge_utils.source_admission import SourceAdmission
    from kg_microbe.utils.source_finalization import SourceFinalizationRequired

    if path.is_symlink() or not path.is_file():
        raise SourceFinalizationRequired(f"Mandatory producer audit missing or symlinked: {path}")
    admission = SourceAdmission()
    identity = admission.capture(path)
    admission.verify(metadata_only=True)
    return identity


def record_producer_audit(transform, name):
    """Record successful producer output once; finalization must not restamp changed bytes."""
    from kg_microbe.utils.source_finalization import SourceFinalizationRequired

    try:
        if name not in required_producer_audits(type(transform)):
            raise SourceFinalizationRequired(f"Undeclared producer audit: {name!r}")
        directory = str(Path(transform.output_dir).resolve())
        previous_directory = transform._producer_audit_directory
        if previous_directory is not None and previous_directory != directory:
            raise SourceFinalizationRequired("Producer audit output directory changed within one run")
        identity = _identity(Path(transform.output_dir) / name)
        previous = transform._producer_audit_snapshots.get(name)
        if previous is not None and previous != identity:
            raise SourceFinalizationRequired(f"Producer audit changed within one run: {name}")
        transform._producer_audit_directory = directory
        transform._producer_audit_snapshots[name] = identity
    except BaseException as exc:
        transform._producer_audit_error = str(exc)
        raise


def verify_producer_audits(transform, *, output_dir=None):
    """Verify original producer identities against the original or staged report bytes."""
    from kg_microbe.utils.source_finalization import SourceFinalizationRequired

    required = set(required_producer_audits(type(transform)))
    snapshots = getattr(transform, "producer_audit_snapshots", {})
    if getattr(transform, "_producer_audit_error", None) is not None:
        raise SourceFinalizationRequired("Producer audit recording failed; rerun the producer")
    if set(snapshots) != required:
        raise SourceFinalizationRequired("Missing or unexpected producer audit snapshots; rerun the producer")
    if required and transform._producer_audit_directory != str(Path(transform.output_dir).resolve()):
        raise SourceFinalizationRequired("Producer audit output directory changed; rerun the producer")
    directory = Path(output_dir) if output_dir is not None else Path(transform.output_dir)
    for name, expected in snapshots.items():
        if _identity(directory / name) != expected:
            raise SourceFinalizationRequired(f"Producer audit changed after emission: {name}; rerun the producer")
    return snapshots


def verify_recorded_producer_audits(producer, report, report_path, admission=None):
    """Enforce current registered requirements even if a report omits its own evidence."""
    from kg_microbe.utils.source_finalization import SourceFinalizationRequired, _valid_member_identities

    required = set(required_producer_audits(producer))
    snapshots = report.get("producer_audit_members", {})
    if (
        not isinstance(snapshots, dict)
        or set(snapshots) != required
        or (snapshots and not _valid_member_identities(snapshots))
    ):
        raise SourceFinalizationRequired("Missing or invalid mandatory producer audit snapshots; rerun the producer")
    if required and report_path is None:
        raise SourceFinalizationRequired("Missing producer audit location; rerun the producer")
    audits = report.get("audit_members", {})
    if not isinstance(audits, dict):
        raise SourceFinalizationRequired("Malformed mandatory audit collection; rerun the producer")
    for name, expected in snapshots.items():
        if audits.get(name) != expected:
            raise SourceFinalizationRequired(f"Mandatory producer audit identity omitted or inconsistent: {name}")
        path = Path(report_path).parent / name
        if path.is_symlink() or not path.is_file():
            raise SourceFinalizationRequired(f"Mandatory producer audit missing or symlinked: {path}")
        actual = admission.capture(path) if admission is not None else _identity(path)
        if actual != expected:
            raise SourceFinalizationRequired(f"Mandatory producer audit changed: {name}; rerun the producer")
