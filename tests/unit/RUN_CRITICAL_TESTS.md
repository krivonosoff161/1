# 🧪 Запуск критических тестов

## ✅ Созданные тесты (20 тестов, все проходят!)

### 1. IndicatorManager ATR (3 теста) - НОВОЕ!
```bash
pytest tests/unit/test_indicator_manager_atr.py -v
```
**Проверяет:**
- ✅ ATR рассчитывается правильно через IndicatorManager (не 0.0)
- ✅ TALibATR вызывается с правильными параметрами (highs, lows, closes)
- ✅ TALibATR определяется правильно по имени класса

### 2. ATR Provider (8 тестов)
```bash
pytest tests/unit/test_atr_provider.py -v
```
**Проверяет:**
- ✅ ATR возвращает None если не найден (БЕЗ FALLBACK)
- ✅ ATR возвращает None если равен 0.0 (БЕЗ FALLBACK)
- ✅ ATR правильно кэшируется
- ✅ ATR=0.0 НЕ сохраняется в DataRegistry

### 3. Regime + DataRegistry (4 теста)
```bash
pytest tests/unit/test_regime_dataregistry.py -v
```
**Проверяет:**
- ✅ `update_regime()` сохраняет режим в DataRegistry
- ✅ `detect_regime()` НЕ сохраняет (только определяет)
- ✅ Режим сохраняется для каждого символа отдельно

### 4. Leverage Timeout (3 теста)
```bash
pytest tests/unit/test_leverage_timeout.py -v
```
**Проверяет:**
- ✅ Обработка timeout (50004) с retry (5 попыток)
- ✅ Обработка rate limit (429)
- ✅ Превышение максимального количества попыток

### 5. Signal Generator Indicators (2 теста)
```bash
pytest tests/unit/test_signal_generator_indicators.py -v
```
**Проверяет:**
- ✅ Индикаторы сохраняются в `market_data.indicators`
- ✅ Индикаторы доступны после расчета

## 🚀 Запуск всех критических тестов

```bash
# Все критические тесты одной командой
pytest tests/unit/test_indicator_manager_atr.py tests/unit/test_atr_provider.py tests/unit/test_regime_dataregistry.py tests/unit/test_leverage_timeout.py tests/unit/test_signal_generator_indicators.py -v

# С кратким выводом ошибок
pytest tests/unit/test_indicator_manager_atr.py tests/unit/test_atr_provider.py tests/unit/test_regime_dataregistry.py tests/unit/test_leverage_timeout.py tests/unit/test_signal_generator_indicators.py -v --tb=short
```

## 📊 Результаты

**Всего тестов:** 20  
**Проходят:** 20 ✅  
**Покрытие:** IndicatorManager ATR, ATR Provider, Regime, Leverage timeout, Indicators

## ⚠️ Проблемы БЕЗ тестов (нужно добавить):

- ❌ Проблема #2: Position Size (нужны тесты для risk_manager и signal_coordinator)
- ❌ Проблема #3: Exit Analyzer Timeout (нужны тесты для exit_analyzer)
- ❌ Проблема #4: Marker Orders (нужны тесты для delta check)
- ❌ Проблема #5: Timezone Error (нужны тесты для execute_signal_from_price)

**См. `TEST_COVERAGE_SUMMARY.md` для полной сводки покрытия тестами.**

## 🎯 Что это дает?

Теперь вместо запуска всего бота можно:
1. Запустить тесты: `pytest tests/unit/test_atr_provider.py -v`
2. Увидеть что падает
3. Исправить проблему
4. Запустить тесты снова
5. Убедиться что все работает

**Быстро, надежно, без запуска всего бота!**
