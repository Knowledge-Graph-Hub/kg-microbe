"""Organism-specific query functions for KG-Microbe."""

from typing import Dict, List, Optional

import duckdb
import pandas as pd


def resolve_organism_name(conn: duckdb.DuckDBPyConnection, name: str) -> Dict[str, str]:
    """
    Resolve organism name to NCBITaxon ID using fuzzy matching.

    :param conn: DuckDB connection
    :param name: Organism name to search
    :return: Dict with 'id', 'name', 'synonym' keys
    :raises ValueError: If no organism found or multiple matches
    """
    query = """
    SELECT id, name, synonym
    FROM nodes
    WHERE category = 'biolink:OrganismTaxon'
      AND id LIKE 'NCBITaxon:%'
      AND (LOWER(name) LIKE '%' || LOWER(?) || '%'
           OR LOWER(synonym) LIKE '%' || LOWER(?) || '%')
    ORDER BY CASE
        WHEN LOWER(name) = LOWER(?) THEN 1
        WHEN LOWER(synonym) LIKE '%' || LOWER(?) || '%' THEN 2
        ELSE 3 END
    LIMIT 10;
    """

    result = conn.execute(query, [name, name, name, name]).fetchall()

    if not result:
        raise ValueError(
            f"No organism found matching '{name}'. "
            f"Try checking NCBITaxon directly or using a different spelling."
        )

    if len(result) > 1:
        print("Multiple matches found:")
        for row in result[:5]:
            print(f"  - {row[1]} ({row[0]})")
        print(f"\nUsing first match: {result[0][1]} ({result[0][0]})")

    return {
        "id": result[0][0],
        "name": result[0][1],
        "synonym": result[0][2] if result[0][2] else "",
    }


def get_organism_traits(
    conn: duckdb.DuckDBPyConnection, taxon_id: str
) -> pd.DataFrame:
    """
    Get all direct trait edges from organism (1-hop).

    :param conn: DuckDB connection
    :param taxon_id: NCBITaxon ID (e.g., 'NCBITaxon:84112')
    :return: DataFrame with predicate, object, object_name, category, source columns
    """
    query = """
    SELECT
        e.predicate,
        e.relation,
        e.object,
        n.name AS object_name,
        n.category AS object_category,
        e.primary_knowledge_source
    FROM edges e
    LEFT JOIN nodes n ON e.object = n.id
    WHERE e.subject = ?
    ORDER BY e.predicate, n.name;
    """

    return conn.execute(query, [taxon_id]).df()


def get_media_preferences(
    conn: duckdb.DuckDBPyConnection, taxon_id: str
) -> Dict[str, List[Dict]]:
    """
    Get growth media preferences (grows in / doesn't grow in).

    :param conn: DuckDB connection
    :param taxon_id: NCBITaxon ID
    :return: Dict with 'grows_in' and 'no_growth' lists
    """
    query = """
    SELECT
        e.predicate,
        e.object AS medium_id,
        n.name AS medium_name,
        e.primary_knowledge_source
    FROM edges e
    JOIN nodes n ON e.object = n.id
    WHERE e.subject = ?
      AND e.predicate IN ('METPO:2000517', 'METPO:2000518')
    ORDER BY e.predicate, n.name;
    """

    result = conn.execute(query, [taxon_id]).fetchall()

    grows_in = []
    no_growth = []

    for predicate, medium_id, medium_name, source in result:
        media_entry = {
            "medium_id": medium_id,
            "medium_name": medium_name,
            "source": source,
        }

        if predicate == "METPO:2000517":  # grows in
            grows_in.append(media_entry)
        elif predicate == "METPO:2000518":  # doesn't grow in
            no_growth.append(media_entry)

    return {"grows_in": grows_in, "no_growth": no_growth}


