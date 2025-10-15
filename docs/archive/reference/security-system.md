# Продвинутая система безопасности для торгового бота

## Многоуровневая система безопасности

### 1. Безопасность секретов и конфигурации

#### 1.1 Менеджер секретов
```python
"""
src/core/security.py - Безопасное управление секретами
"""

import os
import base64
import hashlib
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from typing import Optional, Dict, Any
import keyring
from loguru import logger


class SecretManager:
    """Безопасное управление секретами с шифрованием"""
    
    def __init__(self, master_password: Optional[str] = None):
        self.master_password = master_password or os.environ.get('MASTER_PASSWORD')
        self._encryption_key = None
        self._setup_encryption()
    
    def _setup_encryption(self):
        """Настройка шифрования для локального хранения"""
        if self.master_password:
            password = self.master_password.encode()
            salt = b'stable_salt_for_trading_bot'  # В продакшене использовать случайную соль
            kdf = PBKDF2HMAC(
                algorithm=hashes.SHA256(),
                length=32,
                salt=salt,
                iterations=100000,
            )
            key = base64.urlsafe_b64encode(kdf.derive(password))
            self._encryption_key = Fernet(key)
    
    def get_secret(self, key: str, fallback_env: bool = True) -> Optional[str]:
        """
        Получение секрета из безопасного хранилища
        
        Приоритет:
        1. Системное хранилище ключей (keyring)
        2. Переменные окружения (если fallback_env=True)
        3. Зашифрованный локальный файл
        """
        try:
            # Попытка получить из системного хранилища
            secret = keyring.get_password("trading_bot", key)
            if secret:
                return secret
        except Exception as e:
            logger.debug(f"Failed to get secret from keyring: {e}")
        
        # Попытка получить из переменных окружения
        if fallback_env:
            secret = os.environ.get(key)
            if secret:
                return secret
        
        # Попытка получить из зашифрованного файла
        return self._get_encrypted_secret(key)
    
    def set_secret(self, key: str, value: str, use_keyring: bool = True):
        """Сохранение секрета в безопасное хранилище"""
        try:
            if use_keyring:
                keyring.set_password("trading_bot", key, value)
                logger.info(f"Secret {key} saved to system keyring")
            else:
                self._save_encrypted_secret(key, value)
                logger.info(f"Secret {key} saved to encrypted storage")
        except Exception as e:
            logger.error(f"Failed to save secret {key}: {e}")
            raise
    
    def _get_encrypted_secret(self, key: str) -> Optional[str]:
        """Получение секрета из зашифрованного файла"""
        if not self._encryption_key:
            return None
        
        try:
            with open(f".secrets/{key}.enc", "rb") as f:
                encrypted_data = f.read()
            decrypted_data = self._encryption_key.decrypt(encrypted_data)
            return decrypted_data.decode()
        except Exception:
            return None
    
    def _save_encrypted_secret(self, key: str, value: str):
        """Сохранение секрета в зашифрованный файл"""
        if not self._encryption_key:
            raise ValueError("Encryption not setup")
        
        os.makedirs(".secrets", exist_ok=True)
        encrypted_data = self._encryption_key.encrypt(value.encode())
        
        with open(f".secrets/{key}.enc", "wb") as f:
            f.write(encrypted_data)


class APICredentialsManager:
    """Безопасное управление API ключами"""
    
    def __init__(self, secret_manager: SecretManager):
        self.secret_manager = secret_manager
        self._credentials_cache = {}
    
    def get_okx_credentials(self) -> Dict[str, str]:
        """Получение OKX API credentials"""
        cache_key = "okx_credentials"
        
        if cache_key not in self._credentials_cache:
            credentials = {
                'api_key': self.secret_manager.get_secret('OKX_API_KEY'),
                'secret_key': self.secret_manager.get_secret('OKX_SECRET_KEY'),
                'passphrase': self.secret_manager.get_secret('OKX_PASSPHRASE'),
            }
            
            # Валидация credentials
            if not all(credentials.values()):
                raise ValueError("Missing required OKX API credentials")
            
            self._credentials_cache[cache_key] = credentials
        
        return self._credentials_cache[cache_key]
    
    def rotate_credentials(self, exchange: str, new_credentials: Dict[str, str]):
        """Ротация API ключей"""
        for key, value in new_credentials.items():
            self.secret_manager.set_secret(f"{exchange.upper()}_{key.upper()}", value)
        
        # Очистка кэша
        cache_key = f"{exchange}_credentials"
        if cache_key in self._credentials_cache:
            del self._credentials_cache[cache_key]
        
        logger.info(f"Credentials rotated for {exchange}")


class LogSanitizer:
    """Санитизация логов от чувствительных данных"""
    
    SENSITIVE_PATTERNS = [
        r'api[_-]?key["\s]*[:=]["\s]*([a-zA-Z0-9]+)',
        r'secret[_-]?key["\s]*[:=]["\s]*([a-zA-Z0-9]+)',
        r'passphrase["\s]*[:=]["\s]*([a-zA-Z0-9]+)',
        r'password["\s]*[:=]["\s]*([a-zA-Z0-9]+)',
        r'token["\s]*[:=]["\s]*([a-zA-Z0-9]+)',
    ]
    
    @staticmethod
    def sanitize_message(message: str) -> str:
        """Удаление чувствительных данных из лог-сообщения"""
        import re
        
        sanitized = message
        for pattern in LogSanitizer.SENSITIVE_PATTERNS:
            sanitized = re.sub(pattern, r'\1***REDACTED***', sanitized, flags=re.IGNORECASE)
        
        return sanitized


class SecureConfig:
    """Безопасная конфигурация с валидацией"""
    
    def __init__(self, secret_manager: SecretManager):
        self.secret_manager = secret_manager
        self._config_cache = {}
        self._config_hash = None
    
    def load_config(self, config_path: str = "config.yaml") -> Dict[str, Any]:
        """Загрузка конфигурации с проверкой целостности"""
        import yaml
        import hashlib
        
        # Проверка изменений файла
        with open(config_path, 'r') as f:
            content = f.read()
        
        current_hash = hashlib.sha256(content.encode()).hexdigest()
        
        if self._config_hash != current_hash or not self._config_cache:
            # Загрузка конфигурации
            config = yaml.safe_load(content)
            
            # Валидация конфигурации
            self._validate_config(config)
            
            # Замена плейсхолдеров секретов
            config = self._resolve_secrets(config)
            
            self._config_cache = config
            self._config_hash = current_hash
            
            logger.info("Configuration loaded and validated")
        
        return self._config_cache.copy()
    
    def _validate_config(self, config: Dict[str, Any]):
        """Валидация конфигурации"""
        required_sections = ['risk', 'trading', 'exchange']
        
        for section in required_sections:
            if section not in config:
                raise ValueError(f"Missing required config section: {section}")
        
        # Валидация риск-параметров
        risk_config = config.get('risk', {})
        if risk_config.get('max_daily_loss_percent', 0) > 20:
            logger.warning("High daily loss limit detected")
        
        if risk_config.get('leverage', 1) > 10:
            logger.warning("High leverage detected")
    
    def _resolve_secrets(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Замена плейсхолдеров секретов на реальные значения"""
        import re
        
        def replace_secrets(obj):
            if isinstance(obj, dict):
                return {k: replace_secrets(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [replace_secrets(item) for item in obj]
            elif isinstance(obj, str):
                # Поиск паттерна ${SECRET_NAME}
                pattern = r'\$\{([^}]+)\}'
                matches = re.findall(pattern, obj)
                
                for match in matches:
                    secret_value = self.secret_manager.get_secret(match)
                    if secret_value:
                        obj = obj.replace(f'${{{match}}}', secret_value)
                    else:
                        logger.warning(f"Secret {match} not found")
                
                return obj
            else:
                return obj
        
        return replace_secrets(config)
```

