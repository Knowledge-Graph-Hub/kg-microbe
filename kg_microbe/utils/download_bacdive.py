"""Download BacDive data using the BacDive API."""

import json
import os
import time

import bacdive
from dotenv import load_dotenv

# ------------------------------------------------------------------------
# 1) Initialize the client with your BacDive API credentials
#    Read credentials from environment variables loaded from .env file
# ------------------------------------------------------------------------
# Load environment variables from .env file
load_dotenv()

username = os.getenv("BACDIVE_USERNAME")
password = os.getenv("BACDIVE_PASSWORD")

if not username or not password:
    raise ValueError("BACDIVE_USERNAME and BACDIVE_PASSWORD environment variables must be set")

client = bacdive.BacdiveClient(username, password)
print("-- Authentication successful --")

# Optional: set the search type. Default is 'exact'.
# Other valid values: 'contains', 'startswith', 'endswith'
# If you're grabbing everything, the search type here is less important,
# but we'll set it to 'contains' just as an example.
client.setSearchType('exact')
max_id = 200000
chunk_size = 100

all_bacdive_data = []

# ------------------------------------------------------------------------
# 3) Loop over ID ranges, 100 at a time
# ------------------------------------------------------------------------
for start_id in range(1, max_id + 1, chunk_size):
    end_id = min(start_id + chunk_size - 1, max_id)

    # Build a semicolon-delimited list of IDs: e.g., "1;2;3;...;100"
    id_list = ";".join(str(i) for i in range(start_id, end_id + 1))

    print(f"Processing IDs {start_id} through {end_id} ...")

    # Construct the query dict and perform the search
    search_query = {"id": id_list}
    client.search(**search_query)

    # Use this to track whether this chunk returned *any* records
    chunk_empty = True

    # Retrieve *all* results for this query (client.retrieve() handles paging)
    for record in client.retrieve():
        all_bacdive_data.append(record)
        chunk_empty = False

    # If this entire chunk is empty (no records found) and we're already past ID 100,000,
    # then break out of the loop to skip the rest.
    #if chunk_empty and start_id > 100000:
    #    print(f"No results for IDs {start_id}..{end_id}, past 100000. Terminating early.")
    #    break

    # Optional: Sleep a bit to avoid rate-limiting or server overload
    time.sleep(1)

# ------------------------------------------------------------------------
# 4) Store all collected data in a JSON file
# ------------------------------------------------------------------------
output_file = "bacdive_data_all.json"
with open(output_file, "w", encoding="utf-8") as f:
    json.dump(all_bacdive_data, f, indent=2)

print(f"Done! A total of {len(all_bacdive_data)} records saved to '{output_file}'.")
