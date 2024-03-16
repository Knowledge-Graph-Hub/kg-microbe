"""Description: This file contains utility functions for the OAK client."""


import csv
from pathlib import Path
from typing import Union

from kg_microbe.transform_utils.transform import Transform


def get_label(oi, curie: str):
    """Return the label of a given curie via oaklib."""
    (_, label) = list(oi.labels([curie]))[0]
    return label