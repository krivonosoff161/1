@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul 2>&1
title ТЕСТ Очистка логов
color 0A

echo ====================================
echo   ТЕСТ ОЧИСТКИ ЛОГОВ
echo ====================================
echo.
echo Текущая директория: %CD%
echo.
echo Проверка файлов...
echo.

REM Проверяем файлы
set filefound=0
dir /b "logs\futures\*.log" >nul 2>&1 && (
    echo [OK] Найдены LOG файлы
    set filefound=1
) || echo [НЕТ] LOG файлов не найдено

dir /b "logs\futures\*.zip" >nul 2>&1 && (
    echo [OK] Найдены ZIP файлы
    set filefound=1
) || echo [НЕТ] ZIP файлов не найдено

dir /b "logs\futures\debug\*.csv" >nul 2>&1 && (
    echo [OK] Найдены DEBUG CSV файлы
    set filefound=1
) || echo [НЕТ] DEBUG CSV файлов не найдено

dir /b "logs\trades_*.csv" >nul 2>&1 && (
    echo [OK] Найдены TRADE CSV файлы
    set filefound=1
) || echo [НЕТ] TRADE CSV файлов не найдено

dir /b "logs\trades_*.json" >nul 2>&1 && (
    echo [OK] Найдены JSON файлы
    set filefound=1
) || echo [НЕТ] JSON файлов не найдено

echo.
echo filefound = !filefound!
echo.

if !filefound! equ 0 (
    echo WARNING: Файлов для архивации не найдено!
) else (
    echo OK: Найдены файлы для архивации
)

echo.
echo Press any key to exit...
pause

