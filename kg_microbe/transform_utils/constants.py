"""Constants for transform_utilities."""

import re
from pathlib import Path

# Source Names
MADIN_ETAL = "madin_etal"
BACDIVE = "bacdive"
MEDIADIVE = "mediadive"
BACTOTRAITS = "bactotraits"
RHEAMAPPINGS = "rhea_mappings"
ONTOLOGIES = "ontologies"
WALLEN_ETAL = "wallen_etal"
CTD = "ctd"
DISBIOME = "disbiome"
UNIPROT_FUNCTIONAL_MICROBES = "uniprot_functional_microbes"
UNIPROT_HUMAN = "uniprot_human"

TRANSFORM_UTILS_DIR = Path(__file__).parent
BACDIVE_DIR = TRANSFORM_UTILS_DIR / BACDIVE
BACDIVE_TMP_DIR = BACDIVE_DIR / "tmp"
BACDIVE_YAML_DIR = BACDIVE_TMP_DIR / "yaml"
MEDIADIVE_DIR = TRANSFORM_UTILS_DIR / MEDIADIVE
MEDIADIVE_TMP_DIR = MEDIADIVE_DIR / "tmp"
MEDIADIVE_MEDIUM_YAML_DIR = MEDIADIVE_TMP_DIR / "medium_yaml"
MEDIADIVE_MEDIUM_STRAIN_YAML_DIR = MEDIADIVE_TMP_DIR / "medium_strain_yaml"
MADIN_ETAL_DIR = TRANSFORM_UTILS_DIR / MADIN_ETAL
RAW_DATA_DIR = Path(__file__).parents[2] / "data" / "raw"
RHEAMAPPINGS_DIR: Path = TRANSFORM_UTILS_DIR / RHEAMAPPINGS
RHEAMAPPINGS_TMP_DIR = RHEAMAPPINGS_DIR / "tmp"
BACTOTRAITS_DIR = TRANSFORM_UTILS_DIR / "bactotraits"
BACTOTRAITS_TMP_DIR = BACTOTRAITS_DIR / "tmp"
UNIPROT_TREMBL_DIR = TRANSFORM_UTILS_DIR / "uniprot_trembl"
UNIPROT_TREMBL_TMP_DIR = UNIPROT_TREMBL_DIR / "tmp"
ONTOLOGIES_DIR = TRANSFORM_UTILS_DIR / ONTOLOGIES
ONTOLOGIES_XREFS_DIR = ONTOLOGIES_DIR / "xrefs"
ONTOLOGIES_TREES_DIR = ONTOLOGIES_DIR / "trees"
CHEBI_XREFS_FILEPATH = ONTOLOGIES_XREFS_DIR / "chebi_xrefs.tsv"
MONDO_XREFS_FILEPATH = ONTOLOGIES_XREFS_DIR / "mondo_xrefs.tsv"
MONDO_GENE_IDS_FILEPATH = ONTOLOGIES_XREFS_DIR / "mondo_gene_ids.tsv"
CUSTOM_CURIES_YAML_FILE = TRANSFORM_UTILS_DIR / "custom_curies.yaml"
NCBITAXON_SOURCE = RAW_DATA_DIR / "ncbitaxon.owl"
CHEBI_SOURCE = RAW_DATA_DIR / "chebi.owl"
GO_SOURCE = RAW_DATA_DIR / "go.owl"
EC_SOURCE = RAW_DATA_DIR / "ec.owl"
METABOLITE_MAPPING_FILE = BACDIVE_DIR / "metabolite_mapping.json"

# KEYS FOR JSON FILE
GENERAL = "General"
BACDIVE_ID = "BacDive-ID"
KEYWORDS = "keywords"
GENERAL_DESCRIPTION = "description"
NCBITAXON_ID = "NCBI tax id"
MATCHING_LEVEL = "Matching level"
SPECIES = "species"
STRAIN = "strain"
DOI = "doi"
DSM_NUMBER = "DSM-Number"

NAME_TAX_CLASSIFICATION = "Name and taxonomic classification"
MORPHOLOGY = "Morphology"
DOMAIN = "domain"
PHYLUM = "phylum"
CLASS = "class"
ORDER = "order"
FAMILY = "family"
GENUS = "genus"
FULL_SCIENTIFIC_NAME = "full scientific name"
STRAIN_DESIGNATION = "strain designation"
TYPE_STRAIN = "type strain"
LPSN = "LPSN"
SYNONYMS = "synonyms"
SYNONYM = "synonym"

CULTURE_AND_GROWTH_CONDITIONS = "Culture and growth conditions"
CULTURE_MEDIUM = "culture medium"
CULTURE_COMPOSITION = "composition"
CULTURE_GROWTH = "growth"
CULTURE_LINK = "link"
CULTURE_NAME = "name"
CULTURE_TEMP = "culture temp"
CULTURE_TEMP_GROWTH = "growth"
CULTURE_TEMP_TYPE = "type"
CULTURE_TEMP_TEMP = "temperature"
CULTURE_TEMP_RANGE = "range"

