"""Ontology transform module."""

import gzip
import re
import shutil
from collections import defaultdict
from os import makedirs
from pathlib import Path
from typing import Optional, Union

import pandas as pd

# from kgx.transformer import Transformer
from kgx.cli.cli_utils import transform

from kg_microbe.transform_utils.constants import (
    AGENT_TYPE_COLUMN,
    CATEGORY_COLUMN,
    CHEBI_XREFS_FILEPATH,
    DESCRIPTION_COLUMN,
    ENABLED_BY_PREDICATE,
    ENABLED_BY_RELATION,
    EXCLUSION_TERMS_FILE,
    GO_PREFIX,
    ID_COLUMN,
    KNOWLEDGE_ASSERTION,
    KNOWLEDGE_LEVEL_COLUMN,
    MANUAL_AGENT,
    MONDO_XREFS_FILEPATH,
    NCBITAXON_PREFIX,
    OBJECT_COLUMN,
    ONTOLOGIES,
    ONTOLOGIES_XREFS_DIR,
    PART_OF_PREDICATE,
    PREDICATE_COLUMN,
    PRIMARY_KNOWLEDGE_SOURCE_COLUMN,
    RELATED_TO_PREDICATE,
    RELATED_TO_RELATION,
    RELATION_COLUMN,
    RHEA_NEW_PREFIX,
    ROBOT_REMOVED_SUFFIX,
    SPECIAL_PREFIXES,
    SUBJECT_COLUMN,
    TREMBL_PREFIX,
    UNIPATHWAYS_ENZYMATIC_REACTION_PREFIX,
    UNIPATHWAYS_INCLUDE_PAIRS,
    UNIPATHWAYS_PATHWAY_PREFIX,
    UNIPATHWAYS_REACTION_PREFIX,
    UNIPATHWAYS_XREFS_FILEPATH,
    UNIPROT_PREFIX,
    XREF_COLUMN,
)
from kg_microbe.utils.ontology_utils import replace_category_ontology
from kg_microbe.utils.pandas_utils import (
    drop_duplicates,
    establish_transitive_relationship,
    establish_transitive_relationship_multiple,
)
from kg_microbe.utils.robot_utils import (
    convert_to_json,
    remove_convert_to_json,
)
from kg_microbe.utils.unipathways_utils import (
    check_wanted_pairs,
    remove_unwanted_prefixes_from_edges,
    remove_unwanted_prefixes_from_node_xrefs,
    replace_category_for_unipathways,
    replace_id_with_xref,
    replace_triples_with_labels,
)

from ..transform import Transform

ONTOLOGIES_MAP = {
    "ncbitaxon": "ncbitaxon.owl.gz",
    "chebi": "chebi.owl.gz",
    "envo": "envo.json",
    "go": "go.json",
    ## "rhea": "rhea.json.gz", # Redundant to RheaMappingsTransform
    "ec": "ec.json",
    "upa": "upa.owl",
    "mondo": "mondo.json",
    "hp": "hp.json",
    "metpo": "metpo.owl",
    "uberon": "uberon.owl",
    "foodon": "foodon.owl",
    "ro": "ro.owl",
}


