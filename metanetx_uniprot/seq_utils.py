'''
synbiochem (c) University of Manchester 2015

synbiochem is licensed under the MIT License.

To view a copy of this license, visit <http://opensource.org/licenses/MIT/>.

@author:  neilswainston
'''
from collections import defaultdict
import itertools
import operator
import os
import random
import re
import ssl
from subprocess import call
import tempfile
from urllib import parse

from Bio import Seq, SeqIO, SeqRecord
from Bio.Blast import NCBIXML
from Bio.Data import CodonTable
from Bio.Restriction import Restriction, Restriction_Dictionary
from Bio.SeqUtils.MeltingTemp import Tm_NN
import requests
from synbiochem.biochem4j import taxonomy
from synbiochem.utils import thread_utils
import queue

import numpy as np
from tqdm import tqdm
import sys

def get_uniprot_values(uniprot_ids, fields, batch_size, verbose=False,
                       num_threads=0):
    '''Gets dictionary of ids to values from Uniprot.'''
    values = []

    if num_threads:
        thread_pool = thread_utils.ThreadPool(num_threads)

        for i in range(0, len(uniprot_ids), batch_size):
            thread_pool.add_task(_get_uniprot_batch, uniprot_ids, i,
                                batch_size, fields, values, verbose)

        thread_pool.wait_completion()
    else:
        for i in range(0, len(uniprot_ids), batch_size):
            _get_uniprot_batch(uniprot_ids, i, batch_size, fields, values,
                               verbose)

    return {value['Entry']: value for value in values}


def search_uniprot(query, fields, limit=128):
    '''Gets dictionary of ids to values from Uniprot.'''
    values = []

    url = 'http://www.uniprot.org/uniprot/?query=' + parse.quote(query) + \
        '&sort=score&limit=' + str(limit) + \
        '&format=tab&columns=id,' + ','.join([parse.quote(field)
                                              for field in fields])

    _parse_uniprot_data(url, values)

    return values


def _get_uniprot_batch(uniprot_ids, i, batch_size, fields, values, verbose):
    '''Get batch of Uniprot data.'''
    if verbose:
        print('seq_utils: getting Uniprot values ' + str(i) + ' - ' +
              str(min(i + batch_size, len(uniprot_ids))) + ' / ' +
              str(len(uniprot_ids)))

    #If getting values in batch Remove 'accession:' +  from start of join([HERE .....]) and accession: from query=HERE
    batch = uniprot_ids[i:min(i + batch_size, len(uniprot_ids))]
    query = '%20OR%20'.join(['accession:' + uniprot_id for uniprot_id in batch])
    url = 'https://rest.uniprot.org/uniprotkb/search?query=' + query + \
        '&format=tsv&fields=accession%2C' + '%2C'.join([parse.quote(field)
                                              for field in fields])

    _parse_uniprot_data(url, values)


def _parse_uniprot_data(url, values):
    '''Parses Uniprot data.'''
    headers = None

    try:
        resp = requests.get(url, allow_redirects=True)

        for line in resp.iter_lines():
            line = line.decode('utf-8')
            tokens = line.strip().split('\t')

            if headers is None:
                headers = tokens
            else:
                resp = dict(zip(headers, tokens))

                if 'Protein names' in resp:
                    regexp = re.compile(r'(?<=\()[^)]*(?=\))|^[^(][^()]*')
                    names = regexp.findall(resp.pop('Protein names'))
                    resp['Protein names'] = [nme.strip() for nme in names]

                for key in resp:
                    if key.startswith('Cross-reference'):
                        resp[key] = resp[key].split(';')

                if 'Error messages' in resp:
                    print(resp); sys.exit()
                values.append(resp)
    except Exception as err:
        print(err)


def get_uniprot_values_organism(organism_ids, fields, batch_size, verbose=False, num_threads=0):
    values = []

    for i in tqdm(range(0, len(organism_ids), batch_size)):
        values = _get_uniprot_batch_organism(organism_ids, i, batch_size, fields, values,verbose)

    ##Issue: Only returns one enzyme per organism
    #return {value['Organism (ID)']: value for value in values}
    ##Returns list of dicts for each organism-id enzyme entry
    return values

def _get_uniprot_batch_organism(organism_ids, i, batch_size, fields, values, verbose):
    '''Get batch of Uniprot data.'''
    if verbose:
        print('seq_utils: getting Uniprot values ' + str(i) + ' - ' +
              str(min(i + batch_size, len(organism_ids))) + ' / ' +
              str(len(organism_ids)))

    #If getting values in batch Remove 'accession:' +  from start of join([HERE .....]) and accession: from query=HERE
    batch = organism_ids[i:min(i + batch_size, len(organism_ids))]
    query = '%20OR%20'.join(['organism_id:' + organism_id for organism_id in batch])
    url = 'https://rest.uniprot.org/uniprotkb/search?query=' + query + \
        '&format=tsv&size=500&fields=organism_id%2C' + '%2C'.join([parse.quote(field)
    #    '&format=tsv&size=1&fields=organism_id%2C' + '%2C'.join([parse.quote(field)
                                              for field in fields])


    _parse_uniprot_data(url, values)
    return values
