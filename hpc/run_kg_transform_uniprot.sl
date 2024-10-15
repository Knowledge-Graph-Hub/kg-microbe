#!/bin/bash
#SBATCH --account=m4689
#SBATCH --qos=shared
#SBATCH --constraint=cpu
#SBATCH --time=360
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --mem=230GB
#SBATCH --output=%j.out
#SBATCH --error=%j.err

module load python/3.10
cd /global/cfs/cdirs/m4689/master/kg-microbe
source venv/bin/activate
git checkout master
poetry run kg transform -s uniprot_functional_microbes
