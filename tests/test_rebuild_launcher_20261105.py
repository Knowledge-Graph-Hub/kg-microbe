"""Offline safety contracts for the retained M5 staging and execution launcher."""

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/adhoc/kgm_rebuild_20261105.py"


@pytest.fixture
def launcher(tmp_path, monkeypatch):
    """Load an independent helper and bind every writable location to a temporary checkout."""
    monkeypatch.delenv("LPSN_USERNAME", raising=False)
    monkeypatch.delenv("LPSN_PASSWORD", raising=False)
    spec = importlib.util.spec_from_file_location("rebuild_launcher_test", SCRIPT)
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    root = tmp_path / "owned"
    root.mkdir()
    script = root / "scripts/adhoc/launcher.py"
    script.parent.mkdir(parents=True)
    script.write_text('"""Synthetic launcher identity."""\n')
    monkeypatch.setattr(helper, "ROOT", root)
    monkeypatch.setattr(helper, "EVIDENCE", root / "data/rebuild-evidence/test")
    monkeypatch.setattr(helper, "PYTHON", root / ".venv/bin/python")
    monkeypatch.setattr(helper, "LAUNCHER", script)
    return helper


@pytest.fixture
def raw_source(tmp_path):
    """Create small immutable input bytes, including files hidden from ordinary searches."""
    source = tmp_path / "original/raw"
    source.mkdir(parents=True)
    (source / "predicate_mapping.yaml").write_text("fixture: mapping\n")
    (source / ".gitignore").write_text("hidden/\n")
    hidden = source / "hidden/.cache"
    hidden.mkdir(parents=True)
    (hidden / "input.json").write_text('{"original": true}\n')
    return source


@pytest.fixture
def fake_cp(launcher, monkeypatch):
    """Replace APFS commands with independent temporary-file copies, retaining real metadata checks."""
    calls = []

    def copy(command, *, check):
        """Implement only the launcher's two copy forms against temporary fixtures."""
        assert check is True
        assert command[:3] == ["/bin/cp", "-c", "-p"]
        calls.append(command)
        source, destination = Path(command[-2]), Path(command[-1])
        if "-R" in command:
            shutil.copytree(source, destination, dirs_exist_ok=True)
        else:
            shutil.copy2(source, destination)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(launcher.subprocess, "run", copy)
    return calls


def test_inventory_includes_hidden_and_ignored_files(launcher, raw_source):
    """Inventory membership must include bytes that gitignore-aware searches omit."""
    assert set(launcher.inventory(raw_source)) == {
        "predicate_mapping.yaml",
        ".gitignore",
        "hidden/.cache/input.json",
    }


@pytest.mark.parametrize("kind", ["root_link", "file_link", "directory_link", "fifo"])
def test_inventory_rejects_links_and_special_files(launcher, raw_source, tmp_path, kind):
    """Reject aliased or non-regular sources before copying any file."""
    if kind == "root_link":
        selected = tmp_path / "alias"
        selected.symlink_to(raw_source, target_is_directory=True)
    else:
        selected = raw_source
        target = raw_source / "unsafe"
        if kind == "fifo":
            os.mkfifo(target)
        elif kind == "file_link":
            target.symlink_to(raw_source / "predicate_mapping.yaml")
        else:
            target.symlink_to(raw_source / "hidden", target_is_directory=True)
    with pytest.raises(RuntimeError):
        launcher.inventory(selected)


def test_inventory_cannot_silently_skip_unreadable_subtree(launcher, raw_source, monkeypatch):
    """An incomplete directory traversal cannot certify a complete input inventory."""

    def denied_walk(root, *, followlinks, onerror=None):
        """Model os.walk's default suppression of a filesystem permission error."""
        assert root == raw_source
        assert followlinks is False
        if onerror is not None:
            onerror(PermissionError("unreadable input subtree"))
        yield str(root), [], []

    monkeypatch.setattr(launcher.os, "walk", denied_walk)
    with pytest.raises((OSError, RuntimeError), match="unreadable"):
        launcher.inventory(raw_source)


