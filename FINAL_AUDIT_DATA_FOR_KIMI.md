# 📋 ФИНАЛЬНЫЙ АУДИТ - ВСЕ ДАННЫЕ ДЛЯ KIMI

**Дата:** 2025-12-07  
**Запрос:** Полный набор данных для финального аудита фильтров, сигналов и режимов

---

## ✅ ИСПРАВЛЕНИЕ БАГА

### Исправлен метод `_check_max_holding` в `position_manager.py`

**Изменения:**
- ✅ Добавлена проверка `if pnl_percent_from_margin < 0: return False` перед закрытием
- ✅ Убыточные позиции больше НЕ закрываются по таймауту
- ✅ Закрываются только прибыльные позиции после превышения `max_holding_minutes`

**Код исправления (строки 4950-4978):**
```python
if margin_used > 0:
    pnl_percent_from_margin = (net_pnl / margin_used) * 100
    
    # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Не закрываем убыточные позиции по max_holding
    if pnl_percent_from_margin < 0:
        logger.info(
            f"⏰ [MAX_HOLDING] {symbol}: Время {minutes_in_position:.1f} мин >= {actual_max_holding:.1f} мин, "
            f"но позиция в убытке ({pnl_percent_from_margin:.2f}%) - НЕ закрываем, ждем SL или восстановления"
        )
        return False  # Не закрываем убыточную позицию
    
    # ... логирование ...
    
    # ✅ Закрываем только прибыльные позиции
    await self._close_position_by_reason(position, "max_holding_exceeded")
    return True
```

