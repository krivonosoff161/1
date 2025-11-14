@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul 2>&1
title Очистка кэша - OKX Trading Bot
color 0E

echo =====================================
echo   ОЧИСТКА КЭША
echo =====================================
echo.

REM Переходим в директорию скрипта (корень проекта)
cd /d "%~dp0"
if errorlevel 1 (
    echo ❌ Ошибка перехода в директорию скрипта!
    pause
    exit /b 1
)

echo Текущая директория: %CD%
echo.

REM ============================================
REM 1. Очистка кэша данных
REM ============================================
echo [1/4] Очистка кэша данных...
set cache_cleaned=0

if exist "data\cache\" (
    echo   ✅ Папка data\cache\ найдена
    echo   Удаляю файлы из data\cache\...
    
    REM Считаем файлы перед удалением
    set file_count=0
    for %%f in ("data\cache\*.*") do (
        if exist "%%f" (
            set /a file_count+=1
        )
    )
    
    if !file_count! gtr 0 (
        echo   Найдено файлов: !file_count!
        del /Q /F "data\cache\*.*" 2>nul
        if errorlevel 1 (
            echo   ⚠️ Некоторые файлы не удалось удалить (возможно, используются ботом)
        ) else (
            set cache_cleaned=1
            echo   ✅ Файлы удалены
        )
    ) else (
        echo   ℹ️ Папка пуста
    )
    
    REM Удаляем lock файл, если есть
    if exist "data\cache\bot.lock" (
        echo   Удаляю bot.lock...
        del /Q /F "data\cache\bot.lock" 2>nul
        if errorlevel 1 (
            echo   ⚠️ Не удалось удалить bot.lock (бот может быть запущен)
        ) else (
            echo   ✅ bot.lock удален
        )
    )
) else (
    echo   ⚠️ Папка data\cache\ не найдена (создаю...)
    mkdir "data\cache\" 2>nul
    if errorlevel 1 (
        echo   ❌ Не удалось создать папку data\cache\
    ) else (
        echo   ✅ Папка data\cache\ создана
    )
)

echo.

REM ============================================
REM 2. Очистка Python __pycache__ в корне
REM ============================================
echo [2/4] Очистка Python __pycache__ в корне...
set pycache_root_cleaned=0

if exist "__pycache__" (
    echo   ✅ Найдена папка __pycache__ в корне
    echo   Удаляю __pycache__...
    rd /s /q "__pycache__" 2>nul
    if errorlevel 1 (
        echo   ⚠️ Не удалось удалить __pycache__ (возможно, используется Python)
    ) else (
        set pycache_root_cleaned=1
        echo   ✅ __pycache__ удалена
    )
) else (
    echo   ℹ️ __pycache__ в корне не найдена
)

echo.

REM ============================================
REM 3. Очистка Python __pycache__ в src и подпапках
REM ============================================
echo [3/4] Очистка Python __pycache__ в src и подпапках...
set pycache_src_cleaned=0
set pycache_count=0

REM Рекурсивно ищем и удаляем все __pycache__
for /f "delims=" %%d in ('dir /b /s /ad "__pycache__" 2^>nul') do (
    if exist "%%d" (
        set /a pycache_count+=1
        echo   Найдена: %%d
        rd /s /q "%%d" 2>nul
        if errorlevel 1 (
            echo     ⚠️ Не удалось удалить: %%d
        ) else (
            echo     ✅ Удалена: %%d
            set pycache_src_cleaned=1
        )
    )
)

if !pycache_count! equ 0 (
    echo   ℹ️ __pycache__ не найдены
) else (
    echo   ✅ Найдено и удалено папок __pycache__: !pycache_count!
)

echo.

REM ============================================
REM 4. Очистка .pyc файлов
REM ============================================
echo [4/4] Очистка .pyc файлов...
set pyc_cleaned=0
set pyc_count=0

REM Рекурсивно ищем и удаляем все .pyc файлы
for /f "delims=" %%f in ('dir /b /s "*.pyc" 2^>nul') do (
    if exist "%%f" (
        set /a pyc_count+=1
        del /Q /F "%%f" 2>nul
        if errorlevel 1 (
            echo   ⚠️ Не удалось удалить: %%f
        ) else (
            set pyc_cleaned=1
        )
    )
)

if !pyc_count! equ 0 (
    echo   ℹ️ .pyc файлы не найдены
) else (
    echo   ✅ Найдено и удалено .pyc файлов: !pyc_count!
)

echo.

REM ============================================
REM ИТОГОВАЯ СТАТИСТИКА
REM ============================================
echo =====================================
echo   ИТОГОВАЯ СТАТИСТИКА
echo =====================================
echo   Кэш данных: !cache_cleaned!
echo   __pycache__ (корень): !pycache_root_cleaned!
echo   __pycache__ (src): !pycache_src_cleaned! (!pycache_count! папок)
echo   .pyc файлы: !pyc_cleaned! (!pyc_count! файлов)
echo.

if !cache_cleaned! equ 1 (
    echo ✅ Кэш данных очищен
) else (
    echo ℹ️ Кэш данных был пуст или не удалось очистить
)

if !pycache_root_cleaned! equ 1 (
    echo ✅ __pycache__ в корне очищен
) else (
    echo ℹ️ __pycache__ в корне не найден
)

if !pycache_src_cleaned! equ 1 (
    echo ✅ __pycache__ в src очищен (!pycache_count! папок)
) else (
    echo ℹ️ __pycache__ в src не найдены
)

if !pyc_cleaned! equ 1 (
    echo ✅ .pyc файлы очищены (!pyc_count! файлов)
) else (
    echo ℹ️ .pyc файлы не найдены
)

echo.
echo =====================================
echo   ✅ ОЧИСТКА КЭША ЗАВЕРШЕНА
echo =====================================
echo.
echo Если некоторые файлы не удалось удалить:
echo   1. Убедитесь, что бот не запущен
echo   2. Закройте все Python процессы
echo   3. Попробуйте запустить батник снова
echo.
pause
