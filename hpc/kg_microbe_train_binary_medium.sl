#!/bin/bash
#SBATCH --account=m4689
#SBATCH --qos=regular
#SBATCH --constraint=cpu
#SBATCH --time=180
#SBATCH --ntasks=20
#SBATCH --mem=128G
#SBATCH --array=0-19
#SBATCH --output=%A_%a.out
#SBATCH --error=%A_%a.err

# Load any necessary modules (e.g., Python)
module load python/3.10

source ../venv/bin/activate

# Define the values
values=(
    "65"
    "514"
    "693"
    "830"
    "92"
    "11"
    "104"
    "645"
    "1a"
    "545"
    "58"
    "215"
    "110"
    "553"
    "372"
    "J14"
    "830c"
    "1076b"
    "381"
    "98"
)


# Get the value for this array task
value=${values[$SLURM_ARRAY_TASK_ID]}

# Run the Python script with the selected value
time python kg_microbe_train_binary_medium.py "$value"
