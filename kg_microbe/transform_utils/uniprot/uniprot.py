from collections import Counter
import csv
import itertools
import math
import re
import urllib
from urllib.request import urlopen
from urllib import parse
import requests

from numpy import *

import os 
import pandas as pd
from pathlib import Path
from typing import Optional, Union

from kg_microbe.transform_utils.transform import Transform
from tqdm import tqdm
import json
import sys

from kg_microbe.utils.pandas_utils import drop_duplicates

from kg_microbe.transform_utils.constants import (
    ORGANISM_TO_ENZYME_EDGE,
    CHEMICAL_TO_ENZYME_EDGE,
    ENZYME_CATEGORY,
    UNIPROT_GENOME_FEATURES,
    UNIPROT_PREFIX,
    NCBITAXON_PREFIX
)

class UniprotTransform(Transform):

    def __init__(self, input_dir: Optional[Path] = None, output_dir: Optional[Path] = None):

        self.__enz_data = {}

        source_name = UNIPROT_GENOME_FEATURES
        super().__init__(source_name, input_dir, output_dir)
        

    def run(self, data_file: Union[Optional[Path], Optional[str]] = None):

        '''Loads Uniprot data from api, then downloads after running once.'''

        # replace with downloaded data filename for this source
        input_dir = str(self.input_base_dir)+"/"+self.source_name
        #Get all organisms downloaded into raw directory
        ncbi_organisms = []
        for f in os.listdir(input_dir):
            if f.endswith(".json"):
                ncbi_organisms.append(f.split('.json')[0])

        # make directory in data/transformed
        os.makedirs(self.output_dir, exist_ok=True)

        with open(self.output_node_file, "w") as node, open(
            self.output_edge_file, "w"
        ) as edge:
            node_writer = csv.writer(node, delimiter="\t")
            node_writer.writerow(self.node_header)
            edge_writer = csv.writer(edge, delimiter="\t")
            edge_writer.writerow(self.edge_header)

            #Generates __enz_data
            self.add_org_to_enz(input_dir, ncbi_organisms,self.source_name, node_writer, edge_writer)


        drop_duplicates(self.output_node_file)
        drop_duplicates(self.output_edge_file)
        
    #Takes ncbitaxon ids as dict in kgx format
    def add_org_to_enz(self, input_dir, nodes, source, node_writer, edge_writer):
        '''Submit data to the graph.'''


        # Create Organism and Enzyme nodes:
        self.get_uniprot_values_from_file(input_dir, nodes, source, node_writer, edge_writer)

    def get_uniprot_values_from_file(self,input_dir, nodes, source, node_writer, edge_writer):

        with tqdm(total=len(nodes) + 1, desc="Processing files") as progress:
            for i in tqdm(range(len(nodes))):
                org_file = input_dir + '/' + nodes[i] + ".json"
                if not os.path.exists(org_file):
                    print('File does not exist: ',org_file,', exiting.')
                    sys.exit()

                else:
                    with open(org_file, encoding='utf-8') as json_file:
                        values = json.load(json_file)
                        self.write_to_df(values, edge_writer, node_writer)

                progress.set_description(f"Processing Uniprot File: {nodes[i]}.yaml")
                # After each iteration, call the update method to advance the progress bar.
                progress.update()


    def get_uniprot_values_organism(self,organism_ids, fields, keywords,edge_writer, node_writer, batch_size, verbose=False, num_threads=0):
        values = []

        print('querying uniprot for enzymes per organism (' + str(len(organism_ids)) +  ') by batch size (' + str(batch_size) + ')')
        for i in tqdm(range(0, len(organism_ids), batch_size)):
            values = self.get_uniprot_values_from_file(organism_ids, i, batch_size, fields, keywords, values,verbose)
            
            self.write_to_df(values, edge_writer, node_writer)
            print('wrote to dataframe')

    
    def parse_binding_site(self,binding_site_entry):

        chem_list=re.findall(r'/ligand_id="ChEBI:(.*?)";',binding_site_entry)

        return chem_list

    def write_to_df(self,uniprot_values, edge_writer, node_writer):

        ##To return all organism-enzyme entries
        for entry in uniprot_values:

            organism_id = entry['Organism (ID)'] \
                if 'Organism (ID)' in entry.keys() else None

            #Use primary accession number as it's ID does not change, as opposed to Entry Name
            if 'Entry' in entry.keys():
                self.__enz_data['id'] = entry['Entry']


            #example response with multiple protein names: {'Organism (ID)': '100', 'Entry Name': 'A0A4R1H4N5_ANCAQ', 'Entry': 'A0A4R1H4N5', 'Protein names': 'Ubiquinone biosynthesis O-methyltransferase (2-polyprenyl-6-hydroxyphenol methylase) (EC 2.1.1.222) (3-demethylubiquinone 3-O-methyltransferase) (EC 2.1.1.64)', 'EC number': '2.1.1.222; 2.1.1.64'}
            if 'Protein names' in entry:
                self.__enz_data['name'] = entry['Protein names'].split('(EC')[0]
                
                ###TO DO: add synonyms here
                #print(entry['Protein names'])
                #self.__enz_data['synonyms'] = entry['Protein names'][1:].str.replace('')
                #print(self.__enz_data['synonyms'])

                #Set name as first name mentioned
                #if 'synonyms' in entry.keys() and len :
                #    self.__enz_data['name'] = entry['names'][0]

            if 'EC number' in entry:
                self.__enz_data['EC number'] = entry['EC number'].replace(';','|')

            chem_list = []
            if 'Binding site' in entry:
                chem_list = self.parse_binding_site(entry['Binding site'])

            if organism_id:

                edges_data_to_write = [
                                NCBITAXON_PREFIX+str(organism_id),
                                ORGANISM_TO_ENZYME_EDGE,
                                UNIPROT_PREFIX+':'+self.__enz_data['id'],
                                '',
                                self.source_name
                            ]

                edge_writer.writerow(edges_data_to_write)

                if len(chem_list) > 0:
                    for chem in chem_list:
                        
                        edges_data_to_write = [
                            chem,
                            CHEMICAL_TO_ENZYME_EDGE,
                            UNIPROT_PREFIX+':'+self.__enz_data['id'],
                            '',
                            self.source_name
                        ]

                        edge_writer.writerow(edges_data_to_write)


            nodes_data_to_write = [
                    UNIPROT_PREFIX+':'+self.__enz_data['id'], ENZYME_CATEGORY,self.__enz_data['name'],'','',self.source_name,''
                    ]

            node_writer.writerow(nodes_data_to_write)