def get_media_composition(
    conn: duckdb.DuckDBPyConnection, medium_ids: List[str]
) -> pd.DataFrame:
    """
    Get chemical composition of growth media (2-hop: medium → solution → chemical).

    :param conn: DuckDB connection
    :param medium_ids: List of medium IDs (e.g., ['mediadive.medium:693'])
    :return: DataFrame with medium_id, chemical_count, chemicals columns
    """
    if not medium_ids:
        return pd.DataFrame(
            columns=["medium_id", "chemical_count", "chemicals"]
        )

    # Convert list to SQL array format
    medium_list = ", ".join([f"'{mid}'" for mid in medium_ids])

    query = f"""
    WITH media_solutions AS (
        SELECT
            e.subject AS medium_id,
            e.object AS solution_id
        FROM edges e
        WHERE e.subject IN ({medium_list})
          AND e.predicate = 'biolink:has_part'
          AND e.object LIKE 'mediadive.solution:%'
    ),
    solution_chemicals AS (
        SELECT
            ms.medium_id,
            e2.object AS chemical_id,
            n.name AS chemical_name
        FROM media_solutions ms
        JOIN edges e2 ON e2.subject = ms.solution_id
        LEFT JOIN nodes n ON n.id = e2.object
        WHERE e2.predicate = 'biolink:has_part'
          AND (e2.object LIKE 'CHEBI:%' OR e2.object LIKE 'mediadive.ingredient:%')
    )
    SELECT
        medium_id,
        COUNT(DISTINCT chemical_id) AS chemical_count,
        STRING_AGG(DISTINCT chemical_name, '; ' ORDER BY chemical_name) AS chemicals
    FROM solution_chemicals
    GROUP BY medium_id;
    """

    return conn.execute(query).df()


def get_strain_info(conn: duckdb.DuckDBPyConnection, taxon_id: str) -> pd.DataFrame:
    """
    Get strain nodes linked to species via subclass_of.

    :param conn: DuckDB connection
    :param taxon_id: NCBITaxon ID
    :return: DataFrame with strain IDs and names
    """
    query = """
    SELECT DISTINCT
        n.id AS strain_id,
        n.name AS strain_name
    FROM edges e
    JOIN nodes n ON e.subject = n.id
    WHERE e.object = ?
      AND e.predicate = 'biolink:subclass_of'
      AND (e.subject LIKE 'kgmicrobe.strain:%' OR e.subject LIKE 'NCBITaxon:%')
    ORDER BY n.name;
    """

    return conn.execute(query, [taxon_id]).df()


def query_organism_full(
    conn: duckdb.DuckDBPyConnection, organism_name: str
) -> Dict:
    """
    Execute comprehensive organism query and return all information.

    :param conn: DuckDB connection
    :param organism_name: Organism name to search
    :return: Dict with all query results
    """
    # Step 1: Resolve organism name
    organism = resolve_organism_name(conn, organism_name)
    taxon_id = organism["id"]

    # Step 2: Get all trait edges
    traits = get_organism_traits(conn, taxon_id)

    # Step 3: Get media preferences
    media = get_media_preferences(conn, taxon_id)

    # Step 4: Get media composition (2-hop)
    medium_ids = [m["medium_id"] for m in media["grows_in"]]
    composition = get_media_composition(conn, medium_ids)

    # Step 5: Get strain information
    strains = get_strain_info(conn, taxon_id)

    # Step 6: Extract data sources
    sources = set()
    if not traits.empty and "primary_knowledge_source" in traits.columns:
        for source in traits["primary_knowledge_source"].dropna():
            if ":" in source:
                sources.add(source.split(":")[0])

    for m in media["grows_in"] + media["no_growth"]:
        if m["source"] and ":" in m["source"]:
            sources.add(m["source"].split(":")[0])

    return {
        "taxon_id": taxon_id,
        "name": organism["name"],
        "synonyms": organism["synonym"].split("|") if organism["synonym"] else [],
        "traits": traits,
        "media": media,
        "composition": composition,
        "strains": strains,
        "sources": sorted(sources),
    }
