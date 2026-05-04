#!/usr/bin/env python3
"""Audit KG-Microbe code + curation files for hardcoded ontology mappings.

Successor to the v1 scanner that only walked top-level ``Assign`` nodes
in ``transform_utils/*.py``. Lessons from the 2026-05-03 cleanup pass:

1. v1 reported "100% data-driven" because it missed all 11 inline
   METPO/RO CURIEs in bacdive.py -- those were function-call arguments
   and method-local dicts of <6 entries, not top-level dicts.
2. v1 only scanned ``transform_utils/<name>/mappings/`` and missed the
   19 curation files under repo-root ``mappings/`` (the actual canonical
   curation hub).
3. v1 didn't notice ``translation_table.yaml`` was 504 lines with zero
   consumers in the codebase.
4. v1 didn't detect schema heterogeneity across canonical curation files
   or repeated-callsite patterns ("data masquerading as code") where the
   same helper is called N times with different CURIE literals.

v2 fixes all of those:

* **Inline CURIE scan** walks every ``Constant(str)`` AST node and
  flags any string matching the broadened CURIE regex (covers mixed-
  case prefixes, dotted prefixes, hyphens). Excludes docstrings.
* **Method-local dict scan** runs at *any* AST nesting level with a
  threshold of 3 entries (down from 5) so small but suspicious dicts
  (e.g. the 3-entry pathogenicity dict at bacdive.py:1336) are caught.
* **Repeated-callsite scan** groups ``Call`` nodes by callee name and
  flags clusters where the same helper is invoked N>=3 times with
  different CURIE first-args -- a strong "this should be table-driven"
  signal.
* **Whole-repo curation inventory** scans both
  ``transform_utils/*/mappings/`` and repo-root ``mappings/`` (incl.
  ``mappings/canonical/``), reporting schema fingerprints.
* **Schema-heterogeneity warning** fingerprints each TSV's header and
  warns when files claim the same purpose but have different headers.
* **Dead-file detection** greps every mapping file's basename across
  ``kg_microbe/``, ``scripts/``, ``tests/``. Files with zero textual
  references are flagged.

Invoke from the repo root::

    python3 .claude/skills/audit-mappings/audit_mappings.py
    python3 .claude/skills/audit-mappings/audit_mappings.py --transform bacdive
    python3 .claude/skills/audit-mappings/audit_mappings.py --format md > report.md
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import yaml


# Broadened CURIE regex. Covers:
#   - Standard `[A-Z]+:[0-9]+`        e.g. CHEBI:15377
#   - Mixed-case lowercased prefixes  e.g. mesh:D000001
#   - Dotted prefixes                 e.g. pubchem.compound:5793
#   - Underscore prefixes             e.g. NCBITaxon:9606
#   - Hyphenated prefixes             e.g. CAS-RN:7647-14-5
# v1's regex (`[A-Z]+:[a-z_]+\d*|[A-Z]+:\d+`) missed all of these.
_CURIE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9._-]*:[A-Za-z0-9._:-]+$")

# Per-prefix recognition for the heuristic that decides when an inline
# string literal is "data-shaped" (a CURIE) vs. "config-shaped" (a URL,
# a class path, etc.). Anything starting with one of these prefixes is
# treated as a CURIE.
_KNOWN_CURIE_PREFIXES = frozenset({
    "METPO", "CHEBI", "GO", "EC", "RO", "BFO", "NCIT", "PATO", "RHEA",
    "ENVO", "UBERON", "FOODON", "PO", "PR", "CL", "MICRO", "BTO",
    "NCBITaxon", "GTDB", "GenBank", "MONDO", "HP", "DOID", "TAXRANK",
    "UPA", "GENEPIO", "FAO", "PRIDE", "PCO", "SNOMED",
    "mesh", "cas", "pubchem.compound", "registry",
    "kgmicrobe.compound", "kgmicrobe.activity", "kgmicrobe.trait",
    "kgmicrobe.pathway", "kgmicrobe.assay", "kgmicrobe.strain",
    "kgmicrobe.species", "kgmicrobe.genus",
    "bacdive", "bacdive.isolation_source", "mediadive.medium",
    "mediadive.solution", "mediadive.ingredient",
    "mediadive.medium-type", "MIM", "skos", "semapv", "biolink",
    "obo", "infores",
})

# Dirs to skip during code/file scanning.
_EXCLUDE_DIRS = frozenset({
    "__pycache__", ".pytest_cache", ".git", ".tox", ".venv", "venv",
    "node_modules", "tmp", "data", "tests/resources",
})

# Variable-name heuristics: dict-style assignments named like these are
# config / API / column metadata, not mappings. Keep skipping these.
_ACCEPTABLE_DICT_NAME_FRAGMENTS = (
    "API_BASE", "ENDPOINT", "BASE_URL", "FILE_PATH", "COLUMN", "HEADER",
    "BIOLINK_", "CATEGORY", "PREFIX", "ALIASES",  # ALIASES = const map
)

# Repeated-callsite detection threshold: if the same callee is invoked
# this many times across one file with a CURIE-literal as one of its
# args, flag as "table-shaped call site".
_REPEATED_CALLSITE_MIN = 3

# Method-local-dict detection threshold (lowered from 5).
_DICT_CURIE_MIN = 3


def _is_curie(value: str) -> bool:
    """True if the string looks like a CURIE we care about."""
    if not value or not _CURIE_RE.match(value):
        return False
    prefix = value.split(":", 1)[0]
    return prefix in _KNOWN_CURIE_PREFIXES


def _docstring_byte_ranges(source: str) -> List[Tuple[int, int]]:
    """Return inclusive byte ranges of all docstrings in source.

    Used to suppress CURIE matches inside triple-quoted blocks (which
    are usually example references, not data).
    """
    ranges: List[Tuple[int, int]] = []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return ranges
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            ds = ast.get_docstring(node, clean=False)
            if ds and node.body:
                first = node.body[0]
                if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                    start = first.lineno
                    end = first.end_lineno or start
                    ranges.append((start, end))
    return ranges


class CodeScanner:
    """AST-based scanner for inline CURIE usage in a single Python file."""

    def __init__(self, py_file: Path):
        self.path = py_file
        self.source = py_file.read_text(errors="replace")
        try:
            self.tree: Optional[ast.AST] = ast.parse(self.source)
        except SyntaxError:
            self.tree = None
        self._docstring_ranges = _docstring_byte_ranges(self.source) if self.tree else []

    def _line_in_docstring(self, lineno: int) -> bool:
        return any(start <= lineno <= end for start, end in self._docstring_ranges)

    def find_inline_curies(self) -> List[Dict[str, Any]]:
        """Every `Constant(str)` with a CURIE value, outside docstrings."""
        out: List[Dict[str, Any]] = []
        if self.tree is None:
            return out
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if _is_curie(node.value) and not self._line_in_docstring(node.lineno):
                    out.append({
                        "file": self.path.name,
                        "line": node.lineno,
                        "curie": node.value,
                    })
        return out

    def find_local_dicts(self) -> List[Dict[str, Any]]:
        """Dict literals (any nesting) with at least ``_DICT_CURIE_MIN`` CURIE values."""
        out: List[Dict[str, Any]] = []
        if self.tree is None:
            return out
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Dict):
                curies = self._count_curie_values(node)
                if curies < _DICT_CURIE_MIN:
                    continue
                # Suppress acceptable variable names if this dict is a
                # top-level Assign target.
                parent_name = self._parent_assign_name(node)
                if parent_name and any(
                    frag in parent_name.upper() for frag in _ACCEPTABLE_DICT_NAME_FRAGMENTS
                ):
                    continue
                out.append({
                    "file": self.path.name,
                    "line_start": node.lineno,
                    "line_end": node.end_lineno or node.lineno,
                    "variable": parent_name or "<inline>",
                    "entry_count": curies,
                    "type": "dict_literal",
                })
        return out

    def _count_curie_values(self, dict_node: ast.Dict) -> int:
        """Number of dict values that are CURIE strings (also descends into tuples)."""
        n = 0
        for v in dict_node.values:
            if isinstance(v, ast.Constant) and isinstance(v.value, str) and _is_curie(v.value):
                n += 1
            elif isinstance(v, (ast.Tuple, ast.List)):
                for elt in v.elts:
                    if isinstance(elt, ast.Constant) and isinstance(elt.value, str) and _is_curie(elt.value):
                        n += 1
                        break  # one CURIE per tuple is enough
        return n

    def _parent_assign_name(self, node: ast.Dict) -> Optional[str]:
        """If this Dict is the RHS of an Assign, return the LHS Name."""
        if self.tree is None:
            return None
        for parent in ast.walk(self.tree):
            if isinstance(parent, ast.Assign) and parent.value is node:
                if len(parent.targets) == 1 and isinstance(parent.targets[0], ast.Name):
                    return parent.targets[0].id
        return None

    def find_repeated_callsites(self) -> List[Dict[str, Any]]:
        """Calls to the same helper at least 3 times where one arg is a CURIE.

        Catches the "data masquerading as code" pattern: 7 calls to
        ``_process_phenotype_by_metpo_parent(value, "METPO:1000601", ...)``
        in bacdive.py that should be table-driven.
        """
        if self.tree is None:
            return []
        # callee-name -> list of (line, curies_in_args)
        by_callee: Dict[str, List[Tuple[int, List[str]]]] = defaultdict(list)
        for node in ast.walk(self.tree):
            if not isinstance(node, ast.Call):
                continue
            callee = self._callee_name(node.func)
            if not callee:
                continue
            curies = []
            for a in list(node.args) + [kw.value for kw in node.keywords]:
                if isinstance(a, ast.Constant) and isinstance(a.value, str) and _is_curie(a.value):
                    curies.append(a.value)
            if curies:
                by_callee[callee].append((node.lineno, curies))

        out: List[Dict[str, Any]] = []
        for callee, calls in by_callee.items():
            if len(calls) < _REPEATED_CALLSITE_MIN:
                continue
            distinct_curies = sorted({c for _, cs in calls for c in cs})
            if len(distinct_curies) < _REPEATED_CALLSITE_MIN:
                continue
            out.append({
                "file": self.path.name,
                "callee": callee,
                "call_count": len(calls),
                "distinct_curies": distinct_curies,
                "lines": [lineno for lineno, _ in calls],
                "type": "repeated_callsite",
            })
        return out

    @staticmethod
    def _callee_name(node: ast.AST) -> Optional[str]:
        """Resolve a Call.func into a string name (best-effort)."""
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return node.attr
        return None


class MappingAuditor:
    """v2 auditor: code + curation file inventory + dead-file detection."""

    def __init__(self, root_dir: Path):
        self.root = root_dir
        self.transform_utils = root_dir / "kg_microbe" / "transform_utils"

    # ---- code scan ----------------------------------------------------

    def scan_transform(self, name: str) -> Dict[str, Any]:
        tdir = self.transform_utils / name
        result = {
            "name": name,
            "inline_curies": [],
            "local_dicts": [],
            "repeated_callsites": [],
            "mapping_files": self.scan_transform_local_files(tdir),
        }
        if not tdir.is_dir():
            return result
        for py in sorted(tdir.glob("*.py")):
            if py.name.startswith("test_"):
                continue
            scanner = CodeScanner(py)
            result["inline_curies"].extend(scanner.find_inline_curies())
            result["local_dicts"].extend(scanner.find_local_dicts())
            result["repeated_callsites"].extend(scanner.find_repeated_callsites())
        return result

    def scan_all_transforms(self, only: Optional[str] = None) -> List[Dict[str, Any]]:
        if not self.transform_utils.is_dir():
            return []
        if only:
            return [self.scan_transform(only)]
        names = sorted(
            d.name for d in self.transform_utils.iterdir()
            if d.is_dir() and d.name not in _EXCLUDE_DIRS
        )
        return [self.scan_transform(n) for n in names]

    # ---- file inventory -----------------------------------------------

    def scan_transform_local_files(self, tdir: Path) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        if not tdir.is_dir():
            return out
        mappings_dir = tdir / "mappings"
        if mappings_dir.is_dir():
            for f in sorted(mappings_dir.iterdir()):
                if f.is_file():
                    out.append(self._describe_file(f, location="transform-local"))
        for f in sorted(tdir.glob("*mapping*.json")):
            out.append(self._describe_file(f, location="transform-local"))
        for f in sorted(tdir.glob("*.yaml")):
            if "mapping" in f.name or "curie" in f.name:
                out.append(self._describe_file(f, location="transform-local"))
        return out

    def scan_root_mappings(self) -> List[Dict[str, Any]]:
        """Inventory the canonical curation hub at repo-root ``mappings/``.

        Includes ``mappings/canonical/`` and any sibling subdirectories
        (consolidated, queues, proposals, etc.) -- anything outside the
        ``__pycache__`` skip list.
        """
        out: List[Dict[str, Any]] = []
        root = self.root / "mappings"
        if not root.is_dir():
            return out
        for f in self._walk_data_files(root):
            out.append(self._describe_file(f, location=str(f.parent.relative_to(self.root))))
        return out

    def _walk_data_files(self, root: Path):
        """Yield TSV/JSON/YAML/SSSOM/CSV files under root, skipping __pycache__."""
        for p in sorted(root.rglob("*")):
            if not p.is_file():
                continue
            if any(part in _EXCLUDE_DIRS for part in p.parts):
                continue
            if p.suffix in {".tsv", ".csv", ".json", ".yaml", ".yml"} or p.name.endswith(".tsv.gz"):
                yield p

    def _describe_file(self, f: Path, location: str) -> Dict[str, Any]:
        rel = f.relative_to(self.root)
        return {
            "path": str(rel),
            "name": f.name,
            "location": location,
            "size_bytes": f.stat().st_size,
            "entry_count": self._count_entries(f),
            "schema_fingerprint": self._schema_fingerprint(f),
        }

    @staticmethod
    def _count_entries(f: Path) -> int:
        try:
            if f.suffix == ".json":
                data = json.loads(f.read_text())
                if isinstance(data, (dict, list)):
                    return len(data)
                return 0
            if f.suffix in {".yaml", ".yml"}:
                data = yaml.safe_load(f.read_text())
                if isinstance(data, dict):
                    total = 0
                    for v in data.values():
                        total += len(v) if isinstance(v, (dict, list)) else 1
                    return total
                if isinstance(data, list):
                    return len(data)
                return 0
            if f.name.endswith(".tsv.gz"):
                import gzip
                with gzip.open(f, "rt") as fh:
                    return max(0, sum(1 for _ in fh) - 1)
            # plain TSV / CSV
            with f.open() as fh:
                return max(0, sum(1 for line in fh if line.strip() and not line.startswith("#")) - 1)
        except Exception:
            return 0

    @staticmethod
    def _schema_fingerprint(f: Path) -> Optional[str]:
        """First non-comment line for TSV/CSV -- used to detect schema heterogeneity."""
        if f.suffix not in {".tsv", ".csv"}:
            return None
        try:
            with f.open() as fh:
                for line in fh:
                    if not line.startswith("#") and line.strip():
                        return line.rstrip("\n")
        except Exception:
            return None
        return None

    # ---- dead-file detection ------------------------------------------

    def find_dead_files(self, files: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Mapping files whose basename has zero textual references in the codebase."""
        dead: List[Dict[str, Any]] = []
        for desc in files:
            basename = Path(desc["path"]).name
            if self._has_consumer(basename, desc["path"]):
                continue
            dead.append({**desc, "reason": "zero textual references in codebase"})
        return dead

    def _has_consumer(self, basename: str, self_path: str) -> bool:
        """Grep basename across kg_microbe/, scripts/, tests/, mappings/, .github/ workflows."""
        scopes = [
            self.root / "kg_microbe",
            self.root / "scripts",
            self.root / "tests",
            self.root / "mappings",
            self.root / ".github",
        ]
        for scope in scopes:
            if not scope.exists():
                continue
            try:
                cp = subprocess.run(
                    ["grep", "-rln", "--include=*.py", "--include=*.yml",
                     "--include=*.yaml", "--include=*.toml", "--include=*.md",
                     basename, str(scope)],
                    capture_output=True, text=True, timeout=30,
                )
            except subprocess.SubprocessError:
                return True  # fail open: assume it's a consumer
            for hit in cp.stdout.splitlines():
                rel = Path(hit).relative_to(self.root) if Path(hit).is_absolute() else Path(hit)
                if str(rel) == self_path:
                    continue
                return True
        return False

    # ---- schema heterogeneity ----------------------------------------

    @staticmethod
    def find_schema_heterogeneity(files: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Group files by directory; warn when sibling files have different headers."""
        by_dir: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for desc in files:
            if not desc.get("schema_fingerprint"):
                continue
            d = str(Path(desc["path"]).parent)
            by_dir[d].append(desc)
        warnings = []
        for d, files_in_d in by_dir.items():
            fingerprints = {f["schema_fingerprint"] for f in files_in_d}
            if len(fingerprints) > 1:
                warnings.append({
                    "directory": d,
                    "file_count": len(files_in_d),
                    "distinct_schemas": len(fingerprints),
                    "schemas": sorted(fingerprints),
                    "files_by_schema": {
                        fp: [f["name"] for f in files_in_d if f["schema_fingerprint"] == fp]
                        for fp in fingerprints
                    },
                })
        return warnings

    # ---- top-level run ------------------------------------------------

    def run(self, only: Optional[str] = None) -> Dict[str, Any]:
        transforms = self.scan_all_transforms(only=only)
        all_files = []
        for t in transforms:
            all_files.extend(t["mapping_files"])
        # Add canonical hub files (only when not narrowed to a single transform).
        if not only:
            root_files = self.scan_root_mappings()
        else:
            root_files = []
        all_files = all_files + root_files
        return {
            "report_date": datetime.now().strftime("%Y-%m-%d"),
            "transforms": transforms,
            "root_mapping_files": root_files,
            "dead_files": self.find_dead_files(all_files),
            "schema_heterogeneity": self.find_schema_heterogeneity(all_files),
            "summary": {
                "transforms_scanned": len(transforms),
                "transforms_with_findings": sum(
                    1 for t in transforms
                    if t["inline_curies"] or t["local_dicts"] or t["repeated_callsites"]
                ),
                "total_mapping_files": len(all_files),
                "total_mapping_entries": sum(f["entry_count"] for f in all_files),
                "inline_curie_count": sum(len(t["inline_curies"]) for t in transforms),
                "repeated_callsite_count": sum(len(t["repeated_callsites"]) for t in transforms),
                "dead_file_count": 0,  # set below
                "schema_heterogeneity_count": 0,  # set below
            },
        }


def format_text(results: Dict[str, Any], verbose: bool = False) -> str:
    s = results["summary"]
    s["dead_file_count"] = len(results["dead_files"])
    s["schema_heterogeneity_count"] = len(results["schema_heterogeneity"])

    out = []
    out.append("=" * 64)
    out.append("=== KG-Microbe Mapping Audit (v2) ===")
    out.append("=" * 64)
    out.append(f"Date: {results['report_date']}\n")

    for t in results["transforms"]:
        flags = []
        if t["inline_curies"]:
            flags.append(f"{len(t['inline_curies'])} inline CURIEs")
        if t["local_dicts"]:
            flags.append(f"{len(t['local_dicts'])} dict(s)")
        if t["repeated_callsites"]:
            flags.append(f"{len(t['repeated_callsites'])} repeated-callsite cluster(s)")
        if not flags and not t["mapping_files"]:
            continue
        out.append(f"Transform: {t['name']}")
        if flags:
            out.append("  ⚠ findings: " + ", ".join(flags))
        if t["repeated_callsites"]:
            for r in t["repeated_callsites"]:
                out.append(
                    f"    [repeated-callsite] {r['file']} {r['callee']}() invoked "
                    f"{r['call_count']}x with {len(r['distinct_curies'])} distinct CURIEs "
                    f"on lines {','.join(map(str, r['lines'][:6]))}{'…' if len(r['lines']) > 6 else ''}"
                )
                if verbose:
                    out.append(f"      curies: {', '.join(r['distinct_curies'][:6])}{'…' if len(r['distinct_curies']) > 6 else ''}")
        if t["local_dicts"]:
            for d in t["local_dicts"]:
                line_range = (
                    f"{d['line_start']}-{d['line_end']}" if d['line_end'] > d['line_start']
                    else str(d['line_start'])
                )
                out.append(f"    [dict] {d['file']}:{line_range} {d['variable']} ({d['entry_count']} CURIE values)")
        if verbose and t["inline_curies"]:
            out.append(f"    [inline-curies] {len(t['inline_curies'])} occurrences (verbose):")
            for inl in t["inline_curies"][:10]:
                out.append(f"      {inl['file']}:{inl['line']}  {inl['curie']}")
            if len(t["inline_curies"]) > 10:
                out.append(f"      … and {len(t['inline_curies']) - 10} more")
        if t["mapping_files"]:
            out.append(f"  📁 {len(t['mapping_files'])} mapping file(s):")
            for f in t["mapping_files"]:
                out.append(f"    - {f['path']} ({f['entry_count']} entries)")
        out.append("")

    out.append("-" * 64)
    out.append("Repo-root canonical curation hub (mappings/):")
    if results["root_mapping_files"]:
        for f in results["root_mapping_files"]:
            out.append(f"  - {f['path']:<60s} {f['entry_count']:>8} entries")
    else:
        out.append("  (none -- narrow audit; rerun without --transform to inventory)")
    out.append("")

    if results["schema_heterogeneity"]:
        out.append("-" * 64)
        out.append("⚠ Schema heterogeneity within sibling curation files:")
        for h in results["schema_heterogeneity"]:
            out.append(f"  {h['directory']}: {h['distinct_schemas']} distinct headers across {h['file_count']} file(s)")
            for fp, names in h["files_by_schema"].items():
                out.append(f"    schema #{abs(hash(fp)) % 1000:03d}: {', '.join(names)}")
                if verbose:
                    out.append(f"      header: {fp[:120]}{'…' if len(fp) > 120 else ''}")
        out.append("")

    if results["dead_files"]:
        out.append("-" * 64)
        out.append("⚠ Dead files (zero textual references in codebase):")
        for f in results["dead_files"]:
            out.append(f"  - {f['path']} ({f['entry_count']} entries) -- {f['reason']}")
        out.append("")

    out.append("-" * 64)
    out.append("Summary:")
    out.append(f"  Transforms scanned:              {s['transforms_scanned']}")
    out.append(f"  Transforms with code findings:   {s['transforms_with_findings']}")
    out.append(f"  Inline CURIE literals:           {s['inline_curie_count']}")
    out.append(f"  Repeated-callsite clusters:      {s['repeated_callsite_count']}")
    out.append(f"  Total mapping files:             {s['total_mapping_files']}")
    out.append(f"  Total mapping entries:           {s['total_mapping_entries']:,}")
    out.append(f"  Schema heterogeneity warnings:   {s['schema_heterogeneity_count']}")
    out.append(f"  Dead files:                      {s['dead_file_count']}")
    out.append("=" * 64)
    return "\n".join(out)


def format_markdown(results: Dict[str, Any], verbose: bool = False) -> str:
    return "```text\n" + format_text(results, verbose=verbose) + "\n```\n"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    p.add_argument("--transform", help="audit a specific transform name (default: all)")
    p.add_argument("--format", choices=["text", "json", "md"], default="text")
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    auditor = MappingAuditor(Path.cwd())
    results = auditor.run(only=args.transform)

    if args.format == "json":
        # Tally summary fields the formatters fill in side-effectfully.
        results["summary"]["dead_file_count"] = len(results["dead_files"])
        results["summary"]["schema_heterogeneity_count"] = len(results["schema_heterogeneity"])
        print(json.dumps(results, indent=2, default=str))
    elif args.format == "md":
        print(format_markdown(results, verbose=args.verbose))
    else:
        print(format_text(results, verbose=args.verbose))
    return 0


if __name__ == "__main__":
    sys.exit(main())
