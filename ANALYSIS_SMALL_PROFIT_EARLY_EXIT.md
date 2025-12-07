# 🔍 АНАЛИЗ: Маленькая прибыль при быстром закрытии

**Дата:** 2025-12-07  
**Проблема:** Позиции закрываются с маленькой прибылью (0.21%) раньше, чем достигается TP (2.4%)

---

## 1️⃣ ПАРАМЕТРЫ ВЫХОДА ИЗ CONFIG

### Базовые параметры (config_futures.yaml):

```yaml
# Take Profit и Stop Loss
tp_percent: 2.4  # ✅ TP = 2.4%
sl_percent: 1.2  # ✅ SL = 1.2%

# Partial TP (частичное закрытие)
partial_tp:
  enabled: true
  fraction: 0.6  # 60% позиции
  trigger_percent: 0.4  # ✅ Срабатывает при 0.4% прибыли!
  by_regime:
    trending:
      fraction: 0.5
      trigger_percent: 0.4  # ✅ Срабатывает при 0.4% прибыли
    ranging:
      fraction: 0.6
      trigger_percent: 0.3  # ✅ Срабатывает при 0.3% прибыли!
    choppy:
      fraction: 0.7
      trigger_percent: 0.2  # ✅ Срабатывает при 0.2% прибыли!

# Profit Drawdown Protection
profit_drawdown:
  enabled: true
  drawdown_percent: 0.20  # 20% откат от пика прибыли
  min_profit_to_activate_usd: 0.5  # Минимальная прибыль $0.5 для активации
  by_regime:
    trending:
      multiplier: 2.0  # 40% откат (0.20 * 2.0)
    ranging:
      multiplier: 1.5  # 30% откат (0.20 * 1.5)
    choppy:
      multiplier: 1.0  # 20% откат (0.20 * 1.0)

# Profit Harvesting (быстрый выход при большой прибыли)
big_profit_exit_percent_majors: 1.5  # BTC/ETH: выход при 1.5%
big_profit_exit_percent_alts: 2.0    # SOL/DOGE/XRP: выход при 2.0%
```

### Адаптивные параметры по режимам:

**Trending:**
- `tp_percent: 2.5-5.0%` (зависит от символа)
- `min_profit_for_extension: 0.5%` (продление времени при прибыли >= 0.5%)

**Ranging:**
- `tp_percent: 2.0-3.5%` (зависит от символа)
- `min_profit_for_extension: 0.5%` (продление времени при прибыли >= 0.5%)

**Choppy:**
- `tp_percent: 1.5-4.0%` (зависит от символа)
- `min_profit_for_extension: 0.5%` (не используется, т.к. `extend_time_if_profitable: false`)

---

## 2️⃣ ФИЛЬТРЫ, КОТОРЫЕ МОГУТ ЗАКРЫВАТЬ РАНЬШЕ TP/SL

### Код из `position_manager.py` (строки 540-571):

```python
# ✅ ПРИОРИТЕТ #1: Profit Harvesting (быстрый выход при большой прибыли)
ph_should_close = await self._check_profit_harvesting(position)
if ph_should_close:
    logger.info(f"🔄 [MANAGE_POSITION] {symbol}: PH сработал, закрываем позицию")
    await self._close_position_by_reason(position, "profit_harvest")
    return  # Закрыли по PH, дальше не проверяем

# ✅ ПРИОРИТЕТ #2: Profit Drawdown (защита от отката прибыли)
drawdown_should_close = await self._check_profit_drawdown(position)
if drawdown_should_close:
    logger.info(f"🔄 [MANAGE_POSITION] {symbol}: Profit Drawdown сработал, закрываем позицию")
    await self._close_position_by_reason(position, "profit_drawdown")
    return  # Закрыли по откату, дальше не проверяем
```

### Код из `position_manager.py` - `_check_profit_harvesting` (строки 1335-1800):

