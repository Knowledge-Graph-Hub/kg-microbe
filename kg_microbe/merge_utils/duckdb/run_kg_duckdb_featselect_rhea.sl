#!/bin/bash
#SBATCH --account=kbase
#SBATCH --qos=shared
#SBATCH --constraint=cpu
#SBATCH --time=120
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --mem=230GB
#SBATCH --output=%j.out
#SBATCH --error=%j.err

/global/homes/m/marcinj/common/duckdb -init duckdb_select_genome_feat_rhea.sql
