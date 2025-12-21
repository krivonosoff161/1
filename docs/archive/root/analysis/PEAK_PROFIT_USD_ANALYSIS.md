# 🔍 АНАЛИЗ ИСПОЛЬЗОВАНИЯ peak_profit_usd

**Дата:** 2025-12-08  
**Проблема:** После `partial_close` используется старый `peak_profit_usd` вместо пересчитанного

---

## 1. ГДЕ ИСПОЛЬЗУЕТСЯ peak_profit_usd В _check_profit_drawdown

### Строка 4466: `position_manager.py`
```python
peak_profit = metadata.peak_profit_usd
```

**Контекст:**
- Функция: `_check_profit_drawdown` (строка 4287)
- Получение metadata: строка 4375
  ```python
  metadata = await self.orchestrator.position_registry.get_metadata(symbol)
  ```
- Использование: строка 4466
  ```python
  peak_profit = metadata.peak_profit_usd
  ```
- Расчет drawdown: строка 4654-4655
  ```python
  drawdown_percent = (
      (peak_profit - net_pnl) / peak_profit if peak_profit > 0 else 0
  )
  ```

**Проблема:** `metadata.peak_profit_usd` берется из `position_registry`, но может быть устаревшим, если `partial_close` только что выполнился.

---

## 2. ГДЕ ПЕРЕСЧИТЫВАЕТСЯ peak_profit_usd ПОСЛЕ partial_close

### Строки 5608-5716: `position_manager.py` (функция `close_partial_position`)

**Пересчет:**
```python
# ✅ НОВОЕ: Пересчет peak_profit_usd после partial_close
new_peak_profit_usd = 0.0
new_peak_profit_time = None
new_peak_profit_price = None

# ... расчет для оставшейся позиции ...

# Обновление в position_registry
if new_peak_profit_usd is not None:
    metadata_updates["peak_profit_usd"] = new_peak_profit_usd
if new_peak_profit_time is not None:
    metadata_updates["peak_profit_time"] = new_peak_profit_time
if new_peak_profit_price is not None:
    metadata_updates["peak_profit_price"] = new_peak_profit_price

await self.position_registry.update_position(
    symbol,
    metadata_updates=metadata_updates,
)
```

**Статус:** ✅ Пересчет выполняется корректно

---

## 3. ПРОБЛЕМА: ОТСУТСТВУЕТ ОБРАБОТКА partial_tp_executed В _update_peak_profit

### Строки 4198-4271: `position_manager.py` (функция `_update_peak_profit`)

**Текущая логика:**
```python
if metadata:
    # ✅ ИСПРАВЛЕНИЕ #1: Первое обновление
    if (
        metadata.peak_profit_usd == 0.0
        and metadata.peak_profit_time is None
    ):
        metadata.peak_profit_usd = net_pnl
        # ...
    
    # ✅ ИСПРАВЛЕНИЕ #2: PnL улучшился
    elif net_pnl > metadata.peak_profit_usd:
        metadata.peak_profit_usd = net_pnl
        # ...
```

**Проблема:** ❌ НЕТ проверки на `partial_tp_executed`!

После `partial_close`:
1. `peak_profit_usd` обновляется в `position_registry` (строка 5702)
2. Но в `_update_peak_profit` нет логики, которая бы проверяла `partial_tp_executed` и сбрасывала старый `peak_profit_usd`

**Результат:** При следующем вызове `_update_peak_profit` может использоваться старый `peak_profit_usd` из кэша metadata, если он не был перезагружен из `position_registry`.

---

## 4. КОНКРЕТНЫЕ СТРОКИ КОДА

### Использование в _check_profit_drawdown:

| Строка | Код | Описание |
|--------|-----|----------|
| 4375 | `metadata = await self.orchestrator.position_registry.get_metadata(symbol)` | Получение metadata |
| 4466 | `peak_profit = metadata.peak_profit_usd` | **ИСПОЛЬЗОВАНИЕ peak_profit_usd** |
| 4654-4655 | `drawdown_percent = (peak_profit - net_pnl) / peak_profit if peak_profit > 0 else 0` | Расчет drawdown |

### Пересчет после partial_close:

| Строка | Код | Описание |
|--------|-----|----------|
| 5608-5613 | `new_peak_profit_usd = 0.0` | Инициализация нового peak |
| 5659-5671 | Расчет `new_peak_profit_usd` для оставшейся позиции | Пересчет peak |
| 5701-5702 | `metadata_updates["peak_profit_usd"] = new_peak_profit_usd` | Обновление в metadata_updates |
| 5710-5713 | `await self.position_registry.update_position(...)` | Сохранение в registry |

