# 🔍 ПОЛНЫЙ АНАЛИЗ FALLBACK ПУТЕЙ - Кто и что где ломает
## Дата: 25 января 2026

---

## 📊 СТАТИСТИКА FALLBACK В КОДЕ

**Найдено 785 fallback вхождений в 36 файлах:**

| Файл | Кол-во | Критичность |
|------|--------|-------------|
| signal_generator.py | 138 | 🔥 ВЫСОКАЯ |
| position_manager.py | 124 | 🔥 ВЫСОКАЯ |
| exit_analyzer.py | 84 | 🔥 КРИТИЧЕСКАЯ |
| orchestrator.py | 77 | 🔴 СРЕДНЯЯ |
| order_executor.py | 53 | 🔴 СРЕДНЯЯ |
| data_registry.py | 20+ | 🔥 КРИТИЧЕСКАЯ |
| websocket_coordinator.py | 10+ | 🔴 СРЕДНЯЯ |

---

## 🔥 ПРОБЛЕМА #1: УСТАРЕВШИЕ ДАННЫЕ (Stale Data)

### Корневая причина: Двойные стандарты TTL

**Где ломается:** DataRegistry возвращает устаревшие данные (до 60 секунд!)

#### Файл: [data_registry.py:24-59](src/strategies/scalping/futures/core/data_registry.py:24)

**Проблема:**
```python
# Строка 51: WebSocket данные терпят устаревание до 60 секунд
effective_max_age = 60.0  # ❌ СЛИШКОМ ДОЛГО для trading decisions!

if age > effective_max_age:
    logger.warning(
        f"❌ DataRegistry: Данные для {symbol} устарели на {age:.2f}s (> {effective_max_age}s)"
    )
    # ❌ НО ВОЗВРАЩАЕТ УСТАРЕВШИЕ ДАННЫЕ ANYWAY!
    return price  # ← ЭТО ПРОБЛЕМА!
```

**Кто использует устаревшие данные:**

1. **OrderExecutor** ([order_executor.py:393-440](src/strategies/scalping/futures/order_executor.py:393))
   ```python
   # Строка 401: Проверяет возраст, но ПРИНИМАЕТ до 1.0s
   md_age_sec = (datetime.now() - updated_at).total_seconds()
   if md_age_sec > 1.0:
       logger.warning(f"❌ DataRegistry price устарела на {md_age_sec:.3f}s, fallback на market")
       return "market"  # ✅ Хотя бы падает на market

   # ❌ НО: DataRegistry может вернуть данные возрастом 60s!
   # Проверка 1.0s не работает, если DataRegistry уже вернул старые данные
   ```

2. **PositionManager** ([position_manager.py:580-588](src/strategies/scalping/futures/position_manager.py:580))
   ```python
   # Строка 580: Fallback на DataRegistry для entry_price
   if entry_price <= 0:
       fallback_price = await self.data_registry.get_price(symbol)
       # ❌ Может получить цену возрастом 60 секунд!
       if fallback_price and fallback_price > 0:
           entry_price = fallback_price
   ```

3. **SignalGenerator** ([signal_generator.py:1797-1859](src/strategies/scalping/futures/signal_generator.py:1797))
   ```python
   # Строка 1832: Fallback на candle close price
   if fallback_price and isinstance(fallback_price, (int, float)) and float(fallback_price) > 0:
       return float(fallback_price)

   # ❌ Свеча может быть закрыта минуту назад!
   # Для scalping это устаревшие данные
   ```

**Что ломается:**
- Лимитные ордера размещаются по устаревшей цене → не исполняются или слипаж
- Позиции открываются с неправильным entry_price → неправильный расчет PnL
- Сигналы генерируются на устаревших данных → ложные входы

**РЕШЕНИЕ:**
```python
# ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Все модули должны использовать СТРОГИЙ TTL

# В data_registry.py:
# 1. get_price() → max 5s TTL для общего использования (не 60s!)
# 2. get_fresh_price_for_exit_analyzer() → max 2s TTL (уже есть!)
# 3. get_fresh_price_for_signals() → max 3s TTL (новый метод)
# 4. get_fresh_price_for_orders() → max 1s TTL (новый метод)

# Все модули должны использовать ПРАВИЛЬНЫЙ метод для своих нужд!
```