@pytest.mark.parametrize("relationship", ["same", "inside", "ancestor", "escaped_destination"])
def test_staging_rejects_overlapping_or_escaped_paths(launcher, tmp_path, monkeypatch, relationship):
    """Reject both containment directions and a destination escaping through its parent symlink."""
    if relationship == "same":
        source = launcher.ROOT / "data/raw"
    elif relationship == "inside":
        source = launcher.ROOT / "nested/raw"
    elif relationship == "ancestor":
        source = launcher.ROOT.parent
    else:
        outside = tmp_path / "unowned-output"
        outside.mkdir()
        (launcher.ROOT / "data").symlink_to(outside, target_is_directory=True)
        source = tmp_path / "independent-source"
    source.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(launcher, "inventory", lambda root: pytest.fail("unsafe path reached inventory"))
    with pytest.raises(RuntimeError):
        launcher.stage_raw(source)


@pytest.mark.parametrize("kind", ["existing", "symlink", "dangling_symlink"])
def test_staging_never_overwrites_destination(launcher, raw_source, tmp_path, monkeypatch, kind):
    """An existing destination or link remains untouched and no copy is attempted."""
    destination = launcher.ROOT / "data/raw"
    destination.parent.mkdir()
    if kind == "existing":
        destination.mkdir()
        (destination / "keep").write_text("existing output")
    else:
        target = tmp_path / "target"
        if kind == "symlink":
            target.mkdir()
        destination.symlink_to(target, target_is_directory=True)
    monkeypatch.setattr(launcher.subprocess, "run", lambda *a, **kw: pytest.fail("copy attempted"))
    with pytest.raises(RuntimeError):
        launcher.stage_raw(raw_source)
    if kind == "existing":
        assert (destination / "keep").read_text() == "existing output"
    else:
        assert destination.is_symlink()


def test_staging_proves_independence_before_complete_copy(launcher, raw_source, fake_cp):
    """The clone proof precedes bulk staging, whose receipt accounts for every independent file."""
    before = launcher.inventory(raw_source)
    launcher.stage_raw(raw_source)
    destination = launcher.ROOT / "data/raw"
    evidence = launcher.EVIDENCE / "raw-staging"
    proof = json.loads((evidence / "clone-proof.json").read_text())
    receipt = json.loads((evidence / "receipt.json").read_text())
    assert len(fake_cp) == 2 and "-R" not in fake_cp[0] and "-R" in fake_cp[1]
    assert proof["independent_inode"] is True
    assert proof["sha256"] == hashlib.sha256((raw_source / "predicate_mapping.yaml").read_bytes()).hexdigest()
    assert receipt["files"] == len(before)
    assert receipt["bytes"] == sum(entry["size"] for entry in before.values())
    assert receipt["original_inventory_unchanged"] and receipt["independent_inodes"]
    assert launcher.inventory(raw_source) == before
    for relative in before:
        original, copied = raw_source / relative, destination / relative
        assert original.read_bytes() == copied.read_bytes()
        assert original.stat().st_ino != copied.stat().st_ino
    (destination / "predicate_mapping.yaml").write_text("changed staged bytes")
    assert (raw_source / "predicate_mapping.yaml").read_text() == "fixture: mapping\n"


@pytest.mark.parametrize("damage", ["hardlink", "changed_bytes"])
def test_failed_clone_proof_prevents_bulk_copy(launcher, raw_source, monkeypatch, damage):
    """An aliased or corrupted probe cannot authorize staging the remaining inputs."""
    calls = []

    def failed_probe(command, *, check):
        """Return a successful command status with an unsafe probe artifact."""
        calls.append(command)
        source, destination = Path(command[-2]), Path(command[-1])
        if damage == "hardlink":
            os.link(source, destination)
        else:
            destination.write_text("wrong bytes")

    monkeypatch.setattr(launcher.subprocess, "run", failed_probe)
    with pytest.raises(RuntimeError, match="clone"):
        launcher.stage_raw(raw_source)
    assert len(calls) == 1
    assert not (launcher.ROOT / "data/raw").exists()
    assert not (launcher.EVIDENCE / "raw-staging/receipt.json").exists()


