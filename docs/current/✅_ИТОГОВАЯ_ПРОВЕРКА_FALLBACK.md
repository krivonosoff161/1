# ИТОГОВАЯ ПРОВЕРКА FALLBACK ЛОГИКИ

**Дата:** 23 ноября 2025  
**Цель:** Убедиться, что везде fallback используется ТОЛЬКО при отсутствии конфига

---

## ✅ ПРОВЕРКА `order_executor.py`

### Логика правильная:

1. ✅ **Инициализация:** `offset_percent = None` (НЕ используем fallback сразу)
2. ✅ **Приоритет 1:** Per-symbol + Per-regime (из конфига)
3. ✅ **Приоритет 2:** Per-regime (из конфига)
4. ✅ **Приоритет 3:** Fallback (ТОЛЬКО если `offset_percent is None`)

**Улучшения:**
- ✅ Добавлено WARNING логирование для fallback
- ✅ Добавлено DEBUG логирование для per-symbol fallback

---

## ✅ ПРОВЕРКА ДРУГИХ МОДУЛЕЙ

### Нужно проверить:

1. ⚠️ **PositionManager:** `_get_adaptive_tp_percent`
2. ⚠️ **RiskManager:** `calculate_position_size`
3. ⚠️ **TrailingSLCoordinator:** `initialize_trailing_stop`
4. ⚠️ **SignalGenerator:** Фильтры и индикаторы

---

## ✅ ВЫВОДЫ

### Логика в `order_executor.py` правильная:

1. ✅ **Сначала читаем из конфига:**
   - Per-symbol + Per-regime
   - Per-symbol
   - Per-regime

2. ✅ **Fallback используется ТОЛЬКО если ничего не найдено:**
   - Проверка `offset_percent is None`
   - Fallback на `default_offset` (из конфига или `0.0`)

3. ✅ **Нет параллельного использования:**
   - Логика последовательная
   - Fallback используется только если конфиг не найден

---

## ✅ РЕКОМЕНДАЦИИ

### Для других модулей:

1. ✅ **Проверить логику приоритетов:**
   - Сначала конфиг
   - Потом fallback

2. ✅ **Добавить логирование:**
   - WARNING для fallback
   - DEBUG для отслеживания источника значений

3. ✅ **Использовать `None` для инициализации:**
   - Не использовать fallback сразу
   - Проверять `is None` перед fallback

---

**Статус:** ✅ ЛОГИКА В `order_executor.py` ПРАВИЛЬНАЯ, НУЖНО ПРОВЕРИТЬ ДРУГИЕ МОДУЛИ

