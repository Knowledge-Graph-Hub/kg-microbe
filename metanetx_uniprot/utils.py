'''
synbiochem (c) University of Manchester 2016

synbiochem is licensed under the MIT License.

To view a copy of this license, visit <http://opensource.org/licenses/MIT/>.

@author:  neilswainston
'''
# pylint: disable=invalid-name
# pylint: disable=too-many-arguments
import os
from shutil import rmtree

import pandas as pd


class Writer(object):
    '''CSV file writer class for biochem4j files.'''

    def __init__(self, dest_dir):
        self.__nodes_dir = os.path.join(os.path.abspath(dest_dir), 'nodes')
        self.__rels_dir = os.path.join(os.path.abspath(dest_dir), 'rels')

        if os.path.exists(self.__nodes_dir):
            rmtree(self.__nodes_dir)

        os.makedirs(self.__nodes_dir)

        if os.path.exists(self.__rels_dir):
            rmtree(self.__rels_dir)

        os.makedirs(self.__rels_dir)

    def write_nodes(self, nodes, group, separator=';'):
        '''Writes Nodes to csv file.'''
        if not nodes:
            return None

        df = pd.DataFrame(nodes)
        df.dropna(axis=1, how='all', inplace=True)

        filename = os.path.join(self.__nodes_dir, group + '.csv')
        df.to_csv(filename, index=False, encoding='utf-8', sep=separator)
        print('just wrote: ',filename)

        return filename

    def write_rels(self, rels, group_start, group_end, separator=';'):
        '''Writes Relationships to csv file.'''
        if not rels:
            return None

        columns = [':START_ID(' + group_start + ')',
                   ':TYPE',
                   ':END_ID(' + group_end + ')']

        if len(rels[0]) > 3:
            columns.append('PROPERTIES')

        df = pd.DataFrame(rels, columns=columns)

        if len(rels[0]) > 3:
            props_df = pd.DataFrame(list(df['PROPERTIES']))
            df.drop('PROPERTIES', axis=1, inplace=True)
            df = df.join(props_df)

        filename = os.path.join(self.__rels_dir,
                                group_start + '_' + group_end + '.csv')
        df.to_csv(filename, index=False, encoding='utf-8', sep=separator)
        print('just wrote: ',filename)

        return filename