**Проверка вызова `exit_analyzer`:**
- ✅ `exit_analyzer.analyze_position()` вызывается в `manage_position()` на строке 506
- ✅ Вызывается ДО всех других проверок (ПРИОРИТЕТ #0)
- ✅ Если `exit_analyzer` возвращает решение о закрытии, позиция закрывается и дальнейшие проверки не выполняются

---

## 1. ✅ ФИЛЬТРЫ И БЛОКИРОВКИ СИГНАЛОВ

### 1.1. Код блокировки сигналов в `signal_generator.py`

**Строки 1969-1976 (блокировка противотрендовых сигналов в trending режиме):**
```python
# ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: В trending режиме - полная блокировка противотрендовых сигналов
should_block = current_regime == "trending" and is_downtrend
if should_block:
    logger.debug(
        f"🚫 RSI OVERSOLD сигнал ПОЛНОСТЬЮ ЗАБЛОКИРОВАН для {symbol}: "
        f"trending режим + EMA bearish (конфликт с трендом)"
    )
else:
    # Генерируем сигнал
    signals.append(...)
```

**Строки 2090-2096 (блокировка для SHORT сигналов):**
```python
# ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: В trending режиме - полная блокировка противотрендовых сигналов
should_block = current_regime == "trending" and is_uptrend
if should_block:
    logger.debug(
        f"🚫 RSI OVERBOUGHT сигнал ПОЛНОСТЬЮ ЗАБЛОКИРОВАН для {symbol}: "
        f"trending режим + EMA bullish (конфликт с трендом)"
    )
else:
    # Генерируем сигнал
    signals.append(...)
```

**Строки 2049-2056 (блокировка по ADX тренду):**
```python
# ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Проверяем ADX тренд ПРИ генерации сигнала
if adx_trend == "bearish" and adx_value >= adx_threshold:
    # Сильный нисходящий тренд - не генерируем BUY сигнал
    logger.debug(
        f"🚫 RSI OVERSOLD сигнал ОТМЕНЕН для {symbol}: "
        f"ADX показывает нисходящий тренд (ADX={adx_value:.1f}, -DI доминирует)"
    )
else:
    signals.append(...)  # Генерируем сигнал
```

### 1.2. Логирование `filters_passed` в `signal_generator.py`

**Строки 1327-1344 (запись в CSV):**
```python
# ✅ НОВОЕ: Логирование сигналов в CSV
if self.performance_tracker:
    for signal in filtered_signals:
        try:
            filters_passed = signal.get("filters_passed", [])
            if isinstance(filters_passed, str):
                filters_passed = (
                    filters_passed.split(",") if filters_passed else []
                )
            elif not isinstance(filters_passed, list):
                filters_passed = []

            self.performance_tracker.record_signal(
                symbol=signal.get("symbol", ""),
                side=signal.get("side", ""),
                price=signal.get("price", 0.0),
                strength=signal.get("strength", 0.0),
                regime=signal.get("regime"),
                filters_passed=filters_passed,
                executed=False,  # Будет обновлено при исполнении
                order_id=None,  # Будет обновлено при исполнении
            )
```

**Фильтры, которые проверяются (порядок применения в `_apply_filters`, строки 3523-4030):**
1. **ADX** (строки 3730-3767) - проверка тренда через ADX, блокирует сигналы против тренда
2. **Correlation** (строки 3769-3807) - корреляция между позициями
3. **MTF** (строки 3809-3855) - Multi-Timeframe фильтр
4. **PivotPoints** (строки 3857-3883) - точки разворота
5. **VolumeProfile** (строки 3885-3920) - профиль объема
6. **Liquidity** (строки 3922-3960) - проверка ликвидности
7. **OrderFlow** (строки 3962-3995) - поток ордеров
8. **FundingRate** (строки 3997-4023) - ставка финансирования

**Код применения фильтров (строки 3750-3757):**
```python
# ADX фильтр блокирует сигналы против тренда
if not adx_result.allowed:
    logger.warning(
        f"🚫 ADX заблокировал {signal_side_str.upper()} сигнал для {symbol}: "
        f"сигнал против тренда (ADX={adx_result.adx_value:.1f})"
    )
    continue  # Блокируем сигнал
```

**Важно:** Если сигнал проходит все фильтры, он добавляется в `filters_passed` список и логируется в CSV. Если хотя бы один фильтр блокирует сигнал, он не попадает в финальный список.

---

## 2. ✅ СИГНАЛЫ VS РЫНОЧНЫЙ ТРЕНД

### 2.1. Первые 50 строк `signals.csv`

**Файл:** `logs/futures/archived/logs_2025-12-07_16-03-39_extracted/signals_2025-12-07.csv`

**Наблюдения:**
- Все сигналы в режиме `ranging` (боковой рынок)
- Все сигналы `buy` (LONG)
- Все сигналы имеют `executed=0` (не исполнены)
- Все сигналы прошли все фильтры: `ADX,MTF,Correlation,PivotPoints,VolumeProfile,Liquidity,OrderFlow,FundingRate`
- Strength варьируется от 0.7612 до 1.0000

**Примеры сигналов:**
| timestamp | symbol | side | price | strength | regime | filters_passed | executed |
|-----------|--------|------|-------|----------|--------|----------------|----------|
| 2025-12-07T10:51:08.856568 | SOL-USDT | buy | 132.44000000 | 1.0000 | ranging | ADX,MTF,Correlation,PivotPoints,VolumeProfile,Liquidity,OrderFlow,FundingRate | 0 |
| 2025-12-07T10:51:08.857568 | ETH-USDT | buy | 3041.49000000 | 0.9000 | ranging | ADX,MTF,Correlation,PivotPoints,VolumeProfile,Liquidity,OrderFlow,FundingRate | 0 |
| 2025-12-07T10:51:08.857568 | DOGE-USDT | buy | 0.13920000 | 0.9000 | ranging | ADX,MTF,Correlation,PivotPoints,VolumeProfile,Liquidity,OrderFlow,FundingRate | 0 |

**Проблема:** Все сигналы не исполнены (`executed=0`), что может указывать на:
- Слишком строгие фильтры на этапе исполнения
- Проблемы с ликвидностью при размещении ордеров
- Блокировка сигналов по другим причинам (cooldown, max_positions, etc.)

---

## 3. ✅ РЕЖИМ РЫНКА VS НАПРАВЛЕНИЕ СДЕЛОК

### 3.1. Определение режима в `regime_manager.py`

**Метод `_classify_regime` (строки 384-500):**

```python
def _classify_regime(
    self, indicators: Dict[str, float]
) -> tuple[RegimeType, float, str]:
    """
    Классифицирует режим рынка на основе индикаторов.
    
    Returns:
        (regime_type, confidence, reason)
    """
    vol = indicators["volatility_percent"]
    trend_dev = indicators["trend_deviation"]
    adx = indicators["adx_proxy"]
    range_width = indicators["range_width"]
    reversals = indicators["reversals"]
    volume_ratio = indicators.get("volume_ratio", 1.0)
    
    # CHOPPY: Высокая волатильность + много разворотов + высокий объем
    has_choppy_volume = volume_ratio > 1.5
    
    if (
        vol > self.config.high_volatility_threshold
        and reversals > 10
        and has_choppy_volume
    ):
        return RegimeType.CHOPPY, confidence, reason
    
    # TRENDING: Сильный тренд + направленное движение + подтверждение объемом
    trend_direction = indicators.get("trend_direction", "neutral")
    di_plus = indicators.get("di_plus", 0)
    di_minus = indicators.get("di_minus", 0)
    
    # Проверяем что есть направленность (+DI > -DI для bullish или -DI > +DI для bearish)
    if adx >= self.config.trending_adx_threshold:
        if di_plus > di_minus:
            # Bullish trend
            return RegimeType.TRENDING, confidence, reason
        elif di_minus > di_plus:
            # Bearish trend
            return RegimeType.TRENDING, confidence, reason
    
    # RANGING: Боковой рынок (по умолчанию)
    if adx < self.config.ranging_adx_threshold:
        return RegimeType.RANGING, confidence, reason
    
    # Fallback на RANGING
    return RegimeType.RANGING, 0.5, "Default to ranging"
```

**Параметры детекции (из конфига):**
- `trending_adx_threshold: 25.0` - ADX >25 = тренд
- `ranging_adx_threshold: 20.0` - ADX <20 = боковик
- `high_volatility_threshold: 0.05` - >5% = высокая волатильность
- `low_volatility_threshold: 0.02` - <2% = низкая волатильность
- `trend_strength_percent: 2.0` - Цена >2% от SMA = тренд
- `min_regime_duration_minutes: 15` - Минимум 15 мин в одном режиме
- `required_confirmations: 3` - Нужно 3 подтверждения для переключения

**Логика определения режима (строки 399-500):**
1. **CHOPPY:** Высокая волатильность (>5%) + много разворотов (>10) + высокий объем (>1.5x)
2. **TRENDING:** ADX >= 25 + направленность (+DI > -DI для bullish или -DI > +DI для bearish)
3. **RANGING:** ADX < 20 или по умолчанию

**Полный код классификации (строки 384-500):**
```python
def _classify_regime(self, indicators: Dict[str, float]) -> tuple[RegimeType, float, str]:
    vol = indicators["volatility_percent"]
    trend_dev = indicators["trend_deviation"]
    adx = indicators["adx_proxy"]
    range_width = indicators["range_width"]
    reversals = indicators["reversals"]
    volume_ratio = indicators.get("volume_ratio", 1.0)
    has_choppy_volume = volume_ratio > 1.5
    
    # CHOPPY: Высокая волатильность + много разворотов + высокий объем
    if (vol > self.config.high_volatility_threshold and reversals > 10 and has_choppy_volume):
        confidence = min(1.0, (vol / 0.1) * 0.4 + (reversals / 20) * 0.3 + (0.3 if has_choppy_volume else 0))
        reason = f"High volatility ({vol:.2%}) + {reversals} reversals + high volume ({volume_ratio:.2f}x) → Chaotic market"
        return RegimeType.CHOPPY, confidence, reason
    
    # TRENDING: Сильный тренд + направленное движение + подтверждение объемом
    trend_direction = indicators.get("trend_direction", "neutral")
    di_plus = indicators.get("di_plus", 0)
    di_minus = indicators.get("di_minus", 0)
    
    if adx >= self.config.trending_adx_threshold:
        if di_plus > di_minus:
            # Bullish trend
            confidence = min(1.0, (adx / 50.0) * 0.5 + (di_plus / di_minus if di_minus > 0 else 1.0) * 0.3 + (0.2 if volume_ratio > 1.0 else 0))
            reason = f"ADX={adx:.1f} (trending) + +DI > -DI ({di_plus:.1f} > {di_minus:.1f}) → Bullish trend"
            return RegimeType.TRENDING, confidence, reason
        elif di_minus > di_plus:
            # Bearish trend
            confidence = min(1.0, (adx / 50.0) * 0.5 + (di_minus / di_plus if di_plus > 0 else 1.0) * 0.3 + (0.2 if volume_ratio > 1.0 else 0))
            reason = f"ADX={adx:.1f} (trending) + -DI > +DI ({di_minus:.1f} > {di_plus:.1f}) → Bearish trend"
            return RegimeType.TRENDING, confidence, reason
    
    # RANGING: Боковой рынок (ADX < ranging_threshold)
    if adx < self.config.ranging_adx_threshold:
        confidence = min(1.0, 1.0 - (adx / self.config.ranging_adx_threshold))
        reason = f"ADX={adx:.1f} < {self.config.ranging_adx_threshold} (ranging threshold) → Sideways market"
        return RegimeType.RANGING, confidence, reason
    
    # Fallback на RANGING
    return RegimeType.RANGING, 0.5, "Default to ranging"
```

### 3.2. Соответствие сигналов режиму

**Наблюдение из `signals.csv`:**
- Все сигналы в режиме `ranging` (боковой рынок)
- Все сигналы `buy` (LONG)
- В режиме `ranging` нет блокировки противотрендовых сигналов (блокировка только в `trending`)

**Проблема:** Если рынок действительно в `ranging`, то LONG сигналы могут быть убыточными, если:
- Рынок находится в нижней части диапазона и продолжает падать
- Нет четкого направления, и сигналы генерируются слишком часто
- Фильтры недостаточно строгие для `ranging` режима

---

## 4. ✅ PERFORMANCE REPORT (после исправления)

**Примечание:** После исправления `_check_max_holding` нужно перезапустить бота и собрать новые данные. Текущий `performance_report_2025-12-07.yaml` основан на данных ДО исправления.

**Текущие метрики (ДО исправления):**
- `win_rate: 0.0%` - все сделки убыточные
- `total_trades: 5` - все закрыты по `max_holding_exceeded`
- `avg_holding_time_minutes: 30.05` - среднее время удержания близко к `max_holding_minutes` для trending (30 мин)
- `total_pnl: -0.106` - общий убыток
- `max_consecutive_losses: 5` - 5 убытков подряд

**Ожидаемые изменения (ПОСЛЕ исправления):**
- Убыточные позиции больше не будут закрываться по таймауту
- `avg_holding_time_minutes` может увеличиться (убыточные позиции будут держаться дольше)
- `win_rate` может улучшиться, если убыточные позиции восстановятся до прибыли
- `total_pnl` может улучшиться, если убыточные позиции закроются по TP или восстановятся

**Требуется:** Перезапустить бота, собрать новые данные и обновить `performance_report.yaml`

---

## 📊 ИТОГОВЫЕ ВЫВОДЫ

### ✅ Исправления применены:
1. ✅ `_check_max_holding` теперь проверяет PnL перед закрытием
2. ✅ Убыточные позиции больше не закрываются по таймауту
3. ✅ `exit_analyzer` вызывается до всех других проверок

### ⚠️ Потенциальные проблемы:
1. **Все сигналы не исполнены** - возможно, слишком строгие фильтры на этапе исполнения
2. **Все сигналы в режиме `ranging`** - возможно, режим определяется неправильно или рынок действительно боковой
3. **Все сигналы LONG** - возможно, нет SHORT сигналов из-за блокировки или фильтров

### 🔧 Рекомендации для дальнейшего анализа:
1. Проверить, почему все сигналы имеют `executed=0`
2. Сверить направление сигналов с направлением рыночного тренда из `market_data.csv`
3. Проверить, правильно ли определяется режим рынка (может быть, рынок в `trending`, но определяется как `ranging`)

---

**Готово для передачи аналитику (Kimi)**

