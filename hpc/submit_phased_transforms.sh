#!/bin/bash
# Submit a parallel transform as one Slurm array job per dependency phase (#1567).
#
# scripts/transform_phases.py groups the sources by TRANSFORM_INPUTS, so each
# phase reads only outputs that earlier phases wrote. Phase N+1 starts only if
# every task of phase N succeeded (afterok); kg transform would refuse it anyway
# without completed upstream outputs, and this way it never reads a partial one.
# Each job runs `kg transform -s <source>` from the repository root, so it reads
# data/raw there, and the plan is made against that same directory.
#
# Usage, from anywhere: hpc/submit_phased_transforms.sh [-s SOURCE ...]
# With no -s, the default `kg transform` batch is planned.
# DRY_RUN=1 prints the sbatch commands instead of submitting.
set -euo pipefail

repo=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$repo"
selection=()
while [ "$#" -gt 0 ]; do
    if [ "$1" = "-s" ] && [ "$#" -ge 2 ]; then
        selection+=(-s "$2")
        shift 2
    else
        echo "usage: $0 [-s SOURCE ...]" >&2
        exit 2
    fi
done
read -r -a planner <<<"${KG_PYTHON:-poetry run python}"
plan=$("${planner[@]}" scripts/transform_phases.py --input-dir data/raw ${selection[@]+"${selection[@]}"})
phases=()
while IFS= read -r line; do
    [ -n "$line" ] && phases+=("$line")
done <<<"$plan"
if [ "${#phases[@]}" -eq 0 ]; then
    echo "no sources to run" >&2
    exit 1
fi

previous=""
for index in "${!phases[@]}"; do
    read -r -a sources <<<"${phases[$index]}"
    command=(sbatch --parsable --chdir="$repo" --array="0-$((${#sources[@]} - 1))" --job-name="transforms_phase_$index")
    if [ -n "$previous" ]; then
        command+=(--dependency="afterok:$previous" --kill-on-invalid-dep=yes)
    fi
    command+=(hpc/run_parallel_transform.slurm "${sources[@]}")
    if [ -n "${DRY_RUN:-}" ]; then
        echo "${command[*]}"
        previous="PHASE_${index}_JOB"
    else
        previous=$("${command[@]}")
        previous=${previous%%;*}
        echo "phase $index: job $previous: ${sources[*]}"
    fi
done
