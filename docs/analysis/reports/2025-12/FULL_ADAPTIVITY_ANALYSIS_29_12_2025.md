# ПОЛНЫЙ АНАЛИЗ АДАПТИВНОСТИ ТОРГОВОГО БОТА (29.12.2025)

**Дата:** 29.12.2025  
**Цель:** Проверить адаптивность всех параметров, индикаторов, фильтров и расчетов по режимам, символам и балансу

---

## 📊 1. ТАБЛИЦА ПАРАМЕТРОВ

| Параметр | По режиму | Per-symbol | По балансу | Статус | Файл/Строки |
|----------|-----------|------------|------------|--------|-------------|
| `min_holding_minutes` | ✅ | ✅ | ❌ | ✅ Полностью | `exit_analyzer.py:1425-1520`, `config_futures.yaml:270,352,413` |
| `sl_atr_multiplier` | ✅ | ❌ | ❌ | ❌ **НЕ per-symbol** | `parameter_provider.py:179-183`, `config_futures.yaml:42,255,334,405` |
| `tp_atr_multiplier` | ✅ | ❌ | ❌ | ❌ **НЕ per-symbol** | `parameter_provider.py:184-186`, `config_futures.yaml:254,324,404` |
| `max_holding_minutes` | ✅ | ❌ | ❌ | ❌ **НЕ per-symbol** | `parameter_provider.py:172-178`, `config_futures.yaml:258,337,408` |
| `min_signal_strength` | ✅ | ✅ | ❌ | ✅ Полностью | `config_futures.yaml:34,41,51,53` |
| `min_adx` | ✅ | ✅ | ❌ | ✅ Полностью | `config_futures.yaml:36,43,50` |
| `rsi_overbought` | ✅ | ❌ | ❌ | ⚠️ Частично | `config_futures.yaml:274,355,423` |
| `rsi_oversold` | ✅ | ❌ | ❌ | ⚠️ Частично | `config_futures.yaml:275,356,424` |
| `smart_close.reversal_score_threshold` | ✅ | ✅ | ❌ | ✅ Полностью | `parameter_provider.py:209-313`, `config_futures.yaml:47-48` |
| `smart_close.trend_against_threshold` | ✅ | ✅ | ❌ | ✅ Полностью | `parameter_provider.py:209-313` |
| `ph_threshold_percent` | ✅ | ❌ | ❌ | ⚠️ Частично | `config_futures.yaml:267,348,418` |
| `ph_threshold_type` | ✅ | ❌ | ❌ | ⚠️ Частично | `config_futures.yaml:266,347,417` |
| `tsl_offset` | ✅ | ❌ | ❌ | ⚠️ Частично | `config_futures.yaml: (trailing_sl)` |
| `position_size_multiplier` | ✅ | ✅ | ✅ | ✅ Полностью | `position_sizer.py:88-96`, `config_futures.yaml:253,323,403` |
| `max_trades_per_hour` | ✅ | ❌ | ❌ | ⚠️ Частично | `config_futures.yaml:252,322,402` |
| `cooldown_after_loss_minutes` | ✅ | ❌ | ❌ | ⚠️ Частично | `config_futures.yaml:262,343,412` |
| `block_counter_trend` | ✅ | ❌ | ❌ | ⚠️ Частично | `config_futures.yaml:249,319,399` |
| `conflict_multiplier` | ✅ | ❌ | ❌ | ⚠️ Частично | `config_futures.yaml:250,320,400` |

**Легенда:**
- ✅ Полностью адаптивно
- ⚠️ Частично адаптивно (только по режиму)
- ❌ Не адаптивно

---

## 📈 2. ТАБЛИЦА ИНДИКАТОРОВ

