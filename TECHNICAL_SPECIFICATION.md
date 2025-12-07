# Техническое задание: OKX Trading Bot

**Версия:** 1.0  
**Дата:** 2025-12-07  
**Статус:** Production Ready

---

## 🔹 1. Структура проекта

### 1.1 Общая структура директорий

```
simple trading bot okx/
├── src/                          # Исходный код
│   ├── main_futures.py          # Точка входа для Futures торговли
│   ├── main_spot.py             # Точка входа для Spot торговли
│   ├── config.py                # Загрузка конфигурации
│   ├── clients/                  # API клиенты
│   │   ├── futures_client.py    # OKX Futures API клиент
│   │   └── spot_client.py       # OKX Spot API клиент
│   ├── strategies/               # Торговые стратегии
│   │   └── scalping/             # Скальпинг стратегия
│   │       ├── futures/          # Futures реализация
│   │       │   ├── orchestrator.py      # Главный координатор
│   │       │   ├── signal_generator.py   # Генератор сигналов
│   │       │   ├── position_manager.py   # Управление позициями
│   │       │   ├── order_executor.py     # Исполнение ордеров
│   │       │   ├── risk_manager.py       # Управление рисками
│   │       │   ├── positions/            # Модули позиций
│   │       │   │   ├── entry_manager.py  # Открытие позиций
│   │       │   │   └── exit_analyzer.py  # Анализ выхода
│   │       │   ├── coordinators/         # Координаторы
│   │       │   │   ├── websocket_coordinator.py  # WebSocket координатор
│   │       │   │   ├── signal_coordinator.py     # Координатор сигналов
│   │       │   │   └── trailing_sl_coordinator.py # Trailing Stop Loss
│   │       │   ├── filters/               # Фильтры сигналов
│   │       │   │   ├── liquidity_filter.py
│   │       │   │   ├── order_flow_filter.py
│   │       │   │   ├── volatility_regime_filter.py
│   │       │   │   └── funding_rate_filter.py
│   │       │   ├── indicators/            # Индикаторы
│   │       │   │   ├── fast_adx.py
│   │       │   │   ├── order_flow_indicator.py
│   │       │   │   └── trailing_stop_loss.py
│   │       │   ├── calculations/         # Калькуляторы
│   │       │   │   ├── position_sizer.py
│   │       │   │   ├── margin_calculator.py
│   │       │   │   ├── pnl_calculator.py
│   │       │   │   └── balance_calculator.py
│   │       │   ├── adaptivity/            # Адаптивная система
│   │       │   │   ├── regime_manager.py  # Управление режимами рынка
│   │       │   │   ├── balance_manager.py # Управление балансом
│   │       │   │   └── parameter_adapter.py # Адаптация параметров
│   │       │   └── risk/                  # Риск-менеджмент
│   │       │       ├── liquidation_protector.py
│   │       │       ├── margin_monitor.py
│   │       │       └── max_size_limiter.py
│   │       └── spot/              # Spot реализация
│   ├── indicators/                # Базовые индикаторы
│   │   └── base.py                # RSI, ATR, MACD, SMA, EMA
│   ├── filters/                   # Общие фильтры
│   ├── risk/                      # Общий риск-менеджмент
│   └── utils/                     # Утилиты
│       ├── logging_setup.py
│       └── telegram_notifier.py
├── config/                        # Конфигурационные файлы
│   ├── config_futures.yaml        # Конфигурация Futures
│   ├── config_spot.yaml          # Конфигурация Spot
│   └── features.yaml             # Флаги функций
├── logs/                          # Логи и данные
│   ├── futures/                   # Логи Futures торговли
│   │   ├── futures_main_YYYY-MM-DD.log
│   │   ├── trades_YYYY-MM-DD.csv
│   │   ├── positions_open_YYYY-MM-DD.csv
│   │   ├── orders_YYYY-MM-DD.csv
│   │   └── signals_YYYY-MM-DD.csv
│   └── archived/                  # Архивированные логи
├── tests/                         # Тесты
├── scripts/                       # Вспомогательные скрипты
├── requirements.txt               # Зависимости Python
├── env.example                    # Пример переменных окружения
└── README.md                     # Документация
```

### 1.2 Назначение основных директорий

- **`src/strategies/scalping/futures/`**: Основная логика Futures скальпинга
  - `orchestrator.py`: Центральный координатор всех компонентов
  - `signal_generator.py`: Генерация торговых сигналов на основе индикаторов
  - `position_manager.py`: Управление жизненным циклом позиций
  - `order_executor.py`: Размещение и исполнение ордеров на бирже
  - `risk_manager.py`: Управление рисками и расчет размера позиций

- **`src/strategies/scalping/futures/adaptivity/`**: Адаптивная система
  - Динамическая адаптация параметров под режим рынка (Trending/Ranging/Choppy)
  - Адаптация под размер баланса (Micro/Small/Medium/Large)
  - Per-symbol настройки для каждой торговой пары

- **`src/strategies/scalping/futures/filters/`**: Фильтры сигналов
  - Проверка ликвидности, order flow, волатильности, funding rate

- **`src/strategies/scalping/futures/calculations/`**: Математические расчеты
  - Размер позиций, маржа, PnL, баланс

- **`config/`**: Конфигурационные файлы YAML
  - Все параметры торговли, рисков, индикаторов, фильтров

- **`logs/`**: Логирование и CSV файлы
  - Структурированные логи в JSON формате
  - CSV файлы для анализа: сделки, позиции, ордера, сигналы

---

## 🔹 2. Основные исполняемые файлы

### 2.1 Точка входа

**Файл:** `src/main_futures.py`

```python
# Запуск бота
python src/main_futures.py
```

**Особенности:**
- Загружает конфигурацию из `config/config_futures.yaml`
- Проверяет наличие API ключей
- Выводит предупреждение о рисках Futures торговли
- Создает и запускает `FuturesScalpingOrchestrator`
- Обрабатывает `KeyboardInterrupt` для graceful shutdown

**Режимы запуска:**
- **Production**: `sandbox: false` в конфиге
- **Sandbox (Demo)**: `sandbox: true` в конфиге (рекомендуется для тестирования)

**Нет режимов `--dry-run` или `--validate`** - используется только sandbox режим OKX для безопасного тестирования.

### 2.2 Production запуск

1. **Настройка конфигурации:**
   ```yaml
   api:
     okx:
       api_key: "${OKX_API_KEY}"
       api_secret: "${OKX_API_SECRET}"
       passphrase: "${OKX_PASSPHRASE}"
       sandbox: false  # ← false для реальной торговли
   ```

2. **Запуск:**
   ```bash
   python src/main_futures.py
   ```

