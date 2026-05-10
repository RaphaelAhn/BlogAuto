import json
import os
import re
from datetime import datetime

import pandas as pd
import requests

from paths import DATA_DIR
from topic_registry import load_existing_texts, normalize, read_csv_safe

TOP10_PATH = DATA_DIR / "topic_top10.csv"
APPROVED_PATH = DATA_DIR / "topic_approved.csv"
KEYWORD_CANDIDATES_PATH = DATA_DIR / "keyword_candidates.csv"
QUEUE_PATH = DATA_DIR / "writing_queue.csv"
CONSOLIDATION_LOG_PATH = DATA_DIR / "consolidation_log.csv"

PERPLEXITY_API_KEY = os.getenv("PERPLEXITY_API_KEY")

QUEUE_TARGET_COUNT = 12

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

PLATFORM_LIMIT = {
    "naver": 4,
    "tistory": 4,
    "blogspot_kr": 4,
}


def token_set(text):
    text = re.sub(r"[^0-9a-zA-Z가-힣\s]", " ", str(text))
    return {word for word in text.split() if len(word) >= 2}


def _token_matches(a, b, min_len=4):
    """완전 일치 또는 한쪽이 다른 쪽의 접두사인 경우 True.
    'Copilot' vs 'Copilot으로', '합성' vs '합성하는' 등 어미 변형 대응."""
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

        # 정규화 후 완전 일치
        if keyword_norm == old_norm:
            return True

        # 한쪽이 다른 쪽에 포함되는 경우 (4자 이상일 때만 적용)
        if len(keyword_norm) >= 4 and len(old_norm) >= 4:
            if keyword_norm in old_norm or old_norm in keyword_norm:
                return True

        # 접두사 포함 토큰 매칭: 2개 이상 겹치면 중복
        old_tokens = token_set(old)
        match_count = 0
        for t_kw in keyword_tokens:
            for t_old in old_tokens:
                if _token_matches(t_kw, t_old):
                    match_count += 1
                    if match_count >= 2:
                        return True

    return False


def _call_perplexity_json(prompt):
    """Perplexity API를 호출하고 JSON 파싱 결과를 반환합니다. 실패 시 None."""
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
    endpoints = [
        "https://api.perplexity.ai/chat/completions",
        "https://api.perplexity.ai/v1/sonar",
    ]

    for endpoint in endpoints:
        for attempt in range(1, 3):
            try:
                response = requests.post(endpoint, headers=headers, json=body, timeout=60)
                if response.status_code != 200:
                    break
                text = response.json()["choices"][0]["message"]["content"]
                match = re.search(r"\{.*?\}", text, re.DOTALL)
                if match:
                    return json.loads(match.group(0))
            except Exception:
                if attempt == 2:
                    break
    return None


def call_perplexity_inspection(keyword, category, search_intent, existing_keywords):
    """1번 프롬프트: 규칙 필터 통과 후보를 LLM으로 검수합니다."""
    existing_list = "\n".join(f"- {k}" for k in existing_keywords[:20]) or "(없음)"

    prompt = f"""당신은 SEO 카니발라이제이션 검수 에이전트입니다.

[신규 후보 주제]
키워드: {keyword}
카테고리: {category}
검색 의도: {search_intent}

[기존 글 목록]
{existing_list}

판정을 3단계로 수행하세요.

1단계 — 내부 비교 (출력 불필요)
핵심 문제 / 사용자 상황 / 최종 목적 각각이 기존 글과 동일한지 확인합니다.

2단계 — 분류
- 완전중복: 핵심 문제 + 사용자 상황 + 최종 목적이 모두 같고 별도 유지 실익 없음
- 부분중복: 셋 중 하나만 다른 경우
- 별개: 셋 중 둘 이상이 다른 경우

3단계 — 출력
반드시 아래 JSON만 출력하세요. 설명 문장 금지.

{{
  "classification": "완전중복" | "부분중복" | "별개",
  "most_similar": "가장 유사한 기존 글 키워드 또는 null",
  "reason": "판정 이유 한 줄",
  "block": true | false
}}

block 규칙: 완전중복이면 true, 나머지는 false"""

    result = _call_perplexity_json(prompt)
    if not result or "block" not in result:
        return {"classification": "별개", "most_similar": None, "reason": "API 실패 — 통과 처리", "block": False}
    return result


def call_perplexity_consolidation(keyword_a, intent_a, keyword_b, intent_b):
    """2번 프롬프트: 완전중복 판정 시 통합 방식을 결정합니다."""
    prompt = f"""당신은 SEO 콘텐츠 구조 설계 에이전트입니다.
아래 두 주제는 완전중복으로 판정되었습니다.

[주제 A]
키워드: {keyword_a}
검색 의도: {intent_a}

[주제 B]
키워드: {keyword_b}
검색 의도: {intent_b}

판단 기준:
- 두 주제의 검색 볼륨 차이가 크면 → merge (하나로 흡수)
- 사용자 상황이 달라 병렬 유지가 가능하면 → hub_sub (허브/서브 분리)

hub_sub 선택 시: 검색 볼륨이 높은 키워드를 허브로 지정합니다.

반드시 아래 JSON만 출력하세요. 설명 문장 금지.

{{
  "action": "merge" | "hub_sub",
  "hub_keyword": "허브 글 대표 키워드",
  "hub_title": "허브 글 제목 후보",
  "sub_keyword": "서브 글 키워드 또는 null",
  "reason": "통합 방식 선택 이유 한 줄",
  "section_note": "허브 글 내 섹션 배치 방향 한 줄"
}}"""

    return _call_perplexity_json(prompt)