| Индикатор | Параметры | По режиму | Per-symbol | Статус | Файл/Строки |
|-----------|-----------|-----------|------------|--------|-------------|
| **ATR** | `period`, `fallback`, `multiplier` | ✅ | ❌ | ⚠️ Частично | `talib_wrapper.py`, `atr_provider.py`, `config_futures.yaml:281,362,430` |
| **RSI** | `period`, `overbought`, `oversold` | ✅ | ❌ | ⚠️ Частично | `signal_generator.py:92-94`, `config_futures.yaml:274-275,355-356,423-424` |
| **EMA** | `fast`, `slow` | ✅ | ❌ | ⚠️ Частично | `signal_generator.py:102-103`, `config_futures.yaml:279-280,360-361,428-429` |
| **SMA** | `fast`, `slow` | ✅ | ❌ | ⚠️ Частично | `config_futures.yaml:277-278,358-359,426-427` |
| **MACD** | `fast`, `slow`, `signal`, `strength_divider` | ✅ | ❌ | ⚠️ Частично | `signal_generator.py:97-99`, `config_futures.yaml:284-287,365-368,433-436` |
| **Bollinger Bands** | `period`, `std_multiplier` | ✅ | ❌ | ⚠️ Частично | `signal_generator.py:100-101`, `config_futures.yaml:288-289,369-370,437-438` |
| **ADX** | `period`, `threshold` | ✅ | ❌ | ⚠️ Частично | `regime_manager.py:392-403`, `config_futures.yaml:314,394,462` |
| **Pivot Points** | `level_tolerance_percent`, `score_bonus` | ✅ | ❌ | ⚠️ Частично | `config_futures.yaml:304-307,384-387,452-455` |
| **Volume Profile** | `score_bonus`, `poc_tolerance` | ✅ | ❌ | ⚠️ Частично | `config_futures.yaml:308-312,388-392,456-460` |

**Проблемы:**
1. ❌ Индикаторы НЕ адаптируются per-symbol (ETH может требовать другие параметры)
2. ⚠️ Параметры индикаторов берутся из конфига, но не всегда применяются в коде
3. ⚠️ `signal_generator.py` использует базовые параметры из `__init__`, а не из режима

**Пример проблемы:**
```python
# signal_generator.py:92-94 (ХАРДКОД базовых значений)
rsi_period = 14
rsi_overbought = 70
rsi_oversold = 30

# config_futures.yaml:274-275 (TRENDING режим)
indicators:
  rsi_overbought: 85  # ❌ НЕ ИСПОЛЬЗУЕТСЯ в signal_generator!
  rsi_oversold: 25
```

---

## 🔍 3. ТАБЛИЦА ФИЛЬТРОВ

| Фильтр | Пороги | По режиму | Per-symbol | Статус | Файл/Строки |
|--------|--------|-----------|------------|--------|-------------|
| **FundingRateFilter** | `max_positive_rate`, `max_negative_rate` | ✅ | ✅ | ✅ Полностью | `funding_rate_filter.py`, `config_futures.yaml:498-501` |
| **LiquidityFilter** | `min_best_bid_volume`, `min_orderbook_depth`, `max_spread` | ✅ | ✅ | ✅ Полностью | `liquidity_filter.py:317-380`, `config_futures.yaml:489-493,531-535` |
| **OrderFlowFilter** | `long_threshold`, `short_threshold`, `min_total_depth` | ✅ | ✅ | ✅ Полностью | `order_flow_filter.py`, `config_futures.yaml:494-497,536-539` |
| **VolatilityRegimeFilter** | `min_range_percent`, `max_range_percent`, `min_atr_percent` | ✅ | ✅ | ✅ Полностью | `volatility_regime_filter.py`, `config_futures.yaml:502-505` |
| **MomentumFilter** | `min_momentum`, `max_momentum` | ✅ | ❌ | ⚠️ Частично | `momentum_filter.py` |
| **MultiTimeframeFilter** | `block_opposite`, `score_bonus`, `confirmation_timeframe` | ✅ | ❌ | ⚠️ Частично | `config_futures.yaml:293-299,373-379,441-447` |
| **CorrelationFilter** | `threshold`, `max_correlated_positions` | ✅ | ❌ | ⚠️ Частично | `config_futures.yaml:300-303,380-383,448-451` |
| **PivotPointsFilter** | `level_tolerance_percent`, `score_bonus_near_level` | ✅ | ❌ | ⚠️ Частично | `config_futures.yaml:304-307,384-387,452-455` |
| **VolumeProfileFilter** | `score_bonus_in_value_area`, `poc_tolerance_percent` | ✅ | ❌ | ⚠️ Частично | `config_futures.yaml:308-312,388-392,456-460` |