3. **Остановка:**
   - `Ctrl+C` для graceful shutdown
   - Бот корректно закроет все позиции и соединения

---

## 🔹 3. Конфигурация

### 3.1 Основной конфигурационный файл

**Файл:** `config/config_futures.yaml`

**Структура:**

```yaml
# API настройки
api:
  okx:
    api_key: "${OKX_API_KEY}"      # Из переменных окружения
    api_secret: "${OKX_API_SECRET}"
    passphrase: "${OKX_PASSPHRASE}"
    sandbox: true                  # true = demo, false = live

# Торговые пары
trading:
  symbols:
    - "BTC-USDT"
    - "ETH-USDT"
    - "SOL-USDT"
    - "DOGE-USDT"
    - "XRP-USDT"
  base_currency: "USDT"
  trading_mode: "futures"

# Параметры скальпинга
scalping:
  enabled: true
  check_interval: 1.0              # Интервал проверки (секунды)
  min_signal_strength: 0.25
  max_concurrent_signals: 3
  max_positions_per_symbol: 1
  allow_concurrent_positions: false
  allow_long_positions: true
  allow_short_positions: true
  
  # Take Profit и Stop Loss
  tp_percent: 2.4                  # Базовый TP (%)
  sl_percent: 1.2                  # Базовый SL (%)
  order_type: "limit"               # limit или market
  
  # Partial TP (частичное закрытие)
  partial_tp:
    enabled: true
    fraction: 0.6                   # 60% позиции
    trigger_percent: 0.4            # При 0.4% прибыли
    post_only: true
    limit_offset_bps: 7.0
  
  # Комиссии
  commission:
    trading_fee_rate: 0.0010       # 0.10% на круг (taker)
    maker_fee_rate: 0.0002          # 0.02% (maker)
    taker_fee_rate: 0.0005          # 0.05% (taker)
  
  # Profit Drawdown Protection
  profit_drawdown:
    enabled: true
    drawdown_percent: 0.20          # 20% откат от пика
    min_profit_to_activate_usd: 0.5

# Управление рисками
risk:
  max_daily_loss_percent: 5.0      # Макс. дневной убыток (%)
  consecutive_losses_limit: 5       # Лимит убытков подряд
  pair_block_duration_min: 30       # Блокировка пары (минуты)
  max_open_positions: 5
  risk_per_trade_percent: 0.03     # Риск на сделку (3%)

# Адаптивные параметры по режимам рынка
scalping.adaptive_regime:
  enabled: true
  detection:
    trending_adx_threshold: 20.0
    ranging_adx_threshold: 15.0
    choppy_adx_threshold: 12.0
  
  # Trending режим (тренд)
  trending:
    min_score_threshold: 1.6
    tp_percent: 2.5
    sl_percent: 1.5
    max_holding_minutes: 30
    indicators:
      rsi_overbought: 75
      rsi_oversold: 25
      ema_fast: 8
      ema_slow: 21
  
  # Ranging режим (флэт)
  ranging:
    min_score_threshold: 1.6
    tp_percent: 2.0
    sl_percent: 2.0
    max_holding_minutes: 20
    indicators:
      rsi_overbought: 70
      rsi_oversold: 30
      ema_fast: 10
      ema_slow: 25
  
  # Choppy режим (хаос)
  choppy:
    min_score_threshold: 1.8
    tp_percent: 1.5
    sl_percent: 1.0
    max_holding_minutes: 10
    indicators:
      rsi_overbought: 65
      rsi_oversold: 35
      ema_fast: 12
      ema_slow: 30

# Профили баланса
scalping.balance_profiles:
  micro:    # $100 - $500
    threshold: 500.0
    base_position_usd: 50.0
    max_open_positions: 5
  small:    # $500 - $1500
    threshold: 1500.0
    base_position_usd: 100.0
    max_open_positions: 5
  medium:   # $1500 - $3000
    threshold: 3000.0
    base_position_usd: 175.0
    max_open_positions: 5
  large:    # $3000+
    threshold: 999999.0
    base_position_usd: 250.0
    max_open_positions: 5

# Per-symbol настройки
scalping.adaptive_regime.symbol_profiles:
  BTC-USDT:
    position_multiplier: 1.6
    trending:
      tp_percent: 5.0
      sl_percent: 1.5
      filters:
        liquidity:
          min_best_bid_volume_usd: 140
          min_orderbook_depth_usd: 1200
        order_flow:
          long_threshold: 0.0065
    # ... аналогично для ranging и choppy
```

### 3.2 Переменные окружения

**Файл:** `env.example`

```bash
# OKX API Credentials
OKX_API_KEY=your_api_key_here
OKX_API_SECRET=your_api_secret_here
OKX_PASSPHRASE=your_passphrase_here

# Telegram Notifications (optional)
TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here
TELEGRAM_CHAT_ID=your_telegram_chat_id_here
```

**Использование:**
- Создайте файл `.env` на основе `env.example`
- Заполните реальные значения
- Конфиг автоматически подставит значения через `${OKX_API_KEY}`

### 3.3 Группировка параметров

#### 3.3.1 Торговые пары
- Список символов: `trading.symbols`
- Per-symbol настройки: `scalping.adaptive_regime.symbol_profiles.{SYMBOL}`
- Параметры для каждого символа по режимам (trending/ranging/choppy)

#### 3.3.2 Параметры скальпинга
- `check_interval`: Интервал проверки позиций (1.0 сек)
- `tp_percent`, `sl_percent`: Take Profit и Stop Loss
- `partial_tp`: Частичное закрытие позиций
- `order_type`: Тип ордера (limit/market)
- `leverage`: Леверидж (5x по умолчанию)

#### 3.3.3 Управление рисками
- `max_daily_loss_percent`: Максимальный дневной убыток (5%)
- `consecutive_losses_limit`: Лимит убытков подряд (5)
- `pair_block_duration_min`: Блокировка пары после серии убытков (30 мин)
- `max_open_positions`: Максимум открытых позиций (5)
- `risk_per_trade_percent`: Риск на сделку (3%)

#### 3.3.4 Настройки индикаторов
- **По режимам рынка:**
  - `trending.indicators`: RSI (75/25), EMA (8/21)
  - `ranging.indicators`: RSI (70/30), EMA (10/25)
  - `choppy.indicators`: RSI (65/35), EMA (12/30)
- **Per-symbol overrides:** Каждый символ может переопределять параметры индикаторов

---

## 🔹 4. Торговая логика

### 4.1 Реализация стратегии скальпинга

**Файл:** `src/strategies/scalping/futures/signal_generator.py`

**Основной класс:** `FuturesSignalGenerator`