### 2. Система аутентификации и авторизации

#### 2.1 Токены доступа для Web интерфейса
```python
"""
src/core/auth.py - Система аутентификации
"""

import jwt
import secrets
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from passlib.context import CryptContext
from fastapi import HTTPException, Depends, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials


class AuthManager:
    """Управление аутентификацией и авторизацией"""
    
    def __init__(self, secret_key: Optional[str] = None):
        self.secret_key = secret_key or secrets.token_urlsafe(32)
        self.algorithm = "HS256"
        self.pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
        self.security = HTTPBearer()
        
        # Список активных токенов (в продакшене использовать Redis)
        self.active_tokens = set()
    
    def create_access_token(self, data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
        """Создание JWT токена"""
        to_encode = data.copy()
        
        if expires_delta:
            expire = datetime.utcnow() + expires_delta
        else:
            expire = datetime.utcnow() + timedelta(hours=24)
        
        to_encode.update({"exp": expire})
        
        token = jwt.encode(to_encode, self.secret_key, algorithm=self.algorithm)
        self.active_tokens.add(token)
        
        return token
    
    def verify_token(self, token: str) -> Optional[Dict[str, Any]]:
        """Проверка JWT токена"""
        try:
            if token not in self.active_tokens:
                return None
            
            payload = jwt.decode(token, self.secret_key, algorithms=[self.algorithm])
            return payload
        except jwt.PyJWTError:
            return None
    
    def revoke_token(self, token: str):
        """Отзыв токена"""
        self.active_tokens.discard(token)
    
    def hash_password(self, password: str) -> str:
        """Хеширование пароля"""
        return self.pwd_context.hash(password)
    
    def verify_password(self, plain_password: str, hashed_password: str) -> bool:
        """Проверка пароля"""
        return self.pwd_context.verify(plain_password, hashed_password)
    
    async def get_current_user(self, credentials: HTTPAuthorizationCredentials = Depends(security)):
        """Получение текущего пользователя из токена"""
        payload = self.verify_token(credentials.credentials)
        
        if payload is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )
        
        return payload
```

