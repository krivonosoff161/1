@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul 2>&1
title Реструктуризация проекта
color 0A

echo ====================================
echo   РЕСТРУКТУРИЗАЦИЯ ПРОЕКТА
echo ====================================
echo.

REM Создаем структуру папок
echo Создание структуры папок...
if not exist "docs\analysis\logs" mkdir "docs\analysis\logs"
if not exist "docs\analysis\problems" mkdir "docs\analysis\problems"
if not exist "docs\analysis\fixes" mkdir "docs\analysis\fixes"
if not exist "docs\analysis\plans" mkdir "docs\analysis\plans"
if not exist "docs\analysis\current" mkdir "docs\analysis\current"
if not exist "docs\analysis\reports" mkdir "docs\analysis\reports"
if not exist "docs\analysis\other" mkdir "docs\analysis\other"
if not exist "temp\tmp" mkdir "temp\tmp"
echo ✅ Структура папок создана
echo.

REM Перемещаем анализы логов
echo Перемещение анализов логов...
move /Y "АНАЛИЗ_ЛОГОВ_07_11_2025.md" "docs\analysis\logs\" >nul 2>&1
move /Y "АНАЛИЗ_ЛОГОВ_11_11_2025.md" "docs\analysis\logs\" >nul 2>&1
move /Y "АНАЛИЗ_ЛОГОВ_ЗА_ПЕРИОД_11-14_НОЯБРЯ.md" "docs\analysis\logs\" >nul 2>&1
move /Y "АНАЛИЗ_ЛОГОВ_ПОСЛЕ_ЗАПУСКА_12_11.md" "docs\analysis\logs\" >nul 2>&1
move /Y "АНАЛИЗ_ЛОГОВ_ПОСЛЕ_ИСПРАВЛЕНИЙ_TP.md" "docs\analysis\logs\" >nul 2>&1
move /Y "АНАЛИЗ_ЛОГОВ_ПОСЛЕ_ИСПРАВЛЕНИЯ.md" "docs\analysis\logs\" >nul 2>&1
move /Y "АНАЛИЗ_ЛОГОВ_ПОСЛЕ_МОДЕРНИЗАЦИИ.md" "docs\analysis\logs\" >nul 2>&1
move /Y "АНАЛИЗ_СЕССИИ_10_11_2025.md" "docs\analysis\logs\" >nul 2>&1
move /Y "ИТОГОВЫЙ_АНАЛИЗ_ЛОГОВ_11_11_2025.md" "docs\analysis\logs\" >nul 2>&1
move /Y "ИТОГОВЫЙ_АНАЛИЗ_ЛОГОВ_ПОСЛЕ_ИСПРАВЛЕНИЙ.md" "docs\analysis\logs\" >nul 2>&1
move /Y "ИТОГОВЫЙ_АНАЛИЗ_ЛОГОВ_ПОСЛЕ_ИСПРАВЛЕНИЯ.md" "docs\analysis\logs\" >nul 2>&1
move /Y "КРАТКАЯ_СВОДКА_АНАЛИЗА_ЛОГОВ.md" "docs\analysis\logs\" >nul 2>&1
echo ✅ Анализы логов перемещены
echo.