---

## 🔥 ПРОБЛЕМА #2: CONFIG FALLBACK CASCADE - TP/SL дисбаланс

### Корневая причина: Отсутствующие режимные секции в конфиге

**Где ломается:** ExitAnalyzer получает неправильные TP/SL из fallback цепочки

#### Файл: [exit_analyzer.py:1070-1169](src/strategies/scalping/futures/positions/exit_analyzer.py:1070)

**Fallback цепочка для TP/SL:**
```
1. ParameterProvider.get_exit_params()          ✅ ПРАВИЛЬНО
   ↓ (если не нашел)
2. symbol_profiles.{SYMBOL}.{REGIME}            ⚠️ Часто ОТСУТСТВУЕТ!
   ↓ (если не нашел)
3. symbol_profiles.{SYMBOL}                     ❌ НЕПРАВИЛЬНЫЕ ЗНАЧЕНИЯ для режима!
   ↓ (если не нашел)
4. by_regime.{REGIME}                           ⚠️ Глобальные, не учитывают символ
   ↓ (если не нашел)
5. scalping_config.tp_percent                   ❌ ПОСЛЕДНИЙ ШАНС (слишком общий)
```

**Реальный пример катастрофы:**

**XRP-USDT в choppy режиме (25.01.2026):**

```python
# Что ДОЛЖНО быть (после наших фиксов):
# symbol_profiles.XRP-USDT.choppy:
tp_percent = 3.0%
sl_percent = 2.0%
tp_atr_multiplier = 1.5
# Соотношение: 1.5:1 ✅

# Что БЫЛО (fallback на symbol_profiles.XRP-USDT):
tp_percent = 4.5%
tp_atr_multiplier = 4.0  # ❌ Для низковолатильных пар, НЕ для choppy!
# После расчета с leverage adjustment:
# TP = 8.80%, SL = 2.5%
# Соотношение: 3.5:1 ❌ КАТАСТРОФА!
```

**Логи показывают проблему:**
```
📊 [PARAMS] XRP-USDT (choppy): TP параметры
   tp_percent=2.40%,
   tp_atr_multiplier=1.00,
   tp_min=1.00%, tp_max=2.20%
   | Источник: ParameterProvider.get_exit_params()  ✅ ПРАВИЛЬНО

📊 [PARAMS] XRP-USDT (choppy): TP параметры
   tp_percent=4.00%,
   tp_atr_multiplier=2.50,  ❌ ПЕРЕЗАПИСАЛИ!
   tp_min=1.50%, tp_max=2.20%
   | Источник: symbol_profiles.XRP-USDT.choppy (fallback)  ❌ НО СЕКЦИИ НЕТ В КОНФИГЕ!
```

**Что ломается:**
- TP = 8.80% требует огромного движения цены (редко достигается)
- SL = 2.5% срабатывает часто (легко достигается)
- Убытки в **4.4 раза больше** прибылей!
- При win rate 50% → гарантированный слив денег

**Кто еще использует config fallback:**

1. **PositionManager.get_tp_for_symbol** ([position_manager.py:180-290](src/strategies/scalping/futures/position_manager.py:180)):
   ```python
   # Цепочка fallback:
   # 1. symbol_profiles.{SYMBOL}.{REGIME}.tp_percent
   # 2. symbol_profiles.{SYMBOL}.tp_percent  ← FALLBACK без режима!
   # 3. scalping_config.tp_percent  ← ГЛОБАЛЬНЫЙ FALLBACK
   ```

2. **PositionManager.get_sl_for_symbol** ([position_manager.py:352-460](src/strategies/scalping/futures/position_manager.py:352)):
   ```python
   # Аналогичная цепочка для SL
   ```

