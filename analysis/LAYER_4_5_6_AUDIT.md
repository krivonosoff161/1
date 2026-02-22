# Layer 4-6: Выход, Адаптивность, Наблюдаемость — АУДИТ

## Дата: 2026-02-22

---

## Layer 4: Выход

### 🔴 L4-1: Множественные пути закрытия позиции

**Severity:** 🔴 Высокая

**Файл:** `src/strategies/scalping/futures/orchestrator.py`

**Root cause:**
- `_close_position()` вызывается из многих мест
- Нет единого entrypoint как требует CLAUDE.md

**Места вызовов:**
```
1. trailing_sl_coordinator → _close_position_for_tsl_callback
2. signal_coordinator → _close_position_for_tsl_callback
3. smart_exit_coordinator → _close_position
4. position_monitor → close_position_callback
5. exit_analyzer → напрямую?
6. emergency_stop → _emergency_close_all_positions
```

**Влияние на PnL:**
- Возможны race conditions при одновременных сигналах
- Дублирование закрытий или пропуски
- Оценка: до 0.5% на сделку

**Предложение:** Все закрытия через ExitDecisionCoordinator

---

### 🟡 L4-2: TTLCache 60 секунд может блокировать emergency close

**Severity:** 🟡 Средняя (уже частично исправлено)

**Файл:** `src/strategies/scalping/futures/orchestrator.py:5170`

**Root cause:**
- `TTLCache(maxsize=100, ttl=60.0)` — позиция в кэше 60 секунд
- Но есть `force` параметр для bypass

**Код:**
```python
if not force and symbol in self._closing_positions_cache:
    logger.debug(f"Position {symbol} already closing (TTLCache), skip")
    return
```

**Влияние на PnL:** Минимальное — force bypass есть

---

### 🟡 L4-3: Нет гарантии единственности закрытия

**Severity:** 🟡 Средняя

**Root cause:**
- Есть `_closing_locks` и `TTLCache`
- Но нет атомарной проверки "позиция закрыта на бирже"

**Влияние на PnL:**
- Двойное закрытие → двойная комиссия
- Оценка: 0.02-0.04% лишних комиссий

---

## Layer 5: Адаптивность

### 🟡 L5-1: ADX пороги — одинаковы для всех символов

**Severity:** 🟡 Средняя

**Файл:** `src/strategies/scalping/futures/adaptivity/regime_manager.py`

**Root cause:**
- `trending > 25, choppy < 20` — фиксированные значения
- Нет per-symbol ADX thresholds

**Влияние на PnL:**
- DOGE с ADX=22 считается ranging, ETH с ADX=22 тоже
- Но волатильность разная!
- Оценка: 1-2% ложных режимов

**Предложение:** Добавить by_symbol ADX thresholds

---

### 🟡 L5-2: Баланс-профили — переключение без гистерезиса

**Severity:** 🟡 Средняя

**Root cause:**
- При $490 → $510: мгновенное переключение micro → small
- Может привести к частым переключениям на границе

**Влияние на PnL:**
- Нестабильные параметры на границе профиля
- Оценка: до 0.3% на сделку

**Предложение:** Добавить гистерезис ±5% на переключение

---

### 🟢 L5-3: Статистика → адаптация — не реализовано

**Severity:** 🟢 Низкая

**Root cause:**
- `trading_statistics.py` собирает данные
- Но нет обратной связи для адаптации параметров

**Влияние на PnL:** Минимальное — ручная настройка работает

---

## Layer 6: Наблюдаемость

### 🟡 L6-1: Telegram — не все события покрыты

**Severity:** 🟡 Средняя

**Root cause:**
- Уведомления при открытии есть
- Но нет уведомлений при:
  - Закрытии позиции (PnL)
  - Emergency stop
  - Смене режима
  - Блокировке символа

**Влияние на PnL:** Операционный риск — не заметить проблему

---

### 🟢 L6-2: Correlation ID — не везде

**Severity:** 🟢 Низкая

**Root cause:**
- Correlation ID есть в некоторых местах
- Но не связан вход → выход для всей цепочки

**Влияние на PnL:** Минимальное — только отладка

---

## СВОДНАЯ ТАБЛИЦА Layer 4-6

| ID | Проблема | Severity | Влияние | Действие |
|----|----------|----------|---------|----------|
| L4-1 | Множественные пути закрытия | 🔴 | До 0.5% | Унифицировать |
| L4-2 | TTLCache 60с (частично fixed) | 🟡 | Минимальное | Проверить force bypass |
| L4-3 | Нет атомарности закрытия | 🟡 | 0.02-0.04% | Добавить проверку биржи |
| L5-1 | ADX пороги одинаковые | 🟡 | 1-2% | Per-symbol thresholds |
| L5-2 | Баланс без гистерезиса | 🟡 | До 0.3% | Добавить гистерезис |
| L5-3 | Статистика не адаптирует | 🟢 | Минимальное | Реализовать feedback |
| L6-1 | Telegram неполный | 🟡 | Операционный | Добавить уведомления |
| L6-2 | Correlation ID не везде | 🟢 | Отладка | Расширить покрытие |

---

## РЕКОМЕНДАЦИИ

### P0:
1. **L4-1** — Унифицировать закрытия через ExitDecisionCoordinator

### P1:
2. **L5-1** — Per-symbol ADX thresholds
3. **L6-1** — Дополнить Telegram уведомления
4. **L5-2** — Гистерезис для баланс-профилей

### P2:
5. **L4-3** — Атомарность закрытия
6. **L5-3** — Адаптация из статистики
7. **L6-2** — Correlation ID везде