REM Перемещаем анализы проблем
echo Перемещение анализов проблем...
move /Y "АНАЛИЗ_ПРОБЛЕМЫ_LEVERAGE.md" "docs\analysis\problems\" >nul 2>&1
move /Y "АНАЛИЗ_ПРОБЛЕМЫ_LEVERAGE_И_РЕЖИМОВ.md" "docs\analysis\problems\" >nul 2>&1
move /Y "АНАЛИЗ_ПРОБЛЕМЫ_ЗАКРЫТИЯ_ПОЗИЦИИ.md" "docs\analysis\problems\" >nul 2>&1
move /Y "АНАЛИЗ_ПРОБЛЕМЫ_ЗАКРЫТИЯ_С_МИНУСОМ.md" "docs\analysis\problems\" >nul 2>&1
move /Y "АНАЛИЗ_ПРОБЛЕМЫ_ЛИМИТНЫХ_ОРДЕРОВ.md" "docs\analysis\problems\" >nul 2>&1
move /Y "АНАЛИЗ_ПРОБЛЕМЫ_МАЛОЙ_МАРЖИ_АНАЛИЗ.md" "docs\analysis\problems\" >nul 2>&1
move /Y "АНАЛИЗ_ПРОБЛЕМЫ_НАПРАВЛЕНИЯ_ПОЗИЦИЙ.md" "docs\analysis\problems\" >nul 2>&1
move /Y "АНАЛИЗ_РАСХОЖДЕНИЙ_ЛОГИ_РЕАЛЬНОСТЬ.md" "docs\analysis\problems\" >nul 2>&1
move /Y "ДЕТАЛЬНЫЙ_РАЗБОР_ПРОБЛЕМ_БЕЗ_КОДА.md" "docs\analysis\problems\" >nul 2>&1
move /Y "ИТОГОВЫЙ_АНАЛИЗ_ПРОБЛЕМ_БЕЗ_КОДА.md" "docs\analysis\problems\" >nul 2>&1
move /Y "ПОДРОБНЫЙ_РАЗБОР_ПРОБЛЕМ_БЕЗ_КОДИНГА.md" "docs\analysis\problems\" >nul 2>&1
move /Y "ПОЛНЫЙ_АНАЛИЗ_ПРОБЛЕМ_ПО_РЕАЛЬНЫМ_СДЕЛКАМ.md" "docs\analysis\problems\" >nul 2>&1
move /Y "ПРОБЛЕМА_LEVERAGE_3X_В_SANDBOX.md" "docs\analysis\problems\" >nul 2>&1
move /Y "ПРОБЛЕМА_ЛИМИТОВ_ЦЕНЫ_OKX.md" "docs\analysis\problems\" >nul 2>&1
move /Y "ПРОБЛЕМА_МАЛОЙ_МАРЖИ_АНАЛИЗ.md" "docs\analysis\problems\" >nul 2>&1
move /Y "УТОЧНЕННЫЙ_АНАЛИЗ_ПРОБЛЕМ.md" "docs\analysis\problems\" >nul 2>&1
move /Y "КРАТКАЯ_СВОДКА_ПРОБЛЕМ.md" "docs\analysis\problems\" >nul 2>&1
echo ✅ Анализы проблем перемещены
echo.

