"""Constants for transform_utilities."""

from pathlib import Path

TRANSFORM_UTILS_DIR = Path(__file__).parent
BACDIVE_DIR = TRANSFORM_UTILS_DIR / "bacdive"
BACDIVE_TMP_DIR = BACDIVE_DIR / "tmp"
BACDIVE_YAML_DIR = BACDIVE_TMP_DIR / "yaml"
MEDIADIVE_DIR = TRANSFORM_UTILS_DIR / "mediadive"
MEDIADIVE_TMP_DIR = MEDIADIVE_DIR / "tmp"
MEDIADIVE_MEDIUM_YAML_DIR = MEDIADIVE_TMP_DIR / "medium_yaml"
MEDIADIVE_MEDIUM_STRAIN_YAML_DIR = MEDIADIVE_TMP_DIR / "medium_strain_yaml"
TRAITS_DIR = TRANSFORM_UTILS_DIR / "traits"
RAW_DATA_DIR = Path(__file__).parents[2] / "data" / "raw"
RHEA_DIR: Path = TRANSFORM_UTILS_DIR / "rhea"
RHEA_TMP_DIR = RHEA_DIR / "tmp"
BACTOTRAITS_DIR = TRANSFORM_UTILS_DIR / "bactotraits"
BACTOTRAITS_TMP_DIR = BACTOTRAITS_DIR / "tmp"
UNIPROT_TREMBL_DIR = TRANSFORM_UTILS_DIR / "uniprot_trembl"
UNIPROT_TREMBL_TMP_DIR = UNIPROT_TREMBL_DIR / "tmp"
ONTOLOGY_DIR = TRANSFORM_UTILS_DIR / "ontology"
ONTOLOGY_XREFS_DIR = ONTOLOGY_DIR / "xrefs"
CHEBI_XREFS_FILEPATH = ONTOLOGY_XREFS_DIR / "chebi_xrefs.tsv"
CUSTOM_CURIES_YAML_FILE = TRANSFORM_UTILS_DIR / "custom_curies.yaml"

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

PHYSIOLOGY_AND_METABOLISM = "Physiology and metabolism"
ISOLATION_SAMPLING_ENV_INFO = "Isolation, sampling and environmental information"
SAFETY_INFO = "Safety information"
SEQUENCE_INFO = "Sequence information"
RISK_ASSESSMENT = "risk assessment"
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

EXTERNAL_LINKS = "External links"
EXTERNAL_LINKS_CULTURE_NUMBER = "culture collection no."
REF = "Reference"
NCBITAXON_PREFIX = "NCBITaxon:"
BACDIVE_PREFIX = "bacdive:"
CHEBI_PREFIX = "CHEBI:"
CAS_RN_PREFIX = "CAS-RN:"
PUBCHEM_PREFIX = "PubChem:"
UBERON_PREFIX = "UBERON:"
RO_PREFIX = "RO:"
MEDIADIVE_INGREDIENT_PREFIX = "ingredient:"
MEDIADIVE_SOLUTION_PREFIX = "solution:"
MEDIADIVE_MEDIUM_PREFIX = "medium:"
GO_PREFIX = "GO:"
KEGG_PREFIX = "KEGG:"
SHAPE_PREFIX = "cell_shape:"
PATHWAY_PREFIX = "pathways:"
CARBON_SUBSTRATE_PREFIX = "carbon_substrates:"
ISOLATION_SOURCE_PREFIX = "isolation_source:"
RHEA_OLD_PREFIX = "OBO:rhea_"
RHEA_NEW_PREFIX = "RHEA:"
RHEA_URI = "http://purl.obolibrary.org/obo/rhea_"
DEBIO_OBO_PREFIX = "OBO:debio_"
DEBIO_NEW_PREFIX = "debio:"
DEBIO_URI = "http://purl.obolibrary.org/obo/debio_"
RHEA_OBO_PREFIX = "OBO:rhea_"
MEDIADIVE_REST_API_BASE_URL = "https://mediadive.dsmz.de/rest/"
BACDIVE_API_BASE_URL = "https://bacmedia.dsmz.de/"

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
NCBI_TO_METABOLISM_EDGE = "biolink:capable_of"  # [org -> metabolism]
NCBI_TO_PATHWAY_EDGE = "biolink:capable_of"  # # [org -> pathway]
CHEBI_TO_ROLE_EDGE = "biolink:has_chemical_role"
NCBI_TO_METABOLITE_UTILIZATION_EDGE = "biolink:consumes"  # [org -> metabolite_utilization]
NCBI_TO_ENZYME_EDGE = "biolink:capable_of"  # [org -> enzyme]
ASSAY_TO_NCBI_EDGE = "biolink:assesses"  # [org -> assay]
NCBI_TO_METABOLITE_PRODUCTION_EDGE = "biolink:produces"
ENZYME_TO_ASSAY_EDGE = "biolink:is_assessed_by"  # [enzyme -> assay]
SUBSTRATE_TO_ASSAY_EDGE = "biolink:occurs_in"  # [substrate -> assay]
ENZYME_TO_SUBSTRATE_EDGE = "biolink:consumes"  # [substrate -> enzyme]
NCBI_TO_SUBSTRATE_EDGE = "biolink:consumes"
RHEA_TO_EC_EDGE = "biolink:close_match"
RHEA_TO_GO_EDGE = "biolink:close_match"

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
PHENOTYPIC_CATEGORY = "biolink:PhenotypicQuality"
ATTRIBUTE_CATEGORY = "biolink:Attribute"
METABOLITE_CATEGORY = "biolink:ChemicalEntity"
SUBSTRATE_CATEGORY = "biolink:ChemicalEntity"

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
ASSOCIATED_WITH_PREDICATE = "biolink:associated_with"
PREDICATE_ID_COLUMN = "predicate_id"
PREDICATE_LABEL_COLUMN = "predicate_label"
DEBIO_MAPPER = {
    RHEA_LEFT_TO_RIGHT_DIRECTION: "debio:0000007",
    RHEA_RIGHT_TO_LEFT_DIRECTION: "debio:0000008",
    RHEA_BIDIRECTIONAL_DIRECTION: "debio:0000009",
}
DEBIO_PREDICATE_MAPPER = {
    RHEA_LEFT_TO_RIGHT_DIRECTION: "biolink:is_input_of",
    RHEA_RIGHT_TO_LEFT_DIRECTION: "biolink:is_output_of",
    RHEA_BIDIRECTIONAL_DIRECTION: "biolink:participates_in",
}
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

