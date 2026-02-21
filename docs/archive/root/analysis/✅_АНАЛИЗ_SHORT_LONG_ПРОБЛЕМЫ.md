# ✅ АНАЛИЗ ПРОБЛЕМЫ SHORT/LONG: Profit=-100% вместо +100%

**Дата:** 10 января 2026  
**Версия:** Futures Trading Bot v2  
**Статус:** 🔍 АКТИВНОЕ РАССЛЕДОВАНИЕ

---

## 📋 Суть Проблемы

### Наблюдаемое поведение
SHORT позиция ETH-USDT @ 3138.00 показывает `profit=-100.000%` при `price=0.00000`, хотя математически должно быть `profit=+100.000%`.

### Временная последовательность (Session 10 Jan 15:32-15:33)
```
15:32:47 - Position opened: ETH-USDT SHORT @ 3138.00
15:32:49 - TSL initialized: side=short ✓
15:32:50 - TSL check #1: price=0.00000, profit=0.000%
15:32:51 - TSL check #2: price=0.00000, profit=0.000%
15:32:56 - TSL check #3: price=0.00000, profit=0.000%
15:32:59 - TSL check #4: price=0.00000, profit=0.000%
15:33:01 - TSL check #5: price=0.00000, profit=-100.000% ❌ АНОМАЛИЯ
```

**Критическое наблюдение:** Profit изменился от 0% к -100% за 2 секунды.

---

## 🔍 Проведённый Анализ

### 1. Проверка формул расчёта PnL (trailing_stop_loss.py:505-508)

**LONG формула:**
```python
profit = (current_price - entry_price) / entry_price
# Для price=0, entry=3138: (0 - 3138) / 3138 = -1.0 = -100%
```

**SHORT формула:**
```python
profit = (entry_price - current_price) / entry_price  
# Для price=0, entry=3138: (3138 - 0) / 3138 = +1.0 = +100%
```

**Вывод:** ✅ Формулы математически КОРРЕКТНЫ.

### 2. Проверка инициализации TSL

**Код:** `trailing_stop_loss.py:148-157`
```python
def initialize(self, entry_price, side, symbol, entry_timestamp):
    self.entry_price = entry_price
    self.side = side  # ← Устанавливается здесь
    self._symbol = symbol
    ...
```

**Лог:** `15:32:49.888 | TSL_CREATE: ETH-USDT | entry=3138.0000 | side=short`

**Вывод:** ✅ TSL инициализируется с правильным `side=short`.

### 3. Проверка передачи side параметра

**Цепочка вызовов:**
```
orchestrator.py:1955
  → initialize_trailing_stop(symbol, entry_price, side=position_side, ...)

trailing_sl_coordinator.py:460-469
  → Конвертация side: "buy"/"sell" → "long"/"short"
  → position_side = "short" для sell

trailing_sl_coordinator.py:523
  → tsl.initialize(entry_price, side=position_side, ...)

trailing_stop_loss.py:152
  → self.side = side
```

**Вывод:** ✅ Параметр `side` корректно передаётся через всю цепочку.

### 4. Проверка открытия позиций

**Данные из логов:**
- Открыто 17 позиций: mix LONG и SHORT
- ETH-USDT имела как LONG (13:12, 14:03), так и SHORT (13:07, 13:55, 15:32) позиции
- Все направления открываются корректно

**Вывод:** ✅ Оба направления (LONG/SHORT) работают при открытии.

---

## 🚨 КРИТИЧЕСКАЯ ГИПОТЕЗА

### Переключение между путями расчёта PnL

В `trailing_stop_loss.py` существует **2 пути расчёта** PnL:

#### PRIORITY PATH (lines 467-498)
```python
if margin_used and margin_used > 0 and unrealized_pnl is not None:
    gross_pnl_pct_from_margin = (unrealized_pnl / margin_used) * 100
```
- Использует данные от биржи (`margin`, `unrealized_pnl`)
- **НЕ зависит от `self.side`**
- Возвращает 0% если `unrealized_pnl ≈ 0`

#### FALLBACK PATH (lines 502-515)
```python
if self.side == "long":
    profit = (current_price - entry_price) / entry_price
else:
    profit = (entry_price - current_price) / entry_price
profit_margin = profit * leverage
```
- Рассчитывает из цены и направления
- **ЗАВИСИТ от `self.side`**
- Должен возвращать +100% для SHORT с price=0

### Объяснение аномалии

**Первые 4 проверки (profit=0%):**
- Использовался **PRIORITY PATH**
- Биржа возвращала `margin=39.45, unrealized_pnl≈0`
- Результат: `0 / 39.45 * 100 = 0%` ✓

**Пятая проверка (profit=-100%):**
- Переключение на **FALLBACK PATH** (margin не доступен?)
- **ЕСЛИ** `self.side = "long"` вместо `"short"`:
  - Использовалась LONG формула
  - Результат: `(0 - 3138) / 3138 = -100%` ✓✓✓

### Возможные причины переключения `self.side`

1. **`self.side` не установлен (None)** → код использует LONG по умолчанию
2. **`self.side` перезаписывается** между проверками 4 и 5
3. **Fallback расчёт `unrealized_pnl`** использует неправильный `pos_side`

---

