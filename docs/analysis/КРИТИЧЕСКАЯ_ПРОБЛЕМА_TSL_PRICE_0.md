# 🚨 КРИТИЧЕСКАЯ ПРОБЛЕМА: TSL получает price=0.0000

**Дата:** 2026-01-10  
**Проблема:** Позиции не закрываются, потому что TSL получает `price=0.0000`

---

## 📊 НАЙДЕННАЯ ПРОБЛЕМА В ЛОГАХ

### Логи показывают:

```
🔍 TSL_CHECK: XRP-USDT minutes=456.9216 | profit=4.0000 | price=0.0000 | sl=2.0970 | close=False
🔍 TSL_CHECK: SOL-USDT minutes=408.4187 | profit=4.0000 | price=0.0000 | sl=136.2729 | close=False
🔍 TSL_CHECK: ETH-USDT minutes=500.5903 | profit=4.0000 | price=0.0000 | sl=3192.0798 | close=False
🔍 TSL_CHECK: BTC-USDT minutes=504.1298 | profit=4.0000 | price=0.0000 | sl=94714.2680 | close=False
```

### ⚠️ КРИТИЧЕСКИЕ ПРОБЛЕМЫ:

1. **`price=0.0000`** - текущая цена = 0!
2. **`profit=4.0000%`** - это FALLBACK значение, не реальный PnL!
3. **Позиции открыты очень долго** (456 минут = 7.6 часов!)

---

## 🔍 АНАЛИЗ ПРОБЛЕМЫ

### 1. Почему `price=0.0000`?

**В логах также видно:**
```
⚠️ TSL: Using REST API callback for BTC-USDT: 90579.00000000
⚠️ TSL: Using REST API callback for ETH-USDT: 3088.88000000
⚠️ TSL: Using REST API callback for XRP-USDT: 2.09550000
⚠️ TSL: Using REST API callback for SOL-USDT: 135.92000000
```

**Вывод:** Цена получается через REST API callback, но **НЕ передается** в `should_close_position()`!

### 2. Почему `profit=4.0000%` (fallback)?

**В логах:**
```
💰 TrailingStopLoss: PnL calc (fallback): leverage=5.0, fees_adj=1.0000%, gross=5.0000%, net=4.0000%
```

**Проблема:** Когда `current_price=0`, расчет PnL использует fallback значение вместо реального расчета!

**Код в `trailing_stop_loss.py`:**
```python
def get_profit_pct(self, current_price: float, ...):
    if current_price <= 0:
        # Fallback - возвращает фиксированное значение!
        return 0.04  # 4%
```

### 3. Почему loss_cut не срабатывает?

**Проверка loss_cut:**
```python
if profit_pct <= -loss_cut_from_price:
    # Закрываем
```

**НО:** `profit_pct = 4.0%` (fallback), а не реальный убыток `-1.39%`!

**Результат:** Loss_cut **НИКОГДА** не срабатывает, потому что:
- `4.0% > -0.4%` ✅ (не закрываем)
- Реальный убыток `-1.39% < -0.4%` ❌ (должны закрыть, но не проверяется!)

---

## 🔧 КОРНЕВАЯ ПРИЧИНА

### Проблема в `update_trailing_stop_loss()`:

**Файл:** `trailing_sl_coordinator.py:578`

```python
async def update_trailing_stop_loss(self, symbol: str, current_price: float):
    # ...
    # Получаем текущую цену
    current_price = await self._get_current_price(symbol)
    
    # ...
    # Вызываем should_close_position
    should_close, reason = tsl.should_close_position(
        current_price,  # ⚠️ ПРОБЛЕМА: current_price может быть 0!
        ...
    )
```

**Проблема:** `_get_current_price()` может вернуть `0`, если:
1. WebSocket не подключен
2. DataRegistry не содержит цену
3. REST API callback не работает

---

## 📋 ДЕТАЛЬНЫЙ АНАЛИЗ КОДА

### 1. `_get_current_price()` в `trailing_sl_coordinator.py`:

```python
async def _get_current_price(self, symbol: str) -> float:
    # ПРИОРИТЕТ 1: DataRegistry
    if self.data_registry:
        market_data = await self.data_registry.get_market_data(symbol)
        if market_data and hasattr(market_data, "current_price"):
            return market_data.current_price
    
    # ПРИОРИТЕТ 2: REST API callback
    if self.get_current_price_callback:
        price = await self.get_current_price_callback(symbol)
        if price and price > 0:
            return price
    
    # FALLBACK: 0
    return 0.0  # ⚠️ ПРОБЛЕМА!
```

**Проблема:** Если оба источника не работают → возвращает `0.0`!

### 2. `should_close_position()` в `trailing_stop_loss.py`:

```python
def should_close_position(self, current_price: float, ...):
    if current_price <= 0:
        # ⚠️ ПРОБЛЕМА: Использует fallback вместо реального расчета!
        profit_pct = self.get_profit_pct(current_price, ...)
        # get_profit_pct() возвращает 4.0% fallback при price=0
        return False, None  # НЕ закрываем!
```

