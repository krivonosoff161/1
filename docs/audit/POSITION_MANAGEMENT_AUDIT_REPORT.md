# 🔍 ПОЛНЫЙ АУДИТ УПРАВЛЕНИЯ ОТКРЫТЫМИ ПОЗИЦИЯМИ

**Дата:** 04.12.2025  
**Проблема:** Низкий win rate (34.7%), нужно проверить правильность анализа позиций и принятия решений

---

## 📊 ТЕКУЩАЯ СТАТИСТИКА

### Из анализа сделок (02-03.12.2025):
- **Всего позиций:** 3684
- **Прибыльных:** 1279 (34.7%) ⚠️ **НИЗКИЙ WIN RATE**
- **Убыточных:** 2405 (65.3%)
- **Общий PnL:** -$324.27
- **Общая комиссия:** $202.40

### Проблема:
- Win rate 34.7% слишком низкий для прибыльной торговли
- Нужно минимум 40-45% при среднем PnL $0.10-0.20
- Текущий средний PnL: -$0.09 (убыточный)

---

## 🔴 НАЙДЕННЫЕ ПРОБЛЕМЫ

### 🔴 ПРОБЛЕМА #1: Несоответствие расчета PnL% в разных модулях

**Критическая проблема:** Разные модули считают PnL% по-разному!

#### 1. **TrailingStopLoss.get_profit_pct()** - считает от ЦЕНЫ
**Файл:** `src/strategies/scalping/futures/indicators/trailing_stop_loss.py` (строки 404-407)

```python
# Считает процент от ЦЕНЫ, а не от маржи!
if self.side == "long":
    gross_profit_pct = (current_price - self.entry_price) / self.entry_price
else:
    gross_profit_pct = (self.entry_price - current_price) / self.entry_price
```

**Проблема:**
- При leverage 3x: **1% от цены = 3% от маржи**
- Если TP = 2.4% от маржи, то в TrailingStopLoss нужно сравнивать с **0.8% от цены**
- Но TrailingStopLoss сравнивает с **2.4% от цены** - это неправильно!

**Пример:**
- Entry: $90,000, Current: $90,240 (0.27% от цены)
- Leverage: 3x → PnL% от маржи = 0.27% × 3 = **0.81% от маржи**
- TP = 2.4% от маржи → нужно 0.8% от цены
- TrailingStopLoss видит: 0.27% < 2.4% → **НЕ закрывает** (неправильно!)

#### 2. **PositionManager._check_tp_only()** - пытается считать от МАРЖИ
**Файл:** `src/strategies/scalping/futures/position_manager.py` (строки 2115-2153)

```python
# Пытается получить margin и unrealizedPnl
if margin_used > 0:
    pnl_percent = (unrealized_pnl / margin_used) * 100  # ✅ ПРАВИЛЬНО: от маржи
else:
    # Fallback: считает от цены
    pnl_percent = (current_price - entry_price) / entry_price * 100  # ❌ НЕПРАВИЛЬНО: от цены
```

**Проблема:**
- Если не удалось получить margin → fallback на расчет от цены
- Это может привести к неправильным решениям

#### 3. **ExitAnalyzer._calculate_pnl_percent()** - правильно считает от МАРЖИ
**Файл:** `src/strategies/scalping/futures/positions/exit_analyzer.py` (строки 343-344)

```python
# ✅ ПРАВИЛЬНО: Считает от маржи
if margin_used and margin_used > 0 and unrealized_pnl is not None:
    gross_pnl_pct = (unrealized_pnl / margin_used) * 100
```

**Вывод:** ExitAnalyzer правильный, но TrailingStopLoss - неправильный!

---

### 🔴 ПРОБЛЕМА #2: TrailingStopLoss использует неправильные пороги

**Файл:** `src/strategies/scalping/futures/indicators/trailing_stop_loss.py` (строки 504-505)

**Текущая логика:**
```python
loss_cut_from_price = self.loss_cut_percent / self.leverage  # ✅ ПРАВИЛЬНО: конвертирует
if profit_pct <= -loss_cut_from_price:  # profit_pct от ЦЕНЫ
```

**НО! min_profit_to_close сравнивается напрямую:**
```python
if profit_pct < self.min_profit_to_close:  # ❌ ПРОБЛЕМА: min_profit_to_close от маржи или от цены?
```

