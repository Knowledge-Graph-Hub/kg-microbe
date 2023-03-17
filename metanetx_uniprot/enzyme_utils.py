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
        self.__org_enz_rels = []

    def get_nodes(self):
        '''Gets enzyme nodes.'''
        return self.__nodes.values()

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
                enzyme_node['entry'] = uniprot_value['Entry name']

            if 'Protein names' in uniprot_value:
                enzyme_node['names'] = uniprot_value['Protein names']

                if enzyme_node['names']:
                    enzyme_node['name'] = enzyme_node['names'][0]

            if 'EC number' in uniprot_value:
                enzyme_node['ec-code'] = uniprot_value['EC number']

            if organism_id:
                self.__org_enz_rels.append([organism_id, 'expresses',
                                            uniprot_id, {'source': source}])