REM Перемещаем отчеты об исправлениях
echo Перемещение отчетов об исправлениях...
move /Y "АНАЛИЗ_И_ИСПРАВЛЕНИЕ_ОШИБОК.md" "docs\analysis\fixes\" >nul 2>&1
move /Y "АНАЛИЗ_И_РЕАЛИЗАЦИЯ_PER_SYMBOL_TP.md" "docs\analysis\fixes\" >nul 2>&1
move /Y "ИСПРАВЛЕНИЕ_LEVERAGE_ИЗ_ПОЗИЦИИ.md" "docs\analysis\fixes\" >nul 2>&1
move /Y "ИСПРАВЛЕНИЕ_LEVERAGE_И_РАЗМЕРА_ПОЗИЦИЙ.md" "docs\analysis\fixes\" >nul 2>&1
move /Y "ИСПРАВЛЕНИЕ_LEVERAGE_SANDBOX.md" "docs\analysis\fixes\" >nul 2>&1
move /Y "ИСПРАВЛЕНИЕ_МАЛОЙ_МАРЖИ.md" "docs\analysis\fixes\" >nul 2>&1
move /Y "ИСПРАВЛЕНИЕ_ПРОБЛЕМЫ_ЛИМИТОВ_ЦЕНЫ.md" "docs\analysis\fixes\" >nul 2>&1
move /Y "ИСПРАВЛЕНИЕ_RATE_LIMIT_429.md" "docs\analysis\fixes\" >nul 2>&1
move /Y "ИСПРАВЛЕНИЕ_ЗАХАРДКОЖЕННЫХ_ПАРАМЕТРОВ_MAXSIZELIMITER.md" "docs\analysis\fixes\" >nul 2>&1
move /Y "ИСПРАВЛЕНИЕ_ЛОГИКИ_SHORT.md" "docs\analysis\fixes\" >nul 2>&1
move /Y "ИСПРАВЛЕНИЕ_СИНХРОНИЗАЦИИ_ПОЗИЦИЙ.md" "docs\analysis\fixes\" >nul 2>&1
move /Y "ИТОГОВОЕ_ИСПРАВЛЕНИЕ_LEVERAGE.md" "docs\analysis\fixes\" >nul 2>&1
move /Y "ИТОГОВЫЕ_ИСПРАВЛЕНИЯ_ОКРУГЛЕНИЯ_ПОЗИЦИЙ.md" "docs\analysis\fixes\" >nul 2>&1
move /Y "ИТОГОВЫЕ_ИСПРАВЛЕНИЯ_ПОЗИЦИИ_И_PNL.md" "docs\analysis\fixes\" >nul 2>&1
move /Y "ИТОГОВЫЕ_ИСПРАВЛЕНИЯ_TP_И_ТРЕЙЛИНГА.md" "docs\analysis\fixes\" >nul 2>&1
move /Y "РЕШЕНИЕ_LEVERAGE_3X.md" "docs\analysis\fixes\" >nul 2>&1
move /Y "РЕШЕНИЕ_ПРОБЛЕМ_TP_И_ТРЕЙЛИНГА.md" "docs\analysis\fixes\" >nul 2>&1
move /Y "РЕШЕНИЕ_ПРОБЛЕМЫ_МАЛОЙ_МАРЖИ.md" "docs\analysis\fixes\" >nul 2>&1
move /Y "ФИНАЛЬНОЕ_РЕШЕНИЕ_ПРОБЛЕМ_TP_И_ТРЕЙЛИНГА.md" "docs\analysis\fixes\" >nul 2>&1
move /Y "ФИНАЛЬНЫЙ_ОТЧЕТ_ИСПРАВЛЕНИЯ_SHORT.md" "docs\analysis\fixes\" >nul 2>&1
echo ✅ Отчеты об исправлениях перемещены
echo.

