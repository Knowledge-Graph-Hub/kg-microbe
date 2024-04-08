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
    CATEGORY_COLUMN,
    CHEBI_XREFS_FILEPATH,
    EXCLUSION_TERMS_FILE,
    GO_PREFIX,
    ID_COLUMN,
    NCBITAXON_PREFIX,
    OBJECT_COLUMN,
    ONTOLOGY_XREFS_DIR,
    PART_OF_PREDICATE,
    PREDICATE_COLUMN,
    RELATION_COLUMN,
    ROBOT_REMOVED_SUFFIX,
    SPECIAL_PREFIXES,
    SUBJECT_COLUMN,
    UNIPATHWAYS_CATEGORIES_DICT,
    UNIPATHWAYS_IGNORE_PREFIXES,
    UNIPATHWAYS_INCLUDE_PAIRS,
    UNIPATHWAYS_PATHWAY_PREFIX,
    UNIPATHWAYS_REACTION_PREFIX,
    UNIPATHWAYS_RELATIONS_DICT,
    UNIPATHWAYS_RHEA_PAIR,
    XREF_COLUMN,
)
from kg_microbe.utils.robot_utils import (
    convert_to_json,
    remove_convert_to_json,
)

from ..transform import Transform

ONTOLOGIES = {
    # "HpTransform": "hp.json",
    # 'GoTransform': 'go-plus.json',
    # "ncbitaxon": "ncbitaxon.owl.gz",
    # "chebi": "chebi.owl.gz",
    # "envo": "envo.json",
    # "go": "go.json",
    # "rhea": "rhea.json.gz",
    # "ec": "ec.json",
    # "uniprot": "uniprot.json.gz",
    "upa": "upa.owl",
}