**Приоритет получения порогов (LiquidityFilter):**
```python
# liquidity_filter.py:317-380
def _get_thresholds(self, symbol: str, regime: Optional[str] = None):
    # 1. Базовые значения (lowest priority)
    base = {...}
    
    # 2. Per-symbol overrides (выше приоритет)
    symbol_override = overrides.get(symbol)
    
    # 3. Regime multipliers (выше приоритет)
    regime_multipliers = {...}
    
    # 4. thresholds_override в evaluate() (highest priority)
    # Из by_regime.{regime}.filters.liquidity
```

---

## 🧠 4. РАСЧЁТЫ РЕЖИМА РЫНКА

### 4.1. Определение режима (detect_regime)

**Файл:** `regime_manager.py:250-326`  
**Метод:** `detect_regime(candles, current_price)`

**Адаптивные параметры:**
- ✅ `trending_adx_threshold`: 15.0 (config_futures.yaml:240)
- ✅ `ranging_adx_threshold`: 18.0 (config_futures.yaml:241)
- ✅ `high_volatility_threshold`: 0.02 (2.0%) (config_futures.yaml:242)
- ✅ `trend_strength_percent`: 1.0% (config_futures.yaml:243)

**Scoring система:**
```python
# regime_manager.py:289-326
choppy_score = 0.0
if volatility > high_volatility_threshold:
    choppy_score += min(0.4, (volatility / 0.1) * 0.4)
if reversals > 5:
    choppy_score += min(0.3, (reversals / 20) * 0.3)
if vol_ratio > 1.1:
    choppy_score += min(0.3, ((vol_ratio - 1.0) / 0.5) * 0.3)

trending_score = 0.0
if abs(trend_deviation) > trend_strength_percent:
    trending_score += min(0.3, (abs(trend_deviation) / 5.0) * 0.3)
if adx_val >= trending_adx_threshold:
    trending_score += min(0.3, (adx_val / 50.0) * 0.3)

ranging_score = 0.0
if range_width < 5.0:
    ranging_score += min(0.4, (5.0 - range_width) / 5.0 * 0.4)
if adx_val < ranging_adx_threshold:
    ranging_score += min(0.3, (1.0 - adx_val / ranging_adx_threshold) * 0.3)
```

**Статус:** ✅ Полностью адаптивно (пороги из конфига)

---

## 📥 5. РАСЧЁТЫ ВХОДА/ВЫХОДА

### 5.1. Генерация сигналов (generate_signals)

**Файл:** `signal_generator.py`  
**Проблема:** ❌ Использует базовые параметры индикаторов вместо режим-специфичных

**Пример:**
```python
# signal_generator.py:92-94 (ХАРДКОД)
rsi_period = 14
rsi_overbought = 70  # ❌ Должно быть 85 для TRENDING!
rsi_oversold = 30   # ❌ Должно быть 25 для TRENDING!

# Пытается получить из конфига (строки 106-150), но не всегда применяется
```

**Статус:** ⚠️ Частично адаптивно (параметры есть в конфиге, но не всегда применяются)

### 5.2. Выход (exit_analyzer.py)

**Файл:** `exit_analyzer.py`  
**Методы:**
- `_generate_exit_for_ranging()` (строка 2800+)
- `_generate_exit_for_trending()` (строка 2200+)
- `_generate_exit_for_choppy()` (строка 3800+)

**Адаптивные параметры:**
- ✅ `min_holding_minutes` — полностью адаптивно (режим + per-symbol)
- ✅ `smart_close` thresholds — полностью адаптивно (режим + per-symbol)
- ⚠️ `sl_atr_multiplier` — по режиму, но НЕ per-symbol
- ⚠️ `tp_atr_multiplier` — по режиму, но НЕ per-symbol
- ⚠️ `max_holding_minutes` — по режиму, но НЕ per-symbol

