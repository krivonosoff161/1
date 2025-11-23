# ПРОВЕРКА FALLBACK ЛОГИКИ

**Дата:** 23 ноября 2025  
**Цель:** Убедиться, что fallback используется ТОЛЬКО при отсутствии конфига

---

## ✅ ПРОВЕРКА ЛОГИКИ

### Текущая логика (ПРАВИЛЬНАЯ):

```python
# 1. Инициализация: offset_percent = None (НЕ используем fallback сразу!)
offset_percent = None

# 2. ПРИОРИТЕТ 1: Per-symbol + Per-regime (из конфига)
if symbol and limit_order_config.get("by_symbol"):
    symbol_config = limit_order_config.get("by_symbol", {}).get(symbol, {})
    if symbol_config:
        if regime and symbol_config.get("by_regime"):
            regime_config = symbol_config.get("by_regime", {}).get(regime, {})
            symbol_regime_offset = regime_config.get("limit_offset_percent")
            if symbol_regime_offset is not None:  # ✅ Проверяем, что найдено
                offset_percent = symbol_regime_offset  # ✅ Используем из конфига
            else:
                # ✅ FALLBACK: Per-symbol (режим не найден, используем per-symbol из конфига)
                symbol_offset = symbol_config.get("limit_offset_percent")
                if symbol_offset is not None:
                    offset_percent = symbol_offset

# 3. ПРИОРИТЕТ 2: Per-regime (из конфига)
if offset_percent is None and regime and limit_order_config.get("by_regime"):
    regime_config = limit_order_config.get("by_regime", {}).get(regime, {})
    regime_offset = regime_config.get("limit_offset_percent")
    if regime_offset is not None:  # ✅ Проверяем, что найдено
        offset_percent = regime_offset  # ✅ Используем из конфига

# 4. ПРИОРИТЕТ 3: Глобальный fallback (ТОЛЬКО если offset_percent is None)
if offset_percent is None:
    offset_percent = default_offset  # ✅ Fallback ТОЛЬКО если ничего не найдено
    logger.warning(f"⚠️ FALLBACK: Используется глобальный offset...")
```

---

## ✅ ВЫВОДЫ

### Логика правильная:

1. ✅ **Сначала читаем из конфига:**
   - Per-symbol + Per-regime
   - Per-symbol (fallback внутри per-symbol)
   - Per-regime

2. ✅ **Fallback используется ТОЛЬКО если ничего не найдено:**
   - Проверка `offset_percent is None`
   - Fallback на `default_offset` (из конфига или `0.0`)

3. ✅ **Нет параллельного использования:**
   - Логика последовательная
   - Fallback используется только если конфиг не найден

---

## ✅ УЛУЧШЕНИЯ

### Добавлено улучшенное логирование:

1. ✅ **WARNING для fallback:**
   ```python
   logger.warning(
       f"⚠️ FALLBACK: Используется глобальный offset из конфига: {offset_percent}% "
       f"(per-symbol+regime и per-regime не найдены для {symbol}, regime={regime or 'N/A'})"
   )
   ```

2. ✅ **DEBUG для per-symbol fallback:**
   ```python
   logger.debug(
       f"💰 Per-symbol offset для {symbol}: {offset_percent}% "
       f"(режим {regime} не найден в per-symbol, используется per-symbol)"
   )
   ```

---

## ✅ ПРОВЕРКА ДРУГИХ МЕСТ

### Нужно проверить другие модули:

1. ⚠️ **PositionManager:** Проверить использование fallback для TP/SL
2. ⚠️ **RiskManager:** Проверить использование fallback для position sizing
3. ⚠️ **TrailingSLCoordinator:** Проверить использование fallback для TSL
4. ⚠️ **SignalGenerator:** Проверить использование fallback для фильтров

---

**Статус:** ✅ ЛОГИКА ПРАВИЛЬНАЯ, FALLBACK ИСПОЛЬЗУЕТСЯ ТОЛЬКО ПРИ ОТСУТСТВИИ КОНФИГА

