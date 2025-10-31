# ✅ ИСПРАВЛЕНИЕ WebSocket URL для Sandbox

**Дата:** 2025-10-31  
**Проблема:** Неправильные цены из-за использования production WebSocket в sandbox режиме

---

## 🐛 **ПРОБЛЕМА:**

WebSocket URL был захардкожен на production, даже когда пользователь в sandbox режиме:
```python
self.ws_manager = FuturesWebSocketManager(
    ws_url="wss://ws.okx.com:8443/ws/v5/public"  # ❌ Всегда production
)
```

Это приводило к тому, что:
- API запросы шли в sandbox (где цены могут отличаться)
- WebSocket данные приходили из production (реальные цены)
- Возникало расхождение в ценах

**Пример:** 
- BTC реальная цена: ~$111,000
- BTC в логах бота: ~$109,420 (это sandbox цена или старая цена)

---

## ✅ **ИСПРАВЛЕНИЕ:**

Добавил проверку sandbox режима и выбор правильного WebSocket URL:

```python
# OKX Sandbox WebSocket: wss://wspap.okx.com:8443/ws/v5/public
# OKX Production WebSocket: wss://ws.okx.com:8443/ws/v5/public
okx_config = config.get_okx_config()
if okx_config.sandbox:
    ws_url = "wss://wspap.okx.com:8443/ws/v5/public"  # Sandbox WebSocket
    logger.info("📡 Используется SANDBOX WebSocket для тестирования")
else:
    ws_url = "wss://ws.okx.com:8443/ws/v5/public"  # Production WebSocket
    logger.info("📡 Используется PRODUCTION WebSocket")

self.ws_manager = FuturesWebSocketManager(ws_url=ws_url)
```

---

## ✅ **ДОПОЛНИТЕЛЬНО:**

Также добавлена диагностика для проверки данных тикера:
```python
# Логируем все поля тикера для проверки
logger.debug(
    f"🔍 Диагностика {symbol}: "
    f"last={ticker.get('last', 'N/A')}, "
    f"bidPx={ticker.get('bidPx', 'N/A')}, "
    f"askPx={ticker.get('askPx', 'N/A')}, "
    f"instId={ticker.get('instId', 'N/A')}"
)
```

---

## ✅ **СТАТУС:**

Исправлено! Теперь WebSocket автоматически использует правильный URL в зависимости от sandbox режима.

**Примечание:** Sandbox цены могут отличаться от production, это нормально для тестового окружения.


