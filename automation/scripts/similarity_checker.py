import os
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse

import pandas as pd

from paths import DATA_DIR, OUTPUT_DIR
from topic_registry import TOPIC_USED_COLUMNS, read_csv_safe


PREVIOUS_POSTS_PATH = DATA_DIR / "previous_posts.csv"
TOPIC_USED_PATH = DATA_DIR / "topic_used.csv"

SIMILARITY_REPORT_PATH = DATA_DIR / "similarity_report_latest.csv"

_PREVIOUS_POSTS_LIMIT = int(os.getenv("BLOGAUTO_PREVIOUS_POSTS_LIMIT", "500"))

# 구조적 유사도 검사를 건너뛸 표준 유사도 하한
# 표준 유사도가 이 값보다 낮으면 내용이 충분히 달라 구조 검사가 불필요
_STRUCTURAL_SKIP_BELOW = 0.08


def normalize_text(text: str) -> str:
    text = str(text or "").lower()
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def token_set(text: str) -> set[str]:
    normalized = normalize_text(text)
    return {
        token
        for token in re.split(r"[^0-9a-zA-Z가-힣]+", normalized)
        if len(token) >= 2
    }


def sentence_set(text: str) -> set[str]:
    normalized = normalize_text(text)
    sentences = re.split(r"[.!?\n]+", normalized)
    return {sentence.strip() for sentence in sentences if len(sentence.strip()) >= 20}


def char_ngrams(text: str, size: int = 6, limit: int = 5000) -> set[str]:
    normalized = normalize_text(text).replace(" ", "")
    normalized = normalized[:limit]
    if len(normalized) < size:
        return {normalized} if normalized else set()
    return {normalized[index:index + size] for index in range(len(normalized) - size + 1)}


def _jaccard_sets(a: frozenset, b: frozenset) -> float:
    if not a or not b:
        return 0.0
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)


def jaccard(left: Iterable[str], right: Iterable[str]) -> float:
    return _jaccard_sets(frozenset(left), frozenset(right))


def _score_precomputed(
    q_tokens: frozenset,
    q_sentences: frozenset,
    q_ngrams: frozenset,
    c_tokens: frozenset,
    c_sentences: frozenset,
    c_ngrams: frozenset,
) -> float:
    """미리 계산된 집합으로 유사도 점수를 산출합니다 (텍스트 파싱 없음)."""
    token_score = _jaccard_sets(q_tokens, c_tokens)
    sentence_score = _jaccard_sets(q_sentences, c_sentences)
    char_score = _jaccard_sets(q_ngrams, c_ngrams)
    return round((token_score * 0.30) + (sentence_score * 0.35) + (char_score * 0.35), 4)


def compare_texts(left: str, right: str) -> float:
    token_score = jaccard(token_set(left), token_set(right))
    sentence_score = jaccard(sentence_set(left), sentence_set(right))
    char_score = jaccard(char_ngrams(left), char_ngrams(right))

    return round((token_score * 0.30) + (sentence_score * 0.35) + (char_score * 0.35), 4)


def _find_unique_tokens(text: str, other: str, min_count: int = 2) -> set[str]:
    """text에는 min_count 이상 등장하지만 other에는 전혀 없는 토큰을 반환합니다."""
    toks = [t for t in re.split(r"[^0-9a-zA-Z가-힣]+", normalize_text(text)) if len(t) >= 2]
    other_toks = set(re.split(r"[^0-9a-zA-Z가-힣]+", normalize_text(other)))
    freq = Counter(toks)
    return {t for t, c in freq.items() if c >= min_count and t not in other_toks}


def _find_unique_tokens_fast(
    tok_freq: Counter, other_tokens: frozenset, min_count: int = 2
) -> set[str]:
    """미리 계산된 빈도수와 집합을 이용해 고유 토큰을 빠르게 반환합니다."""
    return {t for t, c in tok_freq.items() if c >= min_count and t not in other_tokens}


def _mask_tokens(text: str, tokens: set[str]) -> str:
    """주어진 토큰 집합을 placeholder로 교체합니다."""
    result = normalize_text(text)
    for tok in sorted(tokens, key=len, reverse=True):
        result = result.replace(tok, "키")
    return result


def compare_texts_structural(left: str, right: str) -> float:
    """키워드를 제거한 후 구조적 유사도를 비교합니다."""
    unique_left = _find_unique_tokens(left, right)
    unique_right = _find_unique_tokens(right, left)

    masked_left = _mask_tokens(left, unique_left)
    masked_right = _mask_tokens(right, unique_right)

    return compare_texts(masked_left, masked_right)


def _is_home_or_listing_url(url: str) -> bool:
    parsed = urlparse(str(url or ""))
    path = (parsed.path or "").strip("/")
    if not parsed.scheme or not parsed.netloc:
        return True
    return path in {"", "index.html"} or path.endswith("sitemap.xml")


def _clean_reference_text(text: str) -> str:
    text = normalize_text(text)
    text = text.replace("더보기", " ")
    return text[:6000]


@dataclass
class SimilarityCandidate:
    source: str
    label: str
    text: str
    extra: str = ""

    def __post_init__(self):
        # 로딩 시점에 집합을 한 번만 계산 → 비교 시 재파싱 불필요
        self._tokens: frozenset = frozenset(token_set(self.text))
        self._sentences: frozenset = frozenset(sentence_set(self.text))
        self._ngrams: frozenset = frozenset(char_ngrams(self.text))


@dataclass
class SimilarityMatch:
    score: float
    candidate: SimilarityCandidate | None


