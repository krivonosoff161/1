# 🧮 ПРОМПТ ДЛЯ KIMMIE: ПОЛНАЯ ПРОВЕРКА МАТЕМАТИКИ ПРОЕКТА

## 📋 ЗАДАЧА
Проведи **полный аудит математики** торгового бота OKX, включая:
1. **Адаптивные балансы** (3 режима)
2. **Торговая логика** (Spot + Futures)
3. **Расчет позиций** (маржа, леверидж)
4. **ТП/СЛ логика** (трайлинг, микро-пивоты)
5. **Риск-менеджмент** (ликвидация, проскальзывание)
6. **Консистентность формул** во всех модулях

---

## 🔍 КЛЮЧЕВЫЕ ФАЙЛЫ ДЛЯ АНАЛИЗА

### 1. Конфигурация балансов
```
config/config_spot.yaml
config/config_futures.yaml
src/config.py
```

**Задачи:**
- Проверить корректность 3-х режимов баланса
- Проверить пороги ($100-$1500, $1500-$2300, $2300+)
- Проверить минимальные значения ордеров ($10, $15, $20)
- Проверить структуру `adaptive_minimums`

### 2. Проверка баланса
```
src/strategies/modules/balance_checker.py
```

**Задачи:**
- Проверить метод `_get_adaptive_minimum()` - правильно ли выбирает минимум?
- Проверить расчет `total_balance_usd` - учитывает ли все активы?
- Проверить `_check_usdt_balance()` - правильно ли считает резерв?
- Проверить `_check_asset_balance()` - корректно ли для SHORT?

**Вопросы:**
```python
# Правильно ли работает эта логика?
if total_balance_usd <= 1500:
    return 10.0  # Малый баланс
elif total_balance_usd <= 2300:
    return 15.0  # Средний баланс
else:
    return 20.0  # Большой баланс
```

### 3. Futures: Маржа и ликвидация
```
src/strategies/modules/margin_calculator.py
src/strategies/modules/liquidation_guard.py
```

**Задачи:**
- Проверить формулу `calculate_max_safe_size()`:
  ```python
  max_size = (balance * leverage * (1 - safety_buffer)) / entry_price
  max_safe_size = max_size * (1 - sl_percent)
  ```
- Проверить формулу `calculate_liquidation_price()`:
  ```python
  # Long
  liq_price = entry_price * (1 - (1/leverage) + maintenance_margin)
  
  # Short
  liq_price = entry_price * (1 + (1/leverage) - maintenance_margin)
  ```
- Проверить пороги ликвидации (warning_threshold, danger_threshold, critical_threshold)
- Проверить авто-закрытие позиций при критической марже

**Вопросы:**
```python
# Правильно ли работает страховой буфер 1%?
available_margin = balance_usd * (1 - self.safety_buffer)  # 0.01

# Правильно ли расчет ликвидации?
if side == "long":
    liq_price = entry * (1 - (1/3) + 0.005)  # leverage=3, maint=0.005
```

### 4. Futures: Order Flow и Delta
```
src/strategies/scalping/futures/indicators/order_flow_indicator.py
```

**Задачи:**
- Проверить формулу delta:
  ```python
  delta = (bid_volume - ask_volume) / (bid_volume + ask_volume)
  ```
- Проверить логику `is_long_favorable()` и `is_short_favorable()`
- Проверить трендовый анализ `get_delta_trend()`
- Проверить метрики рыночного давления

**Вопросы:**
```python
# Правильно ли рассчитывается delta?
delta = (bid - ask) / (bid + ask)  # Диапазон: [-1, 1]

# Правильно ли пороги?
if delta > 0.1:  # Благоприятен для лонга
if delta < -0.1:  # Благоприятен для шорта
```

### 5. Futures: Micro Pivots
```
src/strategies/scalping/futures/indicators/micro_pivot_calculator.py
```

**Задачи:**
- Проверить формулу классических пивотов:
  ```python
  pivot = (high + low + close) / 3
  r1 = 2 * pivot - low
  s1 = 2 * pivot - high
  r2 = pivot + (high - low)
  s2 = pivot - (high - low)
  ```
- Проверить Camarilla пивоты:
  ```python
  cam_r1 = close + (high - low) * 0.08333
  cam_s1 = close - (high - low) * 0.08333
  ```
- Проверить Fibonacci пивоты:
  ```python
  fib_r1 = pivot + 0.382 * (high - low)
  fib_r2 = pivot + 0.618 * (high - low)
  ```
- Проверить логику выбора оптимального TP

**Вопросы:**
```python
# Правильно ли выбирается ближайший уровень?
if side == "long":
    target = min(r1, cam_r1)  # Берем минимальную цель
else:
    target = max(s1, cam_s1)  # Берем максимальную цель

# Правильно ли ограничение максимального расстояния?
if target - entry > max_distance:
    target = entry + max_distance
```

### 6. Проскальзывание и спред
```
src/strategies/modules/slippage_guard.py
```

**Задачи:**
- Проверить расчет спреда:
  ```python
  spread = (ask - bid) / mid
  ```
- Проверить расчет проскальзывания:
  ```python
  if side == "buy":
      slippage = (order_price - ask) / ask
  else:
      slippage = (bid - order_price) / bid
  ```
