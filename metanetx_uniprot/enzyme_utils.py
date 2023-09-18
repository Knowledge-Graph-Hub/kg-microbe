'''
SYNBIOCHEM-DB (c) University of Manchester 2015

SYNBIOCHEM-DB is licensed under the MIT License.

To view a copy of this license, visit <http://opensource.org/licenses/MIT/>.

@author:  neilswainston
'''
#from synbiochem.utils import seq_utils
import queue
from seq_utils import *


class EnzymeManager(object):
    '''Class to implement a manager of Enzyme data.'''

    def __init__(self):
        '''Constructor.'''
        self.__nodes = {}
        self.__node_enzymes = {}
        self.__org_enz_rels = []

    def get_nodes(self):
        '''Gets enzyme nodes.'''
        return self.__nodes.values()

    def get_enz_nodes(self):
        #nodes_enzymes_df = pd.DataFrame(self.__node_enzymes.items(), columns=['entity_uri', 'label'])
        return self.__node_enzymes.values()


    def get_org_enz_rels(self):
        '''Gets organism-to-enzyme relationships.'''
        return self.__org_enz_rels

    def add_uniprot_data(self, enzyme_ids, source, num_threads=0):
        '''Gets Uniprot data.'''

        #fields = ['entry name', 'protein names', 'organism-id', 'ec']
        fields = ['id', 'protein_name', 'organism_id', 'ec']
        enzyme_ids = [enzyme_id for enzyme_id in enzyme_ids
                      if enzyme_id not in self.__nodes]
        uniprot_values = get_uniprot_values(enzyme_ids, fields,
                                                      batch_size=128,  # changed to 128 from 512
                                                      verbose=False,  #Changed to False
                                                      num_threads=num_threads)

        for uniprot_id, uniprot_value in uniprot_values.items():
            enzyme_node = {':LABEL': 'Enzyme',
                           'uniprot:ID(Enzyme)': uniprot_id}
            self.__nodes[uniprot_id] = enzyme_node

            organism_id = uniprot_value.pop('Organism (ID)') \
                if 'Organism (ID)' in uniprot_value else None

            if 'Entry name' in uniprot_value:
                enzyme_node['entry'] = 'Uniprot:'+uniprot_value['Entry name']

            if 'Protein names' in uniprot_value:
                enzyme_node['names'] = 'Uniprot:'+uniprot_value['Protein names']

                if enzyme_node['names']:
                    enzyme_node['name'] = enzyme_node['names'][0]

            if 'EC number' in uniprot_value:
                enzyme_node['ec-code'] = uniprot_value['EC number']

            if organism_id:
                self.__org_enz_rels.append([organism_id, 'expresses',
                                            uniprot_id, {'source': source}])

    #Builds into reactionManager
    def add_uniprot_data_organism(self, organism_ids, source, num_threads=0):
        '''Gets Uniprot data.'''

        fields = ['id', 'accession','protein_name', 'organism_id', 'ec']
        print('querying uniprot for enzymes per organism')
        ##Uniprot returns list of dicts for each entry
        uniprot_values = get_uniprot_values_organism(organism_ids, fields, 
                                                                   batch_size=128,
                                                                   verbose=False,
                                                                   num_threads=num_threads)

        print('adding uniprot data to graph')
        
        ##To return all organism-enzyme entries
        for entry in tqdm(uniprot_values):
            enzyme_node = {':LABEL': 'Enzyme',
                        'uniprot:ID(Enzyme)': entry['Entry']}
            self.__nodes[entry['Entry']] = enzyme_node

            organism_id = entry['Organism (ID)'] \
                if 'Organism (ID)' in entry.keys() else None

            if 'Entry' in entry.keys():
                enzyme_node['entry'] = entry['Entry']

            if 'Protein names' in entry:
                enzyme_node['names'] = entry['Protein names'][0]

                if 'names' in entry.keys():
                    enzyme_node['name'] = entry['names'][0]

            if 'EC number' in entry:
                enzyme_node['ec-code'] = entry['EC number']

            if organism_id:
                self.__org_enz_rels.append(['NCBITaxon:'+organism_id, 'expresses','Uniprot:'+entry['Entry'], {'source': source}])

            self.__node_enzymes['Uniprot:'+entry['Entry']] = {'entity_uri':'Uniprot:'+entry['Entry'], 'label':enzyme_node['names']}

        return uniprot_values
        