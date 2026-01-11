#!/usr/bin/env python3
"""
Точка входа для Futures торговли.
Запускает Futures версию торгового бота.
"""

import asyncio
import sys
from pathlib import Path

# Добавляем корневую папку проекта в путь
project_root = Path(
    __file__
).parent.parent  # Переходим на уровень выше (из src в корень)
sys.path.insert(0, str(project_root))

from src.config import BotConfig  # noqa: E402
from src.strategies.scalping.futures.logging.correlation_id_context import \
    CorrelationIdContext  # noqa: E402
from src.strategies.scalping.futures.logging.logger_factory import \
    LoggerFactory  # noqa: E402
from src.strategies.scalping.futures.orchestrator import \
    FuturesScalpingOrchestrator  # noqa: E402

# 🔴 BUG #31 FIX (11.01.2026): Single logging setup via LoggerFactory
LoggerFactory.setup_futures_logging(log_dir="logs/futures", log_level="DEBUG")

# Import logger AFTER LoggerFactory setup
from loguru import logger  # noqa: E402


async def main():
    """Основная функция запуска Futures бота"""
    orchestrator = None
    # 🔴 BUG #37 FIX (11.01.2026): Generate and set correlation ID for session tracing
    session_correlation_id = CorrelationIdContext.generate_id(prefix="session")
    CorrelationIdContext.set_correlation_id(session_correlation_id)

    try:
        logger.info(
            f"🚀 Запуск Futures торгового бота... (session={session_correlation_id})"
        )

        # Загружаем конфигурацию
        config_path = project_root / "config" / "config_futures.yaml"
        if not config_path.exists():
            # Пробуем альтернативный путь (если запускаем из корня)
            alt_path = Path("config/config_futures.yaml")
            if alt_path.exists():
                config_path = alt_path
            else:
                logger.error(f"❌ Конфигурационный файл не найден: {config_path}")
                logger.error(f"❌ Альтернативный путь также не найден: {alt_path}")
                logger.info(
                    "💡 Создайте файл config/config_futures.yaml с вашими настройками"
                )
                return

        # 🔴 BUG #26 FIX: Явная валидация что Futures режим использует
        # config_futures.yaml
        if "config_futures.yaml" not in str(config_path):
            logger.error(
                "❌ КРИТИЧЕСКАЯ ОШИБКА: Futures режим должен использовать "
                "config_futures.yaml"
            )
            logger.error(f"   Загруженный путь: {config_path}")
            logger.info("💡 Используйте явно: python -m src.main_futures")
            return

        logger.info(f"✓ Конфиг: {config_path}")
        logger.info("✓ Режим: Futures (с левериджем)")

        # Создаем конфигурацию
        config = BotConfig.load_from_file(str(config_path))

        # 🔴 BUG #30 FIX: Валидация что конфиг содержит Futures параметры,
        # не Spot (11.01.2026)
        # Проверяем что конфиг не содержит spot-специфичные настройки
        try:
            # Spot режимы (есть в config.yaml, не должны быть в
            # config_futures.yaml)
            spot_keys_to_check = {
                "paper_trading_mode": "spot",  # Spot имеет paper_trading_mode
                "websocket_spot": "spot",  # Spot WebSocket отличается
                "cache_klines_locally": "spot",  # Spot может кэшировать
            }

            # Futures уникальные параметры (должны быть в
            # config_futures.yaml)
            futures_required_keys = {
                "scalping": "futures scalping config",
                "margin_mode": "futures margin mode",
                "leverage": "futures leverage",
            }

            config_dict = config.__dict__ if hasattr(config, "__dict__") else {}

            # Проверяем наличие Futures параметров
            missing_futures_keys = []
            for key in futures_required_keys.keys():
                if key not in config_dict or getattr(config, key, None) is None:
                    missing_futures_keys.append(key)

            if missing_futures_keys:
                logger.error("❌ BUG #30: Конфигурация NOT для Futures режима!")
                logger.error(
                    f"   Отсутствуют параметры: " f"{', '.join(missing_futures_keys)}"
                )
                logger.error(
                    "   Это похоже на Spot конфигурацию, "
                    "но использован --mode futures"
                )
                logger.info("💡 Используйте файл: config/config_futures.yaml")
                logger.info(
                    "💡 Убедитесь что конфиг содержит 'scalping', "
                    "'margin_mode', 'leverage'"
                )
                return

            # Проверяем что случайно не загрузился spot конфиг
            spot_detected = False
            for spot_key in spot_keys_to_check.keys():
                if hasattr(config, spot_key) and getattr(config, spot_key) is not None:
                    spot_detected = True
                    logger.warning(
                        f"⚠️ BUG #30: Обнаружен spot параметр "
                        f"'{spot_key}' в futures конфиге"
                    )

            if spot_detected:
                logger.error(
                    "❌ BUG #30: Конфиг содержит Spot параметры - " "НЕПРАВИЛЬНЫЙ РЕЖИМ!"
                )
                logger.info("💡 Проверьте что используется config/config_futures.yaml")
                return

            logger.debug(
                "✅ BUG #30: Конфиг валиден для Futures режима "
                "(все параметры на месте)"
            )

        except Exception as e:
            logger.error(f"❌ BUG #30: Ошибка валидации конфига: {e}")
            logger.debug("", exc_info=True)
            # Продолжаем работу, но логируем предупреждение
            logger.warning("⚠️ Убедитесь что используется config_futures.yaml")

        # Проверяем конфигурацию
        if (
            not config.get_okx_config().api_key
            or config.get_okx_config().api_key == "your_api_key_here"
        ):
            logger.error("❌ API ключ не настроен в конфигурации")
            logger.info(
                "💡 Отредактируйте config/config_futures.yaml и укажите ваши API ключи"
            )
            return

        # Предупреждение о рисках Futures торговли
        logger.warning("⚠️ ВНИМАНИЕ: Futures торговля связана с высокими рисками!")
        logger.warning(
            "⚠️ Используйте только те средства, "
            "потерю которых можете себе позволить!"
        )
        logger.warning("⚠️ Рекомендуется начать с sandbox режима для тестирования!")

        # Создаем оркестратор
        orchestrator = FuturesScalpingOrchestrator(config)

        # Запускаем бота
        await orchestrator.start()

    except KeyboardInterrupt:
        logger.info("🛑 Получен сигнал остановки (Ctrl+C)...")
        # Останавливаем оркестратор при KeyboardInterrupt
        if orchestrator:
            try:
                await orchestrator.stop()
            except (asyncio.CancelledError, Exception) as stop_error:
                logger.debug(
                    f"⚠️ Ошибка при остановке (ожидаемо при прерывании): {stop_error}"
                )
    except asyncio.CancelledError:
        logger.info("🛑 Задача отменена")
        if orchestrator:
            try:
                await orchestrator.stop()
            except Exception as stop_error:
                logger.debug(f"⚠️ Ошибка при остановке: {stop_error}")
    except Exception as e:
        logger.error(f"❌ Критическая ошибка: {e}")
        # Останавливаем оркестратор при ошибке
        if orchestrator:
            try:
                await orchestrator.stop()
            except Exception as stop_error:
                logger.debug(f"⚠️ Ошибка при остановке: {stop_error}")
        raise
    finally:
        logger.info("✅ Futures бот остановлен")


if __name__ == "__main__":
    # ✅ Логирование уже настроено в LoggerFactory (L19)
    # 🔴 BUG #31 FIX: Removed duplicate logging setup -
    # was causing double logger initialization

    # Запуск
    asyncio.run(main())
