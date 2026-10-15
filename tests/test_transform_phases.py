"""The phased parallel transform: dependency phases and the Slurm scripts that run them (#1567)."""

import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import kg_microbe.transform as dispatcher

REPO = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location("transform_phases", REPO / "scripts" / "transform_phases.py")
phases_script = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(phases_script)

BASH = shutil.which("bash")
needs_bash = pytest.mark.skipif(BASH is None, reason="needs bash")


def _upstream(name):
    """Return the sources ``name`` declares in TRANSFORM_INPUTS."""
    return tuple(getattr(dispatcher.DATA_SOURCES[name], "TRANSFORM_INPUTS", ()))


def test_every_default_source_runs_once_after_all_it_reads(tmp_path):
    """Each source of the default batch is in exactly one phase, after every upstream it declares."""
    (tmp_path / "bakta" / "dataset" / "bakta" / "SAMN00000001").mkdir(parents=True)
    phases, skipped = phases_script.plan(input_dir=tmp_path)
    planned = [name for phase in phases for name in phase]
    expected = [name for name in dispatcher.DATA_SOURCES if name not in dispatcher.EXPLICIT_ONLY_SOURCES]
    assert skipped == {}
    assert sorted(planned) == sorted(expected) and len(planned) == len(set(planned))
    phase_of = {name: index for index, phase in enumerate(phases) for name in phase}
    for name in planned:
        assert all(phase_of[upstream] < phase_of[name] for upstream in _upstream(name)), name
    assert phases[0][0] == "ontologies"
    assert all(phase for phase in phases)


def test_an_optional_source_with_no_input_is_skipped_with_its_dependents(tmp_path):
    """As in the default batch: named with -s, Bakta with no dataset would fail instead (#1567)."""
    phases, skipped = phases_script.plan(input_dir=tmp_path)
    assert "bakta" in skipped
    assert "bakta" not in {name for phase in phases for name in phase}


def test_a_selection_waits_only_for_the_upstreams_it_includes(tmp_path):
    """An upstream left out is not waited for; kg transform then requires its completed output."""
    phases, _ = phases_script.plan(["mediadive", "bactotraits", "bacdive"], input_dir=tmp_path)
    assert phases == [["bacdive"], ["mediadive", "bactotraits"]]
    assert phases_script.plan(["bactotraits", "bactotraits"], input_dir=tmp_path)[0] == [["bactotraits"]]


def test_an_unknown_source_is_refused(tmp_path, capsys):
    """A retired or misspelled name fails the plan instead of becoming a task that does nothing."""
    with pytest.raises(ValueError, match="Unknown transform source"):
        phases_script.plan(["uniprot_human"], input_dir=tmp_path)
    assert phases_script.main(["-i", str(tmp_path), "-s", "ctd"]) == 2
    assert "Unknown transform source(s): ctd" in capsys.readouterr().err


def test_a_single_ontology_is_refused_with_its_reason(tmp_path):
    """It withdraws the ontologies marker, so it never runs beside readers of that output (#1660)."""
    with pytest.raises(ValueError, match="Single ontologies are not planned: go"):
        phases_script.plan(["go", "bacdive"], input_dir=tmp_path)


def test_a_cycle_is_refused(monkeypatch, tmp_path):
    """Two sources that read each other cannot be phased."""

    class Source:
        """A registry entry that declares only its upstreams."""

        def __init__(self, *upstream):
            """Declare ``upstream`` as TRANSFORM_INPUTS."""
            self.TRANSFORM_INPUTS = upstream

    monkeypatch.setattr(dispatcher, "DATA_SOURCES", {"a": Source("b"), "b": Source("a"), "c": Source()})
    monkeypatch.setattr(dispatcher, "EXPLICIT_ONLY_SOURCES", frozenset())
    with pytest.raises(ValueError, match="cycle among: a, b"):
        phases_script.plan(input_dir=tmp_path)


