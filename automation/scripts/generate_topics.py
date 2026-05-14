from datetime import datetime

import pandas as pd

from paths import DATA_DIR
from topic_registry import read_csv_safe

KEYWORD_CANDIDATES_PATH = DATA_DIR / "keyword_candidates.csv"
USABLE_KEYWORDS_PATH = DATA_DIR / "usable_keywords.csv"
TOP10_PATH = DATA_DIR / "topic_top10.csv"
HISTORY_TOP10_PATH = DATA_DIR / "topic_top10_history.csv"

TOPIC_COUNT = 12
TOPIC_TYPE_ORDER = [
    "error_solution",
    "feature_explanation",
    "practical_usage",
    "comparison_analysis",
]
TOPIC_TYPE_LABELS = {
    "error_solution": "\uc624\ub958 \ud574\uacb0\ud615",
    "feature_explanation": "\uae30\ub2a5 \uc124\uba85\ud615",
    "practical_usage": "\uc2e4\ubb34 \ud65c\uc6a9\ud615",
    "comparison_analysis": "\ube44\uad50/\ubd84\uc11d\ud615",
}
TOPIC_TYPE_TARGET_RATIO = {
    "error_solution": 0.35,
    "feature_explanation": 0.25,
    "comparison_analysis": 0.20,
    "practical_usage": 0.20,
}
TITLE_TEMPLATES = {
    "error_solution": [
        "{keyword} 원인과 해결 방법",
        "{keyword} 자주 생기는 이유와 점검 순서",
        "{keyword} 해결 전에 먼저 확인할 것",
        "{keyword} 문제를 줄이는 실무 처리 순서",
    ],
    "feature_explanation": [
        "{keyword} 기능과 사용 방법 쉽게 설명",
        "{keyword} 처음 시작할 때 알아두면 좋은 사용법",
        "{keyword} 초보자도 이해하기 쉬운 설정과 활용",
        "{keyword} 기본 개념부터 적용 방법까지 정리",
    ],
    "practical_usage": [
        "{keyword} 실무에서 바로 쓰는 방법",
        "{keyword} 업무에 적용하는 단계별 방법",
        "{keyword} 작업 흐름에 맞춰 정리한 활용법",
        "{keyword} 반복 작업을 줄이는 실전 사용법",
    ],
    "comparison_analysis": [
        "{keyword} 차이점과 선택 기준 정리",
        "{keyword} 비교할 때 먼저 봐야 할 핵심",
        "{keyword} 어떤 상황에서 무엇을 골라야 하는지 정리",
        "{keyword} 차이를 이해하고 선택하는 방법",
    ],
}
INTENT_TO_TOPIC_TYPE = {
    "problem_solving": "error_solution",
    "how_to": "feature_explanation",
    "informational": "feature_explanation",
    "practical": "practical_usage",
    "comparison": "comparison_analysis",
}


def _compute_seed(*parts):
    text = "|".join(str(part).strip().lower() for part in parts if str(part).strip())
    if not text:
        return 0
    return sum((idx + 1) * ord(char) for idx, char in enumerate(text))


def select_input_path():
    if KEYWORD_CANDIDATES_PATH.exists():
        return KEYWORD_CANDIDATES_PATH
    return USABLE_KEYWORDS_PATH


def infer_topic_type(keyword, search_intent):
    keyword = str(keyword).strip().lower()
    intent = str(search_intent).strip().lower()

    if intent in INTENT_TO_TOPIC_TYPE:
        return INTENT_TO_TOPIC_TYPE[intent]

    if any(
        token in keyword
        for token in [
            "\uc624\ub958",
            "\uc548\ub428",
            "\ubb38\uc81c",
            "\ubcf5\uad6c",
            "\uc2e4\ud328",
            "\uba48\ucda4",
        ]
    ):
        return "error_solution"
    if any(
        token in keyword
        for token in [
            "\ube44\uad50",
            "\ucc28\uc774",
            "\uc7a5\ub2e8\uc810",
            "vs",
            "versus",
        ]
    ):
        return "comparison_analysis"
    if any(
        token in keyword
        for token in [
            "\uc2e4\ubb34",
            "\uc5c5\ubb34",
            "\uc790\ub3d9\ud654",
            "\uad00\ub9ac",
            "\ud611\uc5c5",
            "\ubcf4\uace0\uc11c",
        ]
    ):
        return "practical_usage"
    return "feature_explanation"


def make_title(keyword, topic_type):
    keyword = str(keyword).strip()
    if not keyword:
        return "\uc81c\ubaa9 \uc5c6\uc74c"
    templates = TITLE_TEMPLATES.get(topic_type, TITLE_TEMPLATES["feature_explanation"])
    seed = _compute_seed(keyword, topic_type)
    return templates[seed % len(templates)].format(keyword=keyword)