@pytest.mark.parametrize("damage", ["changed_source", "missing_copy", "aliased_copy"])
def test_incomplete_or_shared_staging_never_gets_success_receipt(launcher, raw_source, fake_cp, monkeypatch, damage):
    """Successful copy exit codes cannot hide source mutation, omissions, or shared inodes."""
    copy = launcher.subprocess.run

    def damaged_copy(command, *, check):
        """Inject an integrity failure after the synthetic recursive copy."""
        result = copy(command, check=check)
        if "-R" in command:
            source_file = raw_source / "hidden/.cache/input.json"
            copied_file = Path(command[-1]) / "hidden/.cache/input.json"
            if damage == "changed_source":
                source_file.write_text("source changed during copy")
            else:
                copied_file.unlink()
                if damage == "aliased_copy":
                    os.link(source_file, copied_file)
        return result

    monkeypatch.setattr(launcher.subprocess, "run", damaged_copy)
    with pytest.raises(RuntimeError):
        launcher.stage_raw(raw_source)
    assert not (launcher.EVIDENCE / "raw-staging/receipt.json").exists()


def test_environment_binds_owned_inputs_and_preserves_stronger_checks(launcher, monkeypatch):
    """Unrelated shell settings cannot redirect the run or weaken its required release checks."""
    inherited = {
        "PYTHONPATH": "/old/checkout",
        "KG_MICROBE_BIOLINK_MODEL": "/old/schema.yaml",
        "KG_GO_VERSION_CHECK": "warn",
        "KG_SEMSQL_BUILD": "off",
        "PREGO_SHAPES": "all",
        "GOLD_APPLY_TAXON_TRIM": "false",
        "METATRAITS_WORKERS": "999",
        "KG_NCBITAXON_VERSION_CHECK": "strict",
        "KG_CHEBI_VERSION_CHECK": "strict",
        "ROBOT_JAVA_ARGS": "-Xmx16g -XX:+UseG1GC",
    }
    for key, value in inherited.items():
        monkeypatch.setenv(key, value)
    env = launcher.environment()
    raw = launcher.ROOT / "data/raw"
    assert env["PYTHONPATH"] == str(launcher.ROOT)
    assert env["VIRTUAL_ENV"] == str(launcher.ROOT / ".venv")
    assert env["PATH"].split(os.pathsep)[:3] == [
        str(launcher.PYTHON.parent),
        env["JAVA_HOME"] + "/bin",
        "/Users/marcin/.local/bin",
    ]
    assert env["KG_MICROBE_BIOLINK_MODEL"] == str(raw / "biolink-model.yaml")
    assert env["KG_MICROBE_BIOLINK_PREDICATE_MAP"] == str(raw / "predicate_mapping.yaml")
    assert env["KG_MICROBE_METPO_JSON"] == str(raw / "metpo.json")
    assert env["KG_MICROBE_METPO_TEMPLATE_DIR"] == str(raw)
    assert env["KG_GO_VERSION_CHECK"] == "strict" and env["KG_SEMSQL_BUILD"] == "on"
    assert env["KG_NCBITAXON_VERSION_CHECK"] == env["KG_CHEBI_VERSION_CHECK"] == "strict"
    assert env["ROBOT_JAVA_ARGS"] == inherited["ROBOT_JAVA_ARGS"]
    assert (env["PREGO_SHAPES"], env["PREGO_MIN_CONFIDENCE"], env["PREGO_HABITAT_MIN_SCORE"]) == ("habitat", "0", "1.0")
    assert env["GOLD_APPLY_TAXON_TRIM"] == env["METATRAITS_MULTIPROCESSING"] == "true"
    assert env["METATRAITS_WORKERS"] == "4"
    assert env["PYTHONDONTWRITEBYTECODE"] == env["PYTHONUNBUFFERED"] == "1"
    assert launcher.environment() == env
    assert {key: os.environ[key] for key in inherited} == inherited


