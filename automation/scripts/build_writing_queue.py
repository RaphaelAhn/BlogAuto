import re
from datetime import datetime
from pathlib import Path
import pandas as pd

from topic_registry import load_existing_texts, read_csv_safe

BASE_DIR = Path(__file__).resolve().parent.parent

TOP10_PATH = BASE_DIR / "data" / "topic_top10.csv"
APPROVED_PATH = BASE_DIR / "data" / "topic_approved.csv"
QUEUE_PATH = BASE_DIR / "data" / "writing_queue.csv"

QUEUE_COLUMNS = [
    "topic_id",
    "platform",
    "category",
    "keyword",
    "title",
    "search_intent",
    "priority",
    "source",
    "status",
    "created_at",
]

# 🔥 플랫폼 최대 개수 제한
PLATFORM_LIMIT = {
    "naver": 4,
    "tistory": 3,
    "blogspot_kr": 2,
    "blogspot_en": 2,
}

def normalize(text):
    text = str(text).lower()
    text = re.sub(r"\s+", "", text)
    return text.strip()


def token_set(text):
    text = re.sub(r"[^0-9a-zA-Z가-힣\s]", " ", str(text))
    return set([w for w in text.split() if len(w) >= 2])


def is_semantic_duplicate(keyword, existing):
    k_tokens = token_set(keyword)

    for old in existing:
        old_tokens = token_set(old)

        if len(k_tokens & old_tokens) >= 2:
            return True

    return False


def make_topic_id(platform, keyword, index):
    today = datetime.now().strftime("%Y%m%d")
    safe_keyword = normalize(keyword)[:20]
    return f"{today}_{platform}_{index:03d}_{safe_keyword}"


def load_topics():
    top10_df = read_csv_safe(TOP10_PATH)

    if not top10_df.empty:
        print("TOP10 기준 사용")
        return top10_df

    approved_df = read_csv_safe(APPROVED_PATH)

    if not approved_df.empty:
        print("Approved 기준 사용")
        return approved_df.head(12)

    return pd.DataFrame()


# 🔥 플랫폼 점수 기반 배정
def platform_score(row):
    keyword = str(row.get("keyword", ""))
    intent = str(row.get("search_intent", ""))
    source = str(row.get("source", ""))

    scores = {
        "naver": 0,
        "tistory": 0,
        "blogspot_kr": 0,
        "blogspot_en": 0,
    }

    # 네이버
    if source == "naver_suggest":
        scores["naver"] += 3
    if intent == "problem_solving":
        scores["naver"] += 3
    if any(w in keyword for w in ["오류", "안됨", "해결", "초보"]):
        scores["naver"] += 2

    # 티스토리
    if intent in ["practical", "comparison"]:
        scores["tistory"] += 3
    if any(w in keyword for w in ["자동화", "업무", "보고서"]):
        scores["tistory"] += 2

    # 블로그스팟 KR
    if intent == "how_to":
        scores["blogspot_kr"] += 2

    # 블로그스팟 EN
    if re.search(r"[A-Za-z]", keyword):
        scores["blogspot_en"] += 3

    return max(scores, key=scores.get)


def build_queue():
    topic_df = load_topics()

    if topic_df.empty:
        print("주제 없음")
        return pd.DataFrame(columns=QUEUE_COLUMNS)

    old_df = read_csv_safe(QUEUE_PATH, QUEUE_COLUMNS)
    blocked_texts = load_existing_texts()

    existing_keywords = set(old_df["keyword"].astype(str)) if not old_df.empty else set()

    rows = []
    platform_count = {k: 0 for k in PLATFORM_LIMIT}

    existing_all = list(existing_keywords) + blocked_texts

    for _, row in topic_df.iterrows():
        keyword = str(row.get("keyword", ""))

        if not keyword:
            continue

        # 🔥 의미 중복 제거
        if is_semantic_duplicate(keyword, existing_all):
            continue

        platform = platform_score(row)

        # 🔥 플랫폼 개수 제한
        if platform_count[platform] >= PLATFORM_LIMIT[platform]:
            continue

        topic_id = make_topic_id(platform, keyword, len(rows) + 1)

        rows.append({
            "topic_id": topic_id,
            "platform": platform,
            "category": row.get("category", ""),
            "keyword": keyword,
            "title": row.get("title", keyword),
            "search_intent": row.get("search_intent", ""),
            "priority": row.get("final_score", ""),
            "source": row.get("source", ""),
            "status": "pending",
            "created_at": datetime.now().strftime("%Y-%m-%d"),
        })

        platform_count[platform] += 1
        existing_all.append(keyword)

    new_df = pd.DataFrame(rows, columns=QUEUE_COLUMNS)

    final_df = pd.concat([old_df, new_df], ignore_index=True)
    final_df = final_df.drop_duplicates(subset=["keyword", "platform"])

    return final_df


def main():
    print("작업 큐 생성 시작 (고급 버전)")

    df = build_queue()

    if df.empty:
        print("생성된 작업 없음")
        return

    df.to_csv(QUEUE_PATH, index=False, encoding="utf-8-sig")

    print("\n완료")
    print(df["platform"].value_counts())


if __name__ == "__main__":
    main()
