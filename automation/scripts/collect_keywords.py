import os
import re
import json
import requests
import pandas as pd
from pathlib import Path
from datetime import datetime
from urllib.parse import quote

from topic_registry import load_existing_texts, normalize, read_csv_safe


BASE_DIR = Path(__file__).resolve().parent.parent

ALLOWED_CATEGORIES_PATH = BASE_DIR / "data" / "allowed_categories.csv"
KEYWORD_CANDIDATES_PATH = BASE_DIR / "data" / "keyword_candidates.csv"
PREVIOUS_POSTS_PATH = BASE_DIR / "data" / "previous_posts.csv"
QA_USED_PATH = BASE_DIR / "data" / "qa_used.csv"
TOPIC_USED_PATH = BASE_DIR / "data" / "topic_used.csv"

PERPLEXITY_API_KEY = os.getenv("PERPLEXITY_API_KEY")


COLUMNS = [
    "category",
    "keyword",
    "source",
    "search_intent",
    "trend_score",
    "difficulty",
    "duplicate_risk",
    "reason",
    "created_at",
]


SEED_KEYWORDS = {
    "unity": ["유니티", "Unity", "Unity Editor", "Unity 오류"],
    "general_it": [
        "윈도우 오류",
        "Windows 오류",
        "컴퓨터 오류",
        "핸드폰 관리",
        "스마트폰 오류",
        "스마트폰 설정",
        "인터넷 연결 오류",
        "와이파이 오류",
    ],
    "office365": [
        "오피스365",
        "Microsoft 365",
        "엑셀",
        "Excel",
        "워드",
        "Word",
        "파워포인트",
        "PowerPoint",
        "PPT",
        "아웃룩",
        "Outlook",
        "원드라이브",
        "OneDrive",
        "팀즈",
        "Microsoft Teams",
        "원노트",
        "OneNote",
    ],
    "unreal": ["언리얼", "Unreal", "Unreal Engine", "언리얼 엔진"],
    "blender": ["블렌더", "Blender"],
    "python": ["파이썬", "Python"],
    "notion": ["노션", "Notion"],
    "figma": ["피그마", "Figma"],
    "canva": ["캔바", "Canva"],
    "jira": ["지라", "Jira"],
    "trello": ["트렐로", "Trello"],
}


EXPAND_WORDS = [
    "방법",
    "사용법",
    "안됨",
    "오류",
    "해결",
    "기본",
    "초보",
    "설정",
    "자동화",
    "차이",
    "비교",
    "정리",
    "실무",
    "활용",
    "문제",
]

def is_valid_keyword(keyword):
    keyword = str(keyword).strip()
    keyword_lower = keyword.lower()

    if len(keyword) < 4:
        return False

    if len(keyword) > 40:
        return False

    if re.search(r"[^0-9a-zA-Z가-힣\s]", keyword):
        return False

    bad_words = [
        "테스트",
        "sample",
        "example",
        "asdf",
        "1234",
        "undefined",
        "null",
        "none",
    ]

    if any(word in keyword_lower for word in bad_words):
        return False

    too_generic = [
        "유니티",
        "unity",
        "언리얼",
        "unreal",
        "파이썬",
        "python",
        "엑셀",
        "excel",
        "노션",
        "notion",
        "워드",
        "word",
        "ppt",
        "피그마",
        "figma",
        "블렌더",
        "blender",
        "캔바",
        "canva",
    ]

    if keyword_lower in too_generic:
        return False

    banned = [
        "무료 다운로드",
        "토렌트",
        "torrent",
        "크랙",
        "crack",
        "불법",
        "도박",
        "카지노",
        "성인",
        "19금",
        "해킹",
        "마약",
    ]

    if any(word in keyword_lower for word in banned):
        return False

    return True


def load_categories():
    df = read_csv_safe(ALLOWED_CATEGORIES_PATH, ["category"])

    if df.empty:
        return list(SEED_KEYWORDS.keys())

    categories = df["category"].dropna().astype(str).tolist()
    categories = [x.strip() for x in categories if x.strip()]

    if not categories:
        return list(SEED_KEYWORDS.keys())

    return categories


