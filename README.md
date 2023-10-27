# kg-microbe

Knowledge graph construction for BacDive data

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

# Contributors
Please remember to run `poetry run tox` before every commit to make sure the code you commit is error-free.

# Acknowledgements

This [cookiecutter](https://cookiecutter.readthedocs.io/en/stable/README.html) project was developed from the [kg-cookiecutter](https://github.com/Knowledge-Graph-Hub/kg-cookiecutter) template and will be kept up-to-date using [cruft](https://cruft.github.io/cruft/).