# ТЗ для Cursor: Сбор и структурирование данных для аудита кода и торговой стратегии

**Версия:** 1.2  
**Дата:** 2025-12-07  
**Последнее обновление:** 2025-12-07  
**Назначение:** Инструкция для Cursor по сбору данных для внешнего аналитика (Kimi)

---

## 1. Цель

Сформировать унифицированный «пакет данных» (далее – **Пакет**), который будет отправлен внешнему аналитику (Kimi) для:

- **аудита качества кода** (data quality audit);
- **аудита логики торговой стратегии** (strategy logic audit);
- **расчёта метрик до- и после-ковки** (pre/post-burn analysis);
- **выявления потенциальных утечек/оверфиттинга**.

---

## 2. Общие правила сбора

### 2.1. Запрашивать файлы строго в порядке, указанном в разделе 3

### 2.2. После получения каждого файла сразу:

1. **Проверять наличие обязательных колонок** (см. раздел 4);
2. **Фиксировать метаданные:**
   - `shape`: (rows, columns)
   - `date_modified`: дата последнего изменения файла
   - `md5_hash`: MD5-хеш файла (для проверки целостности) **ПОСЛЕ редактирования секретов** (см. п.7.0.5)
   - `file_size_bytes`: размер файла в байтах
3. **Записывать краткий словарь:**
   - Название каждой колонки
   - Тип данных (int, float, str, datetime)
   - Единицы измерения (USDT, BTC, %, и т.д.)
   - Частота дискретности (tick, 1m, 1h, 1d)
   - Описание назначения колонки
4. **Проверка блокировки файла:**
   - Если `PermissionError` → попросить пользователя сделать копию (см. п.7.0.7)
5. **Обработка Parquet:**
   - Если файл `.parquet` и путь указывает на директорию → использовать `pyarrow.dataset` (см. п.7.0.8)

### 2.3. Если обязательная колонка отсутствует или пуста

- **Останавливаться** и спрашивать у пользователя, как заполнять/исправлять
- Записывать проблему в `integrity_errors.json`
- Не продолжать сбор до исправления

### 2.4. Все пути к файлам внутри Пакета хранить относительно корня проекта

**Пример:**
```json
{
  "file_path": "logs/trades_2025-12-07.csv",
  "absolute_path": "C:/Users/krivo/simple trading bot okx/logs/trades_2025-12-07.csv"
}
```

### 2.5. Итоговый Пакет сохранять в `audit_bundle_<YYYYMMDD>_<strategy_name>.json`

**Формат имени:**
- `YYYYMMDD`: дата создания пакета (например, 20251207)
- `strategy_name`: название стратегии из конфига (например, `futures_scalping`)

**Пример:** `audit_bundle_20251207_futures_scalping.json`

**Структура JSON описана в разделе 6.**

---

## 3. Последовательность запроса файлов

### 3.1. Конфигурационный файл стратегии

**Название:** `config.*` (yaml, json, py, toml – любой)

**Путь:** `config/config_futures.yaml` (или аналогичный)

**Что вытащить:**

```yaml
# Параметры входа/выхода
- tp_percent, sl_percent (Take Profit / Stop Loss)
- partial_tp (частичное закрытие)
- order_type (limit/market)

# Фильтры
- liquidity_filter (min_best_bid_volume_usd, min_orderbook_depth_usd)
- order_flow_filter (long_threshold, short_threshold)
- volatility_filter (min_atr_percent, max_range_percent)
- funding_rate_filter (max_positive_rate, max_negative_rate)

# Лимиты
- max_open_positions
- max_daily_loss_percent
- consecutive_losses_limit
- risk_per_trade_percent

# Рычаг (leverage)
- leverage (по умолчанию 5x)

# Комиссия
- commission.trading_fee_rate
- commission.maker_fee_rate
- commission.taker_fee_rate

# Slippage
- commission.slippage_buffer_percent

# Режим ребалансировки
- adaptive_regime (trending/ranging/choppy)
- balance_profiles (micro/small/medium/large)
- symbol_profiles (per-symbol настройки)
```

**Структура в JSON:**
```json
{
  "config": {
    "file_path": "config/config_futures.yaml",
    "entry_exit_params": {...},
    "filters": {...},
    "limits": {...},
    "leverage": 5,
    "commission": {...},
    "slippage": {...},
    "rebalancing_mode": {...}
  }
}
```

---

### 3.2. Исходный код стратегии

**Название:** `strategy.py` (или аналог)

**Путь:** `src/strategies/scalping/futures/` (основные файлы)

**Что вытащить:**

#### 3.2.1. Список всех используемых DataFrame/arrays и их колонок

**Файлы для анализа:**
- `signal_generator.py` - генерация сигналов
- `position_manager.py` - управление позициями
- `order_executor.py` - исполнение ордеров
- `risk_manager.py` - управление рисками
- `orchestrator.py` - главный координатор

**Пример структуры:**
```json
{
  "data_structures": {
    "signal_generator": {
      "market_data": {
        "ohlcv_data": ["timestamp", "open", "high", "low", "close", "volume"],
        "order_book": ["bids", "asks", "best_bid", "best_ask"],
        "trades": ["timestamp", "price", "size", "side"]
      },
      "indicators": {
        "rsi": ["value", "period", "overbought", "oversold"],
        "ema": ["fast", "slow", "period"],
        "atr": ["value", "period"]
      }
    }
  }
}
```

#### 3.2.2. Список всех констант, хардкода, магических чисел

**Искать в коде:**
- Числовые константы (например, `0.5`, `1.2`, `100`)
- Строковые константы (например, `"trending"`, `"long"`)
- Хардкод значений (например, `max_size = 100.0`)

**Пример:**
```json
{
  "constants": {
    "signal_generator.py": {
      "rsi_default_period": 14,
      "ema_fast_default": 12,
      "ema_slow_default": 26,
      "atr_default_period": 14
    },
    "risk_manager.py": {
      "kelly_fraction_limit": 0.25,
      "max_kelly_percent": 0.1
    }
  }
}
```

#### 3.2.3. Наличие random_state/seed-ов

**Искать:**
- `random.seed()`
- `np.random.seed()`
- `random_state=` в функциях
- Любые источники случайности

**Пример:**
```json
{
  "random_sources": {
    "signal_generator.py": {
      "line": 123,
      "code": "np.random.seed(42)",
      "purpose": "Инициализация генератора случайных чисел"
    }
  }
}
```

#### 3.2.4. Наличие forward-looking (закомментировать строки и regex-паттерны)

**Искать:**

1. **Закомментированные строки:**
   - Использование будущих данных для текущих решений
   - Обращение к `data[i+1]` или `data[t+1]`
   - Использование данных после текущего timestamp

2. **Regex-паттерны (см. п.7.0.4):**
   - `df.shift(-1)` - сдвиг назад
   - `iloc[i+1]` - обращение к будущему индексу
   - `loc[t + pd.Timedelta(...)]` - обращение к будущему времени
   - Слова: `future`, `ahead`, `lead`, `next_bar`, `tomorrow`

**Пример:**
```json
{
  "forward_looking": {
    "position_manager.py": {
      "line": 456,
      "code": "# current_price = future_data[timestamp + 1]  # ⚠️ FORWARD LOOKING",
      "pattern": "iloc\\s*\\[\\s*.+\\s*\\+\\s*\\d+\\s*\\]",
      "severity": "critical",
      "description": "Использование будущей цены для текущего решения"
    },
    "signal_generator.py": {
      "line": 789,
      "code": "price_future = data.shift(-1)['close']",
      "pattern": "df\\.shift\\s*\\(\\s*-\\d+\\s*\\)",
      "severity": "critical",
      "description": "Сдвиг данных назад (forward-looking)"
    }
  }
}
```

---

### 3.3. Журнал сделок (executions)

**Название:** `trades.csv` (или parquet)

**Путь:** `logs/trades_YYYY-MM-DD.csv`

**Обязательные колонки:**

