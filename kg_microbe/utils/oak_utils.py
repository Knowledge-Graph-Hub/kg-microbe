"""Description: This file contains utility functions for the OAK client."""


def get_label(oi, curie: str):
    """Return the label of a given curie via oaklib."""
    (_, label) = list(oi.labels([curie]))[0]
    return label