**Процесс генерации сигналов:**

1. **Получение рыночных данных:**
   - OHLCV свечи через WebSocket
   - Order book (стакан)
   - Trades (последние сделки)

2. **Расчет индикаторов:**
   - RSI (Relative Strength Index)
   - EMA (Exponential Moving Average) - быстрая и медленная
   - ATR (Average True Range)
   - MACD (Moving Average Convergence Divergence)
   - ADX (Average Directional Index)

3. **Определение режима рынка:**
   - **Trending**: ADX > 20, сильный тренд
   - **Ranging**: ADX 15-20, боковое движение
   - **Choppy**: ADX < 15, хаотичное движение

4. **Генерация сигналов:**
   - Проверка условий входа (RSI, EMA, ATR)
   - Расчет силы сигнала (strength 0.0-1.0)
   - Расчет уверенности (confidence 0.0-1.0)

5. **Фильтрация сигналов:**
   - Ликвидность (order book depth)
   - Order flow (поток ордеров)
   - Волатильность (ATR)
   - Funding rate (для Futures)

6. **Ранжирование и выбор:**
   - Расчет финального score (strength × confidence × filters)
   - Сравнение с `min_score_threshold` для режима
   - Выбор лучших сигналов

### 4.2 Генерация сигналов на вход

**Метод:** `_generate_rsi_signals()` в `signal_generator.py`

**Логика:**

```python
# 1. Получаем RSI значение
rsi = indicators.get("rsi", 50)

# 2. Получаем режим-специфичные пороги
rsi_oversold = regime_params.get("rsi_oversold", 30)  # Trending: 25, Ranging: 30, Choppy: 35
rsi_overbought = regime_params.get("rsi_overbought", 70)  # Trending: 75, Ranging: 70, Choppy: 65

# 3. Проверяем перепроданность (BUY сигнал)
if rsi < rsi_oversold:
    # Проверяем тренд через EMA
    is_downtrend = ema_fast < ema_slow and current_price < ema_fast
    
    # Если конфликт (RSI oversold, но EMA bearish) - снижаем strength
    if is_downtrend:
        strength *= conflict_multiplier  # Обычно 0.5
    
    # Генерируем BUY сигнал
    signals.append({
        "symbol": symbol,
        "side": "buy",
        "type": "rsi_oversold",
        "strength": strength,
        "confidence": confidence,
        "price": current_price
    })

# 4. Проверяем перекупленность (SELL сигнал)
elif rsi > rsi_overbought:
    # Аналогично для SHORT сигнала
    signals.append({
        "symbol": symbol,
        "side": "sell",
        "type": "rsi_overbought",
        "strength": strength,
        "confidence": confidence,
        "price": current_price
    })
```

### 4.3 Проверка совпадения SMA/EMA

**Метод:** `_check_ema_alignment()` в `signal_generator.py`

**Логика:**

```python
# Получаем EMA значения
ema_fast = indicators.get("ema_12", 0)   # Быстрая EMA (8-12 периодов)
ema_slow = indicators.get("ema_26", 0)   # Медленная EMA (21-30 периодов)
current_price = market_data.ohlcv_data[-1].close

# Для LONG сигнала:
# ✅ Бычий тренд: ema_fast > ema_slow И current_price > ema_fast
is_uptrend = ema_fast > ema_slow and current_price > ema_fast

# Для SHORT сигнала:
# ✅ Медвежий тренд: ema_fast < ema_slow И current_price < ema_fast
is_downtrend = ema_fast < ema_slow and current_price < ema_fast

# Если конфликт (например, RSI oversold, но EMA bearish):
# - Снижаем strength сигнала на conflict_multiplier (обычно 0.5)
# - Снижаем confidence до 50% от нормальной
```

**Адаптивные пороги по режимам:**

- **Trending**: `min_ma_difference_pct: 0.1%` (менее строго)
- **Ranging**: `min_ma_difference_pct: 0.01%` (очень строго)
- **Choppy**: `min_ma_difference_pct: 0.03%` (умеренно)

### 4.4 Использование RSI

**Файл:** `src/indicators/base.py` → класс `RSI`

**Формула расчета:**

```python
# 1. Вычисляем изменения цены
deltas = np.diff(prices)

# 2. Разделяем на прибыльные и убыточные
gains = np.where(deltas > 0, deltas, 0)
losses = np.where(deltas < 0, -deltas, 0)

# 3. Экспоненциальное сглаживание Wilder
avg_gain = (avg_gain * (period - 1) + gains[i]) / period
avg_loss = (avg_loss * (period - 1) + losses[i]) / period

# 4. Вычисляем RSI
rs = avg_gain / avg_loss
rsi_value = 100.0 - (100.0 / (1.0 + rs))
```

**Фильтр по значению ИЛИ по направлению:**

- **По значению:**
  - `rsi < rsi_oversold` → BUY сигнал
  - `rsi > rsi_overbought` → SELL сигнал
  
- **По направлению:**
  - RSI растет → усиление бычьего сигнала
  - RSI падает → усиление медвежьего сигнала

**Адаптивные пороги:**

- **Trending**: `rsi_oversold: 25`, `rsi_overbought: 75` (более экстремальные)
- **Ranging**: `rsi_oversold: 30`, `rsi_overbought: 70` (стандартные)
- **Choppy**: `rsi_oversold: 35`, `rsi_overbought: 65` (менее экстремальные)

### 4.5 Расчет и применение ATR

**Файл:** `src/indicators/base.py` → класс `ATR`

**Формула расчета:**

```python
# True Range = max из трёх значений:
#   1. High - Low (диапазон текущего бара)
#   2. |High - Close_prev| (гэп вверх)
#   3. |Low - Close_prev| (гэп вниз)
true_ranges = []
for i in range(1, len(close_data)):
    high_low = high_data[i] - low_data[i]
    high_close = abs(high_data[i] - close_data[i - 1])
    low_close = abs(low_data[i] - close_data[i - 1])
    true_range = max(high_low, high_close, low_close)
    true_ranges.append(true_range)

# ATR = экспоненциальное сглаживание True Range
atr = exponential_smoothing(true_ranges, period=14)
```

**Применение ATR:**

1. **Фильтр волатильности:**
   - `min_volatility_atr`: Минимальная волатильность для входа
   - Trending: `0.0004`, Ranging: `0.0003`, Choppy: `0.0005`

2. **Расчет TP/SL:**
   - `tp_atr_multiplier`: Множитель ATR для TP (0.5-1.0)
   - `sl_atr_multiplier`: Множитель ATR для SL (0.4-0.5)

3. **Адаптация размера позиции:**
   - Высокая волатильность → уменьшаем размер
   - Низкая волатильность → увеличиваем размер

