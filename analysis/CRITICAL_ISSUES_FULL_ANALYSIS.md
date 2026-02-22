# Полный анализ критических проблем торгового бота

## Дата анализа: 2026-02-22
## Сессия: 10:39-14:18 (баланс $940→$892, просадка 5.03%)

---

## ИСПРАВЛЕННЫЕ ОЦЕНКИ (после углублённого анализа)

### ✅ P0-2: FastADX reset() + replay — НЕ БАГ, А НАМЕРЕННЫЙ ПАТТЕРН

**Локация:** `src/strategies/scalping/futures/adaptivity/regime_manager.py:411`

```python
self.fast_adx.reset()  # Очищает состояние
adx_window = max(self.fast_adx.period * 3, 30)
for candle in candles[-adx_window:]:
    self.fast_adx.update(...)  # Переигрывает последние N свечей
```

**Почему это правильно:**
- FastADX требует 3×period баров для математически корректного расчёта
- Инкрементальный подход был бы быстрее, но менее точным
- Это компромисс между производительностью и точностью
- Поведение задокументировано в коде

**Статус:** Работает как задумано

---

### ✅ P1-6: ADX сохраняется в registry — РАБОТАЕТ КОРРЕКТНО

**Локация:** `src/strategies/scalping/futures/adaptivity/regime_manager.py:710-730`

```python
if not used_registry_adx and self.data_registry and self.symbol:
    adx_value = detection.indicators.get("adx")
    if adx_value is not None:
        await self.data_registry.update_regime(
            symbol=self.symbol,
            regime=regime,
            indicators={"adx_proxy": float(adx_value), ...}
        )
```

**Подтверждение работы:**
- ADX сохраняется как `"adx_proxy"` в DataRegistry
- SignalGenerator читает его перед генерацией сигналов
- Логи подтверждают: `ADX из DataRegistry: 34.56`

**Статус:** Работает корректно

---

## ПОДТВЕРЖДЁННЫЕ КРИТИЧЕСКИЕ ПРОБЛЕМЫ

### 🔴 P0-4: Cycle time 2.3s — БУТЫЛОЧНОЕ ГОРЛЫШКО manage_positions (1668ms)

**Локация:** `src/strategies/scalping/futures/core/trading_control_center.py:407-566`

**Проблема:**
```
⏱️ TCC Performance: cycle=2280ms, manage=1668ms (73% времени цикла!)
```

**Корень проблемы — position_manager.py:**

1. **Синхронные REST-вызовы для КАЖДОЙ позиции:**
   ```python
   # position_manager.py:668 — вызывается для каждой позиции!
   price_limits = await self.client.get_price_limits(symbol)
   ```
   
2. **get_price_limits делает HTTP-запрос:**
   ```python
   # futures_client.py:988-1050
   async with aiohttp.ClientSession() as session:
       orderbook_url = f"https://www.okx.com/api/v5/market/books?instId={inst_id}&sz=5"
       async with session.get(orderbook_url) as book_resp:
           # ... парсинг
   ```

3. **Множественные вызовы на одну позицию:**
   - `manage_position()` → `get_price_limits()` для текущей цены
   - `_check_stop_loss()` → `get_price_limits()` (строка 1580)
   - `_check_take_profit()` → `get_price_limits()` (строка 2383)
   - `_close_position_by_reason()` → `get_price_limits()` (строка 4475)

**Математика:**
- При 3 позициях × 4 вызова = 12 HTTP-запросов за цикл
- При latency 50-100ms = 600-1200ms только на HTTP
- Плюс обработка = 1668ms итоговое время

**Решение:**
1. Кэшировать цены из WebSocket (DataRegistry)
2. Использовать markPx с валидацией freshness
3. batch-запросы для всех позиций одним вызовом

---

### 🔴 P0-1: EMA threshold 0.0001 — АБСОЛЮТНЫЙ ПОРОГ НЕРАБОТОСПОСОБЕН

**Локация:** `src/strategies/scalping/futures/signal_generator.py:2846`

