@echo off
chcp 65001 >nul 2>&1
title Clear Cache - OKX Trading Bot
color 0E

echo =====================================
echo   OCHISTKA KESHA
echo =====================================
echo.

REM Change to script directory (project root)
cd /d "%~dp0"

echo Ochishchayu kesh...
if exist "data\cache\" (
    del /Q "data\cache\*.*" 2>nul
    if exist "data\cache\bot.lock" (
        del /Q "data\cache\bot.lock" 2>nul
    )
    echo [OK] Kesh ochishchen!
) else (
    echo [WARNING] Papka cache ne naydena
)

REM Also clean Python cache
echo Ochishchayu Python cache...
if exist "__pycache__" (
    for /d /r . %%d in (__pycache__) do @if exist "%%d" rd /s /q "%%d" 2>nul
)

if exist "src\__pycache__" (
    for /d /r "src" %%d in (__pycache__) do @if exist "%%d" rd /s /q "%%d" 2>nul
)

echo [OK] Python cache ochishchen!

echo.
echo =====================================
echo Gotovo! Kesh ochishchen.
echo.
pause

