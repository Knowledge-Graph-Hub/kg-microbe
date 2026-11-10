"""Opt-in native-validated stable MIM candidate, without production activation."""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
from collections import Counter
from copy import deepcopy
from pathlib import Path

from kg_microbe.edge_snapshot import _regular_open, _signature
from kg_microbe.utils.ingredient_bundle_contract import canonical_json, read_json

CONTRACT = "kg-microbe-stable-source-candidate/v1"
STATUS = "PRIVATE_NOT_KG_ACCEPTED"
ONTOLOGY_PREFIXES = frozenset({"BTO", "CHEBI", "ENVO", "FOODON", "MICRO", "NCIT", "UBERON", "mesh"})
PRODUCER_AUXILIARY = (
    "scripts/record_review.py",
    "schema/record_review.yaml",
    "pyproject.toml",
    "uv.lock",
    ".python-version",
)
HOLD_POLICY_SHA256 = "ed136aca89d76107a456ddc11f3da49ce31bec8a474abdcab71c8cda9b6a9ddf"


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _require(value, message):
    if not value:
        raise ValueError("Stable MIM candidate: " + message)


def _keys(value, expected):
    _require(isinstance(value, dict) and set(value) == set(expected), "unexpected selection fields")


def _path(root, name):
    path = Path(name)
    _require(
        isinstance(name, str)
        and name
        and not path.is_absolute()
        and path.as_posix() == name
        and ".." not in path.parts
        and "\\" not in name,
        "unsafe relative path",
    )
    result = root / path
    _require(not any(p.is_symlink() for p in (result, *result.parents)), "aliased input")
    return result


def _root(value):
    path = Path(value)
    _require(path.is_absolute() and path == path.resolve(strict=True), "explicit unaliased absolute root required")
    _require(not any(p.is_symlink() for p in (path, *path.parents)), "aliased root")
    _require(path.is_dir(), "missing input root")
    return path


def _head(root):
    return (
        subprocess.check_output(["git", "--no-optional-locks", "rev-parse", "HEAD"], cwd=root, timeout=30)  # noqa: S607
        .decode()
        .strip()
    )


def producer_members(root):
    """Enumerate the complete selected native package and its maintained auxiliaries."""
    root = _root(str(root))
    members = set(PRODUCER_AUXILIARY)
    for path in (root / "src/mediaingredientmech").rglob("*"):
        if "__pycache__" not in path.parts and path.suffix not in {".pyc", ".pyo"} and path.is_file():
            members.add(path.relative_to(root).as_posix())
    _require(any(name.endswith("/export/source_producer.py") for name in members), "missing native producer")
    return sorted(members)


class _Snapshots:
    """Retain exact read bytes and file identity using the existing snapshot primitive."""

    def __init__(self):
        self.files = {}
        self.identities = {}
        self.directories = {}

    def add(self, path, digest=None):
        path = Path(path).absolute()
        _require(not any(p.is_symlink() for p in (path, *path.parents)), "aliased input")
        with _regular_open(path) as stream:
            identity = _signature(os.fstat(stream.fileno()))
            raw = stream.read()
            _require(identity == _signature(os.fstat(stream.fileno())), "input changed during read")
        _require(identity == _signature(path.lstat()), "input replaced during read")
        actual = _sha(raw)
        if digest is not None:
            _require(isinstance(digest, str) and re.fullmatch("[a-f0-9]{64}", digest), "invalid pin")
            _require(actual == digest, "input pin differs: " + str(path))
        previous = self.files.get(path)
        _require(previous is None or previous == (raw, identity), "input changed between reads")
        alias = self.identities.get(identity[:2])
        _require(alias is None or alias == path, "physical input alias")
        self.identities[identity[:2]] = path
        self.files[path] = raw, identity
        return raw

    def directory(self, root, names):
        root = _root(str(root))
        expected = sorted(names)
        actual = []
        for path in root.rglob("*"):
            _require(not path.is_symlink(), "aliased product member")
            if path.is_file():
                actual.append(path.relative_to(root).as_posix())
        _require(sorted(actual) == expected, "complete product inventory differs")
        self.directories[root] = expected

    def verify(self):
        for path, (raw, identity) in list(self.files.items()):
            _require(self.add(path) == raw and self.files[path][1] == identity, "snapshot drift")
        for root, names in list(self.directories.items()):
            self.directory(root, names)


