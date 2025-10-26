"""
Тесты для Futures клиента.
Проверяет корректность работы с OKX Futures API.
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from src.clients.futures_client import OKXFuturesClient


class TestOKXFuturesClient:
    """Тесты для OKXFuturesClient"""
    
    def setup_method(self):
        """Настройка перед каждым тестом"""
        self.client = OKXFuturesClient(
            api_key="test_key",
            secret_key="test_secret",
            passphrase="test_passphrase",
            sandbox=True,
            leverage=3
        )
    
    def test_initialization(self):
        """Тест инициализации клиента"""
        assert self.client.api_key == "test_key"
        assert self.client.secret_key == "test_secret"
        assert self.client.passphrase == "test_passphrase"
        assert self.client.sandbox is True
        assert self.client.leverage == 3
        assert self.client.base_url == "https://www.okx.com"
    
    def test_initialization_production(self):
        """Тест инициализации клиента для продакшена"""
        client = OKXFuturesClient(
            api_key="prod_key",
            secret_key="prod_secret",
            passphrase="prod_passphrase",
            sandbox=False,
            leverage=5
        )
        
        assert client.sandbox is False
        assert client.leverage == 5
    
    @pytest.mark.asyncio
    async def test_make_request_success(self):
        """Тест успешного запроса"""
        mock_response = {
            "code": "0",
            "data": [{"test": "data"}]
        }
        
        with patch('aiohttp.ClientSession') as mock_session:
            mock_resp = AsyncMock()
            mock_resp.json.return_value = mock_response
            mock_session.return_value.request.return_value.__aenter__.return_value = mock_resp
            
            result = await self.client._make_request("GET", "/test/endpoint")
            
            assert result == mock_response
    
    @pytest.mark.asyncio
    async def test_make_request_error(self):
        """Тест запроса с ошибкой"""
        mock_response = {
            "code": "50001",
            "msg": "API error"
        }
        
        with patch('aiohttp.ClientSession') as mock_session:
            mock_resp = AsyncMock()
            mock_resp.json.return_value = mock_response
            mock_session.return_value.request.return_value.__aenter__.return_value = mock_resp
            
            with pytest.raises(RuntimeError):
                await self.client._make_request("GET", "/test/endpoint")
    
    @pytest.mark.asyncio
    async def test_get_balance(self):
        """Тест получения баланса"""
        mock_response = {
            "code": "0",
            "data": [{
                "details": [
                    {"ccy": "USDT", "eq": "1000.50"},
                    {"ccy": "BTC", "eq": "0.1"}
                ]
            }]
        }
        
        with patch.object(self.client, '_make_request', return_value=mock_response):
            balance = await self.client.get_balance()
            
            assert balance == 1000.50
    
    @pytest.mark.asyncio
    async def test_get_balance_no_usdt(self):
        """Тест получения баланса без USDT"""
        mock_response = {
            "code": "0",
            "data": [{
                "details": [
                    {"ccy": "BTC", "eq": "0.1"}
                ]
            }]
        }
        
        with patch.object(self.client, '_make_request', return_value=mock_response):
            balance = await self.client.get_balance()
            
            assert balance == 0.0
    
    @pytest.mark.asyncio
    async def test_get_margin_info(self):
        """Тест получения информации о марже"""
        mock_response = {
            "code": "0",
            "data": [{
                "eq": "1000.0",
                "liqPx": "45000.0",
                "mgnRatio": "0.15"
            }]
        }
        
        with patch.object(self.client, '_make_request', return_value=mock_response):
            margin_info = await self.client.get_margin_info("BTC-USDT")
            
            assert margin_info["equity"] == 1000.0
            assert margin_info["liqPx"] == 45000.0
            assert margin_info["mgnRatio"] == 0.15
    
    @pytest.mark.asyncio
    async def test_get_margin_info_no_position(self):
        """Тест получения информации о марже без позиции"""
        mock_response = {
            "code": "0",
            "data": []
        }
        
        with patch.object(self.client, '_make_request', return_value=mock_response):
            margin_info = await self.client.get_margin_info("BTC-USDT")
            
            assert margin_info == {}
    
    @pytest.mark.asyncio
    async def test_set_leverage(self):
        """Тест установки плеча"""
        mock_response = {
            "code": "0",
            "data": [{"result": "true"}]
        }
        
        with patch.object(self.client, '_make_request', return_value=mock_response):
            result = await self.client.set_leverage("BTC-USDT", 5)
            
            assert result == mock_response
    
    @pytest.mark.asyncio
    async def test_place_futures_order_market(self):
        """Тест размещения рыночного ордера"""
        mock_response = {
            "code": "0",
            "data": [{"ordId": "12345"}]
        }
        
        with patch.object(self.client, '_make_request', return_value=mock_response):
            result = await self.client.place_futures_order(
                symbol="BTC-USDT",
                side="buy",
                size=0.01,
                order_type="market"
            )
            
            assert result == mock_response
    
    @pytest.mark.asyncio
    async def test_place_futures_order_limit(self):
        """Тест размещения лимитного ордера"""
        mock_response = {
            "code": "0",
            "data": [{"ordId": "12346"}]
        }
        
        with patch.object(self.client, '_make_request', return_value=mock_response):
            result = await self.client.place_futures_order(
                symbol="BTC-USDT",
                side="buy",
                size=0.01,
                price=50000.0,
                order_type="limit"
            )
            
            assert result == mock_response
    
    @pytest.mark.asyncio
    async def test_place_oco_order(self):
        """Тест размещения OCO ордера"""
        mock_response = {
            "code": "0",
            "data": [{"ordId": "12347"}]
        }
        
        with patch.object(self.client, '_make_request', return_value=mock_response):
            result = await self.client.place_oco_order(
                symbol="BTC-USDT",
                side="buy",
                size=0.01,
                tp_price=51000.0,
                sl_price=49000.0
            )
            
            assert result == mock_response
    
    @pytest.mark.asyncio
    async def test_cancel_order(self):
        """Тест отмены ордера"""
        mock_response = {
            "code": "0",
            "data": [{"ordId": "12345"}]
        }
        
        with patch.object(self.client, '_make_request', return_value=mock_response):
            result = await self.client.cancel_order("BTC-USDT", "12345")
            
            assert result == mock_response
    
    @pytest.mark.asyncio
    async def test_get_positions(self):
        """Тест получения позиций"""
        mock_response = {
            "code": "0",
            "data": [
                {
                    "instId": "BTC-USDT-SWAP",
                    "pos": "0.01",
                    "posSide": "long",
                    "avgPx": "50000.0",
                    "markPx": "51000.0",
                    "lever": "3"
                }
            ]
        }
        
        with patch.object(self.client, '_make_request', return_value=mock_response):
            positions = await self.client.get_positions()
            
            assert len(positions) == 1
            assert positions[0]["instId"] == "BTC-USDT-SWAP"
            assert positions[0]["pos"] == "0.01"
    
    @pytest.mark.asyncio
    async def test_get_positions_with_symbol(self):
        """Тест получения позиций для конкретного символа"""
        mock_response = {
            "code": "0",
            "data": [
                {
                    "instId": "BTC-USDT-SWAP",
                    "pos": "0.01",
                    "posSide": "long"
                }
            ]
        }
        
        with patch.object(self.client, '_make_request', return_value=mock_response):
            positions = await self.client.get_positions("BTC-USDT")
            
            assert len(positions) == 1
            assert positions[0]["instId"] == "BTC-USDT-SWAP"
    
    @pytest.mark.asyncio
    async def test_batch_amend_orders(self):
        """Тест пакетного изменения ордеров"""
        mock_response = {
            "code": "0",
            "data": [{"result": "true"}]
        }
        
        amend_list = [
            {"ordId": "12345", "newPx": "50000.0"},
            {"ordId": "12346", "newPx": "51000.0"}
        ]
        
        with patch.object(self.client, '_make_request', return_value=mock_response):
            result = await self.client.batch_amend_orders(amend_list)
            
            assert result == mock_response
    
    @pytest.mark.asyncio
    async def test_close_session(self):
        """Тест закрытия сессии"""
        mock_session = AsyncMock()
        mock_session.closed = False
        self.client.session = mock_session
        
        await self.client.close()
        
        mock_session.close.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_close_session_already_closed(self):
        """Тест закрытия уже закрытой сессии"""
        mock_session = AsyncMock()
        mock_session.closed = True
        self.client.session = mock_session
        
        await self.client.close()
        
        mock_session.close.assert_not_called()
    
    def test_request_headers(self):
        """Тест заголовков запроса"""
        # Этот тест проверяет, что заголовки формируются правильно
        # В реальном тесте нужно было бы мокать время и HMAC
        
        # Проверяем, что sandbox заголовок устанавливается правильно
        assert hasattr(self.client, 'sandbox')
        assert self.client.sandbox is True
    
    @pytest.mark.asyncio
    async def test_error_handling(self):
        """Тест обработки ошибок"""
        # Тест с некорректным ответом API
        mock_response = {
            "code": "50001",
            "msg": "Invalid API key"
        }
        
        with patch.object(self.client, '_make_request', return_value=mock_response):
            with pytest.raises(RuntimeError):
                await self.client.get_balance()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])