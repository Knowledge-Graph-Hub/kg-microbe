#!/usr/bin/env python3
"""Helper script for kg-query skill."""

import subprocess
import sys


def main():
    """Execute kg query-organism command with provided arguments."""
    if len(sys.argv) < 2:
        print("Usage: query_organism.py <organism_name>")
        sys.exit(1)

    organism = " ".join(sys.argv[1:])
    cmd = ["poetry", "run", "kg", "query-organism", organism]
    result = subprocess.run(cmd, capture_output=False)
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
