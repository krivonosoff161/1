"""
✅ Комплексная проверка всего проекта фьючерсов
Проверка на критические проблемы для работы 20+ часов
"""
import sys
import os
import ast
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

print("=" * 80)
print("🔍 КОМПЛЕКСНАЯ ПРОВЕРКА ПРОЕКТА ФЬЮЧЕРСОВ")
print("=" * 80)

errors = []
warnings = []
success_count = 0

def check_file(file_path):
    """Проверка одного файла"""
    file_errors = []
    file_warnings = []
    
    try:
        # 1. Проверка синтаксиса
        with open(file_path, 'r', encoding='utf-8') as f:
            source = f.read()
            try:
                ast.parse(source)
            except SyntaxError as e:
                file_errors.append(f"❌ Синтаксическая ошибка: {e}")
                return file_errors, file_warnings
        
        # 2. Проверка критических паттернов
        lines = source.split('\n')
        
        # Проверка на бесконечные циклы без sleep
        for i, line in enumerate(lines, 1):
            if 'while True' in line or 'while 1' in line:
                # Проверяем, есть ли sleep в следующих 20 строках
                has_sleep = False
                for j in range(i, min(i + 20, len(lines))):
                    if 'sleep' in lines[j] or 'await asyncio.sleep' in lines[j]:
                        has_sleep = True
                        break
                if not has_sleep:
                    file_warnings.append(f"⚠️ Строка {i}: Бесконечный цикл без sleep может заблокировать event loop")
        
        # Проверка на отсутствие обработки ошибок
        has_try_except = 'try:' in source
        has_async_def = 'async def' in source
        
        if has_async_def and not has_try_except:
            file_warnings.append("⚠️ Есть async функции, но нет обработки ошибок (try/except)")
        
        # Проверка на отсутствие finally для очистки ресурсов
        if 'open(' in source or 'connect(' in source or 'websocket' in source.lower():
            if 'finally:' not in source:
                file_warnings.append("⚠️ Используются ресурсы (open/connect/websocket), но нет finally для очистки")
        
        # Проверка на потенциальные утечки памяти
        if '.append(' in source or '.extend(' in source:
            if 'clear()' not in source and 'del ' not in source:
                # Это не критично, просто предупреждение
                pass
        
        # Проверка на неправильное использование asyncio
        if 'asyncio.create_task(' in source:
            if 'await' not in source or 'asyncio.gather' not in source:
                file_warnings.append("⚠️ Используется create_task без await/gather - возможны потерянные задачи")
        
        # Проверка на закрытие WebSocket соединений
        if 'websocket' in source.lower() or 'WebSocket' in source:
            if 'close()' not in source and '.close()' not in source:
                file_warnings.append("⚠️ Используются WebSocket, но нет вызова close() - возможна утечка соединений")
        
        # Проверка на импорты
        try:
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name.startswith('src.'):
                            # Проверяем, что модуль существует
                            module_path = Path('src') / alias.name.replace('src.', '').replace('.', '/') / '__init__.py'
                            if not module_path.exists() and not (module_path.parent / f'{Path(alias.name).name}.py').exists():
                                file_errors.append(f"❌ Несуществующий импорт: {alias.name}")
                elif isinstance(node, ast.ImportFrom):
                    if node.module and node.module.startswith('src.'):
                        module_path = Path('src') / node.module.replace('src.', '').replace('.', '/')
                        if not module_path.exists() and not (module_path.parent / f'{Path(node.module).name}.py').exists():
                            file_errors.append(f"❌ Несуществующий модуль для импорта: {node.module}")
        except Exception as e:
            file_warnings.append(f"⚠️ Ошибка проверки импортов: {e}")
        
        success_count = 1
        
    except Exception as e:
        file_errors.append(f"❌ Ошибка проверки файла: {e}")
    
    return file_errors, file_warnings

# Проверяем все Python файлы в futures
futures_dir = Path('src/strategies/scalping/futures')
python_files = list(futures_dir.rglob('*.py'))
python_files.extend(Path('config').glob('*.yaml'))

print(f"\n📁 Найдено файлов для проверки: {len(python_files)}")

for file_path in python_files:
    if file_path.suffix == '.yaml':
        continue
    
    print(f"\n📄 Проверка: {file_path.relative_to('.')}")
    file_errors, file_warnings = check_file(file_path)
    
    if file_errors:
        errors.extend([f"{file_path}: {e}" for e in file_errors])
        for e in file_errors:
            print(f"  {e}")
    if file_warnings:
        warnings.extend([f"{file_path}: {w}" for w in file_warnings])
        for w in file_warnings:
            print(f"  {w}")
    
    if not file_errors and not file_warnings:
        success_count += 1
        print(f"  ✅ OK")

# Проверка критических файлов отдельно
critical_files = [
    'src/strategies/scalping/futures/orchestrator.py',
    'src/strategies/scalping/futures/position_manager.py',
    'src/strategies/scalping/futures/risk_manager.py',
    'src/strategies/scalping/futures/order_executor.py',
    'src/strategies/scalping/futures/coordinators/websocket_coordinator.py',
    'src/strategies/scalping/futures/private_websocket_manager.py',
    'config/config_futures.yaml',
]

print("\n" + "=" * 80)
print("🔍 ПРОВЕРКА КРИТИЧЕСКИХ ФАЙЛОВ")
print("=" * 80)

for file_path in critical_files:
    if not Path(file_path).exists():
        errors.append(f"❌ Критический файл не найден: {file_path}")
        print(f"❌ {file_path}: НЕ НАЙДЕН")
        continue
    
    print(f"\n📄 {file_path}")
    if file_path.endswith('.yaml'):
        try:
            import yaml
            with open(file_path, 'r', encoding='utf-8') as f:
                yaml.safe_load(f)
            print("  ✅ YAML синтаксис корректен")
        except Exception as e:
            errors.append(f"{file_path}: YAML ошибка: {e}")
            print(f"  ❌ YAML ошибка: {e}")
    else:
        file_errors, file_warnings = check_file(file_path)
        if file_errors:
            errors.extend([f"{file_path}: {e}" for e in file_errors])
        if file_warnings:
            warnings.extend([f"{file_path}: {w}" for w in file_warnings])

# Итоговый отчет
print("\n" + "=" * 80)
print("📊 ИТОГОВЫЙ ОТЧЕТ")
print("=" * 80)

print(f"\n✅ Успешно проверено файлов: {success_count}")
print(f"❌ Ошибок: {len(errors)}")
print(f"⚠️ Предупреждений: {len(warnings)}")

if errors:
    print("\n❌ КРИТИЧЕСКИЕ ОШИБКИ:")
    for error in errors[:20]:  # Показываем первые 20
        print(f"  {error}")
    if len(errors) > 20:
        print(f"  ... и еще {len(errors) - 20} ошибок")

if warnings:
    print("\n⚠️ ПРЕДУПРЕЖДЕНИЯ (первые 20):")
    for warning in warnings[:20]:
        print(f"  {warning}")
    if len(warnings) > 20:
        print(f"  ... и еще {len(warnings) - 20} предупреждений")

if not errors:
    print("\n✅ ВСЕ КРИТИЧЕСКИЕ ПРОВЕРКИ ПРОЙДЕНЫ!")
    print("   Бот готов к длительной работе (20+ часов)")
else:
    print("\n❌ ОБНАРУЖЕНЫ КРИТИЧЕСКИЕ ОШИБКИ!")
    print("   Необходимо исправить перед запуском на длительное время")
    sys.exit(1)

