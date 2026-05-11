import os
import subprocess
import sys
from collections import deque
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from scripts.paths import OUTPUT_DIR as ROOT_OUTPUT_DIR


BASE_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = BASE_DIR / "automation" / "scripts"
PIPELINE_SCRIPT = SCRIPTS_DIR / "run_blog_pipeline.py"
TOPIC_USED_PATH = BASE_DIR / "automation" / "data" / "topic_used.csv"
LOGS_DIR = BASE_DIR / "logs" / "pipeline"

TODAY = datetime.now().strftime("%Y-%m-%d")
OUTPUT_DIR = ROOT_OUTPUT_DIR


def build_article_speed_env(use_fast_mode: bool) -> dict[str, str]:
    if not use_fast_mode:
        return {}
    return {
        "BLOGAUTO_MAX_REWRITE_ATTEMPTS": "2",
        "BLOGAUTO_API_MAX_ATTEMPTS": "1",
        "BLOGAUTO_API_TIMEOUT_SECONDS": "45",
        "BLOGAUTO_PARALLEL_WORKERS": "4",
        "BLOGAUTO_MIN_KOREAN_CHARS": "1500",
        "BLOGAUTO_PREVIOUS_POSTS_LIMIT": "300",
    }


def build_run_log_path(script_path: Path, args: tuple[str, ...]) -> Path:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    step_name = args[0] if args else script_path.stem
    safe_step_name = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in step_name)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return LOGS_DIR / f"{timestamp}_{safe_step_name}.log"


def run_python_script(script_path: Path, *args: str, extra_env: dict[str, str] | None = None):
    if not script_path.exists():
        return False, f"파일을 찾을 수 없습니다:\n{script_path}", None

    log_path = build_run_log_path(script_path, args)
    status_placeholder = st.empty()
    log_placeholder = st.empty()
    recent_lines = deque(maxlen=200)
    command = [sys.executable, "-u", str(script_path), *args]

    try:
        with log_path.open("w", encoding="utf-8") as log_file:
            log_file.write(f"[START] {datetime.now().isoformat()}\n")
            log_file.write(f"[CWD] {BASE_DIR}\n")
            log_file.write(f"[COMMAND] {' '.join(command)}\n\n")
            log_file.flush()

            process = subprocess.Popen(
                command,
                cwd=str(BASE_DIR),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                env={
                    **os.environ,
                    "PYTHONIOENCODING": "utf-8",
                    "PYTHONUNBUFFERED": "1",
                    **(extra_env or {}),
                },
                bufsize=1,
            )

            status_placeholder.info(f"실행 중입니다. 로그 파일: {log_path}")

            if process.stdout is not None:
                for line in process.stdout:
                    cleaned_line = line.rstrip()
                    recent_lines.append(cleaned_line)
                    log_file.write(line)
                    log_file.flush()
                    log_placeholder.code("\n".join(recent_lines) or "로그를 기다리는 중입니다.")

            return_code = process.wait()
            log_file.write(f"\n[END] {datetime.now().isoformat()} returncode={return_code}\n")
            log_file.flush()
    except Exception as exc:
        return False, str(exc), log_path

    output = "\n".join(recent_lines).strip() or "실행 로그가 없습니다."

    if return_code == 0:
        status_placeholder.success(f"실행이 완료되었습니다. 로그 파일: {log_path}")
        return True, output, log_path

    status_placeholder.error(f"실행 중 오류가 발생했습니다. 로그 파일: {log_path}")
    return False, output, log_path


def open_folder(folder_path: Path):
    try:
        folder_path.mkdir(parents=True, exist_ok=True)
        os.startfile(str(folder_path))
        return True, f"폴더를 열었습니다:\n{folder_path}"
    except Exception as exc:
        return False, str(exc)