CHEBI_MANUAL_ANNOTATION_PATH = TRAITS_DIR / "chebi_manual_annotation.tsv"

# ROBOT
ROBOT_REMOVED_SUFFIX = "_removed_subset"
ROBOT_EXTRACT_SUFFIX = "_extract_subset"
EXCLUSION_TERMS_FILE = "exclusion_branches.tsv"

# Uniprot
ORGANISM_TO_ENZYME_EDGE = "biolink:expresses"
ENZYME_CATEGORY = "biolink:Enzyme"
CHEMICAL_TO_ENZYME_EDGE = "biolink:binds_to"
UNIPROT_GENOME_FEATURES = "uniprot_genome_features"
UNIPROT_BASE_URL = "https://rest.uniprot.org/uniprotkb/"
UNIPROT_FIELDS = ["organism_id", "id", "accession", "protein_name", "ec", "ft_binding"]
UNIPROT_KEYWORDS = ["Reference+proteome"]
UNIPROT_DESIRED_FORMAT = "tsv"
UNIPROT_SIZE = 500
ORGANISM_ID_MIXED_CASE = "Organism_ID"
UNIPROT_ORG_ID_COLUMN_NAME = "Organism (ID)"
TAXONOMY_ID_UNIPROT_PREFIX = "taxonomy_id:"
TAXONOMY_ID_UNIPROT_COLUMN = "taxonomy_id"
UNIPROT_REVIEWED_FLAG = "reviewed:true+"
UNIPROT_PREFIX = "uniprot"

PROTEOME_ID_COLUMN = "proteome_id"
PROTEOME_PREFIX = "Proteomes:"
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
    "API_",
    RHEA_NEW_PREFIX,
    GO_PREFIX,
]

# Create a mapping for special cases
SPECIAL_PREFIXES = {
    EC_PYOBO_PREFIX: EC_PREFIX.rstrip(":"),
    EC_OBO_PREFIX: EC_PREFIX,
    RHEA_NEW_PREFIX.lower().rstrip(":"): RHEA_NEW_PREFIX.rstrip(":"),
    RHEA_OBO_PREFIX: RHEA_NEW_PREFIX,
    UNIPROT_OBO_PREFIX: UNIPROT_PREFIX + ":",
    DEBIO_OBO_PREFIX: DEBIO_NEW_PREFIX,
    CHEBI_CAS_PREFIX: CAS_RN_PREFIX,
}
HAS_PARTICIPANT_PREDICATE = "biolink:has_participant"
ENABLED_BY_PREDICATE = "biolink:enabled_by"
HAS_INPUT_PREDICATE = "biolink:has_input"
HAS_OUTPUT_PREDICATE = "biolink:has_output"
CAN_BE_CARRIED_OUT_BY_PREDICATE = "biolink:can_be_carried_out_by"
RHEA_PREDICATE_MAPPER = {
    "has participant": HAS_PARTICIPANT_PREDICATE,
    "enabled by": ENABLED_BY_PREDICATE,
    "reaction enabled by molecular function": CAN_BE_CARRIED_OUT_BY_PREDICATE,
    "has input": HAS_INPUT_PREDICATE,
    "has output": HAS_OUTPUT_PREDICATE,
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
