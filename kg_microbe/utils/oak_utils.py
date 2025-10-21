"""Description: This file contains utility functions for the OAK client."""


def get_label(oi, curie: str):
    """Return the label of a given curie via oaklib."""
    try:
        (_, label) = list(oi.labels([curie]))[0]
        return label
    except Exception as e:
        print(f"Warning: Could not get label for {curie}: {e}")
        # Return the curie without prefix as fallback
        return curie.split(":")[-1] if ":" in curie else curie
