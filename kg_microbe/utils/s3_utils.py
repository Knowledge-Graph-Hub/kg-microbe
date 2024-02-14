"""S3 Utilities, including uploading and downloading data from S3."""

import csv
import json
import multiprocessing
from functools import partial
from pathlib import Path
from typing import List
from urllib import parse

import requests
import requests_cache
from tqdm import tqdm
from tqdm.contrib.concurrent import process_map

from kg_microbe.transform_utils.constants import (
    NCBITAXON_PREFIX,
    ORGANISM_ID_MIXED_CASE,
    RAW_DATA_DIR,
    TAXONOMY_ID_UNIPROT_PREFIX,
    UNIPROT_BASE_URL,
    UNIPROT_DESIRED_FORMAT,
    UNIPROT_FIELDS,
    UNIPROT_KEYWORDS,
    UNIPROT_SIZE,
)
from kg_microbe.utils.dummy_tqdm import DummyTqdm

ORGANISM_RESOURCE = RAW_DATA_DIR / "ncbitaxon_removed_subset.json"
UNIPROT_RAW_DIR = RAW_DATA_DIR / "uniprot"
EMPTY_ORGANISM_OUTFILE = UNIPROT_RAW_DIR / "uniprot_empty_organism.tsv"
UNIPROT_S3_DIR = UNIPROT_RAW_DIR / "s3"


# Function to read organisms from a CSV file and return a set
def _read_organisms_from_csv(file_path):
    with open(file_path, newline="") as csvfile:
        reader = csv.DictReader(csvfile)
        return {str(row[ORGANISM_ID_MIXED_CASE]) for row in reader}


def _write_file(file_path, response, organism_id):
    # Write response to file if it contains data
    if len(response.text.strip().split("\n")) > 1:
        with open(file_path, "w") as file:
            file.write(response.text)
    else:
        # Append organism ID to the empty organisms file
        with open(EMPTY_ORGANISM_OUTFILE, "a") as tsv_file:
            tsv_file.write(f"{organism_id}\n")


def get_organism_list() -> List[str]:
    """
    Update organism list based on existing empty request files.

    :param organism_list: List of organism IDs.
    """
    # Read organism resource file and extract organism IDs
    with open(ORGANISM_RESOURCE, "r") as f:
        contents = json.load(f)
        ncbi_prefix = NCBITAXON_PREFIX.replace(":", "_")

    # Create a list of organism IDs after filtering and cleaning
    organism_list = [
        i["id"].split(ncbi_prefix)[1]
        for i in contents["graphs"][0]["nodes"]
        if ncbi_prefix in i["id"] and i["id"].split(ncbi_prefix)[1].isdigit()
    ]
    # Update organism list based on existing empty request files
    for file_path in [EMPTY_ORGANISM_OUTFILE]:
        if file_path.is_file():
            no_info_organism_set = _read_organisms_from_csv(file_path)
            organism_list = list(set(organism_list) - no_info_organism_set)
        else:
            # Create file and write header if it doesn't exist
            file_path.parent.mkdir(parents=True, exist_ok=True)
            with open(file_path, "w") as tsv_file:
                tsv_file.write(f"{ORGANISM_ID_MIXED_CASE}\n")
    return organism_list


def run_api(api: str, show_status: bool) -> None:
    """
    Upload data to S3.

    :param api: A string pointing to the API to upload data to.
    :return: None
    """
    if api == "uniprot":
        # run_uniprot_api(show_status) # ! Single worker.
        run_uniprot_api_parallel(show_status)  # ! Multiple workers.
    else:
        raise ValueError(f"API {api} not supported")