def get_google_suggestions(query):
    url = (
        "https://suggestqueries.google.com/complete/search"
        f"?client=firefox&q={quote(query)}"
    )

    try:
        response = requests.get(
            url,
            timeout=10,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        response.raise_for_status()
        data = response.json()

        if len(data) >= 2:
            return data[1]

    except Exception:
        return []

    return []


def extract_strings_from_json(obj):
    results = []

    if isinstance(obj, str):
        if 2 <= len(obj) <= 80:
            results.append(obj)

    elif isinstance(obj, list):
        for item in obj:
            results.extend(extract_strings_from_json(item))

    elif isinstance(obj, dict):
        for value in obj.values():
            results.extend(extract_strings_from_json(value))

    return results


def get_naver_suggestions(query):
    url = (
        "https://ac.search.naver.com/nx/ac"
        f"?q={quote(query)}"
        "&q_enc=UTF-8"
        "&st=100"
        "&r_format=json"
        "&r_enc=UTF-8"
        "&r_unicode=0"
        "&t_koreng=1"
        "&ans=2"
        "&run=2"
        "&rev=4"
        "&con=0"
    )

    try:
        response = requests.get(
            url,
            timeout=10,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Referer": "https://search.naver.com/",
            },
        )
        response.raise_for_status()
        data = response.json()

        raw_items = extract_strings_from_json(data)
        cleaned = []

        for item in raw_items:
            item = str(item).strip()

            if not item:
                continue

            if len(item) < 2:
                continue

            if item.startswith("http"):
                continue

            cleaned.append(item)

        return list(dict.fromkeys(cleaned))[:10]

    except Exception:
        return []


def call_perplexity_questions(category, seed):
    if not PERPLEXITY_API_KEY:
        return []

    prompt = f"""
'{category}' 분야에서 사람들이 실제로 많이 궁금해할 만한 검색 주제 15개를 만들어줘.

조건:
1. 글 제목으로 바꾸기 좋은 형태
2. 문제 해결형, 사용법, 비교, 실무 활용 중심
3. 너무 넓은 주제 금지
4. 아래 JSON 배열 형식으로만 답변

[
  "키워드 또는 질문",
  "키워드 또는 질문"
]

기준 키워드: {seed}
"""

    headers = {
        "Authorization": f"Bearer {PERPLEXITY_API_KEY}",
        "Content-Type": "application/json",
    }

    body = {
        "model": "sonar",
        "messages": [
            {
                "role": "user",
                "content": prompt,
            }
        ],
    }

    endpoints = [
        "https://api.perplexity.ai/v1/sonar",
        "https://api.perplexity.ai/chat/completions",
    ]

    for endpoint in endpoints:
        try:
            response = requests.post(
                endpoint,
                headers=headers,
                json=body,
                timeout=60,
            )

            if response.status_code != 200:
                continue

            data = response.json()
            text = data["choices"][0]["message"]["content"]

            match = re.search(r"\[.*\]", text, re.DOTALL)

            if not match:
                return []

            parsed = json.loads(match.group(0))

            if isinstance(parsed, list):
                return [str(x).strip() for x in parsed if str(x).strip()]

        except Exception:
            continue

    return []


def classify_intent(keyword):
    if any(x in keyword for x in ["안됨", "오류", "해결", "문제", "안 열림", "작동 안함"]):
        return "problem_solving"

    if any(x in keyword for x in ["차이", "비교", "vs", "장단점"]):
        return "comparison"

    if any(x in keyword for x in ["방법", "사용법", "설정", "기본", "만들기"]):
        return "how_to"

    if any(x in keyword for x in ["자동화", "실무", "활용", "업무", "보고서", "관리", "정리"]):
        return "practical"

    return "informational"


def score_keyword(keyword):
    score = 50

    if any(x in keyword for x in ["안됨", "오류", "해결", "문제", "안 열림", "작동 안함"]):
        score += 25

    if any(x in keyword for x in ["실무", "자동화", "업무", "활용", "보고서", "관리", "정리"]):
        score += 20

    if any(x in keyword for x in ["초보", "기본", "처음", "입문"]):
        score += 15

    if any(x in keyword for x in ["방법", "사용법", "설정", "만들기"]):
        score += 15

    if len(keyword) >= 12:
        score += 10

    if len(keyword) >= 18:
        score += 10

    return min(score, 100)


def estimate_difficulty(keyword):
    if len(keyword) >= 18:
        return "low"

    if any(x in keyword for x in ["오류", "안됨", "해결", "문제"]):
        return "medium"

    return "medium"


def make_reason(keyword):
    intent = classify_intent(keyword)

    if intent == "problem_solving":
        return "문제 해결형 검색어라 방문 의도가 강합니다."

    if intent == "how_to":
        return "사용 방법을 찾는 검색어라 단계별 설명 글로 만들기 좋습니다."

    if intent == "comparison":
        return "비교 검색 의도가 있어 선택 기준을 설명하는 글로 적합합니다."

    if intent == "practical":
        return "실무 활용 의도가 강해 경험형 콘텐츠로 확장하기 좋습니다."

    return "정보 탐색형 검색어라 기초 설명 글로 만들기 좋습니다."