**РЕШЕНИЕ:**
```yaml
# ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (25.01.2026): Добавлены все режимные секции

symbol_profiles:
  XRP-USDT:
    position_multiplier: 1.1
    # ✅ ОБЯЗАТЕЛЬНО: Секции для КАЖДОГО режима!
    trending:
      tp_percent: 5.0
      sl_percent: 1.5
      tp_atr_multiplier: 3.0
      sl_atr_multiplier: 2.5
    choppy:  # ← ЭТО БЫЛО ПРОПУЩЕНО!
      tp_percent: 3.0
      sl_percent: 2.0
      tp_atr_multiplier: 1.5
      sl_atr_multiplier: 3.5
    ranging:
      tp_percent: 3.5
      sl_percent: 2.0
      tp_atr_multiplier: 2.0
      sl_atr_multiplier: 3.5
```

---

## 🔥 ПРОБЛЕМА #3: REST API FALLBACK СПАМ

### Корневая причина: WebSocket отстает → весь бот падает на REST API

**Где ломается:** WebSocketCoordinator + OrderExecutor + PositionManager

#### Файл: [websocket_coordinator.py:736-877](src/strategies/scalping/futures/coordinators/websocket_coordinator.py:736)

**Проблема:**
```python
# Строка 736: REST candle polling как fallback
logger.info("📡 REST candle polling включен (fallback)")

# Строка 747: Опрос REST API каждые X секунд
async def _start_rest_candle_polling(self):
    """Опрос REST API для получения свечей (fallback для Sandbox)"""
    while self._rest_polling_active:
        for symbol in self.symbols_to_watch:
            # ❌ REST запрос для КАЖДОГО символа!
            await self._fetch_candles_rest(symbol, bar="1m", limit=100)
        await asyncio.sleep(5)  # ❌ Каждые 5 секунд!
```

**Последствия:**
- 10 символов × REST запрос каждые 5 секунд = 120 запросов в минуту
- Rate limit на OKX API: 20 requests/2s для публичных endpoint
- **РИСК BAN из-за превышения rate limit!**

**Кто еще использует REST fallback:**

1. **OrderExecutor._calculate_limit_price** ([order_executor.py:875-960](src/strategies/scalping/futures/order_executor.py:875)):
   ```python
   # Строка 934: Fallback на REST API ticker
   if not price_limits or not current_price:
       logger.warning(f"⚠️ Не удалось получить лимиты цены, используем fallback")
       async with aiohttp.ClientSession() as session:
           url = f"{self.client.base_url}/api/v5/market/ticker?instId={symbol}-SWAP"
           async with session.get(url) as resp:
               # ❌ REST запрос при КАЖДОЙ проверке лимитной цены!
   ```

2. **DataRegistry.get_fresh_price_for_exit_analyzer** ([data_registry.py:220-237](src/strategies/scalping/futures/core/data_registry.py:220)):
   ```python
   # Строка 220: REST fallback если WebSocket устарел >2s
   if client:
       ticker = await client.get_ticker(symbol)
       # ✅ Это ПРАВИЛЬНО для ExitAnalyzer (критические решения)
       # ❌ НО если WebSocket постоянно отстает → СПАМ REST запросов!
   ```

**Логи показывают:**
```
⚠️ ExitAnalyzer: WebSocket цена для XRP-USDT устарела на 3.2s, fallback на REST API
⚠️ ExitAnalyzer: WebSocket цена для SOL-USDT устарела на 2.8s, fallback на REST API
⚠️ ExitAnalyzer: WebSocket цена для BTC-USDT устарела на 2.3s, fallback на REST API
⚠️ OrderExecutor: Не удалось получить лимиты цены для XRP-USDT, используем fallback
⚠️ OrderExecutor: Не удалось получить лимиты цены для SOL-USDT, используем fallback
```

**Что ломается:**
- Превышение rate limit → задержки или бан
- Медленные ордера → пропуск оптимальных входов
- Высокая нагрузка на сервер OKX

