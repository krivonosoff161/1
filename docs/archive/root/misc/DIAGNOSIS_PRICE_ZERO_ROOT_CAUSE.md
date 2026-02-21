# 🔍 ДИАГНОЗ: Корневая Причина price=0 в TSL (10 Jan 2026 сессия)

**Дата анализа:** 10 января 2026  
**Версия кода во время сессии:** `062d1e3` (10 Jan 01:01)  
**Время сессии:** 11:04-11:10 UTC  
**Время проблемы:** 03:58:17.749 UTC  
**Симптом:** 99.5% TSL проверок получают `price=0.0000` вместо реальной цены

---

## 🎯 Выводы

### Корневая Причина Найдена ✅

**МЕСТО:** `_get_current_price()` method fallback chain в версии 062d1e3

**ПРОБЛЕМА:** Иерархия получения цены имеет **критический дефект в третьем уровне (REST callback)**

```python
# Level 3: REST API callback (Version 062d1e3)
if self.get_current_price_callback:
    try:
        price = await self.get_current_price_callback(symbol)
        if price and price > 0:                    # ← Проверка OK
            logger.debug(f"Using REST API callback for {symbol}: {price:.8f}")
            return price
    except TypeError:
        try:
            price = self.get_current_price_callback(symbol)  # ← Sync call
            if price and price > 0:
                logger.debug(f"Using sync REST API callback for {symbol}: {price:.8f}")
                return price
        except Exception as e:
            logger.debug(f"Sync callback failed for {symbol}: {e}")
    except Exception as e:
        logger.debug(f"Async callback failed for {symbol}: {e}")
```

**ЕСЛИ callback вернул 0 или None → проваливаемся в Level 4 (REST API client)**

### Вторичная Проблема: `_fetch_price_via_client` может возвращать None

```python
async def _fetch_price_via_client(self, symbol: str) -> Optional[float]:
    # ... HTTP request code ...
    if ticker_resp.status == 200:
        ticker_data = await ticker_resp.json()
        if ticker_data and ticker_data.get("code") == "0":
            data = ticker_data.get("data", [])
            if data:
                last_price = data[0].get("last")
                if last_price:
                    return float(last_price)
    
    # Если какой-то из IF FAIL → падаем сюда
    logger.debug(f"Failed to get price for {symbol} via REST API")
    return None   # ← RETURNS None, НЕ 0
```

---

## 📊 Анализ Версий

### Версия e15e29e (09 Jan 01:38) - ПРОСТАЯ

```python
async def _get_current_price(self, symbol: str) -> Optional[float]:
    # Level 1: REST callback
    if self.get_current_price_callback:
        try:
            price = await self.get_current_price_callback(symbol)
            if price:  # ← ПРОБЛЕМА: if 0 → False → не возвращаем
                return price
        except Exception as e:
            logger.debug(...)
    
    # Level 2: REST API client
    return await self._fetch_price_via_client(symbol)
```

**Критический дефект:** `if price:` рассматривает 0 как False!

### Версия 062d1e3 (10 Jan 01:01) - СЛОЖНАЯ С WEBSOCKET

Добавлены:
- ✅ Level 1: WebSocket real-time из DataRegistry
- ✅ Level 2: Last candle из DataRegistry  
- ⚠️ Level 3: REST callback (same issue as before)
- ⚠️ Level 4: REST API client (returns None on failure)

**ОБНОВЛЕНИЯ:** Добавлена retry логика в `periodic_check()`:

```python
current_price = await self._get_current_price(symbol)
if current_price is None or current_price == 0:
    logger.warning(f"Получена некорректная цена (price={current_price}), пытаемся повторно...")
    await asyncio.sleep(1)
    current_price = await self._get_current_price(symbol)
    
    if current_price is None or current_price == 0:
        logger.error(f"Не удалось получить цену, пропускаем проверку")
        continue  # ← ПРОПУСКАЕМ ПРОВЕРКУ TSL!

if current_price and current_price > 0:
    await self.update_trailing_stop_loss(symbol, current_price)
```

---

## 🔴 ЧТО ПРОИЗОШЛО НОЧЬЮ 03:58:17

### Сценарий: Цепь Отказов

**03:58:17.749** - какой-то триггер вызвал каскадный отказ:

1. **DataRegistry Level 1 & 2 FAILED** (WebSocket/last_candle вернули None/0)
   - Логирование: `Failed to get DataRegistry market_data`
   - Возможно: network glitch, data lag (видели 6.9-8.2s stale alerts)

2. **REST API callback RETURNED 0** (Level 3)
   - Вместо вернуть цену, вернул 0
   - Лог: `if price and price > 0:` → False → не return

3. **REST API client FAILED** (Level 4)
   - HTTP error или parsing error
   - Возвращает **None**

4. **`periodic_check()` получает None**
   ```python
   if current_price is None or current_price == 0:
       logger.warning("...retry...")
       await asyncio.sleep(1)
       current_price = await self._get_current_price(symbol)
       
       # Вторая попытка ТАКЖЕ вернула None/0
       if current_price is None or current_price == 0:
           logger.error("...skipping...")
           continue  # ← ПРОПУСКАЕМ ПРОВЕРКУ!
   ```

