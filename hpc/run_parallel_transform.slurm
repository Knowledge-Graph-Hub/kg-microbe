#!/bin/bash
#SBATCH --account=m4689
#SBATCH --qos=regular
#SBATCH --constraint=cpu
#SBATCH --time=360
#SBATCH --ntasks=1
#SBATCH --mem=425GB
#SBATCH --job-name=parallel_transforms
#SBATCH --output=parallel_transforms_%A_%a.out
#SBATCH --error=parallel_transforms_%A_%a.err
#SBATCH -N 1

# One phase of a parallel transform, one source per array task (#1567).
# Submit through hpc/submit_phased_transforms.sh, which plans the phases from
# each source's TRANSFORM_INPUTS, passes the phase's sources as arguments, sets
# --array to match and starts each phase only after the previous one succeeded.
# Sources in one phase never read each other's output.

export ROBOT_JAVA_ARGS="-Xmx64g -XX:+UseG1GC"
export JAVA_OPT="-Xmx64g -XX:+UseG1GC"

module use /global/common/software/m4689/public/modulefiles
module load sqlite3/3460000

conda activate kg-microbe

if [ "$#" -eq 0 ] || [ -z "${SLURM_ARRAY_TASK_ID:-}" ]; then
    echo "usage: submit through hpc/submit_phased_transforms.sh (sources as arguments, one per array task)" >&2
    exit 2
fi
sources=("$@")
transform=${sources[$SLURM_ARRAY_TASK_ID]:-}
if [ -z "$transform" ]; then
    echo "array task $SLURM_ARRAY_TASK_ID has no source; this phase has ${#sources[@]}" >&2
    exit 2
fi

echo "Starting $transform"
time poetry run kg transform -s "$transform"
echo "Finished $transform"
