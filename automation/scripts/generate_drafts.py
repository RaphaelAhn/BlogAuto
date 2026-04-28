import os
from datetime import datetime
from pathlib import Path

import pandas as pd

from topic_registry import append_topic_used


BASE_DIR = Path(__file__).resolve().parent.parent

QUEUE_PATH = BASE_DIR / "data" / "writing_queue.csv"

OUTPUT_DIRS = {
    "naver": BASE_DIR / "naver" / "drafts",
    "tistory": BASE_DIR / "tistory" / "drafts",
    "blogspot_kr": BASE_DIR / "blogspot" / "drafts",
    "blogspot_en": BASE_DIR / "blogspot_en" / "drafts",
}


def read_csv():
    return pd.read_csv(QUEUE_PATH, encoding="utf-8-sig")


def save_csv(df):
    df.to_csv(QUEUE_PATH, index=False, encoding="utf-8-sig")


def create_dummy_content(title, keyword):
    return f"""
제목: {title}

이 글은 '{keyword}'에 대한 설명입니다.

1. 개념 설명
2. 문제 해결 방법
3. 실무 적용 방법

자동 생성 테스트 콘텐츠입니다.
"""


def main():
    print("초안 생성 시작")

    df = read_csv()
    pending_df = df[df["status"] == "pending"]

    if pending_df.empty:
        print("생성할 글 없음")
        return

    topic_rows = []

    for idx, row in pending_df.iterrows():
        platform = row["platform"]
        title = row["title"]
        keyword = row["keyword"]
        topic_id = row["topic_id"]

        output_dir = OUTPUT_DIRS.get(platform)

        if not output_dir:
            continue

        os.makedirs(output_dir, exist_ok=True)

        content = create_dummy_content(title, keyword)
        file_path = output_dir / f"{topic_id}.txt"

        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)

        df.loc[idx, "status"] = "drafted"
        topic_rows.append({
            "platform": platform,
            "title": title,
            "keyword": keyword,
            "search_intent": row.get("search_intent", ""),
            "status": "drafted",
            "created_at": datetime.now().strftime("%Y-%m-%d"),
        })

        print(f"생성 완료: {file_path}")

    save_csv(df)
    saved_topic_count = append_topic_used(topic_rows, default_status="drafted")

    print(f"topic_used.csv 즉시 기록: {saved_topic_count}건")
    print("\n초안 생성 완료")


if __name__ == "__main__":
    main()
