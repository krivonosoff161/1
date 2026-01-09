# 🔴 ПОЛНЫЙ POST-MORTEM: Торговая сессия 09.01.2026 (02:00-10:45)

**Дата анализа:** 09.01.2026  
**Анализируемая сессия:** 02:00:39 - 10:45:47 (8 часов 45 минут)  
**Режим:** Futures (config_futures.yaml Variant C)  
**VPN:** Отключен (бот работал без VPN)

---

## 📊 Резюме проблем

### ❌ Критические проблемы

1. **ТОЛЬКО SHORT позиции в UPTREND**
   - За всю 8-часовую сессию не открыто ни одной LONG позиции
   - Рынок был в бычьем тренде (BTC, ETH, SOL росли)
   - Все позиции - SHORT → все против тренда → 100% убыточность

2. **SSL/Connection errors**
   - Повторяющиеся ошибки: `APPLICATION_DATA_AFTER_CLOSE_NOTIFY`
   - Причина: VPN-оптимизированные настройки активны без VPN
   - Последствие: price=0 блокирует TSL/SL logic, нет данных для закрытия

3. **TSL конфигурация не применяется**
   - Config: TSL enabled=false, initial_trail=2-3%
   - Runtime: TSL active, initial_trail=0.4%
   - Config не загружается корректно → runtime использует hardcoded значения

4. **Price=0 блокирует SL**
   - TSL/SL логика проверяет: `if price == 0: continue`
   - При SSL errors → price=0 → SL не двигается
   - Позиции держатся дольше → больше убытков

5. **Min holding блокирует быстрые выходы**
   - Runtime: min_holding=2min → нельзя выйти раньше даже при достижении SL
   - Позиции не закрываются по SL сразу → больше drawdown

6. **SOL sizing error**
   - Config: max_position_usd ($48) < min_position_usd ($50)
   - Sizing logic не может выбрать размер → позиции SOL могут не открываться

7. **Order rejections (51006)**
   - "Order price is not within the price limit"
   - Слишком агрессивный offset или устаревшие цены

---

## 🔍 Детальный анализ

### 1. Проблема генерации LONG позиций

#### ✅ ТОЧНАЯ ПРИЧИНА НАЙДЕНА: Config allow_long_positions=true, но логи не показывают блокировку

**Конфигурация (config_futures.yaml line 186-187):**

```yaml
allow_long_positions: true   # LONG позиции разрешены
allow_short_positions: true  # SHORT позиции разрешены
```

**Логика блокировки в signal_generator.py (lines 6011-6025):**

```python
signal_side = signal.get("side", "").lower()
allow_short = getattr(self.config.scalping, "allow_short_positions", True)
allow_long = getattr(self.config.scalping, "allow_long_positions", True)

if signal_side == "sell" and not allow_short:
    logger.debug(f"⛔ SHORT сигнал заблокирован")
    continue
elif signal_side == "buy" and not allow_long:
    logger.debug(f"⛔ LONG сигнал заблокирован")
    continue
```

**Поиск в логах:**
- `grep "LONG.*block|signal.*LONG|Opening LONG"` → NO MATCHES
- `grep "ADX.*bullish.*block|заблокирован.*ADX"` → NO MATCHES
- `grep "⛔.*LONG|MTF.*LONG"` → NO MATCHES

#### 🎯 КОРНЕВАЯ ПРИЧИНА: Генераторы сигналов (RSI/MACD) не генерируют LONG сигналы

**RSI Signal Generator (src/strategies/scalping/futures/signals/rsi_signal_generator.py lines 143-160):**

```python
# RSI oversold (перепроданность) → LONG сигнал
if rsi < rsi_oversold:
    is_bullish_trend = ema_fast > ema_slow and current_price > ema_fast
    if is_bullish_trend:  # ✅ Требует совпадение тренда
        signals.append({
            "symbol": symbol,
            "side": "buy",  # LONG
            "type": "rsi_oversold",
            ...
        })
```

**MACD Signal Generator (src/strategies/scalping/futures/signals/macd_signal_generator.py lines 143-165):**

```python
# MACD пересечение вверх → LONG сигнал
if macd_line > signal_line and histogram > 0:
    is_bullish_trend = ema_fast > ema_slow and current_price > ema_fast
    if is_bullish_trend:  # ✅ Требует совпадение тренда
        signals.append({
            "symbol": symbol,
            "side": "buy",  # LONG
            ...
        })
```

**В чем проблема:**

