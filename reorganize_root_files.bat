@echo off
chcp 65001 >nul
echo ========================================
echo   ROOT PROJECT FILES REORGANIZATION
echo ========================================
echo.
echo Запускаю Python скрипт...
echo.

python reorganize_root_files.py

echo.
echo Нажмите любую клавишу для выхода...
pause >nul