class OntologyTransform(Transform):

    """OntologyTransform parses an Obograph JSON form of an Ontology into nodes nad edges."""

    def __init__(self, input_dir: Optional[Path] = None, output_dir: Optional[Path] = None):
        """Instantiate object."""
        source_name = "ontologies"
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
            for k in ONTOLOGIES.keys():
                data_file = self.input_base_dir / ONTOLOGIES[k]
                self.parse(k, data_file, k)

    def parse(self, name: str, data_file: Optional[Path], source: str) -> None:
        """
        Process the data_file.

        :param name: Name of the ontology.
        :param data_file: data file to parse.
        :param source: Source name.
        :return: None.
        """
        if data_file.suffixes == [".owl", ".gz"]:
            if NCBITAXON_PREFIX.strip(":").lower() in str(
                data_file
            ):  # or CHEBI_PREFIX.strip(":").lower() in str(data_file):
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
        if name in ["ec", "rhea", "uniprot", "chebi", "upa"]:
            self.post_process(name)

    def decompress(self, data_file):
        """Unzip file."""
        print(f"Decompressing {data_file}...")
        with gzip.open(data_file, "rb") as f_in:
            with open(data_file.parent / data_file.stem, "wb") as f_out:
                shutil.copyfileobj(f_in, f_out)

    def post_process(self, name: str):
        """Post process specific nodes and edges files."""
        nodes_file = self.output_dir / f"{name}_nodes.tsv"
        edges_file = self.output_dir / f"{name}_edges.tsv"

        # Compile a regex pattern that matches any key in SPECIAL_PREFIXES
        pattern = re.compile("|".join(re.escape(key) for key in SPECIAL_PREFIXES.keys()))

        def _replace_special_prefixes(line):
            """Use the pattern to replace all occurrences of the keys with their values."""
            return pattern.sub(lambda match: SPECIAL_PREFIXES[match.group(0)], line)

        if name == "chebi":
            makedirs(ONTOLOGY_XREFS_DIR, exist_ok=True)
            # Get two columns from the nodes file: 'id' and 'xref'
            # The xref column is | separated and contains different prefixes
            # We need to make a 1-to-1 mapping between the prefixes and the id
            with open(nodes_file, "r") as nf, open(CHEBI_XREFS_FILEPATH, "w") as xref_file:

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

        def _replace_id_with_xref(line, xref_index, id_index, category_index):
            """
            Replace node ID with corresponding xref.

            :param line: A line from the original triples.
            :type line: str
            :param xref_index: The index of the tab delimited line with the node xref.
            :type xref_index: int
            :param id_index: The index of the tab delimited line with the node id.
            :type id_index: int
            :param category_index: The index of the tab delimited line with the node category.
            :type category_index: int
            """
            parts = line.strip().split("\t")
            xrefs = parts[xref_index].split("|") if parts[xref_index] != "" else None
            new_lines = []
            if xrefs:
                # Avoid reactions that are given GO xrefs, use Unipathways prefix instead
                xrefs = [xref for xref in xrefs if GO_PREFIX not in xref]
                for xref in xrefs:
                    l_parts = [xref] + ([""] * (len(self.node_header) - 1))
                    self.nodes_dictionary[parts[id_index]].append(xref)
                    l_joined = "\t".join(l_parts)
                    new_lines.append(l_joined)
            else:
                new_lines.append(_replace_category(line, id_index, category_index))
            return new_lines

        def _replace_category(line, id_index, category_index):
            """
            Replace category of a given node.

            :param line: A line from the original triples.
            :type line: str
            :param id_index: The index of the tab delimited line with the node id.
            :type id_index: int
            :param category_index: The index of the tab delimited line with the node category.
            :type category_index: int
            """
            parts = line.strip().split("\t")
            id_substring = _get_unipathways_prefix(parts[id_index])
            # Get defined category
            category = UNIPATHWAYS_CATEGORIES_DICT[id_substring]
            parts[category_index] = category
            # Join the parts back together with a tab separator
            new_line = "\t".join(parts)
            return new_line

        def _replace_triples_with_labels(
            line, subject_index, object_index, predicate_index, relation_index
        ):
            """
            Replace triples labels according to a dictionary lookup. Also replace the predicate and relation.

            :param line: A line from the original triples.
            :type line: str
            :param subject_index: The index of the tab delimited line with the triple subject.
            :type subject_index: int
            :param object_index: The index of the tab delimited line with the triple object.
            :type object_index: int
            :param predicate_index: The index of the tab delimited line with the triple predicate.
            :type predicate_index: int
            :param relation_index: The index of the tab delimited line with the triple relation.
            :type relation_index: int
            """
            parts = line.strip().split("\t")
            # Replace predicate
            new_predicate = get_key_from_value(UNIPATHWAYS_RELATIONS_DICT, parts[relation_index])
            if new_predicate:
                parts[predicate_index] = new_predicate
            # Get new labels for subject
            new_subject_labels = self.nodes_dictionary.get(parts[subject_index])
            # Get new labels for object
            new_object_labels = self.nodes_dictionary.get(parts[object_index])
            new_subj_parts = []
            new_obj_parts = []
            if new_subject_labels:
                for subj_lab in new_subject_labels:
                    new_parts = parts[:]  # Create a copy of parts
                    new_parts[subject_index] = subj_lab  # Assign subj_lab to the appropriate index
                    new_subj_parts.append(new_parts)  # Append the copy to new_subj_parts
            else:
                new_subj_parts.append(parts)
            if new_object_labels:
                for p in new_subj_parts:
                    for obj_lab in new_object_labels:
                        new_parts = p[:]  # Create a copy of parts
                        new_parts[object_index] = (
                            obj_lab  # Assign subj_lab to the appropriate index
                        )
                        new_obj_parts.append(new_parts)  # Append the copy to new_subj_parts
            else:
                new_obj_parts = new_subj_parts
            new_lines = []
            for p in new_obj_parts:
                # Join the parts back together with a tab separator
                l_joined = "\t".join(p)
                new_lines.append(l_joined)
            return new_lines

        def get_key_from_value(dictionary, value):
            """Extract a key from a dictionary with the corresponding value."""
            for key, val in dictionary.items():
                if val == value:
                    return key
            return None  # If value not found

        def _remove_unwanted_prefixes_from_node_xrefs(line, xref_index):
            """
            Remove unwanted prefixes that exist in xrefs for given node.

            :param line: A line from the original triples.
            :type line: str
            :param xref_index: The index of the tab delimited line with the triple xref.
            :type xref_index: int
            """
            # Construct regex pattern
            pattern = r"\b(?:{}):[^\s|]+\|?".format(
                "|".join(re.escape(prefix.rstrip(":")) for prefix in UNIPATHWAYS_IGNORE_PREFIXES)
            )
            # Remove substrings matching the pattern, make all caps since there is variation among node types
            line = re.sub(pattern, "", line, flags=re.IGNORECASE)
            # Remove trailing |
            parts = line.strip().split("\t")
            parts[xref_index] = parts[xref_index].rstrip("|")
            line = "\t".join(parts)
            return line

        def _remove_unwanted_prefixes_from_edges(line):
            """
            Remove unwanted prefixes that exist in a triple.

            :param line: A line from the original triples.
            :type line: str
            """
            for prefix in UNIPATHWAYS_IGNORE_PREFIXES:
                if prefix in line:
                    return None
                else:
                    continue
            return line

        def _get_unipathways_prefix(id):
            """
            Get unipathways prefix of a given node ID if available.

            :param id: The node ID.
            :type line: str
            """
            if "UPa" in id:
                prefix = re.match(r"^(?:OBO:[A-Za-z]+)_?[A-Za-z]+", id).group()
            else:
                prefix = id

            return prefix

        def _check_wanted_pairs(line, subject_index, object_index):
            """
            Check if subject object pair should be included.

            :param line: A line from the original triples.
            :type line: str
            :param subject_index: The index of the tab delimited line with the triple subject.
            :type subject_index: int
            :param object_index: The index of the tab delimited line with the triple object.
            :type object_index: int
            """
            parts = line.strip().split("\t")
            if [
                _get_unipathways_prefix(parts[subject_index]),
                _get_unipathways_prefix(parts[object_index]),
            ] in UNIPATHWAYS_INCLUDE_PAIRS + [
                [UNIPATHWAYS_PATHWAY_PREFIX, UNIPATHWAYS_PATHWAY_PREFIX]
            ]:
                return line
            else:
                return None

        def _create_df_from_pair(df, pair, subject_node=None):
            """
            Create a dataframe from a given dataframe according to substrings in a given pair.

            :param df: A dataframe that contains all triples.
            :type df: pd.DataFrame
            :param pair: A list of the subject, object of the desired triple pattern.
            :type pair: List
            :param subject_node: Optional, a specific subject node ID to base the search on.
            :type subject_node: str
            """
            if subject_node:
                new_df = df[
                    (df[SUBJECT_COLUMN] == subject_node) & (df[OBJECT_COLUMN].str.contains(pair[1]))
                ]
            else:
                new_df = df[
                    (df[SUBJECT_COLUMN].str.contains(pair[0]))
                    & df[OBJECT_COLUMN].str.contains(pair[1])
                ]
            return new_df

        # Function to find all occurrences of the patterns in the DataFrame
        def _collapse_pattern(df):
            """
            Collapse a series of triples into a single triple according to a given pattern.

            :param df: A dataframe that contains all triples.
            :type df: pd.DataFrame
            """
            new_triples = []

            # For reactions, could be Unipathways prefix or Rhea prefix
            tmp_df = _create_df_from_pair(df, UNIPATHWAYS_INCLUDE_PAIRS[0])
            other_tmp_df = _create_df_from_pair(df, UNIPATHWAYS_RHEA_PAIR)
            tmp_df = pd.concat([tmp_df, other_tmp_df], ignore_index=True)
            for _, row in tmp_df.iterrows():
                rhea_id = row[SUBJECT_COLUMN]
                obj = row[OBJECT_COLUMN]
                tmp_df2 = _create_df_from_pair(df, UNIPATHWAYS_INCLUDE_PAIRS[1], obj)
                for _, row in tmp_df2.iterrows():
                    obj = row[OBJECT_COLUMN]
                    tmp_df3 = _create_df_from_pair(df, UNIPATHWAYS_INCLUDE_PAIRS[2], obj)
                    for _, row in tmp_df3.iterrows():
                        upa_id = row[OBJECT_COLUMN]
                        new_triples.append(
                            [
                                rhea_id,
                                PART_OF_PREDICATE,
                                upa_id,
                                UNIPATHWAYS_RELATIONS_DICT[PART_OF_PREDICATE],
                                name + ".json",
                            ]
                        )
            return new_triples

        if name == "upa":
            # Keep track of new node IDs for edges file
            self.nodes_dictionary = defaultdict(list)
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
                        line = _remove_unwanted_prefixes_from_node_xrefs(line, xref_index)
                        # For Reactions only
                        if any(
                            substring in line for substring in [UNIPATHWAYS_REACTION_PREFIX]
                        ):  # UNIPATHWAYS_COMPOUND_PREFIX,UNIPATHWAYS_ENZYMATIC_REACTION_PREFIX]):
                            new_lines = _replace_id_with_xref(
                                line, xref_index, id_index, category_index
                            )
                            for new_line in new_lines:
                                if len(new_line) > 0:
                                    add_lines.append(new_line + "\n")
                        # Add category only for nodes that are not added by another ingest, only Pathways
                        elif any(
                            substring in line for substring in [UNIPATHWAYS_PATHWAY_PREFIX]
                        ):  # ,UNIPATHWAYS_LINEAR_SUB_PATHWAY_PREFIX]):
                            new_line = _replace_category(line, id_index, category_index)
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
                # Write a new edges tsv file with same edge header
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
                        line = _check_wanted_pairs(line, subject_index, object_index)
                        if line:
                            # Remove unwanted prefixes
                            line = _remove_unwanted_prefixes_from_edges(line)
                            if line:
                                new_lines = _replace_triples_with_labels(
                                    line,
                                    subject_index,
                                    object_index,
                                    predicate_index,
                                    relation_index,
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
            # Consolidate paths into 1 edge
            patterns_list = _collapse_pattern(edges_df)
            # Create a DataFrame from the list and specify column names
            collapsed_df = pd.DataFrame(patterns_list, columns=self.edge_header)
            # Add Pathway-pathway triples
            pathways_df = edges_df[
                (edges_df[SUBJECT_COLUMN].str.contains(UNIPATHWAYS_PATHWAY_PREFIX))
                & (edges_df[OBJECT_COLUMN].str.contains(UNIPATHWAYS_PATHWAY_PREFIX))
            ]
            collapsed_df = pd.concat([collapsed_df, pathways_df], ignore_index=True)
            # Rewrite edges file
            collapsed_df.to_csv(edges_file, sep="\t", index=False)

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
