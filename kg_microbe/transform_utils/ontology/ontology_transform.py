"""Ontology transform module."""

import gzip
import re
import shutil
from os import makedirs
from pathlib import Path
from typing import Optional, Union
from collections import defaultdict

# from kgx.transformer import Transformer
from kgx.cli.cli_utils import transform

from kg_microbe.transform_utils.constants import (
    CATEGORY_COLUMN,
    CHEBI_XREFS_FILEPATH,
    EXCLUSION_TERMS_FILE,
    ID_COLUMN,
    NCBITAXON_PREFIX,
    OBJECT_COLUMN,
    ONTOLOGY_XREFS_DIR,
    PREDICATE_COLUMN,
    ROBOT_REMOVED_SUFFIX,
    SPECIAL_PREFIXES,
    SUBJECT_COLUMN,
    UNIPATHWAYS_CATEGORIES_DICT,
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
    "ncbitaxon": "ncbitaxon.owl.gz",
    "chebi": "chebi.owl.gz",
    "envo": "envo.json",
    "go": "go.json",
    "rhea": "rhea.json.gz",
    "ec": "ec.json",
    "uniprot": "uniprot.json.gz",
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
        # TODO rewrite existing nodes and edges files, not to new file. Using this for comparison and testing
        new_nodes_file = self.output_dir / f"{name}_transformed_nodes.tsv"
        new_edges_file = self.output_dir / f"{name}_transformed_edges.tsv"

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

        def _replace_id_with_xref(line,xref_index,id_index,category_index):
            """Replace ID with xref."""
            parts = line.strip().split("\t")
            xrefs = parts[xref_index].split("|") if parts[xref_index] != "" else None
            
            new_lines = []
            if xrefs:
                for xref in xrefs:
                    l_parts = [xref] + ([""] * (len(self.node_header) - 1))
                    self.nodes_dictionary[parts[id_index]].append(xref)
                    l = "\t".join(l_parts)
                    new_lines.append(l)
            else:
                new_lines.append(_replace_category(line,id_index,category_index))
            '''if len(new_lines) == 0: 
                new_lines = line'''
            return new_lines
        
        def _replace_category(line,id_index,category_index):
            """Replace category."""
            parts = line.strip().split("\t")
            id_substring = parts[id_index].split('0')[0]
            # Get defined category
            category = UNIPATHWAYS_CATEGORIES_DICT[id_substring]
            parts[category_index] = category
            # Join the parts back together with a tab separator
            new_line = "\t".join(parts)

            return new_line
        
        def _replace_triples_with_labels(line,subject_object_indices,predicate_index):
            """Replace triples labels."""
            parts = line.strip().split("\t")
            # Get new labels for subject, object
            for i in subject_object_indices:
                new_label = self.nodes_dictionary.get(parts[i])
                if new_label:
                    for lab in new_label:
                        parts[i] = new_label
            # Get new predicate
            new_predicate = self.predicates_dictionary[parts[predicate_index]]
            # Join the parts back together with a tab separator
            new_line = "\t".join(parts)

            return new_line
            
        if name == "upa":
            # TODO finish this, waiting on relations from downloaded file
            # New predicates for unipathways 
            self.predicates_dictionary = {
                "biolink:part_of"
            }
            # Keep track of new node IDs for edges file
            self.nodes_dictionary = defaultdict(list)
            with open(nodes_file, "r") as nf, open(new_nodes_file, "w") as new_nf:
                # Write a new nodes tsv file with same node header
                new_nf.write("\t".join(self.node_header) + "\n")
                for line in nf:
                    if line.startswith("id"):
                        # get the index for the term 'id'
                        id_index = line.strip().split("\t").index(ID_COLUMN)
                        # get the index for the term 'xref'
                        xref_index = line.strip().split("\t").index(XREF_COLUMN)
                        # get the index for the term 'category'
                        category_index = line.strip().split("\t").index(CATEGORY_COLUMN)
                    else:
                        # For Chemicals, Reactions, and Enzymatic Reactions
                        if any(substring in line for substring in ['OBO:UPa_UPC','OBO:UPa_UCR','OBO:UPa_UER']):
                        #if line.contains('OBO:UPa_UPC'|'OBO:UPa_UCR'|'OBO:UPa_UER'):
                            new_lines = _replace_id_with_xref(line,xref_index,id_index,category_index)
                            #import pdb;pdb.set_trace()
                            for l in new_lines:
                                new_nf.write(l + "\n")
                        # Add category only for nodes that are not added by another ingest
                        elif any(substring in line for substring in ['OBO:UPa_UPA','OBO:UPa_ULS']):
                            new_line = _replace_category(line,id_index,category_index)
                            new_nf.write(new_line + "\n")
                        else:
                            new_nf.write(line + "\n")
            with open(edges_file, "r") as ef, open(new_edges_file, "w") as new_ef:
                # TODO finish this, waiting on relations from downloaded file
                # Write a new edges tsv file with same edge header
                new_ef.write("\t".join(self.edge_header) + "\n")
                for line in ef:
                    if line.startswith("id"):
                        # get the index for the 'subject'
                        subject_index = line.strip().split("\t").index(SUBJECT_COLUMN)
                        # get the index for the 'predicate'
                        predicate_index = line.strip().split("\t").index(PREDICATE_COLUMN)
                        # get the index for the 'object'
                        object_index = line.strip().split("\t").index(OBJECT_COLUMN)
                        subject_object_indices = [subject_index,object_index]
                    else:
                        new_lines = _replace_triples_with_labels(line,subject_object_indices,predicate_index)


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
