"""Constants for transform_utilities."""
from pathlib import Path

BACDIVE_DIR = Path(__file__).parent / "bacdive"
BACDIVE_TMP_DIR = BACDIVE_DIR / "tmp"
BACDIVE_YAML_DIR = BACDIVE_TMP_DIR / "yaml"
MEDIADIVE_DIR = Path(__file__).parent / "mediadive"
MEDIADIVE_TMP_DIR = MEDIADIVE_DIR / "tmp"
MEDIADIVE_MEDIUM_YAML_DIR = MEDIADIVE_TMP_DIR / "medium_yaml"
MEDIADIVE_RECIPE_YAML_DIR = MEDIADIVE_TMP_DIR / "recipe_yaml"


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

PHYS_AND_METABOLISM = "Physiology and metabolism"
ISOLATION_SAMPLING_ENV_INFO = "Isolation, sampling and environmental information"
SAFETY_INFO = "Safety information"
SEQUENCE_INFO = "Sequence information"

DATA_KEY = "data"
SOLUTION_KEY = "solutions"

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

EXTERNAL_LINKS = "External links"
EXTERNAL_LINKS_CULTURE_NUMBER = "culture collection no."
REF = "Reference"
NCBITAXON_PREFIX = "NCBITaxon:"
BACDIVE_PREFIX = "bacdive:"
CHEBI_PREFIX = "CHEBI:"
CAS_RN_PREFIX = "CAS-RN:"
PUBCHEM_PREFIX = "PubChem:"
MEDIADIVE_INGREDIENT_PREFIX = "mediadive.ingredient:"
MEDIADIVE_SOLUTION_PREFIX = "mediadive.solution:"
MEDIADIVE_MEDIUM_PREFIX = "mediadive.medium:"
GO_PREFIX = "GO:"
KEGG_PREFIX = "KEGG:"
SHAPE_PREFIX = "traits.cell_shape_enum:"
PATHWAY_PREFIX = "traits.pathways:"
CARBON_SUBSTRATE_PREFIX = "traits.carbon_substrates:"
ISOLATION_SOURCE_PREFIX = "traits.data_source:"

MEDIADIVE_REST_API_BASE_URL = "https://mediadive.dsmz.de/rest/"
BACDIVE_API_BASE_URL = "https://bacmedia.dsmz.de/"

MEDIUM = "medium/"
COMPOUND = "ingredient/"
SOLUTION = "solution/"

BACDIVE_MEDIUM_DICT = {MEDIADIVE_MEDIUM_PREFIX: BACDIVE_API_BASE_URL + MEDIUM}

NCBI_TO_MEDIUM_EDGE = "biolink:occurs_in"
MEDIUM_TO_NCBI_EDGE = "biolink:contains_process"
MEDIUM_TO_INGREDIENT_EDGE = "biolink:has_part"  # Could also be has_constituent/has_participant
MEDIUM_TO_SOLUTION_EDGE = "biolink:has_part"
NCBI_TO_SHAPE_EDGE = "biolink:has_phenotype"  # [org_name -> cell_shape, metabolism]
NCBI_TO_CHEM_EDGE = "biolink:interacts_with"  # [org_name -> carbon_substrate]
NCBI_TO_ISOLATION_SOURCE_EDGE = "biolink:location_of"  # [org -> isolation_source]
NCBI_TO_METABOLISM_EDGE = "biolink:capable_of"  # [org -> metabolism]
NCBI_TO_PATHWAY_EDGE = "biolink:capable_of"  # # [org -> pathway]
CHEBI_TO_ROLE_EDGE = "biolink:has_chemical_role"


NCBI_CATEGORY = "biolink:OrganismTaxon"
MEDIUM_CATEGORY = "biolink:ChemicalEntity"
SOLUTION_CATEGORY = "biolink:ChemicalEntity"
INGREDIENT_CATEGORY = "biolink:ChemicalEntity"
SHAPE_CATEGORY = "biolink:AbstractEntity"
METABOLISM_CATEGORY = "biolink:ActivityAndBehavior"
PATHWAY_CATEGORY = "biolink:BiologicalProcess"
CARBON_SUBSTRATE_CATEGORY = "biolink:ChemicalEntity"
ROLE_CATEGORY = "biolink:ChemicalRole"
ENVIRONMENT_CATEGORY = "biolink:EnvironmentalFeature"  # "ENVO:01000254"

HAS_PART = "BFO:0000051"
IS_GROWN_IN = "BAO:0002924"
HAS_PHENOTYPE = "RO:0002200"  # [org_name -> has phenotype -> cell_shape, metabolism]
TROPHICALLY_INTERACTS_WITH = (
    "RO:0002438"  # [org_name -> 'trophically interacts with' -> carbon_substrate]
)
LOCATION_OF = "RO:0001015"  # [org -> location_of -> source]
BIOLOGICAL_PROCESS = "RO:0002215"  # [org -> biological_process -> metabolism]
HAS_ROLE = "RO:0000087"

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


MEDIADIVE_ID_COLUMN = "mediadive_id"
MEDIADIVE_COMPLEX_MEDIUM_COLUMN = "complex_medium"
MEDIADIVE_SOURCE_COLUMN = "source"
MEDIADIVE_LINK_COLUMN = "link"
MEDIADIVE_MIN_PH_COLUMN = "min_pH"
MEDIADIVE_MAX_PH_COLUMN = "max_pH"
MEDIADIVE_REF_COLUMN = "reference"
MEDIADIVE_DESC_COLUMN = "description"

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

CHEBI_NODES_FILENAME = "chebi_curies.tsv"

# ROBOT
ROBOT_REMOVED_SUFFIX = "_removed_subset"
ROBOT_EXTRACT_SUFFIX = "_extract_subset"
EXCLUSION_TERMS_FILE = "exclusion_branches.tsv"
