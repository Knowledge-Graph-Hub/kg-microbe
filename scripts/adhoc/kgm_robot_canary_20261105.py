"""
Run one preserved UPA conversion through production ROBOT on 2026-11-05.

Inputs: independently staged pinned upa.owl, verified candidate ROBOT jar/wrapper.
Outputs: an isolated UPA JSON candidate and complete identities/version evidence.
No raw input or policy is replaced; the candidate requires separate semantic review.
"""

import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
UPGRADES = ROOT / "data/rebuild-evidence/20261105/upgrades"
DESTINATION = UPGRADES / "upa-canary"
ROBOT_SHA256 = "53cd275c8e4c0dad1fc2c1c34174876795cd7d6b6926e1444adcbb0cb3c7ab26"


def digest(path):
    """Measure full-byte identity with bounded memory."""
    checksum = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            checksum.update(block)
    return checksum.hexdigest()


def main():
    """Verify candidate acquisition, copy independent inputs, and perform exactly one conversion."""
    from kg_microbe.utils.robot_utils import convert_to_json, initialize_robot

    if Path.cwd().resolve() != ROOT:
        raise RuntimeError("Use the owned worktree")
    policy = json.loads((ROOT / "mappings/upa_reaction_projection_dispositions.json").read_text())
    owl = ROOT / "data/raw/upa.owl"
    old_json = ROOT / "data/raw/upa.json"
    if digest(owl) != policy["sources"]["upa.owl"]:
        raise RuntimeError("Native UPA source does not match the reviewed pin")
    if digest(old_json) != policy["sources"]["upa.json"]["sha256"]:
        raise RuntimeError("Preserved derived UPA source does not match the historical review")
    robot = UPGRADES / "candidates/robot1911"
    for name, key in (("robot.jar", "robot-jar"), ("robot", "robot-wrapper")):
        receipt = json.loads((UPGRADES / "candidates/http" / key / "receipt.json").read_text())
        if receipt["status"] != "downloaded" or digest(robot / name) != receipt["sha256"]:
            raise RuntimeError(f"Candidate acquisition receipt mismatch: {name}")
    if digest(robot / "robot.jar") != ROBOT_SHA256:
        raise RuntimeError("Candidate jar differs from the official release asset digest")
    DESTINATION.mkdir(parents=True, exist_ok=False)
    inputs = {}
    for source in (owl, robot / "robot.jar", robot / "robot"):
        destination = DESTINATION / source.name
        subprocess.run(["/bin/cp", "-c", "-p", str(source), str(destination)], check=True)  # noqa: S603
        if destination.samefile(source) or destination.stat().st_nlink != 1 or digest(source) != digest(destination):
            raise RuntimeError(f"Canary input is not an identical independent copy: {source}")
        inputs[source.name] = {"source": str(source), "sha256": digest(source), "bytes": source.stat().st_size}
    with (DESTINATION / "inputs.json").open("x") as stream:
        json.dump(inputs, stream, indent=2)
    wrapper, env = initialize_robot(str(DESTINATION))
    version = subprocess.run(  # noqa: S603 - fixed wrapper in owned candidate directory
        ["/bin/bash", wrapper, "--version"], env=env, check=True, capture_output=True, text=True
    )
    (DESTINATION / "robot-version.txt").write_text(version.stdout + version.stderr)
    if "1.9.11" not in version.stdout + version.stderr:
        raise RuntimeError("ROBOT execution did not report the verified release")
    convert_to_json(str(DESTINATION), "upa")
    candidate = DESTINATION / "upa.json"
    if not candidate.is_file() or not candidate.stat().st_size:
        raise RuntimeError("Production conversion did not publish nonempty UPA JSON")
    result = {
        "input_identities": inputs,
        "old_json_sha256": digest(old_json),
        "candidate_json_sha256": digest(candidate),
        "candidate_json_bytes": candidate.stat().st_size,
        "semantic_admission": False,
        "converter": "kg_microbe.utils.robot_utils.convert_to_json",
    }
    with (DESTINATION / "conversion.json").open("x") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
    print(json.dumps(result, indent=2), flush=True)


if __name__ == "__main__":
    main()