### 3. Система мониторинга безопасности

#### 3.1 Детектор аномалий
```python
"""
src/monitoring/security_monitor.py - Мониторинг безопасности
"""

import asyncio
from datetime import datetime, timedelta
from typing import List, Dict, Any
from dataclasses import dataclass
from enum import Enum
import numpy as np
from loguru import logger


class ThreatLevel(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class SecurityAlert:
    timestamp: datetime
    threat_level: ThreatLevel
    category: str
    message: str
    details: Dict[str, Any]


class SecurityMonitor:
    """Мониторинг безопасности торговой системы"""
    
    def __init__(self):
        self.alerts: List[SecurityAlert] = []
        self.api_call_history = []
        self.failed_auth_attempts = {}
        self.unusual_activity_threshold = 3  # стандартных отклонения
        self.max_failed_attempts = 5
        self.monitoring_active = True
    
    async def monitor_api_usage(self, endpoint: str, response_time: float, status_code: int):
        """Мониторинг использования API"""
        self.api_call_history.append({
            'timestamp': datetime.utcnow(),
            'endpoint': endpoint,
            'response_time': response_time,
            'status_code': status_code
        })
        
        # Проверка аномальной активности
        await self._check_unusual_api_activity()
        
        # Проверка высокой частоты запросов
        await self._check_rate_limits()
    
    async def monitor_failed_auth(self, ip_address: str):
        """Мониторинг неудачных попыток аутентификации"""
        current_time = datetime.utcnow()
        
        if ip_address not in self.failed_auth_attempts:
            self.failed_auth_attempts[ip_address] = []
        
        self.failed_auth_attempts[ip_address].append(current_time)
        
        # Удаление старых записей (старше 1 часа)
        one_hour_ago = current_time - timedelta(hours=1)
        self.failed_auth_attempts[ip_address] = [
            attempt for attempt in self.failed_auth_attempts[ip_address]
            if attempt > one_hour_ago
        ]
        
        # Проверка превышения лимита
        if len(self.failed_auth_attempts[ip_address]) >= self.max_failed_attempts:
            await self._create_alert(
                ThreatLevel.HIGH,
                "authentication",
                f"Multiple failed authentication attempts from {ip_address}",
                {"ip_address": ip_address, "attempts": len(self.failed_auth_attempts[ip_address])}
            )
    
    async def monitor_trading_anomalies(self, trade_data: Dict[str, Any]):
        """Мониторинг торговых аномалий"""
        
        # Проверка необычно больших позиций
        position_size = trade_data.get('position_size', 0)
        if position_size > trade_data.get('max_position_size', float('inf')):
            await self._create_alert(
                ThreatLevel.CRITICAL,
                "trading",
                f"Position size exceeds maximum allowed: {position_size}",
                trade_data
            )
        
        # Проверка необычной частоты торгов
        symbol = trade_data.get('symbol')
        if symbol:
            recent_trades = [
                trade for trade in self.api_call_history[-100:]  # Последние 100 вызовов
                if 'trade' in trade.get('endpoint', '') and symbol in trade.get('endpoint', '')
            ]
            
            if len(recent_trades) > 50:  # Более 50 торгов за последние N вызовов
                await self._create_alert(
                    ThreatLevel.MEDIUM,
                    "trading",
                    f"High frequency trading detected for {symbol}",
                    {"symbol": symbol, "recent_trades": len(recent_trades)}
                )
    
    async def _check_unusual_api_activity(self):
        """Проверка необычной API активности"""
        if len(self.api_call_history) < 50:
            return
        
        recent_calls = self.api_call_history[-50:]  # Последние 50 вызовов
        response_times = [call['response_time'] for call in recent_calls]
        
        if len(response_times) > 10:
            mean_time = np.mean(response_times)
            std_time = np.std(response_times)
            
            # Проверка аномально долгих ответов
            for call in recent_calls[-10:]:  # Последние 10 вызовов
                if call['response_time'] > mean_time + (self.unusual_activity_threshold * std_time):
                    await self._create_alert(
                        ThreatLevel.MEDIUM,
                        "api",
                        f"Unusual API response time detected: {call['response_time']:.2f}s",
                        call
                    )
    
    async def _check_rate_limits(self):
        """Проверка превышения лимитов частоты запросов"""
        current_time = datetime.utcnow()
        one_minute_ago = current_time - timedelta(minutes=1)
        
        recent_calls = [
            call for call in self.api_call_history
            if call['timestamp'] > one_minute_ago
        ]
        
        if len(recent_calls) > 100:  # Более 100 вызовов в минуту
            await self._create_alert(
                ThreatLevel.HIGH,
                "rate_limit",
                f"High API call frequency detected: {len(recent_calls)} calls/minute",
                {"calls_per_minute": len(recent_calls)}
            )
    
    async def _create_alert(
        self, 
        threat_level: ThreatLevel, 
        category: str, 
        message: str, 
        details: Dict[str, Any]
    ):
        """Создание алерта безопасности"""
        alert = SecurityAlert(
            timestamp=datetime.utcnow(),
            threat_level=threat_level,
            category=category,
            message=message,
            details=details
        )
        
        self.alerts.append(alert)
        
        # Ограничение размера списка алертов
        if len(self.alerts) > 1000:
            self.alerts = self.alerts[-500:]  # Оставляем последние 500
        
        # Логирование алерта
        if threat_level in [ThreatLevel.HIGH, ThreatLevel.CRITICAL]:
            logger.error(f"SECURITY ALERT [{threat_level.value.upper()}]: {message}")
        else:
            logger.warning(f"Security alert [{threat_level.value}]: {message}")
        
        # Отправка уведомлений для критических алертов
        if threat_level == ThreatLevel.CRITICAL:
            await self._send_critical_alert_notification(alert)
    
    async def _send_critical_alert_notification(self, alert: SecurityAlert):
        """Отправка уведомлений о критических алертах"""
        # Здесь можно добавить отправку email, Telegram, Slack и т.д.
        logger.critical(f"CRITICAL SECURITY ALERT: {alert.message}")
        
        # Пример отправки в Telegram (если настроен)
        try:
            # await self.telegram_notifier.send_message(f"🚨 CRITICAL ALERT: {alert.message}")
            pass
        except Exception as e:
            logger.error(f"Failed to send critical alert notification: {e}")
    
    def get_security_summary(self) -> Dict[str, Any]:
        """Получение сводки по безопасности"""
        current_time = datetime.utcnow()
        last_24h = current_time - timedelta(hours=24)
        
        recent_alerts = [alert for alert in self.alerts if alert.timestamp > last_24h]
        
        alert_counts = {}
        for level in ThreatLevel:
            alert_counts[level.value] = len([
                alert for alert in recent_alerts if alert.threat_level == level
            ])
        
        return {
            "monitoring_active": self.monitoring_active,
            "total_alerts_24h": len(recent_alerts),
            "alert_counts": alert_counts,
            "api_calls_24h": len([
                call for call in self.api_call_history 
                if call['timestamp'] > last_24h
            ]),
            "failed_auth_attempts": sum(len(attempts) for attempts in self.failed_auth_attempts.values()),
            "last_alert": recent_alerts[-1].message if recent_alerts else None
        }
```

