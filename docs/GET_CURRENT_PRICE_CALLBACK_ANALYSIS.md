# 🔍 `get_current_price_callback` Analysis - Complete Chain

## 📌 Quick Summary

The `get_current_price_callback` passed to `TrailingSLCoordinator` is a **fallback mechanism that makes HTTP REST API calls to OKX public endpoint** to fetch the latest price when WebSocket is not available.

---

## 1️⃣ Where It's Set - TrailingSLCoordinator Creation

**File:** [src/strategies/scalping/futures/orchestrator.py](src/strategies/scalping/futures/orchestrator.py#L505-L522)

```python
self.trailing_sl_coordinator = TrailingSLCoordinator(
    config_manager=self.config_manager,
    debug_logger=self.debug_logger,
    signal_generator=self.signal_generator,
    client=self.client,
    scalping_config=self.scalping_config,
    get_position_callback=lambda sym: self.active_positions.get(sym, {}),
    close_position_callback=self._close_position,
    get_current_price_callback=self._get_current_price_fallback,  # ✅ THIS ONE
    active_positions_ref=self.active_positions,
    fast_adx=self.fast_adx,
    position_manager=self.position_manager,
    order_flow=self.order_flow,
    exit_analyzer=self.exit_analyzer,
)
# ...
logger.info("✅ TrailingSLCoordinator инициализирован в orchestrator")
```

---

## 2️⃣ Callback Function Implementation - Orchestrator Level

**File:** [src/strategies/scalping/futures/orchestrator.py](src/strategies/scalping/futures/orchestrator.py#L3947-L3963)

```python
async def _get_current_price_fallback(self, symbol: str) -> Optional[float]:
    """
    Получение текущей цены через REST API (fallback если WebSocket не отвечает).

    Делегирует вызов WebSocketCoordinator.

    Args:
        symbol: Символ (например, BTC-USDT)

    Returns:
        Текущая цена или None если не удалось получить
    """
    if hasattr(self, "websocket_coordinator") and self.websocket_coordinator:
        return await self.websocket_coordinator.get_current_price_fallback(symbol)
    # Fallback для случая, когда координатор еще не инициализирован
    return None
```

**⚠️ Key Point:** This is a **delegation function** - it doesn't fetch the price itself, it delegates to `websocket_coordinator.get_current_price_fallback()`.

---

## 3️⃣ Actual Implementation - WebSocket Coordinator

**File:** [src/strategies/scalping/futures/coordinators/websocket_coordinator.py](src/strategies/scalping/futures/coordinators/websocket_coordinator.py#L1163-L1222)

```python
async def get_current_price_fallback(self, symbol: str) -> Optional[float]:
    """
    Получение текущей цены через REST API (fallback если WebSocket не отвечает).

    Args:
        symbol: Символ (например, BTC-USDT)

    Returns:
        Текущая цена или None если не удалось получить
    """
    try:
        # Используем прямой HTTP запрос для публичного endpoint без авторизации
        import aiohttp

        inst_id = f"{symbol}-SWAP"

        # Правильный endpoint для публичного тикера
        base_url = "https://www.okx.com"
        ticker_url = f"{base_url}/api/v5/market/ticker?instId={inst_id}"

        # Создаем временную сессию если нужно
        session = (
            self.client.session
            if self.client
            and hasattr(self.client, "session")
            and self.client.session
            and not self.client.session.closed
            else None
        )
        if not session:
            session = aiohttp.ClientSession()
            close_session = True
        else:
            close_session = False

        try:
            async with session.get(ticker_url) as ticker_resp:
                if ticker_resp.status == 200:
                    ticker_data = await ticker_resp.json()
                    if ticker_data and ticker_data.get("code") == "0":
                        data = ticker_data.get("data", [])
                        if data and len(data) > 0:
                            last_price = data[0].get("last")
                            if last_price:
                                return float(last_price)
                else:
                    logger.debug(
                        f"⚠️ Не удалось получить цену для {symbol}: HTTP {ticker_resp.status}"
                    )
        finally:
            if close_session and session:
                await session.close()

        logger.debug(f"⚠️ Не удалось получить цену для {symbol} через REST API")
        return None

    except Exception as e:
        logger.debug(f"⚠️ Ошибка получения цены для {symbol}: {e}")
```

---

## 📊 Data Source Analysis

### What source does it use?

**REST API HTTP Call to OKX Public Endpoint**

- **Endpoint:** `https://www.okx.com/api/v5/market/ticker?instId={symbol}-SWAP`
- **No Authentication:** Uses public endpoint, no API keys needed
- **Data Extracted:** `data[0].get("last")` - the last traded price
- **Format:** Float conversion from JSON string

### Flow:

```
TrailingSLCoordinator.execute_trailing_sl()
  ↓
calls get_current_price_callback(symbol)
  ↓
orchestrator._get_current_price_fallback(symbol)
  ↓
websocket_coordinator.get_current_price_fallback(symbol)
  ↓
HTTP GET https://www.okx.com/api/v5/market/ticker?instId=BTC-USDT-SWAP
  ↓
Parse response JSON: data[0]["last"] → float
  ↓
Return price (or None on error)
```

---

## 🔗 Session Management

The function intelligently reuses existing session if available:

```python
session = (
    self.client.session              # Try to reuse existing client session
    if self.client
    and hasattr(self.client, "session")
    and self.client.session
    and not self.client.session.closed
    else None
)

if not session:
    session = aiohttp.ClientSession()  # Create temporary session
    close_session = True               # Will close after use
else:
    close_session = False              # Don't close client's session
```

---

## ⚠️ Error Handling

1. **HTTP Error:** Logs debug message with HTTP status code
2. **JSON Parse Error:** Caught in exception handler
3. **No Session:** Falls back to `None`
4. **All Exceptions:** Logged at DEBUG level and returns `None`

Returns `None` (not throws) on any failure.

---

## 💡 When Is This Used?

The callback is called from **TrailingSLCoordinator** in these scenarios:

**File:** [src/strategies/scalping/futures/coordinators/websocket_coordinator.py](src/strategies/scalping/futures/coordinators/websocket_coordinator.py#L972)

```python
current_price = await self.get_current_price_fallback(symbol)
```

This is used when:
1. **WebSocket price updates are not available or stale**
2. **Real-time trailing stop-loss needs current price**
3. **Fallback mechanism ensures orders aren't placed with stale prices**

---

## 📋 Summary Table

| Aspect | Value |
|--------|-------|
| **Function Name** | `_get_current_price_fallback` (in orchestrator) |
| **Passed To** | `TrailingSLCoordinator` constructor |
| **Actual Source** | `WebSocketCoordinator.get_current_price_fallback()` |
| **Data Source** | REST API HTTP call (NOT ohlcv_data or current_tick) |
| **Endpoint** | `https://www.okx.com/api/v5/market/ticker?instId={symbol}-SWAP` |
| **Price Field** | `data[0].get("last")` from JSON response |
| **Returns** | `Optional[float]` - the last traded price or None |
| **Error Behavior** | Returns None, logs at DEBUG level |
| **Session Type** | Reuses client session if available, creates temporary if needed |

