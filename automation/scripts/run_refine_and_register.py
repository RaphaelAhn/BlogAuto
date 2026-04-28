from pathlib import Path

import pandas as pd

import refine_drafts_ai
from topic_registry import append_topic_used


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
TOP10_PATH = DATA_DIR / "topic_top10.csv"


def main():
    refine_drafts_ai.main()

    if not TOP10_PATH.exists():
        print("topic_top10.csv가 없어 topic_used.csv 등록을 건너뜁니다.")
        return

    top10_df = pd.read_csv(TOP10_PATH, encoding="utf-8-sig")

    if top10_df.empty:
        print("topic_top10.csv가 비어 있어 topic_used.csv 등록을 건너뜁니다.")
        return

    topic_rows = []

    for _, row in top10_df.iterrows():
        keyword = str(row.get("keyword", "")).strip()
        if not keyword:
            continue

        title = str(row.get("title", "")).strip() or keyword
        topic_rows.append({
            "platform": str(row.get("platform", "")).strip(),
            "title": title,
            "keyword": keyword,
            "search_intent": str(row.get("search_intent", "")).strip(),
            "status": "drafted",
            "created_at": str(row.get("created_at", "")).strip(),
        })

    saved_topic_count = append_topic_used(topic_rows, default_status="drafted")
    print(f"topic_used.csv 즉시 기록: {saved_topic_count}건")


if __name__ == "__main__":
    main()
