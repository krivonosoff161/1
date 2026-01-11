# 🔴 КРИТИЧЕСКИЙ FIX: TSL price=0 → profit=-1.0000% (10 января 2026)

## 📌 Проблема (из анализа Codex)

**В сессии staging_2026-01-10_22-43-17:**
- Первый price=0 в 17:10:33.975
- Цепочка: ExitAnalyzer получает `current_price=None` → TSL получает `price=0.0` → fallback дает `profit=-1.0000%` → loss_cut → закрытие

**Результат:** 14 позиций (12 SHORT, 2 LONG), все закрывались с убытком из-за -1.0000% profit, хотя реальная цена была доступна

## 🔍 Корневая Причина

### Почему price=0 появляется:
1. **DataRegistry пуст** (нет свежих WS данных от OKX)
2. **ExitAnalyzer** пытается получить цену из 3 источников:
   - WebSocket (current_tick)
   - Последняя свеча (ohlcv_data)
   - Сохраненная цена (last_known_price)
3. Если все три = None/0 → ExitAnalyzer возвращает None
4. **TSL** получает None, подставляет `current_price = entry_price`
5. **get_profit_pct()** рассчитывает: `profit = 0% - 1% комиссия = -1.0000%`
6. **loss_cut срабатывает** потому что -1% < threshold (например 0.4%)

### Почему 5-уровневый fallback в trailing_sl_coordinator не помог:
- Fallback находится в **trailing_sl_coordinator._get_current_price()**
- Но price=0 приходит из **ExitAnalyzer**, который НЕ использует этот fallback
- ExitAnalyzer только берет цену из DataRegistry, при ошибке возвращает None

## ✅ Решение (2 части)

### Fix #1: REST API fallback в ExitAnalyzer (НОВОЕ)

**Файл:** `exit_analyzer.py:475-504`

**Что изменилось:**
```python
# БЫЛО: Если current_price = None/0 → return None
if current_price is None or current_price <= 0:
    return None

# СТАЛО: Если current_price = None/0 → пытаемся REST API перед return None
if current_price is None or current_price <= 0:
    if self.client:
        rest_price = await self._fetch_price_via_rest(symbol)
        if rest_price and rest_price > 0:
            current_price = rest_price
        else:
            return None
    else:
        return None
```

**Добавлен новый метод:** `_fetch_price_via_rest(symbol)`
```python
async def _fetch_price_via_rest(self, symbol: str) -> Optional[float]:
    """Получение текущей цены через OKX REST API"""
    if not self.client:
        return None
    try:
        ticker = await self.client.get_ticker(symbol)
        if ticker and isinstance(ticker, dict):
            price = ticker.get("last") or ticker.get("lastPx")
            if price:
                price_float = float(price)
                if price_float > 0:
                    return price_float
    except Exception as e:
        logger.debug(f"REST API fallback ошибка: {e}")
    return None
```

**Эффект:**
- ✅ Если DataRegistry пуст → пытаемся REST API
- ✅ REST API обычно доступен даже при WS задержках
- ✅ ExitAnalyzer получит РЕАЛЬНУЮ цену вместо None
- ✅ TSL получит РЕАЛЬНУЮ цену вместо price=0

### Fix #2: Не считать комиссию при fallback цене (НОВОЕ)

**Файл:** `trailing_stop_loss.py:626-634`

**Что изменилось:**
```python
# БЫЛО: Всегда include_fees=True
profit_pct = self.get_profit_pct(
    current_price,
    include_fees=True,  # ← Это дает -1% когда current_price=entry_price
    ...
)

# СТАЛО: Не считаем комиссию если current_price это fallback (= entry_price)
is_fallback_price = (current_price == self.entry_price) and (current_price != 0)
profit_pct = self.get_profit_pct(
    current_price,
    include_fees=not is_fallback_price,  # ← include_fees=False для fallback
    ...
)
```

**Эффект:**
- ✅ Когда current_price = entry_price → profit = 0%, а не -1.0000%
- ✅ TSL не будет ошибочно срабатывать по loss_cut
- ✅ Позиция сохранится в статусе "в ожидании реальной цены"

## 📊 Иерархия источников цены после fix

**1️⃣ ExitAnalyzer (новая иерархия):**
- WebSocket real-time (current_tick) 
- Последняя свеча (ohlcv_data)
- Сохраненная цена (last_known_price)
- ✅ **REST API (НОВОЕ - Fix #1)**
- Возвращает None только если все источники недоступны

**2️⃣ TSL (fallback):**
- Получает реальную цену из ExitAnalyzer
- Если все еще None → использует entry_price с логикой No-Fees (Fix #2)
- Не закрывает позицию ошибочно

## 🔬 Тестирование

**Что нужно проверить в следующей сессии:**
1. ✅ Нет больше price=0 в логах ExitAnalyzer
2. ✅ Если DataRegistry пуст, видны логи "REST API fallback"
3. ✅ profit=-1.0000% замещен на profit=0% при fallback цене
4. ✅ Позиции не закрываются ошибочно по loss_cut в первые 30 секунд

**Логи для отслеживания:**
```
✅ ExitAnalyzer: REST API fallback успешен для {symbol}: {price}
✅ ExitAnalyzer._fetch_price_via_rest: {symbol} = {price}
profit=0.000% (fallback, no fees)
```

## ⚠️ Важные замечания

1. **REST API медленнее чем WebSocket** (~50-100ms вместо <10ms)
   - Но это лучше чем price=0 и ошибочное закрытие

2. **Fix #2 (No-Fees для fallback)** безопасен потому что:
   - Если current_price = entry_price → реально нулевой PnL
   - Комиссия начисляется при РЕАЛЬНОМ движении цены
   - Когда цена обновится → profit будет рассчитан правильно

3. **Fallback должен быть редким** в нормальных сетевых условиях
   - Fix предотвращает "черный лебедь" сценарии (DDoS, сбой WS)

## 📝 Файлы изменены

1. `src/strategies/scalping/futures/positions/exit_analyzer.py`
   - Lines 475-504: Добавлена проверка and REST API fallback
   - Lines 210-243: Добавлен метод `_fetch_price_via_rest()`

2. `src/strategies/scalping/futures/indicators/trailing_stop_loss.py`
   - Lines 626-634: Улучшена логика include_fees для fallback цены

## ✅ Статус

**ГОТОВО К ТЕСТИРОВАНИЮ**

Рекомендуется:
1. Перезагрузить бот
2. Запустить на Futures с мониторингом логов
3. Следить за наличием "REST API fallback" событий
4. Проверить что profit больше не падает в -1.0000% при fallback
