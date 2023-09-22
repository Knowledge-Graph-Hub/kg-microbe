'''
libChEBIpy (c) University of Manchester 2015

libChEBIpy is licensed under the MIT License.

To view a copy of this license, visit <http://opensource.org/licenses/MIT/>.

@author:  neilswainston
'''
import calendar
import datetime
import gzip
import io
import os.path
import re
import tempfile
import zipfile

import six.moves.urllib.parse as urlparse
from six.moves.urllib.request import urlretrieve, urlcleanup

from ._comment import Comment
from ._compound_origin import CompoundOrigin
from ._database_accession import DatabaseAccession
from ._formula import Formula
from ._name import Name
from ._reference import Reference
from ._relation import Relation
from ._structure import Structure
import wget


__ALL_IDS = {}
__ALL_NAMES = {}
__COMMENTS = {}
__COMPOUND_ORIGINS = {}
__CHARGES = {}
__CREATED_BYS = {}
__DATABASE_ACCESSIONS = {}
__DEFAULT_STRUCTURE_IDS = []
__DEFINITIONS = {}
__FORMULAE = {}
__INCHIS = {}
__INCHI_KEYS = {}
__INCOMINGS = {}
__MASSES = {}
__MODIFIED_ONS = {}
__NAMES = {}
__OUTGOINGS = {}
__PARENT_IDS = {}
__SMILES = {}
__SOURCES = {}
__STARS = {}
__STATUSES = {}

__DOWNLOAD_PARAMS = {'path': os.path.join(os.path.expanduser('~'), 'libChEBI'),
                     'auto_update': True}


def set_download_cache_path(path):
    '''Sets download cache path.'''
    __DOWNLOAD_PARAMS['path'] = path


def set_auto_update(auto_update):
    '''Sets auto update flag.'''
    __DOWNLOAD_PARAMS['auto_update'] = auto_update


def get_formulae(chebi_id):
    '''Returns formulae'''
    if not __FORMULAE:
        __parse_chemical_data()

    return __FORMULAE[chebi_id] if chebi_id in __FORMULAE else []


def get_all_formulae(chebi_ids):
    '''Returns all formulae'''
    all_formulae = [get_formulae(chebi_id) for chebi_id in chebi_ids]
    return [x for sublist in all_formulae for x in sublist]


def get_mass(chebi_id):
    '''Returns mass'''
    if not __MASSES:
        __parse_chemical_data()

    return __MASSES[chebi_id] if chebi_id in __MASSES else float('NaN')


def get_charge(chebi_id):
    '''Returns charge'''
    if not __CHARGES:
        __parse_chemical_data()

    return __CHARGES[chebi_id] if chebi_id in __CHARGES else float('NaN')


def __parse_chemical_data():
    '''Gets and parses file'''
    filename = get_file('chemical_data.tsv')

    with io.open(filename, 'r', encoding='cp1252') as textfile:
        next(textfile)

        for line in textfile:
            tokens = line.strip().split('\t')

            if tokens[3] == 'FORMULA':
                # Many seemingly contradictory formulae exist,
                # depending upon the source database
                chebi_id = int(tokens[1])

                if chebi_id not in __FORMULAE:
                    __FORMULAE[chebi_id] = []

                # Append formula:
                form = Formula(tokens[4], tokens[2])
                __FORMULAE[chebi_id].append(form)

            elif tokens[3] == 'MASS':
                __MASSES[int(tokens[1])] = float(tokens[4])

            elif tokens[3] == 'CHARGE':
                __CHARGES[int(tokens[1])] = int(tokens[4]
                                                if tokens[4][-1] != '-'
                                                else '-' + tokens[4][:-1])


def get_comments(chebi_id):
    '''Returns comments'''
    if not __COMMENTS:
        __parse_comments()

    return __COMMENTS[chebi_id] if chebi_id in __COMMENTS else []


def get_all_comments(chebi_ids):
    '''Returns all comments'''
    all_comments = [get_comments(chebi_id) for chebi_id in chebi_ids]
    return [x for sublist in all_comments for x in sublist]


