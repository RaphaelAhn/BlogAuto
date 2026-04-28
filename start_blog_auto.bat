@echo off
chcp 65001 > nul

cd /d "%~dp0"

echo [1] Python 확인 중...
python --version
if %errorlevel% neq 0 (
    echo Python이 설치되지 않았거나 PATH 설정이 안되어 있습니다.
    pause
    exit
)

echo [2] Streamlit 실행 중...
start http://localhost:8501
python -m streamlit run automation/app.py

pause