| Колонка | Тип | Описание | Единицы |
|---------|-----|----------|---------|
| `trade_id` | str | Уникальный ID сделки | - |
| `timestamp` | datetime | Время закрытия позиции | UTC |
| `symbol` | str | Торговая пара | - |
| `side` | str | Направление (long/short) | - |
| `entry_price` | float | Цена входа | USDT |
| `exit_price` | float | Цена выхода | USDT |
| `size` | float | Размер позиции | контракты |
| `gross_pnl` | float | Валовая прибыль/убыток | USDT |
| `commission` | float | Комиссия | USDT |
| `net_pnl` | float | Чистая прибыль/убыток | USDT |
| `duration_sec` | int | Длительность позиции | секунды |
| `reason` | str | Причина закрытия | - |

**Дополнительные колонки (если есть):**

- `strategy_id` - ID стратегии
- `account_id` - ID аккаунта
- `tags` - Теги для категоризации
- `funding_fee` - Funding fee для Futures (может быть отрицательным, если получен)
- `contract_id` - ID контракта для экспирируемых фьючерсов (например, "BTC-USDT-250320") - см. п.7.0.17
- `regime` - Режим рынка (trending/ranging/choppy)
- `balance_profile` - Профиль баланса (micro/small/medium/large)

**Структура в JSON:**
```json
{
  "trades": {
    "file_path": "logs/trades_2025-12-07.csv",
    "shape": [141, 12],
    "date_modified": "2025-12-07T12:00:00Z",
    "md5_hash": "abc123...",
    "columns": {
      "trade_id": {"type": "str", "required": true},
      "timestamp": {"type": "datetime", "required": true, "frequency": "event"},
      "symbol": {"type": "str", "required": true},
      "side": {"type": "str", "required": true, "values": ["long", "short"]},
      "entry_price": {"type": "float", "required": true, "units": "USDT"},
      "exit_price": {"type": "float", "required": true, "units": "USDT"},
      "size": {"type": "float", "required": true, "units": "contracts"},
      "gross_pnl": {"type": "float", "required": true, "units": "USDT"},
      "commission": {"type": "float", "required": true, "units": "USDT"},
      "net_pnl": {"type": "float", "required": true, "units": "USDT"},
      "duration_sec": {"type": "int", "required": true, "units": "seconds"},
      "reason": {"type": "str", "required": true}
    },
    "date_range": {
      "start": "2025-12-07T00:00:00Z",
      "end": "2025-12-07T23:59:59Z"
    },
    "symbols": ["BTC-USDT", "ETH-USDT", "SOL-USDT", "DOGE-USDT", "XRP-USDT"],
    "total_trades": 141,
    "winning_trades": 78,
    "losing_trades": 63
  }
}
```

---

### 3.4. Маркет-дата, на которую была запущена стратегия

**Название:** `market_data.csv` (или parquet)

**Путь:** Может быть в `data/` или получаться через WebSocket (нужно уточнить у пользователя)

**Обязательные колонки:**

| Колонка | Тип | Описание | Единицы |
|---------|-----|----------|---------|
| `timestamp` | datetime | Время свечи | UTC |
| `symbol` | str | Торговая пара | - |
| `open` | float | Цена открытия | USDT |
| `high` | float | Максимальная цена | USDT |
| `low` | float | Минимальная цена | USDT |
| `close` | float | Цена закрытия | USDT |
| `volume` | float | Объем торгов | контракты |
| `bid` | float | Лучшая цена покупки | USDT |
| `ask` | float | Лучшая цена продажи | USDT |
| `quote_currency` | str | Квотируемая валюта (USDT/USDC/BTC) | - |

**Частота:** Минимальная, которую использует стратегия

**Если смешанная частота** – разложить по файлам:
- `market_1m.csv` - 1-минутные свечи
- `market_5m.csv` - 5-минутные свечи
- `market_1h.csv` - 1-часовые свечи
- `market_1d.csv` - дневные свечи

**Структура в JSON:**
```json
{
  "market_data": {
    "1m": {
      "file_path": "data/market_1m_2025-12-07.csv",
      "shape": [1440, 9],  # 1440 минут в сутках
      "frequency": "1m",
      "columns": {...},
      "date_range": {...}
    },
    "5m": {
      "file_path": "data/market_5m_2025-12-07.csv",
      "shape": [288, 9],  # 288 пятиминуток в сутках
      "frequency": "5m",
      "columns": {...}
    }
  }
}
```

**Если маркет-дата получается через WebSocket в реальном времени:**

- Запросить у пользователя, есть ли сохраненные исторические данные
- Если нет – отметить в `integrity_errors.json`: "Market data obtained via WebSocket, no historical file available"
- Запросить период, за который нужны данные для анализа

---

### 3.5. Позиционный лог (positions)

**Название:** `positions.csv` или `positions_open_YYYY-MM-DD.csv`

**Путь:** `logs/positions_open_YYYY-MM-DD.csv`

**Обязательные колонки:**

| Колонка | Тип | Описание | Единицы |
|---------|-----|----------|---------|
| `timestamp` | datetime | Время открытия позиции | UTC |
| `symbol` | str | Торговая пара | - |
| `side` | str | Направление (long/short) | - |
| `entry_price` | float | Средняя цена входа | USDT |
| `size` | float | Размер позиции | контракты |
| `regime` | str | Режим рынка | - |
| `order_id` | str | ID ордера открытия | - |
| `order_type` | str | Тип ордера (limit/market) | - |

**Дополнительные колонки (если есть):**

- `mtm_price` - Mark-to-market цена
- `margin` - Использованная маржа (может быть > balance при cross_margin)
- `leverage` - **ОБЯЗАТЕЛЬНО:** Леверидж позиции (нужен для расчета маржи)
- `cross_margin` - Флаг кросс-маржинальной позиции (true/false) - см. п.7.0.18
- `position_mode` - Режим позиции (hedge/netting) - см. п.7.0.19
- `unrealized_pnl` - Нереализованный PnL

**Структура в JSON:**
```json
{
  "positions": {
    "file_path": "logs/positions_open_2025-12-07.csv",
    "shape": [25, 8],
    "columns": {...},
    "date_range": {...},
    "total_positions": 25,
    "open_positions": 3,
    "closed_positions": 22
  }
}
```

---

### 3.6. Логи заявок (orders)

**Название:** `orders.csv` или `orders_YYYY-MM-DD.csv`

**Путь:** `logs/orders_YYYY-MM-DD.csv`

**Обязательные колонки:**

| Колонка | Тип | Описание | Единицы |
|---------|-----|----------|---------|
| `order_id` | str | Уникальный ID ордера | - |
| `timestamp` | datetime | Время размещения ордера | UTC |
| `symbol` | str | Торговая пара | - |
| `side` | str | Направление (buy/sell) | - |
| `order_type` | str | Тип ордера (limit/market) | - |
| `size` | float | Размер ордера | контракты |
| `price` | float | Цена ордера | USDT |
| `status` | str | Статус (filled/partially_filled/cancelled/rejected) | - |
| `fill_price` | float | Цена исполнения | USDT |
| `fill_size` | float | Исполненный размер | контракты |
| `execution_time_ms` | int | Время исполнения | миллисекунды |
| `slippage` | float | Проскальзывание | USDT или % |
| `slippage_units` | str | Единицы slippage (abs/pct) | - |
| `avg_fill_price` | float | Средняя цена исполнения (для partial fills) | USDT |
| `time_in_force` | str | Время жизни ордера (GTC/IOC/FOK/GTD) | - |
| `fill_id` | str | ID частичного исполнения | - |

**Дополнительные колонки (если есть):**

- `timestamp_fill` - Время исполнения
- `reject_reason` - Причина отклонения
- `maker_taker` - Maker или Taker
- `fee` - Комиссия за ордер
- `trigger_price` - Цена триггера для стоп-ордеров (обязательна для stop_market/stop_limit) - см. п.7.0.20

**Структура в JSON:**
```json
{
  "orders": {
    "file_path": "logs/orders_2025-12-07.csv",
    "shape": [156, 12],
    "columns": {...},
    "date_range": {...},
    "total_orders": 156,
    "filled_orders": 142,
    "cancelled_orders": 10,
    "rejected_orders": 4
  }
}
```

---

### 3.7. Экзогенные данные (если использовались)

**Примеры файлов:**

- `funding.csv` - Funding rates для Futures
- `borrow_rates.csv` - Процентные ставки заимствования
- `options_chain.csv` - Данные опционов
- `economic_calendar.csv` - Экономический календарь

**Для каждого файла повторить пункт 2.2:**

1. Проверить обязательные колонки
2. Зафиксировать метаданные (shape, date_modified, md5_hash)
3. Записать словарь колонок

