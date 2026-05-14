import json
import os
import re
from datetime import datetime

import pandas as pd
import requests

from paths import DATA_DIR
from topic_registry import (
    load_duplicate_candidates,
    load_existing_texts,
    normalize,
    read_csv_safe,
)

TOP10_PATH = DATA_DIR / "topic_top10.csv"
APPROVED_PATH = DATA_DIR / "topic_approved.csv"
KEYWORD_CANDIDATES_PATH = DATA_DIR / "keyword_candidates.csv"
QUEUE_PATH = DATA_DIR / "writing_queue.csv"
CONSOLIDATION_LOG_PATH = DATA_DIR / "consolidation_log.csv"
DUPLICATE_REPORT_LATEST_PATH = DATA_DIR / "duplicate_report_latest.csv"
DUPLICATE_REPORT_HISTORY_PATH = DATA_DIR / "duplicate_report_history.csv"

PERPLEXITY_API_KEY = os.getenv("PERPLEXITY_API_KEY")

QUEUE_TARGET_COUNT = 12

QUEUE_COLUMNS = [
    "topic_id",
    "platform",
    "category",
    "keyword",
    "title",
    "search_intent",
    "topic_type",
    "structure_hint",
    "priority",
    "source",
    "status",
    "created_at",
]

# 구조 변형을 큐 레벨에서 미리 순환 배정해 같은 유형 연속 배치를 방지
_STRUCTURE_ROTATION = [
    "workflow_playbook",
    "checklist_review",
    "comparison_guide",
    "problem_solution",
    "decision_guide",
    "standardization_blueprint",
    "quickstart_entry",
]

PLATFORM_LIMIT = {
    "naver": 4,
    "tistory": 4,
    "blogspot_kr": 4,
}

TOPIC_TYPE_ORDER = [
    "error_solution",
    "feature_explanation",
    "practical_usage",
    "comparison_analysis",
]

TOPIC_TYPE_TARGET_RATIO = {
    "error_solution": 0.35,
    "feature_explanation": 0.25,
    "practical_usage": 0.20,
    "comparison_analysis": 0.20,
}


def token_set(text):
    text = re.sub(r"[^0-9a-zA-Z가-힣\s]", " ", str(text))
    return {word for word in text.split() if len(word) >= 2}


def _token_matches(a, b, min_len=4):
    if a == b:
        return True
    if min(len(a), len(b)) >= min_len:
        return b.startswith(a) or a.startswith(b)
    return False


def is_semantic_duplicate(keyword, existing):
    keyword_norm = normalize(keyword)
    keyword_tokens = token_set(keyword)

    for old in existing:
        old_norm = normalize(old)
        if keyword_norm == old_norm:
            return True
        if len(keyword_norm) >= 4 and len(old_norm) >= 4:
            if keyword_norm in old_norm or old_norm in keyword_norm:
                return True

        old_tokens = token_set(old)
        match_count = 0
        for t_kw in keyword_tokens:
            for t_old in old_tokens:
                if _token_matches(t_kw, t_old):
                    match_count += 1
                    if match_count >= 2:
                        return True
    return False


def _score_title_overlap(left, right):
    left_tokens = token_set(left)
    right_tokens = token_set(right)
    if not left_tokens or not right_tokens:
        return 0.0
    return round(len(left_tokens & right_tokens) / max(1, min(len(left_tokens), len(right_tokens))), 4)


