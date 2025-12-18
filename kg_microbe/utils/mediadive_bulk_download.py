"""
MediaDive bulk download utility.

This module provides functionality to download all MediaDive data in bulk
to avoid repeated API calls during transforms.
"""

import json
import logging
import time
from pathlib import Path
from typing import Dict, List

import requests
import requests_cache
from tqdm import tqdm

# Set up logging for API warnings (written to file, not stdout)
logger = logging.getLogger(__name__)

# MediaDive REST API base URL
MEDIADIVE_REST_API_BASE_URL = "https://mediadive.dsmz.de/rest/"

# API endpoints
MEDIA_ENDPOINT = "media"
MEDIUM_ENDPOINT = "medium/"
MEDIUM_STRAINS_ENDPOINT = "medium-strains/"  # Note: hyphen, not underscore

# Keys in JSON responses
DATA_KEY = "data"
ID_KEY = "id"
SOLUTIONS_KEY = "solutions"
RECIPE_KEY = "recipe"
COMPOUND_KEY = "compound"
COMPOUND_ID_KEY = "compound_id"
SOLUTION_ID_KEY = "solution_id"


def setup_cache(cache_name: str = "mediadive_bulk_cache"):
    """Set up HTTP caching to avoid re-downloading data."""
    requests_cache.install_cache(cache_name, backend="sqlite")
    print(f"HTTP cache enabled: {cache_name}.sqlite")


def get_json_from_api(
    url: str, retry_count: int = 3, retry_delay: float = 2.0, verbose: bool = False
) -> Dict:
    """
    Get JSON data from MediaDive API with retry logic.

    Args:
    ----
        url: Full API URL to fetch
        retry_count: Number of retries on failure
        retry_delay: Delay in seconds between retries
        verbose: If True, log empty responses (useful for debugging)

    Returns:
    -------
        Dictionary with API response data (empty dict on failure or empty response)

    """
    for attempt in range(retry_count):
        try:
            r = requests.get(url, timeout=30)
            r.raise_for_status()
            data_json = r.json()
            result = data_json.get(DATA_KEY, {})
            # Distinguish empty API response from failure (for debugging)
            if not result and verbose:
                print(f"  Empty response from API: {url}")
            return result
        except requests.exceptions.RequestException as e:
            if attempt < retry_count - 1:
                logger.debug(f"Retry {attempt + 1}/{retry_count} after error: {e} (URL: {url})")
                time.sleep(retry_delay)
            else:
                # Log to file instead of stdout - 404s are expected for media without strains
                logger.warning(f"Request failed after {retry_count} attempts: {e} (URL: {url})")
                return {}


def load_basic_media_list(basic_file: str) -> List[Dict]:
    """
    Load basic media list from already downloaded file.

    Args:
    ----
        basic_file: Path to mediadive.json file

    Returns:
    -------
        List of media records with basic info

    """
    print(f"Loading basic media list from {basic_file}")
    with open(basic_file) as f:
        data = json.load(f)
        media_list = data.get(DATA_KEY, [])
        print(f"Found {len(media_list)} media records")
        return media_list


def download_detailed_media(media_list: List[Dict]) -> Dict[str, Dict]:
    """
    Download detailed recipe information for all media.

    Args:
    ----
        media_list: List of basic media records

    Returns:
    -------
        Dictionary mapping medium_id -> detailed_recipe_data

    """
    print(f"\nDownloading detailed recipes for {len(media_list)} media...")
    detailed_data = {}

    for medium in tqdm(media_list, desc="Downloading medium details"):
        medium_id = str(medium.get(ID_KEY))
        url = MEDIADIVE_REST_API_BASE_URL + MEDIUM_ENDPOINT + medium_id
        data = get_json_from_api(url)
        if data:
            detailed_data[medium_id] = data

    print(f"Downloaded {len(detailed_data)} detailed medium recipes")
    return detailed_data


def download_medium_strains(media_list: List[Dict]) -> Dict[str, List]:
    """
    Download strain associations for all media.

    Args:
    ----
        media_list: List of basic media records

    Returns:
    -------
        Dictionary mapping medium_id -> list_of_strain_data

    """
    print(f"\nDownloading strain associations for {len(media_list)} media...")
    strain_data = {}

    for medium in tqdm(media_list, desc="Downloading medium-strain associations"):
        medium_id = str(medium.get(ID_KEY))
        url = MEDIADIVE_REST_API_BASE_URL + MEDIUM_STRAINS_ENDPOINT + medium_id
        data = get_json_from_api(url)
        if data:
            strain_data[medium_id] = data

    # Count total strain associations, handling different data types
    total_strains = 0
    for medium_id, v in strain_data.items():
        if isinstance(v, list):
            total_strains += len(v)
        elif isinstance(v, dict):
            total_strains += len(v)
        else:
            print(
                f"Warning: Unexpected strain data type for medium {medium_id}: {type(v).__name__}"
            )

    print(
        f"Downloaded strain associations for {len(strain_data)} media ({total_strains} total associations)"
    )
    return strain_data


