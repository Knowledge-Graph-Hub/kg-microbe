"""Identity-only refresh preserves YAML meaning and truthful writer provenance (#1237)."""

import gzip
import hashlib
from pathlib import Path

import pytest
import yaml

from scripts import consolidate_chemical_mappings as refresh
from tests.test_mim_conservative_refresh import FIELDS, _metadata, _row

TOOL = "kg-microbe/scripts/consolidate_chemical_mappings.py"
PRIOR_PAIR = "mapping_tool: prior/writer.py\nmapping_tool_version: 'sha256:old'\n"
TAIL = "unrelated: # preserve this comment\n  nested: ['two', 'one']\n  literal: 'colon: # quoted'\n"


def _source(tmp_path, fragment, newline="\n"):
    """Write one valid, immutable test assertion and literal metadata controls."""
    path = tmp_path / "baseline.tsv"
    prefix = yaml.safe_dump(_metadata(), sort_keys=False)
    header = "".join("# " + line + newline for line in (prefix + fragment + TAIL).splitlines())
    row = _row("kgm.name:water", "CHEBI:15377", "water", name="water", comment="canonical_name")
    body = ("\t".join(FIELDS) + newline + "\t".join(row[field] for field in FIELDS) + newline).encode()
    path.write_bytes(header.encode() + body)
    return path, body, "".join("# " + line + newline for line in prefix.splitlines()).encode()


def _read(path):
    """Retain literal header/data bytes and separately parse the header semantics."""
    payload = gzip.decompress(path.read_bytes()) if path.suffix == ".gz" else path.read_bytes()
    lines = payload.splitlines(keepends=True)
    stop = next(index for index, line in enumerate(lines) if not line.startswith(b"#"))
    header = b"".join(lines[:stop])
    metadata = yaml.safe_load("".join(line.decode()[1:].removeprefix(" ") for line in lines[:stop]))
    return metadata, header, b"".join(lines[stop:])


@pytest.mark.parametrize(
    "description",
    [
        "mapping_set_description: plain text\n",
        "mapping_set_description: 'single ''quoted'' text'\n",
        'mapping_set_description: "double \\"quoted\\" text"\n',
        "mapping_set_description: >\n  folded first\n  folded second\n",
        "mapping_set_description: >-\n  folded first\n  folded second\n",
        "mapping_set_description: |\n  literal first\n  literal second\n",
        "mapping_set_description: |+\n  literal first\n\n",
        "mapping_set_description: |-\n  literal first\n  literal second\n",
        "mapping_set_description: 'line one\n  line two'\n",
        'mapping_set_description: "unicode \\u03b1 and \\u2028 exact"\n',
    ],
)
@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_scalar_meaning_tool_pair_unrelated_bytes_and_fixed_point(tmp_path, description, newline):
    """Actual SSSOM validation accepts each style without corrupting its scalar value."""
    source, body, prefix = _source(tmp_path, PRIOR_PAIR + description, newline)
    original = source.read_bytes()
    original_metadata, _, _ = _read(source)
    first, second = tmp_path / "first.tsv.gz", tmp_path / "second.tsv.gz"
    expected_stats = {"rows_read": 1, "rows_removed": 0, "rows_relabelled": 0}
    assert refresh.refresh_identity_policy(source, first) == expected_stats
    assert refresh.refresh_identity_policy(first, second) == expected_stats
    metadata, header, actual_body = _read(first)
    marker = f" Ingredient identity policy sha256:{refresh.ingredient_policy_fingerprint()}."
    assert metadata["mapping_set_description"] == original_metadata["mapping_set_description"] + marker
    assert metadata["mapping_set_description"].count(marker) == 1
    assert metadata["mapping_tool"] == TOOL
    writer_hash = hashlib.sha256(Path(refresh.__file__).read_bytes()).hexdigest()
    assert metadata["mapping_tool_version"] == "sha256:" + writer_hash
    affected = {"mapping_tool", "mapping_tool_version", "mapping_set_description"}
    assert {key: value for key, value in metadata.items() if key not in affected} == {
        key: value for key, value in original_metadata.items() if key not in affected
    }
    assert header.startswith(prefix)
    assert header.endswith("".join("# " + line + newline for line in TAIL.splitlines()).encode())
    assert actual_body == body
    assert first.read_bytes() == second.read_bytes()
    assert source.read_bytes() == original


@pytest.mark.parametrize(
    "fragment",
    [
        "",
        "mapping_tool: old.py\n",
        "mapping_tool_version: old-version\n",
        "mapping_set_description: existing text\n",
        PRIOR_PAIR,
    ],
)
def test_missing_fields_gain_actual_writer_pair(tmp_path, fragment):
    """Absent or partial provenance must never remain a false or incomplete pair."""
    source, body, _ = _source(tmp_path, fragment)
    output = tmp_path / "result.tsv.gz"
    refresh.refresh_identity_policy(source, output)
    metadata, _, actual_body = _read(output)
    assert metadata["mapping_tool"] == TOOL
    assert metadata["mapping_tool_version"] == refresh.script_fingerprint()
    prior_description = (yaml.safe_load(fragment) or {}).get("mapping_set_description", "")
    assert metadata["mapping_set_description"] == prior_description + (
        f" Ingredient identity policy sha256:{refresh.ingredient_policy_fingerprint()}."
    )
    assert actual_body == body


