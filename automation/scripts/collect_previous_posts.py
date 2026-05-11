import hashlib
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from urllib.parse import urlparse

import pandas as pd
import requests
from bs4 import BeautifulSoup

from paths import DATA_DIR
from topic_registry import read_csv_safe as _read_csv_safe, build_intent_core, build_intent_detail


# ==============================
# 1. 기본 경로 설정
# ==============================

PREVIOUS_POSTS_PATH = DATA_DIR / "previous_posts.csv"
QA_USED_PATH = DATA_DIR / "qa_used.csv"
CRAWL_LOG_PATH = DATA_DIR / "crawl_run_log.csv"

CRAWL_INTERVAL_DAYS = 14


# ==============================
# 2. 블로그 설정
# ==============================

BLOGS = [
    {
        "platform": "tistory",
        "url": "https://raphaelstory777.tistory.com/",
        "rss": "https://raphaelstory777.tistory.com/rss",
        "sitemap": "https://raphaelstory777.tistory.com/sitemap.xml",
        "language": "ko",
    },
    {
        "platform": "blogspot_kr",
        "url": "https://ochosblogg.blogspot.com/",
        "rss": "https://ochosblogg.blogspot.com/feeds/posts/default?alt=rss&max-results=500",
        "sitemap": "https://ochosblogg.blogspot.com/sitemap.xml",
        "language": "ko",
    },
    {
        "platform": "blogspot_en",
        "url": "https://raphaelscomsatstation.blogspot.com/",
        "rss": "https://raphaelscomsatstation.blogspot.com/feeds/posts/default?alt=rss&max-results=500",
        "sitemap": "https://raphaelscomsatstation.blogspot.com/sitemap.xml",
        "language": "en",
    },
    {
        "platform": "naver",
        "url": "https://blog.naver.com/wlss7",
        "rss": "https://rss.blog.naver.com/wlss7.xml",
        "sitemap": "",
        "language": "ko",
    },
]


# ==============================
# 3. CSV 컬럼
# ==============================

PREVIOUS_COLUMNS = [
    "platform",
    "title",
    "url",
    "content",
    "qa_questions",
    "keywords",
    "intent_core",
    "intent_detail",
    "language",
    "created_at",
]

QA_COLUMNS = [
    "platform",
    "post_title",
    "question",
    "question_hash",
    "intent_core",
    "created_at",
]

LOG_COLUMNS = [
    "platform",
    "last_run_at",
    "collected_count",
    "new_count",
    "status",
    "message",
]


# ==============================
# 4. CSV 안전 읽기
# ==============================

def read_csv_safe(path, columns):
    return _read_csv_safe(path, columns)


# ==============================
# 5. 14일 실행 제한
# ==============================

def can_run_platform(platform):
    log_df = read_csv_safe(CRAWL_LOG_PATH, LOG_COLUMNS)

    if log_df.empty:
        return True

    platform_logs = log_df[log_df["platform"] == platform]

    if platform_logs.empty:
        return True

    last_run_at = platform_logs.iloc[-1]["last_run_at"]

    try:
        last_run_dt = datetime.strptime(last_run_at, "%Y-%m-%d %H:%M:%S")
    except Exception:
        return True

    diff = datetime.now() - last_run_dt

    if diff < timedelta(days=CRAWL_INTERVAL_DAYS):
        remain = timedelta(days=CRAWL_INTERVAL_DAYS) - diff

        print(f"[{platform}] 최근 {CRAWL_INTERVAL_DAYS}일 안에 이미 수집했습니다.")
        print(f"[{platform}] 남은 대기 시간: {remain}")

        return False

    return True


# ==============================
# 6. 실행 로그 저장
# ==============================

def save_crawl_log(platform, collected_count, new_count, status, message):
    log_df = read_csv_safe(CRAWL_LOG_PATH, LOG_COLUMNS)

    new_log = pd.DataFrame([{
        "platform": platform,
        "last_run_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "collected_count": collected_count,
        "new_count": new_count,
        "status": status,
        "message": message,
    }], columns=LOG_COLUMNS)

    final_log_df = pd.concat([log_df, new_log], ignore_index=True)
    final_log_df.to_csv(CRAWL_LOG_PATH, index=False, encoding="utf-8-sig")