REM Перемещаем планы улучшений
echo Перемещение планов улучшений...
move /Y "ВАРИАНТ_B_ДЕТАЛЬНЫЙ_ПЛАН.md" "docs\analysis\plans\" >nul 2>&1
move /Y "ВАРИАНТ_B_РЕАЛИЗОВАН.md" "docs\analysis\plans\" >nul 2>&1
move /Y "ИТОГОВОЕ_ПРЕДЛОЖЕНИЕ_БАЛАНС.md" "docs\analysis\plans\" >nul 2>&1
move /Y "ИТОГОВОЕ_РЕШЕНИЕ_ПРОБЛЕМ_ВЫСОКОЧАСТОТНЫЙ_СКАЛЬПИНГ.md" "docs\analysis\plans\" >nul 2>&1
move /Y "ИТОГОВОЕ_РЕШЕНИЕ_ПРОБЛЕМ_TP_И_ТРЕЙЛИНГА.md" "docs\analysis\plans\" >nul 2>&1
move /Y "ИТОГОВЫЙ_ПЛАН_АДАПТИВНЫХ_ПАРАМЕТРОВ.md" "docs\analysis\plans\" >nul 2>&1
move /Y "ИТОГОВЫЙ_ПЛАН_МОДЕРНИЗАЦИИ.md" "docs\analysis\plans\" >nul 2>&1
move /Y "ОБЪЕДИНЕННЫЙ_ПЛАН_УЛУЧШЕНИЙ.md" "docs\analysis\plans\" >nul 2>&1
move /Y "ПЛАН_АДАПТИВНЫХ_ПАРАМЕТРОВ_РИСКА.md" "docs\analysis\plans\" >nul 2>&1
move /Y "ПЛАН_ВНЕДРЕНИЯ_ЧАСТОТНОГО_СКАЛЬПИНГА.md" "docs\analysis\plans\" >nul 2>&1
move /Y "ПЛАН_МОДЕРНИЗАЦИИ_БАЛАНСА.md" "docs\analysis\plans\" >nul 2>&1
move /Y "ПЛАН_МОДЕРНИЗАЦИИ_БОТА_ПОЛНЫЙ.md" "docs\analysis\plans\" >nul 2>&1
move /Y "ПЛАН_УВЕЛИЧЕНИЯ_ПРИБЫЛЬНОСТИ_СКАЛЬПИНГА.md" "docs\analysis\plans\" >nul 2>&1
move /Y "ФИНАЛЬНЫЙ_ПЛАН_ВНЕДРЕНИЯ.md" "docs\analysis\plans\" >nul 2>&1
move /Y "ФИНАЛЬНЫЙ_ПЛАН_УЛУЧШЕНИЙ_С_ЛИМИТНЫМИ_ОРДЕРАМИ.md" "docs\analysis\plans\" >nul 2>&1
echo ✅ Планы улучшений перемещены
echo.

REM Перемещаем текущие анализы
echo Перемещение текущих анализов...
move /Y "ГЛУБОКИЙ_АНАЛИЗ_ПАРАМЕТРОВ_И_ФИЛЬТРОВ.md" "docs\analysis\current\" >nul 2>&1
move /Y "PHASE_1_ИЗМЕНЕНИЯ_ПРИМЕНЕНЫ.md" "docs\analysis\current\" >nul 2>&1
move /Y "АНАЛИЗ_СТАТЬИ_MOMENTUM_TRADING.md" "docs\analysis\current\" >nul 2>&1
move /Y "АНАЛИЗ_ЛОГИКИ_ЛИМИТНЫХ_ОРДЕРОВ.md" "docs\analysis\current\" >nul 2>&1
move /Y "АНАЛИЗ_ЛОГИКИ_SHORT_И_LONG.md" "docs\analysis\current\" >nul 2>&1
move /Y "АНАЛИЗ_TP_И_TRAILING_SL_ПО_РЕЖИМАМ.md" "docs\analysis\current\" >nul 2>&1
move /Y "АНАЛИЗ_АДАПТИВНОСТИ_TP_И_TRAILING_SL.md" "docs\analysis\current\" >nul 2>&1
move /Y "АНАЛИЗ_БЛОКИРОВОК_ПОЛНЫЙ.md" "docs\analysis\current\" >nul 2>&1
move /Y "АНАЛИЗ_ПРИМЕНЕНИЯ_ИЗМЕНЕНИЙ_КО_ВСЕМ_ПАРАМ.md" "docs\analysis\current\" >nul 2>&1
move /Y "АНАЛИЗ_СТРАТЕГИИ_И_РЕКОМЕНДАЦИИ.md" "docs\analysis\current\" >nul 2>&1
move /Y "АНАЛИЗ_ЦЕПОЧКИ_ОРДЕРОВ_И_ОКРУГЛЕНИЯ.md" "docs\analysis\current\" >nul 2>&1
move /Y "ПОЛНЫЙ_АНАЛИЗ_И_ПЛАН_УЛУЧШЕНИЙ.md" "docs\analysis\current\" >nul 2>&1
move /Y "ПОЛНЫЙ_АНАЛИЗ_ЦЕПОЧКИ_ОРДЕРОВ.md" "docs\analysis\current\" >nul 2>&1
echo ✅ Текущие анализы перемещены
echo.

