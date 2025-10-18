"""
Telegram уведомления для критичных событий.

Отправляет уведомления только для:
- Max consecutive losses
- Daily loss > 5%
- Emergency stop
- OCO failed
- Borrowed funds detected

Источник: Рекомендация Perplexity AI для мониторинга рисков.
"""

import asyncio
import os
from typing import Optional

from loguru import logger


class TelegramNotifier:
    """
    Отправка критичных уведомлений в Telegram.

    Использует Telegram Bot API для отправки сообщений.
    """

    def __init__(self, bot_token: Optional[str] = None, chat_id: Optional[str] = None):
        """
        Args:
            bot_token: Telegram Bot Token (или из env)
            chat_id: Telegram Chat ID (или из env)
        """
        self.bot_token = bot_token or os.getenv("TELEGRAM_BOT_TOKEN")
        self.chat_id = chat_id or os.getenv("TELEGRAM_CHAT_ID")

        if not self.bot_token or not self.chat_id:
            logger.warning("⚠️ Telegram not configured - alerts disabled")
            logger.warning("   Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env")
            self.enabled = False
        else:
            self.enabled = True
            logger.info(
                f"✅ Telegram Notifier initialized (Chat ID: {self.chat_id[:5]}***)"
            )

        self.api_url = (
            f"https://api.telegram.org/bot{self.bot_token}" if self.bot_token else None
        )

    async def send_critical_alert(self, message: str, title: str = "CRITICAL ALERT"):
        """
        Отправить критичное уведомление.

        Args:
            message: Текст сообщения
            title: Заголовок (по умолчанию "CRITICAL ALERT")
        """
        if not self.enabled:
            logger.debug(f"Telegram disabled - alert not sent: {title}")
            return

        try:
            import aiohttp

            url = f"{self.api_url}/sendMessage"

            formatted_message = (
                f"🚨 <b>{title}</b>\n\n"
                f"{message}\n\n"
                f"<i>{datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}</i>"
            )

            data = {
                "chat_id": self.chat_id,
                "text": formatted_message,
                "parse_mode": "HTML",
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=data, timeout=10) as response:
                    if response.status == 200:
                        logger.debug(f"✅ Telegram alert sent: {title}")
                    else:
                        response_text = await response.text()
                        logger.warning(
                            f"⚠️ Telegram failed: {response.status} - {response_text}"
                        )

        except ImportError:
            logger.error("❌ aiohttp not installed - cannot send Telegram alerts")
            logger.error("   Install: pip install aiohttp")
            self.enabled = False

        except asyncio.TimeoutError:
            logger.warning("⚠️ Telegram timeout - message may not be delivered")

        except Exception as e:
            logger.error(f"❌ Telegram error: {e}")

    async def send_consecutive_losses_alert(self, count: int, max_count: int):
        """
        Уведомление о последовательных убытках.

        Args:
            count: Текущее количество
            max_count: Максимальное количество
        """
        message = (
            f"<b>Consecutive Losses Alert</b>\n\n"
            f"Losses: <b>{count}/{max_count}</b>\n"
            f"Bot stopped automatically!"
        )
        await self.send_critical_alert(message, "MAX CONSECUTIVE LOSSES")

    async def send_daily_loss_alert(
        self, loss_percent: float, limit_percent: float, balance: float
    ):
        """
        Уведомление о превышении дневного лимита убытков.

        Args:
            loss_percent: Текущий процент убытка
            limit_percent: Лимит
            balance: Текущий баланс
        """
        message = (
            f"<b>Daily Loss Alert</b>\n\n"
            f"Loss: <b>{loss_percent:.2f}%</b> (limit: {limit_percent:.2f}%)\n"
            f"Balance: <b>${balance:.2f}</b>\n"
            f"Bot stopped automatically!"
        )
        await self.send_critical_alert(message, "DAILY LOSS LIMIT")

    async def send_emergency_stop_alert(self, reason: str):
        """
        Уведомление об экстренной остановке.

        Args:
            reason: Причина остановки
        """
        message = (
            f"<b>Emergency Stop Triggered</b>\n\n"
            f"Reason: <b>{reason}</b>\n"
            f"All positions closed!"
        )
        await self.send_critical_alert(message, "EMERGENCY STOP")

    async def send_oco_failed_alert(self, symbol: str, error: str):
        """
        Уведомление о провале OCO ордера.

        Args:
            symbol: Торговый символ
            error: Описание ошибки
        """
        message = (
            f"<b>OCO Order Failed</b>\n\n"
            f"Symbol: <b>{symbol}</b>\n"
            f"Error: {error}\n"
            f"Position opened without automatic TP/SL!"
        )
        await self.send_critical_alert(message, "OCO FAILED")

    async def send_borrowed_funds_alert(self, asset: str, amount: float):
        """
        Уведомление об обнаружении займов.

        Args:
            asset: Валюта
            amount: Размер займа
        """
        message = (
            f"<b>BORROWED FUNDS DETECTED!</b>\n\n"
            f"Asset: <b>{asset}</b>\n"
            f"Amount: <b>{amount:.6f}</b>\n"
            f"Trading stopped immediately!\n"
            f"Please repay loan and switch to SPOT mode!"
        )
        await self.send_critical_alert(message, "BORROWED FUNDS")

    async def send_startup_notification(self, balance: float, symbols: list):
        """
        Уведомление о запуске бота.

        Args:
            balance: Стартовый баланс
            symbols: Торгуемые символы
        """
        if not self.enabled:
            return

        message = (
            f"<b>Bot Started</b>\n\n"
            f"Balance: <b>${balance:.2f}</b>\n"
            f"Symbols: {', '.join(symbols)}\n"
            f"Mode: Scalping (Modular v2)"
        )
        await self.send_critical_alert(message, "BOT STARTED")

    async def send_daily_report(self, stats: dict):
        """
        Ежедневный отчет.

        Args:
            stats: Статистика за день
        """
        if not self.enabled:
            return

        message = (
            f"<b>Daily Report</b>\n\n"
            f"Trades: <b>{stats.get('total_trades', 0)}</b>\n"
            f"Win Rate: <b>{stats.get('win_rate', 0):.1f}%</b>\n"
            f"Daily PnL: <b>${stats.get('daily_pnl', 0):.2f}</b>\n"
            f"Best Trade: ${stats.get('best_trade', 0):.2f}\n"
            f"Worst Trade: ${stats.get('worst_trade', 0):.2f}"
        )
        await self.send_critical_alert(message, "DAILY REPORT")


# Для совместимости с другими модулями
from datetime import datetime