class StableSourceCandidate:
    """
    Validate actual current MIM products in their pinned native Python runtime.

    Selection hashes choose inputs; the child replays native source and companion
    validators. No result boolean, cached payload or companion identity claim can
    substitute for source-scoped scientific admission.
    """

    def __init__(self, selection_path: Path, *, selection_sha256: str):
        """Consume one explicit candidate selection and preserve all original lanes."""
        self._snapshots = _Snapshots()
        self.selection_path = Path(selection_path).absolute()
        raw = self._snapshots.add(self.selection_path, selection_sha256)
        self._selection = read_json(raw)
        self.fingerprint = selection_sha256
        selection = self.selection
        _keys(
            selection,
            {
                "contract",
                "mode",
                "mim_root",
                "mim_revision",
                "producer_root",
                "producer_revision",
                "producer_files",
                "python",
                "source_review",
                "source_output",
                "companion_review",
                "companion_output",
                "companion_mode",
                "profile_sha256",
                "lineage",
            },
        )
        _require(
            selection["contract"] == CONTRACT and selection["mode"] == "candidate_only",
            "candidate-only selection required",
        )
        self.root = _root(selection["mim_root"])
        from kg_microbe.utils.stable_ingredient_kgx import stable_ingredient_kgx_profile

        profile_path = Path(__file__).absolute().parents[1] / "profiles/stable_source_kgx_v1.yaml"
        self._snapshots.add(profile_path, selection["profile_sha256"])
        stable_ingredient_kgx_profile()
        self.producer = _root(selection["producer_root"])
        _require(
            self.root != self.producer or selection["mim_revision"] == selection["producer_revision"],
            "one root has conflicting revision pins",
        )
        self._heads = {self.root: selection["mim_revision"], self.producer: selection["producer_revision"]}
        for root, expected in self._heads.items():
            _require(
                re.fullmatch("[a-f0-9]{40}", expected) and _head(root) == expected, "selected Git revision differs"
            )
        files = selection["producer_files"]
        _require(
            isinstance(files, dict) and sorted(files) == producer_members(self.producer),
            "native producer closure differs",
        )
        for name, digest in files.items():
            self._snapshots.add(_path(self.producer, name), digest)
        runtime = selection["python"]
        _keys(runtime, {"path", "realpath", "sha256", "runtime"})
        executable = Path(runtime["path"])
        _require(
            executable.is_absolute() and str(executable.resolve(strict=True)) == runtime["realpath"],
            "runtime executable differs",
        )
        self._snapshots.add(Path(runtime["realpath"]), runtime["sha256"])
        mode = selection["companion_mode"]
        _require(mode in {"required/v1", "absent/v1"}, "explicit versioned companion mode required")
        if mode == "absent/v1":
            _require(
                selection["companion_review"] is None and selection["companion_output"] is None,
                "absent companion mode forbids supplied companion declarations",
            )
        review_keys = ("source_review", "companion_review") if mode == "required/v1" else ("source_review",)
        for key in review_keys:
            _keys(selection[key], {"path", "sha256"})
            self._snapshots.add(_path(self.root, selection[key]["path"]), selection[key]["sha256"])
        self.source_output, source_manifest = self._product("source_output", "files")
        self.companion_output = None
        if mode == "required/v1":
            self.companion_output, companion_manifest = self._product("companion_output", "members")
        for name, digest in source_manifest["inputs"].items():
            self._snapshots.add(_path(self.root, name), digest)
        source_review = read_json(self._snapshots.files[_path(self.root, selection["source_review"]["path"])][0])
        self._owner_members = sorted(source_review["record_inputs"])
        self._owner_directories = {}
        for category in ("mapped", "unmapped"):
            directory = _root(str(self.root / "data/ingredients" / category))
            self._owner_directories[directory] = (directory.stat().st_dev, directory.stat().st_ino)
        if mode == "required/v1":
            for name, declaration in companion_manifest["members"].items():
                if name.startswith("sources/"):
                    self._snapshots.add(_path(self.root, name[len("sources/") :]), declaration["sha256"])
        lineage = selection["lineage"]
        if lineage is not None:
            _keys(lineage, {"manifest", "postimages"})
            for declaration in lineage.values():
                _keys(declaration, {"path", "sha256"})
                self._snapshots.add(_path(self.root, declaration["path"]), declaration["sha256"])
        self._policy_path = Path(__file__).resolve().parents[2] / "mappings/mim_downstream_holds.json"
        # __file__ is kg_microbe/utils/...; repository root is parents[2].
        policy = read_json(self._snapshots.add(self._policy_path, HOLD_POLICY_SHA256))
        for name, field in (
            ("mappings/ingredient_identity_exclusions.tsv", "identity_policy_sha256"),
            ("tests/resources/mediadive/p3556_scope.json", "fixture_sha256"),
            ("docs/reviews/mediadive-p3556-scope-1241.md", "review_document_sha256"),
        ):
            self._snapshots.add(_path(self._policy_path.parent.parent, name), policy[field])
        bridge = Path(__file__).with_name("stable_source_native_bridge.py").absolute()
        bridge_bytes = self._snapshots.add(bridge)
        self.verify_current()
        completed = subprocess.run(  # noqa: S603 - explicitly selected, byte-pinned interpreter; no shell
            [str(executable), "-I", "-B", str(bridge)],
            input=canonical_json(
                {
                    "selection": selection,
                    "selection_sha256": self.fingerprint,
                    "profile_sha256": selection["profile_sha256"],
                    "hold_policy": policy,
                }
            ),
            capture_output=True,
            cwd=self.producer,
            env={
                "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                "GIT_OPTIONAL_LOCKS": "0",
                "PYTHONDONTWRITEBYTECODE": "1",
            },
            check=False,
        )
        self._native_execution = {
            "argv": [str(executable), "-I", "-B", str(bridge)],
            "exit_status": completed.returncode,
            "stdout": completed.stdout.decode("utf-8", errors="replace"),
            "stderr": completed.stderr.decode("utf-8", errors="replace"),
            "bridge_sha256": _sha(bridge_bytes),
        }
        self.verify_current()
        _require(completed.returncode == 0, "native validation failed: " + self.native_execution["stderr"])
        self._payload = read_json(completed.stdout)
        _require(
            self._payload["companion_mode"] == selection["companion_mode"]
            and self._payload["profile_sha256"] == selection["profile_sha256"]
            and self._payload["selection_sha256"] == self.fingerprint,
            "native candidate selection/profile/mode differs",
        )
        _require(self._payload["runtime"] == runtime["runtime"], "native runtime package versions differ")
        _require(
            self._payload["status"] == STATUS and self._payload["production_authorized"] is False,
            "invalid native candidate status",
        )
        self.verify_current()

    @property
    def selection(self):
        """Return an isolated copy of the immutable selected input declarations."""
        return deepcopy(self._selection)

    @property
    def native_execution(self):
        """Return the actual captured command result without exposing mutable state."""
        return deepcopy(self._native_execution)

    def _product(self, key, members):
        declaration = self.selection[key]
        _keys(declaration, {"path", "manifest_sha256"})
        root = _path(self.root, declaration["path"])
        manifest = read_json(self._snapshots.add(root / "manifest.json", declaration["manifest_sha256"]))
        names = {"manifest.json", *manifest[members]}
        self._snapshots.directory(root, names)
        for name, pin in manifest[members].items():
            self._snapshots.add(_path(root, name), pin if members == "files" else pin["sha256"])
        return root, manifest

    def verify_current(self):
        """Keep all input, selected-code, runtime and Git bindings live through use."""
        self._snapshots.verify()
        owners = []
        for directory, identity in self._owner_directories.items():
            _root(str(directory))
            current = directory.stat()
            _require((current.st_dev, current.st_ino) == identity, "owner directory identity changed")
            for path in directory.glob("*.yaml"):
                _require(not path.is_symlink(), "aliased owner member")
                owners.append(path.relative_to(self.root).as_posix())
        _require(sorted(owners) == self._owner_members, "complete owner inventory changed")
        for root, expected in self._heads.items():
            _require(_head(root) == expected, "selected Git HEAD changed")
        runtime = self.selection["python"]
        _require(str(Path(runtime["path"]).resolve(strict=True)) == runtime["realpath"], "runtime locator changed")
        _require(
            producer_members(self.producer) == sorted(self.selection["producer_files"]),
            "native producer membership changed",
        )

    def payload(self):
        """Return isolated full assertions, including all withheld rows and provenance."""
        self.verify_current()
        return deepcopy(self._payload)

    def resolve_source(self, source_id, *, occurrence_position=None):
        """Resolve only a native-supported source; never fall back to names or targets."""
        self.verify_current()
        cases = [case for case in self._payload["source_decisions"] if case["payload"]["source_id"] == source_id]
        if not cases:
            return None
        _require(len(cases) == 1, "source identity is not unique")
        case = cases[0]
        if occurrence_position is not None:
            _require(
                any(item["position"] == occurrence_position for item in case["payload"]["occurrences"]),
                "source occurrence context differs",
            )
        if case["disposition"] != "SUPPORTED":
            return None
        return case["binding"]["object_id"].replace("MIM:", "MIM.ingredient:", 1)

    def legacy_identifier_owners(self, identifier):
        """Return every explicit historical alias owner without choosing an identity."""
        self.verify_current()
        return sorted(
            owner
            for owner, value in self._payload["owners"].items()
            if identifier in value["record"].get("legacy_identifiers", [])
        )

    def graph_rows(self):
        """Project independent assertions without ontology replacement or subclass edges."""
        from kg_microbe.utils.stable_ingredient_kgx import project_stable_candidate

        return project_stable_candidate(
            self.payload(), manifest_sha256=self.selection["source_output"]["manifest_sha256"]
        )

    def audit(self):
        """Separate native mapping coverage from conservative consumer admission limits."""
        payload = self.payload()
        owners = {claim["original_object_id"] for claim in payload["claims"]}
        held = set(payload["consumer_admission"]["held_owners"])

        def counts(rows):
            result = {"exact_external": 0, "stable_mim_plus_inexact": 0, "stable_mim_only": 0}
            for owner in owners:
                predicates = {
                    row["predicate_id"]
                    for row in rows
                    if row["subject_id"] == owner and row["object_id"].partition(":")[0] in ONTOLOGY_PREFIXES
                }
                key = (
                    "exact_external"
                    if "skos:exactMatch" in predicates
                    else "stable_mim_plus_inexact"
                    if predicates
                    else "stable_mim_only"
                )
                result[key] += 1
            return result

        return {
            "status": STATUS,
            "production_authorized": False,
            "selection_sha256": self.fingerprint,
            "source_counts": payload["provenance"]["source_manifest"]["counts"],
            "native_bound_owner_counts": counts(payload["external_supported"]),
            "consumer_bound_owner_counts": counts(
                [row for row in payload["external_supported"] if row["subject_id"] not in held]
            ),
            "ontology_prefixes": sorted(ONTOLOGY_PREFIXES),
            "external_supported_rows": len(payload["external_supported"]),
            "external_withheld_rows": len(payload["external_withheld"]),
            "consumer_admission": payload["consumer_admission"],
            "lineage_status": payload["lineage"]["status"],
            "lineage_limitation": payload["lineage"]["limitation"],
            "companion_mode": payload["companion_mode"],
            "companion_counts": (
                {key: len(rows) for key, rows in payload["companion"].items()}
                if payload["companion"] is not None
                else None
            ),
        }

    def bind_to_transform(self, transform):
        """Register actual validated bytes with native candidate finalization."""
        try:
            self.verify_current()
            for number, (path, (raw, _)) in enumerate(sorted(self._snapshots.files.items())):
                key = f"stable_mim_candidate/{self.fingerprint}/{number:06d}"
                value = {"path": str(path), "sha256": _sha(raw)}
                previous = transform._consumed_input_snapshots.get(key)
                _require(previous is None or previous == value, "candidate changed within transform")
                transform._consumed_input_snapshots[key] = value
        except (OSError, ValueError) as error:
            transform._consumed_input_error = str(error)
            raise

    def verify_graph_rows(self, nodes, edges):
        """Reject mixed profiles, dropped assertions or remapped archive endpoints."""
        from kg_microbe.utils.stable_ingredient_kgx import (
            ASSERTION_JSON,
            STABLE_PROFILE,
            validate_stable_ingredient_fields,
        )

        self.verify_current()
        expected_nodes, expected_edges = self.graph_rows()
        pin = self.selection["source_output"]["manifest_sha256"]
        for rows, is_node in ((nodes, True), (edges, False)):
            for row in rows:
                _require(row.get("ingredient_profile") == STABLE_PROFILE, "mixed graph ingredient profile")
                _require(row.get("ingredient_bundle_sha256") == pin, "graph candidate fingerprint differs")
                validate_stable_ingredient_fields(row, is_node=is_node)
        node_keys = ("id", "ingredient_record_kind")
        edge_keys = ("subject", "predicate", "object", "relation", ASSERTION_JSON)
        for actual, expected, keys in ((nodes, expected_nodes, node_keys), (edges, expected_edges, edge_keys)):
            _require(
                Counter(tuple(row.get(key, "") for key in keys) for row in actual)
                == Counter(tuple(row.get(key, "") for key in keys) for row in expected),
                "graph rows differ from complete native candidate assertions",
            )
        self.verify_current()

    def export_candidate(self, output):
        """Persist complete native products and original assertions into a fresh directory."""
        output = Path(output).absolute()
        _require(not any(p.is_symlink() for p in (output, *output.parents)), "aliased output")
        _require(not output.exists(), "candidate output must be new")
        _require(output == output.resolve(strict=False), "aliased output path")
        output_parts = tuple(part.casefold() for part in output.parts)
        for directory in self._snapshots.directories:
            protected = tuple(part.casefold() for part in directory.parts)
            _require(
                output_parts[: len(protected)] != protected and protected[: len(output_parts)] != output_parts,
                "output overlaps a native product directory",
            )
        _require(not any(output == p or output in p.parents for p in self._snapshots.files), "output overlaps an input")
        self.verify_current()
        # Filesystems may equate spellings that resolve()/casefold() preserve
        # (for example composed/decomposed Unicode on macOS; #1829).
        protected_identities = set()
        for directory in self._snapshots.directories:
            identity = directory.stat()
            protected_identities.add((identity.st_dev, identity.st_ino))
        for ancestor in output.parents:
            if ancestor.exists():
                identity = ancestor.stat()
                _require(
                    (identity.st_dev, identity.st_ino) not in protected_identities,
                    "output physically overlaps a native product directory",
                )
        output.mkdir(parents=True)
        try:
            written = _Snapshots()
            products = {
                "selection.json": self._snapshots.files[self.selection_path][0],
                "assertions.json": canonical_json(self._payload) + b"\n",
                "native-execution.json": canonical_json(self.native_execution) + b"\n",
            }
            for prefix, root in (("native-source", self.source_output), ("native-companion", self.companion_output)):
                if root is None:
                    continue
                for name in self._snapshots.directories[root]:
                    products[prefix + "/" + name] = self._snapshots.files[root / name][0]
            products["input-receipt.json"] = (
                canonical_json({str(path): _sha(raw) for path, (raw, _) in self._snapshots.files.items()}) + b"\n"
            )
            for name, raw in products.items():
                path = _path(output, name)
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("xb") as stream:
                    stream.write(raw)
                written.add(path, _sha(raw))
            self.verify_current()
            manifest = {
                "contract": CONTRACT,
                "status": STATUS,
                "production_authorized": False,
                "selection_sha256": self.fingerprint,
                "companion_mode": self.selection["companion_mode"],
                "source_manifest_sha256": self.selection["source_output"]["manifest_sha256"],
                "profile_sha256": self.selection["profile_sha256"],
                "files": {name: _sha(raw) for name, raw in products.items()},
            }
            manifest_raw = canonical_json(manifest) + b"\n"
            with (output / "manifest.json").open("xb") as stream:
                stream.write(manifest_raw)
            written.add(output / "manifest.json", _sha(manifest_raw))
            written.directory(output, {"manifest.json", *products})
            self.verify_current()
            written.verify()
            return _sha(manifest_raw)
        except BaseException as error:
            with (output / "FAILED.json").open("xb") as stream:
                stream.write(canonical_json({"status": "FAILED_CANDIDATE", "error": str(error)}))
            raise

    @classmethod
    def reload(cls, directory, *, manifest_sha256):
        """Revalidate actual native origins and exact persisted candidate bytes on reload."""
        directory = _root(str(Path(directory).absolute()))
        snapshots = _Snapshots()
        manifest = read_json(snapshots.add(directory / "manifest.json", manifest_sha256))
        _keys(
            manifest,
            {
                "contract",
                "status",
                "production_authorized",
                "selection_sha256",
                "companion_mode",
                "source_manifest_sha256",
                "profile_sha256",
                "files",
            },
        )
        _require(
            manifest["contract"] == CONTRACT
            and manifest["status"] == STATUS
            and manifest["production_authorized"] is False,
            "invalid candidate archive",
        )
        snapshots.directory(directory, {"manifest.json", *manifest["files"]})
        for name, pin in manifest["files"].items():
            snapshots.add(_path(directory, name), pin)
        candidate = cls(directory / "selection.json", selection_sha256=manifest["selection_sha256"])
        _require(
            manifest["companion_mode"] == candidate.selection["companion_mode"]
            and manifest["profile_sha256"] == candidate.selection["profile_sha256"]
            and manifest["source_manifest_sha256"] == candidate.selection["source_output"]["manifest_sha256"],
            "persisted candidate mode or source selection differs",
        )
        expected_members = {"selection.json", "assertions.json", "native-execution.json", "input-receipt.json"}
        for prefix, root in (
            ("native-source", candidate.source_output),
            ("native-companion", candidate.companion_output),
        ):
            if root is not None:
                expected_members.update(prefix + "/" + name for name in candidate._snapshots.directories[root])
        _require(set(manifest["files"]) == expected_members, "candidate member inventory differs from selected mode")
        _require(
            candidate.payload() == read_json(snapshots.files[directory / "assertions.json"][0]),
            "reloaded native assertions differ",
        )
        for prefix, root in (
            ("native-source", candidate.source_output),
            ("native-companion", candidate.companion_output),
        ):
            if root is None:
                continue
            for name in candidate._snapshots.directories[root]:
                _require(
                    snapshots.files[directory / prefix / name][0] == candidate._snapshots.files[root / name][0],
                    "reloaded native product differs",
                )
        snapshots.verify()
        return candidate
