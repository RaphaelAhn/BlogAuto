import os
import re
import json
import requests
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from urllib.parse import quote

from paths import DATA_DIR
from topic_registry import load_existing_texts, normalize, read_csv_safe

ALLOWED_CATEGORIES_PATH = DATA_DIR / "allowed_categories.csv"
KEYWORD_CANDIDATES_PATH = DATA_DIR / "keyword_candidates.csv"
PREVIOUS_POSTS_PATH = DATA_DIR / "previous_posts.csv"
QA_USED_PATH = DATA_DIR / "qa_used.csv"
TOPIC_USED_PATH = DATA_DIR / "topic_used.csv"

PERPLEXITY_API_KEY = os.getenv("PERPLEXITY_API_KEY")
if not PERPLEXITY_API_KEY:
    print("[경고] PERPLEXITY_API_KEY 환경변수가 설정되지 않았습니다. Perplexity 수집을 건너뜁니다.")


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
        # 교육과정/취업준비 — 검색량 낮고 수익성 낮음
        "양성과정",
        "커리큘럼",
        "수료",
        "부트캠프",
        "bootcamp",
        "취업 준비",
        "취준",
        "코딩테스트",
        "코딩 테스트",
        "면접 준비",
        "면접 질문",
        "신입 개발자",
        "교육과정",
        "학원",
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


def call_perplexity_questions(category, seed, existing_texts=None):
    if not PERPLEXITY_API_KEY:
        return []

    if existing_texts:
        existing_list = "\n".join(f"- {t}" for t in list(existing_texts)[:20])
    else:
        existing_list = "(없음)"

    prompt = f"""당신은 트래픽 중심 SEO 주제 설계 전문 에이전트입니다.

[카테고리]
{category}

[기준 키워드]
{seed}

[이미 존재하는 글 목록 — 핵심 검색 의도가 겹치면 무조건 제외]
{existing_list}

새 주제를 15개 생성하세요.

**핵심 목표: 실제 검색량이 많은 키워드 우선**
- 대상 독자: 도구를 실제로 사용하는 일반 직장인, 학생, 콘텐츠 제작자
- 우선 유형: 오류 해결, 사용 방법, 설정 팁, 도구 비교, 업무 자동화, 빠른 활용법
- 반드시 제외: 교육과정, 양성과정, 커리큘럼, 부트캠프, 취업준비, 코딩테스트, 면접준비 관련 주제

생성 규칙:
1. 각 주제는 아래 3축 중 최소 2축이 기존 글과 달라야 합니다.
   - 상황(Situation): 사용자가 처한 맥락 (예: 처음 설치, 공유 직전, 업무 중 오류)
   - 문제(Problem): 사용자가 겪는 구체적 증상 (예: 저장 실패, 동기화 안됨, 권한 오류)
   - 목적(Purpose): 사용자가 원하는 결과 (예: 빠른 해결, 재발 방지, 설정 최적화)
2. 기존 글과 핵심 검색 의도가 1%라도 겹치면 즉시 제외합니다.
3. 같은 기능이어도 상황이 다르면 별도 주제로 허용합니다.
4. 같은 문제여도 사용 환경이 다르면 별도 주제로 허용합니다.

반드시 아래 JSON 배열만 출력하세요. 설명 문장 금지.

[
  {{
    "keyword": "검색 키워드",
    "situation": "상황 한 줄",
    "problem": "문제 한 줄",
    "purpose": "목적 한 줄",
    "why_different": "기존 글과 다른 이유 한 줄"
  }}
]"""

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
        "https://api.perplexity.ai/chat/completions",
        "https://api.perplexity.ai/v1/sonar",
    ]

    for endpoint in endpoints:
        for attempt in range(1, 3):
            try:
                response = requests.post(
                    endpoint,
                    headers=headers,
                    json=body,
                    timeout=60,
                )

                if response.status_code != 200:
                    break

                data = response.json()
                text = data["choices"][0]["message"]["content"]

                match = re.search(r"\[.*?\]", text, re.DOTALL)

                if not match:
                    return []

                parsed = json.loads(match.group(0))

                if not isinstance(parsed, list):
                    return []

                results = []
                for item in parsed:
                    if isinstance(item, dict) and "keyword" in item:
                        results.append({
                            "keyword": str(item.get("keyword", "")).strip(),
                            "why_different": str(item.get("why_different", "")).strip(),
                        })
                    elif isinstance(item, str) and item.strip():
                        results.append({"keyword": item.strip(), "why_different": ""})
                return results

            except Exception:
                if attempt == 2:
                    break
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

    # 트래픽 최대화: 비교/추천은 검색량 높은 패턴
    if any(x in keyword for x in ["차이", "비교", "vs", "추천", "단점", "장점"]):
        score += 10

    # 교육/취업 주제 감점 (필터 통과 시 점수 하락)
    if any(x in keyword for x in ["양성과정", "커리큘럼", "수료", "부트캠프", "취업준비", "코딩테스트", "면접"]):
        score -= 60

    return min(max(score, 0), 100)


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


def fetch_suggestions(seed_word_pair):
    seed, word = seed_word_pair
    query = f"{seed} {word}"
    return get_google_suggestions(query), get_naver_suggestions(query)


def collect_keywords():
    categories = load_categories()
    existing_texts = load_existing_texts()

    rows = []
    blocked_duplicate_count = 0
    blocked_quality_count = 0

    for category in categories:
        seeds = SEED_KEYWORDS.get(category, [category])

        print(f"\n[{category}] 키워드 수집 시작")

        queries = [(seed, word) for seed in seeds for word in EXPAND_WORDS]

        with ThreadPoolExecutor(max_workers=10) as executor:
            future_to_query = {executor.submit(fetch_suggestions, pair): pair for pair in queries}
            for future in as_completed(future_to_query):
                google_items, naver_items = future.result()
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

        representative_seed = seeds[0] if seeds else category
        perplexity_items = call_perplexity_questions(category, representative_seed, existing_texts)

        for item in perplexity_items:
            keyword = str(item.get("keyword", "")).strip()
            why_different = str(item.get("why_different", "")).strip()

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
                "reason": why_different or make_reason(keyword),
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
