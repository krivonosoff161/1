# 📋 Полный список изменений для исправления проблем (29.11.2025)

## 🔍 Анализ связанных участков кода

### ✅ Проверенные файлы и методы:

1. **`src/strategies/scalping/futures/position_manager.py`**
   - `_update_peak_profit` (строка 3547) - вызывается из `manage_position` (строка 485)
   - `_check_profit_harvesting` (строка 1229) - вызывается из `manage_position` (строка 476) и `trailing_sl_coordinator` (строка 1096)
   - `_check_profit_drawdown` (строка 3663) - вызывается из `manage_position` (строка 489) и `_update_peak_profit` (строка 3640)
   - `manage_position` (строка 408) - вызывается из `orchestrator._manage_positions` (строка 2158) и `websocket_coordinator` (строка 277)

2. **`src/strategies/scalping/futures/core/position_registry.py`**
   - `PositionMetadata.peak_profit_usd` (строка 33) - инициализируется как `0.0`
   - Используется в `_update_peak_profit` и `_check_profit_drawdown`

3. **`config/config_futures.yaml`**
   - `adaptive_regime.ranging.ph_time_limit` (строка 284) - текущее значение: 300с
   - `adaptive_regime.trending.ph_time_limit` (строка 226) - текущее значение: 180с
   - `adaptive_regime.choppy.ph_time_limit` (строка 341) - текущее значение: 60с

4. **`src/strategies/scalping/futures/signal_generator.py`**
   - Фильтры для сигналов (ADX, Correlation, MultiTimeframe, VolumeProfile)
   - Нет специфичных фильтров для XRP-USDT

---

## 📝 Список изменений

### 1. **ИСПРАВИТЬ ОБНОВЛЕНИЕ PEAK_PROFIT** (КРИТИЧНО)

**Файл:** `src/strategies/scalping/futures/position_manager.py`  
**Метод:** `_update_peak_profit`  
**Строка:** ~3608-3610

**Текущая логика:**
```python
if metadata:
    if net_pnl > metadata.peak_profit_usd:
        metadata.peak_profit_usd = net_pnl
```

**Проблема:** 
- Для убыточных позиций (net_pnl < 0) это условие никогда не выполнится, так как `peak_profit_usd` инициализируется как `0.0`
- Profit Drawdown не может сработать без `peak_profit`

**Исправление:**
```python
if metadata:
    # ✅ ИСПРАВЛЕНИЕ: Обновляем peak_profit при первом обновлении или если PnL улучшился
    # Для прибыльных: обновляем если больше предыдущего
    # Для убыточных: обновляем если меньше (ближе к 0) - отслеживаем минимальный убыток
    if metadata.peak_profit_usd == 0.0 and metadata.peak_profit_time is None:
        # Первое обновление - устанавливаем текущий PnL (даже если отрицательный)
        metadata.peak_profit_usd = net_pnl
        metadata.peak_profit_time = datetime.now(timezone.utc)
        metadata.peak_profit_price = current_price
        
        logger.debug(
            f"🔍 [UPDATE_PEAK_PROFIT] {symbol}: Первое обновление peak_profit | "
            f"установлен=${net_pnl:.4f}"
        )
    elif net_pnl > metadata.peak_profit_usd:
        # PnL улучшился (для прибыльных: больше, для убыточных: ближе к 0)
        metadata.peak_profit_usd = net_pnl
        metadata.peak_profit_time = datetime.now(timezone.utc)
        metadata.peak_profit_price = current_price
        
        logger.debug(
            f"🔍 [UPDATE_PEAK_PROFIT] {symbol}: Обновлен peak_profit | "
            f"новый=${net_pnl:.4f}, был=${metadata.peak_profit_usd:.4f}"
        )
    else:
        logger.debug(
            f"🔍 [UPDATE_PEAK_PROFIT] {symbol}: PnL не улучшился | "
            f"текущий=${net_pnl:.4f}, peak=${metadata.peak_profit_usd:.4f}"
        )
        # Не обновляем, но продолжаем выполнение для сохранения в registry
        return  # Выходим, так как не нужно сохранять в registry
```

