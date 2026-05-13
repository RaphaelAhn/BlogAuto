import os
import re
from datetime import datetime
from urllib.parse import unquote

import requests


NOTION_API_BASE = "https://api.notion.com/v1"
NOTION_VERSION = os.getenv("NOTION_VERSION", "2026-03-11")
DEFAULT_CHECKLIST_ITEMS = [
    "검수 필요",
    "대표 이미지 추가",
    "블로그 업로드",
    "발행 완료",
]


def _get_bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    if raw in {"1", "true", "yes", "y", "on"}:
        return True
    if raw in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _clean_text(value) -> str:
    return str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()


def _normalize_keyword(value) -> str:
    text = str(value or "").lower()
    text = re.sub(r"\s+", "", text)
    return text.replace("-", "").replace("_", "").strip()


def _normalize_notion_id(raw_value: str) -> str:
    value = unquote(str(raw_value or "").strip())
    if not value:
        return ""

    if re.fullmatch(r"[0-9a-fA-F]{32}", value):
        return value.lower()
    if re.fullmatch(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", value):
        return value.lower()

    matches = re.findall(
        r"[0-9a-fA-F]{32}|[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}",
        value,
    )
    if matches:
        return matches[-1].lower()

    return value


def _get_preferred_notion_parent() -> tuple[str, str]:
    data_source_id = _normalize_notion_id(os.getenv("NOTION_DATA_SOURCE_ID", ""))
    database_id = _normalize_notion_id(os.getenv("NOTION_DATABASE_ID", ""))

    if data_source_id:
        return "data_source_id", data_source_id
    if database_id:
        return "database_id", database_id

    parent_type = os.getenv("NOTION_PARENT_TYPE", "").strip()
    parent_id = _normalize_notion_id(os.getenv("NOTION_PARENT_ID", ""))
    if parent_type == "data_source_id" and parent_id:
        return "data_source_id", parent_id
    if parent_type == "database_id" and parent_id:
        return "database_id", parent_id

    return "", ""


def _chunk_text(text: str, limit: int = 1900) -> list[str]:
    normalized = str(text or "")
    if not normalized:
        return []

    chunks = []
    current = ""
    for line in normalized.split("\n"):
        candidate = f"{current}\n{line}".strip("\n") if current else line
        if len(candidate) <= limit:
            current = candidate
            continue
        if current:
            chunks.append(current)
        while len(line) > limit:
            chunks.append(line[:limit])
            line = line[limit:]
        current = line
    if current:
        chunks.append(current)
    return [chunk for chunk in chunks if chunk]


def _rich_text(text: str) -> list[dict]:
    return [{"type": "text", "text": {"content": chunk}} for chunk in _chunk_text(text)] or [
        {"type": "text", "text": {"content": ""}}
    ]


def _paragraph_block(text: str) -> dict:
    return {"object": "block", "type": "paragraph", "paragraph": {"rich_text": _rich_text(text)}}


def _heading_block(level: int, text: str) -> dict:
    block_type = f"heading_{max(1, min(level, 3))}"
    return {"object": "block", "type": block_type, block_type: {"rich_text": _rich_text(text)}}


def _list_block(block_type: str, text: str, checked: bool | None = None) -> dict:
    payload = {"rich_text": _rich_text(text)}
    if checked is not None:
        payload["checked"] = checked
    return {"object": "block", "type": block_type, block_type: payload}


def _quote_block(text: str) -> dict:
    return {"object": "block", "type": "quote", "quote": {"rich_text": _rich_text(text)}}


def _code_block(text: str, language: str = "plain text") -> dict:
    return {
        "object": "block",
        "type": "code",
        "code": {
            "rich_text": _rich_text(text),
            "language": language,
        },
    }


def _parse_checklist_items(raw: str) -> list[str]:
    items = [item.strip() for item in str(raw or "").split("|")]
    return [item for item in items if item]


def _build_management_blocks() -> list[dict]:
    if not _get_bool_env("NOTION_INCLUDE_MANAGEMENT_CHECKLIST", True):
        return []

    items = _parse_checklist_items(os.getenv("NOTION_CHECKLIST_ITEMS", ""))
    if not items:
        items = DEFAULT_CHECKLIST_ITEMS[:]

    blocks = [_heading_block(2, "관리 체크리스트")]
    for item in items:
        blocks.append(_list_block("to_do", item, checked=False))
    return blocks


def _article_to_blocks(article_text: str, title: str) -> list[dict]:
    lines = _clean_text(article_text).split("\n")
    blocks = []
    buffer: list[str] = []
    in_code = False
    code_lines: list[str] = []
    code_language = "plain text"

    def flush_buffer():
        nonlocal buffer
        if not buffer:
            return
        paragraph = "\n".join(buffer).strip()
        if paragraph:
            for chunk in _chunk_text(paragraph):
                blocks.append(_paragraph_block(chunk))
        buffer = []

    for index, raw_line in enumerate(lines):
        line = raw_line.rstrip()
        stripped = line.strip()

        if in_code:
            if stripped.startswith("```"):
                blocks.append(_code_block("\n".join(code_lines).strip(), code_language))
                in_code = False
                code_lines = []
                code_language = "plain text"
            else:
                code_lines.append(line)
            continue

        if stripped.startswith("```"):
            flush_buffer()
            in_code = True
            code_language = stripped[3:].strip() or "plain text"
            code_lines = []
            continue

        if not stripped:
            flush_buffer()
            continue

        heading_match = re.match(r"^(#{1,3})\s+(.+)$", stripped)
        if heading_match:
            flush_buffer()
            level = len(heading_match.group(1))
            heading_text = heading_match.group(2).strip()
            if index == 0 and _normalize_keyword(heading_text) == _normalize_keyword(title):
                continue
            blocks.append(_heading_block(level, heading_text))
            continue

        todo_match = re.match(r"^- \[( |x|X)\]\s+(.+)$", stripped)
        if todo_match:
            flush_buffer()
            checked = todo_match.group(1).lower() == "x"
            blocks.append(_list_block("to_do", todo_match.group(2).strip(), checked=checked))
            continue

        bullet_match = re.match(r"^[-*]\s+(.+)$", stripped)
        if bullet_match:
            flush_buffer()
            blocks.append(_list_block("bulleted_list_item", bullet_match.group(1).strip()))
            continue

        number_match = re.match(r"^\d+[.)]\s+(.+)$", stripped)
        if number_match:
            flush_buffer()
            blocks.append(_list_block("numbered_list_item", number_match.group(1).strip()))
            continue

        quote_match = re.match(r"^>\s+(.+)$", stripped)
        if quote_match:
            flush_buffer()
            blocks.append(_quote_block(quote_match.group(1).strip()))
            continue

        buffer.append(line)

    flush_buffer()

    if in_code and code_lines:
        blocks.append(_code_block("\n".join(code_lines).strip(), code_language))

    return blocks


def _notion_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Notion-Version": NOTION_VERSION,
    }