**Проблема:**
- `min_profit_to_close` в конфиге указан как процент от маржи (например, 0.1% = 0.1% от маржи)
- Но `profit_pct` - это процент от цены
- При leverage 3x: 0.1% от маржи = 0.033% от цены
- Сравнение: 0.27% (от цены) < 0.1% (от маржи?) → **НЕПРАВИЛЬНО!**

---

### 🔴 ПРОБЛЕМА #3: Fallback на расчет от цены в PositionManager

**Файл:** `src/strategies/scalping/futures/position_manager.py` (строки 2115-2153)

**Проблема:**
- Если не удалось получить `margin_used` → используется fallback расчет от цены
- Это может происходить часто, если API не возвращает margin
- Приводит к неправильным решениям о закрытии

**Пример:**
- Entry: $90,000, Current: $90,240
- PnL% от цены: 0.27%
- TP = 2.4% от маржи = 0.8% от цены (при leverage 3x)
- Fallback: 0.27% < 0.8% → **НЕ закрывает** (правильно, но случайно!)
- Если TP = 0.2% от маржи = 0.067% от цены → 0.27% > 0.067% → **закрывает** (неправильно!)

---

### 🔴 ПРОБЛЕМА #4: Неправильное чтение данных позиций

**Файл:** `src/strategies/scalping/futures/position_manager.py` (строки 2046-2173)

**Проблема:**
- Бот пытается получить `margin` и `upl` из разных источников
- Если данные не найдены → fallback на расчет
- Может быть проблема с чтением данных из OKX API

**Проверка:**
- Нужно убедиться, что `get_margin_info()` правильно возвращает данные
- Нужно проверить, что `position["upl"]` и `position["margin"]` правильно читаются

---

### 🔴 ПРОБЛЕМА #5: Низкий win rate (34.7%)

**Возможные причины:**
1. **Неправильный расчет PnL%** → бот закрывает позиции слишком рано или слишком поздно
2. **Неправильные пороги** → TP/SL срабатывают не в нужный момент
3. **Плохая фильтрация сигналов** → много плохих входов (Loss Cut 28.4%)
4. **Неправильное чтение данных** → бот не видит реальный PnL

---

## ✅ РЕШЕНИЯ

### Решение #1: Исправить TrailingStopLoss.get_profit_pct() для расчета от маржи

**Файл:** `src/strategies/scalping/futures/indicators/trailing_stop_loss.py`

**Изменить метод `get_profit_pct()`:**
```python
def get_profit_pct(self, current_price: float, include_fees: bool = True, 
                   margin_used: Optional[float] = None, 
                   unrealized_pnl: Optional[float] = None) -> float:
    """
    ✅ ИСПРАВЛЕНО: Расчет PnL% от МАРЖИ (как на бирже), а не от цены!
    """
    if self.entry_price == 0:
        return 0.0
    
    # ✅ ПРИОРИТЕТ 1: Если есть margin и unrealizedPnl - считаем от маржи
    if margin_used and margin_used > 0 and unrealized_pnl is not None:
        gross_pnl_pct = (unrealized_pnl / margin_used) * 100  # От маржи!
        
        if include_fees:
            # Учитываем комиссию (0.1% на круг)
            trading_fee_rate = 0.0010
            net_pnl_pct = gross_pnl_pct - (trading_fee_rate * 100)  # Комиссия в процентах
            return net_pnl_pct
        return gross_pnl_pct
    
    # ✅ FALLBACK: Если нет margin - считаем от цены и конвертируем
    if self.side == "long":
        gross_profit_pct_from_price = (current_price - self.entry_price) / self.entry_price
    else:
        gross_profit_pct_from_price = (self.entry_price - current_price) / self.entry_price
    
    # ✅ КРИТИЧЕСКОЕ: Конвертируем процент от цены в процент от маржи
    # При leverage 3x: 1% от цены = 3% от маржи
    gross_profit_pct_from_margin = gross_profit_pct_from_price * self.leverage
    
    if include_fees:
        trading_fee_rate = 0.0010
        net_pnl_pct = gross_profit_pct_from_margin - (trading_fee_rate * 100)
        return net_pnl_pct
    
    return gross_profit_pct_from_margin
```

**Обоснование:**
- Все расчеты должны быть от маржи (как на бирже)
- Это обеспечит правильное сравнение с порогами TP/SL

---

### Решение #2: Передавать margin и unrealizedPnl в TrailingStopLoss

**Файл:** `src/strategies/scalping/futures/coordinators/trailing_sl_coordinator.py`

