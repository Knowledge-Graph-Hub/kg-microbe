"""S3 Utilities, including uploading and downloading data from S3."""

import csv
import json
from pathlib import Path
from urllib import parse

import requests
import requests_cache
from tqdm import tqdm

from kg_microbe.transform_utils.constants import (
    NCBITAXON_PREFIX,
    ORGANISM_ID,
    RAW_DATA_DIR,
    UNIPROT_BASE_URL,
    UNIPROT_BATCH_SIZE,
    UNIPROT_DESIRED_FORMAT,
    UNIPROT_FIELDS,
    UNIPROT_KEYWORDS,
    UNIPROT_SIZE,
)

ORGANISM_RESOURCE = RAW_DATA_DIR / "ncbitaxon_removed_subset.json"
UNIPROT_RAW_DIR = RAW_DATA_DIR / "uniprot"
EMPTY_ORGANISM_OUTFILE = UNIPROT_RAW_DIR / "uniprot_empty_organism.tsv"
UNIPROT_S3_DIR = UNIPROT_RAW_DIR / "s3"


def run_api(api: str) -> None:
    """
    Upload data to S3.

    :param api: A string pointing to the API to upload data to.
    :return: None
    """
    if api == "uniprot":
        run_uniprot_api()
    else:
        raise ValueError(f"API {api} not supported")


def run_uniprot_api() -> None:
    """
    Upload data to S3 from Uniprot.

    :return: None
    """
    # Create the directory if it doesn't exist
    Path(UNIPROT_S3_DIR).mkdir(parents=True, exist_ok=True)

    # Read organism resource and extract organism IDs
    with open(ORGANISM_RESOURCE, "r") as f:
        contents = json.load(f)  # Using json.load instead of json.loads(f.read())
        ncbi_prefix = NCBITAXON_PREFIX.replace(":", "_")

    organism_ids = [
        i["id"].split(ncbi_prefix)[1]
        for i in contents["graphs"][0]["nodes"]
        if ncbi_prefix in i["id"] and i["id"].split(ncbi_prefix)[1].isdigit()
    ]

    # Check for empty organism list and read or initialize the file accordingly
    empty_organism_list = []
    empty_organism_file_path = Path(EMPTY_ORGANISM_OUTFILE)
    if empty_organism_file_path.is_file():
        with open(empty_organism_file_path, newline="") as csvfile:
            reader = csv.DictReader(csvfile)
            empty_organism_list = [str(row[ORGANISM_ID]) for row in reader]
    else:
        empty_organism_file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(empty_organism_file_path, "w") as tsv_file:
            tsv_file.write(f"{ORGANISM_ID}\n")

    # Process uniprot files
    total_organisms = len(organism_ids)
    with tqdm(total=total_organisms, desc="Processing uniprot files") as progress:
        for i in range(0, total_organisms, UNIPROT_BATCH_SIZE):
            _get_uniprot_batch_organism(organism_ids, i, empty_organism_list)
            progress.update(UNIPROT_BATCH_SIZE)

    # Set final description after processing
    last_file = f"{organism_ids[-1]}.{UNIPROT_DESIRED_FORMAT}"
    progress.set_description(
        f"Downloading organism data from Uniprot, final file of batch: {last_file}"
    )


def _get_uniprot_batch_organism(organism_ids, start_index, empty_organism_list):
    """Get batch of Uniprot data."""
    # Set up caching for requests
    requests_cache.install_cache("uniprot_cache")

    confirmed_empty_orgs = []
    end_index = min(start_index + UNIPROT_BATCH_SIZE, len(organism_ids))
    batch = organism_ids[start_index:end_index]
    nonexistent_batch = [
        organism
        for organism in batch
        if not (Path(UNIPROT_S3_DIR) / f"{organism}.{UNIPROT_DESIRED_FORMAT}").exists()
        and organism not in empty_organism_list
    ]

    if nonexistent_batch:
        query = "%20OR%20".join(["organism:" + organism_id for organism_id in nonexistent_batch])
        keywords_param = "&keywords=" + "+".join(UNIPROT_KEYWORDS) if UNIPROT_KEYWORDS else ""
        fields_param = "&fields=" + "%2C".join([parse.quote(field) for field in UNIPROT_FIELDS])

        url = (
            f"{UNIPROT_BASE_URL}/search?query={query}"
            f"&format={UNIPROT_DESIRED_FORMAT}&size={UNIPROT_SIZE}"
            f"{keywords_param}{fields_param}"
        )

        try:
            response = requests.get(url, timeout=30)
            response.raise_for_status()

            if len(response.text.strip().split("\n")) <= 1:
                confirmed_empty_orgs.extend(nonexistent_batch)
            else:
                for organism_id in nonexistent_batch:
                    with open(
                        Path(UNIPROT_S3_DIR) / f"{organism_id}.{UNIPROT_DESIRED_FORMAT}", "w"
                    ) as file:
                        file.write(response.text)

        except requests.exceptions.HTTPError as e:
            print(f"Failed to retrieve data: {e}")
        except requests.exceptions.Timeout:
            print("The request timed out")
        except requests.exceptions.RequestException as e:
            print(f"An error occurred: {e}")

    # Stream the confirmed empty organism IDs to a TSV file
    if confirmed_empty_orgs:
        with open(EMPTY_ORGANISM_OUTFILE, "a") as tsv_file:
            tsv_file.writelines(f"{org_id}\n" for org_id in confirmed_empty_orgs)