**Структура в JSON:**
```json
{
  "exogenous_data": {
    "funding": {
      "file_path": "data/funding_2025-12-07.csv",
      "shape": [120, 4],
      "columns": {
        "timestamp": {"type": "datetime", "frequency": "8h"},
        "symbol": {"type": "str"},
        "funding_rate": {"type": "float", "units": "%"},
        "next_funding_time": {"type": "datetime"}
      }
    }
  }
}
```

**Если экзогенные данные не используются:**

- Отметить: `"exogenous_data": {"used": false}`

---

### 3.8. Файл параметров ковки/оптимизации (если запускали оптим)

**Название:** `burn_params.json` или аналогичный

**Путь:** Может быть в `data/` или `reports/`

**Что вытащить:**

```json
{
  "burn_params": {
    "file_path": "data/burn_params.json",
    "optimization_method": "grid_search",  // или "bayesian", "genetic", "random"
    "metric": "sharpe_ratio",  // или "calmar", "profit_factor", "max_dd"
    "iterations": 1000,
    "seed": 42,
    "parameter_ranges": {
      "tp_percent": {"min": 1.0, "max": 5.0, "step": 0.1},
      "sl_percent": {"min": 0.5, "max": 2.0, "step": 0.1},
      "rsi_period": {"min": 10, "max": 20, "step": 1},
      "min_score_threshold": {"min": 1.0, "max": 3.0, "step": 0.1}
    },
    "train_period": {
      "start": "2025-11-01",
      "end": "2025-11-30"
    },
    "validation_period": {
      "start": "2025-12-01",
      "end": "2025-12-07"
    },
    "walk_forward": false,  // или true, если использовался walk-forward
    "walk_forward_window": null,  // размер окна для walk-forward
    "walk_forward_step": null  // шаг для walk-forward
  }
}
```

**Если оптимизация не проводилась:**

- Отметить: `"burn_params": {"used": false}`

---

### 3.9. Результаты ковки

**Название:** `burn_results.csv` или аналогичный

**Путь:** Может быть в `data/` или `reports/`

**Обязательные колонки:**

| Колонка | Тип | Описание |
|---------|-----|----------|
| `iteration` | int | Номер итерации |
| `params_json` | str | JSON строка с параметрами |
| `train_sharpe` | float | Sharpe ratio на тренировочной выборке |
| `val_sharpe` | float | Sharpe ratio на валидационной выборке |
| `train_max_dd` | float | Максимальная просадка на тренировочной выборке |
| `val_max_dd` | float | Максимальная просадка на валидационной выборке |
| `train_pnl` | float | PnL на тренировочной выборке |
| `val_pnl` | float | PnL на валидационной выборке |

**Дополнительные колонки (если есть):**

- `train_sortino`, `val_sortino` - Sortino ratio
- `train_calmar`, `val_calmar` - Calmar ratio
- `train_win_rate`, `val_win_rate` - Win rate
- `train_profit_factor`, `val_profit_factor` - Profit factor

**Структура в JSON:**
```json
{
  "burn_results": {
    "file_path": "data/burn_results.csv",
    "shape": [1000, 8],
    "columns": {...},
    "best_iteration": 456,
    "best_val_sharpe": 2.34,
    "best_params": {
      "tp_percent": 2.5,
      "sl_percent": 1.2,
      "rsi_period": 14
    }
  }
}
```

**Если ковка не проводилась:**

- Отметить: `"burn_results": {"used": false}`

---

### 3.10. Итоговая статистика по стратегии

**Название:** `performance_report.yaml` или аналогичный

**Путь:** Может быть в `reports/` или рассчитываться из `trades.csv`

**Что вытащить:**

```yaml
# Полный набор метрик
metrics:
  sharpe_ratio: 1.85
  sortino_ratio: 2.12
  calmar_ratio: 3.45
  cagr: 45.6  # Compound Annual Growth Rate (%)
  max_drawdown: -12.3  # Максимальная просадка (%)
  max_drawdown_duration: 5  # Длительность просадки (дни)
  win_rate: 55.3  # Процент прибыльных сделок (%)
  profit_factor: 1.65  # Отношение прибыли к убыткам
  avg_trade: 0.45  # Средняя прибыль на сделку (USDT)
  avg_winning_trade: 1.25  # Средняя прибыльная сделка (USDT)
  avg_losing_trade: -0.85  # Средняя убыточная сделка (USDT)
  avg_bars_in_trade: 15.3  # Среднее количество баров в сделке
  total_trades: 141
  winning_trades: 78
  losing_trades: 63
  total_pnl: 63.45  # Общий PnL (USDT)
  total_commission: 2.82  # Общая комиссия (USDT)
  net_pnl: 60.63  # Чистый PnL (USDT)

# Период расчёта
period:
  start: "2025-12-01"
  end: "2025-12-07"
  days: 7

# Benchmark (если есть)
benchmark:
  name: "BTC-USDT Buy & Hold"
  return: 2.5  # Доходность benchmark (%)
  sharpe: 0.8

# Дополнительные метрики
additional:
  max_consecutive_wins: 8
  max_consecutive_losses: 5
  largest_win: 5.25  # USDT
  largest_loss: -2.10  # USDT
  avg_holding_time_minutes: 12.5
```

**Если файла нет, но есть `trades.csv`:**

- Рассчитать метрики из `trades.csv`
- Использовать стандартные формулы:
  - Sharpe = (mean(returns) / std(returns)) * sqrt(252)
  - Sortino = (mean(returns) / std(negative_returns)) * sqrt(252)
  - Calmar = CAGR / abs(max_drawdown)
  - Win Rate = winning_trades / total_trades
  - Profit Factor = sum(winning_pnl) / abs(sum(losing_pnl))

**Структура в JSON:**
```json
{
  "performance_report": {
    "file_path": "reports/performance_report_2025-12-07.yaml",
    "metrics": {...},
    "period": {...},
    "benchmark": {...}
  }
}
```

---

## 4. Проверки целостности (обязательные колонки)

### 4.1. Для каждого файла из п.3 проверить:

#### 4.1.1. Отсутствие дубликатов по ключевым ключам

**Для `trades.csv`:**
- `trade_id` должен быть уникальным
- `(timestamp, symbol, side)` не должно дублироваться

**Для `orders.csv`:**
- Уникален `(order_id, fill_id)` или `(order_id, timestamp_fill)` (для partial fills)
- Если `fill_id` отсутствует → агрегировать до одной строки с `avg_fill_price` (см. п.7.0.9)

**Для `positions.csv`:**
- `(timestamp, symbol, side)` не должно дублироваться (одна позиция на момент времени)

**Для `market_data.csv`:**
- `(timestamp, symbol)` не должно дублироваться
- **Исключение:** OKX "касание" последней свечи (разница в 1 секунду) → не считать дублем (см. п.7.0.10)
- **Исключение:** Незакрытая свеча (`close == prev_close` и `volume == 0`) → пропускать, не считать дублем (см. п.4.1.6)
- **Исключение:** DST переходы (02:00-03:00 UTC в марте/октябре) → предупреждение, не ошибка (см. п.7.0.6)

**Если найдены дубликаты:**

```json
{
  "integrity_errors": {
    "trades.csv": {
      "duplicates": {
        "trade_id": {
          "count": 2,
          "examples": ["trade_123", "trade_123"],
          "lines": [45, 67]
        }
      }
    }
  }
}
```

#### 4.1.2. Отсутствие пропусков в обязательных полях

**Проверить:**
- Нет `NaN`, `None`, пустых строк в обязательных колонках
- Нет `0` в числовых полях, где `0` недопустим (например, `price`, `size`)
- **Исключение:** Если `file_size_bytes == 0` → см. п.4.1.7 (zero-byte файлы)

**Если найдены пропуски:**

```json
{
  "integrity_errors": {
    "trades.csv": {
      "missing_values": {
        "entry_price": {
          "count": 3,
          "lines": [12, 34, 56],
          "values": [null, NaN, ""]
        }
      }
    }
  }
}
```

#### 4.1.3. Монотонность timestamp

**Проверить:**
- `timestamp` должен быть отсортирован по возрастанию
- Нет "прыжков назад" во времени

**Если найдены нарушения:**

