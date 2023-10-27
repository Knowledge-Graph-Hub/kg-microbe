# Knowledge Graphs for Microbial data

The source for the framework of this repository is from [kg-cookiecutter](https://github.com/Knowledge-Graph-Hub/kg-cookiecutter).

## Knowledge Graph Hub concept
Please see [here](https://github.com/Knowledge-Graph-Hub/kg-covid-19/wiki#knowledge-graph-hub-concept)

## Prerequisites

* Java/JDK is required in order for the transform step to work properly. Installation instructions can be found [here](https://docs.oracle.com/en/java/javase/15/install/overview-jdk-installation.html#GUID-8677A77F-231A-40F7-98B9-1FD0B48C346A).

## Setup

* Create a python virtual environment (venv, anaconda etc.)
* `pip install poetry`
* `git clone https://github.com/Knowledge-Graph-Hub/kg-microbe`
* `cd kg-microbe`
* `poetry install`

## Pipeline Stages:
1. Download
2. Transform
3. Merge

### Download
This step download all files from the urls declared in the [download.yaml](https://github.com/Knowledge-Graph-Hub/kg-microbe/blob/master/download.yaml) file. 

script - `poetry run kg download`

File currently downloaded:
1. Traits data from [bacteria-arachaea-traits](https://github.com/bacteria-archaea-traits/bacteria-archaea-traits/blob/master/output) repository. Considering only 'condensed_traits_NCBI.csv' for now.
2. Environments data from the same repository found as a conversion table titled ['environments.csv'](https://github.com/bacteria-archaea-traits/bacteria-archaea-traits/tree/master/data/conversion_tables).
3. ROBOT [jar](https://github.com/ontodev/robot/releases/download/v1.7.2/robot.jar) and [shell script](https://raw.githubusercontent.com/ontodev/robot/master/bin/robot) files. ROBOT is used to convert the OWL format files of ontologies into OBOJSON format to extract nodes and edges from the ontologies. In this case, we also leverage the 'extract' feature of ROBOT to get subsets of ontologies. Documentation on ROBOT could be found [here](http://robot.obolibrary.org).
4. [CHEBI.owl](http://www.obofoundry.org/ontology/chebi.html) is used as dictionary while running [OGER](https://github.com/OntoGene/OGER) to annotate 'carbon substrate' information from the traits data.
5. [NCBITaxon.owl](http://www.obofoundry.org/ontology/ncbitaxon.html) is used as the ontology source to capture organismal classification information.
6. [bacdive_strains.json](https://drive.google.com/file/d/1dOquB0M6H5Vxu6cBPa4kJ7F9v44medoV/view?usp=share_link)
7. [mediadive.json](https://mediadive.dsmz.de/rest/media)

### Transform
In this step, we create nodes and edges corresponding to the four downloaded files mentioned above (#1, #4 and #5).

scripts
1. All together - `poetry run kg transform`

OR

Running transforms individually:
1. For traits data => `poetry run kg transform -s TraitsTransform`
2. For CHEBI.owl => `poetry run kg transform -s ChebiTransform`
3. For NCBITaxon.owl => `poetry run kg transform -s NCBITransform`
3. For BacDive data => `poetry run kg transform -s BacDiveTransform`
4. For MediaDive data => `poetry run kg transform -s MediaDiveTransform`

### Merge
In this step, all the above transforms are merged and a cumulative nodes and edges files are generated.

script - `poetry run kg merge`


## Data
The final merged data is available [here](https://drive.google.com/drive/folders/1W2iGourDmo1gB8ip6GfCEax9El_OMR9h)
