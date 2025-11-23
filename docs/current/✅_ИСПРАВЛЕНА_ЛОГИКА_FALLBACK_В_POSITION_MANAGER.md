# ИСПРАВЛЕНА ЛОГИКА FALLBACK В POSITION_MANAGER

**Дата:** 23 ноября 2025  
**Проблема:** Fallback использовался ДО проверки конфига

---

## ⚠️ НАЙДЕНА ПРОБЛЕМА

### В `position_manager.py` метод `_get_adaptive_tp_percent`:

**До исправления:**
```python
# Глобальный TP (fallback)
tp_percent = self.scalping_config.tp_percent  # ❌ ПРОБЛЕМА: Используется ДО проверки конфига!

# Получаем режим из позиции, если не передан
if not regime:
    # ...

# Получаем tp_percent для символа и режима (если есть в symbol_profiles)
if symbol and self.symbol_profiles:
    # ...
    if regime_tp_percent is not None:
        tp_percent = float(regime_tp_percent)  # ✅ Перезаписывается, но fallback уже был установлен
```

**Проблема:**
- Fallback устанавливается ДО проверки конфига
- Если конфиг найден, fallback перезаписывается, но это неправильная логика
- Fallback должен использоваться ТОЛЬКО если конфиг не найден

---

## ✅ ИСПРАВЛЕНИЕ

### После исправления:

```python
# ✅ ИСПРАВЛЕНО: Инициализируем tp_percent = None (НЕ используем fallback сразу!)
tp_percent = None

# Получаем режим из позиции, если не передан
if not regime:
    # ...

# Получаем tp_percent для символа и режима (если есть в symbol_profiles)
if symbol and self.symbol_profiles:
    # ...
    if regime_tp_percent is not None:
        tp_percent = float(regime_tp_percent)  # ✅ Устанавливается из конфига
    # ...
    if symbol_tp_percent is not None:
        tp_percent = float(symbol_tp_percent)  # ✅ Устанавливается из конфига

# 3. ✅ ПРИОРИТЕТ 3: Глобальный TP (fallback - ТОЛЬКО если ничего не найдено)
if tp_percent is None:
    tp_percent = self.scalping_config.tp_percent  # ✅ Fallback ТОЛЬКО если tp_percent = None
    logger.warning(f"⚠️ FALLBACK: Используется глобальный TP...")
```

---

## ✅ РЕЗУЛЬТАТ

### Правильная логика:

1. ✅ **Инициализация:** `tp_percent = None` (НЕ используем fallback сразу)
2. ✅ **Приоритет 1:** Per-regime TP (из конфига)
3. ✅ **Приоритет 2:** Per-symbol TP (из конфига)
4. ✅ **Приоритет 3:** Fallback (ТОЛЬКО если `tp_percent is None`)

---

## ✅ УЛУЧШЕНИЯ

### Добавлено:

1. ✅ **WARNING логирование для fallback:**
   ```python
   logger.warning(
       f"⚠️ FALLBACK: Используется глобальный TP для {symbol} (regime={regime or 'N/A'}): {tp_percent}% "
       f"(per-regime и per-symbol TP не найдены...)"
   )
   ```

2. ✅ **Правильная проверка:**
   - `if tp_percent is None:` перед использованием fallback
   - Fallback используется ТОЛЬКО если ничего не найдено

---

**Статус:** ✅ ИСПРАВЛЕНО, ЛОГИКА ПРАВИЛЬНАЯ

