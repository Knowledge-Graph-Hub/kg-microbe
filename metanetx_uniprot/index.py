'''
SYNBIOCHEM-DB (c) University of Manchester 2015

SYNBIOCHEM-DB is licensed under the MIT License.

To view a copy of this license, visit <http://opensource.org/licenses/MIT/>.

@author:  neilswainston
'''
import os
import subprocess
import sys


def index_db(db_loc):
    '''Index database.'''
    directory = os.path.dirname(os.path.realpath(__file__))
    filename = os.path.join(directory, 'init.cql')

    with open(filename, 'rU') as init_file:
        for line in init_file:
            params = ['neo4j-shell', '-path', db_loc, '-c', line.strip()]
            subprocess.call(params)


def main(argv):
    '''main method'''
    index_db(argv[0])


if __name__ == '__main__':
    main(sys.argv[1:])
