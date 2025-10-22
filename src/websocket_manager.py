"""
WebSocket Manager для OKX Trading Bot
Обеспечивает real-time подключение к OKX WebSocket API
"""

import asyncio
import json
import logging
import time
from typing import Dict, List, Optional, Callable, Any
import websockets
from websockets.exceptions import ConnectionClosed, WebSocketException
import threading
from dataclasses import dataclass
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

@dataclass
class WebSocketConfig:
    """Конфигурация WebSocket соединения"""
    url: str = "wss://ws.okx.com:8443/ws/v5/public"
    private_url: str = "wss://ws.okx.com:8443/ws/v5/private"
    ping_interval: int = 20
    ping_timeout: int = 10
    close_timeout: int = 10
    max_size: int = 2**20  # 1MB
    reconnect_interval: int = 5
    max_reconnect_attempts: int = 10

@dataclass
class PriceData:
    """Данные о цене"""
    symbol: str
    price: float
    timestamp: float
    volume: float = 0.0
    bid: float = 0.0
    ask: float = 0.0

@dataclass
class OrderUpdate:
    """Обновление ордера"""
    order_id: str
    symbol: str
    side: str
    status: str
    price: float
    quantity: float
    timestamp: float

class WebSocketPriceManager:
    """Менеджер WebSocket для получения цен в реальном времени"""
    
    def __init__(self, config: WebSocketConfig):
        self.config = config
        self.websocket = None
        self.is_connected = False
        self.is_running = False
        self.subscriptions = set()
        self.price_callbacks: List[Callable[[PriceData], None]] = []
        self.error_callbacks: List[Callable[[Exception], None]] = []
        self.latency_data = []
        self.last_ping_time = 0
        self.reconnect_attempts = 0
        self._lock = threading.Lock()
        
    async def connect(self) -> bool:
        """Подключение к WebSocket"""
        try:
            logger.info("🔌 Connecting to OKX WebSocket...")
            self.websocket = await websockets.connect(
                self.config.url,
                ping_interval=self.config.ping_interval,
                ping_timeout=self.config.ping_timeout,
                close_timeout=self.config.close_timeout,
                max_size=self.config.max_size
            )
            self.is_connected = True
            self.reconnect_attempts = 0
            logger.info("✅ WebSocket connected successfully")
            return True
            
        except Exception as e:
            logger.error(f"❌ WebSocket connection failed: {e}")
            return False
    
    async def disconnect(self):
        """Отключение от WebSocket"""
        self.is_running = False
        if self.websocket:
            await self.websocket.close()
            self.is_connected = False
            logger.info("🔌 WebSocket disconnected")
    
    async def subscribe_ticker(self, symbols: List[str]):
        """Подписка на тикеры"""
        if not self.is_connected:
            logger.error("❌ WebSocket not connected")
            return False
            
        try:
            subscription = {
                "op": "subscribe",
                "args": [{"channel": "tickers", "instId": symbol} for symbol in symbols]
            }
            
            await self.websocket.send(json.dumps(subscription))
            self.subscriptions.update(symbols)
            logger.info(f"📡 Subscribed to tickers: {symbols}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Subscription failed: {e}")
            return False
    
    async def subscribe_candles(self, symbols: List[str], timeframe: str = "5m"):
        """Подписка на свечи"""
        if not self.is_connected:
            logger.error("❌ WebSocket not connected")
            return False
            
        try:
            subscription = {
                "op": "subscribe",
                "args": [{"channel": "candle" + timeframe, "instId": symbol} for symbol in symbols]
            }
            
            await self.websocket.send(json.dumps(subscription))
            logger.info(f"📊 Subscribed to candles {timeframe}: {symbols}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Candle subscription failed: {e}")
            return False
    
    def add_price_callback(self, callback: Callable[[PriceData], None]):
        """Добавление callback для обработки цен"""
        self.price_callbacks.append(callback)
    
    def add_error_callback(self, callback: Callable[[Exception], None]):
        """Добавление callback для обработки ошибок"""
        self.error_callbacks.append(callback)
    
    async def start_listening(self):
        """Запуск прослушивания WebSocket"""
        if not self.is_connected:
            logger.error("❌ WebSocket not connected")
            return
            
        self.is_running = True
        logger.info("🎧 Starting WebSocket listener...")
        
        try:
            async for message in self.websocket:
                if not self.is_running:
                    break
                    
                try:
                    data = json.loads(message)
                    await self._handle_message(data)
                except json.JSONDecodeError as e:
                    logger.error(f"❌ JSON decode error: {e}")
                except Exception as e:
                    logger.error(f"❌ Message handling error: {e}")
                    
        except ConnectionClosed:
            logger.warning("⚠️ WebSocket connection closed")
            await self._handle_reconnect()
        except WebSocketException as e:
            logger.error(f"❌ WebSocket error: {e}")
            await self._handle_reconnect()
        except Exception as e:
            logger.error(f"❌ Unexpected error: {e}")
            for callback in self.error_callbacks:
                try:
                    callback(e)
                except Exception as cb_e:
                    logger.error(f"❌ Callback error: {cb_e}")
    
    async def _handle_message(self, data: Dict[str, Any]):
        """Обработка входящих сообщений"""
        if "data" in data:
            for item in data["data"]:
                if "arg" in item and "data" in item:
                    channel = item["arg"].get("channel", "")
                    inst_id = item["arg"].get("instId", "")
                    
                    if channel == "tickers":
                        await self._handle_ticker_data(inst_id, item["data"])
                    elif channel.startswith("candle"):
                        await self._handle_candle_data(inst_id, item["data"])
    
    async def _handle_ticker_data(self, symbol: str, data: List[Dict]):
        """Обработка данных тикера"""
        if not data:
            return
            
        ticker = data[0]
        try:
            price_data = PriceData(
                symbol=symbol,
                price=float(ticker.get("last", 0)),
                timestamp=float(ticker.get("ts", 0)) / 1000,
                volume=float(ticker.get("vol24h", 0)),
                bid=float(ticker.get("bidPx", 0)),
                ask=float(ticker.get("askPx", 0))
            )
            
            # Вызов callbacks
            for callback in self.price_callbacks:
                try:
                    callback(price_data)
                except Exception as e:
                    logger.error(f"❌ Price callback error: {e}")
                    
        except (ValueError, KeyError) as e:
            logger.error(f"❌ Ticker data parsing error: {e}")
    
    async def _handle_candle_data(self, symbol: str, data: List[Dict]):
        """Обработка данных свечей"""
        if not data:
            return
            
        candle = data[0]
        try:
            # Для свечей создаем PriceData с ценой закрытия
            price_data = PriceData(
                symbol=symbol,
                price=float(candle[4]),  # Цена закрытия
                timestamp=float(candle[0]) / 1000,
                volume=float(candle[5])
            )
            
            # Вызов callbacks
            for callback in self.price_callbacks:
                try:
                    callback(price_data)
                except Exception as e:
                    logger.error(f"❌ Candle callback error: {e}")
                    
        except (ValueError, IndexError) as e:
            logger.error(f"❌ Candle data parsing error: {e}")
    
    async def _handle_reconnect(self):
        """Обработка переподключения"""
        if self.reconnect_attempts >= self.config.max_reconnect_attempts:
            logger.error("❌ Max reconnection attempts reached")
            self.is_running = False
            return
            
        self.reconnect_attempts += 1
        logger.info(f"🔄 Reconnecting... attempt {self.reconnect_attempts}")
        
        await asyncio.sleep(self.config.reconnect_interval)
        
        if await self.connect():
            # Восстанавливаем подписки
            if self.subscriptions:
                await self.subscribe_ticker(list(self.subscriptions))
            await self.start_listening()
    
    def get_latency(self) -> float:
        """Получение текущей латентности"""
        if not self.latency_data:
            return 0.0
        return sum(self.latency_data) / len(self.latency_data)
    
    def get_connection_status(self) -> Dict[str, Any]:
        """Получение статуса соединения"""
        return {
            "connected": self.is_connected,
            "running": self.is_running,
            "subscriptions": list(self.subscriptions),
            "latency": self.get_latency(),
            "reconnect_attempts": self.reconnect_attempts
        }

