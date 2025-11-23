# ОБЪЯСНЕНИЕ FALLBACK ЗНАЧЕНИЙ

**Дата:** 23 ноября 2025  
**Вопрос:** Остаются ли fallback значения?

---

## ✅ ДА, FALLBACK ЗНАЧЕНИЯ ОСТАЮТСЯ

### Почему это важно:

**Fallback значения = Защита от ошибок**

Это означает:
1. ✅ **Безопасность:** Система не сломается, если что-то не настроено
2. ✅ **Надежность:** Система продолжит работать даже при ошибках конфигурации
3. ✅ **Гибкость:** Можно использовать частичные настройки (не обязательно настраивать все)

---

## ✅ КАК РАБОТАЮТ FALLBACK ЗНАЧЕНИЯ

### Приоритет настроек (с fallback):

1. **Per-symbol + Per-regime** (если есть)
   ```python
   if symbol and limit_order_config.get("by_symbol"):
       symbol_config = limit_order_config.get("by_symbol", {}).get(symbol, {})
       if regime and symbol_config.get("by_regime"):
           regime_config = symbol_config.get("by_regime", {}).get(regime, {})
           symbol_regime_offset = regime_config.get("limit_offset_percent")
           if symbol_regime_offset is not None:
               offset_percent = symbol_regime_offset  # ✅ Используется
           else:
               # ✅ FALLBACK: на per-symbol offset
               symbol_offset = symbol_config.get("limit_offset_percent")
               if symbol_offset is not None:
                   offset_percent = symbol_offset
   ```

2. **Per-symbol** (если нет режима или режим не найден)
   ```python
   symbol_offset = symbol_config.get("limit_offset_percent")
   if symbol_offset is not None:
       offset_percent = symbol_offset  # ✅ Используется
   ```

3. **Per-regime** (если per-symbol не найден)
   ```python
   if offset_percent is None and regime and limit_order_config.get("by_regime"):
       regime_config = limit_order_config.get("by_regime", {}).get(regime, {})
       regime_offset = regime_config.get("limit_offset_percent")
       if regime_offset is not None:
           offset_percent = regime_offset  # ✅ Используется
   ```

4. **Глобальный** (FALLBACK - всегда работает)
   ```python
   if offset_percent is None:
       offset_percent = default_offset  # ✅ FALLBACK: 0.05% (из конфига)
       # Или если конфиг не найден:
       # offset_percent = 0.0  # ✅ FALLBACK: 0.0% (минимальный offset 0.01% применяется автоматически)
   ```

---

## ✅ ПРИМЕРЫ РАБОТЫ FALLBACK

### Пример 1: Все настроено

**Конфиг:**
```yaml
by_symbol:
  "BTC-USDT":
    limit_offset_percent: 0.03
    by_regime:
      ranging:
        limit_offset_percent: 0.08
```

**Результат:**
- ✅ Используется: `0.08%` (per-symbol+regime)
- ✅ Fallback не используется

---

### Пример 2: Режим не найден в per-symbol

**Конфиг:**
```yaml
by_symbol:
  "BTC-USDT":
    limit_offset_percent: 0.03
    # Нет by_regime.ranging
```

**Результат:**
- ✅ Используется: `0.03%` (per-symbol) - FALLBACK на per-symbol
- ✅ Fallback на per-regime или global не используется

---

### Пример 3: Символ не найден в by_symbol

**Конфиг:**
```yaml
by_regime:
  ranging:
    limit_offset_percent: 0.12
# Нет by_symbol для "UNKNOWN-USDT"
```

**Результат:**
- ✅ Используется: `0.12%` (per-regime) - FALLBACK на per-regime
- ✅ Fallback на global не используется

---

### Пример 4: Ничего не найдено

**Конфиг:**
```yaml
limit_offset_percent: 0.05
# Нет by_symbol, нет by_regime
```

**Результат:**
- ✅ Используется: `0.05%` (global) - FALLBACK на global
- ✅ Система продолжает работать

---

### Пример 5: Конфиг не найден

**Конфиг:**
```yaml
# Нет order_executor.limit_order
```

**Результат:**
- ✅ Используется: `0.0%` (default_offset) - FALLBACK на default
- ✅ Минимальный offset 0.01% применяется автоматически
- ✅ Система продолжает работать

---

## ✅ ЗАЧЕМ НУЖНЫ FALLBACK ЗНАЧЕНИЯ

### 1. Безопасность:

- ✅ Система не сломается, если что-то не настроено
- ✅ Ошибки конфигурации не приводят к остановке системы
- ✅ Защита от случайных ошибок

### 2. Гибкость:

- ✅ Можно использовать частичные настройки
- ✅ Не обязательно настраивать все пары сразу
- ✅ Можно добавлять настройки постепенно

### 3. Надежность:

- ✅ Система продолжит работать даже при ошибках
- ✅ Fallback гарантирует работу системы
- ✅ Минимальный offset применяется автоматически

---

## ✅ ИТОГ

### Fallback значения:

1. ✅ **Остаются** - это защита от ошибок
2. ✅ **Важны** - гарантируют работу системы
3. ✅ **Не мешают** - используются только если не найдены более приоритетные настройки

### Приоритет:

1. **Per-symbol + Per-regime** (если есть) → используется
2. **Per-symbol** (если нет режима) → используется
3. **Per-regime** (если per-symbol не найден) → используется
4. **Global** (FALLBACK) → используется только если ничего не найдено

---

**Статус:** ✅ FALLBACK ЗНАЧЕНИЯ ОСТАЮТСЯ И РАБОТАЮТ ПРАВИЛЬНО

