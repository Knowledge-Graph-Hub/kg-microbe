'''
SYNBIOCHEM-DB (c) University of Manchester 2015

SYNBIOCHEM-DB is licensed under the MIT License.

To view a copy of this license, visit <http://opensource.org/licenses/MIT/>.

@author:  neilswainston
'''
from collections import defaultdict
import urllib
from urllib.request import urlopen

from synbiochem.utils import thread_utils


def load(reaction_manager, organisms=None, num_threads=0):
    '''Loads KEGG data.'''

    if organisms is None:
        organisms = \
            sorted([line.split()[1] for line in
                    urllib.urlopen('http://rest.kegg.jp/list/organism')])

    # EC to gene, gene to Uniprot:
    ec_genes, gene_uniprots = _get_gene_data(organisms, num_threads)

    data = defaultdict(list)

    # KEGG Reaction to EC:
    kegg_reac_ec = _parse_url('http://rest.kegg.jp/link/ec/reaction')

    for kegg_reac, ec_terms in kegg_reac_ec.items():
        for ec_term in ec_terms:
            if ec_term in ec_genes:
                for gene in ec_genes[ec_term]:
                    if gene in gene_uniprots:
                        uniprots = [val[3:] for val in gene_uniprots[gene]]
                        data[kegg_reac[3:]].extend(uniprots)

    reaction_manager.add_react_to_enz(data, 'kegg.reaction', num_threads)


def _get_gene_data(organisms, num_threads):
    '''Gets gene data.'''
    ec_genes = defaultdict(list)
    gene_uniprots = defaultdict(list)

    if num_threads:
        thread_pool = thread_utils.ThreadPool(num_threads)

        for org in organisms:
            thread_pool.add_task(_parse_organism, org, ec_genes, gene_uniprots)

        thread_pool.wait_completion()
    else:
        for org in organisms:
            _parse_organism(org, ec_genes, gene_uniprots)

    return ec_genes, gene_uniprots


def _parse_organism(org, ec_genes, gene_uniprots):
    '''Parse organism.'''
    print 'KEGG: loading ' + org

    for key, value in _parse_url('http://rest.kegg.jp/link/' + org.lower() +
                                 '/enzyme').items():
        ec_genes[key].extend(value)

    for key, value in _parse_url('http://rest.kegg.jp/conv/uniprot/' +
                                 org.lower()).items():
        gene_uniprots[key].extend(value)


def _parse_url(url, attempts=16):
    '''Parses url to form key to list of values dictionary.'''
    data = defaultdict(list)

    for _ in range(attempts):
        try:
            for line in urllib.urlopen(url):
                tokens = line.split()

                if len(tokens) > 1:
                    data[tokens[0]].append(tokens[1])

            return data
        except urllib.URLError as err:
            # Take no action, but try again...
            print '\t'.join([url, str(err)])

    return data
