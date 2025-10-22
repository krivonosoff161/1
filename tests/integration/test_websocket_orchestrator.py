"""
Integration тесты для WebSocket Orchestrator
"""

import pytest
import asyncio
from unittest.mock import Mock, patch, AsyncMock
from src.strategies.scalping.websocket_orchestrator import WebSocketScalpingOrchestrator, WebSocketTradingState
from src.config import BotConfig, APIConfig, ScalpingConfig, RiskConfig
from src.okx_client import OKXClient

class TestWebSocketTradingState:
    """Тесты для WebSocketTradingState"""
    
    def test_initialization(self):
        """Тест инициализации состояния торговли"""
        state = WebSocketTradingState()
        
        assert state.current_prices == {}
        assert state.last_update_time == {}
        assert state.is_processing is False
        assert state.last_signal_time == 0
        assert state.signal_cooldown == 1.0

@pytest.fixture
def mock_config():
    """Фикстура для тестовой конфигурации"""
    from src.config import APIConfig, ScalpingConfig, RiskConfig
    
    api_config = APIConfig(
        api_key="test_key",
        api_secret="test_secret", 
        passphrase="test_passphrase",
        sandbox=True
    )
    
    scalping_config = ScalpingConfig()
    risk_config = RiskConfig()
    
    return BotConfig(
        api=api_config,
        scalping=scalping_config,
        risk=risk_config,
        trading={
            "symbols": ["ETH-USDT", "BTC-USDT"],
            "base_currency": "USDT"
        }
    )

@pytest.fixture
def mock_okx_client():
    """Фикстура для мок OKX клиента"""
    client = Mock(spec=OKXClient)
    client.connect = AsyncMock()
    client.disconnect = AsyncMock()
    client.get_candles = AsyncMock(return_value=[
        ["1698000000000", "3850", "3860", "3840", "3851.16", "1000", "0", "0"],
        ["1698000060000", "3851", "3861", "3841", "3852.16", "1100", "0", "0"],
    ])
    return client

