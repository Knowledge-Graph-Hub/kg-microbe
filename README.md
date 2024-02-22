

![alt text](https://github.com/Knowledge-Graph-Hub/kg-microbe/blob/master/kg-microbe.png?raw=true)

# KG-Microbe -- Knowledge graph construction for microbial traits

[Conference paper](https://ceur-ws.org/Vol-3073/paper19.pdf)

[Semantic Scholar](https://www.semanticscholar.org/paper/KG-Hub%E2%80%94building-and-exchanging-biological-knowledge-Caufield-Putman/4c456614394d274fea181ec858429339f61c1c2c)

[Documentation]([docs/CONTRIBUTING.md](http://kghub.org/kg-microbe/index.html))

[KG-Microbe @KG-Hub](https://kghub.io/kg-microbe/)

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

# Contributors
Please remember to run `poetry run tox` before every commit to make sure the code you commit is error-free.

# Acknowledgements

This [cookiecutter](https://cookiecutter.readthedocs.io/en/stable/README.html) project was developed from the [kg-cookiecutter](https://github.com/Knowledge-Graph-Hub/kg-cookiecutter) template and will be kept up-to-date using [cruft](https://cruft.github.io/cruft/).