### 4.6 Определение "volume spike"

**Нет прямого определения "volume spike"**, но есть:

1. **Volume Profile Filter:**
   - Анализ распределения объема по ценам
   - Бонус к score при нахождении в Value Area или около POC (Point of Control)

2. **Volume Threshold:**
   - `volume_threshold: 1.05` (объем должен быть на 5% выше среднего)
   - Trending: `1.05`, Ranging: `1.05`, Choppy: `1.1`

3. **Order Flow Indicator:**
   - Анализ потока ордеров (buy vs sell pressure)
   - `long_threshold: 0.0065` для BTC в trending режиме

### 4.7 Расчет размера позиции, стоп-лосса, тейк-профита

#### 4.7.1 Размер позиции

**Файл:** `src/strategies/scalping/futures/risk_manager.py` → метод `calculate_position_size()`

**Формула:**

```python
# 1. Базовый размер (процент от баланса)
base_usd_size = balance * risk_per_trade_percent  # Обычно 3%

# 2. Режимный множитель
regime_multiplier = get_regime_multiplier(regime)  # Trending: 1.1, Ranging: 1.0, Choppy: 0.8
base_usd_size *= regime_multiplier

# 3. Множитель силы сигнала
strength_multiplier = 0.8 + (signal_strength * 0.4)  # 0.8-1.2
base_usd_size *= strength_multiplier

# 4. Kelly Criterion (опционально)
if trading_statistics:
    win_rate = statistics.get_win_rate(regime)
    avg_win = statistics.get_avg_win(regime)
    avg_loss = statistics.get_avg_loss(regime)
    
    if avg_loss > 0:
        risk_reward = avg_win / avg_loss
        kelly_fraction = (win_rate * risk_reward - (1 - win_rate)) / risk_reward
        kelly_multiplier = min(kelly_fraction * 0.25, 0.1)  # Максимум 10% от баланса
        base_usd_size *= kelly_multiplier

# 5. Ограничение максимальным размером
max_usd_size = balance_profile.get("max_position_usd", 250.0)
base_usd_size = min(base_usd_size, max_usd_size)

# 6. Конвертация в монеты
position_size_coins = base_usd_size / current_price
```

#### 4.7.2 Take Profit (TP)

**Расчет:**

```python
# Базовый TP из конфига (адаптивно по режиму)
base_tp_percent = regime_params.get("tp_percent", 2.4)  # Trending: 2.5%, Ranging: 2.0%, Choppy: 1.5%

# Адаптация через ATR
atr_multiplier = regime_params.get("tp_atr_multiplier", 1.0)
atr_tp = atr_value * atr_multiplier

# Финальный TP = max(базовый, ATR-based)
tp_percent = max(base_tp_percent, (atr_tp / current_price) * 100)

# Для LONG: exit_price = entry_price * (1 + tp_percent / 100)
# Для SHORT: exit_price = entry_price * (1 - tp_percent / 100)
```

#### 4.7.3 Stop Loss (SL)

**Расчет:**

```python
# Базовый SL из конфига (адаптивно по режиму)
base_sl_percent = regime_params.get("sl_percent", 1.2)  # Trending: 1.5%, Ranging: 2.0%, Choppy: 1.0%

# Адаптация через ATR
atr_multiplier = regime_params.get("sl_atr_multiplier", 0.5)
atr_sl = atr_value * atr_multiplier

# Финальный SL = max(базовый, ATR-based)
sl_percent = max(base_sl_percent, (atr_sl / current_price) * 100)

# Для LONG: exit_price = entry_price * (1 - sl_percent / 100)
# Для SHORT: exit_price = entry_price * (1 + sl_percent / 100)
```

### 4.8 Backtesting модуль

**Нет встроенного backtesting модуля**, но есть:

1. **Sandbox режим OKX:**
   - `sandbox: true` в конфиге
   - Реальная торговля на демо-счете OKX

2. **Логирование для анализа:**
   - CSV файлы: `trades_YYYY-MM-DD.csv`, `signals_YYYY-MM-DD.csv`
   - Можно анализировать исторические данные

3. **Скрипты анализа:**
   - `analyze_trades_quality.py`: Анализ качества сделок
   - `analyze_logs_comprehensive.py`: Комплексный анализ логов

---

## 🔹 5. Риск-менеджмент

### 5.1 Kelly Criterion

**Файл:** `src/strategies/scalping/futures/calculations/margin_calculator.py` → метод `calculate_optimal_position_size()`

**Формула:**

```python
# Kelly Criterion формула:
# f* = (p * b - q) / b
# где:
#   f* = оптимальная доля капитала
#   p = вероятность выигрыша (win_rate)
#   q = вероятность проигрыша (1 - p)
#   b = коэффициент выплаты (risk_reward_ratio = avg_win / avg_loss)

win_rate = statistics.get_win_rate(regime)  # Например, 0.55 (55%)
avg_win = statistics.get_avg_win(regime)     # Например, $2.0
avg_loss = statistics.get_avg_loss(regime)    # Например, $1.0

if avg_loss > 0:
    risk_reward_ratio = avg_win / avg_loss   # Например, 2.0
    
    # Kelly fraction
    kelly_fraction = (win_rate * risk_reward_ratio - (1 - win_rate)) / risk_reward_ratio
    # Пример: (0.55 * 2.0 - 0.45) / 2.0 = (1.1 - 0.45) / 2.0 = 0.325 (32.5%)
    
    # Ограничиваем Kelly для безопасности (используем 25% от Kelly)
    kelly_fraction_safe = min(kelly_fraction * 0.25, 0.1)  # Максимум 10% от баланса
    
    # Применяем как множитель к risk_percentage
    kelly_multiplier = max(0.5, min(2.0, kelly_fraction_safe / risk_percentage))
    # Если risk_percentage = 0.03 (3%), то kelly_multiplier = 0.325 / 0.03 = 10.83 → ограничиваем до 2.0
```

**Использование:**

- Kelly применяется только если есть статистика по режиму
- Отрицательный Kelly → снижаем размер позиции (multiplier = 0.5)
- Положительный Kelly → увеличиваем размер (multiplier до 2.0)

### 5.2 Отслеживание дневного убытка

**Файл:** `src/strategies/scalping/futures/risk_manager.py` → методы `record_daily_pnl()`, `_check_max_daily_loss()`

**Логика:**

