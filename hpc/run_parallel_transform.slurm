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
#SBATCH --array=0-10
#SBATCH -N 1

export ROBOT_JAVA_ARGS="-Xmx64g -XX:+UseG1GC"
export JAVA_OPT="-Xmx64g -XX:+UseG1GC"

module use /global/common/software/m4689/public/modulefiles
module load sqlite3/3460000

conda activate kg-microbe
cd kg-microbe

# Array of transform names
transforms=(
    ontologies
    bacdive
    mediadive
    madin_etal
    rhea_mappings
    bactotraits
    uniprot_human
    ctd
    disbiome
    wallen_etal
    uniprot_functional_microbes
)

# Get the transform for this job array task
transform=${transforms[$SLURM_ARRAY_TASK_ID]}

echo "Starting $transform"
time poetry run kg transform -s $transform
echo "Finished $transform"
