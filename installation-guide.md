# Полное руководство по установке и настройке модернизированного торгового бота

## 📋 Содержание

1. [Подготовка системы](#подготовка-системы)
2. [Установка зависимостей](#установка-зависимостей)
3. [Клонирование и настройка проекта](#клонирование-и-настройка-проекта)
4. [Настройка безопасности](#настройка-безопасности)
5. [Конфигурация OKX API](#конфигурация-okx-api)
6. [Первый запуск и тестирование](#первый-запуск-и-тестирование)
7. [Настройка мониторинга](#настройка-мониторинга)
8. [Развертывание в продакшене](#развертывание-в-продакшене)
9. [Обслуживание и мониторинг](#обслуживание-и-мониторинг)
10. [Решение проблем](#решение-проблем)

---

## 🔧 Подготовка системы

### Требования к системе

**Минимальные требования:**
- OS: Ubuntu 20.04+ / Windows 10+ / macOS 10.15+
- RAM: 4GB (рекомендуется 8GB+)
- CPU: 2 ядра (рекомендуется 4+)
- Диск: 20GB свободного места
- Интернет: стабильное соединение 10+ Мбит/с

**Рекомендуемые требования для продакшена:**
- OS: Ubuntu 22.04 LTS
- RAM: 16GB
- CPU: 8 ядер
- Диск: SSD 100GB
- Интернет: выделенный канал 100+ Мбит/с

### Установка базовых компонентов

#### Ubuntu/Debian:
```bash
# Обновление системы
sudo apt update && sudo apt upgrade -y

# Установка базовых пакетов
sudo apt install -y \
    python3.10 \
    python3.10-dev \
    python3-pip \
    python3-venv \
    git \
    curl \
    wget \
    build-essential \
    libffi-dev \
    libssl-dev \
    pkg-config \
    redis-server \
    nginx \
    supervisor \
    htop \
    ntp

# Настройка времени (критично для HMAC подписей)
sudo systemctl enable ntp
sudo systemctl start ntp
sudo timedatectl set-ntp true

# Проверка синхронизации времени
timedatectl status
```

#### Windows:
```powershell
# Установка Python (скачайте с python.org версию 3.10+)
# Установка Git (скачайте с git-scm.com)
# Установка Redis (через WSL или Docker)

# В PowerShell (от администратора):
Set-ExecutionPolicy RemoteSigned
pip install --upgrade pip
```

#### macOS:
```bash
# Установка Homebrew (если не установлен)
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Установка компонентов
brew install python@3.10 git redis nginx
brew services start redis
```

---

## 📦 Установка зависимостей

### Установка Poetry (рекомендуется)

```bash
# Установка Poetry
curl -sSL https://install.python-poetry.org | python3 -

# Добавление в PATH (добавьте в ~/.bashrc или ~/.zshrc)
export PATH="$HOME/.local/bin:$PATH"

# Перезагрузка shell или выполните:
source ~/.bashrc

# Проверка установки
poetry --version
```

### Альтернативно: использование pip

```bash
# Установка pip-tools для фиксации зависимостей
pip install pip-tools

# Обновление pip
python -m pip install --upgrade pip
```

---

## 📁 Клонирование и настройка проекта

### Шаг 1: Клонирование репозитория

```bash
# Клонирование проекта
git clone https://github.com/your-username/enhanced-trading-bot-okx.git
cd enhanced-trading-bot-okx

# Создание ветки для персональных настроек
git checkout -b production-config
```

### Шаг 2: Создание виртуального окружения

#### Вариант A: Poetry (рекомендуется)
```bash
# Создание и активация окружения
poetry install

# Активация окружения
poetry shell
```

#### Вариант B: venv
```bash
# Создание виртуального окружения
python3 -m venv venv

# Активация окружения
# Linux/macOS:
source venv/bin/activate
# Windows:
# venv\Scripts\activate

# Установка зависимостей
pip install -r requirements.txt
```

### Шаг 3: Создание структуры папок

```bash
# Создание необходимых папок
mkdir -p logs backups .secrets config/production

# Установка правильных прав доступа
chmod 700 .secrets
chmod 755 logs backups
```

---

## 🔐 Настройка безопасности

### Шаг 1: Настройка переменных окружения

```bash
# Создание .env файла из шаблона
cp .env.example .env

# Редактирование .env файла
nano .env
```

**.env файл:**
```bash
# Основные настройки
ENVIRONMENT=production
LOG_LEVEL=INFO
TIMEZONE=UTC

# Мастер-пароль для шифрования секретов
MASTER_PASSWORD=your_very_secure_master_password_here

# OKX API (будут храниться в безопасном хранилище)
# OKX_API_KEY=your_api_key
# OKX_SECRET_KEY=your_secret_key  
# OKX_PASSPHRASE=your_passphrase

# База данных
DATABASE_URL=sqlite:///./trading_bot.db

# Redis (для кэширования и очередей)
REDIS_URL=redis://localhost:6379

# Web интерфейс
WEB_HOST=localhost
WEB_PORT=8000
WEB_SECRET_KEY=your_web_secret_key_32_chars_min

# Уведомления
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=

# Мониторинг
ENABLE_PROMETHEUS=true
PROMETHEUS_PORT=8001

# Безопасность
MAX_FAILED_AUTH_ATTEMPTS=5
TOKEN_EXPIRE_HOURS=24
ENABLE_RATE_LIMITING=true
```

### Шаг 2: Генерация секретных ключей

```bash
# Запуск скрипта генерации ключей
python scripts/generate_secrets.py

# Или вручную через Python:
python -c "
import secrets
print('MASTER_PASSWORD:', secrets.token_urlsafe(32))
print('WEB_SECRET_KEY:', secrets.token_urlsafe(32))
print('JWT_SECRET:', secrets.token_urlsafe(32))
"
```

### Шаг 3: Безопасное хранение API ключей

```bash
# Запуск скрипта настройки секретов
python scripts/setup_secrets.py

# Скрипт интерактивно запросит:
# - OKX API Key
# - OKX Secret Key  
# - OKX Passphrase
# И сохранит их в зашифрованном виде
```

**scripts/setup_secrets.py:**
```python
#!/usr/bin/env python3
"""
Скрипт для безопасной настройки API ключей
"""

import getpass
import os
from src.core.security import SecretManager

def main():
    print("🔐 Настройка безопасного хранения секретов")
    print("=" * 50)
    
    # Проверка мастер-пароля
    master_password = os.environ.get('MASTER_PASSWORD')
    if not master_password:
        master_password = getpass.getpass("Введите мастер-пароль: ")
    
    secret_manager = SecretManager(master_password)
    
    # Настройка OKX API
    print("\n📊 Настройка OKX API")
    okx_api_key = getpass.getpass("OKX API Key: ")
    okx_secret_key = getpass.getpass("OKX Secret Key: ")
    okx_passphrase = getpass.getpass("OKX Passphrase: ")
    
    # Сохранение в безопасное хранилище
    secret_manager.set_secret('OKX_API_KEY', okx_api_key)
    secret_manager.set_secret('OKX_SECRET_KEY', okx_secret_key)
    secret_manager.set_secret('OKX_PASSPHRASE', okx_passphrase)
    
    print("✅ Секреты сохранены в безопасное хранилище")
    
    # Тестирование доступа
    print("\n🧪 Тестирование доступа к секретам...")
    test_api_key = secret_manager.get_secret('OKX_API_KEY')
    if test_api_key and test_api_key.startswith(okx_api_key[:5]):
        print("✅ Доступ к секретам работает корректно")
    else:
        print("❌ Ошибка доступа к секретам")
        return False
    
    return True

if __name__ == "__main__":
    main()
```

---

## 🏗️ Конфигурация OKX API

### Шаг 1: Создание API ключей на OKX

1. **Войдите в аккаунт OKX** и перейдите в раздел API Management
2. **Создайте новый API ключ** с правами:
   - ✅ Read (чтение данных)
   - ✅ Trade (торговля)
   - ❌ Withdraw (без права вывода!)
3. **Добавьте IP адрес** сервера в whitelist
4. **Сохраните** API Key, Secret Key и Passphrase

### Шаг 2: Настройка sandbox режима

```bash
# Создание конфигурации для sandbox
cp config/config.example.yaml config/sandbox.yaml

# Редактирование sandbox конфигурации
nano config/sandbox.yaml
```

**config/sandbox.yaml:**
```yaml
# Настройки среды
environment: "sandbox"
debug: true

# OKX API настройки
exchange:
  name: "okx"
  sandbox: true
  demo_trading: true
  api_base_url: "https://www.okx.com"
  
  # Секреты будут загружены из безопасного хранилища
  credentials:
    api_key: "${OKX_API_KEY}"
    secret_key: "${OKX_SECRET_KEY}"
    passphrase: "${OKX_PASSPHRASE}"
  
  # Лимиты запросов
  rate_limits:
    rest_requests_per_second: 10
    websocket_connections: 5
    
  # Настройки подключения
  timeout: 30
  retry_attempts: 3
  retry_delay: 1.0

# Торговые инструменты
instruments:
  - symbol: "BTC-USDT-SWAP"
    inst_type: "SWAP"
    enabled: true
    min_size: 0.001
    tick_size: 0.1
    
  - symbol: "ETH-USDT-SWAP"
    inst_type: "SWAP"
    enabled: true
    min_size: 0.01
    tick_size: 0.01

# Стратегия скальпинга
strategy:
  name: "enhanced_scalping"
  enabled: true
  
  # Временные рамки
  timeframes: ["1m", "5m"]
  max_trades_per_hour: 20
  max_concurrent_positions: 3
  
  # Индикаторы
  indicators:
    rsi:
      period: 14
      overbought: 70
      oversold: 30
      adaptive: true
      
    macd:
      fast_period: 12
      slow_period: 26
      signal_period: 9
      adaptive: true
      
    bollinger_bands:
      period: 20
      std_multiplier: 2.0
      adaptive: true
      
    atr:
      period: 14
      
  # Условия входа
  entry:
    min_volatility_atr: 0.0008
    volume_threshold: 1.5
    correlation_threshold: 0.7
    
  # Условия выхода  
  exit:
    take_profit_levels: [1.2, 2.5, 4.0]  # ATR множители
    stop_loss_atr: 1.8
    max_holding_minutes: 30
    trailing_stop: true

# Управление рисками
risk_management:
  # Основные лимиты
  max_daily_loss_percent: 2.0
  max_position_size_percent: 5.0
  max_open_positions: 5
  max_correlation_exposure: 0.7
  
  # Sizing стратегия
  position_sizing:
    method: "kelly_criterion"
    base_risk_percent: 1.0
    kelly_lookback_trades: 100
    max_kelly_fraction: 0.25
    
  # Stop loss настройки  
  stop_loss:
    type: "adaptive_atr"
    atr_multiplier: 1.8
    max_loss_percent: 2.0
    
  # Take profit настройки
  take_profit:
    type: "multi_level"
    levels: [1.2, 2.5, 4.0]  # ATR множители
    size_distribution: [0.5, 0.3, 0.2]  # Распределение размера

# Фильтры времени торговли
time_filters:
  # Торговые сессии (UTC)
  trading_sessions:
    asian: {start: "00:00", end: "09:00", weight: 0.8}
    european: {start: "07:00", end: "16:00", weight: 1.0}
    american: {start: "13:00", end: "22:00", weight: 1.0}
    overlap_eur_us: {start: "13:00", end: "16:00", weight: 1.2}
    
  # Избегаемые периоды
  avoid_periods:
    - {start: "23:00", end: "01:00", reason: "low_liquidity"}
    - {weekday: "saturday", reason: "weekend"}
    - {weekday: "sunday", reason: "weekend"}

# Мониторинг и алерты
monitoring:
  health_checks:
    enabled: true
    interval_seconds: 30
    
  performance_tracking:
    enabled: true
    save_interval_minutes: 5
    
  alerts:
    telegram:
      enabled: false
      critical_only: true
    
    email:
      enabled: false
      smtp_server: ""
      
  metrics:
    prometheus:
      enabled: true
      port: 8001
      
# Логирование
logging:
  level: "INFO"
  format: "detailed"
  file_rotation: "10 MB"
  retention_days: 30
  
  # Логирование компонентов
  components:
    strategy: "DEBUG"
    risk_manager: "INFO"
    exchange_client: "INFO"
    websocket: "WARNING"
```

### Шаг 3: Валидация конфигурации

```bash
# Проверка конфигурации
python scripts/validate_config.py config/sandbox.yaml

# Тестирование подключения к OKX
python scripts/test_okx_connection.py --config config/sandbox.yaml
```

---

## 🚀 Первый запуск и тестирование

### Шаг 1: Проверка системы

```bash
# Проверка всех компонентов
python scripts/system_check.py

# Вывод должен быть примерно таким:
# ✅ Python версия: 3.10.x
# ✅ Зависимости установлены
# ✅ Секреты настроены
# ✅ Конфигурация валидна
# ✅ OKX API доступно
# ✅ Redis подключен
# ✅ База данных инициализирована
```

### Шаг 2: Инициализация базы данных

```bash
# Создание схемы базы данных
python scripts/init_database.py

# Проверка таблиц
python scripts/db_status.py
```

### Шаг 3: Первый запуск в sandbox режиме

```bash
# Запуск в режиме только чтения (без реальных ордеров)
python main.py --config config/sandbox.yaml --read-only

# В логах вы увидите:
# 2024-01-01 12:00:00 | INFO     | Starting Enhanced Trading Bot v2.0
# 2024-01-01 12:00:01 | INFO     | Environment: sandbox
# 2024-01-01 12:00:01 | INFO     | Mode: READ-ONLY (no actual trading)
# 2024-01-01 12:00:02 | INFO     | OKX API connection established
# 2024-01-01 12:00:03 | INFO     | WebSocket connections established
# 2024-01-01 12:00:04 | INFO     | Strategy initialized: enhanced_scalping
# 2024-01-01 12:00:05 | INFO     | Bot started successfully
```

### Шаг 4: Мониторинг первого запуска

Откройте новый терминал для мониторинга:

```bash
# Мониторинг логов в реальном времени
tail -f logs/trading_bot.log

# Мониторинг системных ресурсов
htop

# Проверка состояния через веб-интерфейс
curl http://localhost:8000/health
# {"status": "healthy", "uptime": 300, "version": "2.0.0"}

# Проверка метрик
curl http://localhost:8001/metrics
```

### Шаг 5: Тестирование торговых сигналов

```bash
# Запуск в режиме бэктестинга на исторических данных
python scripts/backtest.py \
  --config config/sandbox.yaml \
  --symbol BTC-USDT-SWAP \
  --start-date 2024-01-01 \
  --end-date 2024-01-07 \
  --initial-balance 10000

# Результат:
# 📊 Backtest Results for BTC-USDT-SWAP
# =====================================
# Period: 2024-01-01 to 2024-01-07
# Initial Balance: $10,000
# Final Balance: $10,243
# Total Return: 2.43%
# Sharpe Ratio: 1.34
# Max Drawdown: -1.2%
# Total Trades: 156
# Win Rate: 62.8%
# Profit Factor: 1.67
```

---

## 📊 Настройка мониторинга

### Шаг 1: Настройка Prometheus

```bash
# Создание конфигурации Prometheus
sudo mkdir -p /etc/prometheus
sudo nano /etc/prometheus/prometheus.yml
```

**/etc/prometheus/prometheus.yml:**
```yaml
global:
  scrape_interval: 15s
  
scrape_configs:
  - job_name: 'trading-bot'
    static_configs:
      - targets: ['localhost:8001']
    scrape_interval: 5s
    metrics_path: /metrics
```

### Шаг 2: Настройка Grafana Dashboard

```bash
# Создание дашборда
curl -X POST http://admin:admin@localhost:3000/api/dashboards/db \
  -H "Content-Type: application/json" \
  -d @deployment/monitoring/grafana-dashboard.json
```

### Шаг 3: Настройка алертов

```bash
# Настройка Telegram уведомлений
nano scripts/setup_alerts.py
```

**scripts/setup_alerts.py:**
```python
import os
import asyncio
from src.monitoring.alerts import TelegramNotifier

async def setup_telegram_alerts():
    bot_token = input("Введите Telegram Bot Token: ")
    chat_id = input("Введите Telegram Chat ID: ")
    
    # Сохранение в переменные окружения
    with open('.env', 'a') as f:
        f.write(f"\nTELEGRAM_BOT_TOKEN={bot_token}")
        f.write(f"\nTELEGRAM_CHAT_ID={chat_id}")
    
    # Тестирование уведомления
    notifier = TelegramNotifier(bot_token, chat_id)
    await notifier.send_message("🤖 Торговый бот настроен и готов к работе!")
    
    print("✅ Telegram уведомления настроены")

if __name__ == "__main__":
    asyncio.run(setup_telegram_alerts())
```

---

## 🚢 Развертывание в продакшене

### Шаг 1: Создание продакшен конфигурации

```bash
# Копирование базовой конфигурации
cp config/sandbox.yaml config/production.yaml

# Настройка для продакшена
nano config/production.yaml
```

**Изменения для продакшена в config/production.yaml:**
```yaml
# Отключение sandbox режима
environment: "production"
debug: false

exchange:
  sandbox: false
  demo_trading: false  # ВНИМАНИЕ: включает реальную торговлю!
  
# Более консервативные настройки риска
risk_management:
  max_daily_loss_percent: 1.0  # Снижено с 2.0%
  max_position_size_percent: 2.0  # Снижено с 5.0%
  
# Более строгие фильтры
strategy:
  max_trades_per_hour: 10  # Снижено с 20
  
# Продакшен логирование
logging:
  level: "INFO"  # Не DEBUG для производительности
```

### Шаг 2: Docker контейнеризация

**Dockerfile:**
```dockerfile
FROM python:3.10-slim

# Установка системных зависимостей
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Создание пользователя
RUN useradd -m -s /bin/bash trader
USER trader
WORKDIR /home/trader/app

# Установка Poetry
RUN pip install --user poetry
ENV PATH="/home/trader/.local/bin:$PATH"

# Копирование зависимостей
COPY --chown=trader:trader pyproject.toml poetry.lock ./
RUN poetry config virtualenvs.create false && poetry install --no-dev

# Копирование кода
COPY --chown=trader:trader . .

# Создание необходимых папок
RUN mkdir -p logs backups .secrets

# Настройка прав доступа
RUN chmod 700 .secrets && chmod 755 logs backups

# Проверка здоровья
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
  CMD curl -f http://localhost:8000/health || exit 1

# Запуск
CMD ["python", "main.py", "--config", "config/production.yaml"]
```

**docker-compose.prod.yml:**
```yaml
version: '3.8'

services:
  trading-bot:
    build: .
    restart: always
    environment:
      - ENVIRONMENT=production
    env_file:
      - .env
    volumes:
      - ./logs:/home/trader/app/logs
      - ./backups:/home/trader/app/backups
      - ./config:/home/trader/app/config:ro
    ports:
      - "8000:8000"  # Web interface
      - "8001:8001"  # Metrics
    depends_on:
      - redis
      - prometheus
    networks:
      - trading-network
      
  redis:
    image: redis:7-alpine
    restart: always
    volumes:
      - redis-data:/data
    networks:
      - trading-network
      
  prometheus:
    image: prom/prometheus:latest
    restart: always
    ports:
      - "9090:9090"
    volumes:
      - ./deployment/monitoring/prometheus.yml:/etc/prometheus/prometheus.yml:ro
      - prometheus-data:/prometheus
    networks:
      - trading-network
      
  grafana:
    image: grafana/grafana:latest
    restart: always
    ports:
      - "3000:3000"
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=secure_password_here
    volumes:
      - grafana-data:/var/lib/grafana
      - ./deployment/monitoring/grafana-dashboard.json:/var/lib/grafana/dashboards/trading-dashboard.json:ro
    networks:
      - trading-network

volumes:
  redis-data:
  prometheus-data:
  grafana-data:

networks:
  trading-network:
    driver: bridge
```

### Шаг 3: Настройка systemd сервиса

```bash
# Создание systemd сервиса
sudo nano /etc/systemd/system/trading-bot.service
```

**/etc/systemd/system/trading-bot.service:**
```ini
[Unit]
Description=Enhanced Trading Bot for OKX
After=network.target
Requires=redis.service

[Service]
Type=simple
User=trader
Group=trader
WorkingDirectory=/home/trader/enhanced-trading-bot-okx
Environment=PYTHONPATH=/home/trader/enhanced-trading-bot-okx
EnvironmentFile=/home/trader/enhanced-trading-bot-okx/.env
ExecStart=/home/trader/enhanced-trading-bot-okx/venv/bin/python main.py --config config/production.yaml
ExecReload=/bin/kill -HUP $MAINPID
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=trading-bot

# Безопасность
PrivateTmp=true
NoNewPrivileges=true
ProtectHome=true
ProtectSystem=strict
ReadWritePaths=/home/trader/enhanced-trading-bot-okx/logs /home/trader/enhanced-trading-bot-okx/backups

[Install]
WantedBy=multi-user.target
```

```bash
# Активация сервиса
sudo systemctl daemon-reload
sudo systemctl enable trading-bot.service
sudo systemctl start trading-bot.service

# Проверка статуса
sudo systemctl status trading-bot.service
```

---

## 🔍 Обслуживание и мониторинг

### Ежедневные проверки

**scripts/daily_check.sh:**
```bash
#!/bin/bash

echo "🔍 Ежедневная проверка торгового бота"
echo "====================================="

# Проверка статуса сервиса
echo "📊 Статус сервиса:"
systemctl is-active trading-bot.service

# Проверка использования ресурсов
echo -e "\n💾 Использование ресурсов:"
echo "Память: $(free -h | awk '/^Mem:/ {print $3 "/" $2}')"
echo "Диск: $(df -h / | awk 'NR==2 {print $3 "/" $2 " (" $5 ")"}')"
echo "CPU: $(top -bn1 | grep "Cpu(s)" | awk '{print $2}' | sed 's/%us,//')"

# Проверка логов на ошибки
echo -e "\n📝 Последние ошибки в логах:"
tail -n 100 logs/trading_bot.log | grep -i error | tail -5

# Проверка производительности
echo -e "\n📈 Производительность за последние 24 часа:"
python scripts/performance_report.py --period 24h

# Проверка свободного места
echo -e "\n💿 Свободное место:"
df -h logs/ backups/

# Проверка бэкапов
echo -e "\n💾 Последние бэкапы:"
ls -lah backups/ | tail -5

echo -e "\n✅ Проверка завершена"
```

### Мониторинг в реальном времени

```bash
# Создание dashboard в терминале
watch -n 5 'python scripts/status_dashboard.py'
```

**scripts/status_dashboard.py:**
```python
#!/usr/bin/env python3
"""
Простой dashboard состояния в терминале
"""

import asyncio
import json
from datetime import datetime, timedelta
import requests
import os

def get_bot_status():
    try:
        response = requests.get('http://localhost:8000/status', timeout=5)
        return response.json()
    except:
        return {"error": "Bot not responding"}

def get_performance_metrics():
    try:
        response = requests.get('http://localhost:8000/performance', timeout=5)
        return response.json()
    except:
        return {"error": "Metrics not available"}

def print_dashboard():
    os.system('clear')  # Очистка экрана
    
    print("🤖 Enhanced Trading Bot - Live Dashboard")
    print("=" * 50)
    print(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print()
    
    # Статус бота
    status = get_bot_status()
    if "error" not in status:
        print(f"📊 Status: {status.get('status', 'Unknown')}")
        print(f"🔄 Uptime: {status.get('uptime_hours', 0):.1f} hours")
        print(f"📈 Active Positions: {status.get('active_positions', 0)}")
        print(f"⏳ Pending Orders: {status.get('pending_orders', 0)}")
    else:
        print("❌ Bot Status: OFFLINE")
    
    print()
    
    # Производительность
    metrics = get_performance_metrics()
    if "error" not in metrics:
        print("📊 Performance (24h):")
        print(f"   💰 PnL: ${metrics.get('daily_pnl', 0):.2f}")
        print(f"   📈 Total Trades: {metrics.get('total_trades', 0)}")
        print(f"   🎯 Win Rate: {metrics.get('win_rate', 0):.1f}%")
        print(f"   📊 Sharpe Ratio: {metrics.get('sharpe_ratio', 0):.2f}")
    else:
        print("❌ Performance Metrics: UNAVAILABLE")
    
    print()
    
    # Системные ресурсы
    try:
        import psutil
        print("💻 System Resources:")
        print(f"   🖥️  CPU: {psutil.cpu_percent():.1f}%")
        print(f"   💾 RAM: {psutil.virtual_memory().percent:.1f}%")
        print(f"   💿 Disk: {psutil.disk_usage('/').percent:.1f}%")
    except ImportError:
        print("💻 System Resources: Install psutil for monitoring")
    
    print("\n" + "=" * 50)
    print("Press Ctrl+C to exit")

if __name__ == "__main__":
    try:
        while True:
            print_dashboard()
            time.sleep(5)
    except KeyboardInterrupt:
        print("\nDashboard stopped.")
```

### Автоматические алерты

**scripts/alert_monitor.py:**
```python
#!/usr/bin/env python3
"""
Система мониторинга и автоматических алертов
"""

import asyncio
import json
from datetime import datetime, timedelta
import requests
import smtplib
from email.mime.text import MimeText
from email.mime.multipart import MimeMultipart

class AlertMonitor:
    def __init__(self):
        self.last_check = datetime.now()
        self.alert_thresholds = {
            'max_drawdown': -5.0,  # -5%
            'daily_loss': -2.0,    # -2%
            'error_rate': 10,      # 10 ошибок в час
            'response_time': 5.0,  # 5 секунд
        }
    
    async def check_critical_conditions(self):
        """Проверка критических условий"""
        alerts = []
        
        # Проверка статуса бота
        if not await self.is_bot_responsive():
            alerts.append({
                'level': 'CRITICAL',
                'message': 'Trading bot is not responding',
                'action': 'Immediate attention required'
            })
        
        # Проверка производительности
        metrics = await self.get_performance_metrics()
        if metrics:
            if metrics.get('daily_pnl', 0) < self.alert_thresholds['daily_loss']:
                alerts.append({
                    'level': 'HIGH',
                    'message': f"Daily loss exceeded threshold: {metrics['daily_pnl']:.2f}%",
                    'action': 'Review trading strategy'
                })
            
            if metrics.get('max_drawdown', 0) < self.alert_thresholds['max_drawdown']:
                alerts.append({
                    'level': 'CRITICAL',
                    'message': f"Max drawdown exceeded: {metrics['max_drawdown']:.2f}%",
                    'action': 'Consider stopping bot'
                })
        
        return alerts
    
    async def send_alerts(self, alerts):
        """Отправка алертов"""
        for alert in alerts:
            if alert['level'] == 'CRITICAL':
                await self.send_telegram_alert(alert)
                await self.send_email_alert(alert)
            elif alert['level'] == 'HIGH':
                await self.send_telegram_alert(alert)

async def main():
    monitor = AlertMonitor()
    
    while True:
        try:
            alerts = await monitor.check_critical_conditions()
            if alerts:
                await monitor.send_alerts(alerts)
            
            await asyncio.sleep(300)  # Проверка каждые 5 минут
            
        except Exception as e:
            print(f"Error in alert monitor: {e}")
            await asyncio.sleep(60)

if __name__ == "__main__":
    asyncio.run(main())
```

---

## 🚨 Решение проблем

### Частые проблемы и решения

#### 1. "Invalid Sign" ошибка OKX API
```bash
# Проверка синхронизации времени
timedatectl status

# Принудительная синхронизация
sudo ntpdate -s time.nist.gov

# Перезапуск бота
sudo systemctl restart trading-bot
```

#### 2. Высокое потребление памяти
```bash
# Проверка утечек памяти
python scripts/memory_profiler.py

# Очистка кэша
python scripts/clear_cache.py

# Рестарт с очисткой
sudo systemctl restart trading-bot
```

#### 3. Потеря WebSocket соединения
```bash
# Проверка сетевого соединения
ping www.okx.com

# Проверка логов WebSocket
grep -i websocket logs/trading_bot.log | tail -20

# Принудительное переподключение
curl -X POST http://localhost:8000/reconnect
```

#### 4. База данных заблокирована
```bash
# Проверка блокировок
python scripts/check_db_locks.py

# Освобождение блокировок (ОСТОРОЖНО!)
python scripts/release_db_locks.py

# Восстановление из бэкапа при необходимости
python scripts/restore_database.py --backup backups/latest.db
```

### Экстренные процедуры

#### Экстренная остановка торговли
```bash
# Установка kill-switch через API
curl -X POST http://localhost:8000/emergency-stop

# Или через переменную окружения
export KILL_SWITCH=true

# Или создание файла-флага
touch EMERGENCY_STOP
```

#### Быстрое восстановление
```bash
# Скрипт быстрого восстановления
./scripts/emergency_recovery.sh

# Что включает:
# 1. Остановка всех процессов
# 2. Закрытие всех позиций
# 3. Отмена всех ордеров
# 4. Восстановление из последнего бэкапа
# 5. Проверка целостности данных
# 6. Перезапуск в безопасном режиме
```

Это полное руководство обеспечивает пошаговую установку, настройку и эксплуатацию модернизированного торгового бота с максимальным уровнем безопасности и надежности.