from __future__ import annotations

from typing import Any, Dict, Iterable

_MISSING = object()
_ALIAS_KEYS = {
    "sync": "positions_sync",
}


def _is_scalar(value: Any) -> bool:
    return value is None or isinstance(value, (str, int, float, bool))


def _has_key(source: Any, key: str) -> bool:
    if source is None:
        return False
    if isinstance(source, dict):
        return key in source
    return hasattr(source, key)


def _get_value(source: Any, key: str, default: Any = _MISSING) -> Any:
    if source is None:
        return default
    if isinstance(source, dict):
        return source.get(key, default)
    return getattr(source, key, default) if hasattr(source, key) else default


def _to_dict(raw: Any) -> Dict[str, Any]:
    if raw is None:
        return {}
    if isinstance(raw, MergedConfigView):
        return raw.to_dict()
    if isinstance(raw, dict):
        return dict(raw)
    if hasattr(raw, "model_dump"):
        try:
            return dict(raw.model_dump())  # type: ignore[attr-defined]
        except Exception:
            pass
    if hasattr(raw, "dict"):
        try:
            return dict(raw.dict(by_alias=True))  # type: ignore[attr-defined]
        except Exception:
            try:
                return dict(raw.dict())  # type: ignore[attr-defined]
            except Exception:
                pass
    if hasattr(raw, "__dict__"):
        try:
            return dict(raw.__dict__)
        except Exception:
            return {}
    return {}


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


class MergedConfigView:
    """Read-only view: primary config with fallback to secondary config."""

    def __init__(self, primary: Any, fallback: Any):
        self._primary = primary
        self._fallback = fallback

    def _resolve(self, key: str, default: Any = _MISSING) -> Any:
        has_primary = _has_key(self._primary, key)
        has_fallback = _has_key(self._fallback, key)

        if has_primary:
            primary_val = _get_value(self._primary, key, _MISSING)
        else:
            primary_val = _MISSING
        if has_fallback:
            fallback_val = _get_value(self._fallback, key, _MISSING)
        else:
            fallback_val = _MISSING

        if primary_val is _MISSING and fallback_val is _MISSING:
            alias = _ALIAS_KEYS.get(key)
            if alias:
                if _has_key(self._primary, alias):
                    return _get_value(self._primary, alias, default)
                if _has_key(self._fallback, alias):
                    return _get_value(self._fallback, alias, default)
            return default
        if primary_val is _MISSING:
            return fallback_val
        if fallback_val is _MISSING:
            return primary_val

        if _is_scalar(primary_val) or isinstance(primary_val, (list, tuple, set)):
            return primary_val
        if _is_scalar(fallback_val) or isinstance(fallback_val, (list, tuple, set)):
            return primary_val

        if isinstance(primary_val, MergedConfigView):
            return primary_val
        return MergedConfigView(primary_val, fallback_val)

    def get(self, key: str, default: Any = None) -> Any:
        value = self._resolve(key, default=_MISSING)
        return default if value is _MISSING else value

    def __getattr__(self, key: str) -> Any:
        value = self._resolve(key, default=_MISSING)
        if value is _MISSING:
            raise AttributeError(key)
        return value

    def __getitem__(self, key: str) -> Any:
        value = self._resolve(key, default=_MISSING)
        if value is _MISSING:
            raise KeyError(key)
        return value

    def __contains__(self, key: object) -> bool:
        if not isinstance(key, str):
            return False
        return _has_key(self._primary, key) or _has_key(self._fallback, key)

    def keys(self) -> Iterable[str]:
        return self.to_dict().keys()

    def to_dict(self) -> Dict[str, Any]:
        primary_dict = _to_dict(self._primary)
        fallback_dict = _to_dict(self._fallback)
        return _deep_merge(fallback_dict, primary_dict)

    def model_dump(self) -> Dict[str, Any]:
        return self.to_dict()

    def dict(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        return self.to_dict()

    def __repr__(self) -> str:
        return f"MergedConfigView(primary={type(self._primary).__name__}, fallback={type(self._fallback).__name__})"


def get_scalping_view(config: Any) -> Any:
    if config is None:
        return None
    scalping = getattr(config, "scalping", None)
    futures_modules = getattr(config, "futures_modules", None)
    if isinstance(scalping, MergedConfigView):
        return scalping
    if scalping is None and futures_modules is None:
        return None
    return MergedConfigView(scalping, futures_modules)