```python
# 1. Отслеживание дневного PnL
def record_daily_pnl(self, pnl: float):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    
    # Если новый день - сбрасываем
    if self.daily_pnl_date != today:
        self.daily_pnl = 0.0
        self.daily_pnl_date = today
        self.daily_trading_stopped = False
    
    # Обновляем дневной PnL
    self.daily_pnl += pnl

# 2. Проверка лимита
async def _check_max_daily_loss(self) -> bool:
    if self.daily_trading_stopped:
        return False  # Уже остановлено
    
    # Получаем текущий баланс
    balance = await self.data_registry.get_balance()
    balance_value = balance.get("balance", 0.0)
    
    # Рассчитываем процент убытка
    loss_percent = abs(self.daily_pnl) / balance_value * 100 if balance_value > 0 else 0
    
    # Проверяем лимит
    if loss_percent >= self.max_daily_loss_percent:  # Обычно 5%
        self.daily_trading_stopped = True
        logger.error(
            f"❌ Дневной лимит убытков достигнут: {loss_percent:.2f}% >= {self.max_daily_loss_percent}%"
        )
        return False
    
    return True
```

**Вызов:**

- Вызывается перед расчетом размера позиции в `calculate_position_size()`
- Если лимит достигнут → возвращает `None` (позиция не открывается)

### 5.3 Ограничение макс. числа позиций

**Файл:** `src/strategies/scalping/futures/coordinators/signal_coordinator.py` → метод `check_for_signals()`

**Логика:**

```python
# 1. Получаем количество открытых позиций
active_positions = await self.client.get_positions()
active_positions_count = len([p for p in active_positions if abs(float(p.get("pos", 0))) > 1e-8])

# 2. Получаем лимит из balance_profile
balance = await self.client.get_balance()
balance_profile = self.config_manager.get_balance_profile(balance)
max_open = balance_profile.get("max_open_positions", 5)  # Micro: 5, Small: 5, Medium: 5, Large: 5

# 3. Проверяем лимит
if active_positions_count >= max_open:
    logger.debug(
        f"⚠️ Достигнут лимит открытых позиций: {active_positions_count}/{max_open}. "
        f"Пропускаем открытие {symbol}"
    )
    return  # Не открываем новую позицию
```

**Адаптивные лимиты:**

- **Micro** ($100-$500): `max_open_positions: 5`
- **Small** ($500-$1500): `max_open_positions: 5`
- **Medium** ($1500-$3000): `max_open_positions: 5`
- **Large** ($3000+): `max_open_positions: 5`

### 5.4 Действия при достижении лимита убытков

**Файл:** `src/strategies/scalping/futures/risk_manager.py` → метод `record_trade_result()`

**Логика Circuit Breaker:**

```python
def record_trade_result(
    self,
    symbol: str,
    is_profit: bool,
    error_code: Optional[str] = None,
    error_msg: Optional[str] = None,
):
    # Фильтруем технические ошибки (не считаем как убыток)
    if error_code == "51169":  # OKX error code для технических проблем
        return
    
    if is_profit:
        # Прибыль → сбрасываем серию убытков
        self.pair_loss_streak[symbol] = 0
    else:
        # Убыток → увеличиваем счетчик
        self.pair_loss_streak[symbol] = self.pair_loss_streak.get(symbol, 0) + 1
        
        # Проверяем лимит (обычно 5 убытков подряд)
        if self.pair_loss_streak[symbol] >= self._max_consecutive_losses:
            # Блокируем пару на определенное время (обычно 30 минут)
            block_until = time.monotonic() + (self._block_duration_minutes * 60)
            self.pair_block_until[symbol] = block_until
            
            logger.warning(
                f"🚫 Circuit Breaker: {symbol} заблокирован на {self._block_duration_minutes} минут "
                f"после {self.pair_loss_streak[symbol]} убытков подряд"
            )
```

**Проверка блокировки:**

```python
def is_pair_blocked(self, symbol: str) -> bool:
    if symbol not in self.pair_block_until:
        return False
    
    block_until = self.pair_block_until[symbol]
    if time.monotonic() < block_until:
        return True  # Все еще заблокирован
    
    # Блокировка истекла - удаляем
    del self.pair_block_until[symbol]
    return False
```

### 5.5 Защита от повторного входа после убытка (cooldown)

**Файл:** `config/config_futures.yaml` → `scalping.adaptive_regime.{regime}.cooldown_after_loss_minutes`

**Логика:**

```python
# Cooldown настраивается по режимам:
trending:
  cooldown_after_loss_minutes: 0.5  # 30 секунд
ranging:
  cooldown_after_loss_minutes: 1.0  # 1 минута
choppy:
  cooldown_after_loss_minutes: 1.5  # 1.5 минуты

# Применяется после закрытия убыточной позиции
# Бот не будет открывать новую позицию по этой паре в течение cooldown времени
```

**Реализация:**

- Отслеживается в `position_manager.py` при закрытии позиции
- Время последнего закрытия сохраняется в `position_registry`
- При генерации сигнала проверяется, прошло ли достаточно времени

---

## 🔹 6. Работа с OKX API

### 6.1 Клиент

**Файл:** `src/clients/futures_client.py` → класс `OKXFuturesClient`

**Тип:** Кастомный HTTP/WebSocket клиент (не официальный SDK)

**Особенности:**

- Асинхронный (`async/await`)
- Подпись запросов по стандарту OKX (HMAC-SHA256)
- Поддержка sandbox и production режимов
- Кэширование instrument details (lot sizes, ctVal)

### 6.2 Создание ордеров

**Метод:** `place_order()` в `futures_client.py`

**Market ордер:**

```python
async def place_order(
    self,
    symbol: str,
    side: str,  # "buy" или "sell"
    order_type: str,  # "market" или "limit"
    size: float,
    price: Optional[float] = None,  # Для limit ордеров
    reduce_only: bool = False,  # Только закрытие позиции
) -> Dict[str, Any]:
    """
    Размещение ордера на OKX.
    
    Endpoint: POST /api/v5/trade/order
    """
    inst_id = f"{symbol}-SWAP"  # Например, "BTC-USDT-SWAP"
    
    data = {
        "instId": inst_id,
        "tdMode": "isolated",  # Изолированная маржа
        "side": side,  # "buy" или "sell"
        "ordType": order_type,  # "market" или "limit"
        "sz": str(size),  # Размер в контрактах
        "posSide": "long" if side == "buy" else "short",
    }
    
    if order_type == "limit":
        data["px"] = str(price)
    
    if reduce_only:
        data["reduceOnly"] = True
    
    response = await self._make_request("POST", "/api/v5/trade/order", data=data)
    return response
```

**Limit ордер:**

```python
# Аналогично, но с указанием цены
data["px"] = str(price)
data["ordType"] = "limit"
```

### 6.3 Обновление стоп-лосса

**Метод:** `update_stop_loss()` в `futures_client.py` (если реализован)