```json
{
  "integrity_errors": {
    "trades.csv": {
      "timestamp_monotonicity": {
        "violations": [
          {
            "line": 45,
            "timestamp": "2025-12-07T12:00:00Z",
            "previous_timestamp": "2025-12-07T12:05:00Z",
            "issue": "Timestamp goes backwards"
          }
        ]
      }
    }
  }
}
```

#### 4.1.4. Корректность знаков qty

**Проверить:**
- Для `side == "long"`: `qty > 0` или `size > 0`
- Для `side == "short"`: `qty < 0` или `size < 0` (для Futures)

**Если найдены нарушения:**

```json
{
  "integrity_errors": {
    "trades.csv": {
      "qty_signs": {
        "violations": [
          {
            "line": 23,
            "side": "long",
            "size": -0.001,
            "issue": "Long position has negative size"
          }
        ]
      }
    }
  }
}
```

#### 4.1.5. Корректность цен

**Проверить:**
- `high >= max(open, close)`
- `low <= min(open, close)`
- `bid <= ask` (для order book данных)
- `price_open > 0` и `price_close > 0`
- `exit_price` для LONG должен быть >= `entry_price` (если прибыль) или <= `entry_price` (если убыток)
- `exit_price` для SHORT должен быть <= `entry_price` (если прибыль) или >= `entry_price` (если убыток)

**Если найдены нарушения:**

```json
{
  "integrity_errors": {
    "market_data.csv": {
      "price_consistency": {
        "violations": [
          {
            "line": 123,
            "symbol": "BTC-USDT",
            "high": 89000.0,
            "close": 89500.0,
            "issue": "high < close"
          }
        ]
      }
    },
    "trades.csv": {
      "price_consistency": {
        "violations": [
          {
            "line": 45,
            "symbol": "BTC-USDT",
            "side": "long",
            "entry_price": 89000.0,
            "exit_price": 88500.0,
            "net_pnl": 0.50,
            "issue": "Long position: exit < entry but net_pnl > 0 (inconsistent)"
          }
        ]
      }
    }
  }
}
```

#### 4.1.6. Незакрытая свеча (OKX "касание")

**Проблема:** OKX отдает последнюю незакрытую 1-минутку с тем же timestamp, что и предыдущая закрытая. Может дать дубль при подписке на publicChannel.

**Проверить:**
- Если `(timestamp, symbol)` дублируются в `market_data.csv`
- Но `close == prev_close` И `volume == 0` → это незакрытая свеча, не дубль
- Пропускать строку, не считать ошибкой

**Пример:**
```json
{
  "integrity_errors": {
    "market_data.csv": {
      "unclosed_candles": {
        "info": [
          {
            "line": 1440,
            "timestamp": "2025-12-07T23:59:00Z",
            "symbol": "BTC-USDT",
            "close": 89000.0,
            "prev_close": 89000.0,
            "volume": 0.0,
            "issue": "Unclosed candle (OKX 'touching' behavior) - skipping, not an error"
          }
        ]
      }
    }
  }
}
```

#### 4.1.7. Zero-byte файлы

**Проблема:** Бот иногда создает `touch trades.csv` до первой сделки. Файл существует, но пустой.

**Проверить:**
- Если `file_size_bytes == 0` → статус `"missing"`, пропустить файл, не считать ошибкой
- Уведомить пользователя, что файл пустой

**Пример:**
```json
{
  "integrity_errors": {
    "trades.csv": {
      "status": "missing",
      "reason": "File is empty (zero-byte), no trades recorded yet",
      "file_size_bytes": 0
    }
  }
}
```

### 4.2. Если проверка не прошла

1. **Записать ошибки в `integrity_errors.json`**
2. **Не включать файл в Пакет до исправления**
3. **Спросить у пользователя, как исправить**

**Структура `integrity_errors.json`:**

```json
{
  "file": "trades.csv",
  "errors": {
    "duplicates": {...},
    "missing_values": {...},
    "timestamp_monotonicity": {...},
    "qty_signs": {...},
    "price_consistency": {...}
  },
  "status": "blocked",  // или "warning" если не критично
  "recommendation": "Remove duplicate trade_id entries or merge them"
}
```

---

## 5. Дополнительные метаданные

### 5.1. Окружение

**Собрать информацию:**

```json
{
  "environment": {
    "python_version": "3.11.5",
    "os": "Windows 10.0.26200",
    "cpu": "Intel Core i7-9700K",
    "ram_gb": 32,
    "pip_freeze": [
      "aiohttp==3.8.6",
      "pandas==2.0.3",
      "numpy==1.24.3",
      ...
    ]
  }
}
```

**Команды для сбора:**

```bash
python --version
pip freeze > pip_freeze.txt
# OS, CPU, RAM - из системных команд или psutil
```

### 5.2. Версия библиотеки бэктеста

**Проверить:**

- Используется ли `backtrader`, `vectorbt`, `zipline`, `backtest.py`, или собственный фреймворк
- Версия библиотеки

```json
{
  "backtest_framework": {
    "name": "custom",  // или "backtrader", "vectorbt", и т.д.
    "version": null,  // если custom
    "description": "Custom futures scalping framework with real-time WebSocket data"
  }
}
```

**Для данного проекта:** Собственный фреймворк (нет внешней библиотеки бэктеста)

### 5.3. Таймзона биржи и таймзона стратегии

```json
{
  "timezone": {
    "exchange": "UTC",  // OKX использует UTC
    "strategy": "UTC",  // Бот использует UTC (timezone.utc)
    "local": "Europe/Moscow",  // Таймзона пользователя (опционально)
    "note": "All timestamps in logs are UTC"
  }
}
```

### 5.4. Способ торговли

```json
{
  "trading_mode": {
    "type": "live",  // или "paper", "dry-run", "sandbox"
    "sandbox": true,  // true если используется sandbox OKX
    "description": "Live trading on OKX sandbox (demo account)"
  }
}
```

### 5.5. Лимиты биржи

```json
{
  "exchange_limits": {
    "exchange": "OKX",
    "min_lot_size": {
      "BTC-USDT": {
        "lot_size": 0.01,
        "min_lot": 1,
        "lot_multiplier": 0.01
      },
      "ETH-USDT": {
        "lot_size": 0.1,
        "min_lot": 1,
        "lot_multiplier": 0.1
      }
    },
    "price_step": {
      "BTC-USDT": 0.1,
      "ETH-USDT": 0.01,
      "SOL-USDT": 0.001,
      "DOGE-USDT": 0.00001,
      "XRP-USDT": 0.0001
    },
    "commission": {
      "maker": 0.0002,  // 0.02% для VIP0
      "taker": 0.0005,  // 0.05% для VIP0
      "fee_level": "VIP0",  // Или VIP1, VIP2, VIP3
      "source": "config"  // Или "api"
    },
    "order_lifetime": ["GTC", "IOC", "FOK", "GTD"],  // Возможные значения
    "leverage": {
      "max": 125,
      "used": 5
    }
  }
}
```

**Источник:** Конфиг или документация OKX

**Важно:**
- Комиссия зависит от VIP уровня (см. п.7.0.13)
- Запросить `fee_level` у пользователя или парсить из API
- Добавить `lot_multiplier` для проверки кратности размера (см. п.7.0.14)

### 5.6. Режим кеширования данных

```json
{
  "data_caching": {
    "mode": "memory",  // или "disk", "db", "none"
    "description": "Market data cached in memory (DataRegistry), positions cached in PositionRegistry",
    "cache_ttl_seconds": 300,  // Time-to-live для кеша
    "persistence": false  // Сохраняется ли кеш на диск
  }
}
```

---

## 6. Финальная структура audit_bundle_<YYYYMMDD>_<strategy_name>.json

### 6.1. Полная структура JSON