def __parse_comments():
    '''Gets and parses file'''
    filename = get_file('comments.tsv')

    with io.open(filename, 'r', encoding='cp1252') as textfile:
        next(textfile)

        for line in textfile:
            tokens = line.strip().split('\t')
            chebi_id = int(tokens[1])

            if chebi_id not in __COMMENTS:
                __COMMENTS[chebi_id] = []

            # Append Comment:
            com = Comment(tokens[3],
                          tokens[4],
                          tokens[5],
                          datetime.datetime.strptime(tokens[2], '%Y-%M-%d'))

            __COMMENTS[chebi_id].append(com)


def get_compound_origins(chebi_id):
    '''Returns compound origins'''
    if not __COMPOUND_ORIGINS:
        __parse_compound_origins()
    return __COMPOUND_ORIGINS[chebi_id] if chebi_id in \
        __COMPOUND_ORIGINS else []


def get_all_compound_origins(chebi_ids):
    '''Returns all compound origins'''
    all_compound_origins = [get_compound_origins(chebi_id)
                            for chebi_id in chebi_ids]
    return [x for sublist in all_compound_origins for x in sublist]


def __parse_compound_origins():
    '''Gets and parses file'''
    filename = get_file('compound_origins.tsv')

    with io.open(filename, 'r', encoding='cp1252') as textfile:
        next(textfile)

        for line in textfile:
            tokens = line.strip().split('\t')

            if len(tokens) > 10:
                chebi_id = int(tokens[1])

                if chebi_id not in __COMPOUND_ORIGINS:
                    __COMPOUND_ORIGINS[chebi_id] = []

                # Append CompoundOrigin:
                comp_orig = CompoundOrigin(tokens[2], tokens[3],
                                           tokens[4], tokens[5],
                                           tokens[6], tokens[7],
                                           tokens[8], tokens[9],
                                           tokens[10])
                __COMPOUND_ORIGINS[chebi_id].append(comp_orig)


def get_status(chebi_id):
    '''Returns status'''
    if not __STATUSES:
        __parse_compounds()

    return __STATUSES[chebi_id] if chebi_id in __STATUSES else None


def get_source(chebi_id):
    '''Returns source'''
    if not __SOURCES:
        __parse_compounds()

    return __SOURCES[chebi_id] if chebi_id in __SOURCES else None


def get_parent_id(chebi_id):
    '''Returns parent id'''
    if not __PARENT_IDS:
        __parse_compounds()

    return __PARENT_IDS[chebi_id] if chebi_id in __PARENT_IDS else float('NaN')


def get_all_ids(chebi_id):
    '''Returns all ids'''
    if not __ALL_IDS:
        __parse_compounds()

    return __ALL_IDS[chebi_id] if chebi_id in __ALL_IDS else []


def get_name(chebi_id):
    '''Returns name'''
    if not __NAMES:
        __parse_compounds()

    return __NAMES[chebi_id] if chebi_id in __NAMES else None


def get_definition(chebi_id):
    '''Returns definition'''
    if not __DEFINITIONS:
        __parse_compounds()

    return __DEFINITIONS[chebi_id] if chebi_id in __DEFINITIONS else None


def get_modified_on(chebi_id):
    '''Returns modified on'''
    if not __MODIFIED_ONS:
        __parse_compounds()

    return __MODIFIED_ONS[chebi_id] if chebi_id in __MODIFIED_ONS else None


def get_all_modified_on(chebi_ids):
    '''Returns all modified on'''
    all_modified_ons = [get_modified_on(chebi_id) for chebi_id in chebi_ids]
    all_modified_ons = [modified_on for modified_on in all_modified_ons
                        if modified_on is not None]
    return None if not all_modified_ons else sorted(all_modified_ons)[-1]


def get_created_by(chebi_id):
    '''Returns created by'''
    if not __CREATED_BYS:
        __parse_compounds()

    return __CREATED_BYS[chebi_id] if chebi_id in __MODIFIED_ONS else None


def get_star(chebi_id):
    '''Returns star'''
    if not __STARS:
        __parse_compounds()

    return __STARS[chebi_id] if chebi_id in __STARS else float('NaN')