**Или через размещение нового ордера:**

```python
# Закрытие позиции по стоп-лоссу
await client.place_order(
    symbol=symbol,
    side="sell" if position_side == "long" else "buy",
    order_type="market",
    size=position_size,
    reduce_only=True  # Только закрытие
)
```

**Trailing Stop Loss:**

- Реализован в `src/strategies/scalping/futures/indicators/trailing_stop_loss.py`
- Динамически обновляет уровень стоп-лосса при движении цены
- При достижении уровня → размещается market ордер на закрытие

### 6.4 Отмена ордеров

**Метод:** `cancel_order()` в `futures_client.py`

```python
async def cancel_order(
    self,
    symbol: str,
    order_id: str,
) -> Dict[str, Any]:
    """
    Отмена ордера.
    
    Endpoint: POST /api/v5/trade/cancel-order
    """
    inst_id = f"{symbol}-SWAP"
    
    data = {
        "instId": inst_id,
        "ordId": order_id,
    }
    
    response = await self._make_request("POST", "/api/v5/trade/cancel-order", data=data)
    return response
```

### 6.5 Обработка ошибок API

**Файл:** `src/clients/futures_client.py` → метод `_make_request()`

**Обработка:**

1. **Rate Limit (429):**
   ```python
   if response_status == 429:
       retry_after = int(response_headers.get("Retry-After", 1))
       await asyncio.sleep(retry_after)
       # Retry запрос
   ```

2. **Недоступность API (500, 503):**
   ```python
   if response_status in [500, 503]:
       # Exponential backoff
       await asyncio.sleep(2 ** retry_count)
       # Retry запрос
   ```

3. **Частичное исполнение:**
   ```python
   # OKX возвращает fills в ответе на ордер
   fills = order_response.get("data", [{}])[0].get("fills", [])
   
   if len(fills) > 0:
       # Ордер частично исполнен
       filled_size = sum(float(fill.get("sz", 0)) for fill in fills)
       remaining_size = total_size - filled_size
       
       if remaining_size > 0:
           # Размещаем новый ордер на оставшийся размер
   ```

4. **Ошибки OKX:**
   ```python
   # OKX возвращает код ошибки в поле "code"
   error_code = response.get("code", "0")
   error_msg = response.get("msg", "")
   
   # Известные коды:
   # "51169" - Техническая ошибка (не считаем как убыток)
   # "51000" - Параметр неверный
   # "51001" - API ключ неверный
   ```

---

## 🔹 7. Логирование и мониторинг

### 7.1 Типы логов

**Файл:** `src/main_futures.py` → настройка `loguru`

**Уровни логирования:**

- **DEBUG**: Детальная информация (индикаторы, расчеты)
- **INFO**: Основные события (открытие/закрытие позиций, сигналы)
- **WARNING**: Предупреждения (лимиты, блокировки)
- **ERROR**: Ошибки (API ошибки, критические проблемы)

**Формат:**

```python
# Консоль (INFO и выше)
logger.add(
    sys.stdout,
    level="INFO",
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
)

# Файл (DEBUG и выше)
logger.add(
    "logs/futures/futures_main_{time:YYYY-MM-DD}.log",
    level="DEBUG",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
    rotation="5 MB",
    retention="7 days",
    compression="zip",
)
```

### 7.2 Метрики (P&L, win rate, drawdown)

**Файл:** `src/strategies/scalping/spot/performance_tracker.py` → класс `PerformanceTracker`

**Метрики:**

1. **P&L (Profit & Loss):**
   ```python
   self.total_pnl = 0.0  # Общий PnL
   self.daily_pnl = 0.0  # Дневной PnL
   
   # Обновление при закрытии позиции
   def record_trade(self, trade_result: TradeResult):
       self.total_pnl += trade_result.net_pnl
       self.daily_pnl += trade_result.net_pnl
   ```

2. **Win Rate:**
   ```python
   self.total_trades = 0
   self.winning_trades = 0
   
   def record_trade(self, trade_result: TradeResult):
       self.total_trades += 1
       if trade_result.net_pnl > 0:
           self.winning_trades += 1
   
   def get_win_rate(self) -> float:
       if self.total_trades == 0:
           return 0.0
       return self.winning_trades / self.total_trades
   ```

3. **Drawdown:**
   - Не рассчитывается автоматически
   - Можно рассчитать из CSV файлов `trades_YYYY-MM-DD.csv`

**Логирование метрик:**

```python
# Периодически логируется в orchestrator
logger.info(
    f"📊 Статистика: Trades={total_trades}, "
    f"Win Rate={win_rate:.1f}%, "
    f"Total PnL=${total_pnl:.2f}, "
    f"Daily PnL=${daily_pnl:.2f}"
)
```

### 7.3 Таблица сделок (журнал исполненных ордеров)

**CSV файлы:**

1. **`trades_YYYY-MM-DD.csv`** - Закрытые сделки:
   ```csv
   timestamp,symbol,side,entry_price,exit_price,size,gross_pnl,commission,net_pnl,duration_sec,reason,win_rate
   2025-12-07 12:00:00,BTC-USDT,long,89000.0,89500.0,0.001,0.50,0.01,0.49,300,tp,55.5
   ```

2. **`positions_open_YYYY-MM-DD.csv`** - Открытые позиции:
   ```csv
   timestamp,symbol,side,entry_price,size,regime,order_id,order_type
   2025-12-07 12:00:00,BTC-USDT,long,89000.0,0.001,trending,12345,limit
   ```

3. **`orders_YYYY-MM-DD.csv`** - Размещенные ордера:
   ```csv
   timestamp,symbol,side,order_type,order_id,size,price,status,fill_price,fill_size,execution_time_ms,slippage
   2025-12-07 12:00:00,BTC-USDT,buy,limit,12345,0.001,89000.0,filled,89000.5,0.001,150,0.0006
   ```

4. **`signals_YYYY-MM-DD.csv`** - Сгенерированные сигналы:
   ```csv
   timestamp,symbol,side,price,strength,regime,filters_passed,executed,order_id
   2025-12-07 12:00:00,BTC-USDT,buy,89000.0,0.85,trending,true,true,12345
   ```

**Запись в CSV:**

```python
# В performance_tracker.py
def record_trade_result(self, trade_result: TradeResult):
    with open(self.csv_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[...])
        writer.writerow({
            "timestamp": trade_result.timestamp.isoformat(),
            "symbol": trade_result.symbol,
            "side": trade_result.side,
            "entry_price": trade_result.entry_price,
            "exit_price": trade_result.exit_price,
            "size": trade_result.size,
            "gross_pnl": trade_result.gross_pnl,
            "commission": trade_result.commission,
            "net_pnl": trade_result.net_pnl,
            "duration_sec": trade_result.duration_sec,
            "reason": trade_result.reason,
            "win_rate": self.get_win_rate(),
        })
```

