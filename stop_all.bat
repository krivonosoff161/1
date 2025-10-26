@echo off
chcp 65001 >nul
echo.
echo ========================================
echo    ОСТАНОВКА ВСЕХ PYTHON ПРОЦЕССОВ
echo ========================================
echo.
echo Остановка всех Python процессов...
taskkill /F /IM python.exe 2>nul
if %ERRORLEVEL% EQU 0 (
    echo ✅ Все Python процессы остановлены
) else (
    echo ℹ️  Python процессы не найдены
)
echo.
pause

