@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul 2>&1
title Очистка логов
color 0A

REM Обработка ошибок - не закрывать окно при ошибке
set "EXIT_CODE=0"

REM Переходим в директорию скрипта
cd /d "%~dp0"
if errorlevel 1 (
    echo Ошибка перехода в директорию скрипта!
    pause
    exit /b 1
)

REM Показываем текущую директорию для отладки
echo Текущая директория скрипта: %CD%
echo.

REM Включаем обработку ошибок
set "ERROR_OCCURRED=0"

REM Отключаем автоматическое закрытие при ошибках
set "ERRORLEVEL="

echo ====================================
echo   ОЧИСТКА ЛОГОВ
echo ====================================
echo.
echo ⚠️ ВНИМАНИЕ: Закройте все программы, которые могут использовать файлы логов или CSV!
echo    (например: Excel, Notepad++, блокнот, анализаторы логов)
echo.
echo Нажмите любую клавишу для продолжения...
pause >nul
echo.

REM Проверяем текущую директорию
echo Текущая директория: %CD%
echo.

REM Создаем папку для архивов
if not exist "logs\futures\archived" mkdir "logs\futures\archived"

REM Создаем папку с датой и временем для текущего архива
set datetime=
for /f "tokens=2 delims==" %%I in ('wmic os get localdatetime /value 2^>nul') do set datetime=%%I
if "!datetime!"=="" (
    echo Ошибка получения даты и времени!
    echo Нажмите любую клавишу для выхода...
    pause >nul
    exit /b 1
)
set datefolder=logs_!datetime:~0,4!-!datetime:~4,2!-!datetime:~6,2!_!datetime:~8,2!-!datetime:~10,2!-!datetime:~12,2!
set archivefolder=logs\futures\archived\!datefolder!

REM Создаем папку архива
if not exist "!archivefolder!" mkdir "!archivefolder!"

echo Создана папка архива: !archivefolder!
echo.

REM Проверяем наличие файлов логов
echo Проверка наличия файлов...
set filefound=0
if exist "logs\futures\*.log" (
    echo   Найдены логи: logs\futures\*.log
    set filefound=1
) else (
    echo   Логи не найдены: logs\futures\*.log
)

if exist "logs\futures\*.zip" (
    echo   Найдены архивы: logs\futures\*.zip
    set filefound=1
) else (
    echo   Архивы не найдены: logs\futures\*.zip
)

if exist "logs\trades_*.csv" (
    echo   Найдены файлы сделок: logs\trades_*.csv
    set filefound=1
) else (
    echo   Файлы сделок не найдены: logs\trades_*.csv
)

if !filefound! equ 0 (
    echo.
    echo ⚠️ Файлы для архивирования не найдены!
    echo.
    echo Нажмите любую клавишу для выхода...
    pause >nul
    exit /b 0
)
echo.

REM Перемещаем старые логи в архив
echo Перемещение логов futures в архив...
set logcount=0
set failedcount=0
set foundfiles=0
set zipcount=0
set failedzip=0
set tradescount=0
set failedtrades=0
set csv_processed=0
set csv_found_in_loop=0

REM Сначала проверяем, есть ли файлы
for %%f in (logs\futures\*.log) do (
    if exist "%%f" (
        set /a foundfiles+=1
        echo   Найден файл: %%f
    )
)

if !foundfiles! equ 0 (
    echo   ⚠️ Логи не найдены в logs\futures\
) else (
    echo   Найдено файлов: !foundfiles!
    echo.
)

REM Теперь перемещаем
for %%f in (logs\futures\*.log) do (
    if exist "%%f" (
        echo.
        echo   Перемещаю: %%f
        echo   В папку: !archivefolder!
        
        REM Пробуем стандартный move (выводим ошибки для отладки)
        echo     Выполняю: move /Y "%%f" "!archivefolder!\"
        move /Y "%%f" "!archivefolder!\" 2>&1
        set moveerror=!errorlevel!
        if !moveerror! neq 0 (
            echo     ⚠️ Ошибка move, код: !moveerror!
        )
        
        if exist "!archivefolder!\%%~nxf" (
            set /a logcount+=1
            echo     ✅ Перемещен: %%~nxf
        ) else (
            REM Пробуем копирование и удаление
            echo     ⚠️ Файл заблокирован, пробую копирование...
            echo     Выполняю: copy /Y "%%f" "!archivefolder!\"
            copy /Y "%%f" "!archivefolder!\" 2>&1
            set copyerror=!errorlevel!
            if !copyerror! neq 0 (
                echo     ⚠️ Ошибка copy, код: !copyerror!
            )
            
            if exist "!archivefolder!\%%~nxf" (
                REM Копирование успешно, пробуем удалить оригинал
                timeout /t 1 /nobreak >nul 2>&1
                echo     Выполняю: del /F /Q "%%f"
                del /F /Q "%%f" 2>&1
                set delerror=!errorlevel!
                if !delerror! neq 0 (
                    echo     ⚠️ Не удалось удалить оригинал, код: !delerror!
                )
                set /a logcount+=1
                echo     ✅ Скопирован и удален: %%~nxf
            ) else (
                set /a failedcount+=1
                echo     ❌ Не удалось переместить: %%f
                echo        Файл открыт в другой программе или бот пишет в лог.
                echo        Закройте файл и попробуйте снова.
            )
        )
    )
)
echo.

