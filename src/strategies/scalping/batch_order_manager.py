"""
Batch Order Manager для группировки обновлений TP/SL ордеров
Уменьшает API calls с 10 до 1 (90% экономии)
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

from loguru import logger


@dataclass
class OrderUpdate:
    """Данные для обновления ордера"""

    inst_id: str
    ord_id: str
    new_sz: Optional[str] = None
    new_px: Optional[str] = None
    new_tp_trigger_px: Optional[str] = None
    new_sl_trigger_px: Optional[str] = None
    new_tp_ord_px: Optional[str] = None
    new_sl_ord_px: Optional[str] = None


class BatchOrderManager:
    """
    Менеджер для группировки обновлений ордеров в batch операции

    Преимущества:
    - До 20 ордеров за один API call
    - -90% API calls
    - Избежание rate limits (429 ошибок)
    - Быстрее обновления TP/SL
    """

    def __init__(self, client):
        self.client = client
        self.pending_updates: List[OrderUpdate] = []
        self.max_batch_size = 20
        self.auto_flush_threshold = 10  # Автоматический flush при 10 обновлениях

    def add_order_update(
        self,
        inst_id: str,
        ord_id: str,
        new_sz: Optional[str] = None,
        new_px: Optional[str] = None,
        new_tp_trigger_px: Optional[str] = None,
        new_sl_trigger_px: Optional[str] = None,
        new_tp_ord_px: Optional[str] = None,
        new_sl_ord_px: Optional[str] = None,
    ):
        """Добавить обновление ордера в batch"""
        update = OrderUpdate(
            inst_id=inst_id,
            ord_id=ord_id,
            new_sz=new_sz,
            new_px=new_px,
            new_tp_trigger_px=new_tp_trigger_px,
            new_sl_trigger_px=new_sl_trigger_px,
            new_tp_ord_px=new_tp_ord_px,
            new_sl_ord_px=new_sl_ord_px,
        )

        self.pending_updates.append(update)
        logger.debug(f"📝 Added order update to batch: {inst_id} {ord_id}")

        # Автоматический flush при достижении порога
        if len(self.pending_updates) >= self.auto_flush_threshold:
            logger.info(f"🔄 Auto-flush triggered: {len(self.pending_updates)} updates")
            return self.flush_updates()

        return None

    async def flush_updates(self) -> Dict[str, Any]:
        """Выполнить все накопленные обновления"""
        if not self.pending_updates:
            return {"code": "0", "msg": "No updates to flush", "data": []}

        try:
            # Конвертируем в формат OKX API
            orders_data = []
            for update in self.pending_updates:
                order_data = {"instId": update.inst_id, "ordId": update.ord_id}

                # Добавляем только не-None поля
                if update.new_sz is not None:
                    order_data["newSz"] = update.new_sz
                if update.new_px is not None:
                    order_data["newPx"] = update.new_px
                if update.new_tp_trigger_px is not None:
                    order_data["newTpTriggerPx"] = update.new_tp_trigger_px
                if update.new_sl_trigger_px is not None:
                    order_data["newSlTriggerPx"] = update.new_sl_trigger_px
                if update.new_tp_ord_px is not None:
                    order_data["newTpOrdPx"] = update.new_tp_ord_px
                if update.new_sl_ord_px is not None:
                    order_data["newSlOrdPx"] = update.new_sl_ord_px

                orders_data.append(order_data)

            logger.info(f"🚀 Executing batch amend: {len(orders_data)} orders")

            # Выполняем batch amend
            result = await self.client.batch_amend_orders(orders_data)

            # Очищаем pending updates
            self.pending_updates.clear()

            if result.get("code") == "0":
                logger.info(
                    f"✅ Batch amend successful: {len(orders_data)} orders updated"
                )
            else:
                logger.error(
                    f"❌ Batch amend failed: {result.get('msg', 'Unknown error')}"
                )

            return result

        except Exception as e:
            logger.error(f"❌ Batch flush error: {e}")
            return {"code": "1", "msg": str(e), "data": []}

    async def force_flush(self) -> Dict[str, Any]:
        """Принудительный flush всех накопленных обновлений"""
        if not self.pending_updates:
            return {"code": "0", "msg": "No updates to flush", "data": []}

        logger.info(f"🔄 Force flush: {len(self.pending_updates)} updates")
        return await self.flush_updates()

    def get_pending_count(self) -> int:
        """Получить количество накопленных обновлений"""
        return len(self.pending_updates)

    def clear_pending(self):
        """Очистить накопленные обновления (без выполнения)"""
        count = len(self.pending_updates)
        self.pending_updates.clear()
        logger.warning(f"🗑️ Cleared {count} pending updates")

    async def update_tp_sl_batch(
        self,
        inst_id: str,
        tp_ord_id: str,
        sl_ord_id: str,
        new_tp_price: str,
        new_sl_price: str,
        new_tp_trigger: Optional[str] = None,
        new_sl_trigger: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Обновление TP/SL ордеров в batch режиме

        Args:
            inst_id: Торговая пара
            tp_ord_id: ID Take Profit ордера
            sl_ord_id: ID Stop Loss ордера
            new_tp_price: Новая цена TP
            new_sl_price: Новая цена SL
            new_tp_trigger: Новый trigger для TP (опционально)
            new_sl_trigger: Новый trigger для SL (опционально)
        """
        try:
            # Добавляем обновление TP
            self.add_order_update(
                inst_id=inst_id,
                ord_id=tp_ord_id,
                new_px=new_tp_price,
                new_tp_trigger_px=new_tp_trigger,
            )

            # Добавляем обновление SL
            self.add_order_update(
                inst_id=inst_id,
                ord_id=sl_ord_id,
                new_px=new_sl_price,
                new_sl_trigger_px=new_sl_trigger,
            )

            # Если накопилось достаточно - выполняем
            if len(self.pending_updates) >= self.auto_flush_threshold:
                return await self.flush_updates()

            return {"code": "0", "msg": "Updates queued", "data": []}

        except Exception as e:
            logger.error(f"❌ Batch TP/SL update error: {e}")
            return {"code": "1", "msg": str(e), "data": []}

    def get_stats(self) -> Dict[str, Any]:
        """Получить статистику batch операций"""
        return {
            "pending_updates": len(self.pending_updates),
            "max_batch_size": self.max_batch_size,
            "auto_flush_threshold": self.auto_flush_threshold,
            "ready_for_flush": len(self.pending_updates) >= self.auto_flush_threshold,
        }