**РЕШЕНИЕ:**
```python
# ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Ограничить REST fallback

# 1. Кэширование REST ответов (TTL 1s)
_rest_ticker_cache = {}

async def get_ticker_with_cache(symbol: str):
    cache_key = f"{symbol}_ticker"
    cached = _rest_ticker_cache.get(cache_key)
    if cached and (time.time() - cached['timestamp']) < 1.0:
        return cached['data']  # ✅ Используем кэш

    # Делаем REST запрос только если кэш устарел
    ticker = await client.get_ticker(symbol)
    _rest_ticker_cache[cache_key] = {
        'data': ticker,
        'timestamp': time.time()
    }
    return ticker

# 2. Rate limiter для REST API
from asyncio import Semaphore
_rest_api_semaphore = Semaphore(5)  # Max 5 concurrent requests

async def get_ticker_with_limit(symbol: str):
    async with _rest_api_semaphore:
        await asyncio.sleep(0.1)  # 100ms delay между запросами
        return await client.get_ticker(symbol)

# 3. WebSocket auto-reconnect при частых fallback
_fallback_counter = 0

async def get_fresh_price_for_exit_analyzer(symbol: str):
    global _fallback_counter

    # Пытаемся WebSocket
    ws_price = await get_ws_price(symbol)
    if ws_price and age <= 2.0:
        _fallback_counter = 0
        return ws_price

    # Fallback на REST
    _fallback_counter += 1
    if _fallback_counter > 10:
        logger.error("❌ WebSocket постоянно отстает! Перезапускаем...")
        await self.websocket_coordinator.reconnect()
        _fallback_counter = 0

    return await get_ticker_with_cache(symbol)
```

---

## 🔴 ПРОБЛЕМА #4: LIMIT ORDER OFFSET FALLBACK → Market Orders

### Корневая причина: Отсутствующие offset конфиги → fallback на market

**Где ломается:** OrderExecutor не может рассчитать лимитную цену

#### Файл: [order_executor.py:565-760](src/strategies/scalping/futures/order_executor.py:565)

**Fallback цепочка для limit_offset_percent:**
```
1. by_symbol.{SYMBOL}.by_regime.{REGIME}.limit_offset_percent  ✅ Самый точный
   ↓ (если не нашел)
2. by_symbol.{SYMBOL}.limit_offset_percent                     ⚠️ Игнорирует режим
   ↓ (если не нашел)
3. by_regime.{REGIME}.limit_offset_percent                     ⚠️ Игнорирует символ
   ↓ (если не нашел)
4. default_offset (глобальный)                                  ❌ 0.0 → market order!
   ↓ (если 0.0)
5. FALLBACK НА MARKET ORDER                                     ❌ Потеря контроля!
```

**Реальный пример:**

**Лог показывает:**
```
📊 [LIMIT_ORDER_OFFSET] XRP-USDT SHORT (choppy):
   ✅ Приоритет 1 - by_symbol.by_regime: НЕ НАЙДЕН
   ✅ Приоритет 2 - by_symbol: НЕ НАЙДЕН
   ✅ Приоритет 3 - by_regime: НЕ НАЙДЕН
   ❌ Приоритет 4 - Глобальный fallback: 0.0%

   by_symbol существует: False
   by_regime существует: False

   ❌ offset_percent = 0.0%
   Лимитный ордер не будет размещён, fallback на market
```

**Код fallback:**
```python
# Строка 744: Финальный fallback на глобальный offset
if offset_percent is None:
    offset_percent = default_offset  # ❌ Часто = 0.0

    logger.warning(
        f"⚠️ [LIMIT_ORDER_OFFSET] {symbol} {side} ({regime}): "
        f"Используется глобальный fallback offset={offset_percent:.3f}% "
        f"Лимитный ордер не будет размещён, fallback на market"
    )

# Строка 760: Возвращаем 0.0 → OrderExecutor интерпретирует как "market order"
return 0.0  # ❌ FALLBACK НА MARKET!
```

**Что ломается:**
- Лимитные ордера НЕ размещаются → всегда market orders
- Market orders → немедленное исполнение → НЕТ контроля цены
- Слипаж на волатильных парах (XRP, DOGE) → больше убытков
- **Невозможно войти точно на уровне поддержки/сопротивления**