def find_latest_output_run_dir(base_output_dir: Path, day_prefix: str) -> Path:
    if not base_output_dir.exists():
        return base_output_dir

    candidates = []
    prefix = f"{day_prefix}_"

    for child in base_output_dir.iterdir():
        if not child.is_dir():
            continue
        if not child.name.startswith(prefix):
            continue
        suffix = child.name[len(prefix):]
        if suffix.isdigit():
            candidates.append((int(suffix), child))

    if not candidates:
        return base_output_dir

    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def load_topic_used() -> pd.DataFrame:
    if not TOPIC_USED_PATH.exists() or TOPIC_USED_PATH.stat().st_size == 0:
        return pd.DataFrame()
    try:
        return pd.read_csv(TOPIC_USED_PATH, encoding="utf-8-sig")
    except Exception:
        return pd.DataFrame()


def save_topic_used(df: pd.DataFrame) -> None:
    tmp = TOPIC_USED_PATH.with_suffix(".tmp")
    df.to_csv(tmp, index=False, encoding="utf-8-sig")
    tmp.replace(TOPIC_USED_PATH)


def reset_drafted(keep_used: bool = True) -> dict:
    """drafted 상태 글과 관련 큐를 초기화합니다."""
    results = {}

    # topic_used.csv: drafted 행 제거 (used 유지 여부에 따라)
    df = load_topic_used()
    if not df.empty and "status" in df.columns:
        before = len(df)
        if keep_used:
            df = df[df["status"] == "used"].copy()
        else:
            df = pd.DataFrame(columns=df.columns)
        save_topic_used(df)
        results["topic_used"] = f"{before}행 → {len(df)}행"
    else:
        results["topic_used"] = "변경 없음"

    # writing_queue.csv: 헤더만 남기고 초기화
    queue_path = BASE_DIR / "automation" / "data" / "writing_queue.csv"
    if queue_path.exists():
        try:
            header_df = pd.read_csv(queue_path, nrows=0, encoding="utf-8-sig")
            header_df.to_csv(queue_path, index=False, encoding="utf-8-sig")
            results["writing_queue"] = "초기화 완료"
        except Exception as exc:
            results["writing_queue"] = f"오류: {exc}"
    else:
        results["writing_queue"] = "파일 없음"

    # topic_top10.csv: 초기화 (새 주제 선정 가능하게)
    top10_path = BASE_DIR / "automation" / "data" / "topic_top10.csv"
    if top10_path.exists():
        try:
            header_df = pd.read_csv(top10_path, nrows=0, encoding="utf-8-sig")
            header_df.to_csv(top10_path, index=False, encoding="utf-8-sig")
            results["topic_top10"] = "초기화 완료"
        except Exception as exc:
            results["topic_top10"] = f"오류: {exc}"
    else:
        results["topic_top10"] = "파일 없음"

    return results


# ── UI ──────────────────────────────────────────────────────────────────────

st.set_page_config(page_title="BlogAuto", page_icon="📝", layout="centered")

st.title("BlogAuto 자동 글 생성")
st.caption("기존 글 수집, 키워드 후보 수집, TOP 주제 선정, 완성 글 생성을 순서대로 실행합니다.")

st.divider()

fast_article_mode = st.checkbox(
    "빠른 글 생성 모드",
    value=True,
    help="완성 글 생성 단계에서 API 대기 시간을 줄이고 재시도 횟수를 낮춰 전체 시간을 단축합니다.",
)
article_env = build_article_speed_env(fast_article_mode)
if fast_article_mode:
    st.caption("빠른 모드: API 45초 1회 시도, 재작성 최대 2회, 최소 1,500자, 4개 글 병렬 생성.")

# 전체 실행
st.header("전체 자동 실행")

if st.button("전체 파이프라인 실행", type="primary"):
    with st.spinner("수집부터 글 생성까지 전체 파이프라인을 실행하는 중입니다..."):
        success, message, log_path = run_python_script(PIPELINE_SCRIPT, "all", extra_env=article_env)
    if success:
        st.success("전체 파이프라인 실행이 완료되었습니다.")
    else:
        st.error("전체 파이프라인 실행 중 오류가 발생했습니다.")
    if log_path:
        st.caption(f"실행 로그: {log_path}")
    st.code(message)

