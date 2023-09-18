from kgx.cli.cli_utils import transform
import os

go_plus_file = '/Users/brooksantangelo/Documents/HunterLab/Exploration/biochem4j/kg-microbe/metanetx_uniprot/Files/go-plus.owl'


output_dir = '/Users/brooksantangelo/Documents/HunterLab/biochem4j/biochem4j/'
name = 'go_plus_transformed'

transform(inputs=[go_plus_file], input_format='xml', output= os.path.join(output_dir, name), output_format='tsv')