```python
async def _check_profit_harvesting(self, position: Dict[str, Any]) -> bool:
    """
    ✅ МОДЕРНИЗАЦИЯ #1: Profit Harvest (PH) - быстрое закрытие при высокой прибыли
    
    Досрочный выход если позиция быстро достигла хорошей прибыли!
    ✅ АДАПТИВНЫЕ параметры из конфига по режиму рынка:
    - TRENDING: $0.20 за 180 сек (3 мин)
    - RANGING: $0.15 за 120 сек (2 мин)
    - CHOPPY: $0.10 за 60 сек (1 мин)
    """
    symbol = position.get("instId", "").replace("-SWAP", "")
    size = float(position.get("pos", "0"))
    side = position.get("posSide", "long").lower()
    entry_price = float(position.get("avgPx", "0"))
    current_price = float(position.get("markPx", "0"))
    
    # Получаем параметры PH из конфига по режиму
    market_regime = None  # Получаем из orchestrator
    ph_enabled = False
    ph_threshold_usd = 0.0  # Порог прибыли в USD
    ph_time_limit = 0  # Время в секундах
    
    # Получаем режим из orchestrator
    if hasattr(self, "orchestrator") and self.orchestrator:
        if hasattr(self.orchestrator, "signal_generator"):
            regime_manager = getattr(
                self.orchestrator.signal_generator, "regime_manager", None
            )
            if regime_manager:
                regime_obj = regime_manager.get_current_regime()
                if regime_obj:
                    market_regime = regime_obj.lower()
    
    # Получаем параметры из adaptive_regime по режиму
    adaptive_regime = getattr(self.scalping_config, "adaptive_regime", {})
    regime_config = None
    
    if isinstance(adaptive_regime, dict):
        if market_regime and market_regime in adaptive_regime:
            regime_config = adaptive_regime.get(market_regime, {})
        elif "ranging" in adaptive_regime:
            regime_config = adaptive_regime.get("ranging", {})
    
    # Получаем profit_harvest параметры из regime_config
    if regime_config:
        ph_config = regime_config.get("profit_harvest", {})
        if isinstance(ph_config, dict):
            ph_enabled = ph_config.get("enabled", False)
            ph_threshold_usd = ph_config.get("threshold_usd", 0.0)
            ph_time_limit = ph_config.get("time_limit_seconds", 0)
    
    if not ph_enabled or ph_threshold_usd <= 0:
        return False  # PH отключен или не настроен
    
    # Рассчитываем прибыль в USD
    size_in_coins = abs(size) * ct_val  # Конвертируем в монеты
    if side == "long":
        unrealized_pnl = (current_price - entry_price) * size_in_coins
    else:
        unrealized_pnl = (entry_price - current_price) * size_in_coins
    
    # Получаем время в позиции
    time_in_position = ...  # Получаем из entry_time
    
    # Проверяем условия PH
    if unrealized_pnl >= ph_threshold_usd and time_in_position >= ph_time_limit:
        logger.info(
            f"✅ Profit Harvesting: {symbol} прибыль ${unrealized_pnl:.2f} >= ${ph_threshold_usd:.2f}, "
            f"время {time_in_position:.1f} сек >= {ph_time_limit} сек - ЗАКРЫВАЕМ"
        )
        return True
    return False
```

### Код из `position_manager.py` - `_check_profit_drawdown` (строки 4285-4600):