@pytest.mark.parametrize("foreign", [False, True])
def test_origins_rejects_old_lazy_module(launcher, tmp_path, monkeypatch, foreign):
    """A correct package origin cannot conceal a lazy module loaded from the original checkout."""
    package = launcher.ROOT / "kg_microbe/__init__.py"
    package.parent.mkdir()
    package.write_text('"""Owned package."""\n')
    child = (tmp_path / "old" if foreign else package.parent) / "lazy.py"
    child.parent.mkdir(exist_ok=True)
    child.write_text('"""Lazy module."""\n')
    modules = {
        "kg_microbe": SimpleNamespace(__file__=str(package)),
        "kg_microbe.lazy": SimpleNamespace(__file__=str(child)),
    }
    monkeypatch.setattr(launcher, "sys", SimpleNamespace(modules=modules))
    if foreign:
        with pytest.raises(RuntimeError, match="Wrong module origin.*kg_microbe.lazy"):
            launcher.origins()
    else:
        origins = launcher.origins()
        assert set(origins) == set(modules)
        assert origins["kg_microbe.lazy"]["sha256"] == hashlib.sha256(child.read_bytes()).hexdigest()


def test_persistent_launch_records_actual_command_and_environment(launcher, monkeypatch):
    """Launch a detached, noninteractive process with durable evidence and no credential dump."""
    monkeypatch.chdir(launcher.ROOT)
    command = ["-m", "kg_microbe.run", "transform", "-s", "ontologies", "--no-show-status"]
    monkeypatch.setattr(launcher.sys, "argv", ["launcher", "launch", "canary", "--", *command])
    monkeypatch.setenv("BACDIVE_PASSWORD", "synthetic-private-value")
    calls = []

    def popen(arguments, **kwargs):
        """Capture process settings while leaving production and network execution disabled."""
        calls.append((arguments, kwargs))
        kwargs["stdout"].write(b"synthetic child output\n")
        return SimpleNamespace(pid=424242)

    monkeypatch.setattr(launcher.subprocess, "Popen", popen)
    assert launcher.main() == 0
    arguments, settings = calls[0]
    assert arguments == [str(launcher.PYTHON), "-B", str(launcher.LAUNCHER), "_run", "canary", "--", *command]
    assert settings["cwd"] == launcher.ROOT
    assert settings["start_new_session"] is True
    assert settings["stdin"] == subprocess.DEVNULL and settings["stderr"] == subprocess.STDOUT
    assert settings["env"] == launcher.environment()
    folder = launcher.EVIDENCE / "stages/canary"
    plan = json.loads((folder / "plan.json").read_text())
    process = json.loads((folder / "process.json").read_text())
    assert plan["command"] == command and plan["python"] == str(launcher.PYTHON)
    assert plan["launcher_sha256"] == hashlib.sha256(launcher.LAUNCHER.read_bytes()).hexdigest()
    selected = launcher.environment_fingerprint(settings["env"])
    assert plan["environment_sha256"] == selected["environment_sha256"]
    assert plan["fingerprint_scope"] == selected["fingerprint_scope"]
    assert plan["environment_bindings"] == selected["environment_bindings"]
    assert "BACDIVE_PASSWORD" not in plan["environment_bindings"]
    assert process["pid"] == process["process_group"] == 424242
    assert Path(process["log"]).read_bytes() == b"synthetic child output\n"
    assert "synthetic-private-value" not in (folder / "plan.json").read_text()
    before = {path.name: path.read_bytes() for path in folder.iterdir()}
    with pytest.raises(FileExistsError):
        launcher.main()
    assert len(calls) == 1
    assert before == {path.name: path.read_bytes() for path in folder.iterdir()}


