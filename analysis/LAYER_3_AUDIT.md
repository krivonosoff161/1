# Layer 3: Управление позицией — АУДИТ

## Дата: 2026-02-22

---

## 🔴 L3-1: Breakeven — отсутствует полностью

**Severity:** 🔴 Высокая

**Файл:** Все модули управления позицией

**Root cause:**
- Нет кода "при прибыли > X% → SL = entry_price + fee"
- TSL двигается вслед за ценой, но не гарантирует безубыток

**Поиск:**
```python
breakeven          # Не найдено
break_even         # Не найдено
move_sl_to_entry   # Не найдено
```

**Влияние на PnL:**
- Позиция в +1.5%, TSL подтянулся до +1.0%
- Разворот → закрытие +0.9% (вместо безубытка)
- Потеря 0.6% накопленной прибыли
- Оценка: до 1% потерь на сделку

**Предложение:** Добавить в TrailingStopLoss.update():
```python
if profit_pct > breakeven_trigger and not self.breakeven_activated:
    self.highest_price = max(self.highest_price, self.entry_price * (1 + fee_buffer))
    self.breakeven_activated = True
```

---

## 🟡 L3-2: max_holding — три разных реализации

**Severity:** 🟡 Средняя

**Файлы:**
- `exit_analyzer.py:2420-2536` — `_get_max_holding_minutes()`
- `position_manager.py` — предположительно своя реализация
- `trailing_sl_coordinator.py` — `timeout_minutes`

**Root cause:**
- Разные места чтения конфига
- Разные fallback значения
- Неясно какое реально применяется

**Код из exit_analyzer:**
```python
def _get_max_holding_minutes(self, regime: str, symbol: Optional[str] = None):
    max_holding_minutes = 120.0  # Default 2 часа
    # Приоритет 1: exit_params
    # Приоритет 2: adaptive_regime
    # Приоритет 3: per-symbol
```

**Влияние на PnL:**
- Непредсказуемое время удержания позиции
- Оценка: до 0.5% при неоптимальном выходе

**Предложение:** Унифицировать через ParameterProvider

---

## 🟡 L3-3: TSL для SHORT — возможна некорректная работа

**Severity:** 🟡 Средняя

**Файл:** `src/strategies/scalping/futures/indicators/trailing_stop_loss.py:478-505`

**Root cause:**
- Логика для SHORT сложная и имеет много комментариев о "исправлениях"
- Стоп может опускаться ниже entry при прибыли

**Код:**
```python
if self.lowest_price < self.entry_price:
    # Позиция в прибыли - стоп следует за минимальной ценой (опускается)
    stop_loss = self.lowest_price * (1 + self.current_trail)
    if stop_loss < self.entry_price:
        # Защита: стоп не должен быть ниже entry
        stop_loss = max(stop_loss, self.entry_price * (1 + self.initial_trail))
```

**Влияние на PnL:**
- При неправильной работе — закрытие SHORT в убыток когда должна быть прибыль
- Оценка: до 1% на сделку

**Предложение:** Протестировать логику SHORT отдельно

---

## 🟡 L3-4: DCA — условия строгие, может не срабатывать

**Severity:** 🟡 Средняя

**Файл:** `src/strategies/scalping/futures/positions/position_scaling_manager.py:147-200`

**Root cause:**
- `max_loss_for_addition = -5%` — долив только при убытке до 5%
- При трендовом движении (позиция в +2%) — долив не сработает
- `min_interval_seconds = 30` — при быстром скальпинге может быть много

**Код:**
```python
if current_pnl_percent < max_loss_for_addition:
    return {"can_add": False, "reason": "Убыток слишком велик"}
```

**Влияние на PnL:**
- Пропуск возможностей для усреднения при тренде
- Оценка: до 0.5% потерянной прибыли

**Предложение:** Добавить режим "долив при прибыли" для трендовых позиций

---

## 🟢 L3-5: Peak profit tracker — не используется для exit

**Severity:** 🟢 Низкая

**Файл:** `src/strategies/scalping/futures/positions/peak_profit_tracker.py`

**Root cause:**
- Трекер есть, но не интегрирован в exit решения
- Нет "smart exit" при откате от пика

**Влияние на PnL:** Минимальное — TSL выполняет схожую функцию

**Предложение:** Интегрировать в exit_analyzer для "exit on peak retracement"

---

## 🟡 L3-6: TSL activation threshold — не всегда достигает безубытка

**Severity:** 🟡 Средняя

**Root cause:**
- `min_profit_to_activate` — прибыль для активации TSL
- Но даже после активации TSL может не дойти до entry_price

**Влияние на PnL:**
- Позиция в +0.8%, TSL активирован
- Разворот → закрытие в +0.3% (вместо безубытка)
- Оценка: 0.3-0.5% потерь

**Предложение:** Явный breakeven уровень отдельно от TSL

---

## СВОДНАЯ ТАБЛИЦА Layer 3

| ID | Проблема | Severity | Влияние на PnL | Действие |
|----|----------|----------|----------------|----------|
| L3-1 | Breakeven отсутствует | 🔴 | До 1% | Реализовать |
| L3-2 | Три реализации max_holding | 🟡 | До 0.5% | Унифицировать |
| L3-3 | TSL для SHORT | 🟡 | До 1% | Протестировать |
| L3-4 | DCA условия строгие | 🟡 | До 0.5% | Ослабить |
| L3-5 | Peak profit не используется | 🟢 | Минимальное | Интегрировать |
| L3-6 | TSL не гарантирует breakeven | 🟡 | 0.3-0.5% | Добавить breakeven |

---

## РЕКОМЕНДАЦИИ ПО ПРИОРИТЕТАМ

### P0 (немедленно):
1. **L3-1** — Реализовать breakeven механизм

### P1 (в ближайшем спринте):
2. **L3-2** — Унифицировать max_holding
3. **L3-3** — Протестировать TSL для SHORT
4. **L3-4** — Ослабить условия DCA
5. **L3-6** — Добавить явный breakeven

### P2 (техдолг):
6. **L3-5** — Интегрировать peak profit tracker