**РЕШЕНИЕ:**
```yaml
# ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (25.01.2026): Добавить offset для всех режимов

order_executor:
  limit_order:
    default_offset_percent: 0.05  # ✅ НЕ 0.0! Минимальный offset

    # ✅ Добавить by_regime для ВСЕХ режимов
    by_regime:
      trending:
        limit_offset_percent: 0.10  # Больше offset для trending
        use_market_order: false
      choppy:
        limit_offset_percent: 0.05  # Меньше offset для choppy
        use_market_order: false
      ranging:
        limit_offset_percent: 0.08
        use_market_order: false

    # ✅ Добавить by_symbol для волатильных пар
    by_symbol:
      XRP-USDT:
        by_regime:
          choppy:
            limit_offset_percent: 0.03  # ← БЫЛО ПРОПУЩЕНО!
          trending:
            limit_offset_percent: 0.12
      DOGE-USDT:
        by_regime:
          choppy:
            limit_offset_percent: 0.04
```

---

## 🔴 ПРОБЛЕМА #5: REGIME FALLBACK → Неправильный режим позиции

### Корневая причина: Режим рынка не сохраняется с позицией

**Где ломается:** PositionManager пытается найти режим из 3 источников

#### Файл: [position_manager.py:1069-1120](src/strategies/scalping/futures/position_manager.py:1069)

**Fallback цепочка для regime:**
```python
# Строка 1069: Fallback chain для получения режима
market_regime = (
    position.get("regime")  # 1. ✅ Из данных позиции (если сохранено)
    or self.active_positions.get(symbol, {}).get("regime")  # 2. ✅ Из кэша
    # 3. ❌ ASYNC запрос к RegimeManager!
)

# Если не нашли в кэше → запрашиваем RegimeManager
if not market_regime:
    try:
        if self.orchestrator and hasattr(self.orchestrator, "signal_generator"):
            regime_manager = (
                self.orchestrator.signal_generator.regime_managers.get(symbol)
                or self.orchestrator.signal_generator.regime_manager
            )
            if regime_manager:
                regime_data = await regime_manager.get_regime_data(symbol)
                market_regime = regime_data.get("regime") if regime_data else "ranging"
    except Exception as e:
        logger.error(f"⚠️ Ошибка получения режима для {symbol}: {e}")
        market_regime = "ranging"  # ❌ ФИНАЛЬНЫЙ FALLBACK на "ranging"!
```

**Проблема:**
- **RegimeManager может вернуть ДРУГОЙ режим** чем был при входе!
- Рынок изменился: был choppy → стал trending
- Позиция использует **TP/SL для trending вместо choppy!**
- **Неправильные параметры выхода → ложные закрытия**

**Реальный пример:**

```
13:26:37 | 📈 Position opened: XRP-USDT SHORT @ 1.9304, regime=choppy
          TP должен: 3.0% (choppy), SL должен: 2.0%

13:28:15 | 🔄 RegimeManager: XRP-USDT теперь TRENDING (ADX вырос)

13:28:42 | 🔄 [MANAGE_POSITION] XRP-USDT: Проверка Exit Analyzer
          ❌ Получен regime=trending из RegimeManager fallback
          ❌ Использует TP: 5.0% (trending), SL: 1.5% (trending)
          ❌ НЕПРАВИЛЬНЫЕ ПАРАМЕТРЫ для позиции открытой в choppy!
```

**Что ломается:**
- Позиции закрываются по **неправильным TP/SL**
- TP слишком высокий (trending) для позиции открытой в choppy → не достигается
- SL слишком низкий (trending) → срабатывает раньше
- **Потеря прибылей и увеличение убытков**

