# 🔍 Автоматический мониторинг логов бота
# Обновляется каждые 30 секунд

param(
    [int]$Lines = 50,           # Сколько строк показывать
    [int]$IntervalSec = 30      # Интервал обновления (секунд)
)

Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan
Write-Host "🔍 АВТОМАТИЧЕСКИЙ МОНИТОРИНГ ЛОГОВ" -ForegroundColor Green
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan
Write-Host ""
Write-Host "⚙️  Настройки:" -ForegroundColor Yellow
Write-Host "   • Строк: $Lines"
Write-Host "   • Интервал: $IntervalSec секунд"
Write-Host "   • Файл: logs\trading_bot_$(Get-Date -Format 'yyyy-MM-dd').log"
Write-Host ""
Write-Host "💡 Нажмите Ctrl+C для остановки" -ForegroundColor Gray
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan
Write-Host ""

$logFile = "logs\trading_bot_$(Get-Date -Format 'yyyy-MM-dd').log"
$iteration = 0

while ($true) {
    $iteration++
    
    # Проверяем существование файла
    if (-not (Test-Path $logFile)) {
        Write-Host "⚠️  Лог файл не найден: $logFile" -ForegroundColor Yellow
        Write-Host "   Ожидание создания файла..." -ForegroundColor Gray
        Start-Sleep -Seconds 5
        continue
    }
    
    # Очищаем экран
    Clear-Host
    
    # Заголовок
    $timestamp = Get-Date -Format "HH:mm:ss"
    Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan
    Write-Host "🔍 МОНИТОРИНГ ЛОГОВ - Обновление #$iteration" -ForegroundColor Green
    Write-Host "⏰ Время: $timestamp | Интервал: ${IntervalSec}s" -ForegroundColor Gray
    Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan
    Write-Host ""
    
    # Статистика файла
    $fileSize = (Get-Item $logFile).Length / 1KB
    Write-Host "📊 Размер лога: $([math]::Round($fileSize, 2)) KB" -ForegroundColor Gray
    Write-Host ""
    
    # Последние строки с цветовой подсветкой
    Get-Content $logFile -Tail $Lines | ForEach-Object {
        $line = $_
        
        # Цветовая подсветка по типу сообщения
        if ($line -match "ERROR|CRITICAL|❌") {
            Write-Host $line -ForegroundColor Red
        }
        elseif ($line -match "WARNING|⚠️") {
            Write-Host $line -ForegroundColor Yellow
        }
        elseif ($line -match "SIGNAL GENERATED|POSITION OPENED|TRADE CLOSED|✅") {
            Write-Host $line -ForegroundColor Green
        }
        elseif ($line -match "ADX BLOCKED|MTF BLOCKED|VOLATILITY TOO HIGH|🚫") {
            Write-Host $line -ForegroundColor Magenta
        }
        elseif ($line -match "ADX CONFIRMED|MTF CONFIRMED|OCO.*placed") {
            Write-Host $line -ForegroundColor Cyan
        }
        elseif ($line -match "DEBUG") {
            Write-Host $line -ForegroundColor DarkGray
        }
        else {
            Write-Host $line
        }
    }
    
    Write-Host ""
    Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan
    Write-Host "⏳ Следующее обновление через ${IntervalSec}s..." -ForegroundColor Gray
    Write-Host "💡 Ctrl+C для остановки" -ForegroundColor DarkGray
    Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan
    
    # Ожидание
    Start-Sleep -Seconds $IntervalSec
}

