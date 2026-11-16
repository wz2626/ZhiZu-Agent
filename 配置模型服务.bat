@echo off
setlocal
chcp 65001 >nul
call "%~dp0scripts\bootstrap.cmd" configure
if errorlevel 1 (
    pause
    exit /b 1
)
exit /b 0