```python
if ema_12 is not None and ema_26 is not None and abs(ema_12 - ema_26) < 0.0001:
    logger.warning(f"⚠️ [EMA] {symbol}: EMA_12 и EMA_26 ОДИНАКОВЫЕ...")
```

**Проблема:**
| Актив | Цена | 0.0001 в % от цены |
|-------|------|-------------------|
| BTC | $95,000 | 0.0000001% (невозможно) |
| ETH | $2,700 | 0.0000037% (невозможно) |
| SOL | $170 | 0.000059% (невозможно) |
| DOGE | $0.25 | 0.04% (редко) |

**Эффект:**
- Для BTC/ETH/SOL порог никогда не достигается
- Проверка бесполезна для высокоценных активов
- EMA "одинаковыми" считаются только при цене ~$0.01

**Решение:**
```python
# Относительный порог вместо абсолютного
price = current_price or max(ema_12, ema_26)
if abs(ema_12 - ema_26) / price < 0.0001:  # 0.01% от цены
```

---

### 🟡 P1-7: Choppy filter — ХАРДКОДИРОВАННЫЕ ТИПЫ СИГНАЛОВ

**Локация:** `src/strategies/scalping/futures/signal_generator.py:1997-2017`

```python
_CHOPPY_BLOCKED_TYPES = {
    "macd_bullish", "macd_bearish",
    "bb_oversold", "bb_overbought",
    "rsi_oversold", "rsi_overbought",
}
```

**Проблема:**
- Список заблокированных типов хардкодирован
- Нет возможности настроить через конфиг
- Блокирует 6 из ~10 типов сигналов

**Остающиеся сигналы в choppy:**
- `rsi_divergence` (только развороты)
- `vwap_mean_reversion` (только mean-reversion)

**Эффект:**
- В choppy режиме доступно только 2 типа сигналов
- Может пропускать валидные сигналы при краткосрочных движениях
- Нет гибкости для разных стратегий

**Решение:**
```python
# Вынести в конфигурацию
choppy_blocked_types = self.scalping_config.signal_generator.get(
    "choppy_blocked_types", 
    ["macd_bullish", "macd_bearish", ...]  # дефолт
)
```

---

### 🟡 P1-8: BUY/SELL conflict — ОБА СИГНАЛА ОТБРАСЫВАЮТСЯ

**Локация:** `src/strategies/scalping/futures/signal_generator.py:2075-2088`

```python
if diff <= 0.05:
    logger.warning(f"⚡ {symbol}: КОНФЛИКТ... пропускаем оба сигнала")
    base_signals = []  # ← Оба сигнала удаляются!
```

**Проблема:**
- При равной силе сигналов (diff ≤ 0.05) оба отбрасываются
- Это приводит к потере потенциально прибыльных сделок
- Нет fallback на "меньшее из двух зол"

**Сценарий:**
```
BUY signal:  strength=0.75 (RSI divergence + MACD)
SELL signal: strength=0.73 (BB breakout)
diff = 0.02 ≤ 0.05 → ОБА ОТБРОШЕНЫ
```

**Ожидаемое поведение:**
- Выбрать сильнейший сигнал
- Или уменьшить размер позиции
- Или использовать нейтральную стратегию

**Решение:**
```python
if diff <= 0.05:
    # Вместо отбрасывания — выбираем сильнейший
    winner = best_buy if buy_str >= sell_str else best_sell
    winner["strength"] *= 0.8  # Штраф за неопределённость
    base_signals = [winner]
```

---

### 🟡 P1-5: volume_ratio — ОДНА СВЕЧА vs MA20, НЕТ МИНИМАЛЬНОГО ПОРОГА

**Локация:** `src/strategies/scalping/futures/signal_generator.py:6964-6980`

```python
vol_sma20 = sum(c.volume for c in candles[-20:]) / 20 if len(candles) >= 20 else 0
if not volume_warmup and vol_sma20 > 0 and vol_cur < vol_sma20 * 1.1:
    # Блокируем низкообъемные сигналы
    return []

avg_volume = sum(c.volume for c in prev_candles) / max(len(prev_candles), 1)
if not volume_warmup and (
    avg_volume <= 0
    or current_candle.volume < avg_volume * detection_values["min_volume_ratio"]
):
    return []
```