PHYSIOLOGY_AND_METABOLISM = "Physiology and metabolism"
ISOLATION_SAMPLING_ENV_INFO = "Isolation, sampling and environmental information"
SAFETY_INFO = "Safety information"
SEQUENCE_INFO = "Sequence information"
RISK_ASSESSMENT = "risk assessment"
BIOSAFETY_LEVEL = "biosafety level"
OBSERVATION = "observation"
MULTIMEDIA = "multimedia"
MULTICELLULAR_MORPHOLOGY = "multicellular morphology"
COLONY_MORPHOLOGY = "colony morphology"
CELL_MORPHOLOGY = "cell morphology"
PIGMENTATION = "pigmentation"
ENZYMES = "enzymes"
METABOLITE_UTILIZATION = "metabolite utilization"
METABOLITE_PRODUCTION = "metabolite production"
METABOLITE_TESTS = "metabolite tests"
OXYGEN_TOLERANCE = "oxygen tolerance"
SPORE_FORMATION = "spore formation"
HALOPHILY = "halophily"
ANTIBIOTIC_RESISTANCE = "antibiotic resistance"
MUREIN = "murein"
COMPOUND_PRODUCTION = "compound production"
FATTY_ACID_PROFILE = "fatty acid profile"
TOLERANCE = "tolerance"
ANTIBIOGRAM = "antibiogram"
NUTRITION_TYPE = "nutrition type"
ISOLATION = "isolation"
ISOLATION_SOURCE_CATEGORIES = "isolation source categories"

DATA_KEY = "data"

RECIPE_KEY = "recipe"
COMPOUND_KEY = "compound"
COMPOUND_ID_KEY = "compound_id"
SOLUTION_KEY = "solution"
SOLUTIONS_KEY = "solutions"
SOLUTION_ID_KEY = "solution_id"
INGREDIENT_KEY = "ingredient_key"
INGREDIENT_ID_KEY = "ingredient_id_key"
CHEBI_KEY = "ChEBI"
CAS_RN_KEY = "CAS-RN"
KEGG_KEY = "KEGG-Compound"
PUBCHEM_KEY = "PubChem"
ACTUAL_TERM_KEY = "ActualTerm"
PREFERRED_TERM_KEY = "PreferredTerm"

ACCESSIONS_KEY = "accessions"
FILENAME_KEY = "file_name"

MEDIUM_KEY = "medium"

EXTERNAL_LINKS = "External links"
EXTERNAL_LINKS_CULTURE_NUMBER = "culture collection no."
REF = "Reference"
NCBITAXON_PREFIX = "NCBITaxon:"
BACDIVE_PREFIX = "bacdive:"
STRAIN_PREFIX = "strain:"
CHEBI_PREFIX = "CHEBI:"
CAS_RN_PREFIX = "CAS-RN:"
PUBCHEM_PREFIX = "PubChem:"
UBERON_PREFIX = "UBERON:"
RO_PREFIX = "RO:"
MEDIADIVE_INGREDIENT_PREFIX = "ingredient:"
MEDIADIVE_SOLUTION_PREFIX = "solution:"
MEDIADIVE_MEDIUM_PREFIX = "medium:"
MEDIADIVE_MEDIUM_TYPE_PREFIX = "medium-type:"
GO_PREFIX = "GO:"
KEGG_PREFIX = "KEGG:"
SHAPE_PREFIX = "cell_shape:"
PATHWAY_PREFIX = "pathways:"
CARBON_SUBSTRATE_PREFIX = "carbon_substrates:"
ISOLATION_SOURCE_PREFIX = "isolation_source:"
RHEA_OLD_PREFIX = "OBO:rhea_"
RHEA_NEW_PREFIX = "RHEA:"
ASSAY_PREFIX = "assay:"
RHEA_URI = "http://purl.obolibrary.org/obo/rhea_"
DEBIO_OBO_PREFIX = "OBO:debio_"
DEBIO_NEW_PREFIX = "debio:"
DEBIO_URI = "http://purl.obolibrary.org/obo/debio_"
RHEA_OBO_PREFIX = "OBO:rhea_"
MEDIADIVE_REST_API_BASE_URL = "https://mediadive.dsmz.de/rest/"
BACDIVE_API_BASE_URL = "https://bacmedia.dsmz.de/"
BIOSAFETY_LEVEL_PREFIX = "BSL:"

MEDIADIVE_MEDIUM_TYPE_COMPLEX_ID = MEDIADIVE_MEDIUM_TYPE_PREFIX + "complex"
MEDIADIVE_MEDIUM_TYPE_COMPLEX_LABEL = "Complex Medium"
MEDIADIVE_MEDIUM_TYPE_DEFINED_ID = MEDIADIVE_MEDIUM_TYPE_PREFIX + "defined"
MEDIADIVE_MEDIUM_TYPE_DEFINED_LABEL = "Defined Medium"

