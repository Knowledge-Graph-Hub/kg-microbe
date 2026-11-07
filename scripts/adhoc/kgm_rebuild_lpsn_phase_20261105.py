"""Launch the final approved M5 dependency phase using existing environment credentials."""

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "data/rebuild-evidence/20261105/mediadive-resolution-1734"
KEYS = ("LPSN_USERNAME", "LPSN_PASSWORD")


def strict_object(pairs):
    """Reject duplicate receipt fields rather than silently selecting one value."""
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate phase admission field: {key!r}")
        result[key] = value
    return result


def encoded(value):
    """Compare native JSON types exactly, including integer versus boolean fields."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def bind_module_origins(guard, planner):
    """Require every loaded production module and the planner to belong to this checkout."""
    planner_path = Path(planner.__file__).resolve()
    if planner_path != ROOT / "scripts/adhoc/kgm_rebuild_admission_20261105.py":
        raise RuntimeError("Planner module resolves outside the owned worktree")
    guard.capture(planner_path)
    for name, module in tuple(sys.modules.items()):
        if name != "kg_microbe" and not name.startswith("kg_microbe."):
            continue
        filename = getattr(module, "__file__", None)
        if filename is not None:
            path = Path(filename).resolve()
            if not path.is_relative_to(ROOT / "kg_microbe"):
                raise RuntimeError(f"Production module resolves outside the owned worktree: {name}")
            guard.capture(path)


def main():
    """Require canonical prior admission and credentials already present in the environment."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", required=True)
    parser.add_argument("--phase3-receipt", required=True, type=Path)
    parser.add_argument("--phase3-sha256", required=True)
    parser.add_argument("--receipt", required=True, type=Path)
    args = parser.parse_args()
    if Path.cwd().resolve() != ROOT or Path(sys.prefix).resolve() != ROOT / ".venv":
        raise RuntimeError("Use the isolated interpreter from the owned worktree")
    sys.path.insert(0, str(ROOT))
    import kg_microbe
    from kg_microbe.merge_utils.source_admission import SourceAdmission
    from scripts.adhoc import kgm_rebuild_admission_20261105 as planner

    if Path(kg_microbe.__file__).resolve() != ROOT / "kg_microbe/__init__.py":
        raise RuntimeError("KG package resolves outside the owned worktree")
    record = args.phase3_receipt.absolute()
    output = args.receipt.resolve()
    if not record.resolve().is_relative_to(EVIDENCE) or not output.is_relative_to(EVIDENCE) or output.exists():
        raise RuntimeError("Require retained phase admission and a new owned evidence receipt")
    guard = SourceAdmission()
    bind_module_origins(guard, planner)
    config = ROOT / "merge.yaml"
    guard.capture(config)
    body = guard.capture(record, retain=True)
    if hashlib.sha256(body).hexdigest() != args.phase3_sha256:
        raise RuntimeError("Phase 3 receipt identity changed")
    admission = json.loads(body, object_pairs_hook=strict_object)
    if (
        admission.get("root") != str(ROOT)
        or admission.get("status") != "pass"
        or admission.get("command") != "verify-sources"
    ):
        raise RuntimeError("Require successful owned production source admission before phase 4")
    plan = planner.build_plan(ROOT, ROOT / "data/raw", ROOT / "data/transformed", config, ROOT / "data/merged")
    if encoded(admission.get("plan")) != encoded(plan):
        raise RuntimeError("Phase 3 receipt differs from the current complete canonical plan")
    phases = plan["phases"]
    if len(phases) != 4 or phases[3] != ["lpsn_api", "microbedecoder"]:
        raise RuntimeError("Approved final dependency phase changed")
    expected = {source for phase in phases[:3] for source in phase}
    preceding = admission.get("verification", {}).get("sources")
    if not isinstance(preceding, dict) or set(preceding) != expected:
        raise RuntimeError("Receipt does not admit all canonical preceding phases")
    bind_module_origins(guard, planner)
    available = {key: bool(os.environ.get(key)) for key in KEYS}
    if not all(available.values()):
        raise RuntimeError("LPSN_USERNAME and LPSN_PASSWORD must already be available in the process environment")
    launcher = ROOT / "scripts/adhoc/kgm_rebuild_20261105.py"
    launcher_identity = guard.capture(launcher)
    helper_identity = guard.capture(Path(__file__).resolve())
    command = [
        str(ROOT / ".venv/bin/python"),
        "-B",
        str(launcher),
        "launch",
        args.label,
        "--",
        "-m",
        "kg_microbe.run",
        "transform",
        "-i",
        "data/raw",
        "-o",
        "data/transformed",
        "-s",
        "lpsn_api",
        "-s",
        "microbedecoder",
        "--no-show-status",
    ]
    guard.verify()
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x") as stream:
        json.dump(
            {
                "helper_sha256": helper_identity["sha256"],
                "launcher_sha256": launcher_identity["sha256"],
                "merge_config": {"path": str(config), **guard.capture(config)},
                "phase3_receipt": str(record),
                "phase3_sha256": args.phase3_sha256,
                "canonical_plan": plan,
                "helper_credentials_available": available,
                "helper_credential_values_recorded": False,
                "helper_credential_files_read": False,
                "helper_credential_files_created": False,
                "child_credential_file_access": (
                    "Not certified by this helper. Production LPSN initialization calls load_dotenv(); "
                    "the helper only requires the two credentials already in its process environment."
                ),
                "command": command,
                "interpretation": "Launch evidence only; actual child result and production admission remain required.",
            },
            stream,
            indent=2,
            sort_keys=True,
        )
        stream.write("\n")
    guard.verify()
    return subprocess.run(command, cwd=ROOT, check=False).returncode  # noqa: S603 - fixed owned launcher, no shell


if __name__ == "__main__":
    raise SystemExit(main())
