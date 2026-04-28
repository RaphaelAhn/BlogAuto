import re
from datetime import datetime
from pathlib import Path

import pandas as pd


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"

PREVIOUS_POSTS_PATH = DATA_DIR / "previous_posts.csv"
QA_USED_PATH = DATA_DIR / "qa_used.csv"
TOPIC_USED_PATH = DATA_DIR / "topic_used.csv"
WRITING_QUEUE_PATH = DATA_DIR / "writing_queue.csv"

TOPIC_USED_COLUMNS = [
    "platform",
    "title",
    "keyword",
    "search_intent",
    "intent_core",
    "intent_detail",
    "status",
    "created_at",
]


def read_csv_safe(path, columns=None):
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame(columns=columns or [])

    try:
        return pd.read_csv(path, encoding="utf-8-sig")
    except pd.errors.EmptyDataError:
        return pd.DataFrame(columns=columns or [])
    except Exception:
        return pd.DataFrame(columns=columns or [])


def normalize(text):
    text = str(text).lower()
    text = re.sub(r"\s+", "", text)
    text = text.replace("-", "").replace("_", "")
    text = text.replace("[", "").replace("]", "")
    return text.strip()


def build_intent_core(keyword):
    text = str(keyword).strip().lower()
    text = re.sub(r"[^0-9a-zA-Z가-힣]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text


def build_intent_detail(keyword, search_intent):
    keyword = str(keyword).strip()
    search_intent = str(search_intent).strip()

    if keyword and search_intent:
        return f"{keyword}을/를 {search_intent} 목적으로 쉽게 이해하고 활용"

    if keyword:
        return f"{keyword}을/를 쉽게 이해하고 활용"

    return ""


def load_existing_texts():
    previous_df = read_csv_safe(PREVIOUS_POSTS_PATH)
    qa_df = read_csv_safe(QA_USED_PATH)
    topic_used_df = read_csv_safe(TOPIC_USED_PATH, TOPIC_USED_COLUMNS)
    writing_queue_df = read_csv_safe(WRITING_QUEUE_PATH)

    texts = []

    for df, columns in [
        (previous_df, ["title", "intent_core", "intent_detail"]),
        (qa_df, ["question"]),
        (topic_used_df, ["title", "keyword", "intent_core", "intent_detail"]),
        (writing_queue_df, ["title", "keyword"]),
    ]:
        if df.empty:
            continue

        for col in columns:
            if col in df.columns:
                texts.extend(df[col].dropna().astype(str).tolist())

    return [normalize(x) for x in texts if str(x).strip()]


def append_topic_used(rows, default_status="drafted"):
    topic_used_df = read_csv_safe(TOPIC_USED_PATH, TOPIC_USED_COLUMNS)
    existing_keys = set()

    if not topic_used_df.empty and "keyword" in topic_used_df.columns:
        existing_keys = {
            normalize(keyword)
            for keyword in topic_used_df["keyword"].dropna().astype(str).tolist()
            if normalize(keyword)
        }

    new_rows = []

    for row in rows:
        keyword = str(row.get("keyword", "")).strip()

        if not keyword:
            continue

        keyword_norm = normalize(keyword)

        if not keyword_norm or keyword_norm in existing_keys:
            continue

        platform = str(row.get("platform", "")).strip()
        title = str(row.get("title", keyword)).strip() or keyword
        search_intent = str(row.get("search_intent", "")).strip()
        status = str(row.get("status", default_status)).strip() or default_status
        created_at = str(row.get("created_at", "")).strip() or datetime.now().strftime("%Y-%m-%d")

        new_rows.append({
            "platform": platform,
            "title": title,
            "keyword": keyword,
            "search_intent": search_intent,
            "intent_core": build_intent_core(keyword),
            "intent_detail": build_intent_detail(keyword, search_intent),
            "status": status,
            "created_at": created_at,
        })
        existing_keys.add(keyword_norm)

    if not new_rows:
        return 0

    new_df = pd.DataFrame(new_rows, columns=TOPIC_USED_COLUMNS)
    final_df = pd.concat([topic_used_df, new_df], ignore_index=True)
    final_df.to_csv(TOPIC_USED_PATH, index=False, encoding="utf-8-sig")
    return len(new_rows)
