import os
import re
from datetime import datetime
from urllib.parse import unquote

import requests

try:
    from scripts.notion_config import build_notion_env, load_notion_config
except ImportError:
    from notion_config import build_notion_env, load_notion_config

NOTION_API_BASE = "https://api.notion.com/v1"
DEFAULT_CHECKLIST_ITEMS = ["검수 필요", "이미지 추가", "블로그 업로드", "발행 완료"]

def _env(name: str, default: str = "") -> str:
    value = os.getenv(name, "").strip()
    if value:
        return value
    return str(build_notion_env(load_notion_config()).get(name, default)).strip() or default

def _get_bool_env(name: str, default: bool) -> bool:
    raw = _env(name, "").lower()
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


def _chunk_text(text: str, limit: int = 1900) -> list[str]:
    normalized = str(text or "")
    if not normalized:
        return []
    chunks, current = [], ""
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
    return [{"type": "text", "text": {"content": chunk}} for chunk in _chunk_text(text)] or [{"type": "text", "text": {"content": ""}}]

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
    return {"object": "block", "type": "code", "code": {"rich_text": _rich_text(text), "language": language}}

def _parse_checklist_items(raw: str) -> list[str]:
    return [item.strip() for item in str(raw or "").split("|") if item.strip()]

def _build_management_blocks() -> list[dict]:
    if not _get_bool_env("NOTION_INCLUDE_MANAGEMENT_CHECKLIST", True):
        return []
    items = _parse_checklist_items(_env("NOTION_CHECKLIST_ITEMS", "")) or DEFAULT_CHECKLIST_ITEMS[:]
    return [_heading_block(2, "관리 체크리스트"), *[_list_block("to_do", item, checked=False) for item in items]]

def _article_to_blocks(article_text: str, title: str) -> list[dict]:
    lines = _clean_text(article_text).split("\n")
    blocks, buffer, code_lines = [], [], []
    in_code = False
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
            blocks.append(_list_block("to_do", todo_match.group(2).strip(), checked=todo_match.group(1).lower() == "x"))
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
    return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json", "Notion-Version": _env("NOTION_VERSION", "2026-03-11")}

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


def _resolve_parent(api_key: str) -> dict | None:
    parent_type = _env("NOTION_PARENT_TYPE", "")
    parent_id = _env("NOTION_PARENT_ID", "")
    data_source_id = _env("NOTION_DATA_SOURCE_ID", "")
    database_id = _env("NOTION_DATABASE_ID", "")
    if data_source_id:
        return {"type": "data_source_id", "id": data_source_id, "schema_id": data_source_id}
    if parent_type == "data_source_id" and parent_id:
        return {"type": "data_source_id", "id": parent_id, "schema_id": parent_id}
    if database_id:
        database = _request("GET", f"{NOTION_API_BASE}/databases/{database_id}", api_key)
        data_sources = database.get("data_sources") or []
        schema_id = data_sources[0].get("id") if data_sources else database_id
        return {"type": "database_id", "id": database_id, "schema_id": schema_id}
    if parent_type == "database_id" and parent_id:
        database = _request("GET", f"{NOTION_API_BASE}/databases/{parent_id}", api_key)
        data_sources = database.get("data_sources") or []
        schema_id = data_sources[0].get("id") if data_sources else parent_id
        return {"type": "database_id", "id": parent_id, "schema_id": schema_id}
    return None