class LatencyMonitor:
    """Монитор латентности WebSocket"""
    
    def __init__(self, max_samples: int = 100):
        self.max_samples = max_samples
        self.latency_samples = []
        self.last_ping_time = 0
        self._lock = threading.Lock()
    
    def record_ping(self):
        """Запись времени ping"""
        with self._lock:
            self.last_ping_time = time.time()
    
    def record_pong(self):
        """Запись времени pong и расчет латентности"""
        with self._lock:
            if self.last_ping_time > 0:
                latency = (time.time() - self.last_ping_time) * 1000  # в миллисекундах
                self.latency_samples.append(latency)
                
                # Ограничиваем количество образцов
                if len(self.latency_samples) > self.max_samples:
                    self.latency_samples.pop(0)
                
                self.last_ping_time = 0
    
    def get_average_latency(self) -> float:
        """Получение средней латентности"""
        with self._lock:
            if not self.latency_samples:
                return 0.0
            return sum(self.latency_samples) / len(self.latency_samples)
    
    def get_max_latency(self) -> float:
        """Получение максимальной латентности"""
        with self._lock:
            if not self.latency_samples:
                return 0.0
            return max(self.latency_samples)
    
    def get_latency_stats(self) -> Dict[str, float]:
        """Получение статистики латентности"""
        with self._lock:
            if not self.latency_samples:
                return {"avg": 0.0, "max": 0.0, "min": 0.0, "count": 0}
            
            return {
                "avg": sum(self.latency_samples) / len(self.latency_samples),
                "max": max(self.latency_samples),
                "min": min(self.latency_samples),
                "count": len(self.latency_samples)
            }