```json
{
  "metadata": {
    "bundle_id": "audit_bundle_20251207_futures_scalping",
    "created_at": "2025-12-07T15:30:00Z",
    "created_by": "Cursor AI",
    "strategy_name": "futures_scalping",
    "strategy_version": "1.0",
    "project_root": "C:/Users/krivo/simple trading bot okx"
  },
  
  "environment": {
    "python_version": "3.11.5",
    "os": "Windows 10.0.26200",
    "cpu": "Intel Core i7-9700K",
    "ram_gb": 32,
    "pip_freeze": [...]
  },
  
  "backtest_framework": {
    "name": "custom",
    "version": null,
    "description": "Custom futures scalping framework"
  },
  
  "timezone": {
    "exchange": "UTC",
    "strategy": "UTC",
    "local": "Europe/Moscow"
  },
  
  "trading_mode": {
    "type": "live",
    "sandbox": true,
    "description": "Live trading on OKX sandbox"
  },
  
  "exchange_limits": {...},
  
  "data_caching": {...},
  
  "config": {
    "file_path": "config/config_futures.yaml",
    "entry_exit_params": {...},
    "filters": {...},
    "limits": {...},
    "leverage": 5,
    "commission": {...},
    "slippage": {...},
    "rebalancing_mode": {...}
  },
  
  "source_code": {
    "data_structures": {...},
    "constants": {...},
    "random_sources": {...},
    "forward_looking": {...}
  },
  
  "trades": {
    "file_path": "logs/trades_2025-12-07.csv",
    "shape": [141, 12],
    "date_modified": "2025-12-07T12:00:00Z",
    "md5_hash": "abc123...",
    "columns": {...},
    "date_range": {...},
    "symbols": [...],
    "total_trades": 141,
    "winning_trades": 78,
    "losing_trades": 63,
    "missing": false
  },
  
  "market_data": {
    "1m": {
      "file_path": "data/market_1m_2025-12-07.csv",
      "shape": [1440, 9],
      "frequency": "1m",
      "columns": {...},
      "date_range": {...},
      "missing": false
    }
  },
  
  "positions": {
    "file_path": "logs/positions_open_2025-12-07.csv",
    "shape": [25, 8],
    "columns": {...},
    "date_range": {...},
    "total_positions": 25,
    "missing": false
  },
  
  "orders": {
    "file_path": "logs/orders_2025-12-07.csv",
    "shape": [156, 12],
    "columns": {...},
    "date_range": {...},
    "total_orders": 156,
    "missing": false
  },
  
  "exogenous_data": {
    "used": true,
    "funding": {
      "file_path": "data/funding_2025-12-07.csv",
      "shape": [120, 4],
      "columns": {...},
      "missing": false
    }
  },
  
  "burn_params": {
    "used": false,
    "missing": true,
    "reason": "No optimization was performed"
  },
  
  "burn_results": {
    "used": false,
    "missing": true,
    "reason": "No optimization was performed"
  },
  
  "performance_report": {
    "file_path": "reports/performance_report_2025-12-07.yaml",
    "metrics": {...},
    "period": {...},
    "benchmark": {...},
    "missing": false
  },
  
  "integrity_errors": {
    "trades.csv": {
      "status": "clean",
      "errors": {}
    },
    "orders.csv": {
      "status": "warning",
      "errors": {
        "missing_values": {
          "slippage": {
            "count": 5,
            "lines": [12, 34, 56, 78, 90]
          }
        }
      }
    }
  },
  
  "summary": {
    "total_trades": 141,
    "total_days": 7,
    "sharpe_ratio": 1.85,
    "win_rate": 55.3,
    "total_pnl_usd": 60.63,
    "files_included": 6,
    "files_missing": 2,
    "integrity_status": "clean"  // или "warnings", "errors"
  }
}
```

---

## 7. Дополнительные технические проверки

### 7.0. Критические технические детали

#### 7.0.1. Contract Multiplier и Quote Currency

**Проблема:** Для фьючерсов разный `contract_multiplier` (BTC=0.01, ETH=0.1). Без этого нельзя правильно рассчитать объем в USDT.

**Решение:**

1. **Запросить у пользователя CSV-файл `instruments.csv`:**
   - Можно выгрузить из OKX API: `/api/v5/public/instruments`
   - Обязательные колонки:
     - `symbol` - Торговая пара (например, "BTC-USDT-SWAP")
     - `ctVal` - Contract value (например, 0.01 для BTC)
     - `ctMult` - Contract multiplier (обычно 1.0)
     - `quoteCcy` - Quote currency (например, "USDT", "USDC", "BTC")
     - `lotSz` - Lot size (например, 1.0)
     - `tickSz` - Tick size (например, 0.1)

2. **Добавить в `market_data` мета-таблицу:**
   ```json
   {
     "market_data": {
       "1m": {
         "file_path": "data/market_1m_2025-12-07.csv",
         "instruments_metadata": {
           "BTC-USDT": {
             "contract_value": 0.01,
             "contract_multiplier": 1.0,
             "quote_currency": "USDT",
             "lot_size": 1.0,
             "tick_size": 0.1
           }
         }
       }
     }
   }
   ```

3. **Валидация:**
   - Проверить, что `volume * contract_value * price` дает объем в USDT
   - Проверить, что `quote_currency` соответствует валюте в `trades.csv`

#### 7.0.2. Leverage в Positions

**Проблема:** В `positions.csv` нет `leverage`, но он нужен для расчета маржи: `margin = abs(size) * contract_value * price / leverage`

**Решение:**

1. **Добавить `leverage` в обязательные колонки `positions.csv`:**
   ```csv
   timestamp,symbol,side,entry_price,size,leverage,margin,regime,order_id,order_type
   2025-12-07T12:00:00Z,BTC-USDT,long,89000.0,0.001,5,17.8,trending,12345,limit
   ```

2. **Валидация:**
   - Проверить, что `leverage > 0` и `leverage <= max_leverage` (обычно 125 для OKX)
   - Проверить, что `margin = abs(size) * contract_value * price / leverage` (с точностью до округления)

#### 7.0.3. Slippage Units

**Проблема:** В `orders.csv` колонка `slippage` может быть в USDT или в %, но не указаны единицы.

**Решение:**

1. **Добавить колонку `slippage_units` в `orders.csv`:**
   ```csv
   order_id,timestamp,symbol,side,order_type,size,price,status,fill_price,fill_size,execution_time_ms,slippage,slippage_units
   12345,2025-12-07T12:00:00Z,BTC-USDT,buy,limit,0.001,89000.0,filled,89000.5,0.001,150,0.5,abs
   ```

2. **Валидация:**
   - `slippage_units` должен быть `"abs"` (USDT) или `"pct"` (%)
   - Если `slippage_units == "abs"`: `slippage >= 0` (всегда положительное проскальзывание)
   - Если `slippage_units == "pct"`: `slippage >= 0` (всегда положительное проскальзывание)
   - Если `slippage` отсутствует, но `fill_price` и `price` есть: рассчитать автоматически

#### 7.0.4. Forward-Looking Detection

**Проблема:** Сейчас ищем только закомментированные строки. Нужны regex-паттерны для поиска forward-looking кода.

**Решение:**

1. **Добавить regex-паттерны для поиска:**
   ```python
   forward_looking_patterns = [
       r"df\.shift\s*\(\s*-\d+\s*\)",  # df.shift(-1)
       r"iloc\s*\[\s*.+\s*\+\s*\d+\s*\]",  # iloc[i+1]
       r"loc\s*\[.*\+\s*pd\.Timedelta",  # loc[t + pd.Timedelta(...)]
       r"\.shift\s*\(\s*-\d+",  # .shift(-N)
       r"future",  # Слово "future" в контексте данных
       r"ahead",  # Слово "ahead"
       r"lead",  # Слово "lead"
       r"next_bar",  # next_bar
       r"tomorrow",  # tomorrow
       r"\.iloc\[.*\+.*\]",  # iloc с плюсом
       r"\.loc\[.*\+.*\]",  # loc с плюсом
   ]
   ```

2. **Структура в JSON:**
   ```json
   {
     "source_code": {
       "forward_looking": {
         "signal_generator.py": {
           "line": 456,
           "code": "price_future = data.iloc[i+1]['close']",
           "pattern": "iloc\\s*\\[\\s*.+\\s*\\+\\s*\\d+\\s*\\]",
           "severity": "critical",
           "description": "Использование будущих данных для текущего решения"
         }
       }
     }
   }
   ```

#### 7.0.5. Secrets Redaction

**Проблема:** Пользователь может засунуть `api_key` прямо в `config.yaml`. Нужно скрыть секреты перед расчетом MD5.

**Решение:**

1. **Список ключей для скрытия:**
   ```python
   redact_keys = [
       'api_key', 'api_secret', 'secret_key', 'secret',
       'passphrase', 'private_key', 'private_key_path',
       'password', 'token', 'access_token', 'refresh_token'
   ]
   ```