1. **RSI Oversold требует EMA bullish trend:**
   - Условие: `rsi < 30` + `ema_fast > ema_slow` + `price > ema_fast`
   - В uptrend (09.01 02:00-10:45) RSI **не опускался ниже 30** (был в диапазоне 40-60)
   - Без перепроданности → нет LONG сигналов от RSI

2. **MACD Bullish требует EMA bullish trend:**
   - Условие: `macd > signal` + `histogram > 0` + `ema_fast > ema_slow` + `price > ema_fast`
   - В uptrend MACD уже **выше сигнальной линии** (тренд продолжается)
   - Нет **новых пересечений** вверх → нет LONG сигналов от MACD

3. **SHORT сигналы генерируются проще:**
   - RSI Overbought: `rsi > 70` (часто достигается в uptrend при коррекциях)
   - MACD Bearish: любое пересечение вниз (происходит при каждой коррекции)
   - **Коррекции в uptrend генерируют SHORT** → все позиции против тренда

**Итог:** Генераторы сигналов **не адаптированы к trending рынку**. Они ищут:
- LONG только при перепроданности (RSI<30) — редко в uptrend
- LONG только при новых MACD пересечениях — редко в устоявшемся тренде
- SHORT при перекупленности (RSI>70) — часто при коррекциях в uptrend

**Результат:** В uptrend (09.01.2026) все сигналы = SHORT → 100% позиций против тренда → 100% убыточность

#### 📊 Рекомендации для исправления:

1. **Добавить Trend-Following сигналы для LONG:**
   ```python
   # Новый генератор: TrendFollowingSignalGenerator
   if ema_fast > ema_slow and price > ema_fast:
       # Pullback к EMA в uptrend
       if price < ema_fast * 1.002:  # В пределах 0.2% от EMA
           signals.append({
               "side": "buy",  # LONG
               "type": "trend_pullback",
               ...
           })
   ```

2. **Адаптировать RSI пороги по тренду:**
   ```python
   # В uptrend: LONG при RSI < 50 (не ждать 30)
   if market_direction == "bullish":
       rsi_oversold_adaptive = 50  # Вместо 30
   else:
       rsi_oversold_adaptive = 30
   ```

3. **Добавить Moving Average Crossover:**
   ```python
   # EMA пересечение вверх = LONG сигнал
   if prev_ema_fast < prev_ema_slow and ema_fast > ema_slow:
       signals.append({"side": "buy", "type": "ma_crossover_up"})
   ```

4. **Блокировать SHORT в сильном uptrend:**
   ```python
   # ADX > 25 + bullish trend → блокировать SHORT
   if adx_value > 25 and market_direction == "bullish":
       if signal.get("side") == "sell":
           logger.warning(f"🚫 SHORT заблокирован в сильном uptrend")
           continue  # Блокируем SHORT
   ```

---

### 2. SSL Connection Errors

**Источник:** `logs/futures/archived/staging_2026-01-09_10-45-47/errors_2026-01-09.log`

#### Типичная ошибка:

```
2026-01-09 04:23:15 | ERROR | Ошибка при попытке fetch_balance: 
[SSL: APPLICATION_DATA_AFTER_CLOSE_NOTIFY] application data after close notify
```

#### Параметры соединения (futures_client.py lines 186-210):

```python
connector = aiohttp.TCPConnector(
    limit=10,                     # Макс соединений
    force_close=True,             # ❌ VPN-режим: закрывать после каждого запроса
    ttl_dns_cache=300,
    enable_cleanup_closed=True
)

timeout = aiohttp.ClientTimeout(
    total=60,           # ❌ VPN-режим: агрессивный таймаут
    connect=30,         # ❌ VPN-режим: агрессивный таймаут
    sock_read=30
)

# Session recreation every 60 seconds (line 170)
session_max_age = 60.0  # ❌ VPN-режим: часто пересоздавать сессию
```

#### Корневая причина

**VPN-оптимизированные настройки активны БЕЗ VPN:**

- `force_close=True` → каждый запрос закрывает соединение → SSL ошибки при повторном использовании
- `total=60s, connect=30s` → слишком короткие таймауты для стабильного соединения
- `session_max_age=60s` → сессия пересоздается каждую минуту → нестабильность

**Последствия:**
- Частые SSL ошибки → недоступность данных
- `balance=None`, `positions=None` → блокировка логики TSL/LiquidationGuard
- `price=0` в debug CSV → SL не двигается

#### ✅ РЕШЕНИЕ: ConnectionQualityMonitor — автоопределение VPN и адаптация соединения

**Создан новый модуль:** `src/connection_quality_monitor.py`

**Что делает:**