st.divider()

# 단계별 실행
st.header("단계별 실행")

col1, col2 = st.columns(2)

with col1:
    if st.button("1. 기존 글 수집"):
        with st.spinner("기존 블로그 글을 수집하는 중입니다..."):
            success, message, log_path = run_python_script(PIPELINE_SCRIPT, "crawl")
        if success:
            st.success("기존 글 수집이 완료되었습니다.")
        else:
            st.error("기존 글 수집 중 오류가 발생했습니다.")
        if log_path:
            st.caption(f"실행 로그: {log_path}")
        st.code(message)

    if st.button("3. TOP 주제 선정"):
        with st.spinner("키워드 후보에서 TOP 주제를 선정하는 중입니다..."):
            success, message, log_path = run_python_script(PIPELINE_SCRIPT, "topics")
        if success:
            st.success("TOP 주제 선정이 완료되었습니다.")
        else:
            st.error("TOP 주제 선정 중 오류가 발생했습니다.")
        if log_path:
            st.caption(f"실행 로그: {log_path}")
        st.code(message)

    if st.button("5. 완성 글 생성"):
        with st.spinner("작업 큐 기준으로 완성 글을 생성하는 중입니다. 시간이 조금 걸릴 수 있습니다..."):
            success, message, log_path = run_python_script(PIPELINE_SCRIPT, "articles", extra_env=article_env)
        if success:
            st.success("완성 글 생성이 완료되었습니다.")
        else:
            st.error("완성 글 생성 중 오류가 발생했습니다.")
        if log_path:
            st.caption(f"실행 로그: {log_path}")
        st.code(message)

with col2:
    if st.button("2. 키워드 후보 수집"):
        with st.spinner("검색 추천어 기반 키워드 후보를 수집하는 중입니다..."):
            success, message, log_path = run_python_script(PIPELINE_SCRIPT, "keywords")
        if success:
            st.success("키워드 후보 수집이 완료되었습니다.")
        else:
            st.error("키워드 후보 수집 중 오류가 발생했습니다.")
        if log_path:
            st.caption(f"실행 로그: {log_path}")
        st.code(message)

    if st.button("4. 작업 큐 생성"):
        with st.spinner("플랫폼별 작업 큐를 생성하는 중입니다..."):
            success, message, log_path = run_python_script(PIPELINE_SCRIPT, "queue")
        if success:
            st.success("작업 큐 생성이 완료되었습니다.")
        else:
            st.error("작업 큐 생성 중 오류가 발생했습니다.")
        if log_path:
            st.caption(f"실행 로그: {log_path}")
        st.code(message)

st.divider()

# 결과 확인
st.header("결과 확인")

if st.button("오늘 완성 글 폴더 열기"):
    latest_output_dir = find_latest_output_run_dir(OUTPUT_DIR, TODAY)
    success, message = open_folder(latest_output_dir)
    if success:
        st.success(message)
    else:
        st.error("폴더 열기 중 오류가 발생했습니다.")
        st.code(message)

st.divider()

# 테스트 초기화
st.header("테스트 초기화")
st.caption("테스트로 생성한 drafted 글을 지우고 처음부터 다시 생성할 수 있습니다.")

col_r1, col_r2 = st.columns(2)

with col_r1:
    if st.button("drafted 글 초기화 (used 유지)", type="secondary"):
        if "confirm_reset_partial" not in st.session_state:
            st.session_state["confirm_reset_partial"] = True
            st.rerun()

    if st.session_state.get("confirm_reset_partial"):
        st.warning("drafted 상태 글 108건과 writing_queue, topic_top10을 초기화합니다. 계속하시겠습니까?")
        col_yes, col_no = st.columns(2)
        with col_yes:
            if st.button("예, 초기화합니다", key="yes_partial"):
                results = reset_drafted(keep_used=True)
                st.session_state.pop("confirm_reset_partial", None)
                st.success("초기화 완료")
                for k, v in results.items():
                    st.write(f"• {k}: {v}")
                st.rerun()
        with col_no:
            if st.button("취소", key="no_partial"):
                st.session_state.pop("confirm_reset_partial", None)
                st.rerun()

