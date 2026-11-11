"""Bind LPSN API citation labels to consumed record bytes and selected locators (#1838)."""

import csv
import io
import re
from pathlib import Path

from kg_microbe.merge_utils.source_admission import SourceAdmission
from kg_microbe.utils.source_finalization import SourceFinalizationRequired

AUDIT_FILE = "lpsn_api_records.tsv"
AUDIT_COLUMNS = ("kind", "record_no", "state", "locator", "path", "sha256")
GSS_ROLE = "lpsn_api_gss_nodes"
RECORD_ROLE_PREFIX = "lpsn_api_record_"
CACHE_SUBDIR = "lpsn/api_cache"


def validate_record_no(record_no):
    """Require a literal numeric record identifier before constructing a cache path."""
    if not isinstance(record_no, str) or re.fullmatch(r"[0-9]+", record_no) is None:
        raise SourceFinalizationRequired(f"Invalid LPSN API requested record identifier: {record_no!r}")


def validate_record(record, record_no):
    """Reject missing, malformed or unrelated API responses before attributing their fields."""
    validate_record_no(record_no)
    if not isinstance(record, dict) or type(record.get("id")) not in (int, str) or str(record["id"]) != record_no:
        raise SourceFinalizationRequired(f"LPSN API payload identity does not match requested record {record_no}")
    return record


def audit_rows(contract):
    """Serialize deterministic evidence for every selected API record, including absent cache entries."""
    yield ["gss", "", "present", *(contract["gss"][key] for key in ("locator", "path", "sha256"))]
    for record_no, item in sorted(contract["records"].items()):
        yield ["api", record_no, *(item[key] for key in ("state", "locator", "path", "sha256"))]


def verify_record_audit(contract, audit_path, *, admission=None):
    """Check required audit bytes, retaining them only for a read-only admission epoch."""
    guard = admission if admission is not None else SourceAdmission()
    try:
        rows = list(csv.reader(io.StringIO(guard.capture(audit_path, retain=True).decode("utf-8")), delimiter="\t"))
    except (UnicodeError, csv.Error) as error:
        raise SourceFinalizationRequired("Unreadable LPSN API required record audit") from error
    if rows != [list(AUDIT_COLUMNS), *audit_rows(contract)]:
        raise SourceFinalizationRequired("LPSN API required record audit disagrees with consumed inputs")
    guard.verify(metadata_only=True)


def verify_native_contract(contract, snapshots, raw_dir, *, audit_path=None, admission=None):
    """Revalidate selected lexical paths as well as bytes before completion and merge admission."""
    guard = admission if admission is not None else SourceAdmission()
    guard.verify(metadata_only=True)
    raw = Path(raw_dir).absolute()
    if (
        not isinstance(contract, dict)
        or set(contract) != {"version", "raw_locator", "raw_directory", "cache_directory", "gss", "records"}
        or type(contract["version"]) is not int
        or contract["version"] != 1
        or contract["raw_locator"] != str(raw)
        or contract["raw_directory"] != str(guard.bind_path(raw))
        or contract["cache_directory"] != str(guard.bind_path(raw / CACHE_SUBDIR))
        or not isinstance(contract["gss"], dict)
        or set(contract["gss"]) != {"locator", "path", "sha256"}
        or not isinstance(contract["records"], dict)
        or not isinstance(snapshots, dict)
    ):
        raise SourceFinalizationRequired("LPSN API native input inventory missing or changed; rerun the producer")
    gss = contract["gss"]
    if not isinstance(gss["locator"], str) or not Path(gss["locator"]).is_absolute():
        raise SourceFinalizationRequired("LPSN API GSS selection locator is missing")
    expected_roles = {GSS_ROLE}
    selected = [(GSS_ROLE, gss, Path(gss["locator"]), "present")]
    for record_no, record in contract["records"].items():
        validate_record_no(record_no)
        if (
            not isinstance(record, dict)
            or set(record) != {"state", "locator", "path", "sha256"}
            or record["state"] not in ("present", "absent")
        ):
            raise SourceFinalizationRequired("Malformed LPSN API selected-record provenance")
        role = RECORD_ROLE_PREFIX + record_no
        if record["state"] == "present":
            expected_roles.add(role)
        selected.append((role, record, raw / CACHE_SUBDIR / f"{record_no}.json", record["state"]))
    actual_roles = {role for role in snapshots if role == GSS_ROLE or role.startswith(RECORD_ROLE_PREFIX)}
    if actual_roles != expected_roles:
        raise SourceFinalizationRequired("LPSN API consumed-record inventory disagrees with selected records")
    for role, record, locator, state in selected:
        if record["locator"] != str(locator) or record["path"] != str(guard.bind_path(locator)):
            raise SourceFinalizationRequired(f"LPSN API selected input locator changed: {role}")
        identity = guard.capture(locator, optional=state == "absent")
        if state == "absent":
            if identity is not None or record["sha256"] != "":
                raise SourceFinalizationRequired(f"LPSN API previously absent cache record appeared: {role}")
        elif identity["sha256"] != record["sha256"] or snapshots.get(role) != {
            "path": record["path"],
            "sha256": record["sha256"],
        }:
            raise SourceFinalizationRequired(f"LPSN API consumed record changed: {role}")
    if audit_path is not None:
        verify_record_audit(contract, audit_path, admission=guard)
    guard.verify(metadata_only=True)
    return guard