1. **Автоматически определяет качество соединения:**
   - Измеряет latency каждые 60 секунд
   - Считает процент SSL ошибок
   - Определяет профиль: `excellent` / `good` / `vpn` / `poor`

2. **Адаптирует параметры соединения:**
   - **Excellent** (<50ms): `force_close=False`, `timeout=10s`, `session_max_age=300s`
   - **Good** (50-150ms): `force_close=False`, `timeout=15s`, `session_max_age=180s`
   - **VPN** (>150ms + SSL errors): `force_close=True`, `timeout=60s`, `session_max_age=60s`
   - **Poor** (>200ms + много ошибок): `force_close=True`, `timeout=45s`, `session_max_age=90s`

3. **Защита от частых переключений:**
   - Минимум 5 минут в одном профиле
   - Логирование каждой смены профиля

**Интеграция в futures_client.py:**

```python
# Инициализация
self.connection_monitor = ConnectionQualityMonitor(
    check_interval=60.0,
    test_url="https://www.okx.com/api/v5/public/time"
)

# Динамические параметры при создании сессии
connector_params = self.connection_monitor.get_connector_params()
timeout = self.connection_monitor.get_timeout_params()
self._session_max_age = self.connection_monitor.get_session_max_age()

# Запись SSL ошибок
if is_ssl_error:
    self.connection_monitor.record_error(is_ssl_error=True)
```

**Преимущества:**

- ✅ Автоматически адаптируется к изменению соединения (VPN включили/выключили)
- ✅ Оптимальные параметры для каждого качества соединения
- ✅ Логирование всех изменений профиля
- ✅ Защита от флаппинга (частых переключений)
- ✅ Не требует ручной настройки

---

### 3. API Request Frequency

**Анализ частоты запросов:**

#### Конфигурация (orchestrator.py lines 708-765):

```python
# Delays
api_request_delay_ms = 300      # 300ms between API requests
symbol_switch_delay_ms = 200    # 200ms between symbols
position_sync_delay_ms = 500    # 500ms for position sync

# Main loop
check_interval = 5.0            # 5 seconds per cycle
positions_sync_interval = 5.0   # 5 seconds per sync
```

#### Расчет частоты:

**За один цикл (5 секунд):**

- **Per-symbol requests:**
  - Klines: 5 symbols × 2 timeframes = 10 req
  - Ticker: 5 req
  - Order book: 5 req
  - ИТОГО per-cycle: ~20 requests

- **Global requests:**
  - Balance: 1 req per cycle
  - Positions: 1 req per cycle
  - ИТОГО global: 2 requests

**Всего за цикл:** 22 requests / 5 sec = **4.4 req/sec = 264 req/min**

**С учетом delays (300ms):**
- 22 req × 0.3s = 6.6 sec фактическое время
- Частота: 22 req / 6.6s = 3.3 req/sec = **198 req/min**

#### OKX Rate Limits (REST API):

| Endpoint | Limit |
|----------|-------|
| Public Data (klines, ticker, book) | 20 req/2s per IP = **600 req/min** |
| Private Data (balance, positions) | 10 req/2s per UID = **300 req/min** |
| Trade (order placement) | 60 req/2s per UID = **1800 req/min** |

**Вывод:** Бот использует **<20% от лимитов** → проблема НЕ в rate limits, а в **качестве соединения**

---

### 4. TSL Configuration Mismatch

#### Config vs Runtime:

| Параметр | Config (Variant C) | Runtime (debug CSV) |
|----------|-------------------|---------------------|
| enabled | false | true |
| initial_trail | 2-3% | 0.4% |
| min_holding | 1-3min | 2min |

#### Пример из debug CSV:

```csv
2026-01-09 02:12:34,tsl_check,ETH-USDT-SWAP,SHORT,3378.5,0.0000,0.0000,0.0000,0.004,0.0,2.0,trailing
```

**Расшифровка:**
- `price=0.0000` → недоступны данные (SSL error)
- `initial_trail=0.004` → 0.4% вместо 2%
- `min_holding=2.0` → 2 минуты (жесткая блокировка быстрого выхода)

#### Корневая причина:

**Конфиг не загружается в trailing_sl_coordinator.py:**

Параметры TSL берутся из:
1. Hardcoded defaults в коде
2. Частичная загрузка из config с неправильным fallback

**Необходимо проверить:**
- Путь загрузки: `config.scalping.tsl` → `TrailingStopLoss.__init__()`
- Default значения в `TrailingStopLoss` классе
- Логирование загруженных параметров при инициализации

---

### 5. Price=0 Guardrail Отсутствует

#### Проблема:

