# Анализ торговых систем бота: Продление, Долив, Trailing SL/TP

## Дата анализа: 2026-02-22

---

## 🔴 КРИТИЧЕСКАЯ ПРОБЛЕМА #1: СИСТЕМА ПРОДЛЕНИЯ СДЕЛОК — **ОТСУТСТВУЕТ**

### Что должно быть:
Бот видит сигнал на старшем таймфрейме → открывает позицию → тренд продолжается → **продлевает сделку** (увеличивает время жизни позиции, подтягивает TP/SL).

### Что есть на самом деле:
**Системы продления сделок НЕТ.**

```python
# Поиск по всему коду:
extend_position()     # ← НЕ НАЙДЕНО
prolong_position()    # ← НЕ НАЙДЕНО  
renew_position()      # ← НЕ НАЙДЕНО
continue_trade()      # ← НЕ НАЙДЕНО
```

### Как работает сейчас:
1. Бот открывает позицию с фиксированными TP/SL
2. Trailing SL двигает стоп-лосс вслед за ценой
3. **Но позиция никогда не "продлевается"** — она либо закрывается по TP/SL, либо по таймауту
4. При новом сигнале в том же направлении — **открывается НОВАЯ позиция** вместо обновления существующей

### Почему это проблема:
```
Сценарий:
1. BTC вход long @ $95,000 (тренд на H1)
2. Цена растёт до $96,500 (прибыль 1.5%)
3. TSL подтянулся до $96,000
4. Новый сигнал long на H1 (тренд продолжается)
5. Ожидание: Продлить сделку, двигать TP выше
6. Реальность: Старая позиция закрывается по TSL @ $96,000 (+1%)
   → Открывается НОВАЯ позиция @ $96,500
   → Комиссия 0.04% + проскальзывание
   → Потеря части прибыли!
```

---

## 🟡 ПРОБЛЕМА #2: ЛЕСТНИЧНОЕ УСРЕДНЕНИЕ (DCA) — **ЕСТЬ, НО ОГРАНИЧЕНО**

### Локация:
`src/strategies/scalping/futures/positions/position_scaling_manager.py`

### Как работает:
```python
ladder = [1.0, 0.5, 0.3, 0.2]  # Множители размера
max_additions = 4              # Максимум добавлений
min_interval_seconds = 30      # Минимум 30 сек между доливами
max_loss_for_addition = -5.0   # Долив только если убыток < 5%
```

### Условия для долива:
1. Позиция существует в реестре
2. Количество добавлений < 4
3. Прошло ≥ 30 секунд с последнего добавления
4. **Текущий PnL ≥ -5%** (не слишком большой убыток)
5. Достаточно маржи

### Проблемы:
1. **Нет интеграции с "продлением"** — долив ≠ продление сделки
2. **Условия слишком строгие** — при сильном тренде позиция в плюсе, долив не сработает
3. **Лестница фиксированная** — не адаптируется под волатильность
4. **Не ясно, вызывается ли вообще** — поиск вызовов:

```python
# Где вызывается calculate_next_addition_size?
# position_scaling_manager.py:332 — определение метода

# Поиск вызовов:
await position_scaling_manager.calculate_next_addition_size(...)  # ← НЕ НАЙДЕНО В ВЫЗОВАХ
position_scaling_manager.can_add_to_position(...)                 # ← НЕ НАЙДЕНО В ВЫЗОВАХ
```

### Вывод:
**Код есть, но система не интегрирована в торговый цикл.**

---

## 🟡 ПРОБЛЕМА #3: TRAILING STOP LOSS — **РАБОТАЕТ, НО ЕСТЬ НЮАНСЫ**

### Локация:
`src/strategies/scalping/futures/indicators/trailing_stop_loss.py`

### Как работает:
```python
def update(self, current_price, margin_used, unrealized_pnl):
    # 1. Обновляет highest_price/lowest_price
    # 2. Увеличивает current_trail при росте прибыли
    # 3. Возвращает новый stop_loss или None
    
def get_stop_loss(self):
    # Для long: highest_price * (1 - current_trail)
    # Для short: lowest_price * (1 + current_trail)
    
def should_close_position(self, current_price, ...):
    # Проверяет: цена достигла стопа? loss_cut? timeout?
```

### Что работает:
✅ Стоп-лосс двигается вслед за ценой
✅ Адаптивный trail (low/medium/high множители)
✅ Loss-cut защита
✅ Timeout закрытие

### Что НЕ работает:
❌ **Нет безубытка (breakeven)** — SL никогда не двигается к точке входа
❌ **Нет привязки к TP** — Trailing SL и TP работают независимо

```python
# В should_close_position:
# Проверки: loss_cut → timeout → price_check → min_holding
# НЕТ проверки: "Если прибыль > X%, подтянуть SL в безубыток"
```

---

## 🔴 КРИТИЧЕСКАЯ ПРОБЛЕМА #4: TAKE PROFIT — **СТАТИЧЕН, НЕ ДВИГАЕТСЯ**

### Локация:
`src/strategies/scalping/futures/positions/take_profit_manager.py`

### Как работает:
```python
async def check_tp(self, position, current_price):
    # 1. Получает tp_percent из конфига
    tp_percent = self._get_tp_percent(symbol, regime, current_price)
    
    # 2. Сравнивает текущий PnL с tp_percent
    if pnl_percent >= tp_percent:
        await self.close_position_callback(position, "take_profit")
```

### Проблемы:
1. **TP фиксирован при открытии** — не двигается при продлении тренда
2. **Нет trailing TP** — нет механизма "если прибыль растёт, двигать TP выше"
3. **Нет интеграции с TSL** — при срабатывании TSL, TP не обновляется

