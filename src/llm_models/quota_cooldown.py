"""按「供應商+Key 指紋+模型標識」記錄額度冷卻與日用量，並以原子快照持久化到 data/。"""

from datetime import datetime, timedelta, timezone
import asyncio
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import re

from src.common.paths import get_instance_root

_DAILY_PATTERNS = (
    re.compile(r"per\s*day", re.IGNORECASE),
    re.compile(r"\bdaily\b", re.IGNORECASE),
    re.compile(r"\bRPD\b"),
)
_MINUTE_PATTERNS = (
    re.compile(r"per\s*minute", re.IGNORECASE),
    re.compile(r"\bRPM\b"),
    re.compile(r"rate\s*limit", re.IGNORECASE),
)

# 鍵為「供應商名|Key SHA-256 前 8 碼|模型標識」，從不保存明文金鑰。
_cooldown_until: Dict[str, float] = {}
_quota_limits: Dict[str, int] = {}
_daily_usage: Dict[str, Tuple[int, float]] = {}
_STATE_VERSION = 1
_state_path = get_instance_root() / "data" / "llm_quota.json"
_state_loaded = False
_save_task: Optional[asyncio.Task[None]] = None

MINUTE_COOLDOWN_SECONDS = 300.0
MAX_COOLDOWN_SECONDS = 24 * 3600.0

# Google 429 正文中的精確資訊：RetryInfo.retryDelay（秒）與 QuotaFailure 實際計額模型。
_RETRY_DELAY_PATTERN = re.compile(r"'retryDelay':\s*'(\d+)s'")
_VIOLATION_MODEL_PATTERN = re.compile(r"'model':\s*'([A-Za-z0-9._-]+)'|(?<![\w.])model:\s*([A-Za-z0-9._-]+)")


def _key_fingerprint(api_key: str) -> str:
    if not api_key:
        return ""
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:8]


def make_key(provider_name: str, model_identifier: str, api_key: str = "") -> str:
    fp = _key_fingerprint(api_key)
    return f"{provider_name}|{fp}|{model_identifier}" if fp else f"{provider_name}|{model_identifier}"