def run_uniprot_api(show_status: bool) -> None:
    """
    Download data from Uniprot in series.

    :param show_status: Boolean flag to show progress status.
    :return: None
    """
    # Cache HTTP requests to avoid repeated calls
    requests_cache.install_cache("uniprot_cache")

    # Ensure the directory for storing Uniprot files exists
    Path(UNIPROT_S3_DIR).mkdir(parents=True, exist_ok=True)

    organism_list = get_organism_list()

    # Process uniprot files
    total_organisms = len(organism_list)
    progress_class = tqdm if show_status else DummyTqdm

    # Iterate over organism IDs and fetch data from Uniprot
    with progress_class(total=total_organisms, desc="Processing uniprot files") as progress:
        for organism_id in organism_list:
            file_path = Path(UNIPROT_S3_DIR) / f"{organism_id}.{UNIPROT_DESIRED_FORMAT}"
            if not file_path.exists():
                # Construct the query URL
                query = TAXONOMY_ID_UNIPROT_PREFIX + organism_id
                keywords_param = (
                    "&keywords=" + "+".join(UNIPROT_KEYWORDS) if UNIPROT_KEYWORDS else ""
                )
                fields_param = "&fields=" + ",".join(map(parse.quote, UNIPROT_FIELDS))

                url = (
                    f"{UNIPROT_BASE_URL}/search?query={query}"
                    f"&format={UNIPROT_DESIRED_FORMAT}&size={UNIPROT_SIZE}{keywords_param}{fields_param}"
                )

                try:
                    # Make the HTTP request to Uniprot
                    response = requests.get(url, timeout=30)
                    response.raise_for_status()
                    _write_file(file_path, response, organism_id)

                    while "next" in response.links:
                        next_url = response.links["next"]["url"]
                        response = requests.get(next_url, timeout=30)
                        response.raise_for_status()
                        _write_file(file_path, response, organism_id)

                    # # Write response to file if it contains data
                    # if len(response.text.strip().split("\n")) > 1:
                    #     with open(file_path, "w") as file:
                    #         file.write(response.text)
                    # else:
                    #     # Append organism ID to the empty organisms file
                    #     with open(EMPTY_ORGANISM_OUTFILE, "a") as tsv_file:
                    #         tsv_file.write(f"{organism_id}\n")

                except requests.exceptions.HTTPError:
                    print(f"Bad request for organism {organism_id} - {response.status_code}")
                except requests.exceptions.Timeout:
                    print("The request timed out")
                except requests.exceptions.RequestException as e:
                    print(f"An error occurred: {e}")

            # Update progress bar
            progress.update(1)
        # Set final description for the progress bar
        progress.set_description(
            f"Downloading organism data from Uniprot, final file of batch: {organism_id}"
        )


def fetch_uniprot_data(organism_id):
    """
    Single URL construction and request for Uniprot data.

    :param organism_id: Just if the ID of the NCBITaxon entity.
    """
    # Construct the query URL
    file_path = Path(UNIPROT_S3_DIR) / f"{organism_id}.{UNIPROT_DESIRED_FORMAT}"
    query = TAXONOMY_ID_UNIPROT_PREFIX + organism_id
    keywords_param = "&keywords=" + "+".join(UNIPROT_KEYWORDS) if UNIPROT_KEYWORDS else ""
    fields_param = "&fields=" + ",".join(map(parse.quote, UNIPROT_FIELDS))

    url = (
        f"{UNIPROT_BASE_URL}/search?query={query}&format={UNIPROT_DESIRED_FORMAT}"
        f"&size={UNIPROT_SIZE}{keywords_param}{fields_param}"
    )

    try:
        # Make the HTTP request to Uniprot
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        _write_file(file_path, response, organism_id)

        while "next" in response.links:
            next_url = response.links["next"]["url"]
            response = requests.get(next_url, timeout=30)
            response.raise_for_status()
            _write_file(file_path, response, organism_id)

    except requests.exceptions.HTTPError:
        print(f"Bad request for organism {organism_id} - {response.status_code}")
    except requests.exceptions.Timeout:
        print("The request timed out")
    except requests.exceptions.RequestException as e:
        print(f"An error occurred: {e}")


def run_uniprot_api_parallel(show_status: bool, workers: int = None) -> None:
    """
    Download data from Uniprot in parallel.

    :param show_status: Boolean flag to show progress status.
    :return: None
    """
    # Cache HTTP requests to avoid repeated calls
    requests_cache.install_cache("uniprot_cache")

    # Ensure the directory for storing Uniprot files exists
    Path(UNIPROT_S3_DIR).mkdir(parents=True, exist_ok=True)

    organism_list = get_organism_list()

    # Set up a pool of worker processes
    with multiprocessing.Pool(processes=workers) as pool:
        # Use partial to create a new function that has some parameters pre-filled
        fetch_func = partial(fetch_uniprot_data)
        # If show_status is True, use process_map to display a progress bar
        if show_status:
            process_map(fetch_func, organism_list, max_workers=workers)
        else:
            # Set up a pool of worker processes without a progress bar
            with multiprocessing.Pool(processes=workers) as pool:
                pool.map(fetch_func, organism_list)
