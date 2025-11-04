@echo off
chcp 65001 >nul 2>&1
title Очистка логов
color 0A

echo ====================================
echo   ОЧИСТКА ЛОГОВ
echo ====================================
echo.

REM Создаем папку для архивов
if not exist "logs\futures\archived" mkdir "logs\futures\archived"

REM Перемещаем старые логи в архив
echo Перемещение старых логов в архив...
for %%f in (logs\futures\*.log) do (
    move "%%f" "logs\futures\archived\" >nul 2>&1
)

for %%f in (logs\futures\*.zip) do (
    move "%%f" "logs\futures\archived\" >nul 2>&1
)

echo ✅ Старые логи перемещены в архив
echo.
echo Готово к запуску бота!
echo.
pause

