"""
MediaDive bulk download utility.

This module provides functionality to download all MediaDive data in bulk
to avoid repeated API calls during transforms.
"""

import json
import time
from pathlib import Path
from typing import Dict, List, Set

import requests
import requests_cache
from tqdm import tqdm

# MediaDive REST API base URL
MEDIADIVE_REST_API_BASE_URL = "https://mediadive.dsmz.de/rest/"

# API endpoints
MEDIA_ENDPOINT = "media"
MEDIUM_ENDPOINT = "medium/"
MEDIUM_STRAINS_ENDPOINT = "medium_strains/"
SOLUTION_ENDPOINT = "solution/"
COMPOUND_ENDPOINT = "compound/"

# Keys in JSON responses
DATA_KEY = "data"
ID_KEY = "id"
SOLUTIONS_KEY = "solutions"
RECIPE_KEY = "recipe"
COMPOUND_KEY = "compound"
SOLUTION_ID_KEY = "solution_id"


def setup_cache(cache_name: str = "mediadive_bulk_cache"):
    """Set up HTTP caching to avoid re-downloading data."""
    requests_cache.install_cache(cache_name, backend="sqlite")
    print(f"HTTP cache enabled: {cache_name}.sqlite")


def get_json_from_api(url: str, retry_count: int = 3, retry_delay: float = 2.0) -> Dict:
    """
    Get JSON data from MediaDive API with retry logic.

    Args:
    ----
        url: Full API URL to fetch
        retry_count: Number of retries on failure
        retry_delay: Delay in seconds between retries

    Returns:
    -------
        Dictionary with API response data

    """
    for attempt in range(retry_count):
        try:
            r = requests.get(url, timeout=30)
            r.raise_for_status()
            data_json = r.json()
            return data_json.get(DATA_KEY, {})
        except requests.exceptions.RequestException as e:
            if attempt < retry_count - 1:
                print(f"  Retry {attempt + 1}/{retry_count} after error: {e}")
                time.sleep(retry_delay)
            else:
                print(f"  Failed after {retry_count} attempts: {e}")
                return {}
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

    total_strains = sum(len(v) if isinstance(v, list) else 1 for v in strain_data.values())
    print(f"Downloaded strain associations for {len(strain_data)} media ({total_strains} total associations)")
    return strain_data


def extract_solution_ids(detailed_media: Dict[str, Dict]) -> Set[str]:
    """
    Extract all unique solution IDs from detailed media data.

    Args:
    ----
        detailed_media: Dictionary of detailed medium recipes

    Returns:
    -------
        Set of unique solution IDs

    """
    solution_ids = set()

    for medium_data in detailed_media.values():
        if RECIPE_KEY in medium_data:
            recipe = medium_data[RECIPE_KEY]
            if SOLUTIONS_KEY in recipe and isinstance(recipe[SOLUTIONS_KEY], dict):
                for sol_id in recipe[SOLUTIONS_KEY].keys():
                    solution_ids.add(str(sol_id))

    return solution_ids


def download_solutions(solution_ids: Set[str]) -> Dict[str, Dict]:
    """
    Download solution ingredient data for all solution IDs.

    Args:
    ----
        solution_ids: Set of solution IDs to download

    Returns:
    -------
        Dictionary mapping solution_id -> solution_data

    """
    print(f"\nDownloading {len(solution_ids)} unique solutions...")
    solutions_data = {}

    for solution_id in tqdm(sorted(solution_ids), desc="Downloading solutions"):
        url = MEDIADIVE_REST_API_BASE_URL + SOLUTION_ENDPOINT + solution_id
        data = get_json_from_api(url)
        if data:
            solutions_data[solution_id] = data

    print(f"Downloaded {len(solutions_data)} solutions")
    return solutions_data


def extract_compound_ids(solutions_data: Dict[str, Dict]) -> Set[str]:
    """
    Extract all unique compound IDs from solution data.

    Args:
    ----
        solutions_data: Dictionary of solution data

    Returns:
    -------
        Set of unique compound IDs

    """
    compound_ids = set()

    for solution_data in solutions_data.values():
        if isinstance(solution_data, dict):
            for key, value in solution_data.items():
                if isinstance(value, dict) and COMPOUND_KEY in value:
                    compound_id = value[COMPOUND_KEY]
                    if compound_id:
                        compound_ids.add(str(compound_id))

    return compound_ids


def download_compounds(compound_ids: Set[str]) -> Dict[str, Dict]:
    """
    Download compound mapping data for all compound IDs.

    Args:
    ----
        compound_ids: Set of compound IDs to download

    Returns:
    -------
        Dictionary mapping compound_id -> compound_data

    """
    print(f"\nDownloading {len(compound_ids)} unique compounds...")
    compounds_data = {}

    for compound_id in tqdm(sorted(compound_ids), desc="Downloading compounds"):
        url = MEDIADIVE_REST_API_BASE_URL + COMPOUND_ENDPOINT + compound_id
        data = get_json_from_api(url)
        if data:
            compounds_data[compound_id] = data

    print(f"Downloaded {len(compounds_data)} compounds")
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

    # Set up HTTP caching
    setup_cache()

    # Create output directory
    output_path.mkdir(parents=True, exist_ok=True)

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

    # Step 4: Download solutions
    print("\n[4/5] Extracting and downloading solutions...")
    solution_ids = extract_solution_ids(detailed_media)
    print(f"Found {len(solution_ids)} unique solution IDs")
    solutions_data = download_solutions(solution_ids)
    save_json_file(solutions_data, output_path / "solutions.json", "solution data")

    # Step 5: Download compounds
    print("\n[5/5] Extracting and downloading compounds...")
    compound_ids = extract_compound_ids(solutions_data)
    print(f"Found {len(compound_ids)} unique compound IDs")
    compounds_data = download_compounds(compound_ids)
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
    print("\nThese files will be used by the MediaDive transform to avoid API calls.")
    print("=" * 80)