def judge_duplicate(row, candidates):
    keyword = str(row.get("keyword", "")).strip()
    title = str(row.get("title", keyword)).strip()
    topic_type = str(row.get("topic_type", "")).strip()
    keyword_norm = normalize(keyword)
    intent_core = normalize(keyword)

    best_review = None
    for candidate in candidates:
        candidate_keyword = str(candidate.get("keyword", "")).strip()
        candidate_title = str(candidate.get("title", "")).strip()
        candidate_norm = str(candidate.get("normalized_keyword", "")).strip()
        candidate_intent_core = normalize(candidate.get("intent_core", ""))
        candidate_topic_type = str(candidate.get("topic_type", "")).strip()
        title_overlap = _score_title_overlap(title or keyword, candidate_title or candidate_keyword)
        same_topic_type = bool(topic_type and candidate_topic_type and topic_type == candidate_topic_type)

        if keyword_norm and candidate_norm and keyword_norm == candidate_norm:
            return {
                "decision": "block",
                "reason": "exact keyword/title normalization match",
                "matched_source": candidate.get("source", ""),
                "matched_title": candidate_title,
                "matched_url": candidate.get("url", ""),
                "keyword_exact_match": 1,
                "intent_core_match": int(intent_core == candidate_intent_core and bool(intent_core)),
                "title_similarity": title_overlap,
                "body_similarity": 0.0,
                "structural_similarity": 0.0,
            }

        if intent_core and candidate_intent_core and intent_core == candidate_intent_core:
            return {
                "decision": "block",
                "reason": "intent_core match",
                "matched_source": candidate.get("source", ""),
                "matched_title": candidate_title,
                "matched_url": candidate.get("url", ""),
                "keyword_exact_match": 0,
                "intent_core_match": 1,
                "title_similarity": title_overlap,
                "body_similarity": 0.0,
                "structural_similarity": 0.0,
            }

        if title_overlap >= 0.67 and same_topic_type:
            return {
                "decision": "block",
                "reason": "high title overlap within same topic_type",
                "matched_source": candidate.get("source", ""),
                "matched_title": candidate_title,
                "matched_url": candidate.get("url", ""),
                "keyword_exact_match": 0,
                "intent_core_match": 0,
                "title_similarity": title_overlap,
                "body_similarity": 0.0,
                "structural_similarity": 0.0,
            }

        if title_overlap >= 0.5:
            review_result = {
                "decision": "review",
                "reason": "moderate title overlap",
                "matched_source": candidate.get("source", ""),
                "matched_title": candidate_title,
                "matched_url": candidate.get("url", ""),
                "keyword_exact_match": 0,
                "intent_core_match": int(intent_core == candidate_intent_core and bool(intent_core)),
                "title_similarity": title_overlap,
                "body_similarity": 0.0,
                "structural_similarity": 0.0,
            }
            if best_review is None or review_result["title_similarity"] > best_review["title_similarity"]:
                best_review = review_result

    if best_review:
        return best_review

    return {
        "decision": "pass",
        "reason": "no strong duplicate signal detected",
        "matched_source": "",
        "matched_title": "",
        "matched_url": "",
        "keyword_exact_match": 0,
        "intent_core_match": 0,
        "title_similarity": 0.0,
        "body_similarity": 0.0,
        "structural_similarity": 0.0,
    }


def save_duplicate_report(rows):
    if not rows:
        return
    latest_df = pd.DataFrame(rows)
    try:
        latest_df.to_csv(DUPLICATE_REPORT_LATEST_PATH, index=False, encoding="utf-8-sig")
        history_df = read_csv_safe(DUPLICATE_REPORT_HISTORY_PATH)
        combined = pd.concat([history_df, latest_df], ignore_index=True)
        combined.to_csv(DUPLICATE_REPORT_HISTORY_PATH, index=False, encoding="utf-8-sig")
    except Exception as exc:
        print(f"[warning] duplicate report save skipped: {exc}")


def _call_perplexity_json(prompt):
    if not PERPLEXITY_API_KEY:
        return None

    headers = {
        "Authorization": f"Bearer {PERPLEXITY_API_KEY}",
        "Content-Type": "application/json",
    }
    body = {
        "model": "sonar",
        "messages": [{"role": "user", "content": prompt}],
    }

    for endpoint in [
        "https://api.perplexity.ai/chat/completions",
        "https://api.perplexity.ai/v1/sonar",
    ]:
        for _ in range(2):
            try:
                response = requests.post(endpoint, headers=headers, json=body, timeout=60)
                if response.status_code != 200:
                    break
                text = response.json()["choices"][0]["message"]["content"]
                match = re.search(r"\{.*?\}", text, re.DOTALL)
                if match:
                    return json.loads(match.group(0))
            except Exception:
                continue
    return None


def call_perplexity_inspection(keyword, category, search_intent, existing_keywords):
    existing_list = "\n".join(f"- {k}" for k in existing_keywords[:20]) or "(none)"
    prompt = f"""You are an SEO duplicate checker.

[New candidate]
keyword: {keyword}
category: {category}
search_intent: {search_intent}

[Existing references]
{existing_list}

Return JSON only:
{{
  "classification": "exact_duplicate" | "partial_overlap" | "distinct",
  "most_similar": "keyword or title",
  "reason": "short reason",
  "block": true | false
}}"""
    result = _call_perplexity_json(prompt)
    if not result or "block" not in result:
        return {"classification": "distinct", "most_similar": None, "reason": "inspection unavailable", "block": False}
    return result


