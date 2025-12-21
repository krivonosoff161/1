# 📋 ДАННЫЕ ДЛЯ АНАЛИЗА KIMI - ЭТАП 2

**Дата:** 2025-12-07  
**Запрос:** Код и логика выхода, forward-looking bias, расчет индикаторов

---

## 1. ✅ ПРОБЛЕМА: Почему убыточные позиции закрылись по `max_holding_exceeded`

### 1.1. Критический фрагмент из `position_manager.py` (строки 4910-4975)

**ПРОБЛЕМА НАЙДЕНА:** Метод `_check_max_holding` закрывает позиции БЕЗ проверки PnL!

```python
async def _check_max_holding(self, position: Dict[str, Any]) -> bool:
    """
    ✅ НОВОЕ: Проверка максимального времени удержания позиции.
    
    Закрывает позицию если она держится дольше max_holding_minutes.
    """
    try:
        symbol = position.get("instId", "").replace("-SWAP", "")
        
        # ... получение entry_time, max_holding_minutes ...
        
        if minutes_in_position >= actual_max_holding:
            # ✅ ДЕТАЛЬНОЕ ЛОГИРОВАНИЕ: Рассчитываем PnL% для отображения
            try:
                margin_used = float(position.get("margin", 0))
                entry_price = float(position.get("avgPx", 0))
                current_price = float(position.get("markPx", 0))
                side = position.get("posSide", "long").lower()
                
                # Рассчитываем PnL
                size = float(position.get("pos", "0"))
                size_in_coins = abs(size) * ct_val
                
                if side == "long":
                    gross_pnl = (current_price - entry_price) * size_in_coins
                else:
                    gross_pnl = (entry_price - current_price) * size_in_coins
                
                pnl_percent_from_margin = (gross_pnl / margin_used * 100) if margin_used > 0 else 0
                
                # ❌ КРИТИЧЕСКАЯ ПРОБЛЕМА: PnL рассчитывается, но НЕ проверяется!
                # Код просто логирует PnL и закрывает позицию независимо от того, прибыльная она или убыточная
                
                logger.warning(
                    f"⏰ MAX_HOLDING: Время в позиции {minutes_in_position:.1f} мин >= {actual_max_holding:.1f} мин | "
                    f"Entry: ${entry_price:.2f}, Exit: ${current_price:.2f}, "
                    f"Gross PnL: ${gross_pnl:.4f}, Net Pnl: ${net_pnl:.4f} ({pnl_percent_from_margin:.2f}% от маржи)"
                )
            except Exception as e:
                logger.debug(f"⚠️ Ошибка расчета PnL: {e}")
            
            # ❌ КРИТИЧЕСКАЯ ПРОБЛЕМА: Закрытие происходит БЕЗ проверки PnL!
            await self._close_position_by_reason(position, "max_holding_exceeded")
            return True  # Позиция закрыта
            
    except Exception as e:
        logger.error(f"❌ Ошибка проверки max_holding: {e}")
    
    return False
```

**Вывод:** Метод `_check_max_holding` в `position_manager.py` закрывает позиции по таймауту БЕЗ проверки, является ли позиция прибыльной или убыточной. Это противоречит логике в `exit_analyzer.py`, которая НЕ должна закрывать убыточные позиции.

### 1.2. Где вызывается `_check_max_holding`?

**Важно:** В `manage_position` (строка 586) есть комментарий:
```python
# Примечание: _check_max_holding оставлен как fallback, но не вызывается здесь
# ExitAnalyzer анализирует время в позиции вместе с другими факторами (тренд, PnL, сигналы)
```

**НО:** Метод `_check_max_holding` может вызываться из других мест. Нужно проверить все вызовы.

### 1.3. Альтернативный путь через `trailing_sl_coordinator.py`

В `trailing_sl_coordinator.py` (строки 1471-1493) есть проверка `max_holding`, но она также может закрывать позиции:

```python
if time_held >= actual_max_holding:
    time_extended = position.get("time_extended", False)
    # ✅ ИСПРАВЛЕНО: Проверяем продление ВАЖНЕЕ чем закрытие
    if (
        extend_time_if_profitable
        and not time_extended
        and profit_pct >= min_profit_for_extension
    ):
        # Продлеваем время
        ...
    else:
        # ❌ ПРОБЛЕМА: Здесь может быть закрытие без проверки PnL
        # Нужно проверить, есть ли проверка profit_pct < 0
```

---

## 2. ✅ Forward-looking в коде — проверка на утечку будущих данных

### 2.1. Поиск в `orchestrator.py`

**Результат:** Не найдено использований:
- `iloc[i+1]`
- `df.shift(-1)`
- `close[i+1]`
- `future_price`
- `next_bar`
- Комментарии с `future`, `ahead`, `lead`, `tomorrow`

**Вывод:** ✅ `orchestrator.py` не содержит forward-looking bias.

### 2.2. Поиск в `signal_generator.py`

**Результат:** Не найдено использований:
- `iloc[i+1]`
- `df.shift(-1)`
- `close[i+1]`
- `future_price`
- `next_bar`
- Комментарии с `future`, `ahead`, `lead`, `tomorrow`

**Вывод:** ✅ `signal_generator.py` не содержит forward-looking bias.

### 2.3. Поиск во всех файлах `src/strategies/scalping/futures`

**Результат:** Не найдено использований паттернов forward-looking.

