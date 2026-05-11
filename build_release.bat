@echo off
chcp 65001 > nul

cd /d "%~dp0"
setlocal

set "PYTHON_CMD="
set "USE_UV="
set "WORK_DIR=%CD%\build\pyinstaller"
set "DIST_DIR=%CD%\dist"
set "APP_DIR=%DIST_DIR%\BlogAuto"

call :resolve_python

if not defined PYTHON_CMD if not defined USE_UV (
    echo No runnable Python or uv was found. Check your install and PATH.
    pause
    exit /b 1
)

tasklist /FI "IMAGENAME eq BlogAuto.exe" 2>nul | find /I "BlogAuto.exe" >nul
if not errorlevel 1 (
    echo.
    echo [경고] BlogAuto.exe가 현재 실행 중입니다.
    echo 빌드하려면 앱을 먼저 종료해야 합니다.
    echo.
    choice /C YN /M "지금 강제 종료하고 빌드를 계속할까요?"
    if errorlevel 2 (
        echo 빌드를 취소합니다.
        pause
        exit /b 1
    )
    taskkill /F /IM BlogAuto.exe >nul 2>&1
    echo BlogAuto.exe 종료 완료.
    timeout /t 1 /nobreak >nul
)

if not exist "%WORK_DIR%" mkdir "%WORK_DIR%"
if not exist "%DIST_DIR%" mkdir "%DIST_DIR%"

echo [1] Release build starting...
echo Work path: %WORK_DIR%
echo Dist path: %DIST_DIR%

if defined PYTHON_CMD (
    "%PYTHON_CMD%" -m PyInstaller --clean --noconfirm --workpath "%WORK_DIR%" --distpath "%DIST_DIR%" app_onedir.spec
) else (
    set "UV_CACHE_DIR=%CD%\.uv-cache"
    uv run --python 3.14 --with pyinstaller --with streamlit --with pandas --with requests --with beautifulsoup4 --with lxml python -m PyInstaller --clean --noconfirm --workpath "%WORK_DIR%" --distpath "%DIST_DIR%" app_onedir.spec
)

if errorlevel 1 (
    echo [ERROR] Release build failed.
    pause
    exit /b 1
)

echo [2] Release build complete.
echo Output: %APP_DIR%
pause
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