---

## 🎯 РЕШЕНИЕ

### Вариант 1: Использовать entry_price как fallback

**В `_get_current_price()`:**
```python
async def _get_current_price(self, symbol: str) -> float:
    # ... существующий код ...
    
    # FALLBACK: Используем entry_price из TSL
    tsl = self.trailing_sl_by_symbol.get(symbol)
    if tsl and hasattr(tsl, "entry_price") and tsl.entry_price > 0:
        logger.warning(f"⚠️ TSL: Используем entry_price как fallback для {symbol}: {tsl.entry_price}")
        return tsl.entry_price
    
    return 0.0
```

### Вариант 2: Получать цену из позиции

**В `update_trailing_stop_loss()`:**
```python
async def update_trailing_stop_loss(self, symbol: str, current_price: float):
    # Если current_price=0, пробуем получить из позиции
    if current_price <= 0:
        position = self.active_positions_ref.get(symbol)
        if position:
            # Пробуем получить цену из позиции
            mark_price = position.get("mark_price") or position.get("markPx")
            if mark_price:
                current_price = float(mark_price)
                logger.warning(f"⚠️ TSL: Используем mark_price из позиции для {symbol}: {current_price}")
    
    # Если все еще 0, используем entry_price
    if current_price <= 0:
        tsl = self.trailing_sl_by_symbol.get(symbol)
        if tsl and hasattr(tsl, "entry_price"):
            current_price = tsl.entry_price
            logger.warning(f"⚠️ TSL: Используем entry_price как последний fallback для {symbol}: {current_price}")
```

### Вариант 3: Исправить расчет PnL при price=0

**В `trailing_stop_loss.py`:**
```python
def get_profit_pct(self, current_price: float, ...):
    if current_price <= 0:
        # ⚠️ ИСПРАВЛЕНО: Используем entry_price для расчета
        if hasattr(self, "entry_price") and self.entry_price > 0:
            # Используем entry_price как текущую цену (консервативный подход)
            # Это даст PnL = 0%, что лучше чем fallback 4%
            current_price = self.entry_price
            logger.warning(f"⚠️ TSL: current_price=0, используем entry_price для расчета PnL: {current_price}")
        else:
            # Только если entry_price тоже недоступен
            return 0.0  # Не знаем PnL, не закрываем
```

---

## 📊 ВЛИЯНИЕ НА ВАШИ ПОЗИЦИИ

### Текущее состояние:

| Символ | Реальный PnL | TSL видит | Loss Cut порог | Статус |
|--------|--------------|-----------|----------------|--------|
| XRPUSDT | **-1.39%** | **+4.0%** (fallback) | -0.4% | ❌ НЕ закрывается |
| SOLUSDT | **-4.57%** | **+4.0%** (fallback) | -0.4% | ❌ НЕ закрывается |
| ETHUSDT | **-0.50%** | **+4.0%** (fallback) | -0.57% | ✅ Норма (не достиг порог) |
| BTCUSDT | **+0.15%** | **+4.0%** (fallback) | - | ✅ Норма (прибыль) |

### Что должно происходить:

1. **XRPUSDT:** `-1.39% < -0.4%` → **ДОЛЖНА ЗАКРЫТЬСЯ** по loss_cut
2. **SOLUSDT:** `-4.57% < -0.4%` → **ДОЛЖНА ЗАКРЫТЬСЯ** немедленно по loss_cut
3. **ETHUSDT:** `-0.50% > -0.57%` → Норма (не достиг порог)
4. **BTCUSDT:** `+0.15%` → Норма (прибыль)

---

## 🔧 РЕКОМЕНДАЦИИ ПО ИСПРАВЛЕНИЮ

### Приоритет 1: Исправить `_get_current_price()`

Добавить fallback на entry_price или mark_price из позиции.

### Приоритет 2: Исправить `get_profit_pct()`

Не использовать fallback 4% при price=0, а использовать entry_price для расчета.

### Приоритет 3: Добавить валидацию цены

Перед вызовом `should_close_position()` проверять, что `current_price > 0`.

---

## 📋 ЧЕКЛИСТ ДЛЯ ИСПРАВЛЕНИЯ

- [ ] Исправить `_get_current_price()` - добавить fallback на entry_price
- [ ] Исправить `get_profit_pct()` - не использовать fallback при price=0
- [ ] Добавить валидацию цены перед `should_close_position()`
- [ ] Добавить логирование, когда используется fallback цена
- [ ] Протестировать на реальных позициях

---

## 🎯 ВЫВОДЫ

**Корневая причина:** TSL получает `price=0.0000`, из-за чего:
1. Расчет PnL использует fallback значение `4.0%` вместо реального убытка
2. Loss_cut не срабатывает, потому что `4.0% > -0.4%`
3. Позиции остаются открытыми, даже когда убыток превышает порог

**Решение:** Исправить получение цены и расчет PnL, чтобы использовать реальные данные вместо fallback значений.