def _request(method: str, url: str, api_key: str, **kwargs):
    response = requests.request(method, url, headers=_notion_headers(api_key), timeout=45, **kwargs)
    if response.ok:
        return response.json() if response.text else {}

    try:
        error_payload = response.json()
        message = error_payload.get("message") or error_payload.get("code") or response.text
    except ValueError:
        message = response.text
    raise RuntimeError(f"Notion API {response.status_code}: {message}")


def _extract_first_data_source_id(database_payload: dict) -> str:
    data_sources = database_payload.get("data_sources") or []
    if not data_sources:
        return ""
    return _normalize_notion_id(data_sources[0].get("id", ""))


def _resolve_data_source_from_database(api_key: str, database_id: str) -> dict:
    database = _request("GET", f"{NOTION_API_BASE}/databases/{database_id}", api_key)
    data_source_id = _extract_first_data_source_id(database)
    if not data_source_id:
        raise RuntimeError(
            "Notion 데이터베이스 아래의 data source ID를 찾지 못했습니다. "
            "현재 API 버전(2026-03-11)에서는 database가 아니라 data source를 기준으로 행을 조회해야 합니다."
        )

    data_source = _request("GET", f"{NOTION_API_BASE}/data_sources/{data_source_id}", api_key)
    return {
        "type": "data_source_id",
        "id": data_source_id,
        "database_id": database_id,
        "schema": data_source.get("properties") or {},
    }


def _resolve_parent(api_key: str) -> dict | None:
    parent_type, parent_id = _get_preferred_notion_parent()
    if parent_type == "data_source_id" and parent_id:
        try:
            data_source = _request("GET", f"{NOTION_API_BASE}/data_sources/{parent_id}", api_key)
            return {"type": "data_source_id", "id": parent_id, "schema": data_source.get("properties") or {}}
        except RuntimeError as exc:
            if "404" not in str(exc):
                raise
            return _resolve_data_source_from_database(api_key, parent_id)

    if parent_type == "database_id" and parent_id:
        return _resolve_data_source_from_database(api_key, parent_id)

    return None


def _retrieve_schema(api_key: str, parent: dict) -> dict[str, dict]:
    return parent.get("schema") or {}