---

## 🔹 8. Безопасность

### 8.1 Использование API-ключей

**Файл:** `config/config_futures.yaml`

```yaml
api:
  okx:
    api_key: "${OKX_API_KEY}"      # Из переменных окружения
    api_secret: "${OKX_API_SECRET}"
    passphrase: "${OKX_PASSPHRASE}"
```

**Загрузка:**

```python
# В src/config.py
import os
from dotenv import load_dotenv

load_dotenv()  # Загружает .env файл

# Подстановка значений
api_key = config.get("api", {}).get("okx", {}).get("api_key", "")
api_key = os.path.expandvars(api_key)  # Заменяет ${OKX_API_KEY} на значение из .env
```

**Безопасность:**

- API ключи НЕ хранятся в коде
- Используются переменные окружения (`.env` файл)
- `.env` файл добавлен в `.gitignore`
- Подпись запросов через HMAC-SHA256 (стандарт OKX)

### 8.2 Защита от случайного live-запуска

**Файл:** `src/main_futures.py`

**Проверки:**

1. **Проверка API ключей:**
   ```python
   if not config.get_okx_config().api_key or config.get_okx_config().api_key == "your_api_key_here":
       logger.error("❌ API ключ не настроен в конфигурации")
       return  # Останавливаем запуск
   ```

2. **Предупреждение о рисках:**
   ```python
   logger.warning("⚠️ ВНИМАНИЕ: Futures торговля связана с высокими рисками!")
   logger.warning("⚠️ Используйте только те средства, потерю которых можете себе позволить!")
   logger.warning("⚠️ Рекомендуется начать с sandbox режима для тестирования!")
   ```

3. **Sandbox по умолчанию:**
   - В `env.example`: `sandbox: true`
   - Пользователь должен явно установить `sandbox: false` для live торговли

**Нет дополнительной защиты** (например, подтверждение через консоль), но есть предупреждения и sandbox по умолчанию.

### 8.3 Использование песочницы OKX

**Настройка:**

```yaml
api:
  okx:
    sandbox: true  # true = demo, false = live
```

**Реализация:**

```python
# В futures_client.py
def __init__(self, api_key, secret_key, passphrase, sandbox=True, ...):
    # OKX использует один и тот же URL для sandbox и production
    # Различие только в API ключах (sandbox ключи vs production ключи)
    self.base_url = "https://www.okx.com"
    self.sandbox = sandbox
    # Sandbox ключи должны быть созданы отдельно в OKX Dashboard
```

**Рекомендация:**

- Всегда начинать с `sandbox: true`
- Тестировать стратегию на демо-счете
- Только после успешного тестирования переходить на `sandbox: false`

---

## 🔹 9. Зависимости

### 9.1 requirements.txt

```
ccxt==4.1.22                    # Библиотека для работы с криптобиржами (не используется напрямую, но может быть полезна)
okx==2.1.2                      # Официальный OKX SDK (не используется, используется кастомный клиент)
pandas==2.0.3                   # Обработка данных (OHLCV, индикаторы)
numpy==1.24.3                   # Математические расчеты (индикаторы, статистика)
aiohttp==3.8.6                  # Асинхронные HTTP запросы к OKX API
asyncio-throttle==1.0.2         # Ограничение частоты запросов (rate limiting)
tenacity==8.2.3                 # Retry логика для API запросов
pyyaml==6.0.1                   # Парсинг YAML конфигурации
python-dotenv==1.0.0            # Загрузка переменных окружения из .env
websockets==11.0.3              # WebSocket соединения для real-time данных
pydantic==2.4.2                 # Валидация конфигурации
loguru==0.7.2                   # Логирование (структурированные логи)
backtrader==1.9.78.123          # Backtesting (не используется в текущей версии)
python-telegram-bot==20.6       # Telegram уведомления (опционально)
schedule==1.2.0                 # Планировщик задач (не используется)
fastapi==0.104.1                # REST API для мониторинга (не используется)
uvicorn==0.24.0                 # ASGI сервер для FastAPI (не используется)
sqlalchemy==2.0.23              # ORM для базы данных (не используется)
alembic==1.12.1                 # Миграции БД (не используется)
redis==5.0.1                    # Кэширование (не используется)
prometheus-client==0.18.0       # Метрики Prometheus (не используется)
psutil==5.9.6                   # Мониторинг использования памяти
cachetools==6.2.2               # TTLCache для идемпотентности (предотвращение дублирования ордеров)
```

### 9.2 Ключевые библиотеки

1. **`aiohttp`**: Асинхронные HTTP запросы к OKX API
2. **`websockets`**: WebSocket для real-time данных (цены, позиции, ордера)
3. **`pandas` + `numpy`**: Расчет индикаторов (RSI, EMA, ATR, MACD)
4. **`loguru`**: Структурированное логирование
5. **`pyyaml` + `pydantic`**: Загрузка и валидация конфигурации
6. **`python-dotenv`**: Загрузка переменных окружения

---

## 🔹 10. Примеры

### 10.1 Пример записи в логе успешной сделки

**Лог файл:** `logs/futures/futures_main_2025-12-07.log`

```
2025-12-07 12:00:00 | INFO     | position_manager:close_position:3688 - 🎯 Закрытие позиции BTC-USDT (LONG)
2025-12-07 12:00:00 | INFO     | position_manager:close_position:3690 -    💰 Entry: $89,000.00 | Exit: $89,500.00
2025-12-07 12:00:00 | INFO     | position_manager:close_position:3692 -    📦 Размер: 0.001 BTC
2025-12-07 12:00:00 | INFO     | position_manager:close_position:3694 -    💵 Gross PnL: +$0.50 USDT
2025-12-07 12:00:00 | INFO     | position_manager:close_position:3696 -    💸 Комиссия: $0.01 USDT
2025-12-07 12:00:00 | INFO     | position_manager:close_position:3698 -    💸 Funding Fee: $0.00 USDT
2025-12-07 12:00:00 | INFO     | position_manager:close_position:3700 -    💵 Net PnL: +$0.49 USDT
2025-12-07 12:00:00 | INFO     | position_manager:close_position:3702 -    ⏱️ Длительность: 300 секунд (5.0 минут)
2025-12-07 12:00:00 | INFO     | position_manager:close_position:3704 -    ✅ Причина закрытия: tp (Take Profit)
2025-12-12 12:00:00 | INFO     | position_manager:close_position:3706 -    📊 Режим: trending
```