@pytest.mark.parametrize("outcome", ["success", "nonzero", "foreign_import"])
def test_execution_receipt_requires_good_exit_and_final_origins(launcher, tmp_path, monkeypatch, outcome):
    """Persist failures and reject successful Python execution that loaded original-checkout code."""
    monkeypatch.chdir(launcher.ROOT)
    package = launcher.ROOT / "kg_microbe/__init__.py"
    package.parent.mkdir()
    package.write_text('"""Owned package."""\n')
    modules = {"kg_microbe": SimpleNamespace(__file__=str(package))}
    runtime = SimpleNamespace(
        modules=modules, path=[], argv=[], prefix=str(launcher.ROOT / ".venv"), executable=str(launcher.PYTHON)
    )
    monkeypatch.setattr(launcher, "sys", runtime)
    monkeypatch.setattr(
        launcher,
        "importlib",
        SimpleNamespace(import_module=lambda name: modules[name], metadata=SimpleNamespace(version=lambda name: "1")),
    )

    def run_module(name, *, run_name, alter_sys):
        """Model module completion and late import contamination without executing a transform."""
        assert (name, run_name, alter_sys) == ("kg_microbe.run", "__main__", True)
        if outcome == "foreign_import":
            foreign = tmp_path / "old_module.py"
            foreign.write_text('"""Foreign module."""\n')
            modules["kg_microbe.late"] = SimpleNamespace(__file__=str(foreign))
        if outcome == "nonzero":
            raise SystemExit(7)

    monkeypatch.setattr(launcher, "runpy", SimpleNamespace(run_module=run_module))
    expected = {"success": 0, "nonzero": 7, "foreign_import": 1}[outcome]
    assert launcher.execute_stage("execution", ["-m", "kg_microbe.run"]) == expected
    folder = launcher.EVIDENCE / "stages/execution"
    started = json.loads((folder / "started.json").read_text())
    result = json.loads((folder / "result.json").read_text())
    assert started["origins_before"]["kg_microbe"]["file"] == str(package)
    assert result["exit_code"] == expected
    assert result["finished"] >= result["started"]
    if outcome == "foreign_import":
        assert "Wrong module origin" in result["origin_error"]


@pytest.mark.parametrize("damage", [None, "changed_seed", "changed_source", "untracked", "missing_seed"])
def test_checkout_seed_preservation_requires_exact_head_and_source(launcher, raw_source, monkeypatch, damage):
    """Only pristine tracked seed bytes shared with the original may be moved aside."""
    destination = launcher.ROOT / "data/raw"
    destination.mkdir(parents=True)
    seed = destination / "predicate_mapping.yaml"
    original = raw_source / seed.name
    committed = original.read_bytes()
    seed.write_bytes(committed)

    def git_read(command, *, cwd):
        """Represent an immutable HEAD containing one raw seed."""
        assert cwd == launcher.ROOT
        if command[1] == "ls-tree":
            return b"data/raw/predicate_mapping.yaml\0"
        assert command == ["/usr/bin/git", "show", "HEAD:data/raw/predicate_mapping.yaml"]
        return committed

    monkeypatch.setattr(launcher.subprocess, "check_output", git_read)
    if damage == "changed_seed":
        seed.write_text("local edits")
    elif damage == "changed_source":
        original.write_text("source differs")
    elif damage == "untracked":
        (destination / ".unknown").write_text("preserve me")
    elif damage == "missing_seed":
        seed.unlink()
    before = launcher.inventory(destination)
    if damage:
        with pytest.raises(RuntimeError):
            launcher.preserve_checkout_seeds(raw_source, destination)
        assert launcher.inventory(destination) == before
        assert not (launcher.EVIDENCE / "checkout-raw-seeds").exists()
    else:
        launcher.preserve_checkout_seeds(raw_source, destination)
        saved = launcher.EVIDENCE / "checkout-raw-seeds"
        assert not destination.exists()
        assert (saved / "raw" / seed.name).read_bytes() == committed
        assert original.read_bytes() == committed
        assert json.loads((saved / "hashes.json").read_text()) == {
            "data/raw/predicate_mapping.yaml": hashlib.sha256(committed).hexdigest()
        }


def test_environment_fingerprint_ignores_all_unselected_secrets(launcher):
    """Credential rotation and arbitrary inherited values never enter the fingerprint input."""
    env = launcher.environment()
    expected = launcher.environment_fingerprint(env)
    env.update(
        LPSN_USERNAME="synthetic-user-a",
        LPSN_PASSWORD="synthetic-pass-a",  # noqa: S106 - synthetic secret-rotation control
        OTHER_SECRET="synthetic-key-a",  # noqa: S106 - synthetic secret-rotation control
        UNREVIEWED_VARIABLE="unreviewed-a",
    )
    assert launcher.environment_fingerprint(env) == expected
    env.update(
        LPSN_USERNAME="synthetic-user-b",
        LPSN_PASSWORD="synthetic-pass-b",  # noqa: S106 - synthetic secret-rotation control
        OTHER_SECRET="synthetic-key-b",  # noqa: S106 - synthetic secret-rotation control
        UNREVIEWED_VARIABLE="unreviewed-b",
    )
    assert launcher.environment_fingerprint(env) == expected
    encoded = json.dumps(expected)
    assert all(value not in encoded for value in ("synthetic-user", "synthetic-pass", "synthetic-key", "unreviewed"))
    assert expected["fingerprint_scope"]["version"] == 1
    assert set(expected["environment_bindings"]) == set(launcher.FINGERPRINT_KEYS)