2. **Алгоритм:**
   - Перед расчетом MD5: заменить все значения ключей на `"***REDACTED***"`
   - Сохранить оригинальный хеш в `md5_hash_original` (если нужно)
   - Сохранить хеш после редактирования в `md5_hash` (для аналитика)

3. **Структура в JSON:**
   ```json
   {
     "config": {
       "file_path": "config/config_futures.yaml",
       "md5_hash": "abc123...",  # После редактирования секретов
       "md5_hash_original": "def456...",  # До редактирования (опционально)
       "secrets_redacted": true,
       "redacted_keys": ["api_key", "api_secret", "passphrase"]
     }
   }
   ```

#### 7.0.6. DST Transition (Daylight Saving Time)

**Проблема:** Окно 02:00-03:00 в марте/октябре дает дубли или дыры из-за перехода на летнее/зимнее время.

**Решение:**

1. **Проверка DST переходов:**
   ```python
   # Проверить дубликаты timestamp внутри одного symbol между 02:00 и 03:00 UTC
   # в марте (последнее воскресенье) и октябре (последнее воскресенье)
   
   dst_months = [3, 10]  # Март и октябрь
   dst_hours = [2, 3]  # 02:00 и 03:00 UTC
   
   # Если pandas >= 2.2:
   # df['timestamp'].dt.dst_transition
   ```

2. **Валидация:**
   - Если найдены дубликаты в окне 02:00-03:00 UTC в марте/октябре → предупреждение, не ошибка
   - Записать в `integrity_errors` как `"warning"`, не `"error"`

3. **Структура в JSON:**
   ```json
   {
     "integrity_errors": {
       "market_data.csv": {
         "dst_transition": {
           "warnings": [
             {
               "date": "2025-03-30",
               "symbol": "BTC-USDT",
               "duplicate_timestamps": ["2025-03-30T02:00:00Z", "2025-03-30T03:00:00Z"],
               "issue": "DST transition - duplicate timestamps expected"
             }
           ]
         }
       }
     }
   }
   ```

#### 7.0.7. File Lock (Файл в процессе записи)

**Проблема:** Бот пишет `trades.csv` каждую сделку. Cursor может поймать половину строк.

**Решение:**

1. **Проверка блокировки файла:**
   ```python
   try:
       with open(file_path, 'r', encoding='utf-8') as f:
           # Читаем файл
           data = f.read()
   except PermissionError:
       # Файл заблокирован
       logger.warning(f"⚠️ Файл {file_path} заблокирован (возможно, бот пишет в него)")
       # Попросить пользователя сделать копию
       ask_user_to_copy_file(file_path)
   ```

2. **Алгоритм:**
   - Если `PermissionError` → попросить пользователя сделать копию файла
   - Указать путь к копии
   - Использовать копию для чтения

#### 7.0.8. Parquet с Partition Columns

**Проблема:** Если пользователь сохраняет `market_data` как `/data/date=2025-12-07/symbol=BTC-USDT/part-0000.parquet`, то просто `pd.read_parquet('market_data.csv')` не прочитает.

**Решение:**

1. **Проверка формата:**
   ```python
   if file_path.endswith('.parquet'):
       # Проверить, является ли путь директорией с partition columns
       if os.path.isdir(file_path):
           # Использовать pyarrow.dataset
           import pyarrow.dataset as ds
           dataset = ds.dataset(file_path, format='parquet')
           df = dataset.to_table().to_pandas()
       else:
           # Обычный parquet файл
           df = pd.read_parquet(file_path)
   ```

2. **Запросить у пользователя:**
   - Если путь указывает на директорию с partition columns → использовать `pyarrow.dataset`
   - Или попросить указать корневую папку

#### 7.0.9. Partial Fill → Несколько строк в Orders

**Проблема:** Один `order_id` может быть разбит на 3-4 строки (разные `fill_price`). Валидация "уникальный order_id" даст ложное срабатывание.

**Решение:**

1. **Изменить правило уникальности:**
   - Уникален `(order_id, fill_id)` или `(order_id, timestamp_fill)`
   - Или агрегировать в Cursor до одной строки с `avg_fill_price`

2. **Добавить колонку `fill_id` в `orders.csv`:**
   ```csv
   order_id,fill_id,timestamp,symbol,side,order_type,size,price,status,fill_price,fill_size,avg_fill_price
   12345,1,2025-12-07T12:00:00Z,BTC-USDT,buy,limit,0.001,89000.0,partially_filled,89000.0,0.0005,89000.25
   12345,2,2025-12-07T12:00:01Z,BTC-USDT,buy,limit,0.001,89000.0,partially_filled,89000.5,0.0005,89000.25
   ```

3. **Валидация:**
   - Если `status == "partially_filled"` → проверить, что есть несколько строк с одним `order_id`
   - Рассчитать `avg_fill_price = sum(fill_price * fill_size) / sum(fill_size)`
   - Добавить `avg_fill_price` в каждую строку
   - **Допуск на округление:** При сверке `avg_fill_price` с OKX API допускается погрешность ±1 тик (`tick_size`)
     - Например, если `tick_size = 0.1` и `avg_fill_price = 89000.333333`, то OKX может вернуть `89000.3` или `89000.4`
     - Это нормально, не считать ошибкой

#### 7.0.10. OKX "Касание" последней свечи

**Проблема:** OKX отдает последнюю 1-минутку `09:59:59.999` с `timestamp 10:00:00.000`. Cursor может считать это дублем.

**Решение:**

1. **Проверка:**
   - Если `timestamp` отличается на 1 секунду, но `symbol` одинаковый → не считать дублем
   - Это нормальное поведение OKX API

2. **Валидация:**
   - Разрешить разницу в 1 секунду для одного `symbol`
   - Записать в `integrity_errors` как `"info"`, не `"error"`

#### 7.0.11. Funding Fee Sign Validation

**Проблема:** В `trades.csv` колонка `funding_fee` может быть отрицательной (ты получил) или положительной (заплатил). Нужно проверить знак.

**Решение:**

1. **Валидация знака (только для Futures):**
   - Если `instrument_type == "SPOT"` → `funding_fee` не применим, пропускать валидацию
   - Если `instrument_type == "FUTURES"` или не указан:
     - Если `side == "long"` и `funding_rate > 0` → `funding_fee` должен быть `> 0` (заплатил)
     - Если `side == "long"` и `funding_rate < 0` → `funding_fee` должен быть `< 0` (получил)
     - Если `side == "short"` и `funding_rate > 0` → `funding_fee` должен быть `< 0` (получил)
     - Если `side == "short"` и `funding_rate < 0` → `funding_fee` должен быть `> 0` (заплатил)

2. **Если `funding_fee` отсутствует или равен 0:**
   - Проверить `instrument_type` в конфиге
   - Если `instrument_type == "SPOT"` → отметить `"funding_not_applicable": true`, не считать ошибкой
   - Если `instrument_type == "FUTURES"` → предупреждение, но не блокировать

2. **Структура в JSON:**
   ```json
   {
     "integrity_errors": {
       "trades.csv": {
         "funding_fee_sign": {
           "violations": [
             {
               "line": 45,
               "symbol": "BTC-USDT",
               "side": "long",
               "funding_rate": 0.01,
               "funding_fee": -0.05,
               "issue": "Long position with positive funding rate should have positive funding_fee"
             }
           ]
         }
       }
     }
   }
   ```

#### 7.0.12. Time In Force для ордеров

**Проблема:** В ТЗ только "GTC". Бывают IOC, FOK, GTD.

**Решение:**

1. **Добавить колонку `time_in_force` в `orders.csv`:**
   ```csv
   order_id,timestamp,symbol,side,order_type,size,price,status,time_in_force,expire_time
   12345,2025-12-07T12:00:00Z,BTC-USDT,buy,limit,0.001,89000.0,filled,GTC,
   12346,2025-12-07T12:00:00Z,BTC-USDT,buy,limit,0.001,89000.0,filled,GTD,2025-12-08T12:00:00Z
   ```

2. **Валидация:**
   - `time_in_force` должен быть одним из: `"GTC"`, `"IOC"`, `"FOK"`, `"GTD"`
   - Если `time_in_force == "GTD"` → должна быть колонка `expire_time`
   - **Если `time_in_force == "GTD"` и `expire_time` отсутствует:**
     - Статус: `"blocked"`
     - Просить пользователя либо заполнить `expire_time`, либо изменить на `"GTC"`
     - Не включать в пакет до исправления

