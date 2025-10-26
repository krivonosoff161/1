@echo off
chcp 65001 >nul
title Trading Bot Launcher

echo.
echo ╔══════════════════════════════════════════════════════════════╗
echo ║                    🚀 TRADING BOT LAUNCHER 🚀                ║
echo ║                                                              ║
echo ║  Windows Launcher для торгового бота                        ║
echo ║  Поддерживает Spot и Futures торговлю                       ║
echo ╚══════════════════════════════════════════════════════════════╝
echo.

REM Проверка наличия Python
python --version >nul 2>&1
if errorlevel 1 (
    echo ❌ Python не найден в системе!
    echo 💡 Установите Python 3.8+ и добавьте его в PATH
    echo 💡 Скачать можно с https://python.org
    pause
    exit /b 1
)

REM Проверка наличия виртуального окружения
if exist "venv\Scripts\activate.bat" (
    echo ✅ Виртуальное окружение найдено
    echo 🔄 Активация виртуального окружения...
    call venv\Scripts\activate.bat
) else (
    echo ⚠️  Виртуальное окружение не найдено
    echo 💡 Рекомендуется создать виртуальное окружение:
    echo    python -m venv venv
    echo    venv\Scripts\activate
    echo    pip install -r requirements.txt
    echo.
    echo Продолжить без виртуального окружения? (y/n)
    set /p choice=
    if /i "%choice%" neq "y" (
        echo 👋 Запуск отменен
        pause
        exit /b 0
    )
)

REM Проверка зависимостей
echo 🔍 Проверка зависимостей...
python -c "import loguru, aiohttp, pydantic" >nul 2>&1
if errorlevel 1 (
    echo ❌ Не все зависимости установлены!
    echo 💡 Установите зависимости: pip install -r requirements.txt
    pause
    exit /b 1
)

REM Проверка конфигурационных файлов
echo 🔍 Проверка конфигурации...
if not exist "config\config_spot.yaml" (
    echo ❌ Конфигурационный файл config\config_spot.yaml не найден!
    echo 💡 Создайте файл конфигурации для Spot торговли
    pause
    exit /b 1
)

if not exist "config\config_futures.yaml" (
    echo ❌ Конфигурационный файл config\config_futures.yaml не найден!
    echo 💡 Создайте файл конфигурации для Futures торговли
    pause
    exit /b 1
)

echo ✅ Конфигурационные файлы найдены

REM Создание папок для логов
if not exist "logs\spot" mkdir "logs\spot"
if not exist "logs\futures" mkdir "logs\futures"

echo.
echo Выберите режим торговли:
echo 1. Spot Trading (Спот торговля)
echo 2. Futures Trading (Фьючерсная торговля)
echo 3. Интерактивный режим
echo 4. Проверка конфигурации
echo 5. Выход
echo.

:menu
set /p choice="Введите номер (1-5): "

if "%choice%"=="1" goto spot_mode
if "%choice%"=="2" goto futures_mode
if "%choice%"=="3" goto interactive_mode
if "%choice%"=="4" goto check_config
if "%choice%"=="5" goto exit
echo ❌ Неверный выбор. Попробуйте снова.
goto menu

:spot_mode
echo.
echo ╔══════════════════════════════════════════════════════════════╗
echo ║                    📈 SPOT TRADING MODE 📈                  ║
echo ║                                                              ║
echo ║  Особенности Spot торговли:                                  ║
echo ║  • Торговля без левериджа (1:1)                             ║
echo ║  • Более низкие риски                                       ║
echo ║  • Подходит для начинающих                                  ║
echo ║  • Меньшая волатильность PnL                                ║
echo ╚══════════════════════════════════════════════════════════════╝
echo.
set /p confirm="Продолжить с Spot торговлей? (y/n): "
if /i "%confirm%" neq "y" goto menu

echo 🚀 Запуск Spot торгового бота...
python src\main_spot.py
goto end

:futures_mode
echo.
echo ╔══════════════════════════════════════════════════════════════╗
echo ║                   ⚡ FUTURES TRADING MODE ⚡                 ║
echo ║                                                              ║
echo ║  Особенности Futures торговли:                               ║
echo ║  • Торговля с левериджем (3x по умолчанию)                  ║
echo ║  • Высокие риски и потенциальная доходность                 ║
echo ║  • Требует опыт в торговле                                  ║
echo ║  • Защита от ликвидации                                     ║
echo ║                                                              ║
echo ║  ⚠️  КРИТИЧЕСКИ ВАЖНО:                                      ║
echo ║     • Настройте правильные пороги маржи                     ║
echo ║     • Используйте sandbox для тестирования                   ║
echo ║     • Начните с минимальных сумм                            ║
echo ╚══════════════════════════════════════════════════════════════╝
echo.
echo ⚠️  ВНИМАНИЕ: Futures торговля связана с высокими рисками!
set /p confirm="Вы уверены, что хотите продолжить? (y/n): "
if /i "%confirm%" neq "y" goto menu

echo 🚀 Запуск Futures торгового бота...
python src\main_futures.py
goto end

:interactive_mode
echo 🚀 Запуск в интерактивном режиме...
python run.py --interactive
goto end

:check_config
echo 🔍 Проверка конфигурации...
python run.py --check-config
echo.
pause
goto menu

:exit
echo 👋 До свидания!
goto end

:end
echo.
echo ✅ Торговый бот остановлен
echo 📊 Логи сохранены в папке logs\
echo.
pause