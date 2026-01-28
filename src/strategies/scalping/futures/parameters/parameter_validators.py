from __future__ import annotations

from typing import Any, Dict, List, Optional


def _path(prefix: str, key: str) -> str:
    return f"{prefix}.{key}" if prefix else key


def require_dict(
    source: Any, key: str, errors: List[str], prefix: str = ""
) -> Dict[str, Any]:
    if not isinstance(source, dict):
        errors.append(f"{prefix or 'root'} must be dict")
        return {}
    if key not in source:
        errors.append(f"missing required key: {_path(prefix, key)}")
        return {}
    value = source.get(key)
    if not isinstance(value, dict):
        errors.append(f"{_path(prefix, key)} must be dict")
        return {}
    return value


def require_float(
    source: Dict[str, Any], key: str, errors: List[str], prefix: str = ""
) -> Optional[float]:
    if key not in source:
        errors.append(f"missing required key: {_path(prefix, key)}")
        return None
    value = source.get(key)
    if value is None:
        errors.append(f"{_path(prefix, key)} is None")
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        errors.append(f"{_path(prefix, key)} must be float")
        return None


def require_int(
    source: Dict[str, Any], key: str, errors: List[str], prefix: str = ""
) -> Optional[int]:
    if key not in source:
        errors.append(f"missing required key: {_path(prefix, key)}")
        return None
    value = source.get(key)
    if value is None:
        errors.append(f"{_path(prefix, key)} is None")
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        errors.append(f"{_path(prefix, key)} must be int")
        return None


def require_bool(
    source: Dict[str, Any], key: str, errors: List[str], prefix: str = ""
) -> Optional[bool]:
    if key not in source:
        errors.append(f"missing required key: {_path(prefix, key)}")
        return None
    value = source.get(key)
    if isinstance(value, bool):
        return value
    errors.append(f"{_path(prefix, key)} must be bool")
    return None


def require_str(
    source: Dict[str, Any], key: str, errors: List[str], prefix: str = ""
) -> Optional[str]:
    if key not in source:
        errors.append(f"missing required key: {_path(prefix, key)}")
        return None
    value = source.get(key)
    if isinstance(value, str):
        return value
    errors.append(f"{_path(prefix, key)} must be str")
    return None


def optional_float(source: Dict[str, Any], key: str) -> Optional[float]:
    if key not in source:
        return None
    value = source.get(key)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def optional_str(source: Dict[str, Any], key: str) -> Optional[str]:
    value = source.get(key)
    return value if isinstance(value, str) else None