def extract_solutions_from_media(detailed_media: Dict[str, Dict]) -> Dict[str, Dict]:
    """
    Extract solution data from embedded structure in detailed_media.

    Instead of making API calls, extract solutions directly from media_detailed.json.

    Args:
    ----
        detailed_media: Dictionary of detailed medium recipes

    Returns:
    -------
        Dictionary mapping solution_id -> solution_data

    """
    solutions_data = {}

    for medium_data in detailed_media.values():
        if SOLUTIONS_KEY in medium_data and isinstance(medium_data[SOLUTIONS_KEY], list):
            for solution in medium_data[SOLUTIONS_KEY]:
                if isinstance(solution, dict) and ID_KEY in solution:
                    sol_id = str(solution[ID_KEY])
                    # Only add if not already present (avoid duplicates)
                    if sol_id not in solutions_data:
                        solutions_data[sol_id] = solution

    return solutions_data


def extract_compounds_from_media(detailed_media: Dict[str, Dict]) -> Dict[str, Dict]:
    """
    Extract compound data from embedded structure in detailed_media.

    Instead of making API calls, extract compound info directly from media_detailed.json.

    Args:
    ----
        detailed_media: Dictionary of detailed medium recipes

    Returns:
    -------
        Dictionary mapping compound_id -> compound_data

    """
    compounds_data = {}

    for medium_data in detailed_media.values():
        if SOLUTIONS_KEY in medium_data and isinstance(medium_data[SOLUTIONS_KEY], list):
            for solution in medium_data[SOLUTIONS_KEY]:
                if isinstance(solution, dict) and RECIPE_KEY in solution:
                    recipe = solution[RECIPE_KEY]
                    if isinstance(recipe, list):
                        for ingredient in recipe:
                            if isinstance(ingredient, dict) and COMPOUND_ID_KEY in ingredient:
                                comp_id = str(ingredient[COMPOUND_ID_KEY])
                                # Only add if not already present (avoid duplicates)
                                if comp_id not in compounds_data:
                                    # Store the ingredient data (has compound, compound_id, etc.)
                                    compounds_data[comp_id] = ingredient

    return compounds_data


def save_json_file(data: Dict, filepath: Path, description: str):
    """Save data to JSON file with logging."""
    filepath.parent.mkdir(parents=True, exist_ok=True)
    with open(filepath, "w") as f:
        json.dump(data, f, indent=2)
    file_size_mb = filepath.stat().st_size / (1024 * 1024)
    print(f"Saved {description} to {filepath} ({file_size_mb:.2f} MB)")


def download_mediadive_bulk(basic_file: str, output_dir: str):
    """
    Download all MediaDive data in bulk.

    This is the main entry point called from kg_microbe.download.

    Args:
    ----
        basic_file: Path to mediadive.json (basic media list)
        output_dir: Directory to save bulk data files

    """
    output_path = Path(output_dir)

    # Create output directory
    output_path.mkdir(parents=True, exist_ok=True)

    # Set up file logging for API warnings (not printed to stdout)
    log_file = output_path / "mediadive_download.log"
    file_handler = logging.FileHandler(log_file, mode="w")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
    logger.addHandler(file_handler)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False  # Prevent propagation to root logger and stdout
    print(f"API warnings will be logged to: {log_file}")

    # Set up HTTP caching
    setup_cache()

    # Step 1: Load basic media list
    print("\n[1/5] Loading basic media list...")
    media_list = load_basic_media_list(basic_file)

    # Step 2: Download detailed medium recipes
    print("\n[2/5] Downloading detailed medium recipes...")
    detailed_media = download_detailed_media(media_list)
    save_json_file(detailed_media, output_path / "media_detailed.json", "detailed media recipes")

    # Step 3: Download medium-strain associations
    print("\n[3/5] Downloading medium-strain associations...")
    media_strains = download_medium_strains(media_list)
    save_json_file(media_strains, output_path / "media_strains.json", "medium-strain associations")

    # Step 4: Extract solutions from embedded structure
    print("\n[4/5] Extracting solutions from embedded structure...")
    solutions_data = extract_solutions_from_media(detailed_media)
    print(f"Extracted {len(solutions_data)} unique solutions from embedded data")
    save_json_file(solutions_data, output_path / "solutions.json", "solution data")

    # Step 5: Extract compounds from embedded structure
    # Compound data is embedded in the recipe structure of detailed media
    # The transform will use MicroMediaParam mappings and fall back to mediadive.ingredient: prefix
    print("\n[5/5] Extracting compounds from embedded structure...")
    compounds_data = extract_compounds_from_media(detailed_media)
    print(f"Extracted {len(compounds_data)} compounds from embedded data")
    save_json_file(compounds_data, output_path / "compounds.json", "compound data")

    # Summary
    print("\n" + "=" * 80)
    print("MediaDive bulk download summary:")
    print("=" * 80)
    print(f"Output directory: {output_path}")
    print(f"  - {len(media_list)} media records (basic)")
    print(f"  - {len(detailed_media)} media recipes (detailed)")
    print(f"  - {len(media_strains)} media-strain associations")
    print(f"  - {len(solutions_data)} solutions")
    print(f"  - {len(compounds_data)} compounds")
    print(f"\nAPI warnings logged to: {output_path / 'mediadive_download.log'}")
    print("These files will be used by the MediaDive transform to avoid API calls.")
    print("=" * 80)
