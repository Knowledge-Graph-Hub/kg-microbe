

![alt text](https://github.com/Knowledge-Graph-Hub/kg-microbe/blob/master/kg-microbe.png?raw=true)

# KG-Microbe -- Knowledge graph construction for microbial traits and beyond

[Conference paper](https://ceur-ws.org/Vol-3073/paper19.pdf)

[Semantic Scholar](https://www.semanticscholar.org/paper/KG-Microbe%3A-A-Reference-Knowledge-Graph-and-for-joachimiak-Hegde/c49a7ed4e5e1c0db815a3b185148877d914473f2)

[Documentation](http://kghub.org/kg-microbe/index.html)

[KG-Microbe @KG-Hub](https://kghub.io/kg-microbe/](https://kghub.org)

[Monthly builds](https://kg-hub.berkeleybop.io/kg-microbe/)


# Setup
 - Create a vrtual environment of your choice.
 - Install poetry using `pip install poetry`
 - `poetry install`
 - `git clone https://github.com/Knowledge-Graph-Hub/kg-microbe.git`
 - `cd kg-microbe`

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



# Contributors
Please remember to run `poetry run tox` before every commit to make sure the code you commit is error-free.

# Acknowledgements

This [cookiecutter](https://cookiecutter.readthedocs.io/en/stable/README.html) project was developed from the [kg-cookiecutter](https://github.com/Knowledge-Graph-Hub/kg-cookiecutter) template and will be kept up-to-date using [cruft](https://cruft.github.io/cruft/).
 