class TestWebSocketScalpingOrchestrator:
    """Тесты для WebSocketScalpingOrchestrator"""
    
    def test_initialization(self, mock_config, mock_okx_client):
        """Тест инициализации оркестратора"""
        orchestrator = WebSocketScalpingOrchestrator(mock_config, mock_okx_client)
        
        assert orchestrator.config == mock_config
        assert orchestrator.okx_client == mock_okx_client
        assert orchestrator.is_running is False
        assert orchestrator.websocket_manager is not None
        assert orchestrator.latency_monitor is not None
        assert orchestrator.indicators is not None
        assert orchestrator.arm is not None
        assert orchestrator.signal_generator is not None
        assert orchestrator.order_executor is not None
        assert orchestrator.position_manager is not None
        assert orchestrator.performance_tracker is not None
        assert orchestrator.risk_controller is not None
    
    def test_stats_initialization(self, mock_config, mock_okx_client):
        """Тест инициализации статистики"""
        orchestrator = WebSocketScalpingOrchestrator(mock_config, mock_okx_client)
        
        expected_stats = {
            "signals_generated": 0,
            "signals_processed": 0,
            "signals_rejected": 0,
            "websocket_errors": 0,
            "last_price_update": 0,
            "avg_latency": 0.0
        }
        
        for key, value in expected_stats.items():
            assert orchestrator.stats[key] == value
    
    @pytest.mark.asyncio
    async def test_start_success(self, mock_config, mock_okx_client):
        """Тест успешного запуска оркестратора"""
        orchestrator = WebSocketScalpingOrchestrator(mock_config, mock_okx_client)
        
        with patch.object(orchestrator.websocket_manager, 'connect', new_callable=AsyncMock) as mock_connect:
            with patch.object(orchestrator.websocket_manager, 'subscribe_ticker', new_callable=AsyncMock) as mock_sub_ticker:
                with patch.object(orchestrator.websocket_manager, 'subscribe_candles', new_callable=AsyncMock) as mock_sub_candles:
                    with patch.object(orchestrator.websocket_manager, 'start_listening', new_callable=AsyncMock) as mock_listen:
                        with patch.object(orchestrator, '_trading_loop', new_callable=AsyncMock) as mock_trading:
                            mock_connect.return_value = True
                            mock_sub_ticker.return_value = True
                            mock_sub_candles.return_value = True
                            
                            # Запускаем в отдельной задаче, чтобы не блокировать тест
                            task = asyncio.create_task(orchestrator.start())
                            
                            # Даем время на инициализацию
                            await asyncio.sleep(0.1)
                            
                            # Останавливаем
                            orchestrator.is_running = False
                            await task
                            
                            mock_connect.assert_called_once()
                            mock_sub_ticker.assert_called_once()
                            mock_sub_candles.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_start_connection_failure(self, mock_config, mock_okx_client):
        """Тест неудачного запуска из-за проблем с подключением"""
        orchestrator = WebSocketScalpingOrchestrator(mock_config, mock_okx_client)
        
        with patch.object(orchestrator.websocket_manager, 'connect', new_callable=AsyncMock) as mock_connect:
            mock_connect.return_value = False
            
            result = await orchestrator.start()
            
            assert result is False
            assert orchestrator.is_running is False
    
    @pytest.mark.asyncio
    async def test_stop(self, mock_config, mock_okx_client):
        """Тест остановки оркестратора"""
        orchestrator = WebSocketScalpingOrchestrator(mock_config, mock_okx_client)
        orchestrator.is_running = True
        
        with patch.object(orchestrator.websocket_manager, 'disconnect', new_callable=AsyncMock) as mock_disconnect:
            await orchestrator.stop()
            
            assert orchestrator.is_running is False
            mock_disconnect.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_process_symbol_no_data(self, mock_config, mock_okx_client):
        """Тест обработки символа без данных"""
        orchestrator = WebSocketScalpingOrchestrator(mock_config, mock_okx_client)
        
        # Символ отсутствует в current_prices
        await orchestrator._process_symbol("ETH-USDT")
        
        # Должен завершиться без ошибок
        assert True
    
    @pytest.mark.asyncio
    async def test_process_symbol_stale_data(self, mock_config, mock_okx_client):
        """Тест обработки символа со старыми данными"""
        orchestrator = WebSocketScalpingOrchestrator(mock_config, mock_okx_client)
        
        # Добавляем старые данные (старше 5 секунд)
        orchestrator.trading_state.current_prices["ETH-USDT"] = 3851.16
        orchestrator.trading_state.last_update_time["ETH-USDT"] = 0  # Очень старое время
        
        await orchestrator._process_symbol("ETH-USDT")
        
        # Должен завершиться без ошибок
        assert True
    
    @pytest.mark.asyncio
    async def test_process_symbol_processing_lock(self, mock_config, mock_okx_client):
        """Тест обработки символа с заблокированной обработкой"""
        orchestrator = WebSocketScalpingOrchestrator(mock_config, mock_okx_client)
        
        # Устанавливаем блокировку
        orchestrator.trading_state.is_processing = True
        orchestrator.trading_state.current_prices["ETH-USDT"] = 3851.16
        orchestrator.trading_state.last_update_time["ETH-USDT"] = 9999999999  # Будущее время
        
        await orchestrator._process_symbol("ETH-USDT")
        
        # Должен завершиться без ошибок
        assert True
    
    @pytest.mark.asyncio
    async def test_get_historical_data_success(self, mock_config, mock_okx_client):
        """Тест успешного получения исторических данных"""
        orchestrator = WebSocketScalpingOrchestrator(mock_config, mock_okx_client)
        
        candles = await orchestrator._get_historical_data("ETH-USDT")
        
        assert candles is not None
        assert len(candles) == 2
        mock_okx_client.get_candles.assert_called_once_with("ETH-USDT", "5m", 200)
    
    @pytest.mark.asyncio
    async def test_get_historical_data_failure(self, mock_config, mock_okx_client):
        """Тест неудачного получения исторических данных"""
        orchestrator = WebSocketScalpingOrchestrator(mock_config, mock_okx_client)
        
        # Настраиваем мок для выброса исключения
        mock_okx_client.get_candles.side_effect = Exception("API Error")
        
        candles = await orchestrator._get_historical_data("ETH-USDT")
        
        assert candles is None
    
    def test_calculate_indicators_success(self, mock_config, mock_okx_client):
        """Тест успешного расчета индикаторов"""
        orchestrator = WebSocketScalpingOrchestrator(mock_config, mock_okx_client)
        
        # Подготавливаем тестовые данные свечей
        candles = [
            ["1698000000000", "3850", "3860", "3840", "3851.16", "1000", "0", "0"],
            ["1698000060000", "3851", "3861", "3841", "3852.16", "1100", "0", "0"],
        ] * 30  # 60 свечей для расчета индикаторов
        
        indicators = orchestrator._calculate_indicators("ETH-USDT", candles)
        
        assert isinstance(indicators, dict)
        assert "sma_fast" in indicators
        assert "sma_slow" in indicators
        assert "ema_fast" in indicators
        assert "ema_slow" in indicators
        assert "rsi" in indicators
        assert "bb_upper" in indicators
        assert "bb_lower" in indicators
        assert "macd" in indicators
        assert "atr" in indicators
        assert "volume_ratio" in indicators
    
    def test_calculate_indicators_insufficient_data(self, mock_config, mock_okx_client):
        """Тест расчета индикаторов с недостаточными данными"""
        orchestrator = WebSocketScalpingOrchestrator(mock_config, mock_okx_client)
        
        # Недостаточно данных для расчета
        candles = [["1698000000000", "3850", "3860", "3840", "3851.16", "1000", "0", "0"]]
        
        indicators = orchestrator._calculate_indicators("ETH-USDT", candles)
        
        assert indicators == {}
    
    def test_calculate_indicators_error(self, mock_config, mock_okx_client):
        """Тест расчета индикаторов с ошибкой"""
        orchestrator = WebSocketScalpingOrchestrator(mock_config, mock_okx_client)
        
        # Некорректные данные
        candles = [["invalid", "data"]]
        
        indicators = orchestrator._calculate_indicators("ETH-USDT", candles)
        
        assert indicators == {}
    
    def test_on_price_update(self, mock_config, mock_okx_client):
        """Тест обработки обновления цены"""
        orchestrator = WebSocketScalpingOrchestrator(mock_config, mock_okx_client)
        
        from src.websocket_manager import PriceData
        
        price_data = PriceData(
            symbol="ETH-USDT",
            price=3851.16,
            timestamp=1698000000.0
        )
        
        orchestrator._on_price_update(price_data)
        
        assert orchestrator.trading_state.current_prices["ETH-USDT"] == 3851.16
        assert "ETH-USDT" in orchestrator.trading_state.last_update_time
        assert orchestrator.stats["last_price_update"] == 1698000000.0
    
    def test_on_websocket_error(self, mock_config, mock_okx_client):
        """Тест обработки ошибки WebSocket"""
        orchestrator = WebSocketScalpingOrchestrator(mock_config, mock_okx_client)
        
        error = Exception("WebSocket error")
        orchestrator._on_websocket_error(error)
        
        assert orchestrator.stats["websocket_errors"] == 1
    
    def test_on_latency_warning(self, mock_config, mock_okx_client):
        """Тест обработки предупреждения о латентности"""
        orchestrator = WebSocketScalpingOrchestrator(mock_config, mock_okx_client)
        
        orchestrator._on_latency_warning(150.0)
        
        # Должен завершиться без ошибок
        assert True
    
    def test_on_latency_critical(self, mock_config, mock_okx_client):
        """Тест обработки критической латентности"""
        orchestrator = WebSocketScalpingOrchestrator(mock_config, mock_okx_client)
        
        orchestrator._on_latency_critical(600.0)
        
        # Должен завершиться без ошибок
        assert True
    
    def test_update_stats(self, mock_config, mock_okx_client):
        """Тест обновления статистики"""
        orchestrator = WebSocketScalpingOrchestrator(mock_config, mock_okx_client)
        
        # Настраиваем мок для latency_monitor
        orchestrator.latency_monitor.get_average_latency = Mock(return_value=50.0)
        
        orchestrator._update_stats()
        
        assert orchestrator.stats["avg_latency"] == 50.0
    
    def test_get_stats(self, mock_config, mock_okx_client):
        """Тест получения статистики"""
        orchestrator = WebSocketScalpingOrchestrator(mock_config, mock_okx_client)
        
        stats = orchestrator.get_stats()
        
        assert "signals_generated" in stats
        assert "signals_processed" in stats
        assert "signals_rejected" in stats
        assert "websocket_errors" in stats
        assert "last_price_update" in stats
        assert "avg_latency" in stats
        assert "websocket_status" in stats
        assert "latency_stats" in stats
        assert "trading_state" in stats