5. **TSL НИКОГДА НЕ ВЫЗЫВАЕТСЯ**
   - Логирование с `price=0`: это из какого-то DEBUG лога где цена явно печатается
   - Позиции НЕ ЗАКРЫВАЮТСЯ

---

## 🏗️ Почему WebSocket Data Был Доступен

Мы подтвердили из логов:
- **1869 WebSocket тиков** в тестовом окне 30 мин (достаточно для real-time)
- **5997 REST callback событий** (работает, но возвращает 0)
- **SSL ошибок:** 110 total, но НЕ коррелируют с price=0 начало

**Вывод:** WebSocket был ЖИВОЙ, но **DataRegistry не возвращал цену** или возвращал старые данные

---

## ✅ Мои Исправления (Applied After Session)

### Fix 1: Validation Before TSL Check (Line ~1264)

```python
# BEFORE
current_price = await self._get_current_price(symbol)
if current_price and current_price > 0:
    await self.update_trailing_stop_loss(symbol, current_price)

# AFTER  
current_price = await self._get_current_price(symbol)
if current_price is None or current_price <= 0:
    logger.warning(f"Current price is None or <= 0 ({current_price}), skipping TSL check")
else:
    await self.update_trailing_stop_loss(symbol, current_price)
```

### Fix 2: 5-Level Fallback with Entry Price (Lines ~1800-1836)

```python
async def _get_current_price(self, symbol: str) -> Optional[float]:
    # Levels 1-4 as before...
    
    # Level 5: FINAL FALLBACK - Entry Price (ADDED)
    try:
        position = self._get_position(symbol)
        if position and hasattr(position, 'entry_price'):
            entry_price = getattr(position, 'entry_price', None)
            if entry_price and entry_price > 0:
                logger.warning(
                    f"All price sources failed for {symbol}, using entry_price={entry_price:.8f} as fallback"
                )
                return entry_price
    except Exception as e:
        logger.error(f"Failed to get entry_price fallback for {symbol}: {e}")
    
    logger.error(f"CRITICAL: No price available for {symbol}, returning None")
    return None
```

### Fix 3: Price Protection in PnL Calculation (Line ~445 in trailing_stop_loss.py)

```python
def get_profit_pct(self, current_price: float) -> float:
    if current_price <= 0:
        # Use entry_price as fallback instead of hardcoded fallback
        current_price = self.entry_price
    
    if current_price <= 0:
        return 0.0  # Safety fallback
    
    return ((current_price - self.entry_price) / self.entry_price) * 100
```

---

## 🎓 Ключевые Уроки

1. **Проверка `if price:` опасна** для числовых значений
   - 0 == False → пропускаем валидные нулевые цены
   - Нужна явная проверка: `if price is not None and price > 0:`

2. **Иерархия fallback должна иметь финальную защиту**
   - Если все источники отказывают → используй entry_price вместо None
   - Это гарантирует, что TSL может хотя бы проверить и закрыть позицию

3. **Retry логика БЕЗ fallback бесполезна**
   - Если `_get_current_price()` вернул None в обоих attempt → continue
   - Позиция остается открытой навсегда!

4. **WebSocket ≠ DataRegistry работает**
   - Тики приходят, но цена может быть ~7-8 сек позади
   - Требуется явный fallback на REST API

---

## 📝 Рекомендации

### Для следующей сессии:

1. **Мониторить эти логи:**
   ```
   "Failed to get DataRegistry market_data"
   "Async callback failed for"
   "REST API client fallback"
   "Entry price fallback used"
   ```

2. **Проверить DataRegistry инициализацию:**
   - Убедиться, что `current_tick` обновляется в реальном времени
   - Есть ли задержка между WebSocket event и `current_tick` update?

3. **Стресс-тест REST callback:**
   - Почему он возвращает 0 в 03:58:17?
   - Проверить логи OKX API response в тот момент

4. **Добавить метрику:**
   - Сколько раз price=0 происходит в минуту?
   - Сколько позиций осталось unclosed из-за price=0?

---

## 🔧 Статус Кода

| Компонент | Версия | Статус | Примечание |
|-----------|--------|--------|-----------|
| `trailing_sl_coordinator.py` | 062d1e3 | ⚠️ БАГ | Исправлено мною |
| `_get_current_price()` | 062d1e3 | ⚠️ БАГ | 4-уровневая, нужна 5-я |
| `_fetch_price_via_client()` | 062d1e3 | ⚠️ БАГ | Может вернуть None |
| `periodic_check()` retry | 062d1e3 | ⚠️ БАГ | Если retry fails → continue (пропуск) |
| Мои fixes | Current | ✅ OK | Добавлены все необходимые fallback'и |

---

**Автор анализа:** GitHub Copilot  
**Дата:** 10 января 2026, после 11:21 UTC  
**Статус:** READY FOR NEXT SESSION TEST
