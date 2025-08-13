#!/usr/bin/env python3
"""Download a subset of BacDive data for testing."""

import os
import time
from datetime import datetime, timezone
from typing import List, Dict, Any

import bacdive
import click
from dotenv import load_dotenv
from pymongo import MongoClient


@click.command()
@click.option(
    "--start-id",
    default=1,
    type=int,
    help="Starting BacDive ID to begin download from [1]"
)
@click.option(
    "--end-id",
    default=100,
    type=int,
    help="Ending BacDive ID to download to [100]"
)
@click.option(
    "--mongo-uri",
    default="mongodb://localhost:27017/",
    help="MongoDB connection URI [mongodb://localhost:27017/]"
)
@click.option(
    "--database", "-d",
    default="bacdive",
    help="MongoDB database name [bacdive]"
)
@click.option(
    "--collection",
    default="strains_api",
    help="MongoDB collection name [strains_api]"
)
@click.option(
    "--chunk-size",
    default=100,
    type=int,
    help="Number of records to request per API call [100]"
)
@click.option(
    "--delay",
    default=1.0,
    type=float,
    help="Delay between API calls in seconds [1.0]"
)
@click.option(
    "--drop-collection",
    is_flag=True,
    help="Drop the collection before inserting new data"
)
def download_bacdive_subset(
    start_id: int,
    end_id: int,
    mongo_uri: str, 
    database: str, 
    collection: str, 
    chunk_size: int, 
    delay: float,
    drop_collection: bool
) -> None:
    """Download a subset of BacDive records and store them in MongoDB.
    
    Requires BACDIVE_USERNAME and BACDIVE_PASSWORD environment variables.
    Load from .env file or set in shell.
    """
    # Load environment variables
    load_dotenv()

    username = os.getenv("BACDIVE_USERNAME")
    password = os.getenv("BACDIVE_PASSWORD")

    if not username or not password:
        click.echo("❌ Error: BACDIVE_USERNAME and BACDIVE_PASSWORD environment variables must be set", err=True)
        click.echo("Copy .env.example to .env and add your credentials", err=True)
        raise click.Abort()

    # Connect to MongoDB
    try:
        mongo_client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
        # Test connection
        mongo_client.server_info()
        db = mongo_client[database]
        coll = db[collection]
        click.echo(f"🗄️  Connected to MongoDB: {database}.{collection}")
        
        if drop_collection:
            coll.drop()
            click.echo(f"🗑️  Dropped collection {collection}")
            
    except Exception as e:
        click.echo(f"❌ MongoDB connection failed: {e}", err=True)
        click.echo("Make sure MongoDB is running on localhost:27017", err=True)
        raise click.Abort()

    count = end_id - start_id + 1
    click.echo(f"📥 Downloading {count} BacDive records (IDs {start_id} to {end_id})...")

    # Connect to BacDive API
    try:
        client = bacdive.BacdiveClient(username, password)
        click.echo("✅ BacDive authentication successful")
    except Exception as e:
        click.echo(f"❌ BacDive authentication failed: {e}", err=True)
        raise click.Abort()

    client.setSearchType('exact')
    total_inserted = 0

    with click.progressbar(range(start_id, end_id + 1, chunk_size), label="Downloading") as chunks:
        for batch_start in chunks:
            batch_end = min(batch_start + chunk_size - 1, end_id)
            
            id_list = ";".join(str(i) for i in range(batch_start, batch_end + 1))
            batch_records: List[Dict[str, Any]] = []
            
            try:
                search_query = {"id": id_list}
                client.search(**search_query)
                
                # Collect batch records
                for record in client.retrieve():
                    batch_records.append(record)
                
                # Insert batch to MongoDB
                if batch_records:
                    result = coll.insert_many(batch_records)
                    batch_count = len(result.inserted_ids)
                    total_inserted += batch_count
                    click.echo(f"  💾 Inserted {batch_count} records (IDs {batch_start}-{batch_end})")
                else:
                    click.echo(f"  ⚠️  No records found for IDs {batch_start}-{batch_end}")
                    
            except Exception as e:
                click.echo(f"⚠️  Warning: Failed to process IDs {batch_start}-{batch_end}: {e}", err=True)
                continue
            
            time.sleep(delay)

    # Final summary
    try:
        total_in_db = coll.count_documents({})
        click.echo(f"✅ Done! {total_inserted} new records inserted")
        click.echo(f"📊 Total records in {database}.{collection}: {total_in_db}")
        
        if total_inserted == 0:
            click.echo("⚠️  Warning: No records were retrieved. Check your credentials and try a smaller subset.", err=True)
            
    except Exception as e:
        click.echo(f"⚠️  Could not get final count: {e}", err=True)
    
    finally:
        mongo_client.close()


if __name__ == "__main__":
    download_bacdive_subset()