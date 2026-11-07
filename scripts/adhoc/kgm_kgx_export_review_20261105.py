"""
Compare installed KGX source APIs for the 2026-11-05 direct-export upgrade review.

Inputs: preserved KGX2.7 package and isolated KGX2.8 package directories.
Outputs: exclusive per-file source diffs, full-byte identities, and AST method deltas.
This read-only comparison never enables a version or substitutes for export tests.
"""

import argparse
import ast
import difflib
import hashlib
import json
from pathlib import Path

FILES = (
    "transformer.py",
    "source/source.py",
    "source/graph_source.py",
    "source/tsv_source.py",
    "sink/sink.py",
    "sink/graph_sink.py",
    "sink/tsv_sink.py",
    "graph/base_graph.py",
    "graph/nx_graph.py",
    "cli/cli_utils.py",
    "config.py",
)


def methods(tree, prefix=""):
    """Index complete function signatures/bodies and class method definitions."""
    result = {}
    for item in tree.body:
        if isinstance(item, ast.ClassDef):
            result.update(methods(item, prefix + item.name + "."))
        elif isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            result[prefix + item.name] = ast.dump(item, include_attributes=False)
    return result


def main():
    """Write source comparisons with exact package identities and no code import."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--old-package", required=True, type=Path)
    parser.add_argument("--new-package", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    report = {
        "old_package": str(args.old_package),
        "new_package": str(args.new_package),
        "files": {},
        "enables_direct_export": False,
        "equivalence_tests_required": True,
    }
    for name in FILES:
        old, new = (args.old_package / name).read_text(), (args.new_package / name).read_text()
        a, b = methods(ast.parse(old)), methods(ast.parse(new))
        target = args.output / (name.replace("/", "__") + ".diff")
        target.write_text(
            "".join(
                difflib.unified_diff(
                    old.splitlines(True), new.splitlines(True), fromfile="kgx-2.7/" + name, tofile="kgx-2.8/" + name
                )
            )
        )
        report["files"][name] = {
            "old_sha256": hashlib.sha256(old.encode()).hexdigest(),
            "new_sha256": hashlib.sha256(new.encode()).hexdigest(),
            "changed_methods": sorted(key for key in a.keys() | b.keys() if a.get(key) != b.get(key)),
            "diff": str(target),
        }
    with (args.output / "source-comparison.json").open("x") as stream:
        json.dump(report, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps({name: data["changed_methods"] for name, data in report["files"].items()}, indent=2))


if __name__ == "__main__":
    main()
