import os
import re
from urllib.parse import unquote

import requests


def normalize_notion_id(raw_value: str) -> str:
    value = unquote(str(raw_value or "").strip())
    if not value:
        return ""

    matches = re.findall(
        r"[0-9a-fA-F]{32}|[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}",
        value,
    )
    return matches[-1].lower() if matches else value


def fetch_parent(api_key: str, parent_type: str, parent_id: str):
    return requests.get(
        f"https://api.notion.com/v1/{parent_type}s/{parent_id}",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Notion-Version": "2026-03-11",
        },
        timeout=10,
    )


api_key = os.getenv("NOTION_API_KEY", "")
data_source_id = normalize_notion_id(os.getenv("NOTION_DATA_SOURCE_ID", ""))
database_id = normalize_notion_id(os.getenv("NOTION_DATABASE_ID", ""))

parent_type = "data_source" if data_source_id else "database"
parent_id = data_source_id or database_id

print(f"NOTION_API_KEY       : {'SET (' + api_key[:8] + '...)' if api_key else 'MISSING'}")
print(f"NOTION_DATA_SOURCE_ID: {'SET (' + data_source_id[:8] + '...)' if data_source_id else 'MISSING'}")
print(f"NOTION_DATABASE_ID   : {'SET (' + database_id[:8] + '...)' if database_id else 'MISSING'}")

if not api_key or not parent_id:
    print("\nEnvironment variables are missing. Load your .env or launch from the app first.")
    raise SystemExit(1)

print("\nTesting Notion API connection...")
resp = fetch_parent(api_key, parent_type, parent_id)

if resp.status_code == 404 and parent_type == "data_source":
    print("Data source lookup returned 404. Retrying the same ID as a database...")
    resp = fetch_parent(api_key, "database", parent_id)
    if resp.status_code == 200:
        parent_type = "database"

if resp.status_code == 200:
    data = resp.json()
    title = data.get("title", [{}])
    parent_name = title[0].get("plain_text", "(no title)") if title else "(no title)"
    props = list(data.get("properties", {}).keys())
    print("Connection successful")
    print(f"Resolved as: {parent_type}")
    print(f"Name       : {parent_name}")
    print(f"Properties : {props}")
elif resp.status_code == 401:
    print("Failed: API key is invalid.")
elif resp.status_code == 404:
    print("Failed: ID not found, or the integration is not shared to this parent.")
    print("Open the target Notion database/data source and confirm the BlogAuto integration is connected.")
else:
    print(f"Failed: HTTP {resp.status_code}: {resp.text}")
