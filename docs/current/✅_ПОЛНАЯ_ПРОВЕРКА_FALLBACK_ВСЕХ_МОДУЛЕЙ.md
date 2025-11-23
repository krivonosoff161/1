# ПОЛНАЯ ПРОВЕРКА FALLBACK ВО ВСЕХ МОДУЛЯХ

**Дата:** 23 ноября 2025  
**Цель:** Убедиться, что везде fallback используется ТОЛЬКО при отсутствии конфига

---

## ✅ ПРОВЕРЕННЫЕ МОДУЛИ

### 1. `order_executor.py` ✅ ИСПРАВЛЕНО

**Проблема:** Нет проблем, логика правильная
**Исправление:** Улучшено логирование (WARNING для fallback)

**Логика:**
- ✅ `offset_percent = None` (не используем fallback сразу)
- ✅ Проверяем per-symbol+regime из конфига
- ✅ Проверяем per-regime из конфига
- ✅ Fallback ТОЛЬКО если `offset_percent is None`

---

### 2. `position_manager.py` ✅ ИСПРАВЛЕНО

**Проблема:** Fallback устанавливался ДО проверки конфига
**Исправление:** Изменена логика приоритетов

**До исправления:**
```python
tp_percent = self.scalping_config.tp_percent  # ❌ ПРОБЛЕМА: ДО проверки конфига!
# ... проверка конфига ...
```

**После исправления:**
```python
tp_percent = None  # ✅ ИСПРАВЛЕНО: НЕ используем fallback сразу
# ... проверка конфига ...
if tp_percent is None:
    tp_percent = self.scalping_config.tp_percent  # ✅ Fallback ТОЛЬКО если ничего не найдено
```

**Логика:**
- ✅ `tp_percent = None` (не используем fallback сразу)
- ✅ Проверяем per-regime TP из конфига
- ✅ Проверяем per-symbol TP из конфига
- ✅ Fallback ТОЛЬКО если `tp_percent is None`

---

### 3. `risk_manager.py` ⚠️ НУЖНО ПРОВЕРИТЬ

**Потенциальная проблема:** Использование `.get()` с fallback значениями

**Примеры:**
```python
strength_multiplier = strength_multipliers.get("conflict", 0.5)  # ⚠️ Fallback 0.5
strength_multiplier = strength_multipliers.get("very_strong", 1.5)  # ⚠️ Fallback 1.5
base_atr_percent = volatility_config.get("base_atr_percent", 0.02)  # ⚠️ Fallback 0.02
```

**Анализ:**
- ✅ Эти fallback значения используются ТОЛЬКО если значение не найдено в конфиге
- ✅ Это правильная логика `.get(key, default)`
- ⚠️ НО нужно проверить, что эти значения действительно есть в конфиге

---

## ✅ ВЫВОДЫ

### Исправлено:

1. ✅ **`order_executor.py`:** Логика правильная, улучшено логирование
2. ✅ **`position_manager.py`:** Исправлена логика приоритетов

### Нужно проверить:

1. ⚠️ **`risk_manager.py`:** Проверить, что все fallback значения есть в конфиге
2. ⚠️ **Другие модули:** Проверить аналогичные проблемы

---

## ✅ РЕКОМЕНДАЦИИ

### Для всех модулей:

1. ✅ **Использовать `None` для инициализации:**
   ```python
   value = None  # НЕ использовать fallback сразу
   ```

2. ✅ **Проверять конфиг сначала:**
   ```python
   if config_value is not None:
       value = config_value
   ```

3. ✅ **Fallback ТОЛЬКО если ничего не найдено:**
   ```python
   if value is None:
       value = fallback_value
       logger.warning(f"⚠️ FALLBACK: Используется fallback значение...")
   ```

---

**Статус:** ✅ ОСНОВНЫЕ ПРОБЛЕМЫ ИСПРАВЛЕНЫ, НУЖНО ПРОВЕРИТЬ ДРУГИЕ МОДУЛИ

