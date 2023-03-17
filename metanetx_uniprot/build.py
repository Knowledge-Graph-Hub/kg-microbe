'''
SYNBIOCHEM-DB (c) University of Manchester 2015

SYNBIOCHEM-DB is licensed under the MIT License.

To view a copy of this license, visit <http://opensource.org/licenses/MIT/>.

@author:  neilswainston
'''
import multiprocessing
import sys

import chebi_utils, chemical_utils, mnxref_utils, \
    ncbi_taxonomy_utils, reaction_utils, rhea_utils, spectra_utils, utils, seq_utils #, kegg_utils


def build_csv(dest_dir, array_delimiter, num_threads):
    '''Build database CSV files.'''
    writer = utils.Writer(dest_dir)
    
    # Get Organism data:
    print('Parsing NCBI Taxonomy')
    #ncbi_taxonomy_utils.load(writer, array_delimiter)
    
    # Get Chemical and Reaction data.
    # Write chemistry csv files:
    chem_man = chemical_utils.ChemicalManager(array_delimiter=array_delimiter)
    reac_man = reaction_utils.ReactionManager()


    #print('Parsing MNXref')
    mnx_loader = mnxref_utils.MnxRefLoader(chem_man, reac_man, writer)
    mnx_loader.load()
    
    print('Parsing ChEBI')
    #chebi_utils.load(chem_man, writer)

    ####Using all memory (120+Gb) and eventually is killed
    # Get Spectrum data:
    #print('Parsing spectrum data')
    #spectra_utils.load(writer, chem_man, array_delimiter=array_delimiter)
    
    #chem_man.write_files(writer)

    ####Not including KEGG for now
    # Get Reaction / Enzyme / Organism data:
    #print('Parsing KEGG')
    #kegg_utils.load(reac_man, num_threads=num_threads)
    
 
    print('Parsing Rhea')
    #rhea_utils.load(reac_man, num_threads=num_threads)
    #reac_man.write_files(writer)
    

def main(args):
    '''main method'''
    num_threads = 0

    if len(args) > 2:
        try:
            num_threads = int(args[2])
        except ValueError:
            if args[2] == 'True':
                num_threads = multiprocessing.cpu_count()

    print('Running build with ' + str(num_threads) + ' threads')

    build_csv(args[0], args[1], num_threads)


if __name__ == '__main__':
    main(sys.argv[1:])
