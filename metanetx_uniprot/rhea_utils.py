'''
SYNBIOCHEM-DB (c) University of Manchester 2015

SYNBIOCHEM-DB is licensed under the MIT License.

To view a copy of this license, visit <http://opensource.org/licenses/MIT/>.

@author:  neilswainston
'''
import tempfile
import urllib
from urllib.request import urlretrieve
import os


__RHEA_URL = 'ftp://ftp.expasy.org/databases/rhea/tsv/rhea2uniprot%5Fsprot.tsv'
#For test, also update load function
#__RHEA_URL = os.getcwd()+'/TestingFiles/rhea2uniprot_sprot.txt'

__RHEA_GO_URL = 'ftp://ftp.expasy.org/databases/rhea/tsv/rhea2go.tsv'
#__RHEA_GO_URL = os.getcwd()+'/TestingFiles/rhea2go_NOTREAL.txt'

def load(reaction_manager, source=__RHEA_URL, go_source = __RHEA_GO_URL, num_threads=0):
    '''Loads Rhea data.'''
    # Parse data:
    
    temp_file = tempfile.NamedTemporaryFile()
    urlretrieve(source, temp_file.name)
    data = _parse(temp_file.name)
    
    
    temp_file = tempfile.NamedTemporaryFile()
    urlretrieve(go_source, temp_file.name)
    go_data = _parse(temp_file.name)

    ##If using test data
    #data = _parse(source)
    #go_data = _parse(go_source)
    ######Not sure why source is Rhea here, calls to UniProt
    #Remove, since this goes from rhea2uniprot to uniprot enzymes. use add_org_to_enz function in ncbi_taxonomy_utils instead
    #reaction_manager.add_react_to_enz(data, 'rhea', num_threads)
    reaction_ids,process_ids = reaction_manager.add_react_to_enz_organism(data, 'rhea', go_data, num_threads) 

    return reaction_ids,process_ids


def _parse(filename):
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

                _add(data, tokens[0], uniprot_id)
                _add(data, tokens[2], uniprot_id)

    return data


def _add(data, rhea_id, uniprot_id):
    '''Adds Rhea id and Uniprot id to data.'''
    if rhea_id in data:
        data[rhea_id].append(uniprot_id)
    else:
        data[rhea_id] = [uniprot_id]