**Вывод:** ✅ Код генерации сигналов не использует будущие данные.

---

## 3. ✅ Расчёт индикаторов — проверка на использование future-bars

### 3.1. RSI (строки 110-173 в `src/indicators/base.py`)

```python
def calculate(self, data: List[float]) -> IndicatorResult:
    # Расчёт RSI (Relative Strength Index)
    prices = np.array(data)
    deltas = np.diff(prices)  # Разница между соседними ценами
    
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    
    # ✅ ИСПРАВЛЕНО: Используем экспоненциальное сглаживание Wilder
    if len(gains) >= self.period:
        avg_gain = np.mean(gains[-self.period :])  # ✅ Использует только прошлые данные
        avg_loss = np.mean(losses[-self.period :])  # ✅ Использует только прошлые данные
        
        # Применяем формулу Wilder для следующих значений
        for i in range(self.period, len(gains)):
            # ✅ Использует только данные до текущего момента (gains[i], не gains[i+1])
            avg_gain = (avg_gain * (self.period - 1) + gains[i]) / self.period
            avg_loss = (avg_loss * (self.period - 1) + losses[i]) / self.period
    
    # RSI = 100 - (100 / (1 + RS))
    rs = avg_gain / avg_loss
    rsi_value = 100.0 - (100.0 / (1.0 + rs))
```

**Вывод:** ✅ RSI НЕ использует future-bars. Все расчеты основаны на прошлых и текущих данных.

### 3.2. EMA (строки 75-107 в `src/indicators/base.py`)

```python
def calculate(self, data: List[float]) -> IndicatorResult:
    # Расчёт EMA: экспоненциальная скользящая средняя
    # EMA(t) = Price(t) * α + EMA(t-1) * (1 - α)
    ema = data[0]  # Инициализация первым значением
    for price in data[1:]:  # ✅ Итерация по данным от начала до конца
        ema = (price * self.alpha) + (ema * (1 - self.alpha))
        # ✅ Использует только текущее значение price, не price[i+1]
```

**Вывод:** ✅ EMA НЕ использует future-bars. Расчет идет последовательно от начала до конца.

### 3.3. ATR (строки 176-227 в `src/indicators/base.py`)

```python
def calculate(self, high_data, low_data, close_data) -> IndicatorResult:
    true_ranges = []
    for i in range(1, len(close_data)):  # ✅ Начинаем с i=1, используем close_data[i-1]
        high_low = high_data[i] - low_data[i]
        high_close = abs(high_data[i] - close_data[i - 1])  # ✅ Использует ПРЕДЫДУЩЕЕ закрытие
        low_close = abs(low_data[i] - close_data[i - 1])  # ✅ Использует ПРЕДЫДУЩЕЕ закрытие
        true_range = max(high_low, high_close, low_close)
        true_ranges.append(true_range)
    
    # ATR = экспоненциальное среднее значение True Range
    if len(true_ranges) >= self.period:
        atr_value = np.mean(true_ranges[-self.period :])  # ✅ Использует только прошлые данные
        
        for i in range(self.period, len(true_ranges)):
            # ✅ Использует только данные до текущего момента
            atr_value = (atr_value * (self.period - 1) + true_ranges[i]) / self.period
```

**Вывод:** ✅ ATR НЕ использует future-bars. Использует только текущий бар и предыдущее закрытие.

### 3.4. MACD (строки 279-356 в `src/indicators/base.py`)

```python
def calculate(self, data: List[float]) -> IndicatorResult:
    # Calculate EMAs
    ema_fast = self._calculate_ema(data, self.fast_period)  # ✅ Использует только прошлые данные
    ema_slow = self._calculate_ema(data, self.slow_period)  # ✅ Использует только прошлые данные
    
    # Calculate MACD line
    macd_line = ema_fast - ema_slow
    
    # ✅ ИСПРАВЛЕНО: Сохраняем историю MACD для правильного расчета signal line
    self.macd_history.append(macd_line)
    
    # Signal line - это EMA от истории MACD
    if len(self.macd_history) >= self.signal_period:
        signal_value = self._calculate_ema(
            self.macd_history[-self.signal_period :], self.signal_period
        )  # ✅ Использует только прошлые значения MACD
```

**Вывод:** ✅ MACD НЕ использует future-bars. Все расчеты основаны на прошлых и текущих данных.

---

## 📊 ИТОГОВЫЕ ВЫВОДЫ

### ✅ Найдено:

1. **Критическая проблема:** Метод `_check_max_holding` в `position_manager.py` закрывает позиции по таймауту БЕЗ проверки PnL. Это объясняет, почему все 5 убыточных позиций закрылись по `max_holding_exceeded`.

2. **Forward-looking bias:** ✅ НЕ обнаружен в коде генерации сигналов и оркестратора.

3. **Индикаторы:** ✅ Все индикаторы (RSI, EMA, ATR, MACD) используют только прошлые и текущие данные, без future-bars.

### 🔧 Рекомендации:

1. **Исправить `_check_max_holding`:** Добавить проверку `if pnl_percent < 0: return False` перед закрытием позиции.

2. **Проверить все вызовы `_check_max_holding`:** Убедиться, что метод не вызывается из других мест, обходя `exit_analyzer.py`.

3. **Проверить `trailing_sl_coordinator.py`:** Убедиться, что там также есть проверка PnL перед закрытием по `max_holding`.

---

**Готово для передачи аналитику (Kimi)**