# ==============================
# 7. HTML / XML 가져오기
# ==============================

def fetch(url, retries=3):
    headers = {"User-Agent": "Mozilla/5.0"}

    for attempt in range(1, retries + 1):
        try:
            response = requests.get(url, headers=headers, timeout=20)
            response.raise_for_status()
            return response.text
        except Exception as e:
            if attempt == retries:
                print(f"[수집 실패] {url} ({attempt}회 시도 후 포기)")
                print(e)
            # 마지막 시도가 아니면 조용히 재시도
    return ""


# ==============================
# 8. 텍스트 정리
# ==============================

def clean_text(text):
    text = str(text)
    text = re.sub(r"\r", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def clean_html_to_text(html):
    soup = BeautifulSoup(html, "html.parser")

    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    text = soup.get_text("\n", strip=True)
    return clean_text(text)


# ==============================
# 9. 실제 글 URL 판별
# ==============================

def is_real_post_url(platform, url):
    parsed = urlparse(url)
    path = parsed.path.strip("/")

    if platform == "tistory":
        bad_words = ["category", "tag", "guestbook", "manage", "notice", "rss", "page"]

        if any(word in url.lower() for word in bad_words):
            return False

        if not path.isdigit():
            return False

        return True

    if platform in ["blogspot_kr", "blogspot_en"]:
        if ".html" not in url:
            return False

        bad_words = ["/search", "/label", "archive", "comment"]

        if any(word in url.lower() for word in bad_words):
            return False

        return True

    if platform == "naver":
        return "blog.naver.com" in url

    return True


# ==============================
# 10. RSS 수집
# ==============================

def collect_from_rss(blog):
    rss_url = blog["rss"]
    platform = blog["platform"]

    if not rss_url:
        return []

    xml = fetch(rss_url)

    if not xml:
        return []

    soup = BeautifulSoup(xml, "xml")
    posts = []

    for item in soup.find_all("item"):
        title_tag = item.find("title")
        link_tag = item.find("link")
        desc_tag = item.find("description")

        if not title_tag or not link_tag:
            continue

        title = title_tag.get_text(strip=True)
        url = link_tag.get_text(strip=True)
        content_hint = desc_tag.get_text() if desc_tag else ""

        if not is_real_post_url(platform, url):
            continue

        posts.append({
            "title": title,
            "url": url,
            "content_hint": content_hint,
        })

    for entry in soup.find_all("entry"):
        title_tag = entry.find("title")
        link_tag = entry.find("link", rel="alternate")

        if not title_tag or not link_tag:
            continue

        title = title_tag.get_text(strip=True)
        url = link_tag.get("href", "")

        content_tag = entry.find("content") or entry.find("summary")
        content_hint = content_tag.get_text() if content_tag else ""

        if not is_real_post_url(platform, url):
            continue

        posts.append({
            "title": title,
            "url": url,
            "content_hint": content_hint,
        })

    return posts


# ==============================
# 11. Sitemap 수집
# ==============================

def collect_from_sitemap(blog):
    sitemap_url = blog["sitemap"]
    platform = blog["platform"]

    if not sitemap_url:
        return []

    xml = fetch(sitemap_url)

    if not xml:
        return []

    soup = BeautifulSoup(xml, "xml")
    locs = [loc.get_text(strip=True) for loc in soup.find_all("loc")]

    posts = []

    for loc in locs:
        if loc.endswith(".xml"):
            child_xml = fetch(loc)

            if not child_xml:
                continue

            child_soup = BeautifulSoup(child_xml, "xml")
            child_locs = [x.get_text(strip=True) for x in child_soup.find_all("loc")]

            for child_loc in child_locs:
                if is_real_post_url(platform, child_loc):
                    posts.append({
                        "title": "",
                        "url": child_loc,
                        "content_hint": "",
                    })

        else:
            if is_real_post_url(platform, loc):
                posts.append({
                    "title": "",
                    "url": loc,
                    "content_hint": "",
                })

    return posts


# ==============================
# 12. RSS + Sitemap 병합
# ==============================

def merge_posts(rss_posts, sitemap_posts):
    merged = []
    seen_urls = set()

    for post in rss_posts + sitemap_posts:
        url = post.get("url", "")

        if not url:
            continue

        if url in seen_urls:
            continue

        merged.append(post)
        seen_urls.add(url)

    return merged


# ==============================
# 13. 제목 / 본문 수집
# ==============================

def get_title_from_page(url):
    html = fetch(url)

    if not html:
        return ""

    soup = BeautifulSoup(html, "html.parser")

    og_title = soup.find("meta", property="og:title")
    if og_title and og_title.get("content"):
        return og_title["content"].strip()

    title = soup.find("title")
    if title:
        return title.get_text(strip=True)

    return ""


def get_content_from_page(url, platform, content_hint=""):
    if platform == "naver":
        return clean_html_to_text(content_hint)

    html = fetch(url)

    if not html:
        return clean_html_to_text(content_hint)

    soup = BeautifulSoup(html, "html.parser")

    selectors = [
        ".tt_article_useless_p_margin",
        ".article-view",
        ".contents_style",
        ".entry-content",
        ".post-body",
        "article",
    ]

    for selector in selectors:
        target = soup.select_one(selector)

        if target:
            return clean_html_to_text(str(target))

    if content_hint:
        return clean_html_to_text(content_hint)

    return clean_html_to_text(html)


# ==============================
# 14. Q&A 추출
# ==============================

def extract_questions(content):
    questions = []
    lines = content.split("\n")

    for line in lines:
        line = line.strip()

        if not line:
            continue

        is_question = False

        if re.match(r"^(Q\d+|Q\.|질문|문\d+)", line):
            is_question = True

        if "?" in line and len(line) <= 160:
            is_question = True

        if is_question:
            questions.append(line)

    return questions


def hash_question(question):
    normalized = question.lower().replace(" ", "")
    return hashlib.md5(normalized.encode("utf-8")).hexdigest()


# ==============================
# 15. 글 수집 실행 단위
# ==============================

def _fetch_post(post, platform):
    title = post.get("title", "")
    url = post.get("url", "")
    content_hint = post.get("content_hint", "")

    if not title:
        title = get_title_from_page(url)
    if not title:
        title = "제목 없음"

    content = get_content_from_page(url, platform, content_hint)
    return title, url, content


# ==============================
# 16. intent / keyword 생성
# ==============================

def make_intent_core(title):
    return build_intent_core(title)


def make_intent_detail(title):
    return build_intent_detail(title, "")


def extract_keywords(title):
    return ",".join(str(title).split()[:5])


# ==============================
# 16. 신규 글 / 신규 Q&A 필터링
# ==============================

def filter_new_posts(platform, new_posts_df, previous_df):
    if new_posts_df.empty:
        return new_posts_df

    existing_urls = set(
        previous_df[
            previous_df["platform"] == platform
        ]["url"].dropna().astype(str)
    )

    return new_posts_df[
        ~new_posts_df["url"].astype(str).isin(existing_urls)
    ]


def filter_new_qas(new_qas_df, qa_df):
    if new_qas_df.empty:
        return new_qas_df

    existing_hashes = set(
        qa_df["question_hash"].dropna().astype(str)
    )

    return new_qas_df[
        ~new_qas_df["question_hash"].astype(str).isin(existing_hashes)
    ]


# ==============================
# 17. 메인 실행
# ==============================

def main():
    print("전체 블로그 기존 글 수집 시작")
    print(f"기존 글 크롤링 제한: 플랫폼별 {CRAWL_INTERVAL_DAYS}일 1회")

    previous_df = read_csv_safe(PREVIOUS_POSTS_PATH, PREVIOUS_COLUMNS)
    qa_df = read_csv_safe(QA_USED_PATH, QA_COLUMNS)

    all_new_posts = []
    all_new_qas = []

    for blog in BLOGS:
        platform = blog["platform"]
        language = blog["language"]

        print(f"\n[{platform}] 수집 시작")

        if not can_run_platform(platform):
            save_crawl_log(
                platform=platform,
                collected_count=0,
                new_count=0,
                status="skipped",
                message=f"{CRAWL_INTERVAL_DAYS}일 이내 실행 기록이 있어 건너뜀",
            )
            continue

        rss_posts = collect_from_rss(blog)
        sitemap_posts = collect_from_sitemap(blog)
        posts = merge_posts(rss_posts, sitemap_posts)

        print(f"[{platform}] RSS 글 수: {len(rss_posts)}")
        print(f"[{platform}] Sitemap 글 수: {len(sitemap_posts)}")
        print(f"[{platform}] 최종 수집 후보: {len(posts)}")

        if len(posts) == 0:
            save_crawl_log(
                platform=platform,
                collected_count=0,
                new_count=0,
                status="empty",
                message="수집 후보가 0개라 저장하지 않음",
            )
            continue

        platform_posts = []
        platform_qas = []
        today = datetime.now().strftime("%Y-%m-%d")

        with ThreadPoolExecutor(max_workers=8) as executor:
            future_to_post = {executor.submit(_fetch_post, post, platform): post for post in posts}
            for index, future in enumerate(as_completed(future_to_post), start=1):
                title, url, content = future.result()
                print(f"{index}. {title}")

                questions = extract_questions(content)
                intent_core = make_intent_core(title)
                intent_detail = make_intent_detail(title)

                platform_posts.append({
                    "platform": platform,
                    "title": title,
                    "url": url,
                    "content": content,
                    "qa_questions": " | ".join(questions),
                    "keywords": extract_keywords(title),
                    "intent_core": intent_core,
                    "intent_detail": intent_detail,
                    "language": language,
                    "created_at": today,
                })

                for question in questions:
                    platform_qas.append({
                        "platform": platform,
                        "post_title": title,
                        "question": question,
                        "question_hash": hash_question(question),
                        "intent_core": intent_core,
                        "created_at": today,
                    })

        platform_posts_df = pd.DataFrame(platform_posts, columns=PREVIOUS_COLUMNS)
        platform_qas_df = pd.DataFrame(platform_qas, columns=QA_COLUMNS)

        new_only_posts_df = filter_new_posts(platform, platform_posts_df, previous_df)
        new_only_qas_df = filter_new_qas(platform_qas_df, qa_df)

        print(f"[{platform}] 새로 추가될 글 수: {len(new_only_posts_df)}")
        print(f"[{platform}] 새로 추가될 Q&A 수: {len(new_only_qas_df)}")

        save_crawl_log(
            platform=platform,
            collected_count=len(posts),
            new_count=len(new_only_posts_df),
            status="success",
            message="수집 완료",
        )

        if not new_only_posts_df.empty:
            all_new_posts.append(new_only_posts_df)

        if not new_only_qas_df.empty:
            all_new_qas.append(new_only_qas_df)

    if all_new_posts:
        add_posts_df = pd.concat(all_new_posts, ignore_index=True)
        previous_df = pd.concat([previous_df, add_posts_df], ignore_index=True)
        previous_df = previous_df.drop_duplicates(subset=["platform", "url"])

    if all_new_qas:
        add_qas_df = pd.concat(all_new_qas, ignore_index=True)
        qa_df = pd.concat([qa_df, add_qas_df], ignore_index=True)
        qa_df = qa_df.drop_duplicates(subset=["question_hash"])

    for df, path in [(previous_df, PREVIOUS_POSTS_PATH), (qa_df, QA_USED_PATH)]:
        tmp_path = path.with_suffix(".tmp")
        try:
            df.to_csv(tmp_path, index=False, encoding="utf-8-sig")
            tmp_path.replace(path)
        except Exception as e:
            print(f"[오류] {path.name} 저장 실패: {e}")
            if tmp_path.exists():
                tmp_path.unlink()
            raise

    print("\n전체 블로그 기존 글 수집 완료")
    print(f"previous_posts.csv 전체 글 수: {len(previous_df)}")
    print(f"qa_used.csv 전체 질문 수: {len(qa_df)}")
    print(f"실행 로그 저장 위치: {CRAWL_LOG_PATH}")


if __name__ == "__main__":
    main()