MEDIUM = "medium/"
COMPOUND = "ingredient/"
SOLUTION = "solution/"
MEDIUM_STRAINS = "medium-strains/"

BACDIVE_MEDIUM_DICT = {MEDIADIVE_MEDIUM_PREFIX: BACDIVE_API_BASE_URL + MEDIUM}

NCBI_TO_MEDIUM_EDGE = "biolink:occurs_in"
MEDIUM_TO_NCBI_EDGE = "biolink:contains_process"
MEDIUM_TO_INGREDIENT_EDGE = "biolink:has_part"  # Could also be has_constituent/has_participant
MEDIUM_TO_SOLUTION_EDGE = "biolink:has_part"
NCBI_TO_SHAPE_EDGE = "biolink:has_phenotype"  # [org_name -> cell_shape, metabolism]
NCBI_TO_CARBON_SUBSTRATE_EDGE = "biolink:consumes"  # [org_name -> carbon_substrate]
NCBI_TO_ISOLATION_SOURCE_EDGE = "biolink:location_of"  # [org -> isolation_source]
NCBI_TO_METABOLISM_EDGE = "biolink:has_phenotype"  # [org -> metabolism]
NCBI_TO_PATHWAY_EDGE = "biolink:capable_of"  # # [org -> pathway]
CHEBI_TO_ROLE_EDGE = "biolink:has_chemical_role"
NCBI_TO_METABOLITE_UTILIZATION_EDGE = "biolink:consumes"  # [org -> metabolite_utilization]
NCBI_TO_ENZYME_EDGE = "biolink:capable_of"  # [org -> enzyme]
ASSAY_TO_NCBI_EDGE = "biolink:assesses"  # [org -> assay]
MEDIUM_TO_METABOLITE_EDGE = "biolink:assesses"  # [org -> assay]
NCBI_TO_ASSAY_EDGE = "biolink:is_assessed_by"  # [org -> assay]
NCBI_TO_METABOLITE_PRODUCTION_EDGE = "biolink:produces"
ENZYME_TO_ASSAY_EDGE = "biolink:is_assessed_by"  # [enzyme -> assay]
SUBSTRATE_TO_ASSAY_EDGE = "biolink:occurs_in"  # [substrate -> assay]
ENZYME_TO_SUBSTRATE_EDGE = "biolink:consumes"  # [substrate -> enzyme]
NCBI_TO_SUBSTRATE_EDGE = "biolink:consumes"
RHEA_TO_EC_EDGE = "biolink:enabled_by"
RHEA_TO_GO_EDGE = "biolink:enables"
NCBI_TO_METABOLITE_RESISTANCE_EDGE = "biolink:associated_with_resistance_to"
NCBI_TO_METABOLITE_SENSITIVITY_EDGE = "biolink:associated_with_sensitivity_to"

NCBI_CATEGORY = "biolink:OrganismTaxon"
MEDIUM_CATEGORY = "biolink:ChemicalEntity"
MEDIUM_TYPE_CATEGORY = "biolink:ChemicalMixture"
SOLUTION_CATEGORY = "biolink:ChemicalEntity"
INGREDIENT_CATEGORY = "biolink:ChemicalEntity"
METABOLISM_CATEGORY = "biolink:ActivityAndBehavior"
PATHWAY_CATEGORY = "biolink:BiologicalProcess"
CARBON_SUBSTRATE_CATEGORY = "biolink:ChemicalEntity"
ROLE_CATEGORY = "biolink:ChemicalRole"
ENVIRONMENT_CATEGORY = "biolink:EnvironmentalFeature"  # "ENVO:01000254"
PHENOTYPIC_CATEGORY = "biolink:PhenotypicQuality"
ATTRIBUTE_CATEGORY = "biolink:Attribute"
METABOLITE_CATEGORY = "biolink:ChemicalEntity"
SUBSTRATE_CATEGORY = "biolink:ChemicalEntity"
BIOSAFETY_CATEGORY = "biolink:Attribute"

HAS_PART = "BFO:0000051"
IS_GROWN_IN = "BAO:0002924"
HAS_PHENOTYPE = "RO:0002200"  # [org_name -> has phenotype -> cell_shape, metabolism]
TROPHICALLY_INTERACTS_WITH = (
    "RO:0002438"  # [org_name -> 'trophically interacts with' -> carbon_substrate]
)
LOCATION_OF = "RO:0001015"  # [org -> location_of -> source]
BIOLOGICAL_PROCESS = "RO:0002215"  # [org -> biological_process -> metabolism]
HAS_ROLE = "RO:0000087"
HAS_PARTICIPANT = "RO:0000057"
PARTICIPATES_IN = "RO:0000056"
ASSESSED_ACTIVITY_RELATIONSHIP = "NCIT:C153110"
CLOSE_MATCH = "skos:closeMatch"
EXACT_MATCH = "skos:exactMatch"
ASSOCIATED_WITH = "PATO:0001668"