def __parse_compounds():
    '''Gets and parses file'''
    filename = get_file('compounds.tsv.gz')

    with io.open(filename, 'r', encoding='cp1252') as textfile:
        next(textfile)

        for line in textfile:
            tokens = line.strip().split('\t')
            chebi_id = int(tokens[0])

            __STATUSES[chebi_id] = tokens[1]
            __SOURCES[chebi_id] = tokens[3]

            parent_id_token = tokens[4]
            __PARENT_IDS[chebi_id] = float('NaN') \
                if parent_id_token == 'null' \
                else int(parent_id_token)
            __put_all_ids(chebi_id, chebi_id)

            if parent_id_token != 'null':
                parent_id = int(parent_id_token)
                __put_all_ids(parent_id, chebi_id)

            __NAMES[chebi_id] = None if tokens[5] == 'null' else tokens[5]
            __DEFINITIONS[chebi_id] = None if tokens[6] == 'null' \
                else tokens[6]
            __MODIFIED_ONS[chebi_id] = None if tokens[7] == 'null' \
                else datetime.datetime.strptime(tokens[7], '%Y-%m-%d')
            __CREATED_BYS[chebi_id] = None if tokens[8] == 'null' \
                or len(tokens) == 9 else tokens[8]
            __STARS[chebi_id] = float('NaN') \
                if tokens[9 if len(tokens) > 9 else 8] == 'null' \
                else int(tokens[9 if len(tokens) > 9 else 8])


def __put_all_ids(parent_id, child_id):
    '''COMMENT'''
    if parent_id in __ALL_IDS:
        __ALL_IDS[parent_id].append(child_id)
    else:
        __ALL_IDS[parent_id] = [child_id]


def get_database_accessions(chebi_id):
    '''Returns database accession'''
    if not __DATABASE_ACCESSIONS:
        __parse_database_accessions()

    return __DATABASE_ACCESSIONS[chebi_id] if chebi_id in \
        __DATABASE_ACCESSIONS else []


def get_all_database_accessions(chebi_ids):
    '''Returns all database accessions'''
    all_database_accessions = [get_database_accessions(chebi_id)
                               for chebi_id in chebi_ids]
    return [x for sublist in all_database_accessions for x in sublist]


def __parse_database_accessions():
    '''Gets and parses file'''
    filename = get_file('database_accession.tsv')

    with io.open(filename, 'r', encoding='cp1252') as textfile:
        next(textfile)

        for line in textfile:
            tokens = line.strip().split('\t')
            chebi_id = int(tokens[1])

            if chebi_id not in __DATABASE_ACCESSIONS:
                __DATABASE_ACCESSIONS[chebi_id] = []

            # Append DatabaseAccession:
            dat_acc = DatabaseAccession(tokens[3], tokens[4], tokens[2])

            __DATABASE_ACCESSIONS[chebi_id].append(dat_acc)


def get_inchi(chebi_id):
    '''Returns InChI string'''
    if not __INCHIS:
        __parse_inchi()

    return __INCHIS[chebi_id] if chebi_id in __INCHIS else None


def __parse_inchi():
    '''Gets and parses file'''
    filename = get_file('chebiId_inchi.tsv')

    with io.open(filename, 'r', encoding='cp1252') as textfile:
        next(textfile)

        for line in textfile:
            tokens = line.strip().split('\t')
            __INCHIS[int(tokens[0])] = tokens[1]


def get_names(chebi_id):
    '''Returns names'''
    if not __ALL_NAMES:
        __parse_names()

    return __ALL_NAMES[chebi_id] if chebi_id in __ALL_NAMES else []


def get_all_names(chebi_ids):
    '''Returns all names'''
    all_names = [get_names(chebi_id) for chebi_id in chebi_ids]
    return [x for sublist in all_names for x in sublist]