def _load_previous_post_candidates(limit: int = _PREVIOUS_POSTS_LIMIT) -> list[SimilarityCandidate]:
    df = read_csv_safe(PREVIOUS_POSTS_PATH)
    if df.empty:
        return []

    # 최신 N건만 유지해 비교 대상 규모 제어
    if limit > 0 and len(df) > limit:
        df = df.tail(limit).copy()

    candidates: list[SimilarityCandidate] = []
    for _, row in df.iterrows():
        title = str(row.get("title", "")).strip()
        url = str(row.get("url", "")).strip()
        content = _clean_reference_text(str(row.get("content", "")))

        if not title or len(content) < 800:
            continue
        if _is_home_or_listing_url(url):
            continue

        label = title
        if url:
            label = f"{title} | {url}"

        candidates.append(
            SimilarityCandidate(
                source="previous_posts",
                label=label,
                text=content,
                extra=str(row.get("platform", "")).strip(),
            )
        )

    return candidates


def _load_output_candidates() -> list[SimilarityCandidate]:
    candidates: list[SimilarityCandidate] = []
    if not OUTPUT_DIR.exists():
        return candidates

    for run_dir in OUTPUT_DIR.iterdir():
        if not run_dir.is_dir():
            continue
        for txt_file in run_dir.glob("*.txt"):
            try:
                text = txt_file.read_text(encoding="utf-8")
            except Exception:
                continue

            cleaned = _clean_reference_text(text)
            if len(cleaned) < 800:
                continue

            candidates.append(
                SimilarityCandidate(
                    source="output_archive",
                    label=str(txt_file),
                    text=cleaned,
                    extra=str(run_dir.name),
                )
            )

    return candidates


def _load_topic_output_candidates() -> list[SimilarityCandidate]:
    df = read_csv_safe(TOPIC_USED_PATH, TOPIC_USED_COLUMNS)
    if df.empty or "output_path" not in df.columns:
        return []

    candidates: list[SimilarityCandidate] = []
    for _, row in df.iterrows():
        output_path = Path(str(row.get("output_path", "")).strip())
        if not output_path.exists() or output_path.suffix.lower() != ".txt":
            continue

        try:
            text = output_path.read_text(encoding="utf-8")
        except Exception:
            continue

        cleaned = _clean_reference_text(text)
        if len(cleaned) < 800:
            continue

        title = str(row.get("title", output_path.stem)).strip() or output_path.stem
        candidates.append(
            SimilarityCandidate(
                source="topic_used_output",
                label=title,
                text=cleaned,
                extra=str(output_path),
            )
        )

    return candidates


class SimilarityChecker:
    def __init__(self, threshold: float = 0.82, structural_threshold: float = 0.62):
        self.threshold = threshold
        self.structural_threshold = structural_threshold
        self.candidates: list[SimilarityCandidate] = []

    def load_defaults(self, previous_posts_limit: int = _PREVIOUS_POSTS_LIMIT) -> None:
        prev = _load_previous_post_candidates(limit=previous_posts_limit)
        print(f"[checker] previous_posts candidates: {len(prev)} (limit={previous_posts_limit})")
        self.candidates.extend(prev)
        self.candidates.extend(_load_output_candidates())
        self.candidates.extend(_load_topic_output_candidates())
        print(f"[checker] total candidates: {len(self.candidates)}")

    def add_candidate(self, source: str, label: str, text: str, extra: str = "") -> None:
        cleaned = _clean_reference_text(text)
        if len(cleaned) < 400:
            return

        self.candidates.append(
            SimilarityCandidate(
                source=source,
                label=label,
                text=cleaned,
                extra=extra,
            )
        )

    def find_best_matches(self, text: str) -> tuple[SimilarityMatch, SimilarityMatch]:
        """표준 유사도와 구조적 유사도를 단일 루프로 동시 계산합니다.

        - 쿼리 집합을 루프 전에 한 번만 계산
        - 후보 집합은 로딩 시 사전 계산된 값 사용
        - 표준 유사도가 낮은 후보는 구조적 검사 건너뜀
        """
        # 쿼리 집합 1회 계산
        q_tokens = frozenset(token_set(text))
        q_sentences = frozenset(sentence_set(text))
        q_ngrams = frozenset(char_ngrams(text))

        # 구조적 검사용 쿼리 토큰 빈도 (unique token 계산에 필요)
        q_tok_list = [t for t in re.split(r"[^0-9a-zA-Z가-힣]+", normalize_text(text)) if len(t) >= 2]
        q_tok_freq = Counter(q_tok_list)

        best_standard = SimilarityMatch(score=0.0, candidate=None)
        best_structural = SimilarityMatch(score=0.0, candidate=None)

        for candidate in self.candidates:
            # 표준 유사도: 사전 계산된 집합으로 즉시 산출
            std_score = _score_precomputed(
                q_tokens, q_sentences, q_ngrams,
                candidate._tokens, candidate._sentences, candidate._ngrams,
            )
            if std_score > best_standard.score:
                best_standard = SimilarityMatch(score=std_score, candidate=candidate)

            # 구조적 유사도: 표준 유사도가 너무 낮으면 건너뜀
            if std_score < _STRUCTURAL_SKIP_BELOW:
                continue

            unique_q = _find_unique_tokens_fast(q_tok_freq, candidate._tokens)
            unique_c = {t for t in candidate._tokens if t not in q_tokens}

            masked_q = _mask_tokens(text, unique_q)
            masked_c = _mask_tokens(candidate.text, unique_c)

            struct_score = compare_texts(masked_q, masked_c)
            if struct_score > best_structural.score:
                best_structural = SimilarityMatch(score=struct_score, candidate=candidate)

        return best_standard, best_structural



def save_similarity_report(report_rows: list[dict], destination: Path | None = None) -> Path:
    target = destination or SIMILARITY_REPORT_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(report_rows).to_csv(target, index=False, encoding="utf-8-sig")
    return target
