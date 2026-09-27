"""Structural CAS registry-number admission, without inferring chemical identity."""

import re


def valid_cas(identifier: str) -> bool:
    """Validate a canonical CAS CURIE's syntax and checksum, never repair it."""
    if not isinstance(identifier, str) or not re.fullmatch(r"cas:[1-9][0-9]{1,6}-[0-9]{2}-[0-9]", identifier):
        return False
    digits = identifier.removeprefix("cas:").replace("-", "")
    return sum(i * int(value) for i, value in enumerate(reversed(digits[:-1]), 1)) % 10 == int(digits[-1])


def invalid_cas_identifier(value: str, *, allow_bare: bool = False) -> bool:
    """
    Reject recognizable invalid CAS inputs; leave other namespaces/names alone.

    Case and the legacy CAS-RN prefix are representation aliases only. Bare
    registry-shaped names are checked only at lexical lookup boundaries. No
    replacement digit, substance, or equivalence is ever supplied.
    """
    if not isinstance(value, str):
        return False
    value = value.strip()
    prefix, separator, local = value.partition(":")
    if separator and prefix.casefold() in {"cas", "cas-rn"}:
        return not valid_cas("cas:" + local)
    if allow_bare and re.fullmatch(r"\d+-\d+-\d+", value):
        # Recognize Unicode digit lookalikes as CAS-shaped input so the ASCII
        # validator rejects them, rather than treating them as ordinary names.
        return not valid_cas("cas:" + value)
    return False
