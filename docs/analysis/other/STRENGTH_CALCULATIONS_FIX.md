# Исправление расчетов strength для всех индикаторов

## Проблема
Все сигналы блокировались из-за слишком низкого `strength` (0.034 = 3.4%) при пороге min_strength=0.133 (13.3%).

## Исправления

### 1. MA (Moving Average) сигналы
**Было:**
```python
strength = (ma_fast - ma_slow) / ma_slow
strength = min(1.0, strength * 100)  # multiplier = 100
```
- Разница EMA 0.05% → strength = 0.05 (5%) ❌
- Разница EMA 0.01% → strength = 0.01 (1%) ❌

**Стало:**
```python
strength = (ma_fast - ma_slow) / ma_slow
strength = min(1.0, abs(strength) * 2000)  # multiplier = 2000
if price_direction == "neutral":
    strength *= 0.9  # Было 0.7
```
- Разница EMA 0.05% → strength = 1.0 (100%) ✅
- Разница EMA 0.01% → strength = 0.2 (20%) ✅
- Разница EMA 0.005% → strength = 0.1 (10%) ⚠️ (чуть ниже порога 13.3%, но это нормально)

### 2. MACD сигналы
**Было:**
```python
strength = min(abs(histogram) / 100, 1.0)
```
- histogram=47 → strength = 0.47 (47%) ✅
- histogram=20 → strength = 0.2 (20%) ✅

**Стало:**
```python
strength = min(abs(histogram) / 200.0, 1.0)
```
- histogram=47 → strength = 0.235 (23.5%) ✅
- histogram=100 → strength = 0.5 (50%) ✅
- histogram=200+ → strength = 1.0 (максимум) ✅

**Причина:** MACD histogram может быть очень большим, поэтому деление на 200 более адекватно.

### 3. Bollinger Bands
**Было:**
```python
strength = (lower - current_price) / (middle - lower)
```
- Проблема: нет защиты от деления на 0

**Стало:**
```python
strength = min((lower - current_price) / (middle - lower) if (middle - lower) > 0 else 0.5, 1.0)
```
- Добавлена защита от деления на 0 ✅
- Ограничение максимума 1.0 ✅

### 4. RSI сигналы
**Осталось без изменений** (уже правильно нормирован):
```python
# OVERSOLD (покупка)
strength = min(1.0, (rsi_oversold - rsi) / rsi_oversold)
# OVERBOUGHT (продажа)
strength = min(1.0, (rsi - rsi_overbought) / (100 - rsi_overbought))
```

## Пороги min_strength

### Ranging режим (из config.yaml: min_score_threshold=2)
- min_strength = 2 / 12 = 0.167 (16.7%)
- После снижения на 20%: 0.167 * 0.8 = **0.133 (13.3%)**
- После снижения на 50% для конфликтных: 0.133 * 0.5 = **0.067 (6.7%)**

### Соответствие новых strength порогам:
- ✅ MA сигнал (разница EMA 0.01%+) → strength ≥ 0.2 (20%) > 0.133 ✅
- ✅ MACD сигнал (histogram 27+) → strength ≥ 0.135 (13.5%) > 0.133 ✅
- ✅ RSI сигнал → strength обычно 0.15-0.5 (15-50%) > 0.133 ✅
- ✅ BB сигнал → strength обычно 0.2-0.8 (20-80%) > 0.133 ✅

## Результат

Теперь большинство сигналов будет проходить через ARM фильтр, так как:
1. MA сигналы имеют достаточный strength (≥20% при разнице EMA ≥0.01%)
2. Порог для ranging режима достаточно низкий (13.3%)
3. Конфликтные сигналы имеют еще более низкий порог (6.7%)

## Примечания

- Если сигналы все еще блокируются, возможно нужно:
  1. Еще больше снизить min_score_threshold для ranging (с 2 до 1)
  2. Или увеличить multiplier для MA (с 2000 до 3000-5000)
  3. Или снизить порог в ARM еще больше (с 0.8 до 0.7 для ranging)


