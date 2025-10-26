"""
Liquidation Guard для Futures торговли.

Основные функции:
- Мониторинг маржи в реальном времени
- Автоматическое закрытие позиций при риске ликвидации
- Предупреждения о рисках
- Защита от катастрофических потерь
"""

import asyncio
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
from loguru import logger

from .margin_calculator import MarginCalculator


class LiquidationGuard:
    """
    Защита от ликвидации для Futures торговли
    
    Функции:
    - Мониторинг маржи в реальном времени
    - Автоматическое закрытие позиций
    - Предупреждения о рисках
    - Интеграция с MarginCalculator
    """
    
    def __init__(self, 
                 margin_calculator: MarginCalculator,
                 warning_threshold: float = 1.8,
                 danger_threshold: float = 1.3,
                 critical_threshold: float = 1.1,
                 auto_close_threshold: float = 1.05):
        """
        Инициализация Liquidation Guard
        
        Args:
            margin_calculator: Калькулятор маржи
            warning_threshold: Порог предупреждения (180%)
            danger_threshold: Порог опасности (130%)
            critical_threshold: Порог критичности (110%)
            auto_close_threshold: Порог автозакрытия (105%)
        """
        self.margin_calculator = margin_calculator
        self.warning_threshold = warning_threshold
        self.danger_threshold = danger_threshold
        self.critical_threshold = critical_threshold
        self.auto_close_threshold = auto_close_threshold
        
        # Состояние мониторинга
        self.is_monitoring = False
        self.monitoring_task = None
        self.last_warning_time = {}
        
        logger.info(f"LiquidationGuard инициализирован: warning={warning_threshold:.1f}, "
                   f"danger={danger_threshold:.1f}, critical={critical_threshold:.1f}, "
                   f"auto_close={auto_close_threshold:.1f}")
    
    async def start_monitoring(self, 
                             client, 
                             check_interval: float = 5.0,
                             callback: Optional[callable] = None):
        """
        Запуск мониторинга маржи
        
        Args:
            client: Futures клиент
            check_interval: Интервал проверки (секунды)
            callback: Функция обратного вызова для уведомлений
        """
        if self.is_monitoring:
            logger.warning("Мониторинг уже запущен")
            return
        
        self.is_monitoring = True
        logger.info(f"Запуск мониторинга ликвидации (интервал: {check_interval}с)")
        
        self.monitoring_task = asyncio.create_task(
            self._monitoring_loop(client, check_interval, callback)
        )
    
    async def stop_monitoring(self):
        """Остановка мониторинга"""
        if not self.is_monitoring:
            return
        
        self.is_monitoring = False
        if self.monitoring_task:
            self.monitoring_task.cancel()
            try:
                await self.monitoring_task
            except asyncio.CancelledError:
                pass
        
        logger.info("Мониторинг ликвидации остановлен")
    
    async def _monitoring_loop(self, client, check_interval: float, callback: Optional[callable]):
        """Основной цикл мониторинга"""
        while self.is_monitoring:
            try:
                await self._check_margin_health(client, callback)
                await asyncio.sleep(check_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Ошибка в мониторинге ликвидации: {e}")
                await asyncio.sleep(check_interval)
    
    async def _check_margin_health(self, client, callback: Optional[callable]):
        """Проверка здоровья маржи"""
        try:
            # Получаем баланс
            equity = await client.get_balance()
            
            # Получаем позиции
            positions = await client.get_positions()
            
            if not positions:
                return  # Нет позиций
            
            # Анализируем каждую позицию
            for position in positions:
                await self._analyze_position(position, equity, client, callback)
                
        except Exception as e:
            logger.error(f"Ошибка проверки маржи: {e}")
    
    async def _analyze_position(self, 
                               position: Dict[str, Any], 
                               equity: float, 
                               client, 
                               callback: Optional[callable]):
        """Анализ отдельной позиции"""
        try:
            symbol = position.get('instId', '').replace('-SWAP', '')
            side = position.get('posSide', 'long')
            size = float(position.get('pos', '0'))
            entry_price = float(position.get('avgPx', '0'))
            current_price = float(position.get('markPx', '0'))
            leverage = int(position.get('lever', '3'))
            
            if size == 0:
                return  # Нет позиции
            
            # Расчет стоимости позиции
            position_value = size * current_price
            
            # Проверка безопасности
            is_safe, details = self.margin_calculator.is_position_safe(
                position_value, equity, current_price, entry_price, 
                side, leverage, self.warning_threshold
            )
            
            margin_ratio = details['margin_ratio']
            
            # Определение уровня риска
            risk_level = self._get_risk_level(margin_ratio)
            
            # Обработка в зависимости от уровня риска
            await self._handle_risk_level(
                risk_level, symbol, side, margin_ratio, details, 
                client, callback
            )
            
        except Exception as e:
            logger.error(f"Ошибка анализа позиции: {e}")
    
    def _get_risk_level(self, margin_ratio: float) -> str:
        """Определение уровня риска"""
        if margin_ratio >= self.warning_threshold:
            return 'safe'
        elif margin_ratio >= self.danger_threshold:
            return 'warning'
        elif margin_ratio >= self.critical_threshold:
            return 'danger'
        else:
            return 'critical'
    
    async def _handle_risk_level(self, 
                               risk_level: str, 
                               symbol: str, 
                               side: str, 
                               margin_ratio: float,
                               details: Dict[str, Any],
                               client, 
                               callback: Optional[callable]):
        """Обработка уровня риска"""
        
        # Предотвращение спама уведомлений
        warning_key = f"{symbol}_{side}"
        now = datetime.now()
        
        if risk_level == 'safe':
            # Сброс времени последнего предупреждения
            if warning_key in self.last_warning_time:
                del self.last_warning_time[warning_key]
            return
        
        elif risk_level == 'warning':
            # Предупреждение (не чаще раза в 5 минут)
            if (warning_key not in self.last_warning_time or 
                now - self.last_warning_time[warning_key] > timedelta(minutes=5)):
                
                message = f"⚠️ ПРЕДУПРЕЖДЕНИЕ: {symbol} {side} - низкая маржа {margin_ratio:.1f}%"
                logger.warning(message)
                
                if callback:
                    await callback('warning', symbol, side, margin_ratio, details)
                
                self.last_warning_time[warning_key] = now
        
        elif risk_level == 'danger':
            # Опасность (не чаще раза в 2 минуты)
            if (warning_key not in self.last_warning_time or 
                now - self.last_warning_time[warning_key] > timedelta(minutes=2)):
                
                message = f"🚨 ОПАСНОСТЬ: {symbol} {side} - критически низкая маржа {margin_ratio:.1f}%"
                logger.error(message)
                
                if callback:
                    await callback('danger', symbol, side, margin_ratio, details)
                
                self.last_warning_time[warning_key] = now
        
        elif risk_level == 'critical':
            # Критично - автозакрытие
            message = f"💀 КРИТИЧНО: {symbol} {side} - автозакрытие позиции! Маржа: {margin_ratio:.1f}%"
            logger.critical(message)
            
            if callback:
                await callback('critical', symbol, side, margin_ratio, details)
            
            # Автоматическое закрытие позиции
            await self._auto_close_position(symbol, side, client)
    
    async def _auto_close_position(self, symbol: str, side: str, client):
        """Автоматическое закрытие позиции"""
        try:
            logger.critical(f"🛑 АВТОЗАКРЫТИЕ: {symbol} {side}")
            
            # Получаем текущую позицию
            positions = await client.get_positions(symbol)
            if not positions:
                logger.warning(f"Позиция {symbol} не найдена для автозакрытия")
                return
            
            position = positions[0]
            size = float(position.get('pos', '0'))
            
            if size == 0:
                logger.warning(f"Размер позиции {symbol} равен 0")
                return
            
            # Определяем сторону закрытия (противоположную)
            close_side = 'sell' if side.lower() == 'long' else 'buy'
            
            # Размещаем рыночный ордер на закрытие
            result = await client.place_futures_order(
                symbol=symbol,
                side=close_side,
                size=abs(size),
                order_type='market'
            )
            
            if result.get('code') == '0':
                logger.critical(f"✅ Позиция {symbol} {side} успешно закрыта автоматически")
            else:
                logger.error(f"❌ Ошибка автозакрытия {symbol}: {result}")
                
        except Exception as e:
            logger.error(f"Ошибка автозакрытия позиции {symbol}: {e}")
    
    async def get_margin_status(self, client) -> Dict[str, Any]:
        """Получение статуса маржи"""
        try:
            equity = await client.get_balance()
            positions = await client.get_positions()
            
            total_margin_used = 0
            position_details = []
            
            for position in positions:
                size = float(position.get('pos', '0'))
                if size == 0:
                    continue
                
                symbol = position.get('instId', '').replace('-SWAP', '')
                side = position.get('posSide', 'long')
                current_price = float(position.get('markPx', '0'))
                leverage = int(position.get('lever', '3'))
                
                position_value = abs(size) * current_price
                margin_used = position_value / leverage
                total_margin_used += margin_used
                
                # Проверка безопасности
                is_safe, details = self.margin_calculator.is_position_safe(
                    position_value, equity, current_price, 
                    float(position.get('avgPx', '0')), side, leverage
                )
                
                position_details.append({
                    'symbol': symbol,
                    'side': side,
                    'size': size,
                    'value': position_value,
                    'margin_used': margin_used,
                    'margin_ratio': details['margin_ratio'],
                    'is_safe': is_safe,
                    'liquidation_price': details['liquidation_price']
                })
            
            # Общий статус
            health_status = self.margin_calculator.get_margin_health_status(
                equity, total_margin_used
            )
            
            return {
                'equity': equity,
                'total_margin_used': total_margin_used,
                'available_margin': equity - total_margin_used,
                'health_status': health_status,
                'positions': position_details,
                'timestamp': datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Ошибка получения статуса маржи: {e}")
            return {
                'error': str(e),
                'timestamp': datetime.now().isoformat()
            }
    
    def set_thresholds(self, 
                      warning: Optional[float] = None,
                      danger: Optional[float] = None,
                      critical: Optional[float] = None,
                      auto_close: Optional[float] = None):
        """Обновление порогов"""
        if warning is not None:
            self.warning_threshold = warning
        if danger is not None:
            self.danger_threshold = danger
        if critical is not None:
            self.critical_threshold = critical
        if auto_close is not None:
            self.auto_close_threshold = auto_close
        
        logger.info(f"Пороги обновлены: warning={self.warning_threshold:.1f}, "
                   f"danger={self.danger_threshold:.1f}, critical={self.critical_threshold:.1f}, "
                   f"auto_close={self.auto_close_threshold:.1f}")


# Пример использования
if __name__ == "__main__":
    # Создаем калькулятор и guard
    calculator = MarginCalculator()
    guard = LiquidationGuard(calculator)
    
    # Пример callback функции
    async def risk_callback(level, symbol, side, margin_ratio, details):
        print(f"Уведомление: {level} - {symbol} {side} - маржа: {margin_ratio:.1f}%")
    
    print("LiquidationGuard готов к работе")