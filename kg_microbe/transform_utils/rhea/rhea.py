from collections import Counter
import csv
import itertools
import math
import re
import urllib
from urllib.request import urlopen
import requests

import numpy
#from subliminal import balance

#import namespace_utils
import os 
import pandas as pd
from pathlib import Path
from typing import Optional, Union

from kg_microbe.transform_utils.transform import Transform
from tqdm import tqdm

from kg_microbe.utils.pandas_utils import drop_duplicates

from kg_microbe.transform_utils.constants import (
    REACTION_CATEGORY,
    ENZYME_CATEGORY,
    PATHWAY_CATEGORY,
    REACTION_TO_ENZYME_EDGE,
    REACTION_TO_PROCESS_EDGE
)


RHEA_FILES = [
    'rhea2uniprot_sprot.tsv',
    'rhea2go.tsv'
]



#Write out Reaction_Chemical rels, Reaction, Chemical nodes

class RheaTransform(Transform):

    def __init__(self, input_dir: Optional[Path] = None, output_dir: Optional[Path] = None):

        source_name = "Rhea"
        super().__init__(source_name, input_dir, output_dir)
        

    def run(self, data_file: Union[Optional[Path], Optional[str]] = None):

        # make directory in data/transformed
        os.makedirs(self.output_dir, exist_ok=True)

        with open(self.output_node_file, "w") as node, open(
            self.output_edge_file, "w"
        ) as edge:
            node_writer = csv.writer(node, delimiter="\t")
            node_writer.writerow(self.node_header)
            edge_writer = csv.writer(edge, delimiter="\t")
            edge_writer.writerow(self.edge_header)

            for k in RHEA_FILES:
                data_file = self.input_base_dir / k
                data = self._parse(data_file)
                if 'rhea2uniprot' in str(data_file):
                    self.write_to_df(str(data_file), data, ENZYME_CATEGORY, REACTION_TO_ENZYME_EDGE, node_writer, edge_writer,'Uniprot:')
                if 'rhea2go' in str(data_file):
                    self.write_to_df(str(data_file), data, PATHWAY_CATEGORY, REACTION_TO_PROCESS_EDGE, node_writer, edge_writer)

        drop_duplicates(self.output_node_file)
        drop_duplicates(self.output_edge_file)
        
    def _parse(self,filename):
        '''Parses file.'''
        data = {}

        with open(filename, 'r') as textfile:
            next(textfile)

            for line in textfile:
                tokens = line.split('\t')

                if len(tokens) == 4:
                    uniprot_id = tokens[3].strip()

                    if not tokens[0] or not tokens[2]:
                        print(','.join(tokens))

                    self._add(data, tokens[0], uniprot_id)
                    self._add(data, tokens[2], uniprot_id)

        return data

    def _add(self,data, rhea_id, uniprot_id):
        '''Adds Rhea id and Uniprot id to data.'''
        if rhea_id in data:
            data[rhea_id].append(uniprot_id)
        else:
            data[rhea_id] = [uniprot_id] #GO id for rhea2go file

    def write_to_df(self, filename, data, val_type, relationship, node_writer, edge_writer,val_header=''):

        with tqdm(total=len(data.keys()) + 1, desc="Processing file"+filename) as progress:
            for reac_id, vals in data.items():
                #reac_id = self.add_reaction(source, reac_id, {})
                reac = self.source_name+':'+reac_id

                nodes_data_to_write = [
                        reac, REACTION_CATEGORY, reac,'','',self.source_name,''
                        ]

                node_writer.writerow(nodes_data_to_write)

                for val in vals:
                    edges_data_to_write = [reac, relationship,
                                                val_header+val,
                                                '',
                                                self.source_name
                                                ]
                    
                    edge_writer.writerow(edges_data_to_write)

                    #Will not write GO nodes which are duplicate
                    #For Uniprot values need to get name
                    if val_header == 'Uniprot:':
                        nodes_data_to_write = [
                            val_header+val, val_type, val_header+val,'','',self.source_name,''
                            ]

                        node_writer.writerow(nodes_data_to_write)

                progress.set_description(f"Processing Rhea data: {reac}")
                # After each iteration, call the update method to advance the progress bar.
                progress.update()
