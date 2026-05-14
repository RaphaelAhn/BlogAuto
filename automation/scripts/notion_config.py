import json
from pathlib import Path

try:
    from scripts.paths import DATA_DIR
except ImportError:
    from paths import DATA_DIR

NOTION_CONFIG_PATH = DATA_DIR / "notion_config.json"
DEFAULT_NOTION_CONFIG = {
    "NOTION_API_KEY": "",
    "NOTION_VERSION": "2026-03-11",
    "NOTION_TARGET_KIND": "data_source_id",
    "NOTION_TARGET_ID": "",
    "NOTION_TITLE_PROPERTY": "Name",
    "NOTION_STATUS_PROPERTY": "",
    "NOTION_STATUS_VALUE": "drafted",
    "NOTION_PLATFORM_PROPERTY": "",
    "NOTION_KEYWORD_PROPERTY": "",
    "NOTION_OUTPUT_PATH_PROPERTY": "",
    "NOTION_CREATED_AT_PROPERTY": "",
    "NOTION_SEARCH_INTENT_PROPERTY": "",
    "NOTION_READY_PROPERTY": "Ready",
    "NOTION_REVIEWED_PROPERTY": "Reviewed",
    "NOTION_UPLOADED_PROPERTY": "Uploaded",
    "NOTION_INCLUDE_MANAGEMENT_CHECKLIST": True,
    "NOTION_CHECKLIST_ITEMS": "검수 필요|이미지 추가|블로그 업로드|발행 완료",
}

def load_notion_config() -> dict[str, object]:
    config = DEFAULT_NOTION_CONFIG.copy()
    if not NOTION_CONFIG_PATH.exists():
        return config
    try:
        payload = json.loads(NOTION_CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return config
    if not isinstance(payload, dict):
        return config
    for key in DEFAULT_NOTION_CONFIG:
        if key in payload:
            config[key] = payload[key]
    return config

def save_notion_config(config: dict[str, object]) -> None:
    payload = DEFAULT_NOTION_CONFIG.copy()
    for key in DEFAULT_NOTION_CONFIG:
        if key in config:
            payload[key] = config[key]
    NOTION_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    NOTION_CONFIG_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

def is_notion_configured(config: dict[str, object]) -> bool:
    return bool(str(config.get("NOTION_API_KEY", "")).strip() and str(config.get("NOTION_TARGET_ID", "")).strip())

def build_notion_env(config: dict[str, object]) -> dict[str, str]:
    env = {
        "NOTION_API_KEY": str(config.get("NOTION_API_KEY", "")).strip(),
        "NOTION_VERSION": str(config.get("NOTION_VERSION", DEFAULT_NOTION_CONFIG["NOTION_VERSION"])).strip() or DEFAULT_NOTION_CONFIG["NOTION_VERSION"],
        "NOTION_TITLE_PROPERTY": str(config.get("NOTION_TITLE_PROPERTY", "Name")).strip() or "Name",
        "NOTION_STATUS_PROPERTY": str(config.get("NOTION_STATUS_PROPERTY", "")).strip(),
        "NOTION_STATUS_VALUE": str(config.get("NOTION_STATUS_VALUE", "drafted")).strip() or "drafted",
        "NOTION_PLATFORM_PROPERTY": str(config.get("NOTION_PLATFORM_PROPERTY", "")).strip(),
        "NOTION_KEYWORD_PROPERTY": str(config.get("NOTION_KEYWORD_PROPERTY", "")).strip(),
        "NOTION_OUTPUT_PATH_PROPERTY": str(config.get("NOTION_OUTPUT_PATH_PROPERTY", "")).strip(),
        "NOTION_CREATED_AT_PROPERTY": str(config.get("NOTION_CREATED_AT_PROPERTY", "")).strip(),
        "NOTION_SEARCH_INTENT_PROPERTY": str(config.get("NOTION_SEARCH_INTENT_PROPERTY", "")).strip(),
        "NOTION_READY_PROPERTY": str(config.get("NOTION_READY_PROPERTY", "Ready")).strip() or "Ready",
        "NOTION_REVIEWED_PROPERTY": str(config.get("NOTION_REVIEWED_PROPERTY", "Reviewed")).strip() or "Reviewed",
        "NOTION_UPLOADED_PROPERTY": str(config.get("NOTION_UPLOADED_PROPERTY", "Uploaded")).strip() or "Uploaded",
        "NOTION_INCLUDE_MANAGEMENT_CHECKLIST": "true" if bool(config.get("NOTION_INCLUDE_MANAGEMENT_CHECKLIST", True)) else "false",
        "NOTION_CHECKLIST_ITEMS": str(config.get("NOTION_CHECKLIST_ITEMS", "")).strip(),
        "NOTION_DATA_SOURCE_ID": "",
        "NOTION_DATABASE_ID": "",
    }
    target_kind = str(config.get("NOTION_TARGET_KIND", "data_source_id")).strip()
    target_id = str(config.get("NOTION_TARGET_ID", "")).strip()
    if target_kind == "database_id":
        env["NOTION_DATABASE_ID"] = target_id
    else:
        env["NOTION_DATA_SOURCE_ID"] = target_id
    return env