**⚠️ ВАЖНО:** После этого изменения нужно обновить логику сохранения в `position_registry` - сохранять только при реальном обновлении.

---

### 2. **УБРАТЬ PH_TIME_LIMIT ДЛЯ ЭКСТРЕМАЛЬНЫХ ПРИБЫЛЕЙ** (КРИТИЧНО)

**Файл:** `src/strategies/scalping/futures/position_manager.py`  
**Метод:** `_check_profit_harvesting`  
**Строка:** ~1554-1595

**Текущая логика:**
- Уже есть проверка `ignore_min_holding` для экстремальных прибылей (>= 1.5x порога)
- Но `ph_time_limit` все еще проверяется даже для экстремальных прибылей

**Исправление:**
```python
# ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Если экстремальная прибыль (>= 2x порога),
# игнорируем не только min_holding, но и ph_time_limit
should_close = False
close_reason = ""

if ignore_min_holding:
    # ✅ ИСПРАВЛЕНО: Для экстремальных прибылей (>= 2x порога) игнорируем ph_time_limit
    extreme_profit_2x = ph_threshold * 2.0
    if net_pnl_usd >= extreme_profit_2x:
        # Экстремальная прибыль >= 2x: игнорируем ph_time_limit
        if net_pnl_usd >= ph_threshold:
            should_close = True
            close_reason = "EXTREME PROFIT 2x+ (ignoring time_limit and min_holding)"
            logger.debug(
                f"✅ PH для {symbol}: Условие экстремальной прибыли 2x+ выполнено "
                f"(profit=${net_pnl_usd:.4f} >= 2x threshold=${extreme_profit_2x:.2f})"
            )
    elif net_pnl_usd >= ph_threshold:
        # Экстремальная прибыль >= 1.5x но < 2x: игнорируем min_holding, но проверяем ph_time_limit
        if time_since_open < ph_time_limit:
            should_close = True
            close_reason = "EXTREME PROFIT 1.5x+ (ignoring min_holding, within time_limit)"
            logger.debug(
                f"✅ PH для {symbol}: Условие экстремальной прибыли 1.5x+ выполнено "
                f"(profit=${net_pnl_usd:.4f} >= 1.5x threshold=${extreme_profit_threshold:.2f}, "
                f"time={time_since_open:.1f}с < {ph_time_limit}с)"
            )
        else:
            logger.debug(
                f"❌ PH для {symbol}: Экстремальная прибыль 1.5x+, но превышен time_limit "
                f"({time_since_open:.1f}с >= {ph_time_limit}с)"
            )
    else:
        logger.debug(
            f"❌ PH для {symbol}: Экстремальная прибыль, но недостаточно для закрытия "
            f"(profit=${net_pnl_usd:.4f} < threshold=${ph_threshold:.2f})"
        )
else:
    # Обычная прибыль: проверяем ph_time_limit
    if net_pnl_usd >= ph_threshold and time_since_open < ph_time_limit:
        should_close = True
        close_reason = "NORMAL PROFIT (within time_limit)"
        logger.debug(
            f"✅ PH для {symbol}: Условие обычной прибыли выполнено "
            f"(profit=${net_pnl_usd:.4f} >= ${ph_threshold:.2f}, "
            f"time={time_since_open:.1f}с < {ph_time_limit}с)"
        )
    else:
        if net_pnl_usd < ph_threshold:
            logger.debug(
                f"❌ PH для {symbol}: Прибыль недостаточна "
                f"(${net_pnl_usd:.4f} < ${ph_threshold:.2f})"
            )
        if time_since_open >= ph_time_limit:
            logger.debug(
                f"❌ PH для {symbol}: Превышен time_limit "
                f"({time_since_open:.1f}с >= {ph_time_limit}с)"
            )
```

---