def _save_consolidation_log(keyword_a, keyword_b, result):
    """통합 판정 결과를 consolidation_log.csv에 기록합니다."""
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
    """final_score 컬럼이 없는 키워드에 대해 내용 기반 점수를 추정합니다."""
    score = 50
    kw = str(keyword).lower()
    if any(x in kw for x in ["안됨", "오류", "해결", "문제", "작동 안함"]):
        score += 25
    if any(x in kw for x in ["실무", "자동화", "업무", "활용", "보고서"]):
        score += 20
    if any(x in kw for x in ["초보", "기본", "처음", "입문"]):
        score += 15
    if any(x in kw for x in ["방법", "사용법", "설정"]):
        score += 15
    if any(x in kw for x in ["차이", "비교", "vs", "추천"]):
        score += 10
    return min(score, 100)


def _top_similar_existing(keyword, existing_all, top_n=30):
    """기존 키워드 목록에서 신규 키워드와 토큰 유사도가 높은 상위 top_n개를 반환합니다."""
    if len(existing_all) <= top_n:
        return list(existing_all)
    kw_tokens = set(re.sub(r"[^0-9a-zA-Z가-힣\s]", " ", str(keyword)).split())
    scored = []
    for existing in existing_all:
        ex_tokens = set(re.sub(r"[^0-9a-zA-Z가-힣\s]", " ", str(existing)).split())
        overlap = len(kw_tokens & ex_tokens)
        scored.append((overlap, existing))
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

    scores = {
        "naver": 0,
        "tistory": 0,
        "blogspot_kr": 0,
    }

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
        "priority": row.get("final_score", ""),
        "source": row.get("source", ""),
        "status": "pending",
        "created_at": datetime.now().strftime("%Y-%m-%d"),
    }


def build_queue():
    topic_df = load_topics()
    if topic_df.empty:
        print("No topics available to build a queue.")
        return pd.DataFrame(columns=QUEUE_COLUMNS)

    blocked_texts = load_existing_texts(include_writing_queue=True)
    selected_rows = []
    selected_keys = set()
    existing_all = list(blocked_texts)
    platform_count = {name: 0 for name in PLATFORM_LIMIT}

    for _, row in topic_df.iterrows():
        if len(selected_rows) >= QUEUE_TARGET_COUNT:
            break

        keyword = str(row.get("keyword", "")).strip()
        if not keyword:
            continue

        keyword_key = normalize(keyword)
        if keyword_key in selected_keys:
            continue

        # 1단계: 규칙 기반 필터
        if is_semantic_duplicate(keyword, existing_all):
            continue

        # 2단계: LLM 검수 — 유사도 높은 기존 키워드 우선 선별
        inspection = call_perplexity_inspection(
            keyword,
            str(row.get("category", "")),
            str(row.get("search_intent", "")),
            _top_similar_existing(keyword, existing_all),
        )
        if inspection.get("block"):
            if inspection.get("classification") == "완전중복":
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
            continue

        # 3단계: 플랫폼 배분 — 점수 동점 시 현재 배정 수가 적은 플랫폼 우선
        scores = platform_score(row)
        platform = min(
            (p for p in platform_count if platform_count[p] < PLATFORM_LIMIT[p]),
            key=lambda p: (-scores.get(p, 0), platform_count[p], p),
            default=None,
        )
        if platform is None:
            continue

        selected_rows.append(build_row(row, platform, len(selected_rows) + 1))
        selected_keys.add(keyword_key)
        existing_all.append(keyword)
        platform_count[platform] += 1

    if len(selected_rows) < QUEUE_TARGET_COUNT:
        for _, row in topic_df.iterrows():
            if len(selected_rows) >= QUEUE_TARGET_COUNT:
                break

            keyword = str(row.get("keyword", "")).strip()
            if not keyword:
                continue

            keyword_key = normalize(keyword)
            if keyword_key in selected_keys:
                continue

            if is_semantic_duplicate(keyword, existing_all):
                continue

            scores = platform_score(row)
            platform = min(
                (p for p in platform_count if platform_count[p] < PLATFORM_LIMIT[p]),
                key=lambda p: (-scores.get(p, 0), platform_count[p], p),
                default=None,
            )
            if platform is None:
                break
            selected_rows.append(build_row(row, platform, len(selected_rows) + 1))
            selected_keys.add(keyword_key)
            existing_all.append(keyword)

    if len(selected_rows) < QUEUE_TARGET_COUNT:
        print(
            f"Unique non-duplicate topics were insufficient. "
            f"Queue will be created with {len(selected_rows)} rows."
        )

    return pd.DataFrame(selected_rows, columns=QUEUE_COLUMNS).head(QUEUE_TARGET_COUNT)


def main():
    print("Writing queue build started")

    # 처리 안 된 pending 항목이 남아 있으면 큐를 재빌드하지 않음
    existing_queue = read_csv_safe(QUEUE_PATH)
    if not existing_queue.empty and "status" in existing_queue.columns:
        pending_count = (existing_queue["status"] == "pending").sum()
        if pending_count > 0:
            print(f"기존 큐에 pending 항목 {pending_count}건 존재. 큐 재빌드 건너뜀.")
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
