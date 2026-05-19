@echo off
chcp 65001 > nul

cd /d "%~dp0"
setlocal
set "HIDDEN_MODE="
if /I "%~1"=="__hidden__" set "HIDDEN_MODE=1"

set "PYTHON_CMD="
set "USE_UV="
set "BLOGAUTO_MAX_REWRITE_ATTEMPTS=2"
set "BLOGAUTO_API_MAX_ATTEMPTS=1"
set "BLOGAUTO_API_TIMEOUT_SECONDS=45"
set "BLOGAUTO_MAX_TOPICS_PER_RUN=4"
set "BLOGAUTO_INCLUDE_DRAFTED_FALLBACK=false"
set "BLOGAUTO_USE_API_ON_RETRY=false"

call :resolve_python

if not defined PYTHON_CMD if not defined USE_UV (
    echo No runnable Python or uv was found. Check your install and PATH.
    if not defined HIDDEN_MODE pause
    exit /b 1
)

if defined PYTHON_CMD (
    echo [1] Checking Python...
    "%PYTHON_CMD%" --version
    if errorlevel 1 (
        set "PYTHON_CMD="
    )
)

if not defined PYTHON_CMD if not defined USE_UV (
    echo Could not verify a runnable Python interpreter, and uv is unavailable.
    if not defined HIDDEN_MODE pause
    exit /b 1
)

echo [2] Starting Streamlit...
echo [speed] BLOGAUTO_MAX_REWRITE_ATTEMPTS=%BLOGAUTO_MAX_REWRITE_ATTEMPTS%
echo [speed] BLOGAUTO_API_MAX_ATTEMPTS=%BLOGAUTO_API_MAX_ATTEMPTS%
echo [speed] BLOGAUTO_API_TIMEOUT_SECONDS=%BLOGAUTO_API_TIMEOUT_SECONDS%
echo [speed] BLOGAUTO_MAX_TOPICS_PER_RUN=%BLOGAUTO_MAX_TOPICS_PER_RUN%
echo [speed] BLOGAUTO_INCLUDE_DRAFTED_FALLBACK=%BLOGAUTO_INCLUDE_DRAFTED_FALLBACK%
echo [speed] BLOGAUTO_USE_API_ON_RETRY=%BLOGAUTO_USE_API_ON_RETRY%
start http://localhost:8501

if defined USE_UV (
    set "UV_CACHE_DIR=%TEMP%\uv-cache-blogauto"
    uv run --python 3.14 --with streamlit --with pandas --with requests --with beautifulsoup4 --with openpyxl python -m streamlit run automation/app.py --server.headless true --browser.gatherUsageStats false
) else (
    "%PYTHON_CMD%" -m streamlit run automation/app.py --server.headless true --browser.gatherUsageStats false
)

if not defined HIDDEN_MODE pause
exit /b 0

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
