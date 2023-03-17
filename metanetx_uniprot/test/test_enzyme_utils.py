'''
synbiochem (c) University of Manchester 2015

synbiochem is licensed under the MIT License.

To view a copy of this license, visit <http://opensource.org/licenses/MIT/>.

@author:  neilswainston
'''
# pylint: disable=too-many-public-methods
import unittest

from sbcdb.enzyme_utils import EnzymeManager


class TestEnzymeManager(unittest.TestCase):
    '''Test class for EnzymeManager.'''

    def setUp(self):
        unittest.TestCase.setUp(self)
        self.__manager = EnzymeManager()

    def test_add_uniprot_data(self):
        '''Tests add_uniprot_data method.'''
        enzyme_ids = ['P19367', 'Q2KNB7']

        # Test unthreaded:
        self.__manager.add_uniprot_data(enzyme_ids, source='test')
        self.assertEqual(len(enzyme_ids), len(self.__manager.get_nodes()))

        # Test threaded:
        self.__manager.add_uniprot_data(enzyme_ids, source='test',
                                        num_threads=24)
        self.assertEqual(len(enzyme_ids), len(self.__manager.get_nodes()))


if __name__ == "__main__":
    # import sys;sys.argv = ['', 'Test.testName']
    unittest.main()
