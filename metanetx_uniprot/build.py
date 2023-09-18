'''
SYNBIOCHEM-DB (c) University of Manchester 2015

SYNBIOCHEM-DB is licensed under the MIT License.

To view a copy of this license, visit <http://opensource.org/licenses/MIT/>.

@author:  neilswainston
'''
import multiprocessing
import sys

import chebi_utils, chemical_utils, mnxref_utils, ncbi_taxonomy_utils, reaction_utils, rhea_utils, spectra_utils, utils, seq_utils #, kegg_utils


def build_csv(dest_dir, array_delimiter, num_threads):
    '''Build database CSV files.'''
    writer = utils.Writer(dest_dir)
    reac_man = reaction_utils.ReactionManager()

    # Get Organism data:
    print('Parsing NCBI Taxonomy')
    ncbi_taxonomy_utils.load(reac_man, writer, array_delimiter) #--> writes Organism_Enzyme.tsv

    # Get Chemical and Reaction data.
    # Write chemistry csv files:
    chem_man = chemical_utils.ChemicalManager(array_delimiter=array_delimiter)


    ## Getting error: urllib.error.URLError: <urlopen error ftp error: error_temp('425 Failed to establish connection.')>
    #print('Parsing ChEBI')
    #chebi_utils.load(chem_man, writer)

    ####Using all memory (120+Gb) and eventually is killed
    # Get Spectrum data:
    #print('Parsing spectrum data')
    #spectra_utils.load(writer, chem_man, array_delimiter=array_delimiter)
    

    ####Not including KEGG for now
    # Get Reaction / Enzyme / Organism data:
    #print('Parsing KEGG')
    #kegg_utils.load(reac_man, num_threads=num_threads)
    
 
    print('Parsing Rhea')
    ##Returns rhea reaction ids
    reaction_ids = rhea_utils.load(reac_man, num_threads=num_threads)
    reac_man.write_files(writer) #--> writes Enzyme_Reaction.tsv

    print('Parsing MNXref')
    mnx_loader = mnxref_utils.MnxRefLoader(chem_man, reac_man, writer, reaction_ids, process_ids,ncbi_taxonomy_utils,array_delimiter)
    print('mxn loading')
    mnx_loader.load() #--> writes Reaction_Chemical.tsv, Chemical_Process.tsv, ##NOT WORKING: Process_Disease.tsv, Process_Phenotype.tsv
    
    chem_man.write_files(writer) #--> writes Chemicals.tsv
    

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