ID_COLUMN = "id"
NAME_COLUMN = "name"
CATEGORY_COLUMN = "category"
SUBJECT_COLUMN = "subject"
PREDICATE_COLUMN = "predicate"
OBJECT_COLUMN = "object"
RELATION_COLUMN = "relation"
PROVIDED_BY_COLUMN = "provided_by"
PRIMARY_KNOWLEDGE_SOURCE_COLUMN = "primary_knowledge_source"
DESCRIPTION_COLUMN = "description"
XREF_COLUMN = "xref"
SYNONYM_COLUMN = "synonym"
IRI_COLUMN = "iri"
SAME_AS_COLUMN = "same_as"
SUBSETS_COLUMN = "subsets"
AMOUNT_COLUMN = "amount"
UNIT_COLUMN = "unit"
GRAMS_PER_LITER_COLUMN = "g_l"
MMOL_PER_LITER_COLUMN = "mmol_l"
RISK_ASSESSMENT_COLUMN = RISK_ASSESSMENT
CURIE_COLUMN = "curie"

BACDIVE_ID_COLUMN = "bacdive_id"
DSM_NUMBER_COLUMN = "dsm_number"
EXTERNAL_LINKS_CULTURE_NUMBER_COLUMN = "culture_collection_number"
NCBITAXON_ID_COLUMN = "ncbitaxon_id"
NCBITAXON_DESCRIPTION_COLUMN = "ncbitaxon_description"
KEYWORDS_COLUMN = "keywords"
MEDIUM_ID_COLUMN = "medium_id"
MEDIUM_LABEL_COLUMN = "medium_label"
MEDIUM_URL_COLUMN = "medium_url"
MEDIADIVE_URL_COLUMN = "mediadive_medium_url"
SOLUTIONS_COLUMN = "solutions"
INGREDIENTS_COLUMN = "ingredents"
ISOLATION_COLUMN = ISOLATION
ISOLATION_SOURCE_CATEGORIES_COLUMN = ISOLATION_SOURCE_CATEGORIES
# Morphology
MORPHOLOGY_MULTIMEDIA_COLUMN = MORPHOLOGY + "_" + MULTIMEDIA
MORPHOLOGY_MULTICELLULAR_MORPHOLOGY_COLUMN = MORPHOLOGY + "_" + MULTICELLULAR_MORPHOLOGY
MORPHOLOGY_COLONY_MORPHOLOGY_COLUMN = MORPHOLOGY + "_" + COLONY_MORPHOLOGY
MORPHOLOGY_CELL_MORPHOLOGY_COLUMN = MORPHOLOGY + "_" + CELL_MORPHOLOGY
MORPHOLOGY_PIGMENTATION_COLUMN = MORPHOLOGY + "_" + PIGMENTATION
API_X_COLUMN = "API_X"
METABOLITE_CHEBI_KEY = "Chebi-ID"
METABOLITE_KEY = "metabolite"
PRODUCTION_KEY = "production"
EC_PREFIX = "EC:"
EC_KEY = "ec"
EC_PYOBO_PREFIX = "eccode"
EC_OBO_PREFIX = "OBO:eccode_"
UNIPROT_OBO_PREFIX = "OBO:uniprot_"
CHEBI_CAS_PREFIX = "CAS:"
ACTIVITY_KEY = "activity"
RESISTANCE_KEY = "is resistant"
SENSITIVITY_KEY = "is sensitive"
UTILIZATION_TYPE_TESTED = "kind of utilization tested"
UTILIZATION_ACTIVITY = "utilization activity"
PLUS_SIGN = "+"
BACDIVE_MAPPING_PSEUDO_ID_COLUMN = "pseudo_CURIE"
BACDIVE_MAPPING_CHEBI_ID = "CHEBI_ID"
BACDIVE_MAPPING_KEGG_ID = "KEGG_ID"
BACDIVE_MAPPING_CAS_RN_ID = "CAS_RN_ID"
BACDIVE_MAPPING_EC_ID = "EC_ID"
BACDIVE_MAPPING_ENZYME_LABEL = "enzyme"
BACDIVE_MAPPING_SUBSTRATE_LABEL = "substrate"
BACDIVE_CULTURE_COLLECTION_NUMBER_COLUMN = "culture_collection_number"
BACDIVE_ENVIRONMENT_CATEGORY = "Cat"
ISOLATION_SOURCE_CATEGORY = "biolink:EnvironmentalFeature"
# ! Primary differenec between the 2 below is the first key-value pair.
# ! Whitespaces are fine for labels.
TRANSLATION_TABLE_FOR_IDS = {
    " ": "-",
    '"': "",
    "(": "",
    ")": "",
    "#": "",
    ";": "",
    "{": "",
    "}": "",
}
TRANSLATION_TABLE_FOR_LABELS = {'"': "", "(": "", ")": "", "#": "", ";": "", "{": "", "}": ""}