## 🔍 НАЙДЕННАЯ УЯЗВИМОСТЬ

### Fallback расчёт `unrealized_pnl` (trailing_sl_coordinator.py:782-795)

```python
pos_side = position.get("posSide") or position.get("position_side", "long")
#                                                                      ^^^^^
#                                          ДЕФОЛТ "long" ЕСЛИ НЕ НАЙДЕНО!

if pos_side.lower() == "long":
    unrealized_pnl = position_value * (current_price - entry_price)
else:  # short
    unrealized_pnl = position_value * (entry_price - current_price)
```

**Проблема:**
- Если API OKX возвращает `posSide=""` (пустая строка)
- И `position_side` не установлен в `active_positions`
- То `pos_side` получит дефолт `"long"`
- И расчёт `unrealized_pnl` будет **неправильным для SHORT**!

**Последствия:**
```python
# Для SHORT с неправильным pos_side="long":
unrealized_pnl = position_value * (0 - 3138)  # Отрицательное!
gross_pnl = (-X / 39.45) * 100 = -100%  # ❌ Неправильно!

# Правильный расчёт для SHORT:
unrealized_pnl = position_value * (3138 - 0)  # Положительное!
gross_pnl = (+X / 39.45) * 100 = +100%  # ✓ Правильно!
```

---

## ✅ РЕШЕНИЕ

### Fix #6: Критическое логирование pos_side

**Файл:** `trailing_sl_coordinator.py:782-795`

**Изменения:**
```python
pos_side = position.get("posSide") or position.get("position_side", "long")

# ✅ НОВОЕ: Отслеживаем источник pos_side
pos_side_source = "posSide" if position.get("posSide") else "position_side_or_default"
logger.debug(
    f"🔍 [UNREALIZED_PNL_CALC] {symbol}: pos_side='{pos_side}' (source={pos_side_source}), "
    f"pos_size={pos_size:.6f}, entry={entry_price:.2f}, current={current_price:.2f}"
)
```

**Цель:** Определить откуда берётся неправильный `pos_side`.

### Fix #7: Логирование в get_profit_pct()

**Файл:** `trailing_stop_loss.py:502, 467`

**PRIORITY PATH логирование:**
```python
if margin_used and margin_used > 0 and unrealized_pnl is not None:
    logger.debug(
        f"🔍 [PNL_CALC] {self._symbol}: PRIORITY_PATH=True, "
        f"margin={margin_used:.2f}, unrealized_pnl={unrealized_pnl:.2f}"
    )
```

**FALLBACK PATH логирование:**
```python
logger.debug(
    f"🔍 [PNL_CALC] {self._symbol}: self.side={self.side}, "
    f"entry={self.entry_price:.2f}, current={current_price:.2f}, "
    f"leverage={self.leverage}x, FALLBACK_PATH=True"
)
```

**Цель:** Отследить какой путь используется и значение `self.side`.

---

## 📊 Следующие Шаги

### 1. Запустить новую сессию с логированием
```bash
python run.py --mode futures
```

### 2. Мониторинг логов
```powershell
tail -f logs/futures/futures_main_*.log | grep -E "PNL_CALC|UNREALIZED_PNL_CALC|profit=-100"
```

### 3. Ожидаемые результаты

**Если гипотеза верна:**
- Увидим `pos_side='long' (source=position_side_or_default)` для SHORT позиций
- Это подтвердит что API возвращает пустой `posSide`

**Если гипотеза неверна:**
- Увидим `pos_side='short' (source=posSide)` 
- Значит проблема в `self.side` внутри TSL объекта

### 4. Возможное финальное решение

**Если API возвращает пустой posSide:**
```python
# Использовать active_positions как первый приоритет
pos_side = (
    self.active_positions.get(symbol, {}).get("position_side") 
    or position.get("posSide") 
    or "long"  # fallback
)
```

**Если self.side теряется:**
```python
# Передавать side явно в get_profit_pct()
def get_profit_pct(self, current_price, margin_used, unrealized_pnl, side_override=None):
    effective_side = side_override or self.side
    if effective_side == "long":
        ...
```

---

## 📝 Статус Изменений

- [x] Fix #1: Validation wrapper before should_close_position() (line ~1267)
- [x] Fix #2: 5-level fallback with entry_price (lines 1800-1836)
- [x] Fix #3: PnL protection with price fallback (lines 450-462)
- [x] Fix #4: Changed `current_price=0.0` to `exit_decision=None` (line 1109)
- [x] Fix #5: Price validation at should_close_position() entry (lines 573-597)
- [x] **Fix #6: pos_side source tracking (lines 782-795)** ← НОВОЕ
- [x] **Fix #7: PnL calculation path logging (lines 467, 502)** ← НОВОЕ

**Всего изменений:** ~120 строк кода  
**Файлов изменено:** 2  
**Статус:** Готово к тестированию

---

## 🎯 Критерии Успеха

После следующей сессии:
- ✅ Нет событий `profit=-100%` для SHORT позиций с price=0
- ✅ В логах видно `pos_side='short' (source=posSide)` для всех SHORT
- ✅ `self.side='short'` используется в FALLBACK PATH
- ✅ Позиции закрываются корректно через loss_cut

---

**Автор:** GitHub Copilot  
**Версия документа:** 1.0
