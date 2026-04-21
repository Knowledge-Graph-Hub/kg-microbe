"""Shared METPO predicate → biolink predicate mapping."""

from kg_microbe.transform_utils.constants import BIOLOGICAL_PROCESS, HAS_PHENOTYPE

# METPO predicate -> biolink predicate (for relation lookup)
METPO_TO_BIOLINK_PREDICATE = {
    # Capability and phenotype
    "METPO:2000101": "biolink:has_attribute",  # has quality
    "METPO:2000102": "biolink:has_phenotype",  # has phenotype
    "METPO:2000103": "biolink:capable_of",  # capable of
    # Chemical interactions (positive)
    "METPO:2000001": "biolink:interacts_with",  # organism interacts with chemical
    "METPO:2000002": "biolink:interacts_with",  # assimilates
    "METPO:2000003": "biolink:produces",  # builds acid from
    "METPO:2000004": "biolink:produces",  # builds base from
    "METPO:2000005": "biolink:produces",  # builds gas from
    "METPO:2000006": "biolink:capable_of",  # uses as carbon source
    "METPO:2000007": "biolink:capable_of",  # degrades
    "METPO:2000008": "biolink:capable_of",  # uses as electron acceptor
    "METPO:2000009": "biolink:capable_of",  # uses as electron donor
    "METPO:2000010": "biolink:capable_of",  # uses as energy source
    "METPO:2000011": "biolink:capable_of",  # ferments
    "METPO:2000012": "biolink:capable_of",  # uses for growth
    "METPO:2000013": "biolink:capable_of",  # hydrolyzes
    "METPO:2000014": "biolink:capable_of",  # uses as nitrogen source
    "METPO:2000015": "biolink:interacts_with",  # uses in other way
    "METPO:2000016": "biolink:capable_of",  # oxidizes
    "METPO:2000017": "biolink:capable_of",  # reduces
    "METPO:2000018": "biolink:capable_of",  # requires for growth
    "METPO:2000019": "biolink:capable_of",  # uses for respiration
    "METPO:2000020": "biolink:capable_of",  # uses as sulfur source
    # Aerobic/anaerobic catabolization and growth (positive)
    "METPO:2000032": "biolink:capable_of",  # uses for aerobic catabolization
    "METPO:2000043": "biolink:capable_of",  # uses for aerobic growth
    "METPO:2000048": "biolink:capable_of",  # uses for anaerobic catabolization
    "METPO:2000049": "biolink:capable_of",  # uses for anaerobic growth
    "METPO:2000051": "biolink:capable_of",  # uses for anaerobic growth with light
    # Chemical interactions (negative)
    "METPO:2000021": "biolink:capable_of",  # does not use for aerobic catabolization
    "METPO:2000022": "biolink:capable_of",  # does not use for aerobic growth
    "METPO:2000024": "biolink:capable_of",  # does not use for anaerobic growth
    "METPO:2000025": "biolink:capable_of",  # does not use for anaerobic growth in the dark
    "METPO:2000026": "biolink:capable_of",  # does not use for anaerobic growth with light
    "METPO:2000027": "biolink:interacts_with",  # does not assimilate
    "METPO:2000028": "biolink:produces",  # does not build acid from
    "METPO:2000029": "biolink:produces",  # does not build base from
    "METPO:2000030": "biolink:produces",  # does not build gas from
    "METPO:2000031": "biolink:capable_of",  # does not use as carbon source
    "METPO:2000033": "biolink:capable_of",  # does not degrade
    "METPO:2000034": "biolink:capable_of",  # does not use as electron acceptor
    "METPO:2000035": "biolink:capable_of",  # does not use as electron donor
    "METPO:2000036": "biolink:capable_of",  # does not use as energy source
    "METPO:2000037": "biolink:capable_of",  # does not ferment
    "METPO:2000038": "biolink:capable_of",  # does not use for growth
    "METPO:2000039": "biolink:capable_of",  # does not hydrolyze
    "METPO:2000040": "biolink:capable_of",  # does not use as nitrogen source
    "METPO:2000041": "biolink:interacts_with",  # does not use in other way
    "METPO:2000042": "biolink:capable_of",  # does not oxidize
    "METPO:2000044": "biolink:capable_of",  # does not reduce
    "METPO:2000045": "biolink:capable_of",  # is not required for growth
    "METPO:2000046": "biolink:capable_of",  # does not use for respiration
    "METPO:2000047": "biolink:capable_of",  # does not use as sulfur source
    # Production
    "METPO:2000202": "biolink:produces",  # produces
    "METPO:2000222": "biolink:produces",  # does not produce
    # Enzyme activity
    "METPO:2000302": "biolink:capable_of",  # shows activity of
    "METPO:2000303": "biolink:capable_of",  # does not show activity of
    # Growth medium
    "METPO:2000517": "biolink:capable_of",  # grows in
    "METPO:2000518": "biolink:capable_of",  # does not grow in
    # Nitrogen / redox processes
    "METPO:2000601": "biolink:capable_of",  # denitrifies
    "METPO:2000602": "biolink:capable_of",  # does not denitrify
    "METPO:2000603": "biolink:capable_of",  # ammonifies
    "METPO:2000604": "biolink:capable_of",  # does not ammonify
    "METPO:2000605": "biolink:capable_of",  # oxidizes in darkness
    "METPO:2000606": "biolink:capable_of",  # does not oxidize in darkness
}

# Biolink predicate -> RO relation
PREDICATE_TO_RELATION = {
    "biolink:produces": "RO:0002234",  # has output
    "biolink:capable_of": BIOLOGICAL_PROCESS,  # RO:0002215
    "biolink:has_phenotype": HAS_PHENOTYPE,  # RO:0002200
    "biolink:has_attribute": "RO:0000086",  # has quality
    "biolink:interacts_with": "RO:0002434",  # interacts with
    "biolink:consumes": "RO:0002233",  # has input
    "biolink:located_in": "RO:0001025",  # located in
    "biolink:related_to": "RO:0000091",  # has disposition (generic fallback)
    "biolink:associated_with": "RO:0000091",
}


def to_biolink_predicate(predicate: str) -> str:
    """Map METPO or other predicate to biolink predicate; pass through biolink predicates unchanged."""
    if predicate.startswith("biolink:"):
        return predicate
    return METPO_TO_BIOLINK_PREDICATE.get(predicate, "biolink:has_phenotype")