REM Перемещаем отчеты и проверки
echo Перемещение отчетов и проверок...
move /Y "ИТОГОВАЯ_ПРОВЕРКА_ГОТОВНОСТИ.md" "docs\analysis\reports\" >nul 2>&1
move /Y "ИТОГОВАЯ_ПРОВЕРКА_ПАРАМЕТРОВ_ИЗ_КОНФИГА.md" "docs\analysis\reports\" >nul 2>&1
move /Y "ИТОГОВАЯ_СВОДКА_ЗАДАЧ_МОДЕРНИЗАЦИИ.md" "docs\analysis\reports\" >nul 2>&1
move /Y "ИТОГОВЫЙ_ОТЧЕТ_ИСПРАВЛЕНИЙ.md" "docs\analysis\reports\" >nul 2>&1
move /Y "ИТОГОВЫЙ_ОТЧЕТ_ИСПРАВЛЕНИЙ_ЛИМИТОВ_И_НАПРАВЛЕНИЯ.md" "docs\analysis\reports\" >nul 2>&1
move /Y "ИТОГОВЫЙ_ОТЧЕТ_ИСПРАВЛЕНИЯ_ЛИМИТОВ.md" "docs\analysis\reports\" >nul 2>&1
move /Y "ИТОГОВЫЙ_ОТЧЕТ_МОДЕРНИЗАЦИИ.md" "docs\analysis\reports\" >nul 2>&1
move /Y "ИТОГОВЫЙ_ОТЧЕТ_ПРОВЕРКИ_НАПРАВЛЕНИЯ_И_РАЗМЕРА.md" "docs\analysis\reports\" >nul 2>&1
move /Y "ИТОГОВЫЙ_СТАТУС_PER_REGIME_TP.md" "docs\analysis\reports\" >nul 2>&1
move /Y "ИТОГОВЫЙ_СТАТУС_ВАРИАНТ_B.md" "docs\analysis\reports\" >nul 2>&1
move /Y "КРАТКАЯ_СВОДКА_26_ЗАДАЧ.md" "docs\analysis\reports\" >nul 2>&1
move /Y "ПОЛНАЯ_ПРОВЕРКА_ПАРАМЕТРОВ_ИЗ_КОНФИГА.md" "docs\analysis\reports\" >nul 2>&1
move /Y "ПРОВЕРКА_КОД_И_КОНФИГ.md" "docs\analysis\reports\" >nul 2>&1
move /Y "ПРОВЕРКА_ЛИМИТОВ_БИРЖИ_OKX.md" "docs\analysis\reports\" >nul 2>&1
move /Y "ПРОВЕРКА_НАПРАВЛЕНИЯ_ПОЗИЦИЙ_И_РАЗМЕРА.md" "docs\analysis\reports\" >nul 2>&1
move /Y "ПРОВЕРКА_ПАРАМЕТРОВ_ИЗ_КОНФИГА.md" "docs\analysis\reports\" >nul 2>&1
move /Y "ПРОВЕРКА_ЧТЕНИЯ_ПАРАМЕТРОВ.md" "docs\analysis\reports\" >nul 2>&1
move /Y "ФИНАЛЬНАЯ_ПРОВЕРКА_ПАРАМЕТРОВ.md" "docs\analysis\reports\" >nul 2>&1
move /Y "СТАТУС_БОТА_ГОТОВ_К_РАБОТЕ.md" "docs\analysis\reports\" >nul 2>&1
move /Y "СТАТУС_ВАРИАНТ_B.md" "docs\analysis\reports\" >nul 2>&1
echo ✅ Отчеты и проверки перемещены
echo.

