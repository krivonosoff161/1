# 🔬 ДЕТАЛЬНЫЙ РАЗБОР: ПОЧЕМУ LOSS_CUT НЕ СРАБАТЫВАЕТ

**Дата:** 2025-11-28  
**Цель:** Найти ТОЧНУЮ причину, почему loss_cut не закрывает позиции после 35 минут

---

## 📍 ШАГ 1: ОТСЛЕЖИВАЕМ ВРЕМЯ УДЕРЖАНИЯ

### Где рассчитывается `minutes_in_position`?

**Файл:** `trailing_stop_loss.py:472-474`

```python
minutes_in_position = (
    (time.time() - self.entry_timestamp) / 60.0 
    if self.entry_timestamp else 0.0
)
```

**КРИТИЧЕСКОЕ:** `entry_timestamp` устанавливается **ОДИН РАЗ** при инициализации TSL и **НЕ ОБНОВЛЯЕТСЯ**!

### Где устанавливается `entry_timestamp`?

**Файл:** `trailing_stop_loss.py:158-164`

```python
if entry_timestamp is not None and entry_timestamp > 0:
    self.entry_timestamp = entry_timestamp
else:
    self.entry_timestamp = time.time()  # Для новых позиций
```

**ВОПРОС:** Обновляется ли `entry_timestamp` после инициализации?  
**ОТВЕТ:** НЕТ! Устанавливается только при инициализации.

---

## 📍 ШАГ 2: ПОСЛЕДОВАТЕЛЬНОСТЬ ПРОВЕРОК В `should_close_position()`

### Порядок проверок:

1. **Строки 501-566:** Критический loss_cut (2x) - с задержкой 5 секунд
2. **Строки 568-607:** MIN_HOLDING блокировка - проверяется ПЕРЕД обычным loss_cut
3. **Строки 613-634:** Обычный loss_cut - проверяется ПОСЛЕ MIN_HOLDING

### Логика MIN_HOLDING блокировки:

```python
# Строка 568-572
if (
    effective_min_holding is not None
    and minutes_in_position < effective_min_holding
):
    # Блокируем loss_cut
    return False, None
```

**ПРОБЛЕМА:** Если `minutes_in_position < 35 минут`, loss_cut **ВСЕГДА** блокируется!

---

## 📍 ШАГ 3: КОГДА ПРОВЕРЯЕТСЯ LOSS_CUT ПОСЛЕ 35 МИНУТ?

### Код после MIN_HOLDING:

**Файл:** `trailing_stop_loss.py:613-634`

```python
# После прохождения MIN_HOLDING (строки 609-607)
if self.loss_cut_percent is not None:
    loss_cut_from_price = self.loss_cut_percent / self.leverage
    if profit_pct <= -loss_cut_from_price:
        # ЗАКРЫВАЕМ! ✅
        return True, "loss_cut"
```

**ВОПРОС:** Вызывается ли этот код после 35 минут?  
**ОТВЕТ:** ДА, должен вызываться! Но почему не срабатывает?

---

## 📍 ШАГ 4: КАК ВЫЗЫВАЕТСЯ `should_close_position()`?

### Цепочка вызовов:

1. **WebSocket тикер** → `websocket_coordinator.handle_ticker_data()`
2. **Для каждой позиции** → `update_trailing_stop_loss()`
3. **В TSL координаторе** → `tsl.should_close_position()`

**Файл:** `trailing_sl_coordinator.py:775-779`

```python
should_close_by_sl, close_reason = tsl.should_close_position(
    current_price,
    trend_strength=trend_strength,
    market_regime=market_regime,
)
```

**ВОПРОС:** Вызывается ли `update_trailing_stop_loss()` для убыточных позиций?  
**ОТВЕТ:** ДА, должен вызываться при каждом WebSocket тикере!

---

## 📍 ШАГ 5: БЛОКИРОВКИ ПОСЛЕ `should_close_position()`

### После `should_close_position()` возвращает `True, "loss_cut"`:

**Файл:** `trailing_sl_coordinator.py:1011-1017`

```python
if should_close_by_sl:
    if should_block_close:
        logger.debug(
            f"🔒 Закрытие по trailing stop заблокировано для {symbol} "
            f"(индикаторы показывают возможный разворот в нашу пользу, позиция в прибыли)"
        )
        return  # БЛОКИРУЕМ закрытие!
```