MEDIADIVE_ID_COLUMN = "mediadive_id"
MEDIADIVE_COMPLEX_MEDIUM_COLUMN = "complex_medium"
MEDIADIVE_SOURCE_COLUMN = "source"
MEDIADIVE_LINK_COLUMN = "link"
MEDIADIVE_MIN_PH_COLUMN = "min_pH"
MEDIADIVE_MAX_PH_COLUMN = "max_pH"
MEDIADIVE_REF_COLUMN = "reference"
MEDIADIVE_DESC_COLUMN = "description"

RHEA_ID_COLUMN = "id"
RHEA_NAME_COLUMN = "name"
RHEA_DIRECTION_COLUMN = "direction"
RHEA_MAPPING_ID_COLUMN = "RHEA_ID"
RHEA_MASTER_ID_COLUMN = "MASTER_ID"
RHEA_MAPPING_OBJECT_COLUMN = "ID"
RHEA_TARGET_ID_COLUMN = "target_id"
RHEA_SUBJECT_ID_COLUMN = "subject_id"
RHEA_UNDEFINED_DIRECTION = "undefined"
RHEA_BIDIRECTIONAL_DIRECTION = "bidirectional"
RHEA_LEFT_TO_RIGHT_DIRECTION = "left-to-right"
RHEA_RIGHT_TO_LEFT_DIRECTION = "right-to-left"
RHEA_CATEGORY_COLUMN = "category"
RHEA_CATEGORY = "biolink:MolecularActivity"
EC_CATEGORY = "biolink:MolecularActivity"
GO_CATEGORY = "biolink:BiologicalProcess"
RDFS_SUBCLASS_OF = "rdfs:subClassOf"
SUBCLASS_PREDICATE = "biolink:subclass_of"
SUPERCLASS_PREDICATE = "biolink:superclass_of"
CAPABLE_OF_PREDICATE = "biolink:capable_of"
PREDICATE_ID_COLUMN = "predicate_id"
PREDICATE_LABEL_COLUMN = "predicate_label"
DEBIO_MAPPER = {
    RHEA_LEFT_TO_RIGHT_DIRECTION: "debio:0000007",
    RHEA_RIGHT_TO_LEFT_DIRECTION: "debio:0000008",
    RHEA_BIDIRECTIONAL_DIRECTION: "debio:0000009",
}

BIOSAFETY_LEVEL_PREDICATE = "biolink:associated_with"
# DEBIO_PREDICATE_MAPPER = {
#     RHEA_LEFT_TO_RIGHT_DIRECTION: "biolink:is_input_of",
#     RHEA_RIGHT_TO_LEFT_DIRECTION: "biolink:is_output_of",
#     RHEA_BIDIRECTIONAL_DIRECTION: "biolink:participates_in",
# }
RHEA_DIRECTION_CATEGORY = "biolink:Activity"

# Traits
TAX_ID_COLUMN = "tax_id"
CARBON_SUBSTRATES_COLUMN = "carbon_substrates"
PATHWAYS_COLUMN = "pathways"
OBJECT_ID_COLUMN = "object_id"
OBJECT_LABEL_COLUMN = "object_label"
OBJECT_CATEGORIES_COLUMN = "object_categories"
OBJECT_ALIASES_COLUMN = "object_aliases"
MATCHES_WHOLE_TEXT_COLUMN = "matches_whole_text"
SUBJECT_LABEL_COLUMN = "subject_label"
START_COLUMN = "subject_start"
END_COLUMN = "subject_end"
TRAITS_DATASET_LABEL_COLUMN = "traits_dataset_term"
ORG_NAME_COLUMN = "org_name"
METABOLISM_COLUMN = "metabolism"
PATHWAYS_COLUMN = "pathways"
SHAPE_COLUMN = "shape"
CELL_SHAPE_COLUMN = "cell_shape"
ISOLATION_SOURCE_COLUMN = "isolation_source"
TYPE_COLUMN = "Type"
ENVO_TERMS_COLUMN = "ENVO_terms"
ENVO_ID_COLUMN = "ENVO_ids"
ACTION_COLUMN = "action"
REPLACEMENT = "REPLACE"
SUPPLEMENT = "SUPPLEMENT"

CHEBI_MANUAL_ANNOTATION_PATH = MADIN_ETAL_DIR / "chebi_manual_annotation.tsv"

# ROBOT
ROBOT_REMOVED_SUFFIX = "_removed_subset"
ROBOT_EXTRACT_SUFFIX = "_extract_subset"
EXCLUSION_TERMS_FILE = "exclusion_branches.tsv"

# Uniprot
UNIPROT_FUNCTIONAL_MICROBES_DIR = TRANSFORM_UTILS_DIR / UNIPROT_FUNCTIONAL_MICROBES
UNIPROT_FUNCTIONAL_MICROBES_TMP_DIR = UNIPROT_FUNCTIONAL_MICROBES_DIR / "tmp"
UNIPROT_FUNCTIONAL_MICROBES_RELEVANT_FILE_LIST = (
    UNIPROT_FUNCTIONAL_MICROBES_TMP_DIR / "relevant_files.tsv"
)
UNIPROT_FUNCTIONAL_MICROBES_TMP_NE_DIR = UNIPROT_FUNCTIONAL_MICROBES_TMP_DIR / "nodes_and_edges"