def _find_property_name(schema: dict[str, dict], configured_name: str) -> str:
    if not configured_name:
        return ""
    if configured_name in schema:
        return configured_name

    lowered = configured_name.strip().lower()
    for name in schema:
        if name.strip().lower() == lowered:
            return name
    return ""


def _is_web_url(value: str) -> bool:
    lowered = str(value or "").strip().lower()
    return lowered.startswith("http://") or lowered.startswith("https://")


def _build_properties(row: dict, schema: dict[str, dict]) -> dict:
    title_property = _find_property_name(schema, os.getenv("NOTION_TITLE_PROPERTY", "Name"))
    if not title_property:
        raise RuntimeError("Notion 데이터베이스에서 title 속성을 찾지 못했습니다. NOTION_TITLE_PROPERTY 값을 확인하세요.")

    title = _clean_text(row.get("title") or row.get("keyword") or "Untitled")
    properties = {title_property: {"title": _rich_text(title)}}

    optional_mappings = [
        ("NOTION_STATUS_PROPERTY", os.getenv("NOTION_STATUS_VALUE", "").strip() or row.get("notion_status") or "drafted"),
        ("NOTION_PLATFORM_PROPERTY", row.get("platform", "")),
        ("NOTION_KEYWORD_PROPERTY", row.get("keyword", "")),
        ("NOTION_OUTPUT_PATH_PROPERTY", row.get("output_path", "")),
        ("NOTION_CREATED_AT_PROPERTY", row.get("created_at", "")),
        ("NOTION_SEARCH_INTENT_PROPERTY", row.get("search_intent", "")),
    ]

    for env_name, raw_value in optional_mappings:
        property_name = _find_property_name(schema, os.getenv(env_name, ""))
        if not property_name:
            continue

        schema_type = schema[property_name].get("type")
        value = _clean_text(raw_value)
        if not value:
            continue

        if schema_type == "status":
            properties[property_name] = {"status": {"name": value}}
        elif schema_type == "select":
            properties[property_name] = {"select": {"name": value}}
        elif schema_type == "multi_select":
            properties[property_name] = {
                "multi_select": [{"name": part.strip()} for part in value.split(",") if part.strip()]
            }
        elif schema_type == "title":
            properties[property_name] = {"title": _rich_text(value)}
        elif schema_type == "date":
            properties[property_name] = {"date": {"start": value}}
        elif schema_type == "url":
            if _is_web_url(value):
                properties[property_name] = {"url": value}
        elif schema_type == "checkbox":
            properties[property_name] = {"checkbox": value.lower() in {"1", "true", "yes", "y", "on"}}
        else:
            properties[property_name] = {"rich_text": _rich_text(value)}

    for env_name, default_label in [
        ("NOTION_READY_PROPERTY", "Ready"),
        ("NOTION_REVIEWED_PROPERTY", "Reviewed"),
        ("NOTION_UPLOADED_PROPERTY", "Uploaded"),
    ]:
        property_name = _find_property_name(schema, os.getenv(env_name, default_label))
        if property_name and schema[property_name].get("type") == "checkbox":
            properties[property_name] = {"checkbox": False}

    return properties


def _build_content_blocks(row: dict) -> list[dict]:
    title = _clean_text(row.get("title") or row.get("keyword"))
    article_text = _clean_text(row.get("article_text", ""))
    blocks = _build_management_blocks()
    if blocks:
        blocks.append(_heading_block(2, "본문"))
    blocks.extend(_article_to_blocks(article_text, title))
    return blocks or [_paragraph_block(article_text or "(빈 본문)")]


def _create_page(api_key: str, parent: dict, properties: dict, content_blocks: list[dict]) -> dict:
    first_batch = content_blocks[:80]
    payload = {
        "parent": {parent["type"]: parent["id"]},
        "properties": properties,
    }
    if first_batch:
        payload["children"] = first_batch

    page = _request("POST", f"{NOTION_API_BASE}/pages", api_key, json=payload)
    remaining = content_blocks[80:]
    page_id = page.get("id", "")

    while remaining and page_id:
        batch = remaining[:80]
        remaining = remaining[80:]
        _request("PATCH", f"{NOTION_API_BASE}/blocks/{page_id}/children", api_key, json={"children": batch})

    return page