**КРИТИЧЕСКОЕ:** `should_block_close` проверяется **ТОЛЬКО** если `profit_pct > 0` (строка 782)!

**Для убыточных позиций:** `profit_pct < 0`, значит `should_block_close` НЕ должен блокировать!

---

## 📍 ШАГ 6: ГДЕ МОЖЕТ БЫТЬ ПРОБЛЕМА?

### ВОЗМОЖНЫЕ ПРИЧИНЫ:

1. **`entry_timestamp` не обновляется** → `minutes_in_position` может быть неправильным
2. **`should_close_position()` не вызывается** → проверка loss_cut не выполняется
3. **`profit_pct` рассчитывается неправильно** → условие `profit_pct <= -loss_cut_from_price` не срабатывает
4. **Блокировка где-то еще** → закрытие блокируется после `should_close_position()`

---

## 🔍 ЧТО НУЖНО ПРОВЕРИТЬ В ЛОГАХ:

1. **Есть ли записи о проверке loss_cut после 35 минут?**
   - Искать: `"Loss-cut заблокирован"` или `"Loss-cut: прибыль"`
   
2. **Какое значение `minutes_in_position` в логах?**
   - Искать: `"time_in_position"` в логах TSL

3. **Вызывается ли `should_close_position()`?**
   - Искать: `"TrailingSL check"` в логах

4. **Что возвращает `should_close_position()`?**
   - Искать: `"Loss-cut:"` или `"закрываем"` в логах

---

---

## 🚨 НАЙДЕНА КРИТИЧЕСКАЯ ПРОБЛЕМА!

### ПРОБЛЕМА: `update_trailing_stop_loss()` НЕ ВЫЗЫВАЕТСЯ, ЕСЛИ `entry_price` ОТСУТСТВУЕТ!

**Файл:** `websocket_coordinator.py:273-276`

```python
if (
    symbol in self.active_positions_ref
    and "entry_price" in self.active_positions_ref.get(symbol, {})  # ⚠️ ПРОБЛЕМА ЗДЕСЬ!
):
    # Вызываем update_trailing_stop_loss
```

**ЧТО ПРОИСХОДИТ:**

1. Позиция открывается
2. Позиция добавляется в `active_positions_ref`
3. НО! `entry_price` может отсутствовать или быть 0
4. Проверка `"entry_price" in self.active_positions_ref.get(symbol, {})` → **FALSE**
5. `update_trailing_stop_loss()` **НЕ ВЫЗЫВАЕТСЯ** ❌
6. TSL не обновляется → loss_cut не проверяется ❌

**НО:** В `update_trailing_stop_loss()` есть логика восстановления `entry_price` из `avgPx` (строки 387-429), но она **НИКОГДА НЕ ВЫЗЫВАЕТСЯ**, потому что метод не вызывается!

---

## 🔧 РЕШЕНИЕ:

### Вариант 1: Убрать проверку `entry_price` из условия

```python
# БЫЛО:
if (
    symbol in self.active_positions_ref
    and "entry_price" in self.active_positions_ref.get(symbol, {})
):

# ДОЛЖНО БЫТЬ:
if symbol in self.active_positions_ref:
    # entry_price будет восстановлен в update_trailing_stop_loss()
```

### Вариант 2: Восстановить `entry_price` перед проверкой

```python
if symbol in self.active_positions_ref:
    position = self.active_positions_ref[symbol]
    # Восстанавливаем entry_price если отсутствует
    if "entry_price" not in position or position["entry_price"] == 0:
        if "avgPx" in position:
            position["entry_price"] = float(position["avgPx"])
    
    # Теперь вызываем update_trailing_stop_loss
    if "entry_price" in position and position["entry_price"] > 0:
        await self.trailing_sl_coordinator.update_trailing_stop_loss(symbol, price)
```

---

**СТАТУС:** 🔴 КРИТИЧЕСКАЯ ПРОБЛЕМА НАЙДЕНА - `update_trailing_stop_loss()` НЕ ВЫЗЫВАЕТСЯ ДЛЯ ПОЗИЦИЙ БЕЗ `entry_price`