def build_topic_type_targets(total_count):
    raw_targets = {
        topic_type: TOPIC_TYPE_TARGET_RATIO.get(topic_type, 0) * total_count
        for topic_type in TOPIC_TYPE_ORDER
    }
    targets = {topic_type: int(raw_targets[topic_type]) for topic_type in TOPIC_TYPE_ORDER}
    assigned = sum(targets.values())
    remainders = sorted(
        TOPIC_TYPE_ORDER,
        key=lambda name: (-1 * (raw_targets[name] - targets[name]), _compute_seed(name, total_count)),
    )
    for topic_type in remainders:
        if assigned >= total_count:
            break
        targets[topic_type] += 1
        assigned += 1
    return targets


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
    else:
        df["final_score"] = pd.to_numeric(df["final_score"], errors="coerce").fillna(0)

    if "trend_score" not in df.columns:
        df["trend_score"] = 0
    else:
        df["trend_score"] = pd.to_numeric(df["trend_score"], errors="coerce").fillna(0)

    if "created_at" not in df.columns:
        df["created_at"] = datetime.now().strftime("%Y-%m-%d")

    if "topic_type" not in df.columns:
        df["topic_type"] = ""

    df["topic_type"] = df.apply(
        lambda row: infer_topic_type(row.get("keyword", ""), row.get("search_intent", "")),
        axis=1,
    )
    df["topic_type_label"] = df["topic_type"].map(TOPIC_TYPE_LABELS).fillna(
        "\uae30\ub2a5 \uc124\uba85\ud615"
    )

    if "title" not in df.columns:
        df["title"] = df.apply(
            lambda row: make_title(row.get("keyword", ""), row.get("topic_type", "")),
            axis=1,
        )
    else:
        missing_title = df["title"].fillna("").astype(str).str.strip().eq("")
        df.loc[missing_title, "title"] = df.loc[missing_title].apply(
            lambda row: make_title(row.get("keyword", ""), row.get("topic_type", "")),
            axis=1,
        )

    return df


def select_balanced_topics(df):
    if df.empty:
        return df

    working = df.sort_values(
        by=["final_score", "trend_score", "created_at"],
        ascending=[False, False, False],
    ).copy()
    target_counts = build_topic_type_targets(TOPIC_COUNT)
    selected_parts = []
    selected_keys = set()
    counts = {topic_type: 0 for topic_type in TOPIC_TYPE_ORDER}

    for topic_type in TOPIC_TYPE_ORDER:
        target_count = target_counts.get(topic_type, 0)
        if target_count <= 0:
            continue
        pool = working[working["topic_type"] == topic_type]
        if pool.empty:
            continue
        for idx, row in pool.iterrows():
            keyword = str(row.get("keyword", "")).strip()
            if not keyword or keyword in selected_keys:
                continue
            selected_parts.append(row.to_dict())
            selected_keys.add(keyword)
            counts[topic_type] += 1
            working = working.drop(index=idx)
            if counts[topic_type] >= target_count or len(selected_keys) >= TOPIC_COUNT:
                break
        if len(selected_keys) >= TOPIC_COUNT:
            break

    if len(selected_keys) < TOPIC_COUNT and not working.empty:
        for _, row in working.iterrows():
            keyword = str(row.get("keyword", "")).strip()
            if not keyword or keyword in selected_keys:
                continue
            selected_parts.append(row.to_dict())
            selected_keys.add(keyword)
            counts[row.get("topic_type", "")] = counts.get(row.get("topic_type", ""), 0) + 1
            if len(selected_keys) >= TOPIC_COUNT:
                break

    selected_df = pd.DataFrame(selected_parts)
    if selected_df.empty:
        return selected_df

    selected_df["topic_type_order"] = selected_df["topic_type"].map(
        {name: index for index, name in enumerate(TOPIC_TYPE_ORDER)}
    ).fillna(len(TOPIC_TYPE_ORDER))
    selected_df = selected_df.sort_values(
        by=["topic_type_order", "final_score", "created_at"],
        ascending=[True, False, False],
    ).drop(columns=["topic_type_order"])

    print("[topic-balance] selected topic type counts:")
    for topic_type in TOPIC_TYPE_ORDER:
        print(
            f"- {TOPIC_TYPE_LABELS[topic_type]}: "
            f"{counts.get(topic_type, 0)} / target {target_counts.get(topic_type, 0)}"
        )

    return selected_df.head(TOPIC_COUNT)


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
    top10_df = select_balanced_topics(top_pool_df)

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