### 3. **СДЕЛАТЬ PH_TIME_LIMIT АДАПТИВНЫМ** (ВАЖНО)

**Файл:** `src/strategies/scalping/futures/position_manager.py`  
**Метод:** `_check_profit_harvesting`  
**Строка:** ~1316-1324

**Текущая логика:**
- `ph_time_limit` читается из конфига статически
- Нет адаптации под волатильность

**Исправление:**
```python
# ✅ НОВОЕ: Адаптивный ph_time_limit на основе волатильности
# Если волатильность высокая, увеличиваем time_limit
base_ph_time_limit = ph_time_limit  # Базовое значение из конфига
try:
    # Получаем ATR для расчета волатильности
    if hasattr(self, "orchestrator") and self.orchestrator:
        if hasattr(self.orchestrator, "signal_generator"):
            indicator_manager = getattr(
                self.orchestrator.signal_generator, "indicator_manager", None
            )
            if indicator_manager:
                # Получаем ATR
                atr_indicator = indicator_manager.get_indicator("ATR")
                if atr_indicator and hasattr(atr_indicator, "value"):
                    atr_value = atr_indicator.value
                    if atr_value and atr_value > 0:
                        # Рассчитываем волатильность как ATR% от цены
                        volatility_pct = (atr_value / current_price) * 100
                        
                        # Адаптируем time_limit: высокая волатильность = больше времени
                        if volatility_pct > 2.0:  # Высокая волатильность (>2%)
                            volatility_multiplier = 1.5  # +50% времени
                        elif volatility_pct > 1.0:  # Средняя волатильность (1-2%)
                            volatility_multiplier = 1.2  # +20% времени
                        else:  # Низкая волатильность (<1%)
                            volatility_multiplier = 1.0  # Базовое время
                        
                        ph_time_limit = int(base_ph_time_limit * volatility_multiplier)
                        logger.debug(
                            f"📊 Адаптивный ph_time_limit для {symbol}: "
                            f"volatility={volatility_pct:.2f}%, "
                            f"multiplier={volatility_multiplier:.2f}x, "
                            f"time_limit={ph_time_limit}с (базовый={base_ph_time_limit}с)"
                        )
except Exception as e:
    logger.debug(
        f"⚠️ Не удалось рассчитать адаптивный ph_time_limit для {symbol}: {e}, "
        f"используем базовое значение {base_ph_time_limit}с"
    )
    ph_time_limit = base_ph_time_limit
```

**Альтернатива (проще):** Просто увеличить `ph_time_limit` в конфиге для ranging режима с 300с до 1200с (20 минут).

---

### 4. **УВЕЛИЧИТЬ PH_TIME_LIMIT В КОНФИГЕ** (ВАЖНО)

**Файл:** `config/config_futures.yaml`  
**Секция:** `adaptive_regime.ranging.ph_time_limit`  
**Строка:** 284

**Текущее значение:** 300с (5 минут)  
**Рекомендуемое значение:** 1200с (20 минут)

**Исправление:**
```yaml
ranging:
  ph_time_limit: 1200  # ✅ УВЕЛИЧЕНО: 20 минут (было 300 = 5 минут)
  # Средняя длительность позиций: 14.3 мин, медиана: 20.0 мин
```

**Также для trending:**
```yaml
trending:
  ph_time_limit: 600  # ✅ УВЕЛИЧЕНО: 10 минут (было 180 = 3 минуты)
```

---

### 5. **УЛУЧШИТЬ PROFIT DRAWDOWN** (ВАЖНО)

**Файл:** `src/strategies/scalping/futures/position_manager.py`  
**Метод:** `_check_profit_drawdown`  
**Строка:** ~3740-3745

**Текущая логика:**
- Проверяет `metadata.peak_profit_usd <= 0` и возвращает `False`
- После исправления `_update_peak_profit`, `peak_profit_usd` будет обновляться даже для убыточных позиций