```python
# Поиск:
trailing_tp       # ← НЕ НАЙДЕНО
move_tp           # ← НЕ НАЙДЕНО
update_tp         # ← НЕ НАЙДЕНО
tp_trail          # ← НЕ НАЙДЕНО
```

---

## 🔴 КРИТИЧЕСКАЯ ПРОБЛЕМА #5: БЕЗУБЫТОК (BREAKEVEN) — **ОТСУТСТВУЕТ**

### Что должно быть:
```python
# Когда прибыль достигает X%:
if profit_pct > breakeven_trigger:  # например, 0.5%
    new_sl = entry_price * (1 + fee_buffer)  # SL в безубыток + комиссия
    update_stop_loss(new_sl)
```

### Что есть:
**НИЧЕГО.** Поиск по коду:
```python
breakeven          # ← НЕ НАЙДЕНО
break_even         # ← НЕ НАЙДЕНО
move_sl_to_entry   # ← НЕ НАЙДЕНО
sl_to_entry        # ← НЕ НАЙДЕНО
```

### Эффект:
- Позиция в прибыли +1.5%
- TSL подтянулся до +1.0%
- Цена разворачивается
- Закрытие по TSL @ +1.0%
- **Вместо безубытка — убыток от комиссии!**

---

## ИТОГОВАЯ ТАБЛИЦА СИСТЕМ

| Система | Статус | Критичность | Примечание |
|---------|--------|-------------|------------|
| **Продление сделок** | ❌ ОТСУТСТВУЕТ | 🔴 Критическая | Бот закрывает и открывает новую вместо продления |
| **Лестничное усреднение** | 🟡 Частично | 🟡 Средняя | Код есть, но не интегрирован в цикл |
| **Trailing Stop Loss** | ✅ Работает | 🟢 Низкая | Двигает SL, но нет безубытка |
| **Trailing Take Profit** | ❌ ОТСУТСТВУЕТ | 🔴 Критическая | TP статичен, не двигается с трендом |
| **Безубыток (Breakeven)** | ❌ ОТСУТСТВУЕТ | 🔴 Критическая | SL никогда не двигается к точке входа |
| **Интеграция TSL+TP** | ❌ ОТСУТСТВУЕТ | 🔴 Критическая | Системы работают изолированно |

---

## ПОЧЕМУ БОТ "НЕ РАБОТАЕТ" ПО ФАКТУ

### Сценарий реальной торговли:

```
1. Сигнал на H1: тренд UP
2. Бот открывает LONG @ $95,000
   TP: $96,425 (+1.5%)
   SL: $94,050 (-1.0%)
   
3. Цена растёт до $96,000 (+1.05%)
   TSL активирован, стоп подтянут до $95,520 (+0.55%)
   
4. Новый сигнал на H1: тренд UP продолжается
   Ожидание: Продлить сделку, двигать TP к $97,000
   
   Реальность:
   - Системы продления НЕТ
   - TP статичен @ $96,425
   - Цена колеблется $95,800-$96,200
   
5. Цена падает до $95,500
   TSL сработал @ $95,520 (+0.55%)
   Позиция закрыта
   
6. Через 5 минут новый сигнал
   Бот открывает НОВУЮ позицию @ $95,600
   (комиссия + проскальзывание)
   
7. Цена растёт до $96,500 (+0.9%)
   TP статичен @ $97,050 (+1.5%)
   TSL подтянут до $96,200 (+0.6%)
   
8. Разворот, закрытие по TSL @ $96,200
   
ИТОГО:
- Сделка 1: +0.55% - комиссия = +0.51%
- Сделка 2: +0.60% - комиссия = +0.56%
- Вместо одной продолжительной сделки с +1.5%
```

---

## РЕКОМЕНДАЦИИ ПО ИСПРАВЛЕНИЮ

### 1. Система продления сделок (Priority: P0)
```python
class PositionExtensionManager:
    async def should_extend_position(self, symbol, current_signal):
        # Проверить:
        # 1. Есть ли открытая позиция
        # 2. Совпадает ли направление сигнала с позицией
        # 3. Сильный ли тренд (ADX > 25)
        # 4. Прибыль позиции > min_profit_for_extension
        
    async def extend_position(self, symbol, new_tp_percent):
        # 1. Обновить TP в позиции
        # 2. Обновить время жизни (timeout)
        # 3. Залогировать продление
```

### 2. Безубыток (Priority: P0)
```python
# В TrailingStopLoss.update():
if profit_pct > breakeven_trigger and not self.breakeven_activated:
    # Подтянуть SL к entry_price + комиссия
    self.breakeven_price = self.entry_price * (1 + fee_buffer)
    if self.side == "long":
        self.highest_price = max(self.highest_price, self.breakeven_price)
    else:
        self.lowest_price = min(self.lowest_price, self.breakeven_price)
    self.breakeven_activated = True
```

### 3. Trailing Take Profit (Priority: P1)
```python
class TrailingTakeProfit:
    def update(self, current_price, profit_pct):
        # Если прибыль растёт, двигать TP выше
        # Например: TP = max(fixed_tp, current_price * 0.995)
```

### 4. Интеграция DCA (Priority: P1)
```python
# В trading_control_center.py:
async def manage_positions():
    for symbol, position in positions.items():
        # Проверить долив
        if await position_scaling_manager.can_add_to_position(symbol):
            size = await position_scaling_manager.calculate_next_addition_size(...)
            if size:
                await add_to_position(symbol, size)
```
