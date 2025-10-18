# PowerShell скрипт для просмотра логов
# Использование: .\view_logs.ps1

Set-Location $PSScriptRoot

# Проверка папки logs
if (-not (Test-Path "logs")) {
    Write-Host "ОШИБКА: Папка logs не найдена!" -ForegroundColor Red
    Write-Host "Бот ещё не был запущен."
    pause
    exit 1
}

# Поиск последнего лога
$logFile = Get-ChildItem "logs\trading_bot_*.log" -ErrorAction SilentlyContinue | 
    Sort-Object LastWriteTime -Descending | 
    Select-Object -First 1

if (-not $logFile) {
    Write-Host "Файлы логов не найдены!" -ForegroundColor Red
    Write-Host "Сначала запустите бота: start_bot.bat"
    pause
    exit 1
}

while ($true) {
    Clear-Host
    Write-Host "=====================================" -ForegroundColor Cyan
    Write-Host "  ПРОСМОТР ЛОГОВ - OKX Торговый Бот" -ForegroundColor Cyan
    Write-Host "=====================================" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "Файл: $($logFile.Name)" -ForegroundColor Yellow
    Write-Host "Размер: $([math]::Round($logFile.Length/1KB, 2)) KB" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "=====================================" -ForegroundColor Cyan
    Write-Host "  ВЫБЕРИТЕ РЕЖИМ:" -ForegroundColor Cyan
    Write-Host "=====================================" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "1. Последние 50 строк"
    Write-Host "2. Последние 100 строк"
    Write-Host "3. Последние 200 строк"
    Write-Host "4. Мониторинг в реальном времени"
    Write-Host "5. Только ошибки (ERROR)"
    Write-Host "6. Только сигналы и сделки"
    Write-Host "7. Profit Harvesting логи"
    Write-Host "8. Статистика быстрая"
    Write-Host "9. Открыть в Notepad"
    Write-Host "0. Выход"
    Write-Host ""
    
    $choice = Read-Host "Ваш выбор (0-9)"
    
    switch ($choice) {
        "1" {
            Clear-Host
            Write-Host "=====================================" -ForegroundColor Green
            Write-Host "  ПОСЛЕДНИЕ 50 СТРОК:" -ForegroundColor Green
            Write-Host "=====================================" -ForegroundColor Green
            Write-Host ""
            Get-Content $logFile.FullName -Tail 50 -Encoding UTF8
            Write-Host ""
            Write-Host "=====================================" -ForegroundColor Green
            pause
        }
        
        "2" {
            Clear-Host
            Write-Host "=====================================" -ForegroundColor Green
            Write-Host "  ПОСЛЕДНИЕ 100 СТРОК:" -ForegroundColor Green
            Write-Host "=====================================" -ForegroundColor Green
            Write-Host ""
            Get-Content $logFile.FullName -Tail 100 -Encoding UTF8
            Write-Host ""
            Write-Host "=====================================" -ForegroundColor Green
            pause
        }
        
        "3" {
            Clear-Host
            Write-Host "=====================================" -ForegroundColor Green
            Write-Host "  ПОСЛЕДНИЕ 200 СТРОК:" -ForegroundColor Green
            Write-Host "=====================================" -ForegroundColor Green
            Write-Host ""
            Get-Content $logFile.FullName -Tail 200 -Encoding UTF8
            Write-Host ""
            Write-Host "=====================================" -ForegroundColor Green
            pause
        }
        
        "4" {
            Clear-Host
            Write-Host "=====================================" -ForegroundColor Magenta
            Write-Host "  МОНИТОРИНГ В РЕАЛЬНОМ ВРЕМЕНИ" -ForegroundColor Magenta
            Write-Host "  Нажмите Ctrl+C для остановки" -ForegroundColor Magenta
            Write-Host "=====================================" -ForegroundColor Magenta
            Write-Host ""
            Get-Content $logFile.FullName -Wait -Tail 20 -Encoding UTF8
        }
        
        "5" {
            Clear-Host
            Write-Host "=====================================" -ForegroundColor Red
            Write-Host "  ТОЛЬКО ОШИБКИ:" -ForegroundColor Red
            Write-Host "=====================================" -ForegroundColor Red
            Write-Host ""
            $errors = Get-Content $logFile.FullName -Encoding UTF8 | Select-String "ERROR|CRITICAL" | Select-Object -Last 50
            if ($errors) {
                $errors
            } else {
                Write-Host "Ошибок не найдено! Отлично!" -ForegroundColor Green
            }
            Write-Host ""
            Write-Host "=====================================" -ForegroundColor Red
            pause
        }
        
        "6" {
            Clear-Host
            Write-Host "=====================================" -ForegroundColor Yellow
            Write-Host "  СИГНАЛЫ И СДЕЛКИ:" -ForegroundColor Yellow
            Write-Host "=====================================" -ForegroundColor Yellow
            Write-Host ""
            $trades = Get-Content $logFile.FullName -Encoding UTF8 | 
                Select-String "SIGNAL GENERATED|POSITION OPENED|TRADE CLOSED" | 
                Select-Object -Last 30
            if ($trades) {
                $trades
            } else {
                Write-Host "Сигналов пока нет. Ожидаем рыночных условий..." -ForegroundColor Yellow
            }
            Write-Host ""
            Write-Host "=====================================" -ForegroundColor Yellow
            pause
        }
        
        "7" {
            Clear-Host
            Write-Host "=====================================" -ForegroundColor Magenta
            Write-Host "  PROFIT HARVESTING:" -ForegroundColor Magenta
            Write-Host "=====================================" -ForegroundColor Magenta
            Write-Host ""
            $ph = Get-Content $logFile.FullName -Encoding UTF8 | 
                Select-String "PH Check|PROFIT HARVESTING|PH близко" | 
                Select-Object -Last 30
            if ($ph) {
                $ph
            } else {
                Write-Host "PH логов пока нет." -ForegroundColor Yellow
            }
            Write-Host ""
            Write-Host "=====================================" -ForegroundColor Magenta
            pause
        }
        
        "8" {
            Clear-Host
            Write-Host "=====================================" -ForegroundColor Cyan
            Write-Host "  СТАТИСТИКА:" -ForegroundColor Cyan
            Write-Host "=====================================" -ForegroundColor Cyan
            Write-Host ""
            Write-Host "Файл: $($logFile.Name)"
            Write-Host "Размер: $([math]::Round($logFile.Length/1KB, 2)) KB"
            Write-Host ""
            
            $content = Get-Content $logFile.FullName -Encoding UTF8
            $signals = ($content | Select-String "SIGNAL GENERATED").Count
            $opened = ($content | Select-String "POSITION OPENED").Count
            $closed = ($content | Select-String "TRADE CLOSED").Count
            $ph_triggered = ($content | Select-String "PROFIT HARVESTING TRIGGERED").Count
            $ph_checks = ($content | Select-String "PH Check").Count
            $errors = ($content | Select-String "ERROR").Count
            $regimes = ($content | Select-String "MARKET REGIME SWITCH").Count
            
            Write-Host "Сигналов сгенерировано: $signals" -ForegroundColor Green
            Write-Host "Позиций открыто: $opened" -ForegroundColor Green
            Write-Host "Позиций закрыто: $closed" -ForegroundColor Green
            Write-Host "PH сработало: $ph_triggered" -ForegroundColor Magenta
            Write-Host "PH проверок: $ph_checks" -ForegroundColor Gray
            Write-Host "Переключений режима: $regimes" -ForegroundColor Yellow
            Write-Host "Ошибок: $errors" -ForegroundColor $(if ($errors -gt 0) { "Red" } else { "Green" })
            
            Write-Host ""
            Write-Host "=====================================" -ForegroundColor Cyan
            pause
        }
        
        "9" {
            Write-Host ""
            Write-Host "Открываю лог в Notepad..." -ForegroundColor Yellow
            Start-Process notepad $logFile.FullName
            Start-Sleep -Seconds 1
        }
        
        "0" {
            Clear-Host
            Write-Host ""
            Write-Host "=====================================" -ForegroundColor Cyan
            Write-Host "  До свидания!" -ForegroundColor Cyan
            Write-Host "=====================================" -ForegroundColor Cyan
            Start-Sleep -Seconds 1
            exit 0
        }
        
        default {
            Write-Host ""
            Write-Host "Неверный выбор! Попробуйте снова..." -ForegroundColor Red
            Start-Sleep -Seconds 2
        }
    }
}