class OntologiesTransform(Transform):

    """OntologyTransform parses an Obograph JSON form of an Ontology into nodes nad edges."""

    # Mapping of ontology names to InforES standard knowledge sources
    ONTOLOGY_KNOWLEDGE_SOURCES = {
        "chebi": "infores:chebi",
        "envo": "infores:envo",
        "go": "infores:go",
        "ncbitaxon": "infores:ncbitaxon",
        "uberon": "infores:uberon",
        "hp": "infores:hp",
        "mondo": "infores:mondo",
        "upa": "infores:upa",
        "ec": "infores:ec",
        "metpo": "infores:metpo",
        "foodon": "infores:foodon",
        "ro": "infores:ro",
    }

    def __init__(self, input_dir: Optional[Path] = None, output_dir: Optional[Path] = None):
        """Instantiate object."""
        source_name = ONTOLOGIES
        super().__init__(source_name, input_dir, output_dir)

    def run(
        self, data_file: Union[Optional[Path], Optional[str]] = None, show_status: bool = True
    ) -> None:
        """
        Transform an ontology.

        :param data_file: data file to parse
        :return: None.
        """
        if data_file:
            k = str(data_file).split(".")[0]
            data_file = self.input_base_dir / data_file
            self.parse(k, data_file, k)
        else:
            # load all ontologies
            for k in ONTOLOGIES_MAP.keys():
                data_file = self.input_base_dir / ONTOLOGIES_MAP[k]
                self.parse(k, data_file, k)

    def parse(self, name: str, data_file: Optional[Path], source: str) -> None:
        """
        Process the data_file.

        :param name: Name of the ontology.
        :param data_file: data file to parse.
        :param source: Source name.
        :return: None.
        """
        if not data_file.suffix == ".json":
            if data_file.suffixes == [".owl", ".gz"]:
                # if NCBITAXON_PREFIX.strip(":").lower() in str(data_file):
                # or CHEBI_PREFIX.strip(":").lower() in str(data_file):
                if NCBITAXON_PREFIX.strip(":").lower() in str(data_file):
                    json_path = str(data_file).replace(".owl.gz", ROBOT_REMOVED_SUFFIX + ".json")
                    if not Path(json_path).is_file():
                        self.decompress(data_file)
                        with open(str(self.input_base_dir / EXCLUSION_TERMS_FILE), "r") as f:
                            terms = [
                                line.strip() for line in f if line.lower().startswith(name.lower())
                            ]
                        remove_convert_to_json(str(self.input_base_dir), name, terms)
                    # elif CHEBI_PREFIX.strip(":").lower() in str(data_file):
                    #     json_path = str(data_file).replace(".owl.gz", ROBOT_EXTRACT_SUFFIX + ".json")
                    #     owl_path = str(data_file).strip(".gz")
                    #     # Convert CHEBI owl => JSON each time to handle varying terms (if any) in CHEBI_NODES_FILENAME
                    #     if not Path(owl_path).is_file():
                    #         self.decompress(data_file)
                    #     terms = str(self.input_base_dir / CHEBI_NODES_FILENAME)
                    #     extract_convert_to_json(str(self.input_base_dir), name, terms, "BOT")
                else:
                    json_path = str(data_file).replace("owl.gz", "json")
                    if not Path(json_path).is_file():
                        # Unzip the file
                        self.decompress(data_file)
                        print(f"Converting {data_file} to obojson...")
                    convert_to_json(str(self.input_base_dir), name)

                data_file = json_path
            elif data_file.suffixes == [".json", ".gz"]:
                json_path = str(data_file).replace(".json.gz", ".json")
                if not Path(json_path).is_file():
                    self.decompress(data_file)
                data_file = json_path
            elif data_file.suffix == ".owl":
                json_path = str(data_file).replace(".owl", ".json")
                if not Path(json_path).is_file():
                    convert_to_json(str(self.input_base_dir), name)
                data_file = json_path
            elif data_file.suffix == ".obo":
                json_path = str(data_file).replace(".obo", ".json")
                if not Path(json_path).is_file():
                    convert_to_json(str(self.input_base_dir), name)
                data_file = json_path
            else:
                raise ValueError(f"Unsupported file format: {data_file}")

        transform(
            inputs=[data_file],
            input_format="obojson",
            output=self.output_dir / name,
            output_format="tsv",
        )
        # Apply post-processing for ontologies that need IRI removal and URL conversion
        # (all ontologies benefit from these cleanups)
        self.post_process(name)

    def decompress(self, data_file):
        """Unzip file."""
        print(f"Decompressing {data_file}...")
        with gzip.open(data_file, "rb") as f_in:
            with open(data_file.parent / data_file.stem, "wb") as f_out:
                shutil.copyfileobj(f_in, f_out)

    def _add_kgx_metadata_to_edges(self, edges_file_path: Path):
        """
        Add knowledge_level and agent_type columns to ontology edge files.

        All ontology edges use knowledge_assertion + manual_agent since ontologies
        are manually curated by domain expert curators (GO, ChEBI, ENVO, etc.).
        The relationships represent definitional assertions made by experts.
        """
        df = pd.read_csv(edges_file_path, sep="\t")

        # Add columns if they don't exist
        if KNOWLEDGE_LEVEL_COLUMN not in df.columns:
            df[KNOWLEDGE_LEVEL_COLUMN] = KNOWLEDGE_ASSERTION
        if AGENT_TYPE_COLUMN not in df.columns:
            df[AGENT_TYPE_COLUMN] = MANUAL_AGENT

        # Write back
        df.to_csv(edges_file_path, sep="\t", index=False)

    def _fix_node_categories(self, nodes_file_path: Path, ontology_name: str):
        """
        Fix node categories for specific ontologies.

        - GO: Apply aspect-based categorization (MF/BP/CC)
        - ChEBI: Replace deprecated ChemicalSubstance with SmallMolecule and detect roles
        - UBERON: Ensure all terms are AnatomicalEntity
        - NCBITaxon: Ensure all terms are OrganismTaxon

        Args:
        ----
            nodes_file_path: Path to nodes TSV file
            ontology_name: Name of the ontology (e.g., "go", "chebi", "uberon", "ncbitaxon")

        """
        from kg_microbe.utils.ontology_utils import (
            get_chebi_category,
            get_go_category_by_aspect,
            get_ncbitaxon_category,
            get_uberon_category,
            replace_deprecated_categories,
        )

        print(f"Fixing node categories for {ontology_name}...")

        df = pd.read_csv(nodes_file_path, sep="\t", low_memory=False)

        if ontology_name == "go":
            # Apply GO aspect-based categorization
            print("  Applying GO aspect-based categorization...")

            # Create GO adapter once to avoid file descriptor leaks
            from oaklib import get_adapter

            from kg_microbe.transform_utils.constants import GO_SOURCE

            try:
                go_adapter = get_adapter(f"sqlite:{GO_SOURCE}")
            except Exception:
                go_adapter = get_adapter("sqlite:data/raw/go.db")

            def fix_go_category(row):
                go_id = row["id"]
                if pd.notna(go_id) and go_id.startswith("GO:"):
                    # Pass the adapter to avoid creating new connections
                    return get_go_category_by_aspect(go_id, go_adapter)
                return row["category"]

            df["category"] = df.apply(fix_go_category, axis=1)

        elif ontology_name == "chebi":
            # Fix ChEBI categories: deprecated ChemicalSubstance → SmallMolecule
            # Also detect roles
            print("  Fixing ChEBI categories (deprecated ChemicalSubstance → SmallMolecule)...")
            print("  Detecting ChEBI roles...")

            # Create ChEBI adapter once to avoid file descriptor leaks
            from oaklib import get_adapter

            from kg_microbe.transform_utils.constants import CHEBI_SOURCE

            try:
                chebi_adapter = get_adapter(f"sqlite:{CHEBI_SOURCE}")
            except Exception:
                chebi_adapter = get_adapter("sqlite:data/raw/chebi.db")

            def fix_chebi_category(row):
                chebi_id = row["id"]
                if pd.notna(chebi_id) and chebi_id.startswith("CHEBI:"):
                    # Get appropriate category (SmallMolecule or ChemicalRole)
                    # Pass the adapter to avoid creating new connections
                    return get_chebi_category(chebi_id, chebi_adapter)
                # For non-CHEBI IDs, just replace deprecated categories
                return replace_deprecated_categories(str(row["category"]))

            df["category"] = df.apply(fix_chebi_category, axis=1)

        elif ontology_name == "uberon":
            # Fix UBERON categories: all UBERON terms should be AnatomicalEntity
            print("  Fixing UBERON categories (all terms → AnatomicalEntity)...")

            def fix_uberon_category(row):
                uberon_id = row["id"]
                if pd.notna(uberon_id) and uberon_id.startswith("UBERON:"):
                    return get_uberon_category(uberon_id)
                return row["category"]

            df["category"] = df.apply(fix_uberon_category, axis=1)

        elif ontology_name == "ncbitaxon":
            # Fix NCBITaxon categories: all NCBITaxon terms should be OrganismTaxon
            print("  Fixing NCBITaxon categories (all terms → OrganismTaxon)...")

            def fix_ncbitaxon_category(row):
                ncbitaxon_id = row["id"]
                if pd.notna(ncbitaxon_id) and ncbitaxon_id.startswith("NCBITaxon:"):
                    return get_ncbitaxon_category(ncbitaxon_id)
                return row["category"]

            df["category"] = df.apply(fix_ncbitaxon_category, axis=1)

        else:
            # For other ontologies, just replace deprecated categories
            print(f"  Replacing deprecated categories in {ontology_name}...")
            df["category"] = df["category"].apply(
                lambda x: replace_deprecated_categories(str(x)) if pd.notna(x) else x
            )

        # Write back
        df.to_csv(nodes_file_path, sep="\t", index=False)
        print(f"  Fixed categories for {ontology_name}")

    def post_process(self, name: str):
        """Post process specific nodes and edges files."""
        nodes_file = self.output_dir / f"{name}_nodes.tsv"
        edges_file = self.output_dir / f"{name}_edges.tsv"

        # Add knowledge_level and agent_type columns to edge files
        self._add_kgx_metadata_to_edges(edges_file)

        # Fix node categories (GO aspect-based, ChEBI deprecated categories, UBERON, NCBITaxon)
        if name in ["go", "chebi", "uberon", "ncbitaxon"]:
            self._fix_node_categories(nodes_file, name)

        # Compile a regex pattern that matches any key in SPECIAL_PREFIXES
        pattern = re.compile("|".join(re.escape(key) for key in SPECIAL_PREFIXES.keys()))

        def _replace_special_prefixes(line):
            """Use the pattern to replace all occurrences of the keys with their values."""
            return pattern.sub(lambda match: SPECIAL_PREFIXES[match.group(0)], line)

        def _replace_quotation_marks(line, description_index):
            """Replace single and double quotation marks."""
            parts = line.split("\t")
            parts = [i.strip() for i in parts]
            parts[description_index] = parts[description_index].replace('"', "").replace("'", "")
            new_line = "\t".join(parts)
            return new_line

        if name == "chebi" or name == "upa" or name == "mondo":
            makedirs(ONTOLOGIES_XREFS_DIR, exist_ok=True)
            # Get two columns from the nodes file: 'id' and 'xref'
            # The xref column is | separated and contains different prefixes
            # We need to make a 1-to-1 mapping between the prefixes and the id
            if name == "chebi":
                xref_filepath = CHEBI_XREFS_FILEPATH
            elif name == "upa":
                xref_filepath = UNIPATHWAYS_XREFS_FILEPATH
                unipathways_xref_dict = {}
            elif name == "mondo":
                xref_filepath = MONDO_XREFS_FILEPATH
            with open(nodes_file, "r") as nf, open(xref_filepath, "w") as xref_file:

                for line in nf:
                    if line.startswith("id"):
                        # get the index for the term 'xref'
                        xref_index = line.strip().split("\t").index("xref")
                        xref_file.write("id\txref\n")
                        continue
                    line = _replace_special_prefixes(line)
                    parts = line.strip().split("\t")
                    subject = parts[0]
                    xrefs = parts[xref_index].split("|") if parts[xref_index] != "" else None
                    if xrefs and subject not in xrefs:
                        for xref in xrefs:
                            # Write a new tsv file with header ["id", "xref"]
                            xref_file.write(f"{subject}\t{xref}\n")
                            # Use unipathways xrefs elsewhere so write to dict
                            if name == "upa":
                                unipathways_xref_dict[subject] = xref

        if name == "mondo":
            with open(nodes_file, "r") as nf, open(edges_file, "r") as ef:
                # Update prefixes in nodes file
                new_nf_lines = []
                for line in nf:
                    if line.startswith("id"):
                        # get the index for the term 'id'
                        id_index = line.strip().split("\t").index(ID_COLUMN)
                        # get the index for the term 'category'
                        category_index = line.strip().split("\t").index(CATEGORY_COLUMN)
                        description_index = line.strip().split("\t").index(DESCRIPTION_COLUMN)
                        new_nf_lines.append(line)
                    else:
                        line = _replace_special_prefixes(line)
                        line = replace_category_ontology(line, id_index, category_index)
                        line = _replace_quotation_marks(line, description_index)
                        new_nf_lines.append(line + "\n")
            # Rewrite nodes file
            with open(nodes_file, "w") as new_nf:
                for line in new_nf_lines:
                    new_nf.write(line)

        if name == "upa":
            # Keep track of new node IDs for edges file
            nodes_dictionary = defaultdict(list)
            with open(nodes_file, "r") as nf:
                add_lines = []
                for line in nf:
                    if line.startswith("id"):
                        # get the index for the term 'id'
                        id_index = line.strip().split("\t").index(ID_COLUMN)
                        # get the index for the term 'xref'
                        xref_index = line.strip().split("\t").index(XREF_COLUMN)
                        # get the index for the term 'category'
                        category_index = line.strip().split("\t").index(CATEGORY_COLUMN)
                    else:
                        line = remove_unwanted_prefixes_from_node_xrefs(line, xref_index)
                        # For Reactions only
                        if any(
                            substring in line for substring in [UNIPATHWAYS_REACTION_PREFIX]
                        ):  # UNIPATHWAYS_COMPOUND_PREFIX,UNIPATHWAYS_ENZYMATIC_REACTION_PREFIX]):
                            new_lines, nodes_dictionary = replace_id_with_xref(
                                line,
                                xref_index,
                                id_index,
                                category_index,
                                nodes_dictionary,
                                self.node_header,
                            )
                            for new_line in new_lines:
                                if len(new_line) > 0:
                                    new_line = _replace_special_prefixes(new_line)
                                    add_lines.append(new_line + "\n")
                        # Add category only for nodes that are not added by another ingest, only Pathways
                        elif any(
                            substring in line for substring in [UNIPATHWAYS_PATHWAY_PREFIX]
                        ):  # ,UNIPATHWAYS_LINEAR_SUB_PATHWAY_PREFIX]):
                            new_line = replace_category_for_unipathways(
                                line, id_index, category_index, self.node_header
                            )
                            if len(new_line) > 0:
                                add_lines.append(new_line + "\n")
                        # Not adding any other node types except what is specified
                        # else:
                        #    add_line = line + "\n"
            # Rewrite nodes file
            with open(nodes_file, "w") as new_nf:
                new_nf.write("\t".join(self.node_header) + "\n")
                for line in add_lines:
                    new_nf.write(line)

            edges_df = pd.DataFrame(columns=self.edge_header)
            with open(edges_file, "r") as ef:
                for line in ef:
                    add_edge = []
                    if line.startswith("id"):
                        # get the index for the 'subject'
                        subject_index = line.strip().split("\t").index(SUBJECT_COLUMN)
                        # get the index for the 'predicate'
                        predicate_index = line.strip().split("\t").index(PREDICATE_COLUMN)
                        # get the index for the 'object'
                        object_index = line.strip().split("\t").index(OBJECT_COLUMN)
                        # get the index for the 'relation'
                        relation_index = line.strip().split("\t").index(RELATION_COLUMN)
                    else:
                        # Remove unwanted triples
                        line = check_wanted_pairs(line, subject_index, object_index)
                        if line:
                            new_lines = replace_triples_with_labels(
                                line,
                                subject_index,
                                object_index,
                                predicate_index,
                                relation_index,
                                nodes_dictionary,
                            )
                            for new_line in new_lines:
                                add_edge.append(new_line + "\n")
                    # new_ef.write(add_edge)
                    if len(add_edge) > 0:
                        for edge_line in add_edge:
                            parts = edge_line.strip().split("\t")
                            if len(parts) == len(self.edge_header) + 1:
                                parts = parts[1:]
                            df = pd.DataFrame([parts], columns=self.edge_header)
                            # Add the list as a new row to the DataFrame
                            edges_df = pd.concat([edges_df, df], ignore_index=True)
            # First write existing edges to file before establishing transitive relationships
            edges_df.to_csv(edges_file, sep="\t", index=False)

            # Add edges between GO and pathways using enzymatic reactions GO xrefs
            transitive_df_uer_go = establish_transitive_relationship(
                edges_file,
                UNIPATHWAYS_INCLUDE_PAIRS[1][0],
                UNIPATHWAYS_INCLUDE_PAIRS[1][1],
                PART_OF_PREDICATE,
                UNIPATHWAYS_INCLUDE_PAIRS[2][1],
            )
            # Replace UER with GO
            transitive_df_uer_go = transitive_df_uer_go[
                (
                    transitive_df_uer_go[SUBJECT_COLUMN].str.contains(
                        UNIPATHWAYS_ENZYMATIC_REACTION_PREFIX
                    )
                )
                & (transitive_df_uer_go[OBJECT_COLUMN].str.contains(UNIPATHWAYS_PATHWAY_PREFIX))
            ]
            # Replace predicate and relation
            transitive_df_uer_go.loc[
                transitive_df_uer_go[PREDICATE_COLUMN] == PART_OF_PREDICATE,
                [PREDICATE_COLUMN, RELATION_COLUMN],
            ] = [ENABLED_BY_PREDICATE, ENABLED_BY_RELATION]
            transitive_df_uer_go = transitive_df_uer_go.map(
                lambda x: unipathways_xref_dict.get(x, x)
            )

            # Only add GO relations, not EC
            transitive_df_uer_go = transitive_df_uer_go[
                transitive_df_uer_go[SUBJECT_COLUMN].str.contains(GO_PREFIX)
            ]

            # Add the list as a new row to the DataFrame
            edges_df = pd.concat([edges_df, transitive_df_uer_go], ignore_index=True)

            # Add edges between GO and pathways using patwhay GO xrefs
            upa_go_df = pd.DataFrame(list(unipathways_xref_dict.items()), columns=["id", "xref"])
            upa_go_df = upa_go_df.loc[
                (upa_go_df["id"].str.contains("UPA:UPA"))
                & (upa_go_df["xref"].str.contains(GO_PREFIX))
            ]
            upa_go_df.rename(columns={"xref": SUBJECT_COLUMN, "id": OBJECT_COLUMN}, inplace=True)
            upa_go_df[PREDICATE_COLUMN] = RELATED_TO_PREDICATE
            upa_go_df[RELATION_COLUMN] = RELATED_TO_RELATION
            # Use InforES standard knowledge source instead of filename
            upa_go_df[PRIMARY_KNOWLEDGE_SOURCE_COLUMN] = self.ONTOLOGY_KNOWLEDGE_SOURCES.get(
                "upa", "infores:upa"
            )
            # Add the list as a new row to the DataFrame
            edges_df = pd.concat([edges_df, upa_go_df], ignore_index=True)
            # Write existing edges to file before establishing more transitive relationships
            edges_df.to_csv(edges_file, sep="\t", index=False)

            # Consolidate paths into 1 edge
            # For triples with rhea prefix for reactions, get rhea to pathway edge
            transitive_df_rhea = establish_transitive_relationship_multiple(
                edges_file,
                RHEA_NEW_PREFIX,
                [UNIPATHWAYS_INCLUDE_PAIRS[0][1], UNIPATHWAYS_INCLUDE_PAIRS[1][1]],
                [PART_OF_PREDICATE, PART_OF_PREDICATE],
                [[UNIPATHWAYS_INCLUDE_PAIRS[1][1]], [UNIPATHWAYS_INCLUDE_PAIRS[2][1]]],
            )
            # For triples with Unipathways reaction prefix for reactions
            transitive_df_uni = establish_transitive_relationship_multiple(
                edges_file,
                UNIPATHWAYS_INCLUDE_PAIRS[0][0],
                [UNIPATHWAYS_INCLUDE_PAIRS[0][1], UNIPATHWAYS_INCLUDE_PAIRS[1][1]],
                [PART_OF_PREDICATE, PART_OF_PREDICATE],
                [[UNIPATHWAYS_INCLUDE_PAIRS[1][1]], [UNIPATHWAYS_INCLUDE_PAIRS[2][1]]],
            )
            transitive_df = pd.concat([transitive_df_rhea, transitive_df_uni], ignore_index=True)
            # Remove unnecessary edges between intermediate prefixes
            transitive_df = remove_unwanted_prefixes_from_edges(transitive_df)
            # Rewrite edges file
            transitive_df.to_csv(edges_file, sep="\t", index=False)
            drop_duplicates(edges_file)
            # Rewrite prefixes
            new_edge_lines = []
            with open(edges_file, "r") as ef:
                # Write a new edges tsv file with same edge header
                for line in ef:
                    new_edge_lines.append(_replace_special_prefixes(line))
            # Rewrite edges file
            with open(edges_file, "w") as new_ef:
                for line in new_edge_lines:
                    new_ef.write(line)

        if name == "ec":  # or name == "rhea":

            with open(nodes_file, "r") as nf, open(edges_file, "r") as ef:
                # Update prefixes in nodes file
                new_nf_lines = []
                for line in nf:
                    if line.startswith("id"):
                        # get the index for the term 'id'
                        id_index = line.strip().split("\t").index(ID_COLUMN)
                        # get the index for the term 'category'
                        category_index = line.strip().split("\t").index(CATEGORY_COLUMN)
                        new_nf_lines.append(line)
                    else:
                        line = _replace_special_prefixes(line)
                        line = replace_category_ontology(line, id_index, category_index)
                        new_nf_lines.append(line + "\n")
                # Update prefixes in edges file
                new_ef_lines = []
                for line in ef:
                    if line.startswith("id"):
                        continue
                    else:
                        line = _replace_special_prefixes(line)
                        new_ef_lines.append(line)
            if name == "ec":
                # Remove UniProt and TrEMBL nodes since accounted for elsewhere
                protein_prefixes = [UNIPROT_PREFIX, TREMBL_PREFIX]
                new_nf_lines = [
                    line
                    for line in new_nf_lines
                    if not any(prefix in line for prefix in protein_prefixes)
                ]
                new_ef_lines = [
                    line
                    for line in new_ef_lines
                    if not any(prefix in line for prefix in protein_prefixes)
                ]
            # elif name == "rhea":
            #     # Remove debio nodes that account for direction, since already there in inverse triples
            #     # Note that CHEBI and EC predicates do not match Rhea pyobo, so removing them
            #     rhea_exclusions = ["debio", UNIPROT_PREFIX, CHEBI_PREFIX, EC_PREFIX]
            #     new_nf_lines = [
            #         line for line in new_nf_lines if not any(sub in line for sub in rhea_exclusions)
            #     ]
            #     new_ef_lines = [
            #         line for line in new_ef_lines if not any(sub in line for sub in rhea_exclusions)
            #     ]
            # Rewrite nodes file
            with open(nodes_file, "w") as new_nf:
                for line in new_nf_lines:
                    new_nf.write(line)

            # Rewrite edges file
            with open(edges_file, "w") as new_ef:
                new_ef.write("\t".join(self.edge_header) + "\n")
                for line in new_ef_lines:
                    new_ef.write(line)

        else:
            # Process and write the nodes file
            with open(nodes_file, "r") as nf, open(
                nodes_file.with_suffix(".temp.tsv"), "w"
            ) as new_nf:
                for line in nf:
                    new_nf.write(_replace_special_prefixes(line))

            # Replace the original file with the modified one
            nodes_file.with_suffix(".temp.tsv").replace(nodes_file)

            # Process and write the edges file
            with open(edges_file, "r") as ef, open(
                edges_file.with_suffix(".temp.tsv"), "w"
            ) as new_ef:
                for line in ef:
                    new_ef.write(_replace_special_prefixes(line))

            # Replace the original file with the modified one
            edges_file.with_suffix(".temp.tsv").replace(edges_file)

        # Remove IRI column that KGX may have auto-generated
        self._remove_iri_column(nodes_file)

        # Convert URL-formatted node IDs to CURIEs
        self._convert_urls_to_curies(nodes_file, edges_file)

    def _remove_iri_column(self, nodes_file: Path) -> None:
        """Remove IRI column from nodes file since it's not used downstream."""
        import pandas as pd

        # Read nodes file
        df = pd.read_csv(nodes_file, sep='\t', low_memory=False)

        # Remove IRI column if it exists (KGX may auto-generate it)
        if 'iri' in df.columns:
            df = df.drop(columns=['iri'])
            df.to_csv(nodes_file, sep='\t', index=False)

    def _convert_urls_to_curies(self, nodes_file: Path, edges_file: Path) -> None:
        """Convert URL-formatted node IDs to CURIEs in both nodes and edges files."""
        import re

        import pandas as pd

        from kg_microbe.utils.mapping_file_utils import uri_to_curie

        url_pattern = re.compile(r'^https?://')

        # Process nodes file
        df_nodes = pd.read_csv(nodes_file, sep='\t', low_memory=False)

        # Track URL to CURIE mappings for updating edges
        url_to_curie_map = {}

        # Convert URL IDs to CURIEs
        if 'id' in df_nodes.columns:
            for idx, node_id in df_nodes['id'].items():
                if isinstance(node_id, str) and url_pattern.match(node_id):
                    curie = uri_to_curie(node_id)
                    url_to_curie_map[node_id] = curie
                    df_nodes.at[idx, 'id'] = curie

        # Save updated nodes file
        df_nodes.to_csv(nodes_file, sep='\t', index=False)

        # Process edges file if there were any URL conversions
        if url_to_curie_map:
            df_edges = pd.read_csv(edges_file, sep='\t', low_memory=False)

            # Update subject and object columns
            for col in ['subject', 'object']:
                if col in df_edges.columns:
                    df_edges[col] = df_edges[col].apply(
                        lambda x: url_to_curie_map.get(x, x) if isinstance(x, str) else x
                    )

            # Save updated edges file
            df_edges.to_csv(edges_file, sep='\t', index=False)
