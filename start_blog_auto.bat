@echo off
chcp 65001 > nul

cd /d "%~dp0"

set "PYTHON_CMD="
set "USE_UV="

where py > nul 2> nul
if not errorlevel 1 set "PYTHON_CMD=py"

if "%PYTHON_CMD%"=="" (
    where python > nul 2> nul
    if not errorlevel 1 set "PYTHON_CMD=python"
)

if not "%PYTHON_CMD%"=="" (
    echo [1] Python 확인 중...
    %PYTHON_CMD% --version
    if %errorlevel% neq 0 (
        set "PYTHON_CMD="
    )
)

if "%PYTHON_CMD%"=="" (
    where uv > nul 2> nul
    if not errorlevel 1 set "USE_UV=1"
)

if "%PYTHON_CMD%"=="" if "%USE_UV%"=="" (
    echo Python 또는 uv를 찾을 수 없습니다. Python 설치와 PATH 설정을 확인해 주세요.
    pause
    exit /b 1
)

echo [2] Streamlit 실행 중...
start http://localhost:8501

if "%USE_UV%"=="1" (
    set "UV_CACHE_DIR=%CD%\.uv-cache"
    uv run --python 3.14 --with streamlit --with pandas --with requests --with beautifulsoup4 python -m streamlit run automation/app.py
) else (
    %PYTHON_CMD% -m streamlit run automation/app.py
)

pause