def test_the_cli_prints_one_line_per_phase(tmp_path, capsys):
    """The driver reads one phase per line, sources separated by spaces."""
    assert phases_script.main(["-i", str(tmp_path), "-s", "bacdive", "-s", "bactotraits"]) == 0
    assert capsys.readouterr().out == "bacdive\nbactotraits\n"


def _stub(bin_dir, name, body):
    """Write an executable stub for a cluster command."""
    path = bin_dir / name
    path.write_text("#!/bin/bash\n" + body + "\n", encoding="utf-8")
    path.chmod(0o755)


@needs_bash
def test_the_driver_chains_each_phase_on_the_previous_one(tmp_path):
    """Phase N+1 is submitted with afterok on phase N's job, its array sized to its sources."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "sbatch.log"
    _stub(bin_dir, "sbatch", f'echo "$*" >> {log}\necho "$((100 + $(wc -l < {log})));cluster"')
    env = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "KG_PYTHON": f"{sys.executable} -W ignore",
        "PYTHONPATH": str(REPO),
    }
    result = subprocess.run(  # noqa: S603 - bash and the scripts are fixed repository paths
        [BASH, str(REPO / "hpc" / "submit_phased_transforms.sh"), "-s", "bacdive", "-s", "mediadive"],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    first, second = log.read_text().splitlines()
    assert first.endswith("--array=0-0 --job-name=transforms_phase_0 hpc/run_parallel_transform.slurm bacdive")
    assert "--dependency=afterok:101 --kill-on-invalid-dep=yes" in second
    assert second.endswith("hpc/run_parallel_transform.slurm mediadive")
    assert f"--chdir={REPO}" in first
    assert "phase 1: job 102: mediadive" in result.stdout


@needs_bash
def test_the_driver_refuses_what_it_cannot_plan(tmp_path):
    """An unknown source or another argument stops before anything is submitted."""
    env = {**os.environ, "KG_PYTHON": f"{sys.executable} -W ignore", "PYTHONPATH": str(REPO), "DRY_RUN": "1"}
    script = str(REPO / "hpc" / "submit_phased_transforms.sh")
    unknown = subprocess.run([BASH, script, "-s", "wallen_etal"], env=env, capture_output=True, text=True)  # noqa: S603 - fixed repository script
    assert unknown.returncode != 0 and "Unknown transform source(s): wallen_etal" in unknown.stderr
    other = subprocess.run([BASH, script, "-i", "elsewhere"], env=env, capture_output=True, text=True)  # noqa: S603 - fixed repository script
    assert other.returncode == 2 and not other.stdout


@needs_bash
@pytest.mark.parametrize("task, expected", [("1", "run kg transform -s mediadive"), ("2", None), ("", None)])
def test_each_array_task_runs_the_source_it_is_given(tmp_path, task, expected):
    """The job script holds no list of its own; task N runs the Nth source it was passed."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in ("module", "conda"):
        _stub(bin_dir, name, "exit 0")
    _stub(bin_dir, "poetry", f'echo "$*" > {tmp_path / "poetry.log"}')
    env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}", "SLURM_ARRAY_TASK_ID": task}
    result = subprocess.run(  # noqa: S603 - bash and the scripts are fixed repository paths
        [BASH, str(REPO / "hpc" / "run_parallel_transform.slurm"), "bacdive", "mediadive"],
        env=env,
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )
    if expected is None:
        assert result.returncode == 2 and not (tmp_path / "poetry.log").exists()
    else:
        assert result.returncode == 0
        assert (tmp_path / "poetry.log").read_text().strip() == expected


def test_the_job_script_names_no_source_of_its_own():
    """The old fixed list named five unregistered sources and ran dependents beside upstreams (#1567)."""
    script = (REPO / "hpc" / "run_parallel_transform.slurm").read_text(encoding="utf-8")
    assert "transforms=(" not in script and "--array" not in script.split("# One phase")[0]
    for retired in ("uniprot_human", "ctd", "disbiome", "wallen_etal", "uniprot_functional_microbes"):
        assert retired not in script