**Порядок проверок выхода (RANGING):**
```
1. Peak Profit
2. Stop Loss (с min_holding_minutes)
3. Smart Close (с min_holding_minutes)
4. Take Profit
5. Big Profit Exit
6. Partial TP
7. Reversal Detected
8. Max Holding Time
9. Emergency Loss Protection
```

**Статус:** ⚠️ Частично адаптивно (некоторые параметры не per-symbol)

---

## 💰 6. РАСЧЁТЫ РИСКА/ПОЗИЦИИ/PNL

### 6.1. Размер позиции (calculate_position_size)

**Файл:** `position_sizer.py:47-115`  
**Метод:** `calculate_position_size(signal, regime, regime_params, balance_profile, balance)`

**Адаптивность:**
```python
# position_sizer.py:84-105
# 1. Базовый размер (процент от баланса)
risk_per_trade = self._get_risk_per_trade(regime, regime_params)
base_size_usd = balance * risk_per_trade

# 2. Режимный множитель
regime_multiplier = self.regime_calculator.calculate_position_size_multiplier(
    symbol, regime, balance_profile
)
adjusted_size_usd = base_size_usd * regime_multiplier

# 3. Balance profile boost
balance_params = self.balance_calculator.calculate_balance_parameters(
    balance, balance_profile
)
size_boost = balance_params.get("position_size_boost", 1.0)
adjusted_size_usd = adjusted_size_usd * size_boost
```

**Приоритеты:**
1. ✅ Balance Profile (small/medium/large)
2. ✅ Regime Multiplier (trending/ranging/choppy)
3. ✅ Symbol Multiplier (per-symbol)
4. ✅ Margin Calculator (максимальный размер)

**Статус:** ✅ Полностью адаптивно

### 6.2. PnL расчёт (от маржи)

**Файл:** `trailing_stop_loss.py`, `exit_analyzer.py`  
**Метод:** `get_profit_pct(position, current_price)`

**Адаптивность:**
- ✅ PnL рассчитывается от маржи (не от баланса)
- ✅ Profit Harvesting использует `ph_threshold_percent` от маржи
- ✅ Адаптивно по режиму (`ph_threshold_percent` разный для режимов)

**Пример:**
```python
# exit_analyzer.py: (расчет PnL от маржи)
margin = position.get('margin', 0)
unrealized_pnl = (current_price - entry_price) * size * direction
pnl_percent = (unrealized_pnl / margin) * 100 if margin > 0 else 0

# ph_threshold_percent по режиму:
# TRENDING: 2.5% (config_futures.yaml:267)
# RANGING: 1.2% (config_futures.yaml:348)
# CHOPPY: 1.0% (config_futures.yaml:418)
```

**Статус:** ✅ Полностью адаптивно

### 6.3. Маржа/ликвидация

**Файл:** `risk_manager.py`, `margin_monitor.py`  
**Адаптивность:**
- ✅ `max_margin_per_trade` — адаптивно по балансу (balance_profiles)
- ✅ `max_daily_loss_percent` — адаптивно по балансу
- ✅ `volatility_factor` — адаптивно по режиму и волатильности

**Статус:** ✅ Полностью адаптивно

---

## ❌ 7. КРИТИЧЕСКИЕ ПРОБЛЕМЫ

### 7.1. `sl_atr_multiplier` из `by_symbol` НЕ учитывается

**Проблема:**
- В конфиге: `by_symbol.ETH-USDT.sl_atr_multiplier: 3.0`
- Но `get_exit_params()` НЕ проверяет `by_symbol`
- Используется только `exit_params.{regime}.sl_atr_multiplier`

**Код:**
```python
# parameter_provider.py:137-146
exit_params = all_exit_params.get(regime_lower, {})
# ❌ НЕТ ПРОВЕРКИ by_symbol.{symbol}.sl_atr_multiplier
```

**Влияние:**
- ETH-USDT получает `sl_atr_multiplier=2.0` вместо `3.0`
- SL на 50% уже, чем должен быть
- Больше преждевременных закрытий по SL

**Файл:** `parameter_provider.py:105-207`

---

### 7.2. Индикаторы используют базовые параметры вместо режим-специфичных

