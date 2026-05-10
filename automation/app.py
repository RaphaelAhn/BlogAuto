import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import streamlit as st


BASE_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = BASE_DIR / "automation" / "scripts"

PIPELINE_SCRIPT = SCRIPTS_DIR / "run_blog_pipeline.py"

TODAY = datetime.now().strftime("%Y-%m-%d")
OUTPUT_DIR = BASE_DIR / "automation" / "output" / TODAY


def run_python_script(script_path: Path, *args: str):
    if not script_path.exists():
        return False, f"파일을 찾을 수 없습니다:\n{script_path}"

    try:
        result = subprocess.run(
            [sys.executable, str(script_path), *args],
            cwd=str(BASE_DIR),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
    except Exception as exc:
        return False, str(exc)

    output = ""
    if result.stdout:
        output += result.stdout
    if result.stderr:
        output += "\n" + result.stderr

    if result.returncode == 0:
        return True, output.strip() or "실행이 완료되었습니다."

    return False, output.strip() or "알 수 없는 오류가 발생했습니다."


def open_folder(folder_path: Path):
    try:
        folder_path.mkdir(parents=True, exist_ok=True)
        os.startfile(str(folder_path))
        return True, f"폴더를 열었습니다:\n{folder_path}"
    except Exception as exc:
        return False, str(exc)


st.set_page_config(page_title="BlogAuto", page_icon="📝", layout="centered")

st.title("BlogAuto 자동 글 생성")
st.caption("기존 글 수집, 키워드 후보 수집, TOP 주제 선정, 완성 글 생성을 순서대로 실행합니다.")

st.divider()

st.header("전체 자동 실행")

if st.button("전체 파이프라인 실행", type="primary", disabled=False):
    with st.spinner("수집부터 글 생성까지 전체 파이프라인을 실행하는 중입니다..."):
        success, message = run_python_script(PIPELINE_SCRIPT, "all")

    if success:
        st.success("전체 파이프라인 실행이 완료되었습니다.")
    else:
        st.error("전체 파이프라인 실행 중 오류가 발생했습니다.")
    st.code(message)

st.divider()

st.header("단계별 실행")

col1, col2 = st.columns(2)

with col1:
    if st.button("1. 기존 글 수집", disabled=False):
        with st.spinner("기존 블로그 글을 수집하는 중입니다..."):
            success, message = run_python_script(PIPELINE_SCRIPT, "crawl")

        if success:
            st.success("기존 글 수집이 완료되었습니다.")
        else:
            st.error("기존 글 수집 중 오류가 발생했습니다.")
        st.code(message)

    if st.button("3. TOP 주제 선정", disabled=False):
        with st.spinner("키워드 후보에서 TOP 주제를 선정하는 중입니다..."):
            success, message = run_python_script(PIPELINE_SCRIPT, "topics")

        if success:
            st.success("TOP 주제 선정이 완료되었습니다.")
        else:
            st.error("TOP 주제 선정 중 오류가 발생했습니다.")
        st.code(message)

with col2:
    if st.button("2. 키워드 후보 수집", disabled=False):
        with st.spinner("검색 추천어 기반 키워드 후보를 수집하는 중입니다..."):
            success, message = run_python_script(PIPELINE_SCRIPT, "keywords")

        if success:
            st.success("키워드 후보 수집이 완료되었습니다.")
        else:
            st.error("키워드 후보 수집 중 오류가 발생했습니다.")
        st.code(message)

    if st.button("4. 완성 글 생성", disabled=False):
        with st.spinner("TOP 주제로 완성 글을 생성하는 중입니다. 시간이 조금 걸릴 수 있습니다..."):
            success, message = run_python_script(PIPELINE_SCRIPT, "articles")

        if success:
            st.success("완성 글 생성이 완료되었습니다.")
        else:
            st.error("완성 글 생성 중 오류가 발생했습니다.")
        st.code(message)

st.divider()

st.header("결과 확인")

if st.button("오늘 완성 글 폴더 열기", disabled=False):
    success, message = open_folder(OUTPUT_DIR)

    if success:
        st.success(message)
    else:
        st.error("폴더 열기 중 오류가 발생했습니다.")
        st.code(message)

st.divider()

st.info(
    """
사용 순서

1. 전체 파이프라인 실행 클릭
2. 단계별 재실행이 필요하면 원하는 단계만 다시 클릭
3. 오늘 완성 글 폴더 열기로 결과 확인

실행 흐름

- 파이프라인: automation/scripts/run_blog_pipeline.py
- 기존 글 수집: automation/scripts/collect_previous_posts.py
- 키워드 후보 수집: automation/scripts/collect_keywords.py
- TOP 주제 선정: automation/scripts/generate_topics.py
- 완성 글 생성: automation/scripts/run_refine_and_register.py
- 결과 위치: automation/output/날짜/
"""
)
