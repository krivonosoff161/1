# ПРОВЕРКА ЛОГИКИ FALLBACK

**Дата:** 23 ноября 2025  
**Цель:** Проверить, что fallback используется ТОЛЬКО при ошибке чтения конфига, а не параллельно

---

## ⚠️ ПРОБЛЕМА

### Опасение пользователя:
- Fallback может использоваться вместо чтения из конфига
- Параллельное использование fallback и конфига
- Хардкод параметров вместо чтения из конфига

---

## ✅ ПРОВЕРКА ТЕКУЩЕЙ ЛОГИКИ

### Текущий код (строки 231-290):

```python
# 1. Получаем глобальный fallback (но НЕ используем сразу!)
default_offset = limit_order_config.get("limit_offset_percent", 0.0)

# 2. Инициализируем offset_percent = None (НЕ используем default_offset!)
offset_percent = None

# 3. ПРИОРИТЕТ 1: Per-symbol + Per-regime (из конфига)
if symbol and limit_order_config.get("by_symbol"):
    symbol_config = limit_order_config.get("by_symbol", {}).get(symbol, {})
    if symbol_config:
        if regime and symbol_config.get("by_regime"):
            regime_config = symbol_config.get("by_regime", {}).get(regime, {})
            symbol_regime_offset = regime_config.get("limit_offset_percent")
            if symbol_regime_offset is not None:  # ✅ Проверяем, что значение найдено
                offset_percent = symbol_regime_offset  # ✅ Используем из конфига
            else:
                # Fallback на per-symbol offset (из конфига!)
                symbol_offset = symbol_config.get("limit_offset_percent")
                if symbol_offset is not None:  # ✅ Проверяем, что значение найдено
                    offset_percent = symbol_offset  # ✅ Используем из конфига

# 4. ПРИОРИТЕТ 2: Per-regime (из конфига)
if offset_percent is None and regime and limit_order_config.get("by_regime"):
    regime_config = limit_order_config.get("by_regime", {}).get(regime, {})
    regime_offset = regime_config.get("limit_offset_percent")
    if regime_offset is not None:  # ✅ Проверяем, что значение найдено
        offset_percent = regime_offset  # ✅ Используем из конфига

# 5. ПРИОРИТЕТ 3: Глобальный fallback (ТОЛЬКО если ничего не найдено)
if offset_percent is None:
    offset_percent = default_offset  # ✅ Fallback используется ТОЛЬКО если offset_percent = None
```

---

## ✅ АНАЛИЗ ЛОГИКИ

### Правильность логики:

1. ✅ **Инициализация:**
   - `offset_percent = None` (НЕ используется `default_offset` сразу)
   - `default_offset` только для fallback

2. ✅ **Приоритет 1: Per-symbol + Per-regime**
   - Проверяем `symbol_regime_offset is not None`
   - Используем ТОЛЬКО если найдено в конфиге
   - Fallback на per-symbol ТОЛЬКО если режим не найден

3. ✅ **Приоритет 2: Per-regime**
   - Проверяем `offset_percent is None` (ничего не найдено)
   - Проверяем `regime_offset is not None`
   - Используем ТОЛЬКО если найдено в конфиге

4. ✅ **Приоритет 3: Fallback**
   - Проверяем `offset_percent is None` (ничего не найдено)
   - Используем `default_offset` ТОЛЬКО если ничего не найдено

---

## ✅ ПРОВЕРКА НА ПРОБЛЕМЫ

### Потенциальная проблема #1: `default_offset = 0.0`

**Текущий код:**
```python
default_offset = limit_order_config.get("limit_offset_percent", 0.0)
```

**Проблема:**
- Если `limit_offset_percent` не найден в конфиге, используется `0.0`
- Но потом применяется минимальный offset `0.01%` автоматически

**Вывод:** ✅ Не проблема, минимальный offset применяется автоматически

---

### Потенциальная проблема #2: Проверка `is not None`

**Текущий код:**
```python
if symbol_regime_offset is not None:
    offset_percent = symbol_regime_offset
```

**Проблема:**
- Если `limit_offset_percent = 0` в конфиге, проверка `is not None` вернет `True`
- Но `0` может быть валидным значением (хотя потом применяется минимальный offset)

**Вывод:** ✅ Не проблема, минимальный offset применяется автоматически

---

### Потенциальная проблема #3: Параллельное использование

**Проверка:**
- Нет мест, где используется и fallback, и конфиг одновременно
- Логика последовательная: сначала конфиг, потом fallback

**Вывод:** ✅ Нет параллельного использования

---

## ✅ ИТОГОВАЯ ПРОВЕРКА

### Логика правильная:

1. ✅ **Сначала читаем из конфига:**
   - Per-symbol + Per-regime
   - Per-symbol
   - Per-regime
   - Global (из конфига)

2. ✅ **Fallback используется ТОЛЬКО если ничего не найдено:**
   - Проверка `offset_percent is None`
   - Fallback на `default_offset` (из конфига или `0.0`)

3. ✅ **Нет параллельного использования:**
   - Логика последовательная
   - Fallback используется только если конфиг не найден

---

## ✅ РЕКОМЕНДАЦИИ

### Улучшение логирования:

Добавить более подробное логирование для отслеживания источника offset:

```python
if offset_percent is None:
    offset_percent = default_offset
    logger.warning(  # ✅ Изменить на WARNING для отслеживания
        f"⚠️ Используется глобальный fallback offset: {offset_percent}% "
        f"(per-symbol+regime и per-regime не найдены для {symbol})"
    )
```

---

**Статус:** ✅ ЛОГИКА ПРАВИЛЬНАЯ, FALLBACK ИСПОЛЬЗУЕТСЯ ТОЛЬКО ПРИ ОТСУТСТВИИ КОНФИГА

