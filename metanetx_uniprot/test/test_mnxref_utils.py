'''
synbiochem (c) University of Manchester 2015

synbiochem is licensed under the MIT License.

To view a copy of this license, visit <http://opensource.org/licenses/MIT/>.

@author:  neilswainston
'''
# pylint: disable=too-many-public-methods
import unittest

from sbcdb.mnxref_utils import MnxRefReader


class TestMnxRefReader(unittest.TestCase):
    '''Test class for MnxRefReader.'''

    def setUp(self):
        unittest.TestCase.setUp(self)
        reader = MnxRefReader()
        self.__chem_data = reader.get_chem_data()
        self.__reac_data = reader.get_reac_data()

    def test_get_chem_data(self):
        '''Tests get_chem_data method.'''
        self.assertEquals(self.__chem_data['MNXM1354']['chebi'], 'CHEBI:58282')

    def test_get_reac_data(self):
        '''Tests get_chem_data method.'''
        eqn = '1 MNXM1 + 1 MNXM6 + 1 MNXM97401 = 1 MNXM5 + 1 MNXM97393'
        self.assertEquals(self.__reac_data['MNXR62989']['equation'], eqn)


if __name__ == "__main__":
    # import sys;sys.argv = ['', 'Test.testName']
    unittest.main()