# UniprotHuman
UNIPROT_HUMAN_DIR = TRANSFORM_UTILS_DIR / "uniprot_human"
UNIPROT_HUMAN_TMP_DIR = UNIPROT_HUMAN_DIR / "tmp"
UNIPROT_HUMAN_RELEVANT_FILE_LIST = UNIPROT_HUMAN_TMP_DIR / "relevant_files.tsv"
UNIPROT_HUMAN_TMP_NE_DIR = UNIPROT_HUMAN_TMP_DIR / "nodes_and_edges"

# All Uniprot
UNIPROT_PROTEOMES_FILE = "uniprot_proteomes.tar.gz"
UNIPROT_HUMAN_FILE = "uniprot_human.tar.gz"
UNIPROT_S3_DIRECTORY = "s3"
GO_CATEGORY_TREES_FILE = ONTOLOGIES_TREES_DIR / "go_category_trees.tsv"

PROTEIN_CATEGORY = "biolink:Enzyme"
UNIPROT_FUNCTIONAL_MICROBES = "uniprot_functional_microbes"
UNIPROT_HUMAN = "uniprot_human"
ORGANISM_ID_MIXED_CASE = "Organism_ID"
TAXONOMY_ID_UNIPROT_PREFIX = "taxonomy_id:"
TAXONOMY_ID_UNIPROT_COLUMN = "taxonomy_id"
UNIPROT_ORG_ID_COLUMN_NAME = "Organism (ID)"
UNIPROT_PROTEIN_ID_COLUMN_NAME = "Entry"
UNIPROT_PROTEIN_NAME_COLUMN_NAME = "Protein names"
UNIPROT_EC_ID_COLUMN_NAME = "EC number"
UNIPROT_BINDING_SITE_COLUMN_NAME = "Binding site"
UNIPROT_GO_COLUMN_NAME = "Gene Ontology (GO)"
UNIPROT_RHEA_ID_COLUMN_NAME = "Rhea ID"
UNIPROT_PROTEOME_COLUMN_NAME = "Proteomes"
UNIPROT_DISEASE_COLUMN_NAME = "Involvement in disease"
UNIPROT_GENE_PRIMARY_COLUMN_NAME = "Gene Names (primary)"
UNIPROT_PREFIX = "UniprotKB:"
CHEMICAL_TO_PROTEIN_EDGE = "biolink:binds"
# PROTEIN_TO_GO_EDGE = "biolink:enables"
PROTEIN_TO_ORGANISM_EDGE = "biolink:derives_from"
ORGANISM_TO_PROTEIN_EDGE = "biolink:expresses"
PROTEIN_TO_EC_EDGE = "biolink:enables"
EC_CATEGORY = "biolink:Enzyme"
PROTEIN_TO_RHEA_EDGE = "biolink:participates_in"
RHEA_KEY = "rhea"
CHEMICAL_CATEGORY = "biolink:ChemicalSubstance"
CHEMICAL_TO_EC_EDGE = "biolink:participates_in"
GO_CELLULAR_COMPONENT_ID = "GO:0005575"
GO_MOLECULAR_FUNCTION_ID = "GO:0003674"
GO_BIOLOGICAL_PROCESS_ID = "GO:0008150"
GO_CELLULAR_COMPONENT_LABEL = "biolink:CellularComponent"
GO_MOLECULAR_FUNCTION_LABEL = "biolink:MolecularActivity"
GO_BIOLOGICAL_PROCESS_LABEL = "biolink:BiologicalProcess"
PROTEIN_TO_GO_CELLULAR_COMPONENT_EDGE = "biolink:located_in"
PROTEIN_TO_GO_MOLECULAR_FUNCTION_EDGE = "biolink:participates_in"
PROTEIN_TO_GO_BIOLOGICAL_PROCESS_EDGE = "biolink:participates_in"
DERIVES_FROM = "RO:0001000"
ENABLES = "RO:0002327"
MOLECULARLY_INTERACTS_WITH = "RO:0002436"
LOCATED_IN = "RO:0001025"
OMIM_PREFIX = "OMIM:"
DISEASE_CATEGORY = "biolink:Disease"
PROTEIN_TO_DISEASE_EDGE = "biolink:contributes_to"
CONTRIBUTES_TO = "RO:0002326"
GENE_TO_PROTEIN_EDGE = "biolink:has_gene_product"
HAS_GENE_PRODUCT = "RO:0002205"
GENE_CATEGORY = "biolink:Gene"

PROTEOME_ID_COLUMN = "proteome_id"
UNIPROT_DATA_LIST = [
    "archaea",
    "bacteria",
]

BACDIVE_MAPPING_FILE = "bacdive_mappings.tsv"