**Проблема:**
- `signal_generator.py` инициализирует базовые параметры (строки 92-103)
- Пытается получить из конфига (строки 106-150), но не всегда применяется
- Режим-специфичные параметры из `config_futures.yaml` не используются

**Пример:**
```python
# signal_generator.py:92-94
rsi_overbought = 70  # Базовое значение

# config_futures.yaml:274 (TRENDING)
rsi_overbought: 85  # ❌ НЕ ИСПОЛЬЗУЕТСЯ!
```

**Влияние:**
- RSI сигналы генерируются с неправильными порогами
- В TRENDING режиме нужен `rsi_overbought=85`, но используется `70`
- Больше ложных сигналов

**Файл:** `signal_generator.py:92-150`

---

### 7.3. `tp_atr_multiplier` и `max_holding_minutes` НЕ per-symbol

**Проблема:**
- Аналогично `sl_atr_multiplier`, эти параметры не проверяют `by_symbol`
- ETH может требовать другие значения, но получает общие

**Влияние:**
- ETH-USDT не может иметь индивидуальные TP/SL параметры
- Все пары используют одинаковые множители

**Файл:** `parameter_provider.py:105-207`

---

### 7.4. Индикаторы не адаптируются per-symbol

**Проблема:**
- Все индикаторы используют одинаковые параметры для всех пар
- ETH может требовать другие периоды/пороги, но получает стандартные

**Влияние:**
- ETH (высокая волатильность) использует те же параметры, что и BTC
- Меньше точности сигналов для волатильных пар

**Файл:** `signal_generator.py`, `indicator_manager.py`

---

## 🎯 8. РЕКОМЕНДАЦИИ

### 8.1. Добавить проверку `by_symbol` в `get_exit_params()`

**Файл:** `src/strategies/scalping/futures/config/parameter_provider.py`  
**Метод:** `get_exit_params()` (строки 105-207)

**Патч:**
```python
# После строки 199, перед return exit_params or {}
# Добавить проверку by_symbol
if symbol and hasattr(self.config_manager, "_raw_config_dict"):
    config_dict = self.config_manager._raw_config_dict
    by_symbol = config_dict.get("by_symbol", {})
    symbol_config = by_symbol.get(symbol, {})
    if isinstance(symbol_config, dict):
        # Переопределяем параметры из by_symbol (приоритет выше)
        if "sl_atr_multiplier" in symbol_config:
            exit_params["sl_atr_multiplier"] = _to_float(
                symbol_config["sl_atr_multiplier"], "sl_atr_multiplier",
                exit_params.get("sl_atr_multiplier", 2.0)
            )
        if "tp_atr_multiplier" in symbol_config:
            exit_params["tp_atr_multiplier"] = _to_float(
                symbol_config["tp_atr_multiplier"], "tp_atr_multiplier",
                exit_params.get("tp_atr_multiplier", 1.0)
            )
        if "max_holding_minutes" in symbol_config:
            exit_params["max_holding_minutes"] = _to_float(
                symbol_config["max_holding_minutes"], "max_holding_minutes",
                exit_params.get("max_holding_minutes", 25.0)
            )
        logger.debug(
            f"✅ ParameterProvider: Exit параметры для {symbol} получены из by_symbol: "
            f"sl_atr={exit_params.get('sl_atr_multiplier')}, "
            f"tp_atr={exit_params.get('tp_atr_multiplier')}, "
            f"max_holding={exit_params.get('max_holding_minutes')}"
        )
```

---

### 8.2. Использовать режим-специфичные параметры индикаторов

**Файл:** `src/strategies/scalping/futures/signal_generator.py`  
**Метод:** `_generate_base_signals()` или аналогичный

**Патч:**
```python
# Вместо использования базовых параметров из __init__
# Получать параметры индикаторов из ParameterProvider по режиму

async def _generate_base_signals(self, symbol: str, market_data: MarketData):
    # Получаем режим
    regime = self._get_current_regime(symbol)
    
    # Получаем параметры индикаторов для режима
    indicator_params = self.parameter_provider.get_indicator_params(symbol, regime)
    
    # Используем режим-специфичные параметры
    rsi_overbought = indicator_params.get("rsi_overbought", 70)
    rsi_oversold = indicator_params.get("rsi_oversold", 30)
    rsi_period = indicator_params.get("rsi_period", 14)
    
    macd_fast = indicator_params.get("macd_fast", 12)
    macd_slow = indicator_params.get("macd_slow", 26)
    macd_signal = indicator_params.get("macd_signal", 9)
    
    # ... остальной код с использованием этих параметров
```

