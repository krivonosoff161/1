@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul 2>&1
title Остановка всех Python процессов - OKX Trading Bot
color 0C

echo =====================================
echo   ОСТАНОВКА ВСЕХ PYTHON ПРОЦЕССОВ
echo =====================================
echo.
echo ⚠️ ВНИМАНИЕ: Этот батник остановит ВСЕ Python процессы!
echo    Используйте stop_bot.bat для остановки только бота.
echo.
echo Нажмите любую клавишу для продолжения...
pause >nul
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
REM 1. Удаление lock файла
REM ============================================
echo [1/3] Проверка lock файла...
if exist "data\cache\bot.lock" (
    echo   ✅ Найден lock файл: data\cache\bot.lock
    echo   Удаляю lock файл...
    del /Q /F "data\cache\bot.lock" 2>nul
    if errorlevel 1 (
        echo   ⚠️ Не удалось удалить lock файл
    ) else (
        echo   ✅ Lock файл удален
    )
) else (
    echo   ℹ️ Lock файл не найден
)

echo.

REM ============================================
REM 2. Поиск и остановка всех Python процессов
REM ============================================
echo [2/3] Поиск Python процессов...
set "python_count=0"
set "stopped=0"
set "failed=0"

REM Считаем количество Python процессов
for /f "tokens=2" %%i in ('tasklist /FI "IMAGENAME eq python.exe" /FO CSV 2^>nul ^| findstr /I "python.exe"') do (
    set /a python_count+=1
)

if !python_count! equ 0 (
    echo   ℹ️ Python процессы не найдены
    goto :show_stats
)

echo   ✅ Найдено Python процессов: !python_count!
echo   Останавливаю все Python процессы...
echo.

REM Останавливаем все python.exe процессы
taskkill /IM python.exe /F >nul 2>&1
if errorlevel 1 (
    echo   ⚠️ Не удалось остановить некоторые Python процессы
    echo   Попробуйте запустить батник от имени администратора
    set "failed=1"
) else (
    echo   ✅ Все Python процессы остановлены
    set "stopped=1"
)

REM Даем время процессам завершиться
timeout /t 2 /nobreak >nul 2>&1

REM Проверяем, остались ли процессы
set "remaining=0"
for /f "tokens=2" %%i in ('tasklist /FI "IMAGENAME eq python.exe" /FO CSV 2^>nul ^| findstr /I "python.exe"') do (
    set /a remaining+=1
)

if !remaining! gtr 0 (
    echo   ⚠️ Осталось Python процессов: !remaining!
    echo   Попробуйте запустить батник от имени администратора
) else (
    echo   ✅ Все Python процессы завершены
)

:show_stats
echo.

REM ============================================
REM 3. Итоговая статистика
REM ============================================
echo [3/3] Итоговая статистика
echo =====================================
echo   Найдено Python процессов: !python_count!
echo   Остановлено: !stopped!
echo   Осталось: !remaining!
echo.

if !stopped! equ 1 (
    echo ✅ Все Python процессы остановлены!
) else (
    if !python_count! equ 0 (
        echo ℹ️ Python процессы не найдены
    ) else (
        echo ⚠️ Не удалось остановить все процессы
        echo    Попробуйте запустить батник от имени администратора
    )
)

echo.
echo =====================================
echo   ОПЕРАЦИЯ ЗАВЕРШЕНА
echo =====================================
echo.
echo Если процессы не остановились:
echo   1. Запустите этот батник от имени администратора
echo   2. Откройте Task Manager (Диспетчер задач) и остановите вручную
echo   3. Проверьте, нет ли процессов pythonw.exe (также нужно остановить)
echo.
pause
