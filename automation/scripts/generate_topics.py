from datetime import datetime

import pandas as pd

from paths import DATA_DIR
from topic_registry import read_csv_safe

KEYWORD_CANDIDATES_PATH = DATA_DIR / "keyword_candidates.csv"
USABLE_KEYWORDS_PATH = DATA_DIR / "usable_keywords.csv"
TOP10_PATH = DATA_DIR / "topic_top10.csv"
HISTORY_TOP10_PATH = DATA_DIR / "topic_top10_history.csv"

TOPIC_COUNT = 12


def select_input_path():
    if KEYWORD_CANDIDATES_PATH.exists():
        return KEYWORD_CANDIDATES_PATH
    return USABLE_KEYWORDS_PATH


def make_title(keyword):
    keyword = str(keyword).strip()
    if not keyword:
        return "제목 없음"
    kw = keyword.lower()
    if any(x in kw for x in ["안됨", "오류", "해결", "안 됨", "작동 안함", "에러"]):
        return f"{keyword} 원인과 해결 방법"
    if any(x in kw for x in ["차이", "비교", "vs", "versus"]):
        return f"{keyword} 어떻게 다른가"
    if any(x in kw for x in ["초보", "처음", "입문", "기본 설정"]):
        return f"{keyword} 처음 시작하는 방법"
    if any(x in kw for x in ["자동화", "업무", "보고서", "반복"]):
        return f"{keyword} 실무에서 바로 쓰는 법"
    if any(x in kw for x in ["설정", "옵션", "세팅"]):
        return f"{keyword} 제대로 설정하는 방법"
    return f"{keyword} 사용할 때 알아야 할 것"


def remove_history(df):
    history_df = read_csv_safe(HISTORY_TOP10_PATH)

    if history_df.empty or "keyword" not in history_df.columns:
        return df

    past_keywords = set(history_df["keyword"].dropna().astype(str))
    return df[~df["keyword"].astype(str).isin(past_keywords)].copy()


def prepare_topics(df):
    if df.empty:
        return df

    df = df.copy()

    if "keyword" not in df.columns:
        return pd.DataFrame()

    if "final_score" not in df.columns:
        if "trend_score" in df.columns:
            df["final_score"] = pd.to_numeric(df["trend_score"], errors="coerce").fillna(0)
        else:
            df["final_score"] = 0

    if "title" not in df.columns:
        df["title"] = df["keyword"].apply(make_title)

    if "created_at" not in df.columns:
        df["created_at"] = datetime.now().strftime("%Y-%m-%d")

    return df


def save_history(topics_df):
    if topics_df.empty:
        return

    history_df = topics_df.copy()
    history_df["selected_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    old_history_df = read_csv_safe(HISTORY_TOP10_PATH)
    if not old_history_df.empty:
        history_df = pd.concat([old_history_df, history_df], ignore_index=True)

    history_df.to_csv(HISTORY_TOP10_PATH, index=False, encoding="utf-8-sig")


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    input_path = select_input_path()
    print("[generate_topics.py] topic selection started")
    print(f"input: {input_path}")

    source_df = read_csv_safe(input_path)
    source_df = prepare_topics(source_df)

    if source_df.empty:
        print("No usable keyword rows found.")
        return

    approved_df = source_df[source_df["final_score"] >= 80].copy()
    hold_df = source_df[
        (source_df["final_score"] >= 60) & (source_df["final_score"] < 80)
    ].copy()
    rejected_df = source_df[source_df["final_score"] < 60].copy()

    top_pool_df = remove_history(source_df)
    top10_df = top_pool_df.sort_values(by=["final_score"], ascending=False).head(TOPIC_COUNT).copy()

    approved_df.to_csv(DATA_DIR / "topic_approved.csv", index=False, encoding="utf-8-sig")
    hold_df.to_csv(DATA_DIR / "topic_hold.csv", index=False, encoding="utf-8-sig")
    rejected_df.to_csv(DATA_DIR / "topic_rejected.csv", index=False, encoding="utf-8-sig")
    top10_df.to_csv(TOP10_PATH, index=False, encoding="utf-8-sig")

    save_history(top10_df)

    print("topic_top10.csv saved")
    print(f"source rows: {len(source_df)}")
    print(f"approved rows: {len(approved_df)}")
    print(f"top rows: {len(top10_df)}")
    print(f"output: {TOP10_PATH}")


if __name__ == "__main__":
    main()
