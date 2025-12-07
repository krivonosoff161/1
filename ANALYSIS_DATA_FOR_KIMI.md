# 📋 ДАННЫЕ ДЛЯ АНАЛИЗА KIMI - ЭТАП 1

**Дата:** 2025-12-07  
**Запрос:** Данные для первого раунда анализа

---

## 1. ✅ Значение `max_holding_minutes` из конфига

**Файл:** `config/config_futures.yaml`

**Значения по режимам:**
- **trending:** `30 минут` (строка 224)
- **ranging:** `20 минут` (строка 285)  
- **choppy:** `10 минут` (строка 345)

**Контекст:**
```yaml
# Строка 224 (trending)
max_holding_minutes: 30  # ✅ КАЧЕСТВЕННАЯ ТОРГОВЛЯ: Увеличено с 18 до 30 минут (+67%)

# Строка 285 (ranging)
max_holding_minutes: 20  # ✅ КАЧЕСТВЕННАЯ ТОРГОВЛЯ: Увеличено с 13 до 20 минут (+54%)

# Строка 345 (choppy)
max_holding_minutes: 10  # ✅ КАЧЕСТВЕННАЯ ТОРГОВЛЯ: Увеличено с 6 до 10 минут (+67%)
```

**Подозрение подтверждено:** Все 5 сделок закрыты по `max_holding_exceeded`, что может указывать на слишком короткие таймауты или проблему с логикой выхода.

---

## 2. ✅ Код из `orchestrator.py` (формирование сигналов и проверка выхода)

### 2.1. Основной торговый цикл (строки 1991-2067)

```python
async def _main_trading_loop(self):
    """Основной торговый цикл"""
    logger.info("🔄 Запуск основного торгового цикла")

    while self.is_running:
        try:
            # Проверяем is_running перед каждым шагом
            if not self.is_running:
                break

            # Обновление состояния
            await self._update_state()
            
            if not self.is_running:
                break

            # Генерация сигналов
            signals = await self.signal_generator.generate_signals()
            if len(signals) > 0:
                logger.info(
                    f"📊 Основной цикл: сгенерировано {len(signals)} сигналов"
                )

            if not self.is_running:
                break

            # Обработка сигналов
            await self.signal_coordinator.process_signals(signals)

            if not self.is_running:
                break

            # Управление позициями
            await self._manage_positions()

            # ... другие проверки ...

            # Пауза между итерациями
            await asyncio.sleep(self.scalping_config.check_interval)
            
        except Exception as e:
            logger.error(f"❌ Ошибка в торговом цикле: {e}")
```

### 2.2. Генерация сигналов в `signal_generator.py` (строки 1871-2120)

```python
async def _generate_rsi_signals(
    self,
    symbol: str,
    indicators: Dict,
    market_data: MarketData,
    adx_trend: str,
    adx_value: float,
    adx_threshold: float,
) -> List[Dict[str, Any]]:
    """Генерация сигналов на основе RSI"""
    signals = []
    
    rsi = indicators.get("rsi", 50)
    rsi_oversold = 30  # Адаптивный порог
    rsi_overbought = 70  # Адаптивный порог
    
    # Получаем EMA для проверки тренда
    ema_fast = indicators.get("ema_12", 0)
    ema_slow = indicators.get("ema_26", 0)
    current_price = (
        market_data.ohlcv_data[-1].close if market_data.ohlcv_data else 0.0
    )
    
    # Перепроданность (покупка) - используем адаптивный порог
    if rsi < rsi_oversold:
        # Проверяем тренд через EMA - если конфликт, снижаем confidence
        is_downtrend = ema_fast < ema_slow and current_price < ema_fast
        
        # Получаем текущий режим для проверки блокировки
        current_regime = "ranging"  # Fallback
        try:
            if hasattr(self, "regime_manager") and self.regime_manager:
                regime_obj = self.regime_manager.get_current_regime()
                if regime_obj:
                    current_regime = (
                        regime_obj.lower()
                        if isinstance(regime_obj, str)
                        else str(regime_obj).lower()
                    )
        except Exception as e:
            logger.debug(f"⚠️ Не удалось получить режим для блокировки: {e}")
        
        # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: В trending режиме - полная блокировка противотрендовых сигналов
        should_block = current_regime == "trending" and is_downtrend
        if should_block:
            logger.debug(
                f"🚫 RSI OVERSOLD сигнал ПОЛНОСТЬЮ ЗАБЛОКИРОВАН для {symbol}: "
                f"trending режим + EMA bearish (конфликт с трендом)"
            )
        else:
            # Нормализованная сила: от 0 до 1
            strength = min(1.0, (rsi_oversold - rsi) / rsi_oversold)
            
            # При конфликте снижаем strength адаптивно под режим
            if is_downtrend:
                strength *= conflict_multiplier  # Снижаем силу
                has_conflict = True
            else:
                has_conflict = False
            
            # Проверяем ADX тренд ПРИ генерации сигнала
            if adx_trend == "bearish" and adx_value >= adx_threshold:
                logger.debug(
                    f"🚫 RSI OVERSOLD сигнал ОТМЕНЕН для {symbol}: "
                    f"ADX показывает нисходящий тренд"
                )
            else:
                # Генерируем сигнал
                signals.append({
                    "symbol": symbol,
                    "side": "buy",
                    "price": current_price,
                    "strength": strength,
                    "regime": current_regime,
                    # ... другие поля
                })
    
    # Аналогично для перекупленности (продажа)
    if rsi > rsi_overbought:
        # ... аналогичная логика для SHORT сигналов ...
    
    return signals
```