- Проверить пороги (max_slippage_percent, max_spread_percent)

**Вопросы:**
```python
# Правильно ли расчет проскальзывания для лонга?
slippage = (order - ask) / ask  # Если order > ask → slippage > 0

# Правильно ли для шорта?
slippage = (bid - order) / bid  # Если order < bid → slippage > 0

# Правильно ли пороги?
if slippage > 0.1% or spread > 0.05%:
    reject_order()
```

### 7. Адаптивный режим
```
src/strategies/modules/adaptive_regime_manager.py
```

**Задачи:**
- Проверить определение режима рынка (FLAT, TRENDING, SIDEWAYS)
- Проверить адаптивные коэффициенты TP/SL
- Проверить влияние баланса на параметры
- Проверить консистентность между Spot и Futures

**Вопросы:**
```python
# Правильно ли выбор режима?
if volatility < 0.01 and adx < 20:
    regime = FLAT  # Боковой рынок
elif volatility > 0.03 and adx > 30:
    regime = TRENDING  # Трендовый рынок

# Правильно ли адаптивные TP?
if regime == FLAT:
    tp_multiplier = 0.8  # Меньший TP
elif regime == TRENDING:
    tp_multiplier = 1.5  # Больший TP
```

### 8. Размер позиции и риск
```
src/strategies/modules/position_size_calculator.py (если есть)
src/risk/risk_controller.py
```

**Задачи:**
- Проверить расчет размера позиции:
  ```python
  risk_amount = balance * risk_per_trade_percent
  size = risk_amount / (sl_distance * price)
  ```
- Проверить максимальный размер:
  ```python
  max_size = balance * max_position_size_percent
  ```
- Проверить лимиты (max_open_positions, max_daily_loss)

**Вопросы:**
```python
# Правильно ли расчет размера с учетом риска?
risk_usd = balance * 0.01  # 1% риск
sl_distance = entry - sl  # Расстояние до SL
size = risk_usd / sl_distance

# Правильно ли ограничение?
optimal_size = min(size, max_size)
```

---

## ⚠️ КРИТИЧЕСКИЕ ВОПРОСЫ

### 1. **Консистентность формул**
- Все ли формулы используют **одинаковые единицы измерения** (проценты vs коэффициенты)?
- Корректно ли округление (сколько знаков после запятой)?
- Учитывается ли **комиссия** в расчетах?

### 2. **Граничные случаи**
- Что если `balance = 0`?
- Что если `sl_distance = 0`?
- Что если `ask == bid` (спред = 0)?
- Что если `delta = 0` (равновесие)?
- Что если `high == low` (нет движения)?

### 3. **Переполнение и подполнение**
- Возможно ли переполнение при расчете `max_size`?
- Возможно ли деление на ноль?
- Корректно ли обработка исключений?

### 4. **Логические ошибки**
- Правильно ли знаки в формулах (`+` vs `-`)?
- Правильно ли логика выбора (`min` vs `max`)?
- Правильно ли условия (`<` vs `<=`, `>` vs `>=`)?

### 5. **Параметры конфигурации**
- Корректны ли значения по умолчанию?
- Проверяются ли границы параметров (min, max)?
- Используются ли параметры везде одинаково?

---

## 📊 ТАБЛИЦА ПРОВЕРКИ

| Модуль | Формула | Ожидаемый результат | Фактический результат | Статус |
|--------|---------|---------------------|---------------------|---------|
| **Balance Check** | `min = 10 if balance <= 1500 else 15 if balance <= 2300 else 20` | min = 10 при $800 | ? | ⏳ |
| **Margin Calc** | `max_size = (balance * leverage * 0.99) / price` | max_size = X | ? | ⏳ |
| **Liquidation** | `liq = entry * (1 - 1/3 + 0.005)` | liq = X | ? | ⏳ |
| **Order Flow** | `delta = (bid - ask) / (bid + ask)` | delta в [-1, 1] | ? | ⏳ |
| **Micro Pivot** | `pivot = (h + l + c) / 3` | pivot между h и l | ? | ⏳ |
| **Slippage** | `slip = (order - ask) / ask` | slip в процентах | ? | ⏳ |
| **Position Size** | `size = risk / sl_distance` | size > 0 | ? | ⏳ |

---

## 🎯 ИТОГОВЫЕ ЗАДАНИЯ

1. ✅ Проверить **все формулы** в указанных файлах
2. ✅ Проверить **граничные случаи** (balance=0, sl=0, и т.д.)
3. ✅ Проверить **логические ошибки** (знаки, условия)
4. ✅ Проверить **консистентность** (одинаковые формулы везде)
5. ✅ Проверить **параметры** (значения по умолчанию, границы)
6. ✅ Создать **таблицу найденных проблем** с приоритетами
7. ✅ Предложить **исправления** для каждой проблемы

---

## 💡 КРИТЕРИИ ОЦЕНКИ

**Отлично:**
- Все формулы математически корректны
- Все граничные случаи обработаны
- Нет логических ошибок
- Консистентность везде

**Хорошо:**
- 1-2 небольшие проблемы
- Минимальные улучшения нужны

**Требует исправлений:**
- >3 проблемы
- Критические ошибки в формулах
- Нет обработки граничных случаев

---

**ПРИСТУПИ К АУДИТУ!** 🚀
