"""Exact-byte AST reuse must preserve freshness and bounded memory (#1862)."""

import ast
import hashlib
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from kg_microbe.utils import transform_fingerprint as fingerprint


@pytest.fixture(autouse=True)
def isolated_ast_cache():
    """Keep reuse assertions independent of earlier tests and leave no cached sources."""
    fingerprint._cached_source_behaviour_digest.cache_clear()
    try:
        yield
    finally:
        fingerprint._cached_source_behaviour_digest.cache_clear()


def test_repeated_content_reuses_parse_but_reads_every_selected_file(tmp_path):
    """Identical bytes can share AST work across paths without caching filesystem reads."""
    first, second = tmp_path / "first.py", tmp_path / "second.py"
    first.write_bytes(b"value = 1\n")
    second.write_bytes(first.read_bytes())
    reads = []
    original_read = Path.read_bytes

    def read(path):
        """Observe every actual read without replacing its contents."""
        reads.append(path)
        return original_read(path)

    with patch.object(Path, "read_bytes", read), patch.object(ast, "parse", wraps=ast.parse) as parse:
        original = fingerprint._behaviour_digest(first)
        assert fingerprint._behaviour_digest(first) == original
        assert fingerprint._behaviour_digest(second) == original
    assert reads == [first, first, second]
    assert parse.call_count == 1


def test_same_size_restored_mtime_change_and_deletion_are_observed(tmp_path):
    """A warm cache cannot bless changed or missing source bytes behind unchanged metadata."""
    path = tmp_path / "source.py"
    original = b"value = 1\n"
    path.write_bytes(original)
    before = fingerprint.code_fingerprint(tmp_path, tmp_path)
    stamp = path.stat()
    path.write_bytes(b"value = 2\n")
    os.utime(path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    assert path.stat().st_size == stamp.st_size
    assert path.stat().st_mtime_ns == stamp.st_mtime_ns
    assert fingerprint.code_fingerprint(tmp_path, tmp_path) != before
    path.unlink()
    assert fingerprint._behaviour_digest(path) == b"<absent>"
    assert fingerprint.code_fingerprint(tmp_path, tmp_path) != before
    path.write_bytes(original)
    assert fingerprint.code_fingerprint(tmp_path, tmp_path) == before


def test_cached_identical_sources_do_not_hide_tree_membership_or_names(tmp_path):
    """Added, renamed and removed paths still change the freshly enumerated tree."""
    first, second, renamed = (tmp_path / name for name in ("first.py", "second.py", "renamed.py"))
    first.write_bytes(b"value = 1\n")
    before = fingerprint.code_fingerprint(tmp_path, tmp_path)
    second.write_bytes(first.read_bytes())
    added = fingerprint.code_fingerprint(tmp_path, tmp_path)
    assert added != before
    second.rename(renamed)
    assert fingerprint.code_fingerprint(tmp_path, tmp_path) not in {before, added}
    renamed.unlink()
    assert fingerprint.code_fingerprint(tmp_path, tmp_path) == before


def test_cached_digest_preserves_ast_formatting_and_docstring_semantics(tmp_path):
    """Keep the previous digest bytes, formatting equivalence and docstring sensitivity."""
    path = tmp_path / "source.py"
    source = b'"""Original documentation."""\nvalue = 1\n'
    expected = hashlib.sha256(ast.dump(ast.parse(source.decode("utf-8"))).encode("utf-8")).digest()
    path.write_bytes(source)
    assert fingerprint._behaviour_digest(path) == expected
    path.write_bytes(b'# A comment\n"""Original documentation."""\n\nvalue=1\n')
    assert fingerprint._behaviour_digest(path) == expected
    path.write_bytes(b'"""Changed documentation."""\nvalue = 1\n')
    assert fingerprint._behaviour_digest(path) != expected


@pytest.mark.parametrize("source", [b"def broken(:\n", b"value = '\xff'\n"])
def test_invalid_source_keeps_exact_raw_byte_fallback(tmp_path, source):
    """Syntax and UTF-8 failures retain their original content-sensitive fallback."""
    path = tmp_path / "source.py"
    path.write_bytes(source)
    expected = hashlib.sha256(source).digest()
    assert fingerprint._behaviour_digest(path) == expected
    assert fingerprint._behaviour_digest(path) == expected
    changed = source + b"# changed\n"
    path.write_bytes(changed)
    assert fingerprint._behaviour_digest(path) == hashlib.sha256(changed).digest() != expected


def test_large_sources_bypass_cache_without_changing_their_digest(tmp_path, monkeypatch):
    """Exercise both sides of the retention boundary with small, otherwise equivalent sources."""
    path = tmp_path / "source.py"
    source = b"value = 1\n"
    monkeypatch.setattr(fingerprint, "_BEHAVIOUR_CACHE_SOURCE_LIMIT", len(source))
    path.write_bytes(source)
    with patch.object(ast, "parse", wraps=ast.parse) as parse:
        expected = fingerprint._behaviour_digest(path)
        assert fingerprint._behaviour_digest(path) == expected
        assert parse.call_count == 1
        path.write_bytes(source + b"# exceeds cache limit\n")
        assert fingerprint._behaviour_digest(path) == expected
        assert fingerprint._behaviour_digest(path) == expected
        assert parse.call_count == 3
    assert fingerprint._cached_source_behaviour_digest.cache_info().currsize == 1


def test_source_cache_evicts_old_entries(tmp_path):
    """Distinct small source versions cannot accumulate beyond the declared entry limit."""
    path = tmp_path / "source.py"
    path.write_bytes(b"value = 0\n")
    original = fingerprint._behaviour_digest(path)
    for value in range(1, fingerprint._BEHAVIOUR_CACHE_ENTRIES + 1):
        path.write_text(f"value = {value}\n", encoding="utf-8")
        fingerprint._behaviour_digest(path)
    cache = fingerprint._cached_source_behaviour_digest
    assert cache.cache_info().currsize == fingerprint._BEHAVIOUR_CACHE_ENTRIES
    path.write_bytes(b"value = 0\n")
    with patch.object(ast, "parse", wraps=ast.parse) as parse:
        assert fingerprint._behaviour_digest(path) == original
    assert parse.call_count == 1
