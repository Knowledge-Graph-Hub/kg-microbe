

![alt text](https://github.com/Knowledge-Graph-Hub/kg-microbe/blob/master/kg-microbe.png?raw=true)

# KG-Microbe -- Knowledge graph construction for microbial traits and beyond

[KG-Microbe preprint](https://www.biorxiv.org/content/10.1101/2025.02.24.639989v1)

[Semantic Scholar](https://www.semanticscholar.org/paper/KG-Microbe%3A-A-Reference-Knowledge-Graph-and-for-joachimiak-Hegde/c49a7ed4e5e1c0db815a3b185148877d914473f2)

[Documentation](http://kghub.org/kg-microbe/index.html)

[Latest KG-Microbe release](https://github.com/Knowledge-Graph-Hub/kg-microbe/releases/latest)

[KG-Microbe @KG-Registry](https://kghub.org/kg-registry/resource/kg-microbe/kg-microbe.html)


# Setup
 - Install [pipx](https://pipx.pypa.io/stable/installation/)
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

The standard merge writes `data/merged/merged-kg.tar.gz`, containing
`merged-kg_nodes.tsv` and `merged-kg_edges.tsv`, and writes statistics to
`merged_graph_stats.yaml`. To work with the TSV files directly:

```shell
tar -xzf data/merged/merged-kg.tar.gz -C data/merged
make run-summary
```

`make run-summary` also reads the archive directly, so extraction is optional.

## Build and release artifacts

The canonical `merge.yaml` build is the release graph. Other merge configs use
distinct names such as `merged-kg-minimal.tar.gz`,
`merged-kg-no-metatraits.tar.gz`, and `merged-kg-prego-full.tar.gz`, so running a
variant cannot masquerade as the canonical graph. The source differences are
defined in `config/merge_variants.yaml`.

The release workflow publishes the checksum-verified Jenkins artifact as
`kg-microbe-YYYYMMDD.tar.gz`. It contains the canonical
`merged-kg_nodes.tsv`, `merged-kg_edges.tsv`, and dated graph statistics. The
release also includes `artifact-provenance.txt` with the build URL, checksum,
and workflow revision.

Download builds from GitHub releases:

- All releases: [releases](https://github.com/Knowledge-Graph-Hub/kg-microbe/releases)
- Latest curated release: [releases/latest](https://github.com/Knowledge-Graph-Hub/kg-microbe/releases/latest)
- Merged graph matching the 2024-08-26 taxa-to-media predictions:
  [2024-08-26/20240826.tar.gz](https://github.com/Knowledge-Graph-Hub/kg-microbe/releases/download/2024-08-26/20240826.tar.gz)
  (SHA-256 `5eae75b3d189dc61cb53a3b2348435c6fcf6941d98538af3e789f7059d0a67fa`)

Pin a specific release tag and verify the checksum for reproducible downstream
work. The former `https://kg-hub.berkeleybop.io/kg-microbe/...` dated and
`current` URLs are no longer served (they return 404); GitHub releases are the
supported distribution channel.

## Release
 ### Requirements
 In order to be able to make KG releases on this repository, you'll need:
 - Appropriate permissions to this repository.
 - A GitHub token that has permissions on this repository. [This is how you set it in GitHub](https://docs.github.com/en/organizations/managing-programmatic-access-to-your-organization/setting-a-personal-access-token-policy-for-your-organization#restricting-access-by-personal-access-tokens-classic). Make sure your token has access to this project.
 - Save this token locally in the environment variable `GH_TOKEN`:
    ```shell
    export GH_TOKEN=XXXX
    ```
   GitHub CLI reads the variable directly. Do not place the token in a Git URL,
   repository file, or shell history.

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
 