def _retrieve_schema(api_key: str, parent: dict) -> dict[str, dict]:

    schema_id = parent.get("schema_id", "")
    if not schema_id:
        return {}
    return _request("GET", f"{NOTION_API_BASE}/data_sources/{schema_id}", api_key).get("properties") or {}

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
    title_property = _find_property_name(schema, _env("NOTION_TITLE_PROPERTY", "Name"))
    if not title_property:
        raise RuntimeError("Notion 데이터베이스에서 title 속성을 찾지 못했습니다. NOTION_TITLE_PROPERTY 값을 확인해 주세요.")
    title = _clean_text(row.get("title") or row.get("keyword") or "Untitled")
    properties = {title_property: {"title": _rich_text(title)}}
    optional_mappings = [("NOTION_STATUS_PROPERTY", _env("NOTION_STATUS_VALUE", "") or row.get("notion_status") or "drafted"), ("NOTION_PLATFORM_PROPERTY", row.get("platform", "")), ("NOTION_KEYWORD_PROPERTY", row.get("keyword", "")), ("NOTION_OUTPUT_PATH_PROPERTY", row.get("output_path", "")), ("NOTION_CREATED_AT_PROPERTY", row.get("created_at", "")), ("NOTION_SEARCH_INTENT_PROPERTY", row.get("search_intent", ""))]
    for env_name, raw_value in optional_mappings:
        property_name = _find_property_name(schema, _env(env_name, ""))
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
            properties[property_name] = {"multi_select": [{"name": part.strip()} for part in value.split(",") if part.strip()]}
        elif schema_type == "title":
            properties[property_name] = {"title": _rich_text(value)}
        elif schema_type == "date":
            properties[property_name] = {"date": {"start": value}}
        elif schema_type == "url" and _is_web_url(value):
            properties[property_name] = {"url": value}
        elif schema_type == "checkbox":
            properties[property_name] = {"checkbox": value.lower() in {"1", "true", "yes", "y", "on"}}
        else:
            properties[property_name] = {"rich_text": _rich_text(value)}
    for env_name, default_label in [("NOTION_READY_PROPERTY", "Ready"), ("NOTION_REVIEWED_PROPERTY", "Reviewed"), ("NOTION_UPLOADED_PROPERTY", "Uploaded")]:
        property_name = _find_property_name(schema, _env(env_name, default_label))
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
    payload = {"parent": {parent["type"]: parent["id"]}, "properties": properties}
    first_batch = content_blocks[:80]
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



def archive_notion_pages(page_ids: list[str]) -> dict[str, int]:
    api_key = _env("NOTION_API_KEY", "")
    normalized_ids = [str(page_id).strip() for page_id in page_ids if str(page_id).strip()]
    if not normalized_ids:
        return {"archived": 0, "failed": 0, "disabled": 0}
    if not api_key:
        return {"archived": 0, "failed": 0, "disabled": len(normalized_ids)}

    counts = {"archived": 0, "failed": 0, "disabled": 0}
    for page_id in normalized_ids:
        try:
            try:
                _request("PATCH", f"{NOTION_API_BASE}/pages/{page_id}", api_key, json={"in_trash": True})
            except Exception:
                _request("PATCH", f"{NOTION_API_BASE}/pages/{page_id}", api_key, json={"archived": True})
            counts["archived"] += 1
            print(f"[notion] archived: {page_id}")
        except Exception as exc:
            counts["failed"] += 1
            print(f"[notion] archive failed: {page_id} -> {exc}")
    return counts

def sync_articles_to_notion(rows: list[dict]) -> list[dict]:
    api_key = _env("NOTION_API_KEY", "")
    if not rows:
        return []
    if not api_key:
        return [{"keyword": _clean_text(row.get("keyword", "")), "status": "disabled", "page_id": "", "page_url": ""} for row in rows]
    parent = _resolve_parent(api_key)
    if not parent:
        return [{"keyword": _clean_text(row.get("keyword", "")), "status": "disabled", "page_id": "", "page_url": ""} for row in rows]
    schema = _retrieve_schema(api_key, parent)
    results = []
    for row in rows:
        keyword = _clean_text(row.get("keyword", ""))
        try:
            page = _create_page(api_key, parent, _build_properties(row, schema), _build_content_blocks(row))
            results.append({"keyword": keyword, "status": "synced", "page_id": page.get("id", ""), "page_url": page.get("url", ""), "synced_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
            print(f"[notion] synced: {keyword} -> {page.get('url', '')}")
        except Exception as exc:
            results.append({"keyword": keyword, "status": "failed", "page_id": "", "page_url": "", "synced_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "error": str(exc)})
            print(f"[notion] failed: {keyword} -> {exc}")
    return results