### 2.3. Проверка `max_holding_exceeded` в `exit_analyzer.py` (строки 1266-1320)

```python
# 8. ✅ НОВОЕ: Проверка Max Holding - учитываем время в позиции как фактор анализа
minutes_in_position = self._get_time_in_position_minutes(metadata, position)
max_holding_minutes = self._get_max_holding_minutes("trending")

if (
    minutes_in_position is not None
    and minutes_in_position >= max_holding_minutes
):
    # Время превышено - проверяем, есть ли сильные сигналы держать
    trend_data = await self._analyze_trend_strength(symbol)
    trend_strength = (
        trend_data.get("trend_strength", 0) if trend_data else 0
    )

    # Если сильный тренд (>= 0.7) и прибыль > 0.3% - продлеваем
    if trend_strength >= 0.7 and pnl_percent > 0.3:
        logger.info(
            f"⏰ ExitAnalyzer TRENDING: Время {minutes_in_position:.1f} мин >= {max_holding_minutes:.1f} мин, "
            f"но сильный тренд (strength={trend_strength:.2f}) и прибыль {pnl_percent:.2f}% - продлеваем"
        )
        return {
            "action": "extend_tp",
            "reason": "max_holding_strong_trend",
            "pnl_pct": pnl_percent,
            "trend_strength": trend_strength,
            "minutes_in_position": minutes_in_position,
        }
    else:
        # ✅ ИСПРАВЛЕНО: Не закрываем убыточные позиции по max_holding
        # Позволяем им дойти до SL или восстановиться
        if pnl_percent < 0:
            logger.info(
                f"⏰ ExitAnalyzer TRENDING: Время превышено, но позиция убыточная ({pnl_percent:.2f}%) - не закрываем"
            )
            return None  # Не закрываем убыточные
        
        # Закрываем только прибыльные позиции
        return {
            "action": "close",
            "reason": "max_holding_exceeded",
            "pnl_pct": pnl_percent,
            "minutes_in_position": minutes_in_position,
        }
```

**Примечание:** Код показывает, что убыточные позиции НЕ должны закрываться по `max_holding_exceeded` в режиме `trending` (строки 1296-1307), но все 5 сделок закрыты по этой причине. Возможно, проблема в режимах `ranging` или `choppy`, или в другой части кода (например, в `position_manager.py`).

---

## 3. ✅ Первые 5 строк `signals.csv` и соответствующие строки `market_data.csv`

### 3.1. Первые 5 строк `signals.csv`:

| timestamp | symbol | side | price | strength | regime | filters_passed | executed |
|-----------|--------|------|-------|----------|--------|----------------|----------|
| 2025-12-07T10:51:08.856568 | SOL-USDT | buy | 132.44000000 | 1.0000 | ranging | ADX,MTF,Correlation,PivotPoints,VolumeProfile,Liquidity,OrderFlow,FundingRate | 0 |
| 2025-12-07T10:51:08.857568 | ETH-USDT | buy | 3041.49000000 | 0.9000 | ranging | ADX,MTF,Correlation,PivotPoints,VolumeProfile,Liquidity,OrderFlow,FundingRate | 0 |
| 2025-12-07T10:51:08.857568 | DOGE-USDT | buy | 0.13920000 | 0.9000 | ranging | ADX,MTF,Correlation,PivotPoints,VolumeProfile,Liquidity,OrderFlow,FundingRate | 0 |
| 2025-12-07T10:51:11.621440 | SOL-USDT | buy | 132.44000000 | 1.0000 | ranging | ADX,MTF,Correlation,PivotPoints,VolumeProfile,Liquidity,OrderFlow,FundingRate | 0 |
| 2025-12-07T10:51:11.621440 | ETH-USDT | buy | 3041.50000000 | 0.9000 | ranging | ADX,MTF,Correlation,PivotPoints,VolumeProfile,Liquidity,OrderFlow,FundingRate | 0 |

**Наблюдение:** Все сигналы имеют `executed=0`, что означает, что они не были исполнены.

### 3.2. Соответствующие строки `market_data.csv`:

**Для timestamp `2025-12-07T10:51:00` (ближайшая свеча к сигналам):**

| timestamp | symbol | open | high | low | close | volume | quote_currency |
|-----------|--------|------|------|-----|-------|--------|-----------------|
| 2025-12-07T10:51:00+00:00 | SOL-USDT | 132.41 | 132.44 | 132.3 | 132.32 | - | USDT |
| 2025-12-07T10:51:00+00:00 | ETH-USDT | 3041.0 | 3041.92 | 3039.46 | 3040.24 | - | USDT |
| 2025-12-07T10:51:00+00:00 | DOGE-USDT | 0.13918 | 0.13922 | 0.13907 | 0.13907 | - | USDT |

**Сравнение:**
- **SOL-USDT:** Сигнал цена = 132.44, свеча close = 132.32, high = 132.44 ✅ Совпадает с high
- **ETH-USDT:** Сигнал цена = 3041.49, свеча close = 3040.24, high = 3041.92 ✅ В диапазоне high-low
- **DOGE-USDT:** Сигнал цена = 0.13920, свеча close = 0.13907, high = 0.13922 ✅ В диапазоне high-low

**Примечание:** Сигналы генерируются в 10:51:08, а свеча закрывается в 10:51:00. Это может указывать на использование текущей цены (tick data), а не закрытой свечи, что нормально для скальпинга.

---

## 4. ✅ Содержимое `performance_report_2025-12-07.yaml`

```yaml
metrics:
  sharpe_ratio: null
  sortino_ratio: null
  calmar_ratio: null
  cagr: null
  max_drawdown: null
  max_drawdown_duration: null
  win_rate: 0.0
  profit_factor: 0
  avg_trade: -0.0212
  avg_winning_trade: 0
  avg_losing_trade: -0.0212
  avg_bars_in_trade: null
  total_trades: 5
  winning_trades: 0
  losing_trades: 5
  total_pnl: -0.106
  total_commission: 0.1881
  net_pnl: -0.106
  max_consecutive_wins: 0
  max_consecutive_losses: 5
  largest_win: -0.0047
  largest_loss: -0.051
  avg_holding_time_minutes: 30.05
period:
  start: '2025-12-07'
  end: '2025-12-07'
  days: 1
benchmark:
  name: null
  return: null
  sharpe: null
additional:
  max_consecutive_wins: 0
  max_consecutive_losses: 5
  largest_win: -0.0047
  largest_loss: -0.051
  avg_holding_time_minutes: 30.05
```

**Наблюдения:**
- `sharpe_ratio`, `max_drawdown` и другие метрики = `null` (требуют маркет-данных для расчета)
- `win_rate = 0.0%` — все сделки убыточные
- `avg_holding_time_minutes = 30.05` — среднее время удержания близко к `max_holding_minutes` для trending (30 мин)
- `profit_factor = 0` — нет прибыльных сделок

---

## 📊 ВЫВОДЫ

1. **`max_holding_minutes`:** 30/20/10 минут по режимам — возможно, слишком короткие для скальпинга
2. **Код выхода:** Логика не должна закрывать убыточные позиции по `max_holding`, но все 5 сделок закрыты по этой причине
3. **Сигналы vs цены:** Нужна проверка соответствия timestamp сигналов и свечей
4. **Performance Report:** Базовые метрики есть, но Sharpe/Drawdown требуют расчета на основе маркет-данных

---

**Готово для передачи аналитику (Kimi)**

