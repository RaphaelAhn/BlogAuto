import streamlit as st
import subprocess
import os
import sys
from pathlib import Path
from datetime import datetime


# =========================
# 기본 경로 설정
# =========================

BASE_DIR = Path(__file__).resolve().parents[1]

SCRIPTS_DIR = BASE_DIR / "automation" / "scripts"

COLLECT_SCRIPT = SCRIPTS_DIR / "collect_keywords.py"
GENERATE_SCRIPT = SCRIPTS_DIR / "run_refine_and_register.py"

TODAY = datetime.now().strftime("%Y-%m-%d")
OUTPUT_DIR = BASE_DIR / "output" / TODAY


# =========================
# 파이썬 스크립트 실행 함수
# =========================

def run_python_script(script_path: Path):
    if not script_path.exists():
        return False, f"파일을 찾을 수 없습니다:\n{script_path}"

    try:
        result = subprocess.run(
            [sys.executable, str(script_path)],
            cwd=str(BASE_DIR),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env={**os.environ, "PYTHONIOENCODING": "utf-8"}
        )

        output = ""
        if result.stdout:
            output += result.stdout
        if result.stderr:
            output += "\n" + result.stderr

        if result.returncode == 0:
            return True, output if output.strip() else "실행이 완료되었습니다."
        else:
            return False, output if output.strip() else "알 수 없는 오류가 발생했습니다."

    except Exception as e:
        return False, str(e)


# =========================
# 폴더 열기 함수
# =========================

def open_folder(folder_path: Path):
    try:
        folder_path.mkdir(parents=True, exist_ok=True)
        os.startfile(str(folder_path))
        return True, f"폴더를 열었습니다:\n{folder_path}"
    except Exception as e:
        return False, str(e)


# =========================
# Streamlit 화면 설정
# =========================

st.set_page_config(
    page_title="BlogAuto",
    page_icon="🚀",
    layout="centered"
)

st.title("🚀 BlogAuto 자동화 시스템")

st.divider()


# =========================
# 1단계: 주제 생성
# =========================

st.header("1️⃣ 주제 생성")

if st.button("주제 TOP10 생성", disabled=False):
    with st.spinner("주제 TOP10을 생성하는 중입니다..."):
        success, message = run_python_script(COLLECT_SCRIPT)

    if success:
        st.success("주제 TOP10 생성이 완료되었습니다.")
        st.code(message)
    else:
        st.error("주제 TOP10 생성 중 오류가 발생했습니다.")
        st.code(message)

st.divider()


# =========================
# 2단계: AI 글 생성
# =========================

st.header("2️⃣ AI 글 생성")

if st.button("AI 완성 글 생성", disabled=False):
    with st.spinner("AI 완성 글을 생성하는 중입니다. 시간이 조금 걸릴 수 있습니다..."):
        success, message = run_python_script(GENERATE_SCRIPT)

    if success:
        st.success("AI 완성 글 생성이 완료되었습니다.")
        st.code(message)
    else:
        st.error("AI 완성 글 생성 중 오류가 발생했습니다.")
        st.code(message)

st.divider()


# =========================
# 3단계: 결과 확인
# =========================

st.header("3️⃣ 결과 확인")

if st.button("오늘 완성 글 폴더 열기", disabled=False):
    success, message = open_folder(OUTPUT_DIR)

    if success:
        st.success(message)
    else:
        st.error("폴더 열기 중 오류가 발생했습니다.")
        st.code(message)

st.divider()


# =========================
# 사용 안내
# =========================

st.info(
    """
사용 순서

1. 주제 TOP10 생성 클릭  
2. AI 완성 글 생성 클릭  
3. 오늘 완성 글 폴더 열기로 결과 확인  

실행 파일 연결 상태

- 주제 생성: automation/scripts/collect_keywords.py
- AI 글 생성: automation/scripts/refine_drafts_ai.py
- 결과 위치: BlogAuto/output/날짜/
"""
)