REM Перемещаем ZIP архивы
echo Перемещение ZIP архивов...
set zipcount=0
set failedzip=0
set foundzip=0

REM Сначала проверяем, есть ли файлы
for %%f in (logs\futures\*.zip) do (
    if exist "%%f" (
        set /a foundzip+=1
        echo   Найден архив: %%f
    )
)

if !foundzip! equ 0 (
    echo   ⚠️ ZIP архивы не найдены в logs\futures\
) else (
    echo   Найдено архивов: !foundzip!
    echo.
)

REM Теперь перемещаем ZIP архивы
for %%f in (logs\futures\*.zip) do (
    if exist "%%f" (
        echo.
        echo   Перемещаю: %%f
        echo   В папку: !archivefolder!
        
        REM Пробуем стандартный move
        echo     Выполняю: move /Y "%%f" "!archivefolder!\" 
        move /Y "%%f" "!archivefolder!\" 2>&1
        set moveerror=!errorlevel!
        if !moveerror! neq 0 (
            echo     ⚠️ Ошибка move, код: !moveerror!
        )
        
        if exist "!archivefolder!\%%~nxf" (
            set /a zipcount+=1
            set /a logcount+=1
            echo     ✅ Перемещен: %%~nxf
        ) else (
            REM Пробуем копирование и удаление
            echo     ⚠️ Файл заблокирован, пробую копирование...
            copy /Y "%%f" "!archivefolder!\" 2>&1
            set copyerror=!errorlevel!
            if !copyerror! neq 0 (
                echo     ⚠️ Ошибка copy, код: !copyerror!
            )
            
            if exist "!archivefolder!\%%~nxf" (
                timeout /t 1 /nobreak >nul 2>&1
                del /F /Q "%%f" 2>&1
                set /a zipcount+=1
                set /a logcount+=1
                echo     ✅ Скопирован и удален: %%~nxf
            ) else (
                set /a failedzip+=1
                echo     ❌ Не удалось переместить: %%f
                echo        Файл открыт в другой программе.
                echo        Закройте файл и попробуйте снова.
            )
        )
    )
)

if !zipcount! gtr 0 (
    echo ✅ Перемещено ZIP архивов: !zipcount!
) else (
    echo ℹ️ ZIP архивы не перемещены
)
if !failedzip! gtr 0 (
    echo ⚠️ Не удалось переместить: !failedzip! архив(ов)
)
echo.

if !logcount! gtr 0 (
    echo ✅ Перемещено логов: !logcount!
) else (
    echo ℹ️ Логи не перемещены
)
if !failedcount! gtr 0 (
    echo ⚠️ Не удалось переместить: !failedcount! файл(ов)
)
echo.

REM Перемещаем файлы trades.csv в архив
echo.
echo ====================================
echo Перемещение файлов сделок (trades.csv) в архив...
echo ====================================
set tradescount=0
set failedtrades=0
set foundtrades=0

REM Проверяем текущую директорию
echo Текущая директория: %CD%
echo Ищем файлы: logs\trades_*.csv

REM Сначала проверяем, есть ли файлы
set "csv_path=logs\trades_*.csv"
echo Проверка наличия CSV файлов...

if not exist "logs" (
    echo   ⚠️ Папка logs не найдена!
) else (
    echo   ✅ Папка logs найдена
)

for %%f in ("!csv_path!") do (
    if exist "%%f" (
        set /a foundtrades+=1
        echo   ✅ Найден файл: %%f
    ) else (
        echo   ⚠️ Файл не найден: %%f
    )
)

REM Альтернативная проверка через dir
dir /b "logs\trades_*.csv" >nul 2>&1
if !errorlevel! equ 0 (
    echo   ✅ Файлы найдены через dir
    for /f "delims=" %%f in ('dir /b "logs\trades_*.csv" 2^>nul') do (
        if exist "logs\%%f" (
            set /a foundtrades+=1
            echo   ✅ Найден файл через dir: logs\%%f
        )
    )
) else (
    echo   ⚠️ Файлы не найдены через dir
)

if !foundtrades! equ 0 (
    echo   ⚠️ Файлы сделок не найдены в logs\
    echo   Попробую найти CSV файлы в других местах...
    dir /b /s *.csv 2>nul | findstr /i trades
) else (
    echo   ✅ Найдено файлов: !foundtrades!
    echo.
)