def test_prior_policy_suffixes_replace_without_losing_original_newlines(tmp_path):
    """Only previous trailing policy annotations are replaced, never original content."""
    old = " Ingredient identity policy sha256:" + "a" * 64 + "."
    original = 'Original "quote"\nretained newline\n'
    fragment = yaml.safe_dump({"mapping_set_description": original + old + old})
    source, _, _ = _source(tmp_path, PRIOR_PAIR + fragment)
    output = tmp_path / "result.tsv.gz"
    refresh.refresh_identity_policy(source, output)
    assert _read(output)[0]["mapping_set_description"] == original + (
        f" Ingredient identity policy sha256:{refresh.ingredient_policy_fingerprint()}."
    )


@pytest.mark.parametrize(
    "fragment,reason",
    [
        (PRIOR_PAIR + "mapping_tool: second.py\n", "Duplicate"),
        (PRIOR_PAIR + "mapping_tool_version: other\n", "Duplicate"),
        ("mapping_set_description: first\nmapping_set_description: second\n", "Duplicate"),
        ("extra:\n  nested: one\n  nested: two\n", "Duplicate"),
        ('mapping_set_description: "unterminated\n', "Malformed"),
        ("mapping_set_description: null\n", "must be a string"),
        ("mapping_set_description: false\n", "must be a string"),
        ("mapping_set_description: 123\n", "must be a string"),
        ("mapping_set_description: [a, b]\n", "must be a string"),
        ("mapping_set_description: {a: b}\n", "must be a string"),
        ("mapping_tool: null\n", "must be a string"),
        ("mapping_tool_version: 123\n", "must be a string"),
        ("mapping_set_description: &shared valid\nextra: *shared\n", "aliases"),
        ("extra: !!python/object:unsafe {}\n", "Malformed"),
        ("? [complex, key]\n: invalid\n", "keys must be strings"),
        ("---\nnew_document: unsupported\n", "Malformed"),
    ],
)
def test_invalid_metadata_never_replaces_existing_candidate(tmp_path, fragment, reason):
    """Reject ambiguity and bad scalar types before atomic output publication."""
    source, _, _ = _source(tmp_path, fragment)
    original = source.read_bytes()
    output = tmp_path / "candidate.tsv.gz"
    output.write_bytes(b"previous validated candidate")
    with pytest.raises(ValueError, match=reason):
        refresh.refresh_identity_policy(source, output)
    assert source.read_bytes() == original
    assert output.read_bytes() == b"previous validated candidate"


@pytest.mark.parametrize("terminator", ["...", "... # end comment"])
def test_explicit_document_terminator_keeps_new_fields_inside_metadata(terminator):
    """Absent fields are inserted before a valid YAML document end marker."""
    original = ["# ---\n", "# unrelated: value\n", f"# {terminator}\n"]
    output = refresh._refresh_identity_metadata(original, "a" * 64)
    parsed = yaml.safe_load("".join(line[2:] for line in output))
    assert parsed["unrelated"] == "value"
    assert parsed["mapping_tool"] == TOOL
    assert output[0] == original[0] and output[-1] == original[-1]


def test_indented_ellipsis_is_unchanged_scalar_content_not_document_end():
    """An unrelated block literal must not receive metadata insertion in its body."""
    original = ["# unrelated: |\n", "#   Title\n", "#   ...\n", "#   end\n"]
    output = refresh._refresh_identity_metadata(original, "a" * 64)
    parsed = yaml.safe_load("".join(line[2:] for line in output))
    assert parsed["unrelated"] == "Title\n...\nend\n"
    assert output[: len(original)] == original
    assert parsed["mapping_tool"] == TOOL


@pytest.mark.parametrize("separator", ["\x85", "\u2028", "\u2029"])
def test_raw_unicode_separator_does_not_shift_physical_header_spans(separator):
    """Unsupported raw separators fail closed rather than erase unrelated fields."""
    original = [f'# mapping_set_description: "first{separator}second"\n', "# unrelated: preserve\n"]
    with pytest.raises(ValueError, match="Unsupported raw Unicode line separator"):
        refresh._refresh_identity_metadata(original, "a" * 64)


def test_multiple_keys_hidden_on_one_physical_header_line_fail_closed():
    """A semantic span must not overwrite another field on the same physical row."""
    lines = ["# mapping_set_description: first\u2028unrelated: keep\n"]
    with pytest.raises(ValueError, match="Unsupported raw Unicode line separator"):
        refresh._refresh_identity_metadata(lines, "a" * 64)