#### 7.0.13. Комиссия OKX (VIP уровни)

**Проблема:** `maker 0.02%`, `taker 0.05%` – это VIP0. У многих уже VIP3 (0.015/0.03).

**Решение:**

1. **Запросить у пользователя:**
   - `fee_level` (VIP0, VIP1, VIP2, VIP3, и т.д.)
   - Или парсить из `/api/v5/account/transaction-history`

2. **Добавить в `exchange_limits`:**
   ```json
   {
     "exchange_limits": {
       "commission": {
         "maker": 0.0002,  # 0.02% для VIP0
         "taker": 0.0005,  # 0.05% для VIP0
         "fee_level": "VIP0",  # Или VIP1, VIP2, VIP3
         "source": "config"  # Или "api"
       }
     }
   }
   ```

#### 7.0.14. Lot Multiplier

**Проблема:** OKX у некоторых инструментов `lot_size = 0.001`, но `min_lot = 1`. Нужна кратность.

**Решение:**

1. **Добавить `lot_multiplier` в `exchange_limits`:**
   ```json
   {
     "exchange_limits": {
       "min_lot_size": {
         "BTC-USDT": {
           "lot_size": 0.001,
           "min_lot": 1,
           "lot_multiplier": 0.001  # size должен быть кратен этому
         }
       }
     }
   }
   ```

2. **Валидация:**
   - Проверить, что `size % lot_multiplier == 0` (с точностью до округления)

#### 7.0.15. Quote Currency в Market Data и Trades

**Проблема:** Инструменты с квотируемой валютой ≠ USDT (SOL-USDC, BTC-USDC, ETH-BTC).

**Решение:**

1. **Добавить `quote_currency` в `market_data` и `trades`:**
   ```csv
   timestamp,symbol,quote_currency,open,high,low,close,volume
   2025-12-07T12:00:00Z,SOL-USDC,USDC,132.5,133.0,132.0,132.8,1000.0
   ```

2. **Валидация:**
   - Проверить, что `quote_currency` соответствует валюте в `trades.csv`
   - Если `quote_currency != "USDT"` → предупредить аналитика

#### 7.0.16. Кодировка файлов (Windows-1251 / UTF-8 с BOM)

**Проблема:** CSV-файлы могут быть в разных кодировках (Windows-1251, UTF-8 с BOM, KOI8-R). Cursor упадет на `UnicodeDecodeError`.

**Решение:**

1. **Последовательность попыток чтения:**
   ```python
   encodings = ['utf-8-sig', 'utf-8', 'cp1251', 'koi8-r', 'latin-1']
   
   for encoding in encodings:
       try:
           with open(file_path, 'r', encoding=encoding) as f:
               data = f.read()
           break  # Успешно прочитано
       except UnicodeDecodeError:
           continue  # Пробуем следующую кодировку
   else:
       # Все кодировки не подошли
       ask_user_to_convert_to_utf8(file_path)
   ```

2. **Если не читается:**
   - Попросить пользователя сохранить файл как UTF-8
   - Или предоставить файл в другой кодировке с указанием кодировки

3. **Структура в JSON:**
   ```json
   {
     "trades": {
       "file_path": "logs/trades_2025-12-07.csv",
       "encoding": "utf-8-sig",  // Определенная кодировка
       "encoding_detected": true
     }
   }
   ```

#### 7.0.17. Rollover контрактов (экспирируемые фьючерсы)

**Проблема:** Бот может торговать `BTC-USDT-241220` до экспирации, потом переключиться на `BTC-USDT-250320`. В `trades.csv` появятся разные символы, но оба будут считаться "BTC-USDT".

**Решение:**

1. **Добавить колонку `contract_id` в `trades.csv`:**
   ```csv
   trade_id,timestamp,symbol,contract_id,side,entry_price,exit_price,size,...
   trade_123,2025-12-07T12:00:00Z,BTC-USDT,BTC-USDT-241220,long,89000.0,89500.0,0.001,...
   trade_124,2025-12-20T12:00:00Z,BTC-USDT,BTC-USDT-250320,long,90000.0,90500.0,0.001,...
   ```

2. **Просить пользователя:**
   - Не менять `symbol` при rollover
   - Менять только `contract_id` (суффикс с датой экспирации)

3. **Валидация:**
   - Если `contract_id` отсутствует, но `symbol` содержит дату (например, "BTC-USDT-241220") → извлечь дату в `contract_id`
   - Если `contract_id` разный для одного `symbol` → это нормально (rollover)

4. **Структура в JSON:**
   ```json
   {
     "trades": {
       "contract_rollovers": {
         "BTC-USDT": [
           {"contract_id": "BTC-USDT-241220", "expiry": "2024-12-20"},
           {"contract_id": "BTC-USDT-250320", "expiry": "2025-03-20"}
         ]
       }
     }
   }
   ```

#### 7.0.18. Кросс-маржинальные позиции (Portfolio-margin)

**Проблема:** OKX позволяет "объединить" маржу между инструментами. Тогда `margin` в `positions.csv` может быть отрицательным или больше баланса.

**Решение:**

1. **Добавить флаг `cross_margin` в `positions.csv`:**
   ```csv
   timestamp,symbol,side,entry_price,size,leverage,margin,cross_margin,...
   2025-12-07T12:00:00Z,BTC-USDT,long,89000.0,0.001,5,17.8,false,...
   ```

2. **Валидация:**
   - Если `cross_margin == false` → проверять `margin <= balance`
   - Если `cross_margin == true` → не валидировать `margin <= balance` (может быть больше)

3. **Структура в JSON:**
   ```json
   {
     "positions": {
       "cross_margin_enabled": false,  // Глобальный флаг
       "cross_margin_positions": 0,  // Количество кросс-маржинальных позиций
       "validation": {
         "margin_check": "skipped_for_cross_margin"  // Если есть cross_margin позиции
       }
     }
   }
   ```

#### 7.0.19. Режим позиций (Hedge vs Netting)

**Проблема:** В netting-mode одновременно не может быть long и short по одному символу. В `positions.csv` может встретиться две строки `(BTC-USDT, long)` и `(BTC-USDT, short)` с одинаковым timestamp → это нормально для hedge-mode, но невозможно для netting.

**Решение:**

1. **Добавить в конфиг поле `position_mode`:**
   ```yaml
   # config/config_futures.yaml
   trading:
     position_mode: "netting"  # Или "hedge"
   ```

2. **Валидация:**
   - Если `position_mode == "netting"` → проверить, что нет одновременно long и short по одному символу
   - Если `position_mode == "hedge"` → разрешить одновременные long и short

3. **Структура в JSON:**
   ```json
   {
     "config": {
       "trading": {
         "position_mode": "netting",
         "validation": {
           "simultaneous_long_short": "forbidden"  // Для netting
         }
       }
     }
   }
   ```

#### 7.0.20. Trigger Price для стоп-ордеров

**Проблема:** В `orders.csv` нет колонки `trigger_price`. Для стоп-ордеров без неё невозможно проверить forward-looking (пользователь мог поставить стоп выше рынка и получить проскальзывание).

**Решение:**

1. **Добавить `trigger_price` как опциональную, но обязательную для стоп-ордеров:**
   ```csv
   order_id,timestamp,symbol,side,order_type,size,price,trigger_price,status,...
   12345,2025-12-07T12:00:00Z,BTC-USDT,buy,stop_market,0.001,89000.0,89500.0,filled,...
   ```

2. **Валидация:**
   - Если `order_type in ['stop_market', 'stop_limit']` → `trigger_price` обязательна
   - Если `trigger_price` отсутствует для стоп-ордера → статус `"blocked"`, просить пользователя заполнить

3. **Структура в JSON:**
   ```json
   {
     "orders": {
       "stop_orders_without_trigger": {
         "count": 2,
         "order_ids": ["12345", "12346"],
         "issue": "stop_market/stop_limit orders require trigger_price"
       }
     }
   }
   ```

---

## 8. Алгоритм для Cursor

### 8.0. Системные инструкции для Cursor

**Перед каждым чтением файла:**

1. **Проверка формата:**
   - Если путь заканчивается на `.parquet` → использовать `pyarrow` или `pd.read_parquet()`
   - Если путь указывает на директорию с partition columns → использовать `pyarrow.dataset`