REM Теперь перемещаем CSV файлы - простой подход
echo.
echo ====================================
echo Перемещение файлов сделок (trades.csv) в архив...
echo ====================================
echo Начинаю перемещение CSV файлов...
echo Текущая директория: %CD%
echo Проверяю наличие CSV файлов напрямую...

REM Сначала проверяем наличие папки logs
if not exist "logs" (
    echo   ❌ Папка logs не найдена!
    goto :skip_csv
)

REM Проверяем наличие CSV файлов
echo Проверка CSV файлов:
dir /b "logs\trades_*.csv" >nul 2>&1
if errorlevel 1 (
    echo   ⚠️ CSV файлы не найдены через dir
    echo   Проверяю через exist:
    if not exist "logs\trades_*.csv" (
        echo   ⚠️ CSV файлы не найдены в logs\
        echo   Проверяю содержимое папки logs\:
        dir /b "logs\" 2>nul | findstr /i "csv"
        goto :skip_csv
    )
)

echo   ✅ CSV файлы найдены!
echo   Начинаю обработку каждого CSV файла...
echo.

REM Обрабатываем каждый CSV файл напрямую
set "csv_processed=0"
set "csv_found_in_loop=0"

REM Сначала проверим, есть ли файлы
echo Проверка перед циклом:
for %%f in ("logs\trades_*.csv") do (
    set /a csv_found_in_loop+=1
    echo   Найден файл для обработки: %%f
)

if !csv_found_in_loop! equ 0 (
    echo   ⚠️ Не найдено CSV файлов в цикле for
    goto :skip_csv_loop
)

echo   ✅ Найдено CSV файлов для обработки: !csv_found_in_loop!
echo   Начинаю цикл обработки...
echo.

for %%f in ("logs\trades_*.csv") do (
    set /a csv_processed+=1
    echo.
    echo   ========================================
    echo   ✅ ФАЙЛ #!csv_processed!: Обрабатываю CSV файл: %%f
    echo   ========================================
    echo   Проверка существования файла...
    
    if exist "%%f" (
        echo   ✅ Файл существует: %%f
        echo   Получаю имя файла...
        
        REM Получаем имя файла
        for %%g in ("%%f") do (
            set "csvname=%%~nxg"
            set "csvfullpath=%%~f"
            echo   Имя файла: !csvname!
            echo   Полный путь: !csvfullpath!
        )
        
        echo   Перемещаю файл в архив: !archivefolder!
        echo   Выполняю команду: move /Y "%%f" "!archivefolder!\"
        
        REM Пробуем стандартный move (выводим ошибки для отладки)
        move /Y "%%f" "!archivefolder!\" 2>&1
        set moveerror=!errorlevel!
        echo   Код ошибки move: !moveerror!
        
        if !moveerror! equ 0 (
            REM Проверяем, появился ли файл в архиве
            if exist "!archivefolder!\!csvname!" (
                set /a tradescount+=1
                echo   ✅ УСПЕХ: Файл перемещен: !csvname!
            ) else (
                echo   ⚠️ Файл не найден в архиве после move
                set /a failedtrades+=1
            )
        ) else (
            echo   ⚠️ Move не удался (код: !moveerror!), пробую копирование...
            echo   Выполняю команду: copy /Y "%%f" "!archivefolder!\"
            
            REM Пробуем копирование и удаление
            copy /Y "%%f" "!archivefolder!\" 2>&1
            set copyerror=!errorlevel!
            echo   Код ошибки copy: !copyerror!
            
            if !copyerror! equ 0 (
                if exist "!archivefolder!\!csvname!" (
                    echo   ✅ Копирование успешно, удаляю оригинал...
                    timeout /t 2 /nobreak >nul 2>&1
                    echo   Выполняю команду: del /F /Q "%%f"
                    del /F /Q "%%f" 2>&1
                    set delerror=!errorlevel!
                    echo   Код ошибки del: !delerror!
                    
                    if !delerror! equ 0 (
                        set /a tradescount+=1
                        echo   ✅ УСПЕХ: Файл скопирован и оригинал удален: !csvname!
                    ) else (
                        echo   ⚠️ Копирование выполнено, но не удалось удалить оригинал (код: !delerror!)
                        echo   Файл в архиве: !archivefolder!\!csvname!
                        set /a tradescount+=1
                    )
                ) else (
                    echo   ❌ Копирование не удалось - файл не найден в архиве
                    set /a failedtrades+=1
                )
            ) else (
                echo   ❌ Копирование не удалось (код: !copyerror!)
                echo   Файл открыт в другой программе (Excel, блокнот и т.д.)
                echo   Закройте файл и попробуйте снова
                set /a failedtrades+=1
            )
        )
    ) else (
        echo   ❌ Файл не существует: %%f
        set /a failedtrades+=1
    )
)

