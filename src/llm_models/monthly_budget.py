"""付費模型月度預算帳本：月請求數、月 Token 數與月金額（CNY/USD）三維限制。

狀態以原子 JSON 快照持久化；鍵沿用 quota_cooldown 的 provider|key_fp|model_identifier，
不保存明文金鑰。月份與重置邊界固定使用 UTC+8（台灣）。
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from src.common.paths import get_instance_root

_STATE_VERSION = 1
_TZ = timezone(timedelta(hours=8))
_state_path = get_instance_root() / "data" / "llm_monthly_budget.json"
_state_loaded = False
_save_task: Optional[asyncio.Task[None]] = None
_limits: Dict[str, Dict[str, float]] = {}
_usage: Dict[str, Dict[str, Any]] = {}
DEFAULT_USD_TO_CNY = 7.0


def _ensure_state_loaded() -> None:
    global _state_loaded
    if _state_loaded:
        return
    if not _state_path.is_file():
        _state_loaded = True
        return
    payload = json.loads(_state_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("version") != _STATE_VERSION:
        raise ValueError(f"月度預算狀態檔版本不合法: {_state_path}")
    limits = payload.get("limits", {})
    usage = payload.get("usage", {})
    if not isinstance(limits, dict) or not isinstance(usage, dict):
        raise ValueError(f"月度預算狀態檔結構不合法: {_state_path}")
    _limits.update({str(key): {name: float(value) for name, value in row.items()} for key, row in limits.items()})
    current_month = _month_key(datetime.now(_TZ))
    for key, row in usage.items():
        if isinstance(row, dict) and row.get("month") == current_month:
            _usage[str(key)] = row
    _state_loaded = True


def _month_key(now: datetime) -> str:
    return now.astimezone(_TZ).strftime("%Y-%m")


def next_month_reset_ts(now_ts: Optional[float] = None) -> float:
    current = datetime.fromtimestamp(now_ts, tz=_TZ) if now_ts is not None else datetime.now(_TZ)
    if current.month == 12:
        next_month = current.replace(year=current.year + 1, month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    else:
        next_month = current.replace(month=current.month + 1, day=1, hour=0, minute=0, second=0, microsecond=0)
    return next_month.timestamp()


def _normalize_limits(
    monthly_requests: int = 0,
    monthly_tokens: int = 0,
    monthly_budget_usd: float = 0.0,
    monthly_budget_cny: float = 0.0,
) -> Dict[str, float]:
    return {
        "requests": max(0, int(monthly_requests or 0)),
        "tokens": max(0, int(monthly_tokens or 0)),
        "budget_usd": max(0.0, float(monthly_budget_usd or 0.0)),
        "budget_cny": max(0.0, float(monthly_budget_cny or 0.0)),
    }


def set_limits(
    key: str,
    monthly_requests: int = 0,
    monthly_tokens: int = 0,
    monthly_budget_usd: float = 0.0,
    monthly_budget_cny: float = 0.0,
) -> None:
    _ensure_state_loaded()
    limits = _normalize_limits(monthly_requests, monthly_tokens, monthly_budget_usd, monthly_budget_cny)
    if any(limits.values()):
        _limits[key] = limits
    else:
        _limits.pop(key, None)
    _schedule_save()


def _state_snapshot() -> Dict[str, Any]:
    return {"version": _STATE_VERSION, "limits": dict(_limits), "usage": dict(_usage)}


def _write_state(snapshot: Dict[str, Any]) -> None:
    _state_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = _state_path.with_name(f".{_state_path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, _state_path)
    finally:
        temporary.unlink(missing_ok=True)


async def _save_state_async() -> None:
    await asyncio.sleep(0.03)
    snapshot = _state_snapshot()
    await asyncio.to_thread(_write_state, snapshot)


def _schedule_save() -> None:
    global _save_task
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        _write_state(_state_snapshot())
        return
    if _save_task is None or _save_task.done():
        _save_task = loop.create_task(_save_state_async())


def _empty_usage(month: str) -> Dict[str, Any]:
    return {
        "month": month,
        "requests": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "cached_input_tokens": 0,
        "cost_cny": 0.0,
        "cost_usd": 0.0,
    }


def _get_usage(key: str) -> Dict[str, Any]:
    month = _month_key(datetime.now(_TZ))
    row = _usage.get(key)
    if row is None or row.get("month") != month:
        row = _empty_usage(month)
        _usage[key] = row
    return row


def status(key: str, configured: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
    """回傳當月用量、生效上限與是否超支；任何一維超標即回傳 exceeded=True。"""
    _ensure_state_loaded()
    limits = dict(_limits.get(key, {}))
    if configured:
        normalized = _normalize_limits(
            int(configured.get("requests", 0)),
            int(configured.get("tokens", 0)),
            float(configured.get("budget_usd", 0.0)),
            float(configured.get("budget_cny", 0.0)),
        )
        if any(normalized.values()):
            limits.update(normalized)
    row = _get_usage(key)
    total_tokens = int(row["input_tokens"]) + int(row["output_tokens"])
    exceeded_reasons = []
    if limits.get("requests", 0) > 0 and row["requests"] >= limits["requests"]:
        exceeded_reasons.append("monthly_requests")
    if limits.get("tokens", 0) > 0 and total_tokens >= limits["tokens"]:
        exceeded_reasons.append("monthly_tokens")
    if limits.get("budget_cny", 0) > 0 and row["cost_cny"] >= limits["budget_cny"]:
        exceeded_reasons.append("monthly_budget_cny")
    if limits.get("budget_usd", 0) > 0 and row["cost_usd"] >= limits["budget_usd"]:
        exceeded_reasons.append("monthly_budget_usd")
    return {
        **row,
        "total_tokens": total_tokens,
        "limits": limits,
        "exceeded": bool(exceeded_reasons),
        "reasons": exceeded_reasons,
        "reset_at": next_month_reset_ts(),
    }


def record_usage(
    key: str,
    configured: Optional[Dict[str, float]] = None,
    *,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cached_input_tokens: int = 0,
    price_in: float = 0.0,
    price_out: float = 0.0,
    cache_price_in: float = 0.0,
    usd_to_cny: float = DEFAULT_USD_TO_CNY,
) -> Dict[str, Any]:
    """累加一次成功請求；價格欄位依 ModelInfo 定義為 CNY / M token。"""
    _ensure_state_loaded()
    if configured:
        set_limits(
            key,
            int(configured.get("requests", 0)),
            int(configured.get("tokens", 0)),
            float(configured.get("budget_usd", 0.0)),
            float(configured.get("budget_cny", 0.0)),
        )
    row = _get_usage(key)
    input_count = max(0, int(input_tokens or 0))
    output_count = max(0, int(output_tokens or 0))
    cached_count = min(input_count, max(0, int(cached_input_tokens or 0)))
    uncached_count = input_count - cached_count
    cost_cny = (
        uncached_count * max(0.0, float(price_in or 0.0))
        + cached_count * max(0.0, float(cache_price_in or 0.0))
        + output_count * max(0.0, float(price_out or 0.0))
    ) / 1_000_000.0
    rate = max(0.01, float(usd_to_cny or DEFAULT_USD_TO_CNY))
    row["requests"] += 1
    row["input_tokens"] += input_count
    row["output_tokens"] += output_count
    row["cached_input_tokens"] += cached_count
    row["cost_cny"] += cost_cny
    row["cost_usd"] += cost_cny / rate
    _schedule_save()
    return status(key, configured)


def snapshot() -> Dict[str, Dict[str, Any]]:
    _ensure_state_loaded()
    return {key: status(key) for key in sorted(set(_limits) | set(_usage))}
