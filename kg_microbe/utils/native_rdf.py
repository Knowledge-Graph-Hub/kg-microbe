"""Finite native RDF selectors must recognize all legal IRI spellings without rewriting evidence."""

import re

_IRI_ESCAPE = re.compile(rb"\\(?:u([0-9A-Fa-f]{4})|U([0-9A-Fa-f]{8}))")


def decoded_iri_subject(subject, *, authority="Native RDF"):
    """
    Decode N-Triples IRI UCHAR escapes solely for semantic membership selection.

    Callers retain original assertion bytes in evidence hashes and audits. Invalid
    scalar values and incomplete/unsupported escapes fail closed (#1295/#1300).
    """
    if b"\\" not in subject:
        return subject

    def replace(match):
        """Require Unicode scalar values, not invalid code points or lone surrogates."""
        value = int(match.group(1) or match.group(2), 16)
        if value > 0x10FFFF or 0xD800 <= value <= 0xDFFF:
            raise ValueError(f"{authority} native subject has an invalid Unicode escape")
        return chr(value).encode("utf-8")

    decoded = _IRI_ESCAPE.sub(replace, subject)
    if b"\\" in decoded:
        raise ValueError(f"{authority} native subject has an invalid IRI escape")
    return decoded
