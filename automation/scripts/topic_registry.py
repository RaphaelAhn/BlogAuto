import re
from datetime import datetime

import pandas as pd

from paths import DATA_DIR, OUTPUT_DIR

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

    # output 폴더의 생성된 txt 파일 제목도 차단 목록에 포함
    # topic_used.csv 업데이트 여부와 무관하게 실제 생성 파일 기준으로 차단
    _KNOWN_PLATFORMS = ["blogspot_kr", "blogspot_en", "naver", "tistory"]
    if OUTPUT_DIR.exists():
        for run_dir in OUTPUT_DIR.iterdir():
            if not run_dir.is_dir():
                continue
            for txt_file in run_dir.glob("*.txt"):
                # 파일명 형식: {num}_{platform}_{safe_title}.txt
                # blogspot_kr / blogspot_en 처럼 플랫폼명에 _ 가 포함되므로
                # split("_", 2) 대신 알려진 플랫폼명을 직접 매칭해 제목 추출
                stem = txt_file.stem
                without_num = stem.split("_", 1)[-1] if "_" in stem else stem
                title_part = without_num
                for platform in _KNOWN_PLATFORMS:
                    if without_num.startswith(platform + "_"):
                        title_part = without_num[len(platform) + 1:]
                        break
                if title_part:
                    texts.append(title_part.replace("_", " "))

    # 원본 텍스트를 반환 (정규화 제거)
    # is_semantic_duplicate()가 공백 기준 토큰 분리를 사용하므로
    # 정규화(공백 제거)된 문자열을 넘기면 토큰 매칭이 작동하지 않음
    return [x for x in texts if str(x).strip()]


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