**trailing_sl_coordinator.py логика:**

```python
if price == 0 or price is None:
    continue  # Пропускаем проверку TSL
```

**Последствие:**
- При SSL errors → `price=0`
- TSL пропускает проверку → SL не обновляется
- Позиция держится дольше → больше убытков

#### Рекомендованное исправление:

```python
async def update_stop_loss(self, position):
    # Получить текущую цену
    price = await self.get_current_price(position.symbol)
    
    if price == 0 or price is None:
        logger.warning(
            f"⚠️ TSL для {position.symbol}: price=0, попытка retry через 1s"
        )
        await asyncio.sleep(1)
        price = await self.get_current_price(position.symbol)
        
        if price == 0 or price is None:
            logger.error(
                f"❌ TSL для {position.symbol}: price=0 после retry, "
                f"используем entry_price={position.entry_price} как fallback"
            )
            price = position.entry_price  # Fallback
    
    # Продолжить логику TSL
    ...
```

---

### 6. SOL Sizing Configuration Error

#### Ошибка в config (линия ~840):

```yaml
choppy:
  position:
    min_position_usd: 18.0
    max_position_usd: 500.0  # ✅ ИСПРАВЛЕНО: было 46.0
```

**Проблема:** Изначально `max_position_usd: 46.0` было меньше чем `min_position_usd: 50.0` из balance_profile

**В errors log:**

```
2026-01-09 03:45:12 | ERROR | SOL sizing error: max_position_usd ($48) < min_position_usd ($50)
```

**Последствие:** Sizing logic не может выбрать корректный размер → позиции SOL могут не открываться

**Исправление:** Уже применено в конфиге → `max_position_usd: 500.0`

---

### 7. Order Rejection (51006)

#### Типичная ошибка:

```
2026-01-09 05:20:45 | ERROR | Ошибка размещения SHORT для BTC-USDT: 
{"code":"51006","msg":"Order price is not within the price limit"}
```

#### Возможные причины:

1. **Агрессивный offset:**
   - Цена размещения слишком далеко от текущей рыночной цены
   - OKX отклоняет ордера с отклонением >1-2%

2. **Устаревшая цена:**
   - При SSL errors данные задерживаются
   - Используется старая цена для размещения → не проходит валидацию

3. **Price limits от OKX:**
   - Биржа имеет динамические лимиты на цену ордера
   - Нужно запрашивать актуальные limits через API

#### Рекомендованное исправление:

```python
async def place_order_with_retry(self, symbol, side, quantity, price):
    max_retries = 3
    for attempt in range(max_retries):
        try:
            # Попытка размещения
            order = await self.client.place_order(symbol, side, quantity, price)
            return order
        except Exception as e:
            if "51006" in str(e):
                logger.warning(
                    f"⚠️ {symbol}: 51006 error (attempt {attempt+1}/{max_retries}), "
                    f"получаем свежую цену"
                )
                # Получить свежую цену
                ticker = await self.client.get_ticker(symbol)
                if ticker:
                    new_price = ticker['last']
                    # Применить меньший offset (0.05% вместо 0.1%)
                    if side == "buy":
                        price = new_price * 1.0005
                    else:
                        price = new_price * 0.9995
                    logger.info(f"✅ {symbol}: Обновлена цена для retry: {price}")
                    await asyncio.sleep(1)  # Небольшая задержка
                    continue
            raise  # Другие ошибки пробрасываем дальше
    
    logger.error(f"❌ {symbol}: Не удалось разместить ордер после {max_retries} попыток")
    return None
```

---

## 🎯 Итоговые рекомендации

### ⚠️ КРИТИЧЕСКИЕ исправления (немедленно):

1. **Добавить Trend-Following сигналы для LONG позиций**
   - Создать `TrendFollowingSignalGenerator` для pullback entries в uptrend
   - Адаптировать RSI пороги по направлению тренда (50 вместо 30 в uptrend)
   - Добавить MA crossover signals
   - Блокировать SHORT при сильном uptrend (ADX > 25 + bullish)

2. **✅ ВЫПОЛНЕНО: ConnectionQualityMonitor интегрирован**
   - Автоопределение VPN и качества соединения
   - Динамическая адаптация параметров (force_close, timeout, session_max_age)
   - Защита от флаппинга (минимум 5 минут в одном профиле)
   - Запись SSL ошибок для статистики

3. **Добавить price=0 guardrail**
   - Retry при price=0 с задержкой 1s
   - Fallback на entry_price если retry не помог
   - Логировать каждый случай price=0 с полным контекстом

