# 🔴 БАГ НАЙДЕН: EXECUTED ФЛАГ НИКОГДА НЕ ОБНОВЛЯЕТСЯ

**Статус:** КРИТИЧНЫЙ БАГ ИД ОЧЕНЬ ВАЖНЫЙ!

---

## 🐛 ОПИСАНИЕ ПРОБЛЕМЫ

### Где находится баг:

**Файл 1:** `src/strategies/scalping/futures/signal_generator.py` (Line 1608)

```python
self.performance_tracker.record_signal(
    symbol=signal.get("symbol", ""),
    side=signal.get("side", ""),
    price=signal.get("price", 0.0),
    strength=signal.get("strength", 0.0),
    regime=signal.get("regime"),
    filters_passed=filters_passed,
    executed=False,  # ← ВСЕГДА ФАЛЬШ!
    order_id=None,   # ← ВСЕГДА НОЛЬ!
)
```

**Файл 2:** `src/strategies/scalping/futures/positions/entry_manager.py` (Line 644-653)

```python
# Вызывается когда ордер УСПЕШНО размещен:
self.conversion_metrics.record_signal_executed(
    symbol=symbol, 
    signal_type=signal_type, 
    regime=final_regime
)

# НО ОТСУТСТВУЕТ:
# self.performance_tracker.record_signal(
#     symbol=symbol,
#     executed=True,  # ← НУЖНО ДОБАВИТЬ!
#     order_id=order_id,
# )
```

---

## 🔍 ЧТО ПРОИСХОДИТ

### Последовательность событий:

```
1. SignalGenerator генерирует сигнал
   └─ Вызывает: performance_tracker.record_signal(..., executed=False)
   └─ CSV получает строку с executed=0

2. Сигнал проходит фильтры и отправляется в order_executor
   └─ (нет логирования фильтра)

3. OrderExecutor размещает ордер
   └─ Вызывает: conversion_metrics.record_signal_executed()
   └─ НО НЕ обновляет performance_tracker!

4. CSV остаётся с executed=0 для ВСЕХ сигналов
   └─ Даже если ордер был успешно размещен!
```

---

## 💥 ПОСЛЕДСТВИЯ

**Неправильные данные в CSV:**

```
311 сигналов в CSV:
  - BTC: 55 signals, ALL with executed=0  ❌
  - SOL: 96 signals, ALL with executed=0  ❌
  - XRP: 124 signals, ALL with executed=0 ❌
  - ETH: 21 signals, ALL with executed=0  ❌
  - DOGE: 15 signals, ALL with executed=0 ❌

27 ордеров БЫЛИ размещены успешно
  - Но в CSV это не отражено!
  - executed флаг остался = 0
  - order_id остался = None
```

**Результат:**
- ❌ Невозможно анализировать конверсию сигналов
- ❌ Невозможно найти какой фильтр отклоняет сигналы
- ❌ Невозможно связать сигналы с ордерами
- ❌ All data in CSV is broken!

---

## ✅ РЕШЕНИЕ

### Шаг 1: Добавить обновление performance_tracker в entry_manager.py

**Файл:** `src/strategies/scalping/futures/positions/entry_manager.py`

**После строки 653 (после record_position_open), добавить:**

```python
# ✅ ИСПРАВЛЕНИЕ: Обновляем сигнал в CSV как исполненный
if self.performance_tracker:
    try:
        self.performance_tracker.record_signal(
            symbol=symbol,
            side=signal.get("side", ""),
            price=signal.get("price", 0.0),
            strength=signal.get("strength", 0.0),
            regime=final_regime or signal.get("regime"),
            filters_passed=signal.get("filters_passed", []),
            executed=True,  # ← ИСПРАВЛЕНО!
            order_id=order_result.get("order_id"),
        )
        logger.debug(
            f"✅ EntryManager: Сигнал обновлён в CSV как исполненный {symbol}"
        )
    except Exception as e:
        logger.warning(
            f"⚠️ EntryManager: Ошибка обновления сигнала в CSV: {e}"
        )
```

---

## 🧪 КАК ПРОВЕРИТЬ ИСПРАВЛЕНИЕ

После добавления исправления, запустить снова и проверить CSV:

```python
import pandas as pd

df = pd.read_csv('all_data_2026-01-06.csv')
signals_df = df[df['record_type'] == 'signals']

executed = len(signals_df[signals_df['executed'] == 1])
rejected = len(signals_df[signals_df['executed'] == 0])

print(f"Executed: {executed}")
print(f"Rejected: {rejected}")
print(f"Conversion: {executed/(executed+rejected)*100:.1f}%")

# ОЖИДАЕМЫЙ РЕЗУЛЬТАТ:
# Executed: 27 (или близко к 27)
# Rejected: 284
# Conversion: 8.7%
```

---

## 🎯 ИТОГ

**Баг:** Флаг `executed` инициализируется как `False` и **никогда не обновляется** когда ордер размещен.

**Причина:** Отсутствует вызов `performance_tracker.record_signal(..., executed=True)` в entry_manager.

**Воздействие:** ВСЕ 311 сигналов в CSV показаны как `executed=0` даже если 27 из них привели к ордерам.

**Исправление:** Добавить один вызов в entry_manager после успешного размещения ордера.

**Важность:** КРИТИЧНАЯ - без этого невозможно анализировать логи или улучшать стратегию.