@pytest.mark.parametrize(
    "key,value",
    [
        ("KG_NCBITAXON_VERSION_CHECK", "strict"),
        ("KG_CHEBI_VERSION_CHECK", "strict"),
        ("ROBOT_JAVA_ARGS", "-Xmx16g"),
        ("JAVA_TOOL_OPTIONS", "-DentityExpansionLimit=0"),
        ("JDK_JAVA_OPTIONS", "-Xmx8g"),
        ("PREGO_HABITAT_MIN_SCORE", "2.0"),
    ],
)
def test_reviewed_nonsecret_settings_remain_fingerprint_sensitive(launcher, key, value):
    """Explicit version guards, JVM arguments and scientific thresholds remain identity inputs."""
    env = launcher.environment()
    env.pop(key, None)
    before = launcher.environment_fingerprint(env)
    env[key] = value
    after = launcher.environment_fingerprint(env)
    assert after["environment_sha256"] != before["environment_sha256"]
    assert after["environment_bindings"][key] == value


@pytest.mark.parametrize(
    "command",
    [
        ["-m", "kg_microbe.run", "--password", "unbound-secret"],
        ["scripts/stage.py", "--token=unbound-token"],
        ["scripts/stage.py", "synthetic-password"],
        ["scripts/stage.py", "https://synthetic:auth@example.invalid/"],
    ],
)
def test_sensitive_commands_refused_before_any_evidence_or_spawn(launcher, monkeypatch, command):
    """Unsafe arguments never reach the filesystem, a child, or an exception message."""
    monkeypatch.setenv("LPSN_PASSWORD", "synthetic-password")
    monkeypatch.chdir(launcher.ROOT)
    monkeypatch.setattr(launcher.sys, "argv", ["launcher", "launch", "refused", "--", *command])
    monkeypatch.setattr(launcher.subprocess, "Popen", lambda *args, **kwargs: pytest.fail("Unsafe command spawned"))
    monkeypatch.setattr(
        launcher, "hashlib", SimpleNamespace(sha256=lambda *args: pytest.fail("Unsafe argument hashed"))
    )
    with pytest.raises(RuntimeError):
        launcher.command_sha256(command)
    assert launcher.main() == 1
    assert not launcher.EVIDENCE.exists()


def test_authenticated_parent_uses_devnull_and_safe_plan(launcher, monkeypatch):
    """Child startup cannot leak diagnostics before the worker installs its own suppression."""
    monkeypatch.setenv("LPSN_USERNAME", "synthetic-user")
    monkeypatch.setenv("LPSN_PASSWORD", "synthetic-password")
    monkeypatch.chdir(launcher.ROOT)
    command = ["-m", "kg_microbe.run", "transform", "-s", "lpsn_api"]
    monkeypatch.setattr(launcher.sys, "argv", ["launcher", "launch", "authenticated", "--", *command])
    calls = []

    def popen(arguments, **kwargs):
        """Capture only launch configuration without creating a process."""
        calls.append((arguments, kwargs))
        assert kwargs["stdout"] == kwargs["stderr"] == subprocess.DEVNULL
        assert kwargs["env"]["LPSN_PASSWORD"] == os.environ["LPSN_PASSWORD"]
        return SimpleNamespace(pid=12345)

    monkeypatch.setattr(launcher.subprocess, "Popen", popen)
    assert launcher.main() == 0
    folder = launcher.EVIDENCE / "stages/authenticated"
    plan = json.loads((folder / "plan.json").read_text())
    assert plan["command_withheld"] and "command" not in plan
    assert plan["diagnostics"] == "suppressed_authenticated_stage"
    assert (folder / "process.log").read_bytes() == b""
    assert len(calls) == 1
    assert b"synthetic-password" not in b"".join(path.read_bytes() for path in folder.iterdir())


