@echo off
setlocal DisableDelayedExpansion
pushd "%~dp0.." || exit /b 1
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -I -c "import sys;sys.exit(sys.version_info[:2] != (3,12) or sys.maxsize.bit_length() != 63)" >nul 2>&1
    if not errorlevel 1 (
        ".venv\Scripts\python.exe" -X utf8 scripts\launcher.py %1
        goto finished
    )
    echo 项目虚拟环境需要 64 位 Python 3.12。请先将 .venv 改名备份，再重新双击。
    exit /b 1
)
py -3.12 -I -c "import sys;sys.exit(sys.version_info[:2] != (3,12) or sys.maxsize.bit_length() != 63)" >nul 2>&1
if not errorlevel 1 (
    py -3.12 -X utf8 scripts\launcher.py %1
    goto finished
)
for /f "delims=" %%P in ('where python.exe 2^>nul ^| findstr /i /v "\\WindowsApps\\"') do (
    "%%P" -I -c "import sys;sys.exit(sys.version_info[:2] != (3,12) or sys.maxsize.bit_length() != 63)" >nul 2>&1
    if not errorlevel 1 (
        "%%P" -X utf8 scripts\launcher.py %1
        goto finished
    )
)
echo 请先安装 Windows 64 位 Python 3.12（含 py 启动器），再双击本文件。
echo https://www.python.org/downloads/windows/
exit /b 1
:finished
set "launch_result=%errorlevel%"
popd
exit /b %launch_result%