REM Перемещаем прочие документы
echo Перемещение прочих документов...
move /Y "ОБЪЯСНЕНИЕ_ПРЕДУПРЕЖДЕНИЙ.md" "docs\analysis\other\" >nul 2>&1
move /Y "ОБЪЯСНЕНИЕ_ПРОБЛЕМ_И_РЕШЕНИЯ.md" "docs\analysis\other\" >nul 2>&1
move /Y "ОБСУЖДЕНИЕ_ОПТИМИЗАЦИИ_БАЛАНСА.md" "docs\analysis\other\" >nul 2>&1
move /Y "РАСЧЕТ_ОПТИМИЗАЦИИ_БАЛАНСА.md" "docs\analysis\other\" >nul 2>&1
move /Y "СВОДКА_ИЗМЕНЕНИЙ_ЧАСТОТНЫЙ_СКАЛЬПИНГ.md" "docs\analysis\other\" >nul 2>&1
move /Y "СПИСОК_ИЗМЕНЕНИЙ_ПРОСТЫМИ_СЛОВАМИ.md" "docs\analysis\other\" >nul 2>&1
move /Y "УТОЧНЕНИЯ_И_ПЛАН_ИСПРАВЛЕНИЙ.md" "docs\analysis\other\" >nul 2>&1
move /Y "УТОЧНЕНИЯ_ПО_ОРДЕРАМ_И_КОМИССИЯМ.md" "docs\analysis\other\" >nul 2>&1
move /Y "ИЗМЕНЕНИЯ_ОПТИМИЗАЦИИ_БАЛАНСА.md" "docs\analysis\other\" >nul 2>&1
move /Y "ПОЛНЫЙ_АУДИТ_БОТА_12_11.md" "docs\analysis\other\" >nul 2>&1
move /Y "ПОЛНЫЙ_АУДИТ_ЗАХАРДКОЖЕННЫХ_ПАРАМЕТРОВ.md" "docs\analysis\other\" >nul 2>&1
move /Y "ПОЛНЫЙ_СПИСОК_ЗАХАРДКОЖЕННЫХ_ПАРАМЕТРОВ.md" "docs\analysis\other\" >nul 2>&1
move /Y "СИМУЛЯЦИЯ_И_АНАЛИЗ_УЛУЧШЕНИЙ.md" "docs\analysis\other\" >nul 2>&1
move /Y "АНАЛИЗ_СИМУЛЯЦИИ_УЛУЧШЕНИЙ.md" "docs\analysis\other\" >nul 2>&1
move /Y "ФИНАЛЬНЫЙ_ОТВЕТ_PER_REGIME_TP_И_TRAILING_SL.md" "docs\analysis\other\" >nul 2>&1
move /Y "STRENGTH_CALCULATIONS_FIX.md" "docs\analysis\other\" >nul 2>&1
echo ✅ Прочие документы перемещены
echo.

REM Перемещаем временные Python скрипты
echo Перемещение временных Python скриптов...
for %%f in (tmp_*.py) do (
    if exist "%%f" (
        move /Y "%%f" "temp\tmp\" >nul 2>&1
    )
)
echo ✅ Временные скрипты перемещены
echo.

REM Перемещаем результаты симуляций
echo Перемещение результатов симуляций...
move /Y "simulation_results.txt" "temp\" >nul 2>&1
move /Y "simulate_trading_improvements.py" "temp\" >nul 2>&1
move /Y "РЕАЛИСТИЧНАЯ_СИМУЛЯЦИЯ_ТОРГОВЛИ.py" "temp\" >nul 2>&1
echo ✅ Результаты симуляций перемещены
echo.

REM Перемещаем конфиги
echo Перемещение конфигов...
move /Y "КОНФИГ_АДАПТИВНЫХ_ПАРАМЕТРОВ_РИСКА.yaml" "config\" >nul 2>&1
echo ✅ Конфиги перемещены
echo.

echo ====================================
echo   РЕСТРУКТУРИЗАЦИЯ ЗАВЕРШЕНА
echo ====================================
echo.
echo ✅ Все файлы успешно перемещены
echo.
pause