@pytest.fixture
def diagnostic_subprocess(tmp_path):
    """Copy the real launcher into a tiny checkout served by the current isolated interpreter."""
    root = tmp_path / "owned"
    script = root / "scripts/adhoc/launcher.py"
    script.parent.mkdir(parents=True)
    shutil.copyfile(SCRIPT, script)
    (root / ".venv").symlink_to(Path(sys.prefix), target_is_directory=True)
    package = root / "kg_microbe"
    package.mkdir()
    (package / "__init__.py").write_text(
        "import logging, os\n"
        'logging.warning("import-token:" + os.environ.get("LPSN_PASSWORD", "public"))\n'
        'os.write(2, b"import-native-diagnostic")\n'
    )
    probe = root / "scripts/probe.py"
    probe.write_text("""import atexit, base64, logging, os, pathlib, sys, types
value = os.environ.get("LPSN_PASSWORD") or os.environ.get("LPSN_USERNAME") or "PUBLIC-DIAGNOSTIC"
token = "server-token-" + base64.b64encode(value.encode()).decode()
for stream in (sys.stdout, sys.stderr, sys.__stdout__, sys.__stderr__):
    stream.write(value[:5])
    stream.write(value[5:] + token)
    stream.flush()
for fd in (1, 2):
    os.write(fd, value[:5].encode())
    os.write(fd, (value[5:] + token).encode())
logging.error(token)
logging.getLogger("synthetic-third-party").addHandler(logging.FileHandler("logging-probe.log"))
logging.getLogger("synthetic-third-party").critical(token)
atexit.register(lambda: print(token))
outcome = sys.argv[1]
if outcome == "exception":
    raise type(value, (Exception,), {})(token)
if outcome == "exit":
    raise SystemExit(7)
if outcome == "exit_text":
    raise SystemExit(token)
if outcome == "foreign":
    foreign = pathlib.Path.cwd().parent / "foreign.py"
    foreign.write_text("# synthetic foreign module")
    sys.modules["kg_microbe.foreign"] = types.SimpleNamespace(__file__=str(foreign))
if outcome == "alias":
    sys.modules["kg_microbe." + token] = sys.modules["kg_microbe"]
if outcome == "receipt_failure":
    (pathlib.Path("data/rebuild-evidence/20261105/stages/worker") / "result.json").mkdir()
""")
    return root, script


