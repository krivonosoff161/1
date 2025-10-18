@echo off
chcp 65001 >nul 2>&1
title Clear Cache - OKX Trading Bot
color 0E

echo =====================================
echo   ОЧИСТКА КЭША
echo =====================================
echo.

REM Change to project directory
cd /d "%~dp0"

echo Очищаю кэш...
if exist "data\cache\" (
    del /Q "data\cache\*.*" 2>nul
    echo ✅ Кэш очищен!
) else (
    echo ⚠️ Папка cache не найдена
)

echo.
echo =====================================
timeout /t 2 >nul

