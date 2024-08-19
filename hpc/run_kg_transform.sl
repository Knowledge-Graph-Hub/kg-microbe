#!/bin/bash
#SBATCH --account=m4689
#SBATCH --qos=regular
#SBATCH --constraint=cpu
#SBATCH --time=360
#SBATCH --mem=420GB
#SBATCH --ntasks=1
#SBATCH -N 1
#SBATCH --output=%j.out
#SBATCH --error=%j.err

module load python/3.10
cd /global/cfs/cdirs/m4689/master/kg-microbe
source venv/bin/activate
git checkout master
time poetry run kg transform