@pytest.mark.parametrize("credential", ["LPSN_USERNAME", "LPSN_PASSWORD"])
@pytest.mark.parametrize(
    "outcome,expected",
    [
        ("success", 0),
        ("exception", 1),
        ("exit", 7),
        ("exit_text", 1),
        ("foreign", 1),
        ("alias", 1),
        ("receipt_failure", 1),
    ],
)
def test_authenticated_real_worker_suppresses_every_diagnostic_channel(
    diagnostic_subprocess, credential, outcome, expected
):
    """Native/split/Python/logging/shutdown output and arbitrary exception text never reach evidence."""
    root, script = diagnostic_subprocess
    env = os.environ.copy()
    env.pop("LPSN_USERNAME", None)
    env.pop("LPSN_PASSWORD", None)
    env[credential] = "synthetic-private-value"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    completed = subprocess.run(  # noqa: S603 - fixed offline synthetic script
        [sys.executable, "-B", str(script), "_run", "worker", "--", "scripts/probe.py", outcome],
        cwd=root,
        env=env,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == expected
    assert completed.stdout == completed.stderr == b""
    folder = root / "data/rebuild-evidence/20261105/stages/worker"
    persisted = b"".join(path.read_bytes() for path in folder.rglob("*") if path.is_file())
    assert b"synthetic-private-value" not in persisted and b"server-token-" not in persisted
    assert (root / "logging-probe.log").read_bytes() == b""
    if outcome == "receipt_failure":
        assert (folder / "result.json").is_dir()
    else:
        result = json.loads((folder / "result.json").read_text())
        assert result["exit_code"] == expected
        assert "origins_before" in result
        assert result["command_withheld"] and "command" not in result and "versions" not in result
        assert "error" not in result and "origin_error" not in result
        if outcome in {"foreign", "alias"}:
            assert result["origin_error_type"] == "RuntimeError"
        else:
            assert "origins_after" in result
        if outcome == "exception":
            assert result["error_type"] == "Exception"


def test_credential_free_worker_retains_diagnostics(diagnostic_subprocess):
    """Ordinary stages retain readable diagnostics and full failure evidence."""
    root, script = diagnostic_subprocess
    env = os.environ.copy()
    env.pop("LPSN_USERNAME", None)
    env.pop("LPSN_PASSWORD", None)
    completed = subprocess.run(  # noqa: S603 - fixed offline synthetic script
        [sys.executable, "-B", str(script), "_run", "worker", "--", "scripts/probe.py", "exception"],
        cwd=root,
        env=env,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 1
    assert b"PUBLIC-DIAGNOSTIC" in completed.stdout + completed.stderr
    result = json.loads((root / "data/rebuild-evidence/20261105/stages/worker/result.json").read_text())
    assert "server-token-" in result["error"]
    assert "command" in result and "versions" in result


def test_authenticated_origin_names_match_actual_owned_modules(launcher, monkeypatch):
    """The actual KG package and ordinary lazy imports retain canonical authenticated origins."""
    import importlib

    monkeypatch.setattr(launcher, "ROOT", SCRIPT.parents[2])
    importlib.import_module("kg_microbe.transform_utils.lpsn_api.lpsn_api")
    actual = launcher.stage_origins(authenticated=True)
    assert "kg_microbe" in actual
    assert "kg_microbe.transform_utils.lpsn_api.lpsn_api" in actual


@pytest.mark.parametrize("key", ["ROBOT_JAVA_ARGS", "JAVA_TOOL_OPTIONS", "JDK_JAVA_OPTIONS", "_JAVA_OPTIONS"])
def test_credential_shaped_jvm_binding_cannot_be_persisted_or_hashed(launcher, key):
    """An allowlisted JVM setting does not authorize embedding a password option."""
    env = launcher.environment()
    env[key] = "-Dhttp.proxyPassword=synthetic-unbound-value"
    with pytest.raises(RuntimeError, match="Credential-bearing JVM bindings"):
        launcher.environment_fingerprint(env)


def test_authenticated_real_parent_and_worker_bind_the_same_nonsecret_command(diagnostic_subprocess):
    """#1784 binds the actual child command to its approved plan without recording argument text."""
    root, script = diagnostic_subprocess
    env = os.environ.copy()
    env["LPSN_USERNAME"] = "synthetic-private-user"
    env["LPSN_PASSWORD"] = "synthetic-private-password"  # noqa: S105 - synthetic subprocess control
    command = ["scripts/probe.py", "success"]
    expected = hashlib.sha256(
        json.dumps(command, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    completed = subprocess.run(  # noqa: S603 - actual launcher with fixed offline synthetic command
        [sys.executable, "-B", str(script), "launch", "worker", "--", *command],
        cwd=root,
        env=env,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0
    assert completed.stdout == completed.stderr == b""
    folder = root / "data/rebuild-evidence/20261105/stages/worker"
    deadline = time.monotonic() + 10
    result = None
    while time.monotonic() < deadline:
        try:
            result = json.loads((folder / "result.json").read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            time.sleep(0.02)
        else:
            break
    assert result is not None, "The actual worker did not finish its safe receipt"
    plan = json.loads((folder / "plan.json").read_text())
    started = json.loads((folder / "started.json").read_text())
    assert plan["command_sha256"] == started["command_sha256"] == result["command_sha256"] == expected
    assert result["exit_code"] == 0
    assert result["origins_before"] and result["origins_after"]
    assert all(record["command_withheld"] and "command" not in record for record in (plan, started, result))
    persisted = b"".join(path.read_bytes() for path in folder.iterdir() if path.is_file())
    assert b"scripts/probe.py" not in persisted
    assert b"synthetic-private-" not in persisted and b"server-token-" not in persisted
    assert (folder / "process.log").read_bytes() == b""