DO_NOT_CHANGE_PREFIXES = [
    NCBITAXON_PREFIX,
    CAS_RN_PREFIX,
    CHEBI_PREFIX,
    PUBCHEM_PREFIX,
    GO_PREFIX,
    KEGG_PREFIX,
    EC_PREFIX,
    UBERON_PREFIX,
    ASSAY_PREFIX,
    RHEA_NEW_PREFIX,
    GO_PREFIX,
    MEDIADIVE_MEDIUM_PREFIX,
    STRAIN_PREFIX,
    BIOSAFETY_LEVEL_PREFIX,
]

HAS_PARTICIPANT_PREDICATE = "biolink:has_participant"
ENABLED_BY_PREDICATE = "biolink:enabled_by"
HAS_INPUT_PREDICATE = "biolink:has_input"
HAS_OUTPUT_PREDICATE = "biolink:has_output"
IS_INPUT_OF_PREDICATE = "biolink:is_input_of"
IS_OUTPUT_OF_PREDICATE = "biolink:is_output_of"
HAS_INPUT_RELATION = "RO:0002233"
HAS_OUTPUT_RELATION = "RO:0002234"
PARTICIPATES_IN_PREDICATE = "biolink:participates_in"
SAME_AS_PREDICATE = "biolink:same_as"
# CAN_BE_CARRIED_OUT_BY_PREDICATE = "biolink:can_be_carried_out_by" # Replacing with enables
RHEA_PREDICATE_MAPPER = {
    "has participant": HAS_PARTICIPANT_PREDICATE,
    "enabled by": ENABLED_BY_PREDICATE,
    "reaction enabled by molecular function": RHEA_TO_GO_EDGE,  # CAN_BE_CARRIED_OUT_BY_PREDICATE,
    "has input": HAS_INPUT_PREDICATE,
    "has output": HAS_OUTPUT_PREDICATE,
}

# RHEA Pyobo
ENABLED_BY_RELATION = "RO:0002333"
RHEA_PYOBO_RELATIONS_MAPPER = {
    ENABLED_BY_RELATION: ENABLED_BY_PREDICATE,
    RDFS_SUBCLASS_OF: SUBCLASS_PREDICATE,
    HAS_INPUT_RELATION: HAS_INPUT_PREDICATE,
    HAS_OUTPUT_RELATION: HAS_OUTPUT_PREDICATE,
    HAS_PARTICIPANT: HAS_PARTICIPANT_PREDICATE,
    # "debio:0000007" : SUPERCLASS_PREDICATE, # This is being ignored in RheaMapperTransform
    # "debio:0000008" : SUPERCLASS_PREDICATE, # This is being ignored in RheaMapperTransform
    # "debio:0000009" : SUPERCLASS_PREDICATE, # This is being ignored in RheaMapperTransform
    "debio:0000047": RHEA_TO_GO_EDGE,
}

RHEA_PYOBO_PREFIXES_MAPPER = {
    "chebi": CHEBI_PREFIX,
    RHEA_KEY: RHEA_NEW_PREFIX,
    EC_PYOBO_PREFIX: EC_PREFIX,
    "uniprot": UNIPROT_PREFIX,
    "go": GO_PREFIX,
}

# Columns desired for the Uniprot data (from .dat files)
UNIPROT_TREMBL_COLUMNS = [
    "taxonomy_id",
    "entry_name",
    "accessions",
    "description",
    "comments",
    "cross_references",
    "proteome_id",
    "data_class",
]


# BactoTraits
COMBO_KEY = "combo"

# Unipathways
UNIPATHWAYS_XREFS_FILEPATH = ONTOLOGIES_XREFS_DIR / "unipathways_xrefs.tsv"
UNIPATHWAYS_SHORT_PREFIX = "UPa"
UNIPATHWAYS_COMPOUND_PREFIX = "OBO:UPa_UPC"
UNIPATHWAYS_ENZYMATIC_REACTION_PREFIX = "OBO:UPa_UER"
UNIPATHWAYS_REACTION_PREFIX = "OBO:UPa_UCR"
UNIPATHWAYS_LINEAR_SUB_PATHWAY_PREFIX = "OBO:UPa_ULS"
UNIPATHWAYS_PATHWAY_PREFIX = "OBO:UPa_UPA"
UNIPATHWAYS_CATEGORIES_DICT = {
    UNIPATHWAYS_COMPOUND_PREFIX: MEDIUM_CATEGORY,
    UNIPATHWAYS_ENZYMATIC_REACTION_PREFIX: EC_CATEGORY,
    UNIPATHWAYS_REACTION_PREFIX: RHEA_CATEGORY,
    UNIPATHWAYS_LINEAR_SUB_PATHWAY_PREFIX: PATHWAY_CATEGORY,
    UNIPATHWAYS_PATHWAY_PREFIX: PATHWAY_CATEGORY,
}