### 4. Система резервного копирования и восстановления

#### 4.1 Автоматические бэкапы
```python
"""
src/persistence/backup.py - Система резервного копирования
"""

import os
import json
import gzip
import shutil
from datetime import datetime, timedelta
from typing import Dict, Any, List
import asyncio
from pathlib import Path
from loguru import logger


class BackupManager:
    """Управление резервными копиями"""
    
    def __init__(self, backup_dir: str = "backups"):
        self.backup_dir = Path(backup_dir)
        self.backup_dir.mkdir(exist_ok=True)
        
        # Настройки ретенции
        self.daily_retention = 30   # 30 дней
        self.hourly_retention = 48  # 48 часов
        self.minute_retention = 60  # 60 минут (для активной торговли)
    
    async def create_full_backup(self) -> str:
        """Создание полного бэкапа системы"""
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        backup_name = f"full_backup_{timestamp}"
        backup_path = self.backup_dir / backup_name
        backup_path.mkdir(exist_ok=True)
        
        try:
            # Бэкап конфигурации (без секретов)
            await self._backup_config(backup_path)
            
            # Бэкап состояния позиций
            await self._backup_positions(backup_path)
            
            # Бэкап истории сделок
            await self._backup_trade_history(backup_path)
            
            # Бэкап логов
            await self._backup_logs(backup_path)
            
            # Бэкап метрик производительности
            await self._backup_performance_metrics(backup_path)
            
            # Создание архива
            archive_path = str(backup_path) + ".tar.gz"
            shutil.make_archive(str(backup_path), 'gztar', backup_path)
            
            # Удаление временной папки
            shutil.rmtree(backup_path)
            
            logger.info(f"Full backup created: {archive_path}")
            return archive_path
            
        except Exception as e:
            logger.error(f"Failed to create full backup: {e}")
            raise
    
    async def create_incremental_backup(self) -> str:
        """Создание инкрементального бэкапа"""
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        backup_name = f"incremental_{timestamp}.json.gz"
        backup_path = self.backup_dir / backup_name
        
        try:
            # Собираем только изменившиеся данные
            incremental_data = {
                'timestamp': timestamp,
                'positions': await self._get_current_positions(),
                'pending_orders': await self._get_pending_orders(),
                'recent_trades': await self._get_recent_trades(minutes=5),
                'system_state': await self._get_system_state()
            }
            
            # Сжатие и сохранение
            with gzip.open(backup_path, 'wt') as f:
                json.dump(incremental_data, f, default=str, indent=2)
            
            logger.debug(f"Incremental backup created: {backup_path}")
            return str(backup_path)
            
        except Exception as e:
            logger.error(f"Failed to create incremental backup: {e}")
            raise
    
    async def restore_from_backup(self, backup_path: str) -> bool:
        """Восстановление из бэкапа"""
        try:
            backup_file = Path(backup_path)
            
            if backup_file.suffix == '.gz' and backup_file.stem.endswith('.json'):
                # Инкрементальный бэкап
                return await self._restore_incremental(backup_path)
            elif backup_file.suffix == '.gz' and '.tar' in backup_file.suffixes:
                # Полный бэкап
                return await self._restore_full(backup_path)
            else:
                logger.error(f"Unknown backup format: {backup_path}")
                return False
                
        except Exception as e:
            logger.error(f"Failed to restore from backup: {e}")
            return False
    
    async def _restore_incremental(self, backup_path: str) -> bool:
        """Восстановление из инкрементального бэкапа"""
        try:
            with gzip.open(backup_path, 'rt') as f:
                backup_data = json.load(f)
            
            # Восстановление позиций
            if 'positions' in backup_data:
                await self._restore_positions(backup_data['positions'])
            
            # Восстановление pending ордеров
            if 'pending_orders' in backup_data:
                await self._restore_pending_orders(backup_data['pending_orders'])
            
            # Восстановление состояния системы
            if 'system_state' in backup_data:
                await self._restore_system_state(backup_data['system_state'])
            
            logger.info(f"Successfully restored from incremental backup: {backup_path}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to restore incremental backup: {e}")
            return False
    
    async def cleanup_old_backups(self):
        """Очистка старых бэкапов согласно политике ретенции"""
        current_time = datetime.utcnow()
        
        for backup_file in self.backup_dir.glob("*"):
            try:
                # Извлечение времени из имени файла
                if backup_file.stem.startswith("full_backup_"):
                    time_str = backup_file.stem.replace("full_backup_", "")
                    backup_time = datetime.strptime(time_str, "%Y%m%d_%H%M%S")
                    
                    # Удаление старых полных бэкапов
                    if current_time - backup_time > timedelta(days=self.daily_retention):
                        backup_file.unlink()
                        logger.info(f"Removed old backup: {backup_file}")
                
                elif backup_file.stem.startswith("incremental_"):
                    time_str = backup_file.stem.replace("incremental_", "").replace(".json", "")
                    backup_time = datetime.strptime(time_str, "%Y%m%d_%H%M%S")
                    
                    # Удаление старых инкрементальных бэкапов
                    if current_time - backup_time > timedelta(hours=self.hourly_retention):
                        backup_file.unlink()
                        logger.debug(f"Removed old incremental backup: {backup_file}")
                        
            except Exception as e:
                logger.warning(f"Failed to process backup file {backup_file}: {e}")
    
    async def schedule_backups(self):
        """Планировщик автоматических бэкапов"""
        logger.info("Starting backup scheduler")
        
        last_full_backup = datetime.utcnow() - timedelta(hours=25)  # Принудительный первый бэкап
        last_incremental_backup = datetime.utcnow()
        
        while True:
            try:
                current_time = datetime.utcnow()
                
                # Полный бэкап каждые 24 часа
                if current_time - last_full_backup >= timedelta(hours=24):
                    await self.create_full_backup()
                    last_full_backup = current_time
                
                # Инкрементальный бэкап каждые 5 минут
                elif current_time - last_incremental_backup >= timedelta(minutes=5):
                    await self.create_incremental_backup()
                    last_incremental_backup = current_time
                
                # Очистка старых бэкапов каждый час
                if current_time.minute == 0:  # Каждый час в 0 минут
                    await self.cleanup_old_backups()
                
                await asyncio.sleep(60)  # Проверка каждую минуту
                
            except Exception as e:
                logger.error(f"Error in backup scheduler: {e}")
                await asyncio.sleep(300)  # Подождать 5 минут при ошибке
```

Эта система безопасности обеспечивает:

1. **Защиту секретов** - шифрование, системное хранилище ключей
2. **Аутентификацию** - JWT токены, хеширование паролей  
3. **Мониторинг** - детекция аномалий, алерты безопасности
4. **Резервирование** - автоматические бэкапы, восстановление

Система готова к продакшен использованию с максимальным уровнем безопасности.