```python
async def _check_profit_drawdown(self, position: Dict[str, Any]) -> bool:
    """
    ✅ НОВОЕ: Проверка отката от максимальной прибыли.
    
    Закрывает позицию если прибыль упала на X% от максимума.
    
    Параметры из конфига:
    - Trending: 40% откат (тренд продолжается)
    - Ranging: 30% откат (боковик)
    - Choppy: 20% откат (быстро фиксируем)
    """
    symbol = position.get("instId", "").replace("-SWAP", "")
    size = float(position.get("pos", "0"))
    entry_price = float(position.get("avgPx", "0"))
    side = position.get("posSide", "long").lower()
    
    # ✅ КРИТИЧЕСКОЕ: Используем markPx для Profit Drawdown (защита от проскальзывания)
    current_price = float(position.get("markPx", "0"))
    
    # Получаем peak_profit из позиции
    peak_profit = position.get("peak_profit", 0.0)
    if peak_profit <= 0:
        return False  # Не было прибыли - не закрываем
    
    # Рассчитываем текущую прибыль
    size_in_coins = abs(size) * ct_val
    if side == "long":
        unrealized_pnl = (current_price - entry_price) * size_in_coins
    else:
        unrealized_pnl = (entry_price - current_price) * size_in_coins
    
    # Получаем margin_used
    margin_used = float(position.get("margin", "0"))
    if margin_used <= 0:
        return False
    
    current_pnl_percent = (unrealized_pnl / margin_used) * 100
    
    # ✅ КРИТИЧЕСКОЕ: Не закрываем если позиция в убытке
    if current_pnl_percent < 0:
        return False
    
    # Получаем drawdown_percent из конфига по режиму
    profit_drawdown_config = getattr(self.scalping_config, "profit_drawdown", {})
    base_drawdown = profit_drawdown_config.get("drawdown_percent", 0.20)  # 20% базовый
    
    # Получаем режим и множитель
    market_regime = None  # Получаем из orchestrator
    multiplier = 1.0
    
    if hasattr(self, "orchestrator") and self.orchestrator:
        if hasattr(self.orchestrator, "signal_generator"):
            regime_manager = getattr(
                self.orchestrator.signal_generator, "regime_manager", None
            )
            if regime_manager:
                regime_obj = regime_manager.get_current_regime()
                if regime_obj:
                    market_regime = regime_obj.lower()
    
    # Получаем множитель по режиму
    by_regime = profit_drawdown_config.get("by_regime", {})
    if market_regime and market_regime in by_regime:
        regime_dd = by_regime[market_regime]
        if isinstance(regime_dd, dict):
            multiplier = regime_dd.get("multiplier", 1.0)
        else:
            multiplier = getattr(regime_dd, "multiplier", 1.0)
    
    drawdown_percent = base_drawdown * multiplier  # 0.20 * 2.0 = 0.40 для trending
    
    # Проверяем откат
    drawdown_threshold = peak_profit * (1 - drawdown_percent)
    if current_pnl_percent < drawdown_threshold:
        logger.info(
            f"✅ Profit Drawdown: {symbol} откат с {peak_profit:.2f}% до {current_pnl_percent:.2f}% "
            f"(порог: {drawdown_threshold:.2f}%, drawdown={drawdown_percent:.0%}) - ЗАКРЫВАЕМ"
        )
        return True
    return False
```

### Код из `position_manager.py` - `_check_partial_tp` (строки ~2800-3000):

```python
async def _check_partial_tp(self, position: Dict[str, Any]) -> bool:
    """
    Проверка Partial TP - частичное закрытие позиции.
    
    Логика:
    - Если прибыль >= trigger_percent (0.2-0.4% в зависимости от режима)
    - И прошло min_holding_minutes
    - → Закрываем fraction (50-70%) позиции
    """
    # Получаем параметры partial_tp из конфига
    partial_tp_config = getattr(self.scalping_config, "partial_tp", {})
    if not partial_tp_config.get("enabled", False):
        return False
    
    # Получаем trigger_percent по режиму
    regime = position.get("regime", "ranging")
    by_regime = partial_tp_config.get("by_regime", {})
    regime_params = by_regime.get(regime, {})
    trigger_percent = regime_params.get("trigger_percent", 0.4)
    fraction = regime_params.get("fraction", 0.6)
    
    # Проверяем прибыль
    if pnl_percent_from_margin >= trigger_percent:
        # Проверяем min_holding
        if time_in_position >= min_holding_minutes:
            logger.info(
                f"✅ Partial TP: {symbol} прибыль {pnl_percent_from_margin:.2f}% >= {trigger_percent:.2f}%, "
                f"время {time_in_position:.1f} мин >= {min_holding_minutes:.1f} мин - "
                f"закрываем {fraction*100:.0f}% позиции"
            )
            await self._close_partial_position(position, fraction)
            return True
    return False
```

---

## 3️⃣ ЛОГИКА ЧАСТИЧНОГО ЗАКРЫТИЯ

### Код из `exit_analyzer.py` (строки 685-750):