with col_r2:
    if st.button("전체 초기화 (used 포함 삭제)", type="secondary"):
        if "confirm_reset_full" not in st.session_state:
            st.session_state["confirm_reset_full"] = True
            st.rerun()

    if st.session_state.get("confirm_reset_full"):
        st.error("used 포함 모든 기록이 삭제됩니다. 계속하시겠습니까?")
        col_yes2, col_no2 = st.columns(2)
        with col_yes2:
            if st.button("예, 전체 초기화", key="yes_full"):
                results = reset_drafted(keep_used=False)
                st.session_state.pop("confirm_reset_full", None)
                st.success("전체 초기화 완료")
                for k, v in results.items():
                    st.write(f"• {k}: {v}")
                st.rerun()
        with col_no2:
            if st.button("취소", key="no_full"):
                st.session_state.pop("confirm_reset_full", None)
                st.rerun()

st.divider()

st.info(
    """
사용 순서

1. 전체 파이프라인 실행 클릭
2. 단계별 재실행이 필요하면 원하는 단계만 다시 클릭
3. 오늘 완성 글 폴더 열기로 결과 확인

실행 흐름

1. 기존 글 수집 → collect_previous_posts.py
2. 키워드 후보 수집 → collect_keywords.py
3. TOP 주제 선정 → generate_topics.py
4. 작업 큐 생성 → build_writing_queue.py (플랫폼별 배정)
5. 완성 글 생성 → run_refine_and_register.py
 - 결과 위치: automation/output/날짜_회차/
"""
)

st.divider()

# 발행 관리
st.header("발행 관리")

topic_df = load_topic_used()

if topic_df.empty or "status" not in topic_df.columns:
    st.info("아직 생성된 글이 없습니다. 파이프라인을 실행해 주세요.")
else:
    drafted_df = topic_df[topic_df["status"] == "drafted"]
    used_df = topic_df[topic_df["status"] == "used"]

    col_m1, col_m2, col_m3 = st.columns(3)
    col_m1.metric("전체 글", len(topic_df))
    col_m2.metric("발행 대기 (drafted)", len(drafted_df))
    col_m3.metric("발행 완료 (used)", len(used_df))

    if not drafted_df.empty:
        st.subheader("발행 대기 중인 글")
        st.caption("블로그에 올린 글은 체크 후 '발행 완료로 변경' 버튼을 누르세요.")

        selected_keywords = []
        for _, row in drafted_df.iterrows():
            keyword = str(row.get("keyword", ""))
            title = str(row.get("title", keyword))
            platform = str(row.get("platform", ""))
            output_path = str(row.get("output_path", ""))
            created_at = str(row.get("created_at", ""))

            label = f"[{platform}] {title}  _(생성일: {created_at})_"
            if st.checkbox(label, key=f"pub_{keyword}"):
                selected_keywords.append(keyword)

            if output_path and output_path != "nan":
                st.caption(f"파일: {output_path}")

        if st.button("선택한 글 발행 완료로 변경", type="primary", disabled=not selected_keywords):
            norm_targets = {kw.lower().replace(" ", "") for kw in selected_keywords}
            mask = topic_df["keyword"].apply(
                lambda k: str(k).lower().replace(" ", "") in norm_targets
            )
            topic_df.loc[mask, "status"] = "used"
            save_topic_used(topic_df)
            st.success(f"{len(selected_keywords)}개 글을 발행 완료로 변경했습니다.")
            st.rerun()
    else:
        st.success("발행 대기 중인 글이 없습니다. 모두 발행 완료 상태입니다.")