**Исправление:**
```python
# ✅ ИСПРАВЛЕНО: Проверяем peak_profit даже для убыточных позиций
# После исправления _update_peak_profit, peak_profit_usd может быть отрицательным
if not metadata:
    logger.debug(
        f"🔍 [PROFIT_DRAWDOWN] {symbol}: Нет metadata"
    )
    return False

# ✅ ИСПРАВЛЕНО: Проверяем не только > 0, но и наличие peak_profit_time
# peak_profit_usd может быть отрицательным для убыточных позиций
if metadata.peak_profit_time is None:
    logger.debug(
        f"🔍 [PROFIT_DRAWDOWN] {symbol}: Нет peak_profit_time "
        f"(peak_profit=${metadata.peak_profit_usd:.4f})"
    )
    return False  # Нет максимума (позиция еще не обновлялась)

# ✅ НОВОЕ: Для убыточных позиций проверяем откат от минимального убытка
# Если убыток увеличился (стал больше по модулю), закрываем
if metadata.peak_profit_usd < 0:
    # Убыточная позиция: проверяем откат от минимального убытка
    # Если текущий убыток больше (по модулю) чем peak_profit_usd, значит убыток увеличился
    if net_pnl < metadata.peak_profit_usd:
        # Убыток увеличился - закрываем
        logger.warning(
            f"📉 Profit Drawdown для убыточной позиции {symbol}: "
            f"убыток увеличился с ${metadata.peak_profit_usd:.4f} до ${net_pnl:.4f}"
        )
        return True
    else:
        logger.debug(
            f"🔍 [PROFIT_DRAWDOWN] {symbol}: Убыточная позиция, убыток не увеличился "
            f"(текущий=${net_pnl:.4f}, peak=${metadata.peak_profit_usd:.4f})"
        )
        return False

# Прибыльная позиция: проверяем откат от максимума (существующая логика)
# ... (остальная логика без изменений)
```

---

### 6. **УЛУЧШИТЬ ОТКРЫТИЕ ПОЗИЦИЙ (XRP-USDT SHORT)** (ВАЖНО)

**Проблема:** XRP-USDT SHORT показывает огромные убытки (-53.38 USDT из -59.74 USDT)

**Варианты решения:**

#### Вариант A: Добавить фильтр для XRP SHORT

**Файл:** `src/strategies/scalping/futures/signal_generator.py`  
**Метод:** `_generate_base_signals` или `generate_signal`

**Исправление:**
```python
# ✅ НОВОЕ: Фильтр для XRP-USDT SHORT
if symbol == "XRP-USDT" and signal.get("side") == "sell":
    # Проверяем ADX тренд - блокируем SHORT если тренд BULLISH
    adx_data = self.adx_filter.check_trend_strength(
        symbol, OrderSide.BUY, market_data.ohlcv_data
    )
    if adx_data.direction == "bullish" and adx_data.adx_value >= self.adx_filter.config.adx_threshold:
        logger.warning(
            f"🚫 XRP-USDT SHORT заблокирован: сильный BULLISH тренд "
            f"(ADX={adx_data.adx_value:.1f}, +DI={adx_data.plus_di:.1f}, -DI={adx_data.minus_di:.1f})"
        )
        return None  # Блокируем сигнал
```

#### Вариант B: Увеличить порог для XRP SHORT

**Файл:** `config/config_futures.yaml`  
**Секция:** `adaptive_regime.ranging` или добавить `by_symbol`

**Исправление:**
```yaml
adaptive_regime:
  ranging:
    by_symbol:
      XRP-USDT:
        min_score_threshold: 2.0  # ✅ УВЕЛИЧЕНО: Более строгий порог для XRP (было 1.6)
        ph_threshold: 0.20  # ✅ УВЕЛИЧЕНО: Больший порог для XRP (было 0.15)
```

#### Вариант C: Временно блокировать XRP SHORT

**Файл:** `src/strategies/scalping/futures/signal_generator.py`  
**Метод:** `generate_signal`