```python
def _get_partial_tp_params(self, regime: str) -> Dict[str, Any]:
    """
    Получение параметров partial_tp из конфига по режиму.
    
    Returns:
        Параметры partial_tp {enabled: bool, fraction: float, trigger_percent: float}
    """
    params = {
        "enabled": False,
        "fraction": 0.6,
        "trigger_percent": 0.4,
    }
    
    if self.scalping_config:
        partial_tp_config = getattr(self.scalping_config, "partial_tp", {})
        if isinstance(partial_tp_config, dict):
            params["enabled"] = partial_tp_config.get("enabled", False)
            params["fraction"] = partial_tp_config.get("fraction", 0.6)
            params["trigger_percent"] = partial_tp_config.get("trigger_percent", 0.4)
            
            # Пробуем получить параметры по режиму
            by_regime = partial_tp_config.get("by_regime", {})
            if regime in by_regime:
                regime_params = by_regime[regime]
                params["fraction"] = regime_params.get("fraction", params["fraction"])
                params["trigger_percent"] = regime_params.get(
                    "trigger_percent", params["trigger_percent"]
                )
    
    return params
```

### Адаптивный min_holding для Partial TP:

```yaml
adaptive_min_holding:
  enabled: true
  profit_threshold_1: 1.0  # Прибыль >= 1.0% → снижаем min_holding до 50%
  profit_threshold_2: 0.5  # Прибыль >= 0.5% → снижаем min_holding до 75%
  reduction_factor_1: 0.5  # Коэффициент снижения для threshold_1 (50%)
  reduction_factor_2: 0.75 # Коэффициент снижения для threshold_2 (75%)
```

**Логика:**
- Если прибыль >= 1.0% → `min_holding` снижается до 50% от базового
- Если прибыль >= 0.5% → `min_holding` снижается до 75% от базового
- Это позволяет быстрее закрывать частично при высокой прибыли

---

## 4️⃣ ПОСЛЕДНИЕ СДЕЛКИ ИЗ TRADES.CSV

**Файл:** `logs/futures/archived/logs_2025-12-07_16-03-39_extracted/trades_2025-12-07.csv`

**Последние 5 сделок:**

| timestamp | symbol | side | entry_price | exit_price | size | gross_pnl | commission | net_pnl | duration_sec | reason | win_rate |
|-----------|--------|------|-------------|------------|------|-----------|------------|---------|--------------|--------|----------|
| 2025-12-07T14:19:11 | DOGE-USDT | long | 0.1392 | 0.1393 | 80.0 | +0.0064 | 0.0111 | **-0.0047** | 1667.3 сек (27.8 мин) | **max_holding_exceeded** | 0.00 |
| 2025-12-07T14:44:57 | ETH-USDT | short | 3033.00 | 3031.81 | -0.008 | +0.0095 | 0.0243 | **-0.0147** | 0.002 сек | **max_holding_exceeded** | 0.00 |
| 2025-12-07T14:49:00 | BTC-USDT | short | 88800.90 | 88755.40 | -0.0007 | +0.0319 | 0.0621 | **-0.0303** | 0.0 сек | **max_holding_exceeded** | 0.00 |
| 2025-12-07T14:54:17 | SOL-USDT | short | 132.66 | 132.58 | -0.1 | +0.0080 | 0.0133 | **-0.0053** | 2512.2 сек (41.9 мин) | **max_holding_exceeded** | 0.00 |
| 2025-12-07T15:12:15 | XRP-USDT | long | 2.0337 | 2.0344 | 38.0 | +0.0263 | 0.0773 | **-0.0510** | 4835.3 сек (80.6 мин) | **max_holding_exceeded** | 0.00 |

**Наблюдения:**
- ❌ **ВСЕ 5 сделок закрыты по `max_holding_exceeded`** - позиции держались слишком долго
- ❌ **ВСЕ 5 сделок убыточные** (net_pnl < 0) - комиссии съели всю прибыль
- ⚠️ **Gross PnL положительный** у всех, но после комиссий становится отрицательным
- ⚠️ **Duration очень разный**: от 0.002 сек до 80.6 минут
- ⚠️ **DOGE-USDT**: держалась 27.8 минут, закрыта с убытком -0.0047 USDT
- ⚠️ **ETH-USDT**: держалась 0.002 сек (почти мгновенно), закрыта с убытком -0.0147 USDT
- ⚠️ **BTC-USDT**: держалась 0.0 сек (мгновенно), закрыта с убытком -0.0303 USDT
- ⚠️ **SOL-USDT**: держалась 41.9 минут, закрыта с убытком -0.0053 USDT
- ⚠️ **XRP-USDT**: держалась 80.6 минут, закрыта с убытком -0.0510 USDT

