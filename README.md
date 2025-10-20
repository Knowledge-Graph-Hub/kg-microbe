

![alt text](https://github.com/Knowledge-Graph-Hub/kg-microbe/blob/master/kg-microbe.png?raw=true)

# KG-Microbe -- Knowledge graph construction for microbial traits and beyond

[KG-Microbe preprint](https://www.biorxiv.org/content/10.1101/2025.02.24.639989v1)

[Semantic Scholar](https://www.semanticscholar.org/paper/KG-Microbe%3A-A-Reference-Knowledge-Graph-and-for-joachimiak-Hegde/c49a7ed4e5e1c0db815a3b185148877d914473f2)

[Documentation](http://kghub.org/kg-microbe/index.html)

[latest KG-Microbe release](https://github.com/Knowledge-Graph-Hub/kg-microbe/releases/tag/2025-03-07)

[KG-Microbe @KG-Hub](https://kghub.org)


# Setup
 - Create a vrtual environment of your choice.
 - Install poetry using `pipx install poetry`
 - `git clone https://github.com/Knowledge-Graph-Hub/kg-microbe.git`
 - `cd kg-microbe`
 - `poetry install`

## Download resources needed
 - `poetry run kg download` : This will download the resources needed for this project.

## Transform
 - `poetry run kg transform`: This transforms the resources into knowledge graphs (KGs).

##  Merge
 - `poetry run kg merge`: This merges all transformed graphs above.

## Release
 ### Requirements
 In order to be able to make KG releases on this repository, you'll need:
 - Appropriate permissions to this repository.
 - A Github token that has permissions on this repository. [This is how you set it in GitHub](https://docs.github.com/en/organizations/managing-programmatic-access-to-your-organization/setting-a-personal-access-token-policy-for-your-organization#restricting-access-by-personal-access-tokens-classic). Make sure your token has access to this project.
 - Save this token locally assigned to the environemnt variable `GH_TOKEN`
    ```shell
    export GH_TOKEN = XXXX
    ```
    or add it to your `~/.bash_profile` or `~/.bashrc` file.

It should be noted that the KG construction process, particularly the transform step  involving trimming of NCBI Taxonomy for any KG and the steps involving the microbial UniProt dataset for KG-Microbe-Function and KG-Microbe-Biomedical-Function, is computationally intensive. Successful execution on a local machine may require significant memory resources (e.g., >500 GB of RAM), further details can be found in the project's code repository.

# Contributors
Please remember to run `poetry run tox` before every commit to make sure the code you commit is error-free.

## Environment Variables
If you need to use environment variables for this project, copy `.env.example` to `.env` and set the environment variables accordingly:
```shell
cp .env.example .env
```
Then edit the `.env` file to configure the required environment variables for your setup.

# Acknowledgements

This [cookiecutter](https://cookiecutter.readthedocs.io/en/stable/README.html) project was developed from the [kg-cookiecutter](https://github.com/Knowledge-Graph-Hub/kg-cookiecutter) template and will be kept up-to-date using [cruft](https://cruft.github.io/cruft/).
 