---

### 8.3. Добавить per-symbol параметры индикаторов

**Конфиг:** `config_futures.yaml`  
**Структура:**
```yaml
by_symbol:
  ETH-USDT:
    indicators:
      rsi_overbought: 80  # Для ETH более строгий порог
      rsi_oversold: 20
      macd_fast: 10  # Более быстрый MACD для ETH
      macd_slow: 22
      bb_std_multiplier: 2.1  # Шире полосы для волатильности
```

**Код:** `parameter_provider.py:get_indicator_params()`  
**Патч:**
```python
def get_indicator_params(self, symbol: str, regime: Optional[str] = None):
    # ... существующий код ...
    
    # Добавить проверку by_symbol.{symbol}.indicators
    if symbol and hasattr(self.config_manager, "_raw_config_dict"):
        config_dict = self.config_manager._raw_config_dict
        by_symbol = config_dict.get("by_symbol", {})
        symbol_config = by_symbol.get(symbol, {})
        if isinstance(symbol_config, dict):
            symbol_indicators = symbol_config.get("indicators", {})
            if isinstance(symbol_indicators, dict):
                # Переопределяем параметры из by_symbol (приоритет выше)
                indicators.update(symbol_indicators)
                logger.debug(
                    f"✅ ParameterProvider: Индикаторы для {symbol} получены из by_symbol"
                )
    
    return indicators
```

---

### 8.4. Улучшить логирование адаптивных параметров

**Рекомендация:** Добавить логирование, когда используется per-symbol или режим-специфичный параметр

**Пример:**
```python
logger.debug(
    f"✅ ExitAnalyzer: SL параметры для {symbol} ({regime}) "
    f"получены через ParameterProvider: sl_percent={sl_percent:.2f}%, "
    f"sl_atr_multiplier={sl_atr_multiplier:.2f} (источник: {'by_symbol' if from_by_symbol else 'exit_params'})"
)
```

---

## 📋 ИТОГОВАЯ ТАБЛИЦА АДАПТИВНОСТИ

| Компонент | По режиму | Per-symbol | По балансу | Общий статус |
|-----------|-----------|------------|------------|--------------|
| **Параметры выхода** | ✅ | ⚠️ Частично | ❌ | ⚠️ 60% |
| **Индикаторы** | ⚠️ Частично | ❌ | ❌ | ⚠️ 30% |
| **Фильтры** | ✅ | ✅ | ❌ | ✅ 90% |
| **Режим рынка** | ✅ | ❌ | ❌ | ✅ 100% |
| **Размер позиции** | ✅ | ✅ | ✅ | ✅ 100% |
| **PnL расчёт** | ✅ | ❌ | ❌ | ✅ 100% |
| **Риск/Маржа** | ✅ | ❌ | ✅ | ✅ 90% |

**Общая оценка адаптивности:** ⚠️ **70%** (хорошо, но есть критические пробелы)

---

## 🚨 ПРИОРИТЕТЫ ИСПРАВЛЕНИЙ

### Срочно (критично для ETH и других пар):
1. ✅ Добавить проверку `by_symbol` в `get_exit_params()` для `sl_atr_multiplier`, `tp_atr_multiplier`, `max_holding_minutes`
2. ✅ Использовать режим-специфичные параметры индикаторов в `signal_generator.py`

### Важно (улучшит точность):
3. ✅ Добавить per-symbol параметры индикаторов
4. ✅ Улучшить логирование адаптивных параметров

### Желательно (оптимизация):
5. ✅ Добавить адаптивность по балансу для большего количества параметров
6. ✅ Кэширование адаптивных параметров для производительности

---

**Дата создания:** 29.12.2025  
**Статус:** ⚠️ Частично адаптивно — нужны критические исправления для полной адаптивности