**Анализ причин:**
1. **Комиссии слишком высокие** относительно прибыли:
   - DOGE: gross_pnl = +0.0064, commission = 0.0111 → net_pnl = -0.0047 (комиссия больше прибыли!)
   - ETH: gross_pnl = +0.0095, commission = 0.0243 → net_pnl = -0.0147 (комиссия в 2.5 раза больше прибыли!)
   - BTC: gross_pnl = +0.0319, commission = 0.0621 → net_pnl = -0.0303 (комиссия в 2 раза больше прибыли!)

2. **Позиции закрываются по таймауту** вместо TP/SL:
   - Все 5 сделок закрыты по `max_holding_exceeded`
   - Это означает, что TP/SL не достигнуты, и позиции просто истекли по времени
   - При этом позиции были в небольшой прибыли (gross_pnl > 0), но комиссии съели всю прибыль

3. **Проблема с расчетом комиссий:**
   - Комиссии рассчитываются от номинала позиции
   - При плече 5x: комиссия 0.10% от номинала = 0.50% от маржи (0.10% × 5)
   - Но в логах комиссии выглядят слишком высокими относительно прибыли

---

## 🔍 ВЫВОДЫ И ПОДОЗРЕНИЯ

### ❌ КРИТИЧЕСКАЯ ПРОБЛЕМА: Partial TP срабатывает слишком рано!

**Проблема:**
- TP = 2.4%, но Partial TP срабатывает при **0.2-0.4%** прибыли
- Это означает, что позиция закрывается частично **ДО** достижения полного TP
- После частичного закрытия оставшаяся позиция может не достичь полного TP

**Пример:**
- Позиция открыта с TP = 2.4%
- При прибыли 0.3% (ranging) срабатывает Partial TP → закрывается 60% позиции
- Оставшиеся 40% позиции могут не достичь 2.4% TP
- Итоговая прибыль: 0.3% * 60% + (возможно 0.5% * 40%) = **~0.38%** вместо 2.4%

### ⚠️ ПРОБЛЕМА: Profit Harvesting может закрывать раньше TP

**Проблема:**
- Для BTC/ETH: `big_profit_exit_percent = 1.5%` < TP (2.4-5.0%)
- Для альтов: `big_profit_exit_percent = 2.0%` < TP (1.9-4.0%)
- Это означает, что позиция закрывается при 1.5-2.0% прибыли, **НЕ ДОСТИГАЯ** полного TP

### ⚠️ ПРОБЛЕМА: Profit Drawdown может закрывать при малом откате

**Проблема:**
- `drawdown_percent = 0.20` (20% откат от пика)
- Если позиция достигла 0.5% прибыли, а затем откатилась до 0.4% (откат 20%)
- → Позиция закрывается при 0.4% прибыли вместо ожидания восстановления до TP

---

## 📊 РЕКОМЕНДАЦИИ

1. **Увеличить `trigger_percent` для Partial TP:**
   - `trending`: 0.4% → **1.0%** (ближе к TP)
   - `ranging`: 0.3% → **0.8%** (ближе к TP)
   - `choppy`: 0.2% → **0.5%** (ближе к TP)

2. **Увеличить `big_profit_exit_percent`:**
   - `big_profit_exit_percent_majors`: 1.5% → **2.5%** (ближе к TP)
   - `big_profit_exit_percent_alts`: 2.0% → **3.0%** (ближе к TP)

3. **Увеличить `drawdown_percent`:**
   - Базовый: 0.20 → **0.30** (30% откат вместо 20%)
   - Это даст больше времени для восстановления до TP

4. **Добавить проверку: Partial TP только если прибыль >= 50% от TP:**
   - Если TP = 2.4%, то Partial TP срабатывает только при прибыли >= 1.2%
   - Это гарантирует, что частичное закрытие происходит ближе к полному TP

---

**Готово для анализа!**

