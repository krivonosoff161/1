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
            chat_id: Telegram Chat ID или несколько через запятую (или из env)
        """
        raw_token = bot_token or os.getenv("TELEGRAM_BOT_TOKEN") or ""
        self.bot_token = raw_token.strip("'\"")

        raw_ids = chat_id or os.getenv("TELEGRAM_CHAT_ID") or ""
        # Поддержка нескольких chat_id через запятую: "111,222,333"
        self.chat_ids: list = [c.strip() for c in raw_ids.split(",") if c.strip()]
        # Для обратной совместимости со старым кодом (send_critical_alert использует self.chat_id)
        self.chat_id = self.chat_ids[0] if self.chat_ids else ""

        if not self.bot_token or not self.chat_ids:
            logger.warning("⚠️ Telegram not configured - alerts disabled")
            logger.warning("   Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env")
            self.enabled = False
        else:
            self.enabled = True
            logger.info(
                f"✅ Telegram Notifier initialized ({len(self.chat_ids)} chat(s))"
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

    # ─────────────────────────────────────────────────────────────────
    # Trade signal notifications
    # ─────────────────────────────────────────────────────────────────

    _SIGNAL_TYPE_RU = {
        "rsi_oversold": "RSI перепродан",
        "rsi_overbought": "RSI перекуплен",
        "macd_bullish": "MACD пересечение вверх",
        "macd_bearish": "MACD пересечение вниз",
        "bb_oversold": "Цена у нижней полосы BB",
        "bb_overbought": "Цена у верхней полосы BB",
        "short_combo": "Комбо-сигнал ШОРТ",
        "rsi_divergence": "RSI дивергенция",
        "volume_spike": "Спайк объёма",
    }

    _REGIME_RU = {
        "trending": "Тренд",
        "ranging": "Флэт",
        "choppy": "Хаос",
    }

    async def send_trade_open(
        self,
        signal: dict,
        tp_price: float,
        sl_price: float,
        size_usd: float = 0.0,
        entry_price: float = None,
    ) -> None:
        """Уведомление об открытии позиции."""
        if not self.enabled:
            return

        symbol = signal.get("symbol", "???")
        side = signal.get("side", "???")
        # FIX 2026-02-25: entry_price передаётся caller'ом (fill/best_ask/live snapshot).
        # Приоритет: явная entry_price > signal["price"] (которая может быть стале).
        entry = entry_price or signal.get("price") or 0.0
        strength = signal.get("strength") or 0.0
        sig_type = signal.get("type", "")
        regime = signal.get("regime", "")
        confidence = signal.get("confidence") or 0.0
        ind_value = signal.get("indicator_value")
        leverage = signal.get("leverage")

        side_icon = "🟢 LONG" if side == "buy" else "🔴 SHORT"
        regime_ru = self._REGIME_RU.get(regime, regime)
        sig_ru = self._SIGNAL_TYPE_RU.get(sig_type, sig_type)

        # R:R
        if entry and entry > 0 and tp_price and sl_price:
            tp_pct = abs(tp_price - entry) / entry * 100
            sl_pct = abs(sl_price - entry) / entry * 100
            rr = tp_pct / sl_pct if sl_pct > 0 else 0.0
            tp_str = f"{tp_price:.4f} (+{tp_pct:.2f}%)"
            sl_str = f"{sl_price:.4f} (-{sl_pct:.2f}%)"
            rr_str = f"{rr:.1f}:1"
        else:
            tp_str = f"{tp_price:.4f}" if tp_price is not None else "—"
            sl_str = f"{sl_price:.4f}" if sl_price is not None else "—"
            rr_str = "—"

        # Плечо
        if leverage:
            lev_int = int(leverage)
            if lev_int <= 3:
                lev_comment = "консервативное"
            elif lev_int <= 7:
                lev_comment = "умеренное"
            elif lev_int <= 12:
                lev_comment = "агрессивное"
            else:
                lev_comment = "⚠️ высокий риск"
            lev_str = f"<b>{lev_int}x</b>  ({lev_comment})"
        else:
            lev_str = "—"

        # Объяснение почему
        why_parts = [sig_ru]
        # ✅ FIX: Проверяем тип перед форматированием (None может прийти даже с is not None проверкой)
        if ind_value is not None and isinstance(ind_value, (int, float)):
            why_parts.append(f"значение={ind_value:.2f}")

        # Дополнительный совет при сильном сигнале
        tip = ""
        if strength >= 0.75:
            tip = (
                "\n\n💡 <b>Сильный сигнал!</b> При достижении половины TP "
                "рассмотри перенос SL в безубыток."
            )
        elif strength >= 0.55:
            tip = "\n\n💡 Средний сигнал — держи стандартный SL."

        size_str = f"${size_usd:.0f}" if size_usd else ""

        text = (
            f"<b>{side_icon} {symbol}</b>  {size_str}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📍 Вход:  <b>{entry:.4f}</b>\n"
            f"🎯 TP:    <b>{tp_str}</b>\n"
            f"🛡 SL:    <b>{sl_str}</b>\n"
            f"📊 R:R:   <b>{rr_str}</b>\n"
            f"⚡ Плечо: {lev_str}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"⚡ Сигнал:  {sig_ru}\n"
            f"📈 Режим:  {regime_ru}\n"
            f"💪 Сила:   {strength:.2f}  |  Уверенность: {confidence:.2f}\n"
            f"🔍 Почему: {', '.join(why_parts)}"
            f"{tip}"
        )

        await self.send_message(text)

    async def send_trade_close(
        self,
        symbol: str,
        side: str,
        entry_price: float,
        close_price: float,
        net_pnl: float,
        reason: str,
        duration_min: float = 0.0,
        leverage: float = 0.0,
        margin_usd: float = 0.0,
    ) -> None:
        """Уведомление о закрытии позиции."""
        if not self.enabled:
            return

        pnl_icon = "✅" if net_pnl >= 0 else "❌"
        pnl_str = f"+${net_pnl:.2f}" if net_pnl >= 0 else f"-${abs(net_pnl):.2f}"
        side_ru = "LONG" if side == "buy" else "SHORT"
        dur_str = f"{duration_min:.1f} мин" if duration_min else ""
        pnl_pct_str = ""
        if margin_usd > 0:
            pnl_pct = (net_pnl / margin_usd) * 100
            sign = "+" if pnl_pct >= 0 else ""
            pnl_pct_str = f"  ({sign}{pnl_pct:.1f}% маржи)"

        lev_str = (
            f"⚡ Плечо: {int(leverage)}x  |  💵 Маржа: ${margin_usd:.0f}\n"
            if leverage > 0 and margin_usd > 0
            else ""
        )

        text = (
            f"{pnl_icon} <b>Закрыто {side_ru} {symbol}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"💰 PnL:    <b>{pnl_str}{pnl_pct_str}</b>\n"
            f"📍 Вход:  {entry_price:.4f}  →  {close_price:.4f}\n"
            f"{lev_str}"
            f"⏱ Время: {dur_str}\n"
            f"📋 Причина: {reason}"
        )

        await self.send_message(text)

    async def send_drift_remove_alert(
        self,
        symbol: str,
        side: str,
        entry_price: float,
        size: float,
        duration_str: str,
        possible_causes: list = None,
    ) -> None:
        """
        ✅ CRITICAL ALERT: Позиция закрыта на бирже, но не через бота (DRIFT_REMOVE).

        Args:
            symbol: Торговый символ
            side: Сторона позиции (buy/sell)
            entry_price: Цена входа
            size: Размер позиции
            duration_str: Длительность удержания
            possible_causes: Список возможных причин закрытия
        """
        if not self.enabled:
            return

        side_ru = "LONG" if side == "buy" else "SHORT"
        causes = possible_causes or [
            "Trailing Stop Loss на бирже",
            "Liquidation (принудительное закрытие)",
            "ADL (Auto-Deleveraging)",
            "Manual close (пользователь закрыл вручную)",
        ]
        causes_str = "\n".join([f"  • {c}" for c in causes])

        text = (
            f"🚨 <b>CRITICAL: ПОЗИЦИЯ ЗАКРЫТА НА БИРЖЕ</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"<b>{side_ru} {symbol}</b>\n\n"
            f"📊 Детали позиции:\n"
            f"  • Entry: ${entry_price:.4f}\n"
            f"  • Size: {size} контрактов\n"
            f"  • Длительность: {duration_str}\n\n"
            f"⚠️ Позиция отсутствует на бирже, но была в локальном реестре!\n\n"
            f"🔍 Возможные причины:\n"
            f"{causes_str}\n\n"
            f"📝 Действие: Локальное состояние синхронизировано"
        )

        await self.send_critical_alert(text, "DRIFT_REMOVE DETECTED")

    async def send_message(self, text: str) -> None:
        """Отправить произвольное HTML-сообщение всем получателям из chat_ids."""
        if not self.enabled:
            return
        try:
            import aiohttp

            url = f"{self.api_url}/sendMessage"
            async with aiohttp.ClientSession() as session:
                for cid in self.chat_ids:
                    data = {"chat_id": cid, "text": text, "parse_mode": "HTML"}
                    async with session.post(
                        url, json=data, timeout=aiohttp.ClientTimeout(total=10)
                    ) as resp:
                        if resp.status != 200:
                            body = await resp.text()
                            logger.warning(
                                f"⚠️ Telegram send_message failed (chat={cid}): {resp.status} {body[:120]}"
                            )
        except asyncio.TimeoutError:
            logger.warning("⚠️ Telegram timeout")
        except Exception as e:
            logger.error(f"❌ Telegram error: {e}")


# Для совместимости с другими модулями
from datetime import datetime