def __parse_names():
    '''Gets and parses file'''
    filename = get_file('names.tsv.gz')

    with io.open(filename, 'r', encoding='cp1252') as textfile:
        next(textfile)

        for line in textfile:
            tokens = line.strip().split('\t')
            chebi_id = int(tokens[1])

            if chebi_id not in __ALL_NAMES:
                __ALL_NAMES[chebi_id] = []

            # Append Name:
            nme = Name(tokens[4],
                       tokens[2],
                       tokens[3],
                       tokens[5] == 'T',
                       tokens[6])

            __ALL_NAMES[chebi_id].append(nme)


def get_references(chebi_ids):
    '''Returns references'''
    references = []
    chebi_ids = [str(chebi_id) for chebi_id in chebi_ids]

    filename = get_file('reference.tsv.gz')

    with io.open(filename, 'r', encoding='cp1252') as textfile:
        next(textfile)

        for line in textfile:
            tokens = line.strip().split('\t')

            if tokens[0] in chebi_ids:
                # Append Reference:
                if len(tokens) > 3:
                    ref = Reference(tokens[1], tokens[2], tokens[3],
                                    tokens[4])
                else:
                    ref = Reference(tokens[1], tokens[2])

                references.append(ref)
    return references


def get_outgoings(chebi_id):
    '''Returns outgoings'''
    if not __OUTGOINGS:
        __parse_relation()

    return __OUTGOINGS[chebi_id] if chebi_id in __OUTGOINGS else []


def get_all_outgoings(chebi_ids):
    '''Returns all outgoings'''
    all_outgoings = [get_outgoings(chebi_id) for chebi_id in chebi_ids]
    return [x for sublist in all_outgoings for x in sublist]


def get_incomings(chebi_id):
    '''Returns incomings'''
    if not __INCOMINGS:
        __parse_relation()

    return __INCOMINGS[chebi_id] if chebi_id in __INCOMINGS else []


def get_all_incomings(chebi_ids):
    '''Returns all incomings'''
    all_incomings = [get_incomings(chebi_id) for chebi_id in chebi_ids]
    return [x for sublist in all_incomings for x in sublist]


def __parse_relation():
    '''Gets and parses file'''
    relation_filename = get_file('relation.tsv')
    relation_textfile = open(relation_filename, 'r')

    next(relation_textfile)

    for line in relation_textfile:
        tokens = line.strip().split('\t')

        source_chebi_id = int(tokens[3])
        target_chebi_id = int(tokens[2])
        typ = tokens[1]

        if source_chebi_id not in __OUTGOINGS:
            __OUTGOINGS[source_chebi_id] = []

        if target_chebi_id not in __INCOMINGS:
            __INCOMINGS[target_chebi_id] = []

        target_relation = Relation(typ, str(target_chebi_id), tokens[4])
        source_relation = Relation(typ, str(source_chebi_id), tokens[4])

        __OUTGOINGS[source_chebi_id].append(target_relation)
        __INCOMINGS[target_chebi_id].append(source_relation)


def get_inchi_key(chebi_id):
    '''Returns InChI key'''
    if not __INCHI_KEYS:
        __parse_structures()

    return __INCHI_KEYS[chebi_id] if chebi_id in __INCHI_KEYS else None


def get_smiles(chebi_id):
    '''Returns InChI key'''
    if not __SMILES:
        __parse_structures()

    return __SMILES[chebi_id] if chebi_id in __SMILES else None


def get_mol(chebi_id):
    '''Returns mol'''
    chebi_id_regexp = '^\\d+\\,' + str(chebi_id) + '\\,.*'
    mol_file_end_regexp = '\",mol,\\dD,[Y\\|N],[Y\\|N]$'
    this_structure = []

    filename = get_file('structures.csv.gz')

    with io.open(filename, 'r', encoding='cp1252') as textfile:
        in_chebi_id = False

        next(textfile)

        for line in textfile:
            if in_chebi_id or line[0].isdigit():
                if re.match(chebi_id_regexp, line):
                    tokens = line.strip().split(',')
                    in_chebi_id = True
                    this_structure = []
                    this_structure.append(','.join(tokens[2:])
                                          .replace('\"', ''))
                    this_structure.append('\n')
                elif in_chebi_id:

                    if re.match(mol_file_end_regexp, line):
                        tokens = line.strip().split(',')

                        if _is_default_structure(tokens[3]):
                            tokens = line.strip().split(',')
                            this_structure.append(tokens[0].replace('\"', ''))
                            return Structure(''.join(this_structure),
                                             Structure.mol,
                                             int(tokens[2][0]))

                        # else:
                        this_structure = []
                        in_chebi_id = False
                        continue

                    this_structure.append(line)

    return None