PART_OF_RELATION = "BFO:0000050"
PART_OF_PREDICATE = "biolink:part_of"
RELATED_TO_RELATION = "RO:0000052"
RELATED_TO_PREDICATE = "biolink:related_to"
HAS_ALTERNATE_ENZYMATIC_REACTION_RELATION = (
    "OBO:upa#has_alternate_enzymatic_reaction"  # TODO explore other relation
)
UNIPATHWAYS_RELATIONS_DICT = {
    HAS_INPUT_PREDICATE: HAS_INPUT_RELATION,
    HAS_OUTPUT_PREDICATE: HAS_OUTPUT_RELATION,
    PART_OF_PREDICATE: PART_OF_RELATION,
    RELATED_TO_PREDICATE: RELATED_TO_RELATION,
}

METACYC_PREFIX = "METACYC:"
UNIPATHWAYS_IGNORE_PREFIXES = [
    KEGG_PREFIX,
    METACYC_PREFIX,
    UNIPATHWAYS_COMPOUND_PREFIX,
    UNIPATHWAYS_ENZYMATIC_REACTION_PREFIX,
    UNIPATHWAYS_LINEAR_SUB_PATHWAY_PREFIX,
]

UNIPATHWAYS_INCLUDE_PAIRS = [
    [UNIPATHWAYS_REACTION_PREFIX, UNIPATHWAYS_ENZYMATIC_REACTION_PREFIX],
    [UNIPATHWAYS_ENZYMATIC_REACTION_PREFIX, UNIPATHWAYS_LINEAR_SUB_PATHWAY_PREFIX],
    [UNIPATHWAYS_LINEAR_SUB_PATHWAY_PREFIX, UNIPATHWAYS_PATHWAY_PREFIX],
]

HGNC_OLD_PREFIX = "http://identifiers.org/hgnc/"
HGNC_NEW_PREFIX = "HGNC:"

# Create a mapping for special cases
SPECIAL_PREFIXES = {
    EC_PYOBO_PREFIX: EC_PREFIX.rstrip(":"),
    EC_OBO_PREFIX: EC_PREFIX,
    UNIPROT_OBO_PREFIX: UNIPROT_PREFIX,
    RHEA_NEW_PREFIX.lower().rstrip(":"): RHEA_NEW_PREFIX.rstrip(":"),
    RHEA_OBO_PREFIX: RHEA_NEW_PREFIX,
    # UNIPROT_OBO_PREFIX: UNIPROT_PREFIX + ":",  # comment for now since we do not need obo-db-ingest for uniprot
    DEBIO_OBO_PREFIX: DEBIO_NEW_PREFIX,
    CHEBI_CAS_PREFIX: CAS_RN_PREFIX,
    UNIPATHWAYS_REACTION_PREFIX: re.sub(r"OBO:UPa_(\w{3})", r"UPA:\1", UNIPATHWAYS_REACTION_PREFIX),
    UNIPATHWAYS_PATHWAY_PREFIX: re.sub(r"OBO:UPa_(\w{3})", r"UPA:\1", UNIPATHWAYS_PATHWAY_PREFIX),
    HGNC_OLD_PREFIX: HGNC_NEW_PREFIX,
}

# CTD
CTD_CAS_RN_COLUMN = "CasRN"
CTD_CHEMICAL_MESH_COLUMN = "ChemicalID"
CTD_DISEASE_MESH_COLUMN = "DiseaseID"
CTD_DISEASE_OMIM_COLUMN = "OmimIDs"
CHEMICAL_TO_DISEASE_EDGE = "biolink:associated_with"
MESH_PREFIX = "MESH:"
NODE_NORMALIZER_URL = "https://nodenormalization-sri.renci.org/1.4/get_normalized_nodes?curie="
MONDO_PREFIX = "MONDO:"

# Disbiome
DISBIOME_DIR: Path = TRANSFORM_UTILS_DIR / "disbiome"
DISBIOME_TMP_DIR = DISBIOME_DIR / "tmp"
DISBIOME_DISEASE_NAME = "disease_name"
DISBIOME_ORGANISM_ID = "organism_ncbi_id"
DISBIOME_ORGANISM_NAME = "organism_name"
DISIOME_QUALITATIVE_OUTCOME = "qualitative_outcome"
DISBIOME_ELEVATED = "Elevated"
DISBIOME_REDUCED = "Reduced"
ASSOCIATED_WITH_INCREASED_LIKELIHOOD_OF_PREDICATE = (
    "biolink:associated_with_increased_likelihood_of"
)
ASSOCIATED_WITH_DECREASED_LIKELIHOOD_OF_PREDICATE = (
    "biolink:associated_with_decreased_likelihood_of"
)
ASSOCIATED_WITH_INCREASED_LIKELIHOOD_OF = ASSOCIATED_WITH
ASSOCIATED_WITH_DECREASED_LIKELIHOOD_OF = ASSOCIATED_WITH

# Wallen etal
WALLEN_ETAL_DIR: Path = TRANSFORM_UTILS_DIR / WALLEN_ETAL
WALLEN_ETAL_TMP_DIR = WALLEN_ETAL_DIR / "tmp"