def call_perplexity_consolidation(keyword_a, intent_a, keyword_b, intent_b):
    prompt = f"""You are an SEO consolidation checker.

A: {keyword_a} / {intent_a}
B: {keyword_b} / {intent_b}

Return JSON only:
{{
  "action": "merge" | "hub_sub",
  "hub_keyword": "keyword",
  "hub_title": "title",
  "sub_keyword": "keyword or null",
  "reason": "short reason",
  "section_note": "short note"
}}"""
    return _call_perplexity_json(prompt)


def _save_consolidation_log(keyword_a, keyword_b, result):
    row = {
        "keyword_a": keyword_a,
        "keyword_b": keyword_b,
        "action": result.get("action", ""),
        "hub_keyword": result.get("hub_keyword", ""),
        "hub_title": result.get("hub_title", ""),
        "sub_keyword": result.get("sub_keyword", ""),
        "reason": result.get("reason", ""),
        "section_note": result.get("section_note", ""),
        "logged_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    old_df = read_csv_safe(CONSOLIDATION_LOG_PATH)
    new_df = pd.concat([old_df, pd.DataFrame([row])], ignore_index=True)
    new_df.to_csv(CONSOLIDATION_LOG_PATH, index=False, encoding="utf-8-sig")


def make_topic_id(platform, keyword, index):
    today = datetime.now().strftime("%Y%m%d")
    safe_keyword = normalize(keyword)[:20]
    return f"{today}_{platform}_{index:03d}_{safe_keyword}"


def _estimate_score(keyword):
    score = 50
    kw = str(keyword).lower()
    if any(x in kw for x in ["안됨", "오류", "해결", "문제", "작동 안함"]):
        score += 25
    if any(x in kw for x in ["실무", "자동화", "업무", "사용", "보고서"]):
        score += 20
    if any(x in kw for x in ["초보", "기본", "처음", "입문"]):
        score += 15
    if any(x in kw for x in ["방법", "사용법", "설정"]):
        score += 15
    if any(x in kw for x in ["차이", "비교", "vs", "추천"]):
        score += 10
    return min(score, 100)


def _top_similar_existing(keyword, existing_all, top_n=30):
    if len(existing_all) <= top_n:
        return list(existing_all)
    kw_tokens = set(re.sub(r"[^0-9a-zA-Z가-힣\s]", " ", str(keyword)).split())
    scored = []
    for existing in existing_all:
        ex_tokens = set(re.sub(r"[^0-9a-zA-Z가-힣\s]", " ", str(existing)).split())
        scored.append((len(kw_tokens & ex_tokens), existing))
    scored.sort(key=lambda x: -x[0])
    return [ex for _, ex in scored[:top_n]]


def load_topics():
    sources = [
        ("topic_top10.csv", read_csv_safe(TOP10_PATH)),
        ("topic_approved.csv", read_csv_safe(APPROVED_PATH)),
        ("keyword_candidates.csv", read_csv_safe(KEYWORD_CANDIDATES_PATH)),
    ]
    ordered_frames = []
    seen_keywords = set()

    for label, df in sources:
        if df.empty or "keyword" not in df.columns:
            continue
        working = df.copy()
        if "final_score" not in working.columns and "trend_score" in working.columns:
            working["final_score"] = pd.to_numeric(working["trend_score"], errors="coerce").fillna(0)
        elif "final_score" in working.columns:
            working["final_score"] = pd.to_numeric(working["final_score"], errors="coerce").fillna(0)
        else:
            working["final_score"] = working["keyword"].apply(_estimate_score)

        if "title" not in working.columns:
            working["title"] = working["keyword"].astype(str)

        working = working.sort_values(by=["final_score"], ascending=False)
        working["keyword_norm"] = working["keyword"].astype(str).map(normalize)
        working = working[working["keyword_norm"].astype(bool)]
        working = working[~working["keyword_norm"].isin(seen_keywords)].copy()
        if working.empty:
            continue
        seen_keywords.update(working["keyword_norm"].tolist())
        ordered_frames.append(working.drop(columns=["keyword_norm"]))
        print(f"{label} loaded: {len(working)} rows")

    if not ordered_frames:
        return pd.DataFrame()
    return pd.concat(ordered_frames, ignore_index=True)


def platform_score(row):
    keyword = str(row.get("keyword", ""))
    intent = str(row.get("search_intent", ""))
    source = str(row.get("source", ""))
    scores = {"naver": 0, "tistory": 0, "blogspot_kr": 0}

    if source == "naver_suggest":
        scores["naver"] += 3
    if intent == "problem_solving":
        scores["naver"] += 3
    if any(word in keyword for word in ["오류", "안됨", "해결", "초보"]):
        scores["naver"] += 2

    if intent in ["practical", "comparison"]:
        scores["tistory"] += 3
    if any(word in keyword for word in ["자동화", "업무", "보고서"]):
        scores["tistory"] += 2

    if intent == "how_to":
        scores["blogspot_kr"] += 2
    if re.search(r"[A-Za-z]", keyword):
        scores["blogspot_kr"] += 1
    return scores


def build_row(row, platform, index):
    keyword = str(row.get("keyword", ""))
    return {
        "topic_id": make_topic_id(platform, keyword, index),
        "platform": platform,
        "category": row.get("category", ""),
        "keyword": keyword,
        "title": row.get("title", keyword),
        "search_intent": row.get("search_intent", ""),
        "topic_type": row.get("topic_type", ""),
        "structure_hint": _STRUCTURE_ROTATION[index % len(_STRUCTURE_ROTATION)],
        "priority": row.get("final_score", ""),
        "source": row.get("source", ""),
        "status": "pending",
        "created_at": datetime.now().strftime("%Y-%m-%d"),
    }


def build_topic_type_targets(total_count):
    raw_targets = {
        topic_type: TOPIC_TYPE_TARGET_RATIO.get(topic_type, 0) * total_count
        for topic_type in TOPIC_TYPE_ORDER
    }
    targets = {topic_type: int(raw_targets[topic_type]) for topic_type in TOPIC_TYPE_ORDER}
    assigned = sum(targets.values())
    remainders = sorted(TOPIC_TYPE_ORDER, key=lambda name: (-1 * (raw_targets[name] - targets[name]), name))
    for topic_type in remainders:
        if assigned >= total_count:
            break
        targets[topic_type] += 1
        assigned += 1
    return targets


def choose_platform(row, platform_count):
    scores = platform_score(row)
    return min(
        (p for p in platform_count if platform_count[p] < PLATFORM_LIMIT[p]),
        key=lambda p: (-scores.get(p, 0), platform_count[p], p),
        default=None,
    )


def can_add_topic_type(row, topic_type_count, target_counts, strict):
    topic_type = str(row.get("topic_type", "")).strip()
    if not strict or topic_type not in target_counts:
        return True
    return topic_type_count.get(topic_type, 0) < target_counts.get(topic_type, 0)


def try_add_row(
    row,
    selected_rows,
    selected_keys,
    existing_all,
    duplicate_candidates,
    report_rows,
    platform_count,
    topic_type_count,
    target_counts,
    strict,
    run_inspection,
):
    keyword = str(row.get("keyword", "")).strip()
    if not keyword:
        return False

    keyword_key = normalize(keyword)
    if keyword_key in selected_keys:
        return False

    if not can_add_topic_type(row, topic_type_count, target_counts, strict):
        return False

    judged = judge_duplicate(row, duplicate_candidates)
    report_rows.append({
        "checked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "stage": "writing_queue",
        "keyword": keyword,
        "title": str(row.get("title", keyword)).strip(),
        "topic_type": str(row.get("topic_type", "")).strip(),
        "search_intent": str(row.get("search_intent", "")).strip(),
        **judged,
    })
    if judged["decision"] == "block":
        return False

    if is_semantic_duplicate(keyword, existing_all):
        return False

    if run_inspection:
        inspection = call_perplexity_inspection(
            keyword,
            str(row.get("category", "")),
            str(row.get("search_intent", "")),
            _top_similar_existing(keyword, existing_all),
        )
        if inspection.get("block"):
            similar = inspection.get("most_similar") or ""
            if similar:
                consolidation = call_perplexity_consolidation(
                    keyword,
                    str(row.get("search_intent", "")),
                    similar,
                    "",
                )
                if consolidation:
                    _save_consolidation_log(keyword, similar, consolidation)
            return False

    platform = choose_platform(row, platform_count)
    if platform is None:
        return False

    selected_rows.append(build_row(row, platform, len(selected_rows) + 1))
    selected_keys.add(keyword_key)
    existing_all.append(keyword)
    duplicate_candidates.append({
        "source": "writing_queue_selected",
        "platform": platform,
        "title": str(row.get("title", keyword)).strip(),
        "keyword": keyword,
        "intent_core": normalize(keyword),
        "intent_detail": "",
        "search_intent": str(row.get("search_intent", "")).strip(),
        "topic_type": str(row.get("topic_type", "")).strip(),
        "url": "",
        "content": "",
        "normalized_keyword": keyword_key,
    })
    platform_count[platform] += 1
    topic_type = str(row.get("topic_type", "")).strip()
    topic_type_count[topic_type] = topic_type_count.get(topic_type, 0) + 1
    return True


def build_queue():
    topic_df = load_topics()
    if topic_df.empty:
        print("No topics available to build a queue.")
        return pd.DataFrame(columns=QUEUE_COLUMNS)

    blocked_texts = load_existing_texts(include_writing_queue=True)
    duplicate_candidates = load_duplicate_candidates(include_writing_queue=True)
    report_rows = []
    selected_rows = []
    selected_keys = set()
    existing_all = list(blocked_texts)
    platform_count = {name: 0 for name in PLATFORM_LIMIT}
    topic_type_count = {topic_type: 0 for topic_type in TOPIC_TYPE_ORDER}
    target_counts = build_topic_type_targets(QUEUE_TARGET_COUNT)

    for strict in [True, False]:
        for run_inspection in [True, False]:
            for topic_type in TOPIC_TYPE_ORDER:
                if len(selected_rows) >= QUEUE_TARGET_COUNT:
                    break
                pool = topic_df[topic_df["topic_type"].astype(str) == topic_type]
                for _, row in pool.iterrows():
                    if len(selected_rows) >= QUEUE_TARGET_COUNT:
                        break
                    try_add_row(
                        row=row,
                        selected_rows=selected_rows,
                        selected_keys=selected_keys,
                        existing_all=existing_all,
                        duplicate_candidates=duplicate_candidates,
                        report_rows=report_rows,
                        platform_count=platform_count,
                        topic_type_count=topic_type_count,
                        target_counts=target_counts,
                        strict=strict,
                        run_inspection=run_inspection,
                    )

    if len(selected_rows) < QUEUE_TARGET_COUNT:
        for strict in [True, False]:
            for _, row in topic_df.iterrows():
                if len(selected_rows) >= QUEUE_TARGET_COUNT:
                    break
                try_add_row(
                    row=row,
                    selected_rows=selected_rows,
                    selected_keys=selected_keys,
                    existing_all=existing_all,
                    duplicate_candidates=duplicate_candidates,
                    report_rows=report_rows,
                    platform_count=platform_count,
                    topic_type_count=topic_type_count,
                    target_counts=target_counts,
                    strict=strict,
                    run_inspection=False,
                )

    if len(selected_rows) < QUEUE_TARGET_COUNT:
        print(f"Unique non-duplicate topics were insufficient. Queue will be created with {len(selected_rows)} rows.")

    print("[queue-balance] selected topic type counts:")
    for topic_type in TOPIC_TYPE_ORDER:
        print(f"- {topic_type}: {topic_type_count.get(topic_type, 0)} / target {target_counts.get(topic_type, 0)}")

    save_duplicate_report(report_rows)
    return pd.DataFrame(selected_rows, columns=QUEUE_COLUMNS).head(QUEUE_TARGET_COUNT)


def main():
    print("Writing queue build started")

    existing_queue = read_csv_safe(QUEUE_PATH)
    if not existing_queue.empty and "status" in existing_queue.columns:
        pending_count = (existing_queue["status"] == "pending").sum()
        if pending_count > 0:
            print(f"Existing pending queue rows detected: {pending_count}. Skipping rebuild.")
            return

    df = build_queue()
    if df.empty:
        print("No queue rows were created.")
        return

    df.to_csv(QUEUE_PATH, index=False, encoding="utf-8-sig")

    print("\nQueue build completed")
    print(f"saved rows: {len(df)}")
    print(df["platform"].value_counts())


if __name__ == "__main__":
    main()
