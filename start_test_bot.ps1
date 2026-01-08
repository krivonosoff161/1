#!/usr/bin/env pwsh
<#
.DESCRIPTION
    Скрипт для запуска бота на тест с сбором статистики
    Улучшена версия: скрипт отслеживает логи в реальном времени
#>

$ErrorActionPreference = "Continue"
$timestamp = Get-Date -Format "yyyy-MM-dd_HH-mm-ss"

Write-Host @"
╔══════════════════════════════════════════════════════════════╗
║           🚀 TRADING BOT TEST RUN с STATISTICS 🚀            ║
║                      $timestamp                             ║
╚══════════════════════════════════════════════════════════════╝
"@ -ForegroundColor Cyan

# Информация о текущей конфигурации
Write-Host "`n📊 КОНФИГУРАЦИЯ:" -ForegroundColor Yellow
Write-Host "  • Режим: FUTURES (с левериджем) 📈"
Write-Host "  • Стратегия: Scalping v2 (Spot + Futures)" -ForegroundColor Green
Write-Host "  • Таймфрейм: 1m (скальпинг)"
Write-Host "  • Символы: BTC-USDT, ETH-USDT, SOL-USDT, XRP-USDT, DOGE-USDT"
Write-Host ""

# Примененные ФИКСЫ
Write-Host "✅ ПРИМЕНЕННЫЕ ФИКСЫ:" -ForegroundColor Green
Write-Host "  [FIX 1]  Circuit Breaker в futures_client.py"
Write-Host "  [FIX 2]  Hard-fail в liquidation_guard.py"
Write-Host "  [FIX 3]  TCC validation payload"
Write-Host "  [FIX 4]  SL grace period в exit_analyzer.py"
Write-Host "  [FIX 5]  Price limits validation"
Write-Host "  [FIX 6]  SL пороги расширены 0.6→0.9-1.2%"
Write-Host "  [FIX 7]  Correlation Filter hedge logic ✨"
Write-Host "  [FIX 8]  Range-bounce сигналы для ranging режима"
Write-Host "  [FIX 9]  Position Sync DRIFT logging"
Write-Host "  [FIX 10] EMA identity check (DOGE-подобные ошибки)"
Write-Host "  [FIX 11] SSL/Connector timeout optimization для VPN"
Write-Host ""

# Важные напоминания
Write-Host "⚠️  ТЕСТОВЫЕ ПАРАМЕТРЫ:" -ForegroundColor Yellow
Write-Host "  • Размер позиции: зависит от конфига"
Write-Host "  • Стоп-лосс: 0.9-1.2% (было 0.6%)"
Write-Host "  • Take-Profit: 1.5-6.55%"
Write-Host "  • Максимум одновременных позиций: 3-5"
Write-Host ""

Write-Host "🔍 МОНИТОРИНГ ЛОГОВ:" -ForegroundColor Cyan
Write-Host "  • INFO логи (сигналы, фильтры): logs/futures/*.log"
Write-Host "  • FUTURES_MAIN логи (ордера): logs/futures/archived/**/futures_main*.log"
Write-Host "  • ОШИБКИ: logs/futures/archived/**/errors*.log"
Write-Host ""

# Запуск бота
Write-Host "🚀 ЗАПУСК БОТА..." -ForegroundColor Cyan
Write-Host "Режим: FUTURES (автоматический выбор)" -ForegroundColor Green
Write-Host ""

# Переходим в директорию проекта
$botDir = "c:\Users\krivo\simple trading bot okx"
Set-Location $botDir

# Проверяем наличие виртуального окружения
if (Test-Path "$botDir\.venv\Scripts\python.exe") {
    $pythonExe = "$botDir\.venv\Scripts\python.exe"
    Write-Host "✅ Используем venv Python: $pythonExe" -ForegroundColor Green
} elseif (Test-Path "$botDir\venv\Scripts\python.exe") {
    $pythonExe = "$botDir\venv\Scripts\python.exe"
    Write-Host "✅ Используем venv Python: $pythonExe" -ForegroundColor Green
} else {
    $pythonExe = "python"
    Write-Host "⚠️  Используем системный Python" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "💡 TIPS ДЛЯ МОНИТОРИНГА:" -ForegroundColor Cyan
Write-Host "  1. Откройте новый PowerShell и запустите:"
Write-Host "     Get-Content 'logs/futures/info*.log' -Wait"
Write-Host "  2. Или используйте VS Code для просмотра логов"
Write-Host "  3. Ищите ошибки: ERROR, CRITICAL, Exception"
Write-Host "  4. Проверьте P&L в логах позиций"
Write-Host ""

Write-Host "🔴 НАЖМИТЕ CTRL+C чтобы остановить бота" -ForegroundColor Yellow
Write-Host ""

# Запускаем бота в режиме Futures с явным выбором
try {
    & $pythonExe run.py --mode futures
} catch {
    Write-Host "❌ Ошибка при запуске: $_" -ForegroundColor Red
    exit 1
}
