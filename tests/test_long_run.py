#!/usr/bin/env python
"""
Долгий тест бота с наблюдением за логами
"""
import asyncio
import subprocess
import sys
import time
from pathlib import Path


async def run_bot(duration_seconds=300):
    """Запустить бот на N секунд"""
    print(f"🤖 Запуск бота Futures на {duration_seconds} сек...")

    # Запустить процесс
    process = subprocess.Popen(
        [sys.executable, "run.py", "--mode", "futures"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    print(f"⏱️  Процесс запущен (PID={process.pid}), жду {duration_seconds} сек...")

    # Ждем
    for i in range(duration_seconds):
        elapsed = i + 1
        remaining = duration_seconds - elapsed
        if remaining % 30 == 0 or elapsed % 30 == 0:
            print(f"⏳ Прошло {elapsed}s из {duration_seconds}s (осталось {remaining}s)")
        await asyncio.sleep(1)

    # Останавливаем
    print(f"🛑 Завершение бота...")
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()

    print(f"✅ Процесс завершен. Проверяем логи...")


async def main():
    """Main"""
    # Получим последний логфайл ДО запуска
    logs_dir = Path("logs/futures")
    if logs_dir.exists():
        before_files = set(f.name for f in logs_dir.glob("*.log"))
    else:
        before_files = set()

    # Запустим бот на 5 минут
    await run_bot(duration_seconds=300)

    # Найдем новый или измененный логфайл
    if logs_dir.exists():
        after_files = set(f.name for f in logs_dir.glob("*.log"))
        new_files = after_files - before_files

        if new_files:
            log_file = logs_dir / list(new_files)[0]
        else:
            # Найдем самый свежий
            all_files = sorted(
                logs_dir.glob("*.log"), key=lambda f: f.stat().st_mtime, reverse=True
            )
            log_file = all_files[0] if all_files else None

        if log_file:
            print(f"\n📋 Последний логфайл: {log_file}")
            print("=" * 80)

            # Показываем интересующие нас строки
            content = log_file.read_text(encoding="utf-8", errors="ignore")
            keywords = [
                "TSL_MODE",
                "TSL_UPDATE",
                "EXIT_GUARD",
                "PH_DECISION",
                "SL_CHECK",
                "signal",
                "SIGNAL",
            ]

            found = 0
            for line in content.split("\n"):
                if any(kw in line for kw in keywords):
                    print(line)
                    found += 1

            if found == 0:
                print("⚠️  Не найдены интересующие логи (позиций не было открыто)")
            else:
                print(f"\n✅ Найдено {found} строк с интересующими логами")


if __name__ == "__main__":
    asyncio.run(main())
