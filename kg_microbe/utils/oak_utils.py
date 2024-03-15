# Description: This file contains utility functions for the OAK client.

def get_label(oi, curie: str):
    prefix = curie.split(":")[0]
    (_, label) = list(oi.labels([curie]))[0]
    return label