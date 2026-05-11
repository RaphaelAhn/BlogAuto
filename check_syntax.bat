@echo off
chcp 65001 > nul

cd /d "%~dp0"
setlocal

set "PYTHON_CMD="
set "USE_UV="

call :resolve_python

if defined PYTHON_CMD (
    echo [1] Using Python: "%PYTHON_CMD%"
    "%PYTHON_CMD%" -m py_compile ^
        automation\app.py ^
        automation\streamlit_launcher.py ^
        automation\scripts\paths.py ^
        automation\scripts\topic_registry.py ^
        automation\scripts\collect_previous_posts.py ^
        automation\scripts\collect_keywords.py ^
        automation\scripts\generate_topics.py ^
        automation\scripts\build_writing_queue.py ^
        automation\scripts\refine_drafts_ai.py ^
        automation\scripts\run_refine_and_register.py ^
        automation\scripts\run_blog_pipeline.py
    exit /b %errorlevel%
)

if defined USE_UV (
    echo [1] Using uv-managed Python
    set "UV_CACHE_DIR=%CD%\.uv-cache"
    uv run --python 3.14 python -m py_compile ^
        automation\app.py ^
        automation\streamlit_launcher.py ^
        automation\scripts\paths.py ^
        automation\scripts\topic_registry.py ^
        automation\scripts\collect_previous_posts.py ^
        automation\scripts\collect_keywords.py ^
        automation\scripts\generate_topics.py ^
        automation\scripts\build_writing_queue.py ^
        automation\scripts\refine_drafts_ai.py ^
        automation\scripts\run_refine_and_register.py ^
        automation\scripts\run_blog_pipeline.py
    exit /b %errorlevel%
)

echo No runnable Python or uv was found.
exit /b 1

:resolve_python
if exist "%~dp0.venv\Scripts\python.exe" (
    set "PYTHON_CMD=%~dp0.venv\Scripts\python.exe"
    exit /b 0
)

if exist "%~dp0..\.venv\Scripts\python.exe" (
    set "PYTHON_CMD=%~dp0..\.venv\Scripts\python.exe"
    exit /b 0
)

for /f "delims=" %%I in ('where py 2^>nul') do (
    call :try_python "%%~fI"
    if defined PYTHON_CMD exit /b 0
)

for /f "delims=" %%I in ('where python 2^>nul') do (
    call :try_python "%%~fI"
    if defined PYTHON_CMD exit /b 0
)

for /f "delims=" %%I in ('where uv 2^>nul') do (
    set "USE_UV=1"
    exit /b 0
)

exit /b 0

:try_python
set "CANDIDATE=%~1"
echo %CANDIDATE% | find /I "WindowsApps" > nul
if not errorlevel 1 exit /b 0

if exist "%CANDIDATE%" (
    set "PYTHON_CMD=%CANDIDATE%"
)
exit /b 0
