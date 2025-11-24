@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul 2>&1
title Остановка бота - OKX Trading Bot
color 0C

echo =====================================
echo   ОСТАНОВКА OKX TRADING BOT
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
REM 1. Удаление lock файла
REM ============================================
echo [1/3] Проверка lock файла...
if exist "data\cache\bot.lock" (
    echo   ✅ Найден lock файл: data\cache\bot.lock
    echo   Удаляю lock файл...
    del /Q /F "data\cache\bot.lock" 2>nul
    if errorlevel 1 (
        echo   ⚠️ Не удалось удалить lock файл (возможно, используется ботом)
    ) else (
        echo   ✅ Lock файл удален
    )
) else (
    echo   ℹ️ Lock файл не найден
)

echo.

REM ============================================
REM 2. Поиск и остановка процессов бота
REM ============================================
echo [2/3] Поиск процессов бота...
set "found=0"
set "stopped=0"
set "failed=0"

REM Список процессов для поиска
set "processes=run.py main_futures.py main_spot.py start.bat"

REM Используем tasklist для поиска python.exe процессов
echo   Ищу Python процессы...
for /f "tokens=2" %%i in ('tasklist /FI "IMAGENAME eq python.exe" /FO CSV 2^>nul ^| findstr /I "python.exe"') do (
    set "pid=%%i"
    set "pid=!pid:"=!"
    
    if not "!pid!"=="" (
        REM Получаем commandline процесса
        set "process_name="
        set "is_bot_process=0"
        
        for /f "tokens=*" %%c in ('wmic process where "processid=!pid!" get commandline 2^>nul') do (
            set "line=%%c"
            if not "!line!"=="" (
                REM Проверяем, содержит ли commandline процессы бота
                echo !line! | findstr /I /C:"run.py" >nul
                if !errorlevel! equ 0 set "is_bot_process=1"
                
                echo !line! | findstr /I /C:"main_futures.py" >nul
                if !errorlevel! equ 0 set "is_bot_process=1"
                
                echo !line! | findstr /I /C:"main_spot.py" >nul
                if !errorlevel! equ 0 set "is_bot_process=1"
                
                if !is_bot_process! equ 1 (
                    set "process_name=!line!"
                )
            )
        )
        
        REM Если это процесс бота - останавливаем
        if !is_bot_process! equ 1 (
            set "found=1"
            echo   ✅ Найден процесс бота: PID !pid!
            echo      Commandline: !process_name!
            echo   Останавливаю процесс...
            
            taskkill /PID !pid! /F >nul 2>&1
            if errorlevel 1 (
                echo   ⚠️ Не удалось остановить PID !pid! (требуются права администратора?)
                set /a failed+=1
            ) else (
                echo   ✅ Процесс остановлен: PID !pid!
                set /a stopped+=1
            )
            echo.
        )
    )
)

if !found! equ 0 (
    echo   ℹ️ Процессы бота не найдены
    echo   Проверяю наличие Python процессов...
    
    tasklist /FI "IMAGENAME eq python.exe" 2>nul | find /I "python.exe" >nul
    if errorlevel 1 (
        echo   ℹ️ Python процессы не найдены
    ) else (
        echo   ⚠️ Найдены Python процессы, но они не похожи на процессы бота
        echo   Используйте stop_all.bat для остановки всех Python процессов
    )
)

echo.

REM ============================================
REM 3. Итоговая статистика
REM ============================================
echo [3/3] Итоговая статистика
echo =====================================
echo   Найдено процессов: !found!
echo   Остановлено процессов: !stopped!
echo   Не удалось остановить: !failed!
echo.

if !stopped! gtr 0 (
    echo ✅ Бот остановлен успешно!
) else (
    if !found! equ 0 (
        echo ℹ️ Процессы бота не найдены
    ) else (
        echo ⚠️ Процессы найдены, но не удалось остановить
        echo    Попробуйте запустить батник от имени администратора
    )
)

echo.
echo =====================================
echo   ОПЕРАЦИЯ ЗАВЕРШЕНА
echo =====================================
echo.
echo Если бот не остановился:
echo   1. Проверьте, запущен ли бот (запустите start.bat и посмотрите процессы)
echo   2. Попробуйте запустить этот батник от имени администратора
echo   3. Используйте stop_all.bat для остановки всех Python процессов
echo   4. Проверьте Task Manager (Диспетчер задач) вручную
echo.
pause