def _ensure_state_loaded() -> None:
    global _state_loaded
    if _state_loaded:
        return
    if not _state_path.is_file():
        _state_loaded = True
        return
    payload = json.loads(_state_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("version") != _STATE_VERSION:
        raise ValueError(f"額度狀態檔版本不合法: {_state_path}")
    now_ts = datetime.now(timezone.utc).timestamp()
    cooldowns = payload.get("cooldowns", {})
    usage_rows = payload.get("daily_usage", {})
    limits = payload.get("quota_limits", {})
    if not isinstance(cooldowns, dict) or not isinstance(usage_rows, dict) or not isinstance(limits, dict):
        raise ValueError(f"額度狀態檔結構不合法: {_state_path}")
    _cooldown_until.update({str(key): float(until) for key, until in cooldowns.items() if float(until) > now_ts})
    for key, row in usage_rows.items():
        if not isinstance(row, dict):
            raise ValueError(f"額度狀態檔的日用量結構不合法: {key}")
        used = int(row["used"])
        reset_ts = float(row["reset_at"])
        if reset_ts > now_ts:
            _daily_usage[str(key)] = (max(0, used), reset_ts)
    _quota_limits.update({str(key): int(limit) for key, limit in limits.items() if int(limit) > 0})
    _state_loaded = True


def _state_snapshot() -> Dict[str, Any]:
    now_ts = datetime.now(timezone.utc).timestamp()
    return {
        "version": _STATE_VERSION,
        "cooldowns": {key: until for key, until in _cooldown_until.items() if until > now_ts},
        "daily_usage": {
            key: {"used": used, "reset_at": reset_ts}
            for key, (used, reset_ts) in _daily_usage.items()
            if reset_ts > now_ts
        },
        "quota_limits": dict(_quota_limits),
    }


def _write_state(snapshot: Dict[str, Any]) -> None:
    _state_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = _state_path.with_name(f".{_state_path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, _state_path)
    finally:
        temporary.unlink(missing_ok=True)


async def _save_state_async() -> None:
    # 合併同一輪短時間內的多次修改，避免每個模型請求都寫一次磁碟。
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


def classify_quota_error(status_code: int, error_text: str) -> Optional[str]:
    """區分 429 是「日額度耗盡」還是「分鐘速率限制」；無法判讀時回傳 None。"""
    if status_code != 429:
        return None
    if any(pattern.search(error_text) for pattern in _DAILY_PATTERNS):
        return "daily"
    if any(pattern.search(error_text) for pattern in _MINUTE_PATTERNS):
        return "minute"
    return None


def next_daily_reset_ts(now: Optional[datetime] = None) -> float:
    # Google AI Studio 的日額度在太平洋時間午夜重置；不依賴 tzdata，用固定 UTC-8 近似，
    # 夏令時期間會多冷卻一小時，方向安全。
    current = now or datetime.now(timezone.utc)
    pacific_wall = current - timedelta(hours=8)
    next_reset_pacific = (pacific_wall + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return (next_reset_pacific + timedelta(hours=8)).timestamp()


def parse_quota_feedback(error_text: str) -> Tuple[Optional[str], Optional[float], List[str]]:
    """從 429 正文解析 (額度類型, retryDelay 秒, 實際計額模型標識列表)。"""
    kind = classify_quota_error(429, error_text)
    delay_match = _RETRY_DELAY_PATTERN.search(error_text)
    retry_delay = float(delay_match.group(1)) if delay_match else None
    reported: List[str] = []
    for match in _VIOLATION_MODEL_PATTERN.finditer(error_text):
        model = match.group(1) or match.group(2)
        if model and model not in reported:
            reported.append(model)
    return kind, retry_delay, reported


def mark_cooldown(key: str, until_ts: float) -> None:
    _ensure_state_loaded()
    _cooldown_until[key] = max(_cooldown_until.get(key, 0.0), until_ts)
    _schedule_save()


def cooled_until(key: str, now_ts: Optional[float] = None) -> Optional[float]:
    """回傳仍在冷卻中的截止時間戳；已過期會順手清理並回傳 None。"""
    _ensure_state_loaded()
    until = _cooldown_until.get(key)
    if until is None:
        return None
    if until <= (now_ts if now_ts is not None else datetime.now(timezone.utc).timestamp()):
        _cooldown_until.pop(key, None)
        _schedule_save()
        return None
    return until


def partition(model_keys: List[str]) -> Tuple[List[str], Dict[str, float]]:
    """按候選鍵分流可選與冷卻中的模型，回傳 (可用鍵列表, {冷卻鍵: 截止時間戳})。"""
    now_ts = datetime.now(timezone.utc).timestamp()
    available: List[str] = []
    cooled: Dict[str, float] = {}
    for key in model_keys:
        until = cooled_until(key, now_ts)
        if until is None:
            available.append(key)
        else:
            cooled[key] = until
    return available, cooled


def set_daily_quota(key: str, daily_limit: int) -> None:
    """設定指定「供應商|Key指紋|模型」鍵的每日請求上限（<=0 表示清除上限）。"""
    _ensure_state_loaded()
    limit = int(daily_limit or 0)
    if limit <= 0:
        _quota_limits.pop(key, None)
    else:
        _quota_limits[key] = limit
    _schedule_save()


def get_daily_quota(key: str, configured_limit: int = 0) -> int:
    """取得指定鍵生效中的每日請求上限（0 表示無主動計數上限）。"""
    _ensure_state_loaded()
    if configured_limit > 0:
        return int(configured_limit)
    return _quota_limits.get(key, 0)


def record_usage(
    key: str,
    configured_limit: int = 0,
    now_ts: Optional[float] = None,
) -> Tuple[int, int, Optional[float]]:
    """遞增指定「供應商|Key指紋|模型」的當日成功請求數；達到上限時自動標記日額冷卻。

    Returns:
        Tuple[int, int, Optional[float]]: (今日已用次數, 每日上限, 若觸發冷卻則為解禁時間戳否則 None)。
    """
    current_ts = now_ts if now_ts is not None else datetime.now(timezone.utc).timestamp()
    _ensure_state_loaded()
    used, reset_ts = _daily_usage.get(key, (0, 0.0))
    if current_ts >= reset_ts:
        used = 0
        reset_ts = next_daily_reset_ts(datetime.fromtimestamp(current_ts, tz=timezone.utc))
    used += 1
    _daily_usage[key] = (used, reset_ts)
    _schedule_save()

    limit = get_daily_quota(key, configured_limit)
    if limit > 0 and used >= limit:
        mark_cooldown(key, reset_ts)
        return used, limit, reset_ts
    return used, limit, None


def snapshot() -> Dict[str, float]:
    """供診斷與工具查詢的當前冷卻表快照。"""
    _ensure_state_loaded()
    now_ts = datetime.now(timezone.utc).timestamp()
    return {key: until for key, until in list(_cooldown_until.items()) if until > now_ts}


def usage_snapshot() -> Dict[str, Dict[str, Any]]:
    """回傳各「供應商|Key指紋|模型」鍵的當日使用量、上限與冷卻狀態快照。"""
    _ensure_state_loaded()
    now_ts = datetime.now(timezone.utc).timestamp()
    result: Dict[str, Dict[str, Any]] = {}
    all_keys = set(_daily_usage) | set(_quota_limits) | set(_cooldown_until)
    for key in sorted(all_keys):
        used, reset_ts = _daily_usage.get(key, (0, 0.0))
        if reset_ts <= now_ts:
            used = 0
            reset_ts = 0.0
        until = cooled_until(key, now_ts)
        result[key] = {
            "used": used,
            "limit": _quota_limits.get(key, 0),
            "reset_at": reset_ts,
            "cooled_until": until,
        }
    return result
