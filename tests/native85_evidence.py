"""Select only explicitly located, hash-pinned evidence for the opt-in native85 test."""

import hashlib
import os
import stat
from pathlib import Path

COHORT_ENV = "BACDIVE_ANCESTRY_NATIVE_COHORT"


def load_native85_cohort(admission, expected_sha256):
    """Read the explicitly selected local cohort through its real retained admission."""
    locator = os.environ.get(COHORT_ENV)
    if not locator:
        raise ValueError(f"{COHORT_ENV}: an explicit absolute cohort file path is required")
    if "\0" in locator:
        raise ValueError(f"{COHORT_ENV}: invalid NUL byte in cohort file path")
    path = Path(locator)
    if not path.is_absolute():
        raise ValueError(f"{COHORT_ENV}: cohort file path must be absolute")
    try:
        mode = path.stat().st_mode
    except OSError as error:
        raise ValueError(f"{COHORT_ENV}: cohort file is missing or unreadable") from error
    if not stat.S_ISREG(mode):
        raise ValueError(f"{COHORT_ENV}: cohort path must select a regular file")
    payload = admission.capture(path, retain=True)
    if hashlib.sha256(payload).hexdigest() != expected_sha256:
        raise ValueError(f"{COHORT_ENV}: cohort SHA-256 mismatch")
    return payload