**Проблемы:**

1. **Одиночная свеча vs MA20 — шум:**
   - Текущий объём одной свечи сравнивается с MA20
   - При волатильности даёт ложные срабатывания
   - Нет сглаживания

2. **Нет абсолютного минимума:**
   ```python
   # min_volume_ratio может быть 0.1 или меньше
   # При avg_volume = 100, текущий = 10 — проходит!
   ```

3. **Двойная проверка с разными базами:**
   - Первая: `vol_cur < vol_sma20 * 1.1`
   - Вторая: `current_candle.volume < avg_volume * min_volume_ratio`
   - Непоследовательная логика

**Решение:**
```python
# Минимальный абсолютный порог
MIN_VOLUME_ABSOLUTE = 1000  # или из конфига

# Сглаженный объём (EMA3 вместо одиночной свечи)
vol_ema3 = calculate_ema(volumes, 3)

if vol_ema3 < max(vol_sma20 * min_ratio, MIN_VOLUME_ABSOLUTE):
    return []
```

---

## ДОПОЛНИТЕЛЬНЫЕ ПРОБЛЕМЫ (из предыдущего анализа)

### 🔴 P0-3: Data Staleness — MARK_PRICE до 54 секунд

**Локация:** WebSocket + DataRegistry

**Проблема:**
```
XRP-USDT-SWAP: MARK_PRICE delayed 54.2s
ETH-USDT-SWAP: MARK_PRICE delayed 31.5s
```

**Эффект:**
- PnL расчёт: модель +1.4%, биржа -0.6%
- Разница 2-5% при волатильности

---

### 🔴 P0-5: TTLCache блокирует emergency close

**Локация:** `src/strategies/scalping/futures/orchestrator.py:5182-5187`

```python
if symbol in self._closing_positions_cache:
    logger.debug(f"Position {symbol} already closing (TTLCache), skip")
    return  # Emergency stop НЕ сработал!
```

---

### 🟡 P1-3: Telegram только для OCO

**Локация:** `src/strategies/scalping/futures/order_executor.py:2573-2580`

```python
# Только в _place_oco_order
if self.telegram:
    asyncio.create_task(self.telegram.send_trade_open(...))
```

---

## ИТОГОВАЯ ТАБЛИЦА ПРОБЛЕМ

| ID | Проблема | Статус | Приоритет | Влияние на PnL |
|----|----------|--------|-----------|----------------|
| P0-1 | EMA threshold 0.0001 | 🔴 Подтверждена | P0 | Нет валидации EMA для BTC/ETH |
| P0-2 | FastADX reset | ✅ Исправлена | — | Намеренный паттерн |
| P0-3 | Data staleness 54s | 🔴 Подтверждена | P0 | PnL mismatch 2-5% |
| P0-4 | Cycle time 2.3s | 🔴 Подтверждена | P0 | Пропуск сигналов |
| P0-5 | TTLCache emergency | 🔴 Подтверждена | P0 | Риск убытков |
| P1-3 | Telegram OCO only | 🟡 Подтверждена | P1 | Нет уведомлений |
| P1-5 | volume_ratio шум | 🟡 Подтверждена | P1 | Ложные сигналы |
| P1-6 | ADX registry | ✅ Исправлена | — | Работает корректно |
| P1-7 | Choppy hardcoded | 🟡 Подтверждена | P1 | 90% сигналов заблокировано |
| P1-8 | BUY/SELL conflict | 🟡 Подтверждена | P1 | Потеря сигналов |

---

## РЕКОМЕНДАЦИИ ПО ПРИОРИТЕТАМ

### Немедленно (P0):
1. **P0-4**: Кэширование цен в manage_positions
2. **P0-5**: Bypass TTLCache для emergency
3. **P0-3**: Fallback на REST при stale WebSocket

### В ближайшем спринте (P1):
4. **P0-1**: Относительный EMA threshold
5. **P1-8**: Выбор сильнейшего при конфликте
6. **P1-7**: Конфигурируемый choppy filter
7. **P1-5**: Сглаживание volume_ratio
8. **P1-3**: Telegram для всех типов ордеров