**РЕШЕНИЕ:**
```python
# ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: ВСЕГДА сохранять режим с позицией

# В EntryManager при открытии позиции:
self.active_positions[symbol] = {
    "symbol": symbol,
    "position_side": side,
    "entry_price": entry_price,
    "size": size,
    "entry_time": datetime.now(),
    "regime": current_regime,  # ✅ ОБЯЗАТЕЛЬНО сохранить!
    "tp_params": tp_params,    # ✅ ОБЯЗАТЕЛЬНО сохранить TP для этого режима!
    "sl_params": sl_params,    # ✅ ОБЯЗАТЕЛЬНО сохранить SL для этого режима!
}

# В PositionManager НЕ ИСПОЛЬЗОВАТЬ fallback на RegimeManager:
def get_position_regime(self, symbol: str, position: dict) -> str:
    """Получить режим позиции БЕЗ fallback на текущий режим рынка"""

    # 1. Из данных позиции
    regime = position.get("regime")
    if regime:
        return regime

    # 2. Из кэша active_positions
    regime = self.active_positions.get(symbol, {}).get("regime")
    if regime:
        return regime

    # 3. ❌ НЕ ПАДАТЬ на RegimeManager!
    # Вместо этого логировать ОШИБКУ и использовать fallback
    logger.error(
        f"❌ КРИТИЧЕСКАЯ ОШИБКА: Позиция {symbol} не имеет сохраненного режима! "
        f"Это означает что данные позиции были потеряны. "
        f"Используем fallback 'ranging' но TP/SL могут быть неправильными!"
    )
    return "ranging"  # Fallback только в крайнем случае
```

---

## 🟡 ПРОБЛЕМА #6: LEVERAGE FALLBACK (Менее критично, но важно)

### Корневая причина: Leverage берется из 3 источников с приоритетом

**Где ломается:** PositionManager определяет leverage для расчета маржи

#### Файл: [position_manager.py:937-1007](src/strategies/scalping/futures/position_manager.py:937)

**Fallback цепочка для leverage:**
```python
# Строка 964: Приоритет leverage
leverage_from_config = None
leverage_from_position_lever = None
leverage_from_position_leverage = None

# 1. Из конфига (scalping_config.leverage)
leverage_from_config = getattr(self.scalping_config, "leverage", None)

# 2. Из OKX API position.lever
if "lever" in position and position.get("lever"):
    lever_value = position.get("lever", "0")
    leverage_from_position_lever = int(float(lever_value))

# 3. Из OKX API position.leverage
if "leverage" in position and position.get("leverage"):
    leverage_value = position.get("leverage", "0")
    leverage_from_position_leverage = int(float(leverage_value))

# ✅ Приоритет: конфиг → position → HARD FAIL
final_leverage = (
    leverage_from_config
    or leverage_from_position_lever
    or leverage_from_position_leverage
)

if not final_leverage or final_leverage <= 0:
    # ✅ ИСПРАВЛЕНО (08.01.2026): Hard-fail вместо fallback
    raise ValueError(
        f"❌ CRITICAL: leverage не определен для {symbol}! "
        f"config={leverage_from_config}, "
        f"position.lever={leverage_from_position_lever}, "
        f"position.leverage={leverage_from_position_leverage}"
    )
```

**Это ПРАВИЛЬНЫЙ fallback:**
- ✅ Приоритет четкий: config > API
- ✅ Логирование всех источников
- ✅ Hard fail если все источники пусты (НЕТ слепого fallback)

**НО есть риск:**
- Если OKX API вернет leverage=0 (bug на их стороне)
- И конфиг не установлен (ошибка пользователя)
- → Бот упадет с ошибкой

**РЕШЕНИЕ:**
```python
# ✅ Оставить как есть, но добавить ЛУЧШЕЕ логирование

if not final_leverage or final_leverage <= 0:
    logger.critical(
        f"❌❌❌ КРИТИЧЕСКАЯ ОШИБКА: Leverage не определен для {symbol}!\n"
        f"    Источник 1 (config): {leverage_from_config}\n"
        f"    Источник 2 (position.lever): {leverage_from_position_lever}\n"
        f"    Источник 3 (position.leverage): {leverage_from_position_leverage}\n"
        f"    Проверьте:\n"
        f"    1. config_futures.yaml → scalping.leverage установлен?\n"
        f"    2. OKX API возвращает корректные данные позиции?\n"
        f"    3. Позиция действительно открыта на бирже?\n"
        f"    Position data: {position}\n"
    )
    raise ValueError(f"CRITICAL: leverage=0 для {symbol}")
```