### Отсутствие обработки в _update_peak_profit:

| Строка | Код | Проблема |
|--------|-----|----------|
| 4198-4271 | Логика обновления `peak_profit_usd` | ❌ НЕТ проверки `partial_tp_executed` |

---

## 5. ИТОГОВЫЙ ВЫВОД

### Основная проблема:

**В `_update_peak_profit` отсутствует обработка `partial_tp_executed`.**

После `partial_close`:
1. ✅ `peak_profit_usd` пересчитывается в `close_partial_position` (строка 5702)
2. ✅ Обновляется в `position_registry` (строка 5710)
3. ❌ Но в `_update_peak_profit` нет проверки на `partial_tp_executed`, которая бы сбрасывала старый `peak_profit_usd` при первом обновлении после `partial_close`

**Результат:** При следующем вызове `_update_peak_profit` может использоваться старый `peak_profit_usd` из metadata, если он не был перезагружен из `position_registry`.

---

## 6. РЕКОМЕНДАЦИИ

### 1. Добавить обработку `partial_tp_executed` в `_update_peak_profit` (КРИТИЧНО)

**Место:** `position_manager.py`, функция `_update_peak_profit`, после строки 4198

**Код:**
```python
if metadata:
    # ✅ НОВОЕ: Обработка partial_tp_executed
    if hasattr(metadata, "partial_tp_executed") and metadata.partial_tp_executed:
        # После partial_close сбрасываем peak_profit_usd и начинаем отслеживать заново
        if net_pnl > 0:
            metadata.peak_profit_usd = net_pnl
            metadata.peak_profit_time = datetime.now(timezone.utc)
            metadata.peak_profit_price = current_price
            logger.debug(
                f"🔍 [UPDATE_PEAK_PROFIT] {symbol}: Partial TP выполнен, "
                f"peak_profit_usd пересчитан до ${net_pnl:.4f}"
            )
        else:
            metadata.peak_profit_usd = 0.0
            metadata.peak_profit_time = None
            metadata.peak_profit_price = None
            logger.debug(
                f"🔍 [UPDATE_PEAK_PROFIT] {symbol}: Partial TP выполнен, "
                f"PnL <= 0, peak_profit_usd сброшен"
            )
        # Сбрасываем флаг после обработки
        metadata.partial_tp_executed = False
        
        # Обновляем в position_registry
        if hasattr(self, "orchestrator") and self.orchestrator:
            if hasattr(self.orchestrator, "position_registry"):
                await self.orchestrator.position_registry.update_position(
                    symbol,
                    metadata_updates={
                        "peak_profit_usd": metadata.peak_profit_usd,
                        "peak_profit_time": metadata.peak_profit_time,
                        "peak_profit_price": metadata.peak_profit_price,
                        "partial_tp_executed": False,
                    },
                )
        return  # Выходим, чтобы не выполнять обычную логику обновления
    
    # ✅ ИСПРАВЛЕНИЕ #1: Первое обновление - устанавливаем текущий PnL
    if (
        metadata.peak_profit_usd == 0.0
        and metadata.peak_profit_time is None
    ):
        # ... существующий код ...
```

### 2. Добавить перезагрузку metadata в `_check_profit_drawdown` (ОПЦИОНАЛЬНО)

**Место:** `position_manager.py`, функция `_check_profit_drawdown`, после строки 4377

**Код:**
```python
# ✅ НОВОЕ: Перезагружаем metadata перед использованием (защита от устаревших данных)
if hasattr(self, "orchestrator") and self.orchestrator:
    if hasattr(self.orchestrator, "position_registry"):
        # Перезагружаем metadata для получения актуальных данных
        metadata = await self.orchestrator.position_registry.get_metadata(symbol)
```

---

## 7. КОНКРЕТНЫЕ СТРОКИ ДЛЯ ИСПРАВЛЕНИЯ

### Файл: `src/strategies/scalping/futures/position_manager.py`

1. **Строка 4198** - добавить обработку `partial_tp_executed` перед существующей логикой
2. **Строка 4377** (опционально) - добавить перезагрузку metadata перед использованием

---

**Сгенерировано:** 2025-12-08  
**Источник:** Анализ кода и логов закрытия DOGE-USDT