class EnhancedLatencyMonitor(LatencyMonitor):
    """Расширенный монитор латентности с реакцией на задержки"""
    
    def __init__(self, max_samples: int = 100, warning_threshold: float = 100.0, critical_threshold: float = 500.0):
        super().__init__(max_samples)
        self.warning_threshold = warning_threshold
        self.critical_threshold = critical_threshold
        self.warning_callbacks = []
        self.critical_callbacks = []
    
    def add_warning_callback(self, callback: Callable[[float], None]):
        """Добавление callback для предупреждений о латентности"""
        self.warning_callbacks.append(callback)
    
    def add_critical_callback(self, callback: Callable[[float], None]):
        """Добавление callback для критических задержек"""
        self.critical_callbacks.append(callback)
    
    def record_pong(self):
        """Запись pong с проверкой латентности"""
        super().record_pong()
        
        current_latency = self.get_average_latency()
        
        if current_latency > self.critical_threshold:
            logger.warning(f"🚨 CRITICAL LATENCY: {current_latency:.2f}ms")
            for callback in self.critical_callbacks:
                try:
                    callback(current_latency)
                except Exception as e:
                    logger.error(f"❌ Critical callback error: {e}")
        elif current_latency > self.warning_threshold:
            logger.warning(f"⚠️ HIGH LATENCY: {current_latency:.2f}ms")
            for callback in self.warning_callbacks:
                try:
                    callback(current_latency)
                except Exception as e:
                    logger.error(f"❌ Warning callback error: {e}")

# Глобальные экземпляры для использования в других модулях
websocket_manager = None
latency_monitor = None

def initialize_websocket(config: WebSocketConfig = None) -> WebSocketPriceManager:
    """Инициализация WebSocket менеджера"""
    global websocket_manager, latency_monitor
    
    if config is None:
        config = WebSocketConfig()
    
    websocket_manager = WebSocketPriceManager(config)
    latency_monitor = EnhancedLatencyMonitor()
    
    return websocket_manager

def get_websocket_manager() -> Optional[WebSocketPriceManager]:
    """Получение глобального WebSocket менеджера"""
    return websocket_manager

def get_latency_monitor() -> Optional[EnhancedLatencyMonitor]:
    """Получение глобального монитора латентности"""
    return latency_monitor