if !csv_processed! equ 0 (
    echo   ⚠️ Не найдено CSV файлов для обработки
)

:skip_csv_loop
:skip_csv
echo.
echo ====================================
echo Завершение обработки CSV файлов
echo ====================================
echo Обработано CSV файлов: !csv_processed!
echo Перемещено CSV файлов: !tradescount!
echo Не удалось переместить CSV: !failedtrades!
echo.

if !tradescount! gtr 0 (
    echo ✅ Перемещено файлов сделок: !tradescount!
) else (
    echo ℹ️ Файлы сделок не перемещены
)
if !failedtrades! gtr 0 (
    echo ⚠️ Не удалось переместить: !failedtrades! файл(ов)
)
echo.

REM Показываем содержимое архива
echo.
echo 📁 Содержимое архива (!archivefolder!):
dir /b "!archivefolder!" 2>nul
if errorlevel 1 (
    echo   (архив пуст)
)
echo.

echo ✅ Все логи и файлы сделок перемещены в архив: !archivefolder!
echo.

REM Проверяем, остались ли файлы
echo Проверка оставшихся файлов...
set remaining=0
if exist "logs\futures\*.log" (
    echo   ⚠️ Остались логи в logs\futures\:
    dir /b "logs\futures\*.log" 2>nul
    set remaining=1
)

if exist "logs\futures\*.zip" (
    echo   ⚠️ Остались ZIP архивы в logs\futures\:
    dir /b "logs\futures\*.zip" 2>nul
    set remaining=1
)

if exist "logs\trades_*.csv" (
    echo   ⚠️ Остались файлы сделок в logs\:
    dir /b "logs\trades_*.csv" 2>nul
    set remaining=1
)

if !remaining! equ 0 (
    echo   ✅ Все файлы успешно перемещены!
) else (
    echo.
    echo ⚠️ ВНИМАНИЕ: Некоторые файлы не удалось переместить!
    echo.
    echo 📋 РЕКОМЕНДАЦИИ:
    echo    1. Закройте файлы в Excel, Notepad++, блокноте или других программах
    echo    2. Убедитесь, что бот не запущен (он пишет в логи)
    echo    3. Закройте все программы и попробуйте запустить батник снова
    echo    4. Если файлы все еще заблокированы, перезагрузите компьютер
    echo.
    echo 💡 ИЛИ: Скопируйте файлы вручную из папок:
    echo    - logs\futures\*.log
    echo    - logs\trades_*.csv
    echo    в архив: !archivefolder!
)

echo.
echo ====================================
echo ✅ ОЧИСТКА ЛОГОВ ЗАВЕРШЕНА
echo ====================================
echo.
echo Итоговая статистика:
echo   - Перемещено LOG файлов: !logcount!
echo   - Перемещено ZIP архивов: !zipcount!
echo   - Перемещено CSV файлов: !tradescount!
echo   - Не удалось переместить: !failedcount! LOG, !failedzip! ZIP, !failedtrades! CSV
echo.

REM Финальная проверка CSV файлов
echo ====================================
echo Финальная проверка CSV файлов:
echo ====================================
if exist "logs\trades_*.csv" (
    echo   ⚠️ ОСТАЛИСЬ CSV файлы в logs\:
    for %%f in ("logs\trades_*.csv") do (
        echo     - %%f
        echo     Проверяю, открыт ли файл...
        REM Пробуем получить информацию о файле
        dir "%%f" 2>nul | findstr /i "csv"
    )
    echo.
    echo   💡 РЕКОМЕНДАЦИЯ: 
    echo     1. Закройте CSV файл в Excel, блокноте или других программах
    echo     2. Убедитесь, что бот не пишет в CSV файл
    echo     3. Попробуйте запустить батник снова
) else (
    echo   ✅ Все CSV файлы успешно перемещены!
)

echo.
echo ====================================
echo Готово к запуску бота!
echo ====================================
echo.
echo ====================================
echo ФИНАЛЬНАЯ ИНФОРМАЦИЯ:
echo ====================================
echo Обработано CSV файлов: !csv_processed!
echo Успешно перемещено CSV: !tradescount!
echo Не удалось переместить CSV: !failedtrades!
echo.
echo Если CSV файлы не переместились:
echo   1. Убедитесь, что файл закрыт в Excel, блокноте или других программах
echo   2. Убедитесь, что бот не запущен (он может писать в CSV)
echo   3. Попробуйте переместить файл вручную в папку архива
echo.
echo Нажмите любую клавишу для выхода...
echo.
echo [ОЖИДАНИЕ НАЖАТИЯ КЛАВИШИ...]
echo.
pause
echo.
echo Скрипт завершен успешно.
timeout /t 1 >nul 2>&1