def fetch_all_database_page_ids() -> list[str]:
    """NOTION_DATABASE_ID에 있는 모든 페이지 ID를 직접 조회합니다.
    실패 시 RuntimeError를 발생시킵니다 (호출자가 처리)."""
    api_key = os.getenv("NOTION_API_KEY", "").strip()
    parent_type, parent_id = _get_preferred_notion_parent()
    if not api_key:
        raise RuntimeError("NOTION_API_KEY가 설정되지 않았습니다.")
    if not parent_id:
        raise RuntimeError("NOTION_DATA_SOURCE_ID 또는 NOTION_DATABASE_ID가 설정되지 않았습니다.")

    page_ids: list[str] = []
    payload: dict = {"page_size": 100}

    while True:
        if parent_type == "database_id":
            query_url = f"{NOTION_API_BASE}/databases/{parent_id}/query"
        else:
            query_url = f"{NOTION_API_BASE}/data_sources/{parent_id}/query"

        try:
            result = _request(
                "POST",
                query_url,
                api_key,
                json=payload,
            )
        except RuntimeError as exc:
            if parent_type != "data_source_id" or "404" not in str(exc):
                raise
            parent_type = "database_id"
            result = _request(
                "POST",
                f"{NOTION_API_BASE}/databases/{parent_id}/query",
                api_key,
                json=payload,
            )
        for page in result.get("results", []):
            pid = str(page.get("id", "")).strip()
            if pid:
                page_ids.append(pid)

        if not result.get("has_more"):
            break
        payload["start_cursor"] = result.get("next_cursor")

    print(f"[notion] fetched {len(page_ids)} page IDs from database")
    return page_ids


def fetch_all_database_page_ids() -> list[str]:
    """Resolve the configured Notion parent to a data source and fetch page IDs from it."""
    api_key = os.getenv("NOTION_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("NOTION_API_KEY가 설정되지 않았습니다.")

    parent = _resolve_parent(api_key)
    if not parent:
        raise RuntimeError("NOTION_DATA_SOURCE_ID 또는 NOTION_DATABASE_ID가 설정되지 않았습니다.")

    parent_id = str(parent.get("id", "")).strip()
    page_ids: list[str] = []
    payload: dict = {"page_size": 100}

    while True:
        result = _request(
            "POST",
            f"{NOTION_API_BASE}/data_sources/{parent_id}/query",
            api_key,
            json=payload,
        )
        for page in result.get("results", []):
            pid = str(page.get("id", "")).strip()
            if pid:
                page_ids.append(pid)

        if not result.get("has_more"):
            break
        payload["start_cursor"] = result.get("next_cursor")

    print(f"[notion] fetched {len(page_ids)} page IDs from database")
    return page_ids


def archive_notion_pages(page_ids: list[str]) -> list[dict]:
    api_key = os.getenv("NOTION_API_KEY", "").strip()
    results = []
    for page_id in page_ids:
        pid = str(page_id or "").strip()
        if not pid:
            continue
        if not api_key:
            results.append({"page_id": pid, "status": "disabled"})
            continue
        try:
            _request(
                "PATCH",
                f"{NOTION_API_BASE}/pages/{pid}",
                api_key,
                json={"in_trash": True},
            )
            results.append({"page_id": pid, "status": "archived"})
            print(f"[notion] deleted: {pid}")
        except Exception as exc:
            results.append({"page_id": pid, "status": "failed", "error": str(exc)})
            print(f"[notion] delete failed: {pid} -> {exc}")
    return results


def sync_articles_to_notion(rows: list[dict]) -> list[dict]:
    api_key = os.getenv("NOTION_API_KEY", "").strip()
    if not rows:
        return []

    if not api_key:
        return [
            {"keyword": _clean_text(row.get("keyword", "")), "status": "disabled", "page_id": "", "page_url": ""}
            for row in rows
        ]

    parent = _resolve_parent(api_key)
    if not parent:
        return [
            {"keyword": _clean_text(row.get("keyword", "")), "status": "disabled", "page_id": "", "page_url": ""}
            for row in rows
        ]

    schema = _retrieve_schema(api_key, parent)
    results = []

    for row in rows:
        keyword = _clean_text(row.get("keyword", ""))
        try:
            properties = _build_properties(row, schema)
            content_blocks = _build_content_blocks(row)
            page = _create_page(api_key, parent, properties, content_blocks)
            results.append(
                {
                    "keyword": keyword,
                    "status": "synced",
                    "page_id": page.get("id", ""),
                    "page_url": page.get("url", ""),
                    "synced_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                }
            )
            print(f"[notion] synced: {keyword} -> {page.get('url', '')}")
        except Exception as exc:
            results.append(
                {
                    "keyword": keyword,
                    "status": "failed",
                    "page_id": "",
                    "page_url": "",
                    "synced_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "error": str(exc),
                }
            )
            print(f"[notion] failed: {keyword} -> {exc}")

    return results