2. **Проверка блокировки:**
   - Если `PermissionError` → попросить пользователя сделать копию файла и указать путь к копии

3. **Проверка кодировки (см. п.7.0.16):**
   - При `UnicodeDecodeError` пробовать последовательности: `utf-8-sig` → `utf-8` → `cp1251` → `koi8-r`
   - Если не читается → просить пользователя конвертировать в UTF-8

4. **Редактирование секретов:**
   - Перед расчетом MD5 всегда удалять строки, содержащие ключи из списка: `['api_key', 'secret', 'passphrase', 'private_key']`
   - Заменять значения на `"***REDACTED***"`

5. **Обработка DST переходов:**
   - Проверять дубликаты timestamp внутри одного symbol между 02:00 и 03:00 UTC в марте/октябре
   - Записывать как предупреждение, не ошибку

6. **Проверка zero-byte файлов:**
   - Если `file_size_bytes == 0` → статус `"missing"`, пропустить файл (см. п.4.1.7)

### 8.1. Приветствие и памятка

**Сообщение пользователю:**

```
Привет! Я буду собирать данные для аудита вашей торговой стратегии.

Я буду запрашивать файлы строго по списку:
1. Конфигурационный файл
2. Исходный код стратегии
3. Журнал сделок (trades.csv)
4. Маркет-дата
5. Позиционный лог
6. Логи заявок
7. Экзогенные данные (если есть)
8. Параметры ковки (если есть)
9. Результаты ковки (если есть)
10. Итоговая статистика

После каждого файла я проверю целостность данных.
Если ошибок нет – пойдём дальше.
Если есть – спрошу, как исправить.

В конце сформирую JSON-пакет и сохраню его в корень проекта.

Готовы начать? Начнём с конфигурационного файла.
```

### 8.2. Запросить файлы в порядке п.3

**Для каждого файла:**

1. Запросить путь к файлу
2. **Проверить блокировку файла** (см. п.7.0.7):
   - Если `PermissionError` → попросить пользователя сделать копию
3. **Обработать формат файла** (см. п.7.0.8):
   - Если `.parquet` и путь указывает на директорию → использовать `pyarrow.dataset`
4. **Редактировать секреты** (см. п.7.0.5):
   - Перед расчетом MD5 заменить секреты на `"***REDACTED***"`
5. Прочитать файл
6. Выполнить проверки из п.2.2, п.4 и п.7.0
7. Если ошибки – записать в `integrity_errors.json` и спросить у пользователя
8. Если всё ОК – продолжить

### 8.3. Когда все файлы собраны и ошибок нет

**Сформировать `audit_bundle_*.json`:**

1. Собрать все данные в структуру из п.6
2. Рассчитать summary (метрики из performance_report или trades.csv)
3. Сохранить JSON файл в корень проекта
4. Вывести пользователю:
   - Путь к итоговому файлу
   - Краткий summary:
     ```
     ✅ Пакет данных создан: audit_bundle_20251207_futures_scalping.json
     
     📊 Summary:
     - Всего сделок: 141
     - Период: 7 дней
     - Sharpe Ratio: 1.85
     - Win Rate: 55.3%
     - Total PnL: $60.63 USDT
     - Файлов включено: 6
     - Файлов отсутствует: 2 (burn_params, burn_results - оптимизация не проводилась)
     - Статус целостности: clean
     ```
5. Попросить пользователя отправить этот файл аналитику (Kimi)

---

## 9. Дополнительные запросы данных

### 9.0. Запрос instruments.csv

**Если отсутствует `instruments.csv` (см. п.7.0.1):**

1. Запросить у пользователя выгрузить из OKX API: `/api/v5/public/instruments`
2. Или создать файл вручную с колонками:
   - `symbol`, `ctVal`, `ctMult`, `quoteCcy`, `lotSz`, `tickSz`
3. Если невозможно → отметить в `integrity_errors`: "instruments.csv missing, contract_multiplier unknown"

### 9.1. Запрос fee_level

**Если комиссия не указана в конфиге (см. п.7.0.13):**

1. Запросить у пользователя VIP уровень (VIP0, VIP1, VIP2, VIP3, и т.д.)
2. Или парсить из `/api/v5/account/transaction-history`
3. Если невозможно → использовать значения по умолчанию (VIP0: maker 0.02%, taker 0.05%)

---

## 10. Что делать, если пользователь не может предоставить часть файлов

### 10.1. Отметить в integrity_errors причину отсутствия

```json
{
  "integrity_errors": {
    "market_data.csv": {
      "status": "missing",
      "reason": "Market data obtained via WebSocket in real-time, no historical file available",
      "recommendation": "Analyst may request specific date range for historical data"
    }
  }
}
```

### 10.2. Продолжать сбор

- Не останавливаться на отсутствующих файлах
- Продолжить сбор остальных файлов

### 10.3. В финальном JSON выставить "missing": true

```json
{
  "market_data": {
    "missing": true,
    "reason": "Market data obtained via WebSocket in real-time",
    "recommendation": "Analyst may request specific date range"
  }
}
```

### 10.4. Уведомить пользователя

```
⚠️ Внимание: Файл market_data.csv отсутствует.
Причина: Данные получаются через WebSocket в реальном времени.
В пакете будет отмечено "missing": true.
Аналитик может запросить недостающие данные позже.
```

---

## 11. Дополнительные инструкции

### 11.1. Обработка больших файлов

Если файл слишком большой (>100MB):

1. Спросить у пользователя, можно ли использовать выборку (sample)
2. Или запросить только метаданные (shape, columns, date_range)
3. Отметить в JSON: `"sampled": true, "sample_size": 10000`

### 11.2. Обработка зашифрованных файлов

Если файл зашифрован:

1. Запросить у пользователя ключ или способ расшифровки
2. Если невозможно – отметить `"encrypted": true, "decryption_required": true`

### 11.3. Обработка бинарных форматов

Если файл в бинарном формате (parquet, pickle):

1. Попытаться прочитать через pandas/специальные библиотеки
2. Если невозможно – запросить у пользователя конвертацию в CSV
3. Отметить в JSON: `"format": "parquet", "converted": false`

---

## 12. Заключение

Этот документ описывает полный процесс сбора и структурирования данных для аудита торговой стратегии. Следуя этому алгоритму, Cursor сможет:

1. ✅ Собрать все необходимые данные
2. ✅ Проверить целостность данных
3. ✅ Сформировать унифицированный JSON-пакет
4. ✅ Подготовить данные для внешнего аналитика

**Важно:**

- Строго следовать порядку запроса файлов
- Всегда проверять целостность данных
- Записывать все ошибки в `integrity_errors.json`
- Уведомлять пользователя о проблемах
- Формировать подробный summary в конце

---

**Версия документа:** 1.2  
**Последнее обновление:** 2025-12-07  
**Изменения в v1.2:**
- Добавлена проверка незакрытых свечей (4.1.6)
- Добавлена проверка zero-byte файлов (4.1.7)
- Добавлена обработка кодировок файлов (7.0.16)
- Добавлена поддержка rollover контрактов (7.0.17)
- Добавлена поддержка кросс-маржинальных позиций (7.0.18)
- Добавлена поддержка режима позиций (hedge/netting) (7.0.19)
- Добавлена поддержка trigger_price для стоп-ордеров (7.0.20)
- Уточнена валидация GTD ордеров (требование expire_time)
- Уточнена валидация funding_fee для SPOT инструментов
- Добавлен допуск на округление avg_fill_price (±1 тик)
- Добавлена колонка contract_id в trades.csv для экспирируемых фьючерсов

**Изменения в v1.1:**
- Добавлен раздел 7.0 "Дополнительные технические проверки" (15 подразделов)
- Уточнены проверки целостности (DST переходы, partial fills, OKX "касание")
- Добавлена обработка секретов перед расчетом MD5
- Добавлена поддержка Parquet с partition columns
- Добавлена проверка блокировки файлов
- Уточнены единицы измерения (slippage_units, quote_currency)
- Добавлены обязательные колонки (leverage, time_in_force, fill_id, avg_fill_price)
- Добавлены regex-паттерны для поиска forward-looking кода
- Уточнены лимиты биржи (VIP уровни, lot_multiplier)