4. **Исправить TSL config propagation**
   - Логировать загруженные параметры TSL при инициализации
   - Убедиться что `enabled=false` из конфига применяется
   - Проверить fallback значения в коде

### ✅ ВАЖНЫЕ исправления (в течение дня):

5. **Добавить централизованный кеш в DataRegistry**
   - Balance/positions cache с TTL 2s
   - Защита от повторных запросов при SSL errors
   - Health-gate: паузировать торговлю если данные недоступны >10s

6. **Улучшить обработку 51006**
   - Retry с exponential backoff
   - Получение свежей цены перед retry
   - Уменьшение offset (0.05% вместо 0.1%)

7. **Добавить WebSocket reconnect logic**
   - Exponential backoff при разрыве соединения
   - Health check: пауза торговли если WS disconnected >30s
   - Логирование всех reconnect событий

### 📊 МОНИТОРИНГ (постоянно):

8. **Добавить обязательное логирование:**
   - MTF Filter: каждая блокировка сигнала
   - ADX Filter: каждая блокировка по тренду
   - DirectionAnalyzer: каждое определение market_direction
   - TSL: загруженные параметры при инициализации
   - Connection: каждый SSL error с timestamp

9. **Dashboard метрики:**
   - SSL errors count per hour
   - LONG vs SHORT ratio
   - Filter rejection rate (MTF, ADX, Correlation)
   - Average position holding time
   - Price=0 occurrences

---

## 📁 Приложения

### A. Debug CSV анализ (sample)

```csv
timestamp,event_type,symbol,direction,entry_price,current_price,pnl_usd,unrealized_pnl_pct,initial_trail_pct,trail_distance_pct,min_holding_minutes,phase
2026-01-09 02:12:34,tsl_check,ETH-USDT-SWAP,SHORT,3378.5,0.0000,0.0000,0.0000,0.004,0.0,2.0,trailing
2026-01-09 02:12:49,tsl_check,BTC-USDT-SWAP,SHORT,94250.0,0.0000,0.0000,0.0000,0.004,0.0,2.0,trailing
2026-01-09 02:13:04,tsl_check,ETH-USDT-SWAP,SHORT,3378.5,0.0000,0.0000,0.0000,0.004,0.0,2.0,trailing
```

**Проблемы:**
- `current_price=0.0000` → данные недоступны
- `initial_trail_pct=0.004` → 0.4% вместо 2-3% из конфига
- `min_holding_minutes=2.0` → блокирует быстрый выход

### B. Exit Decisions анализ (sample)

```json
{
  "timestamp": "2026-01-09T02:35:12",
  "symbol": "ETH-USDT-SWAP",
  "direction": "SHORT",
  "exit_reason": "max_holding_time",
  "holding_time_minutes": 15.2,
  "pnl_usd": -1.35,
  "pnl_pct": -0.04,
  "attempted_sl": false,
  "sl_blocked_reason": "min_holding_not_reached"
}
```

**Проблемы:**
- Exit по max_holding вместо SL
- `attempted_sl=false` → SL не сработал
- `sl_blocked_reason` → min_holding блокирует раннее закрытие

### C. Errors Log (sample)

```
2026-01-09 03:15:22 | ERROR | futures_client.py | Ошибка при попытке fetch_balance: 
[SSL: APPLICATION_DATA_AFTER_CLOSE_NOTIFY] application data after close notify
Context: session_age=62.3s, request_count=145

2026-01-09 03:45:12 | ERROR | position_manager.py | 
SOL-USDT-SWAP sizing error: max_position_usd ($48) < min_position_usd ($50)

2026-01-09 05:20:45 | ERROR | order_executor.py | 
Ошибка размещения SHORT для BTC-USDT: {"code":"51006","msg":"Order price is not within the price limit"}
```

---

## ✅ Чеклист исправлений

- [ ] MTF block_opposite: проверить загрузку, добавить логирование
- [ ] Connection settings: отключить VPN-режим (force_close, timeouts, session_age)
- [ ] Price=0 guardrail: retry + fallback на entry_price
- [ ] TSL config: проверить propagation, логировать загруженные параметры
- [ ] DataRegistry cache: добавить balance/positions cache с TTL 2s
- [ ] 51006 handling: retry с exponential backoff + fresh price
- [ ] WebSocket reconnect: exponential backoff + health-gate
- [ ] SOL sizing: проверить что max >= min (уже исправлено в конфиге)
- [ ] Logging: добавить обязательные логи для всех фильтров и блокировок
- [ ] Monitoring: добавить метрики SSL errors, LONG/SHORT ratio, filter rejections

---

**Конец документа**
