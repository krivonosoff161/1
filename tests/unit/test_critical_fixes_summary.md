# Тесты для критических исправлений

## ✅ Созданные тесты

### 1. `test_atr_provider.py` - Проблема #6 (ATR не рассчитывается)
- ✅ `test_get_atr_returns_none_when_not_found` - ATR возвращает None если не найден (БЕЗ FALLBACK)
- ✅ `test_get_atr_returns_none_when_zero` - ATR возвращает None если равен 0.0 (БЕЗ FALLBACK)
- ✅ `test_get_atr_returns_value_when_valid` - ATR возвращает валидное значение
- ✅ `test_atr_zero_not_saved` - ATR=0.0 НЕ сохраняется в DataRegistry

**Результат:** 8/8 тестов проходят ✅

### 2. `test_regime_dataregistry.py` - Проблема #7 (Режим не сохраняется)
- ✅ `test_update_regime_saves_to_dataregistry` - update_regime() сохраняет режим в DataRegistry
- ✅ `test_detect_regime_does_not_save` - detect_regime() НЕ сохраняет (только определяет)
- ✅ `test_regime_persists_after_update` - Режим сохраняется после update_regime()
- ✅ `test_regime_saved_for_each_symbol` - Режим сохраняется для каждого символа отдельно

**Результат:** 4/4 теста проходят ✅

### 3. `test_leverage_timeout.py` - Проблема #9 (Leverage timeout)
- ✅ `test_set_leverage_handles_timeout_50004` - Обработка timeout (50004) с retry
- ✅ `test_set_leverage_handles_rate_limit_429` - Обработка rate limit (429)
- ✅ `test_set_leverage_max_retries_exceeded` - Превышение максимального количества попыток

**Результат:** 3/3 теста проходят ✅

## 📊 Итого
- **Всего тестов:** 15
- **Проходят:** 15 ✅
- **Покрытие:** ATR, Regime, Leverage timeout

## 🚀 Запуск тестов

```bash
# Все критические тесты
pytest tests/unit/test_atr_provider.py tests/unit/test_regime_dataregistry.py tests/unit/test_leverage_timeout.py -v

# Только ATR
pytest tests/unit/test_atr_provider.py -v

# Только Regime
pytest tests/unit/test_regime_dataregistry.py -v

# Только Leverage
pytest tests/unit/test_leverage_timeout.py -v
```

## 📝 Следующие шаги
1. Добавить тесты для position size calculation (проблема #2)
2. Добавить тесты для exit analyzer timeout (проблема #3)
3. Добавить тесты для индикаторов в market_data.indicators (проблема #8)