**CSV файл:** `logs/trades_2025-12-07.csv`

```csv
timestamp,symbol,side,entry_price,exit_price,size,gross_pnl,commission,net_pnl,duration_sec,reason,win_rate
2025-12-07T12:00:00+00:00,BTC-USDT,long,89000.0,89500.0,0.001,0.50,0.01,0.49,300,tp,55.5
```

### 10.2 Пример записи в логе неудачной сделки

**Лог файл:**

```
2025-12-07 12:05:00 | INFO     | position_manager:close_position:3688 - 🎯 Закрытие позиции ETH-USDT (SHORT)
2025-12-07 12:05:00 | INFO     | position_manager:close_position:3690 -    💰 Entry: $3,130.00 | Exit: $3,140.00
2025-12-07 12:05:00 | INFO     | position_manager:close_position:3692 -    📦 Размер: 0.022 ETH
2025-12-07 12:05:00 | INFO     | position_manager:close_position:3694 -    💵 Gross PnL: -$0.22 USDT
2025-12-07 12:05:00 | INFO     | position_manager:close_position:3696 -    💸 Комиссия: $0.01 USDT
2025-12-07 12:05:00 | INFO     | position_manager:close_position:3698 -    💸 Funding Fee: $0.00 USDT
2025-12-07 12:05:00 | INFO     | position_manager:close_position:3700 -    💵 Net PnL: -$0.23 USDT
2025-12-07 12:05:00 | INFO     | position_manager:close_position:3702 -    ⏱️ Длительность: 120 секунд (2.0 минут)
2025-12-07 12:05:00 | INFO     | position_manager:close_position:3704 -    ❌ Причина закрытия: sl (Stop Loss)
2025-12-07 12:05:00 | INFO     | position_manager:close_position:3706 -    📊 Режим: ranging
2025-12-07 12:05:00 | WARNING  | risk_manager:record_trade_result:200 - ⚠️ Убыток для ETH-USDT. Серия убытков: 1/5
```

**CSV файл:**

```csv
timestamp,symbol,side,entry_price,exit_price,size,gross_pnl,commission,net_pnl,duration_sec,reason,win_rate
2025-12-07T12:05:00+00:00,ETH-USDT,short,3130.0,3140.0,0.022,-0.22,0.01,-0.23,120,sl,55.0
```

### 10.3 Пример сигнала (значения индикаторов в момент входа)

**Лог файл:**

```
2025-12-07 12:00:00 | DEBUG    | signal_generator:_generate_rsi_signals:1950 - 📊 RSI для BTC-USDT: значение=28.5
2025-12-07 12:00:00 | DEBUG    | signal_generator:_generate_rsi_signals:1952 - ✅ RSI OVERSOLD сигнал для BTC-USDT: RSI=28.5 (порог=25 для trending)
2025-12-07 12:00:00 | DEBUG    | signal_generator:_generate_rsi_signals:1954 - 📊 EMA Fast: 89050.0 | EMA Slow: 88900.0 | Цена: 89000.0
2025-12-07 12:00:00 | DEBUG    | signal_generator:_generate_rsi_signals:1956 - ✅ EMA Alignment: UPTREND (ema_fast > ema_slow, цена > ema_fast)
2025-12-07 12:00:00 | DEBUG    | signal_generator:_generate_rsi_signals:1958 - 📊 ATR: 450.0 (0.51% от цены)
2025-12-07 12:00:00 | DEBUG    | signal_generator:_generate_rsi_signals:1960 - ✅ ATR фильтр пройден (min_volatility_atr=0.0004)
2025-12-07 12:00:00 | DEBUG    | signal_generator:_filter_and_rank_signals:2200 - 🎯 Сигнал BTC-USDT (BUY):
2025-12-07 12:00:00 | DEBUG    | signal_generator:_filter_and_rank_signals:2202 -    Strength: 0.85
2025-12-07 12:00:00 | DEBUG    | signal_generator:_filter_and_rank_signals:2204 -    Confidence: 0.75
2025-12-07 12:00:00 | DEBUG    | signal_generator:_filter_and_rank_signals:2206 -    Режим: trending
2025-12-07 12:00:00 | DEBUG    | signal_generator:_filter_and_rank_signals:2208 -    Фильтры: liquidity=✅, order_flow=✅, volatility=✅, funding=✅
2025-12-07 12:00:00 | DEBUG    | signal_generator:_filter_and_rank_signals:2210 -    Final Score: 1.85 (порог=1.6 для trending)
2025-12-07 12:00:00 | INFO     | signal_generator:_filter_and_rank_signals:2212 - ✅ Сигнал принят: BTC-USDT BUY @ $89,000.00
```

**CSV файл:** `logs/signals_2025-12-07.csv`

```csv
timestamp,symbol,side,price,strength,regime,filters_passed,executed,order_id
2025-12-07T12:00:00+00:00,BTC-USDT,buy,89000.0,0.85,trending,true,true,12345
```

**Значения индикаторов:**

- **RSI**: 28.5 (oversold для trending режима, порог=25)
- **EMA Fast (8)**: 89,050.0
- **EMA Slow (21)**: 88,900.0
- **Текущая цена**: 89,000.0
- **ATR**: 450.0 (0.51% от цены)
- **ADX**: 22.5 (trending режим, порог=20)
- **Order Flow**: +0.0065 (бычий поток)
- **Liquidity**: Best Bid Volume = $150, Order Book Depth = $1,200

**Результат:**

- Сигнал принят (score=1.85 > порог=1.6)
- Позиция открыта: 0.001 BTC @ $89,000.00
- TP: $91,225.00 (2.5%)
- SL: $87,665.00 (1.5%)

---

## 📝 Заключение

Этот документ описывает полную структуру и логику работы OKX Trading Bot. Бот использует адаптивную систему параметров, которая динамически подстраивается под режим рынка (Trending/Ranging/Choppy), размер баланса (Micro/Small/Medium/Large) и индивидуальные характеристики каждой торговой пары.

**Ключевые особенности:**

1. **Адаптивность**: Параметры меняются в зависимости от условий рынка
2. **Риск-менеджмент**: Множественные уровни защиты (daily loss, circuit breaker, max positions)
3. **Логирование**: Полное логирование всех операций в CSV и структурированные логи
4. **Безопасность**: Sandbox режим по умолчанию, переменные окружения для API ключей

**Рекомендации:**

- Всегда начинайте с sandbox режима
- Тестируйте стратегию на демо-счете перед live торговлей
- Регулярно анализируйте CSV файлы для оптимизации параметров
- Мониторьте логи на предмет ошибок и предупреждений

---

**Версия документа:** 1.0  
**Последнее обновление:** 2025-12-07