def get_mol_filename(chebi_id):
    '''Returns mol file'''
    mol = get_mol(chebi_id)

    if mol is None:
        return None

    file_descriptor, mol_filename = tempfile.mkstemp(str(chebi_id) +
                                                     '_', '.mol')
    mol_file = open(mol_filename, 'w')
    mol_file.write(mol.get_structure())
    mol_file.close()
    os.close(file_descriptor)

    return mol_filename


def __parse_structures():
    '''COMMENT'''
    filename = get_file('structures.csv.gz')

    with io.open(filename, 'r', encoding='cp1252') as textfile:
        next(textfile)

        for line in textfile:
            tokens = line.strip().split(',')

            if len(tokens) == 7:
                if tokens[3] == 'InChIKey':
                    __INCHI_KEYS[int(tokens[1])] = \
                        Structure(tokens[2],
                                  Structure.InChIKey,
                                  int(tokens[4][0]))
                elif tokens[3] == 'SMILES':
                    __SMILES[int(tokens[1])] = \
                        Structure(tokens[2],
                                  Structure.SMILES,
                                  int(tokens[4][0]))


def get_file(filename):
    '''Downloads filename from ChEBI FTP site'''
    destination = __DOWNLOAD_PARAMS['path']
    filepath = os.path.join(destination, filename)

    if not __is_current(filepath):

        if not os.path.exists(destination):
            os.makedirs(destination)

        url = 'ftp://ftp.ebi.ac.uk/pub/databases/chebi/' + \
            'Flat_file_tab_delimited/'
        
        wget.download(url+filename, out=filepath)
        
        #urlretrieve(urlparse.urljoin(url, filename), filepath)
        #urlcleanup()

    if filepath.endswith('.zip'):
        zfile = zipfile.ZipFile(filepath, 'r')
        filepath = os.path.join(destination, zfile.namelist()[0])
        zfile.extractall(destination)
    elif filepath.endswith('.gz'):
        unzipped_filepath = filepath[:-len('.gz')]

        if os.path.exists(unzipped_filepath) \
                and __is_current(unzipped_filepath):
            filepath = unzipped_filepath
        else:
            input_file = gzip.open(filepath, 'rb')
            filepath = os.path.join(destination, input_file.name[:-len('.gz')])
            output_file = open(filepath, 'wb')

            for line in input_file:
                output_file.write(line)

            input_file.close()
            output_file.close()

    return filepath


def __is_current(filepath):
    '''Checks whether file is current'''
    if not __DOWNLOAD_PARAMS['auto_update']:
        return True

    if not os.path.isfile(filepath):
        return False

    return datetime.datetime.utcfromtimestamp(os.path.getmtime(filepath)) \
        > __get_last_update_time()


def __get_last_update_time():
    '''Returns last FTP site update time'''
    now = datetime.datetime.utcnow()

    # Get the first Tuesday of the month
    first_tuesday = __get_first_tuesday(now)

    if first_tuesday < now:
        return first_tuesday
    # else:
    first_of_month = datetime.datetime(now.year, now.month, 1)
    last_month = first_of_month + datetime.timedelta(days=-1)
    return __get_first_tuesday(last_month)


def __get_first_tuesday(this_date):
    '''Get the first Tuesday of the month'''
    month_range = calendar.monthrange(this_date.year, this_date.month)
    first_of_month = datetime.datetime(this_date.year, this_date.month, 1)
    first_tuesday_day = (calendar.TUESDAY - month_range[0]) % 7
    first_tuesday = first_of_month + datetime.timedelta(days=first_tuesday_day)
    return first_tuesday


def _is_default_structure(def_struct):
    '''Is default structure?'''
    return def_struct.upper() == 'Y'