def is_duplicate_with_existing(keyword, existing_texts):
    keyword_norm = normalize(keyword)

    if not keyword_norm:
        return True

    for old in existing_texts:
        if not old:
            continue

        if keyword_norm == old:
            return True

        if keyword_norm in old or old in keyword_norm:
            return True

        if len(keyword_norm) > 6 and keyword_norm[:5] in old:
            return True

    return False


def collect_keywords():
    categories = load_categories()
    existing_texts = load_existing_texts()

    rows = []
    blocked_duplicate_count = 0
    blocked_quality_count = 0

    for category in categories:
        seeds = SEED_KEYWORDS.get(category, [category])

        print(f"\n[{category}] 키워드 수집 시작")

        for seed in seeds:
            for word in EXPAND_WORDS:
                query = f"{seed} {word}"

                google_items = get_google_suggestions(query)
                naver_items = get_naver_suggestions(query)

                for source, items in [
                    ("google_suggest", google_items),
                    ("naver_suggest", naver_items),
                ]:
                    for keyword in items:
                        keyword = str(keyword).strip()

                        if not keyword:
                            continue

                        if not is_valid_keyword(keyword):
                            blocked_quality_count += 1
                            continue

                        if is_duplicate_with_existing(keyword, existing_texts):
                            blocked_duplicate_count += 1
                            continue

                        rows.append({
                            "category": category,
                            "keyword": keyword,
                            "source": source,
                            "search_intent": classify_intent(keyword),
                            "trend_score": score_keyword(keyword),
                            "difficulty": estimate_difficulty(keyword),
                            "duplicate_risk": "low",
                            "reason": make_reason(keyword),
                            "created_at": datetime.now().strftime("%Y-%m-%d"),
                        })

            perplexity_items = call_perplexity_questions(category, seed)

            for keyword in perplexity_items:
                keyword = str(keyword).strip()

                if not keyword:
                    continue

                if not is_valid_keyword(keyword):
                    blocked_quality_count += 1
                    continue

                if is_duplicate_with_existing(keyword, existing_texts):
                    blocked_duplicate_count += 1
                    continue

                rows.append({
                    "category": category,
                    "keyword": keyword,
                    "source": "perplexity_questions",
                    "search_intent": classify_intent(keyword),
                    "trend_score": score_keyword(keyword),
                    "difficulty": estimate_difficulty(keyword),
                    "duplicate_risk": "low",
                    "reason": make_reason(keyword),
                    "created_at": datetime.now().strftime("%Y-%m-%d"),
                })

    df = pd.DataFrame(rows, columns=COLUMNS)

    print(f"\n품질 기준에 맞지 않아 제외된 키워드 수: {blocked_quality_count}")
    print(f"기존 글/Q&A와 중복되어 제외된 키워드 수: {blocked_duplicate_count}")

    return df


def main():
    print("키워드 후보 수집 시작")
    print("수집원: Google Suggest + Naver Suggest + Perplexity Questions")

    old_df = read_csv_safe(KEYWORD_CANDIDATES_PATH, COLUMNS)
    new_df = collect_keywords()

    if new_df.empty:
        print("수집된 새 키워드가 없습니다.")
        return

    if "keyword" not in old_df.columns:
        old_df = pd.DataFrame(columns=COLUMNS)

    old_keys = set(old_df["keyword"].dropna().astype(str).map(normalize))

    new_df["keyword_norm"] = new_df["keyword"].map(normalize)

    new_only_df = new_df[~new_df["keyword_norm"].isin(old_keys)].copy()
    new_only_df = new_only_df.drop_duplicates(subset=["keyword_norm"])
    new_only_df = new_only_df.drop(columns=["keyword_norm"])

    final_df = pd.concat([old_df, new_only_df], ignore_index=True)
    final_df = final_df.drop_duplicates(subset=["category", "keyword"])

    final_df = final_df.sort_values(
        by=["trend_score", "difficulty"],
        ascending=[False, True],
    )

    final_df.to_csv(KEYWORD_CANDIDATES_PATH, index=False, encoding="utf-8-sig")

    print("\n키워드 후보 수집 완료")
    print(f"이번 수집 후보 수: {len(new_df)}")
    print(f"새로 추가된 키워드 수: {len(new_only_df)}")
    print(f"전체 키워드 후보 수: {len(final_df)}")
    print(f"저장 위치: {KEYWORD_CANDIDATES_PATH}")


if __name__ == "__main__":
    main()