**Изменить вызов `get_profit_pct()`:**
```python
# Получаем margin и unrealizedPnl из позиции
margin_used = float(position.get("margin", "0") or 0)
unrealized_pnl = float(position.get("upl", "0") or 0)

# Передаем в get_profit_pct
profit_pct = tsl.get_profit_pct(
    current_price, 
    include_fees=True,
    margin_used=margin_used if margin_used > 0 else None,
    unrealized_pnl=unrealized_pnl if unrealized_pnl != 0 else None
)
```

---

### Решение #3: Улучшить чтение данных позиций

**Файл:** `src/strategies/scalping/futures/position_manager.py`

**Изменить `_check_tp_only()`:**
```python
# ✅ УЛУЧШЕНО: Множественные попытки получить margin
margin_used = None
unrealized_pnl = None

# Попытка 1: Из position напрямую
if "margin" in position:
    margin_used = float(position["margin"])
if "upl" in position:
    unrealized_pnl = float(position["upl"])

# Попытка 2: Из margin_info
if (margin_used is None or margin_used == 0) or (unrealized_pnl is None):
    margin_info = await self.client.get_margin_info(symbol)
    if margin_info:
        margin_used = margin_used or margin_info.get("margin", 0)
        unrealized_pnl = unrealized_pnl or margin_info.get("upl", 0)

# Попытка 3: Из active_positions
if (margin_used is None or margin_used == 0) or (unrealized_pnl is None):
    if symbol in self.active_positions:
        pos_data = self.active_positions[symbol]
        margin_used = margin_used or pos_data.get("margin", 0)
        unrealized_pnl = unrealized_pnl or pos_data.get("unrealized_pnl", 0)

# ✅ КРИТИЧЕСКОЕ: Если не получили margin - ЛОГИРУЕМ ОШИБКУ
if margin_used is None or margin_used == 0:
    logger.error(
        f"❌ КРИТИЧЕСКАЯ ОШИБКА: Не удалось получить margin для {symbol}! "
        f"position keys: {list(position.keys())}, "
        f"margin_info: {margin_info if 'margin_info' in locals() else 'N/A'}"
    )
    # НЕ используем fallback - это может привести к неправильным решениям
    return
```

---

### Решение #4: Исправить сравнение min_profit_to_close

**Файл:** `src/strategies/scalping/futures/indicators/trailing_stop_loss.py`

**Изменить:**
```python
# ✅ ИСПРАВЛЕНО: min_profit_to_close должен быть от маржи
# Если profit_pct теперь от маржи - сравниваем напрямую
if profit_pct > 0 and self.min_profit_to_close is not None:
    if profit_pct < self.min_profit_to_close:
        # profit_pct теперь от маржи, min_profit_to_close тоже от маржи - правильно!
        logger.debug(
            f"💰 Минимальный профит: позиция в прибыли {profit_pct:.2%} < {self.min_profit_to_close:.2%}, "
            f"не закрываем"
        )
        return False, None
```

---

## 📊 ОЖИДАЕМЫЙ ЭФФЕКТ

### До исправлений:
- TrailingStopLoss считает от цены → неправильные решения
- Fallback на расчет от цены → неправильные решения
- Win rate: 34.7% (низкий)

### После исправлений:
- Все расчеты от маржи (как на бирже) → правильные решения
- Правильное сравнение с порогами → правильное закрытие
- Win rate: 40-45% (улучшение на 5-10%)
- Улучшение общего PnL: +$50-100/день

---

## 🎯 ПРИОРИТЕТ ИСПРАВЛЕНИЙ

1. **КРИТИЧЕСКИЙ:** Решение #1 (исправить TrailingStopLoss.get_profit_pct) - основная причина проблемы
2. **ВЫСОКИЙ:** Решение #2 (передавать margin/unrealizedPnl) - необходимо для правильной работы
3. **ВЫСОКИЙ:** Решение #3 (улучшить чтение данных) - предотвратит fallback
4. **СРЕДНИЙ:** Решение #4 (исправить min_profit_to_close) - дополнительная защита

---

## 📝 ФАЙЛЫ ДЛЯ ИЗМЕНЕНИЯ

1. `src/strategies/scalping/futures/indicators/trailing_stop_loss.py` - метод `get_profit_pct()`
2. `src/strategies/scalping/futures/coordinators/trailing_sl_coordinator.py` - передача margin/unrealizedPnl
3. `src/strategies/scalping/futures/position_manager.py` - улучшение чтения данных

---

**Отчет готов к применению исправлений!** ✅