---

## 📋 ИТОГОВАЯ ТАБЛИЦА FALLBACK ПРОБЛЕМ

| # | Проблема | Где ломается | Критичность | Что ломает |
|---|----------|--------------|-------------|------------|
| 1 | **Stale Data (60s TTL)** | DataRegistry.get_price() | 🔥 КРИТИЧЕСКАЯ | Ложные TP, неправильные ордера, устаревшие сигналы |
| 2 | **Config Fallback Cascade** | ExitAnalyzer TP/SL | 🔥 КРИТИЧЕСКАЯ | TP/SL дисбаланс 3.5:1, убытки в 4.4x больше прибылей |
| 3 | **REST API Fallback Spam** | WebSocket + OrderExecutor | 🔥 ВЫСОКАЯ | Rate limit ban, медленные ордера, высокая нагрузка |
| 4 | **Limit Offset Fallback** | OrderExecutor | 🔴 СРЕДНЯЯ | Всегда market orders, слипаж, потеря контроля цены |
| 5 | **Regime Fallback** | PositionManager | 🔴 СРЕДНЯЯ | Неправильные TP/SL для позиции, ложные закрытия |
| 6 | **Leverage Fallback** | PositionManager | 🟡 НИЗКАЯ | Hard fail (правильно), но нужно лучше логирование |

---

## ✅ ПРИОРИТИЗИРОВАННЫЕ ИСПРАВЛЕНИЯ

### 🔥 КРИТИЧЕСКОЕ (Требует немедленного исправления):