**Исправление:**
```python
# ✅ ВРЕМЕННО: Блокируем XRP-USDT SHORT после анализа убытков
if symbol == "XRP-USDT" and signal.get("side") == "sell":
    logger.warning(
        f"🚫 XRP-USDT SHORT временно заблокирован после анализа убытков"
    )
    return None
```

**Рекомендация:** Начать с Варианта A (фильтр по ADX), так как это наиболее безопасно и не блокирует все SHORT сигналы.

---

## ✅ Проверка зависимостей

### Методы, которые вызывают изменяемые функции:

1. **`manage_position`** → вызывает:
   - `_check_profit_harvesting` ✅
   - `_update_peak_profit` ✅
   - `_check_profit_drawdown` ✅

2. **`_update_peak_profit`** → вызывает:
   - `_check_profit_drawdown` ✅ (уже есть проверка)

3. **`trailing_sl_coordinator`** → вызывает:
   - `_check_profit_harvesting` ✅ (не влияет на изменения)

4. **`websocket_coordinator`** → вызывает:
   - `manage_position` ✅ (не влияет на изменения)

### Конфигурационные файлы:

1. **`config/config_futures.yaml`**
   - `adaptive_regime.ranging.ph_time_limit` ✅
   - `adaptive_regime.trending.ph_time_limit` ✅
   - `adaptive_regime.choppy.ph_time_limit` ✅ (опционально)

### Структуры данных:

1. **`PositionMetadata`**
   - `peak_profit_usd` ✅ (может быть отрицательным после исправления)
   - `peak_profit_time` ✅ (используется для проверки первого обновления)

---

## ⚠️ Риски и предосторожности

### 1. **Отрицательный peak_profit_usd**
- **Риск:** После исправления `_update_peak_profit`, `peak_profit_usd` может быть отрицательным
- **Решение:** Обновить логику `_check_profit_drawdown` для работы с отрицательными значениями

### 2. **Адаптивный ph_time_limit**
- **Риск:** Может увеличить время удержания позиций
- **Решение:** Использовать консервативные множители (1.0-1.5x)

### 3. **Фильтр XRP SHORT**
- **Риск:** Может заблокировать прибыльные SHORT сигналы
- **Решение:** Использовать ADX фильтр (уже есть в коде), а не полную блокировку

---

## 📊 Ожидаемые результаты

1. **Profit Drawdown:** Должен срабатывать чаще (сейчас только 3 раза из 45)
2. **Profit Harvesting:** Должен срабатывать чаще (сейчас только 16 раз из 120+ проверок)
3. **XRP-USDT SHORT:** Должен показывать меньше убытков после добавления фильтра
4. **Общий PnL:** Должен улучшиться после всех исправлений

---

## ✅ Итоговый чеклист

- [ ] Исправить `_update_peak_profit` для убыточных позиций
- [ ] Убрать `ph_time_limit` для экстремальных прибылей (>= 2x threshold)
- [ ] Добавить адаптивный `ph_time_limit` на основе волатильности (опционально)
- [ ] Увеличить `ph_time_limit` в конфиге для ranging режима
- [ ] Обновить `_check_profit_drawdown` для работы с отрицательными `peak_profit_usd`
- [ ] Добавить фильтр для XRP-USDT SHORT (ADX фильтр)
- [ ] Протестировать все изменения на тестовых данных

---

## 🎯 Приоритет изменений

1. **КРИТИЧНО:** Исправить `_update_peak_profit` (блокирует Profit Drawdown)
2. **КРИТИЧНО:** Убрать `ph_time_limit` для экстремальных прибылей (>= 2x threshold)
3. **ВАЖНО:** Увеличить `ph_time_limit` в конфиге
4. **ВАЖНО:** Обновить `_check_profit_drawdown` для отрицательных `peak_profit_usd`
5. **ВАЖНО:** Добавить фильтр для XRP-USDT SHORT
6. **ОПЦИОНАЛЬНО:** Адаптивный `ph_time_limit` на основе волатильности

