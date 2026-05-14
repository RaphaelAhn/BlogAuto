import re
from datetime import datetime

import pandas as pd

try:
    from scripts.paths import DATA_DIR, OUTPUT_DIR
except ImportError:
    from paths import DATA_DIR, OUTPUT_DIR

PREVIOUS_POSTS_PATH = DATA_DIR / "previous_posts.csv"
QA_USED_PATH = DATA_DIR / "qa_used.csv"
TOPIC_USED_PATH = DATA_DIR / "topic_used.csv"
WRITING_QUEUE_PATH = DATA_DIR / "writing_queue.csv"

PREVIOUS_POSTS_COLUMNS = [
    "platform",
    "title",
    "url",
    "content",
    "qa_questions",
    "keywords",
    "intent_core",
    "intent_detail",
    "language",
    "created_at",
]

TOPIC_USED_COLUMNS = [
    "platform",
    "title",
    "keyword",
    "tag_keywords",
    "meta_description",
    "search_intent",
    "topic_type",
    "intent_core",
    "intent_detail",
    "status",
    "created_at",
    "output_path",
    "structure_slot",
    "lead_slot",
    "rhythm_slot",
    "style_slot",
    "ending_slot",
    "topic_profile",
    "similarity_score",
    "structural_score",
    "total_penalty",
    "decision",
    "decision_reason",
    "notion_page_id",
    "notion_page_url",
    "notion_sync_status",
    "notion_synced_at",
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


def load_existing_texts(include_writing_queue=True):
    previous_df = read_csv_safe(PREVIOUS_POSTS_PATH)
    qa_df = read_csv_safe(QA_USED_PATH)
    topic_used_df = read_csv_safe(TOPIC_USED_PATH, TOPIC_USED_COLUMNS)
    writing_queue_df = read_csv_safe(WRITING_QUEUE_PATH)

    texts = []
    sources = [
        (previous_df, ["title", "intent_core", "intent_detail"]),
        (qa_df, ["question"]),
        (topic_used_df, ["title", "keyword", "intent_core", "intent_detail"]),
    ]
    if include_writing_queue:
        sources.append((writing_queue_df, ["title", "keyword"]))

    for df, columns in sources:
        if df.empty:
            continue
        for col in columns:
            if col in df.columns:
                texts.extend(df[col].dropna().astype(str).tolist())

    known_platforms = ["blogspot_kr", "blogspot_en", "naver", "tistory"]
    if OUTPUT_DIR.exists():
        for run_dir in OUTPUT_DIR.iterdir():
            if not run_dir.is_dir():
                continue
            for txt_file in run_dir.glob("*.txt"):
                stem = txt_file.stem
                without_num = stem.split("_", 1)[-1] if "_" in stem else stem
                title_part = without_num
                for platform in known_platforms:
                    if without_num.startswith(platform + "_"):
                        title_part = without_num[len(platform) + 1:]
                        break
                if title_part:
                    texts.append(title_part.replace("_", " "))

    return [x for x in texts if str(x).strip()]


def load_duplicate_candidates(include_writing_queue=True):
    previous_df = read_csv_safe(PREVIOUS_POSTS_PATH, PREVIOUS_POSTS_COLUMNS)
    topic_used_df = read_csv_safe(TOPIC_USED_PATH, TOPIC_USED_COLUMNS)
    writing_queue_df = read_csv_safe(WRITING_QUEUE_PATH)

    candidates = []

    def append_candidate(source, row):
        title = str(row.get("title", "")).strip()
        keyword = str(row.get("keyword", "")).strip()
        intent_core = str(row.get("intent_core", "")).strip()
        search_intent = str(row.get("search_intent", "")).strip()
        topic_type = str(row.get("topic_type", "")).strip()
        url = str(row.get("url", "")).strip()
        content = str(row.get("content", "")).strip()

        if not intent_core and keyword:
            intent_core = build_intent_core(keyword)
        elif not intent_core and title:
            intent_core = build_intent_core(title)

        if not any([title, keyword, intent_core, content]):
            return

        candidates.append({
            "source": source,
            "platform": str(row.get("platform", "")).strip(),
            "title": title,
            "keyword": keyword,
            "intent_core": intent_core,
            "intent_detail": str(row.get("intent_detail", "")).strip(),
            "search_intent": search_intent,
            "topic_type": topic_type,
            "url": url,
            "content": content,
            "normalized_keyword": normalize(keyword or title or intent_core),
        })

    if not previous_df.empty:
        for _, row in previous_df.iterrows():
            append_candidate("previous_posts", row)

    if not topic_used_df.empty:
        for _, row in topic_used_df.iterrows():
            append_candidate("topic_used", row)

    if include_writing_queue and not writing_queue_df.empty:
        for _, row in writing_queue_df.iterrows():
            append_candidate("writing_queue", row)

    return candidates


def append_previous_post_stub(rows):
    previous_df = read_csv_safe(PREVIOUS_POSTS_PATH, PREVIOUS_POSTS_COLUMNS)
    existing_urls = set()
    if not previous_df.empty and "url" in previous_df.columns:
        existing_urls = {str(url).strip() for url in previous_df["url"].dropna().astype(str).tolist() if str(url).strip()}

    new_rows = []
    for row in rows:
        title = str(row.get("title", "")).strip()
        url = str(row.get("url", "")).strip()
        if not title:
            continue
        keyword = str(row.get("keyword", "")).strip()
        search_intent = str(row.get("search_intent", "")).strip()
        platform = str(row.get("platform", "")).strip()
        intent_core = str(row.get("intent_core", build_intent_core(keyword or title))).strip()
        if not url:
            url = f"stub://{platform}/{intent_core or normalize(title)}"
        if url in existing_urls:
            continue
        new_rows.append({
            "platform": platform,
            "title": title,
            "url": url,
            "content": str(row.get("content", "")).strip(),
            "qa_questions": str(row.get("qa_questions", "")).strip(),
            "keywords": str(row.get("keywords", keyword)).strip(),
            "intent_core": intent_core,
            "intent_detail": str(row.get("intent_detail", build_intent_detail(keyword or title, search_intent))).strip(),
            "language": str(row.get("language", "")).strip(),
            "created_at": str(row.get("created_at", datetime.now().strftime("%Y-%m-%d"))).strip(),
        })
        existing_urls.add(url)

    if not new_rows:
        return 0

    new_df = pd.DataFrame(new_rows, columns=PREVIOUS_POSTS_COLUMNS)
    final_df = pd.concat([previous_df, new_df], ignore_index=True)
    if "url" in final_df.columns:
        final_df = final_df.drop_duplicates(subset=["platform", "url"], keep="last")
    tmp_path = PREVIOUS_POSTS_PATH.with_suffix(".tmp")
    try:
        final_df.to_csv(tmp_path, index=False, encoding="utf-8-sig")
        tmp_path.replace(PREVIOUS_POSTS_PATH)
    except Exception as e:
        print(f"[오류] previous_posts.csv 저장 실패: {e}")
        if tmp_path.exists():
            tmp_path.unlink()
        raise

    return len(new_rows)


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
        output_path = str(row.get("output_path", "")).strip()

        new_rows.append({
            "platform": platform,
            "title": title,
            "keyword": keyword,
            "search_intent": search_intent,
            "topic_type": str(row.get("topic_type", "")).strip(),
            "intent_core": build_intent_core(keyword),
            "intent_detail": build_intent_detail(keyword, search_intent),
            "status": status,
            "created_at": created_at,
            "output_path": output_path,
            "structure_slot": str(row.get("structure_slot", row.get("structure_variant", ""))).strip(),
            "lead_slot": str(row.get("lead_slot", "")).strip(),
            "rhythm_slot": str(row.get("rhythm_slot", "")).strip(),
            "style_slot": str(row.get("style_slot", "")).strip(),
            "ending_slot": str(row.get("ending_slot", "")).strip(),
            "topic_profile": str(row.get("topic_profile", "")).strip(),
            "similarity_score": row.get("similarity_score", ""),
            "structural_score": row.get("structural_score", ""),
            "total_penalty": row.get("total_penalty", ""),
            "decision": str(row.get("decision", status)).strip(),
            "decision_reason": str(row.get("decision_reason", "")).strip(),
            "notion_page_id": str(row.get("notion_page_id", "")).strip(),
            "notion_page_url": str(row.get("notion_page_url", "")).strip(),
            "notion_sync_status": str(row.get("notion_sync_status", "")).strip(),
            "notion_synced_at": str(row.get("notion_synced_at", "")).strip(),
        })
        existing_keys.add(keyword_norm)

    if not new_rows:
        return 0

    new_df = pd.DataFrame(new_rows, columns=TOPIC_USED_COLUMNS)
    final_df = pd.concat([topic_used_df, new_df], ignore_index=True)
    tmp_path = TOPIC_USED_PATH.with_suffix(".tmp")
    try:
        final_df.to_csv(tmp_path, index=False, encoding="utf-8-sig")
        tmp_path.replace(TOPIC_USED_PATH)
    except Exception as e:
        print(f"[오류] topic_used.csv 저장 실패: {e}")
        if tmp_path.exists():
            tmp_path.unlink()
        raise

    return len(new_rows)


def mark_as_published(keywords):
    topic_used_df = read_csv_safe(TOPIC_USED_PATH, TOPIC_USED_COLUMNS)
    if topic_used_df.empty or "keyword" not in topic_used_df.columns:
        return 0

    normalized_targets = {normalize(k) for k in keywords if k}
    mask = topic_used_df["keyword"].apply(lambda k: normalize(str(k)) in normalized_targets)
    count = int(mask.sum())
    if count == 0:
        return 0

    published_rows = []
    for _, row in topic_used_df.loc[mask].iterrows():
        published_rows.append({
            "platform": str(row.get("platform", "")).strip(),
            "title": str(row.get("title", "")).strip(),
            "keyword": str(row.get("keyword", "")).strip(),
            "search_intent": str(row.get("search_intent", "")).strip(),
            "intent_core": str(row.get("intent_core", "")).strip(),
            "intent_detail": str(row.get("intent_detail", "")).strip(),
            "created_at": str(row.get("created_at", "")).strip(),
        })

    append_previous_post_stub(published_rows)

    topic_used_df.loc[mask, "status"] = "used"
    tmp_path = TOPIC_USED_PATH.with_suffix(".tmp")
    try:
        topic_used_df.to_csv(tmp_path, index=False, encoding="utf-8-sig")
        tmp_path.replace(TOPIC_USED_PATH)
    except Exception as e:
        print(f"[오류] topic_used.csv 저장 실패: {e}")
        if tmp_path.exists():
            tmp_path.unlink()
        raise

    return count


def reset_publication_state(clear_notion_fields=False):
    topic_used_df = read_csv_safe(TOPIC_USED_PATH, TOPIC_USED_COLUMNS)
    if topic_used_df.empty:
        return 0

    topic_used_df = topic_used_df.copy()
    changed_mask = pd.Series(False, index=topic_used_df.index)

    if "status" in topic_used_df.columns:
        status_mask = topic_used_df["status"].fillna("").astype(str) != "drafted"
        changed_mask = changed_mask | status_mask
        topic_used_df.loc[:, "status"] = "drafted"

    if clear_notion_fields:
        notion_columns = ["notion_page_id", "notion_page_url", "notion_sync_status", "notion_synced_at"]
        for column in notion_columns:
            if column not in topic_used_df.columns:
                topic_used_df[column] = ""
        has_notion_data = topic_used_df[notion_columns].fillna("").astype(str).apply(lambda col: col.str.strip()).ne("").any(axis=1)
        changed_mask = changed_mask | has_notion_data
        for column in notion_columns:
            topic_used_df.loc[:, column] = ""

    tmp_path = TOPIC_USED_PATH.with_suffix(".tmp")
    try:
        topic_used_df.to_csv(tmp_path, index=False, encoding="utf-8-sig")
        tmp_path.replace(TOPIC_USED_PATH)
    except Exception as e:
        print(f"[오류] topic_used.csv 저장 실패: {e}")
        if tmp_path.exists():
            tmp_path.unlink()
        raise

    return int(changed_mask.sum())


def clear_generated_article_state():
    result = {"topic_used": 0, "writing_queue": 0}

    topic_used_df = read_csv_safe(TOPIC_USED_PATH, TOPIC_USED_COLUMNS)
    result["topic_used"] = len(topic_used_df)
    topic_tmp_path = TOPIC_USED_PATH.with_suffix(".tmp")
    pd.DataFrame(columns=TOPIC_USED_COLUMNS).to_csv(topic_tmp_path, index=False, encoding="utf-8-sig")
    topic_tmp_path.replace(TOPIC_USED_PATH)

    writing_queue_df = read_csv_safe(WRITING_QUEUE_PATH)
    result["writing_queue"] = len(writing_queue_df)
    if WRITING_QUEUE_PATH.exists():
        queue_tmp_path = WRITING_QUEUE_PATH.with_suffix(".tmp")
        pd.DataFrame(columns=list(writing_queue_df.columns)).to_csv(queue_tmp_path, index=False, encoding="utf-8-sig")
        queue_tmp_path.replace(WRITING_QUEUE_PATH)

    return result