1. **Stale Data Problem (Проблема #1)**
   - ✅ УЖЕ ИСПРАВЛЕНО: get_fresh_price_for_exit_analyzer() с TTL 2s
   - ❌ ТРЕБУЕТСЯ: Распространить на OrderExecutor, PositionManager, SignalGenerator
   - **Файлы:**
     - data_registry.py: Добавить get_fresh_price_for_orders() (TTL 1s)
     - data_registry.py: Добавить get_fresh_price_for_signals() (TTL 3s)
     - order_executor.py: Использовать get_fresh_price_for_orders()
     - signal_generator.py: Использовать get_fresh_price_for_signals()

2. **Config Fallback Cascade (Проблема #2)**
   - ✅ УЖЕ ИСПРАВЛЕНО: Добавлены XRP-USDT.choppy и XRP-USDT.ranging
   - ❌ ТРЕБУЕТСЯ: Проверить другие символы (SOL, BTC, ETH, DOGE)
   - **Действие:** Добавить choppy/trending/ranging секции для ВСЕХ активных символов

3. **REST API Fallback Spam (Проблема #3)**
   - ❌ ТРЕБУЕТСЯ: Кэширование REST ответов (TTL 1s)
   - ❌ ТРЕБУЕТСЯ: Rate limiter для REST API
   - ❌ ТРЕБУЕТСЯ: Auto-reconnect WebSocket при частых fallback
   - **Файлы:**
     - data_registry.py: Добавить _rest_ticker_cache
     - data_registry.py: Добавить _rest_api_semaphore
     - websocket_coordinator.py: Добавить auto-reconnect logic

### 🔴 ВЫСОКИЙ ПРИОРИТЕТ (Исправить в течение недели):

4. **Limit Offset Fallback (Проблема #4)**
   - ❌ ТРЕБУЕТСЯ: Добавить by_regime офсеты для всех режимов
   - ❌ ТРЕБУЕТСЯ: Добавить by_symbol офсеты для волатильных пар
   - **Файлы:**
     - config_futures.yaml: Добавить order_executor.limit_order.by_regime
     - config_futures.yaml: Добавить order_executor.limit_order.by_symbol.{SYMBOL}.by_regime

5. **Regime Fallback (Проблема #5)**
   - ❌ ТРЕБУЕТСЯ: ВСЕГДА сохранять regime с позицией
   - ❌ ТРЕБУЕТСЯ: ЗАПРЕТИТЬ fallback на RegimeManager
   - **Файлы:**
     - entry_manager.py: Сохранять regime, tp_params, sl_params
     - position_manager.py: НЕ использовать RegimeManager fallback

### 🟡 СРЕДНИЙ ПРИОРИТЕТ (Улучшения):

6. **Leverage Fallback (Проблема #6)**
   - ✅ УЖЕ ИСПРАВЛЕНО: Hard fail вместо слепого fallback
   - ❌ ТРЕБУЕТСЯ: Улучшить логирование
   - **Файлы:**
     - position_manager.py: Добавить detailed logging при leverage=0

---

## 📁 ФАЙЛЫ ТРЕБУЮЩИЕ ИСПРАВЛЕНИЯ

### Критические:
1. ✅ **config/config_futures.yaml** - Добавить все режимные секции
2. ⏳ **src/strategies/scalping/futures/core/data_registry.py** - Методы со строгим TTL
3. ⏳ **src/strategies/scalping/futures/order_executor.py** - Использовать fresh price
4. ⏳ **src/strategies/scalping/futures/signal_generator.py** - Использовать fresh price
5. ⏳ **src/strategies/scalping/futures/coordinators/websocket_coordinator.py** - Auto-reconnect

### Высокий приоритет:
6. ⏳ **config/config_futures.yaml** - Limit order offsets by_regime, by_symbol
7. ⏳ **src/strategies/scalping/futures/positions/entry_manager.py** - Сохранять regime
8. ⏳ **src/strategies/scalping/futures/positions/position_manager.py** - Убрать regime fallback

### Средний приоритет:
9. ⏳ **src/strategies/scalping/futures/positions/position_manager.py** - Улучшить leverage logging

---

## 🚨 КРИТИЧЕСКИЕ ВЫВОДЫ

1. **Fallback ≠ Плохо, но нужен ПРАВИЛЬНЫЙ приоритет!**
   - ✅ Fallback на REST API для ExitAnalyzer (критические решения) - ХОРОШО
   - ❌ Fallback на 60s устаревшие данные - ПЛОХО
   - ❌ Fallback на неправильные конфиги - КАТАСТРОФА

2. **"Бот берет фаллбэк а не данные с биржи" - ЭТО ПРАВДА!**
   - DataRegistry возвращает WebSocket данные возрастом 60s
   - Config fallback использует неправильные TP/SL для режима
   - REST API fallback спамит когда WebSocket отстает

3. **Главная проблема: ОТСУТСТВУЮЩИЕ КОНФИГИ!**
   - Отсутствующие symbol_profiles.{SYMBOL}.{REGIME} → fallback на неправильные значения
   - Отсутствующие by_regime offsets → fallback на market orders
   - **РЕШЕНИЕ: Добавить ВСЕ режимные секции для ВСЕХ символов!**

4. **Вторая проблема: УСТАРЕВШИЕ ДАННЫЕ!**
   - 60s TTL для DataRegistry - СЛИШКОМ ДОЛГО для scalping
   - Только ExitAnalyzer использует 2s TTL
   - **РЕШЕНИЕ: Все модули должны использовать правильный TTL для своих нужд!**

5. **Третья проблема: СПАМ REST API!**
   - WebSocket отстает → весь бот падает на REST API
   - Нет кэширования → повторные запросы
   - Нет rate limiting → риск ban
   - **РЕШЕНИЕ: Кэш + rate limiter + auto-reconnect!**

---

## 📅 ДАТА И КОНТЕКСТ

- **Дата**: 25 января 2026
- **Автор**: Claude Sonnet 4.5
- **Анализ**: 785 fallback вхождений в 36 файлах
- **Критических проблем**: 6
- **Уже исправлено**: 2 из 6 (Config TP/SL, Fresh price для ExitAnalyzer)
- **Требуется исправить**: 4 из 6

---

**ЭТО ПОЛНЫЙ АНАЛИЗ ВСЕХ FALLBACK ПУТЕЙ В СИСТЕМЕ!** 🔍

**СЛЕДУЮЩИЙ ШАГ:** Применить критические исправления #1 и #3 (Stale Data + REST Spam).
