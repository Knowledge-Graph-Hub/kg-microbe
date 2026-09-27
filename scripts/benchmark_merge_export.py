"""Repeatable bounded #1189 benchmark; not a production timing or scientific approval."""

import argparse
import csv
import hashlib
import json
import os
import resource
import socket
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path


def sha256(path):
    """Fingerprint bounded fixture/code files without reading any production inputs."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def child(args):
    """Measure one real public export in a fresh interpreter with deterministic inputs."""
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    os.environ["KG_MICROBE_BIOLINK_MODEL"] = str(root / "tests/resources/biolink-model-minimal.yaml")
    os.environ["KG_MICROBE_BIOLINK_PREDICATE_MAP"] = str(root / "tests/resources/predicate_mapping_minimal.yaml")

    def no_network(*unused, **kwargs):
        """Forbid network access, including unexpected adapter defaults."""
        raise RuntimeError("network is forbidden in the bounded export benchmark")

    socket.socket.connect = no_network
    socket.getaddrinfo = no_network
    from multiprocessing.pool import ThreadPool

    import yaml

    from kg_microbe.utils.biolink_model import prepare_kgx

    prepare_kgx()
    from kgx.cli import cli_utils

    from kg_microbe.merge_utils import kgx_source, merge_kg

    cli_utils.Pool = ThreadPool
    if args.mode == "baseline":
        kgx_source._eligible_merge_configuration = lambda *unused: False
    measures = []
    direct_calls = []
    real_transform = kgx_source.ProvenancePreservingTransformer.transform
    real_direct = kgx_source.ProvenancePreservingTransformer._export_completed_graph

    def counted_direct(self, *positional, **keywords):
        """Ensure a purported fast-path measurement actually exercises that path."""
        direct_calls.append(True)
        return real_direct(self, *positional, **keywords)

    def timed_export(self, input_args, *positional, **keywords):
        """Time the actual destination call; do not include ingestion in this interval."""
        if input_args.get("format") != "graph":
            return real_transform(self, input_args, *positional, **keywords)
        started = time.monotonic()
        result = real_transform(self, input_args, *positional, **keywords)
        measures.append(time.monotonic() - started)
        return result

    kgx_source.ProvenancePreservingTransformer.transform = timed_export
    kgx_source.ProvenancePreservingTransformer._export_completed_graph = counted_direct
    with tempfile.TemporaryDirectory(prefix="export-", dir=args.output) as temporary:
        workspace = Path(temporary)
        fixtures = root / "tests/resources/merge_direct_export"
        nodes = workspace / "nodes.tsv"
        nodes.write_bytes((fixtures / "alpha_nodes.tsv").read_bytes())
        edges = workspace / "edges.tsv"
        with (fixtures / "alpha_edges.tsv").open(newline="") as stream:
            reader = csv.DictReader(stream, delimiter="\t", quoting=csv.QUOTE_NONE)
            header = [*reader.fieldnames, "source_assertion_id"]
            template = next(reader)
        with edges.open("w", newline="") as stream:
            writer = csv.DictWriter(
                stream, fieldnames=header, delimiter="\t", quoting=csv.QUOTE_NONE, quotechar=None, lineterminator="\n"
            )
            writer.writeheader()
            for index in range(args.edges):
                row = {**template, "source_assertion_id": f"fixture:{index}"}
                writer.writerow(row)
                if index % 7 == 0:
                    writer.writerow(row)
        config = workspace / "merge.yaml"
        config.write_text(
            yaml.safe_dump(
                {
                    "configuration": {"output_directory": str(workspace / "out"), "allow_unfinalized_sources": True},
                    "merged_graph": {
                        "source": {"fixture": {"input": {"format": "tsv", "filename": [str(nodes), str(edges)]}}},
                        "destination": {"release": {"format": "tsv", "filename": "result", "compression": "tar.gz"}},
                    },
                }
            )
        )
        started = time.monotonic()
        graph = merge_kg.load_and_merge(str(config))
        elapsed = time.monotonic() - started
        with tarfile.open(workspace / "out/result.tar.gz") as archive:
            members = {}
            for name in archive.getnames():
                if name == "manifest.json":
                    continue
                digest = hashlib.sha256()
                with archive.extractfile(name) as stream:
                    for block in iter(lambda: stream.read(1024 * 1024), b""):
                        digest.update(block)
                members[name] = digest.hexdigest()
        if len(measures) != 1 or graph.number_of_edges() != args.edges or len(direct_calls) != (args.mode == "direct"):
            raise RuntimeError("Unexpected export count or observation loss in benchmark")
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        if sys.platform != "darwin":
            peak *= 1024
        result = {
            "mode": args.mode,
            "public_seconds": elapsed,
            "export_seconds": measures[0],
            "direct_export_calls": len(direct_calls),
            "process_peak_rss_bytes": peak,
            "nodes": graph.number_of_nodes(),
            "edges": graph.number_of_edges(),
            "input_sha256": {"nodes": sha256(nodes), "edges": sha256(edges)},
            "member_sha256": members,
            "kgx_version": kgx_source.version("kgx"),
            "python": sys.version,
            "executable": sys.executable,
        }
        with (args.output / f"{args.mode}-{args.index}.json").open("x") as stream:
            json.dump(result, stream, sort_keys=True, indent=2)
            stream.write("\n")


def main():
    """Run alternating isolated children; compare complete payload hashes, never timing thresholds."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="New exclusive evidence directory")
    parser.add_argument("--edges", type=int, default=20_000, help="Unique synthetic observations, maximum 200000")
    parser.add_argument("--repeats", type=int, default=3, help="Paired repeats, maximum 10")
    parser.add_argument("--mode", choices=("baseline", "direct"), help=argparse.SUPPRESS)
    parser.add_argument("--index", type=int, default=0, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not 1 <= args.edges <= 200_000 or not 1 <= args.repeats <= 10:
        parser.error("bounded benchmark requires 1..200000 edges and 1..10 repeats")
    if args.mode:
        child(args)
        return
    args.output = args.output.resolve()
    args.output.mkdir(parents=False, exist_ok=False)
    root = Path(__file__).resolve().parents[1]
    bound_paths = [
        Path(__file__),
        Path(sys.executable),
        *sorted((root / "kg_microbe").rglob("*.py")),
        *sorted((root / "tests/resources/merge_direct_export").glob("*")),
        root / "tests/resources/biolink-model-minimal.yaml",
        root / "tests/resources/predicate_mapping_minimal.yaml",
    ]
    before = {str(path): sha256(path) for path in bound_paths}
    runs = []
    for index in range(args.repeats):
        modes = ("baseline", "direct") if index % 2 == 0 else ("direct", "baseline")
        for mode in modes:
            command = [
                sys.executable,
                str(Path(__file__).resolve()),
                "--output",
                str(args.output),
                "--edges",
                str(args.edges),
                "--mode",
                mode,
                "--index",
                str(index),
            ]
            environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONPATH=str(root))
            for variable in ("PYTHONOPTIMIZE", "PYTHONHOME"):
                environment.pop(variable, None)
            with (args.output / f"{mode}-{index}.log").open("x") as stream:
                # The argv is this exact script/interpreter plus bounded parser-validated numbers and paths.
                subprocess.run(command, check=True, cwd=root, env=environment, stdout=stream, stderr=subprocess.STDOUT)  # noqa: S603
            runs.append(json.loads((args.output / f"{mode}-{index}.json").read_text()))
    after = {str(path): sha256(path) for path in bound_paths}
    if before != after:
        raise RuntimeError("Benchmark implementation/fixture/interpreter drift")
    reference = runs[0]
    for run in runs:
        if any(
            run[key] != reference[key] for key in ("input_sha256", "member_sha256", "nodes", "edges", "kgx_version")
        ):
            raise RuntimeError("Full payload or input identity mismatch; no speed comparison is admissible")
    report = {
        "scope": "Synthetic diagnostic-opt-out public exports; no production or freshness approval",
        "status": "EQUIVALENT_MEASURED",
        "inputs_unchanged": True,
        "input_sha256": before,
        "runs": runs,
        "limits": (
            "Peak RSS includes imports and ingestion; export timing is isolated. Concurrent host load is uncontrolled."
        ),
    }
    with (args.output / "report.json").open("x") as stream:
        json.dump(report, stream, sort_keys=True, indent=2)
        stream.write("\n")
    print(json.dumps({key: report[key] for key in ("status", "inputs_unchanged", "limits")}))


if __name__ == "__main__":
    main()
