"""按「供應商+模型標識」記錄額度冷卻：免費層額度逐模型獨立計算，打爆的模型在重置前不應再被選用。"""

from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

import re

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

# 冷卻表只在主進程內使用，鍵為 "供應商名|模型標識"，值為冷卻截止的 Unix 時間戳。
_cooldown_until: Dict[str, float] = {}

MINUTE_COOLDOWN_SECONDS = 300.0
MAX_COOLDOWN_SECONDS = 24 * 3600.0

# Google 429 正文中的精確資訊：RetryInfo.retryDelay（秒）與 QuotaFailure 實際計額模型。
_RETRY_DELAY_PATTERN = re.compile(r"'retryDelay':\s*'(\d+)s'")
_VIOLATION_MODEL_PATTERN = re.compile(r"'model':\s*'([A-Za-z0-9._-]+)'|(?<![\w.])model:\s*([A-Za-z0-9._-]+)")


def make_key(provider_name: str, model_identifier: str) -> str:
    return f"{provider_name}|{model_identifier}"


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
    _cooldown_until[key] = max(_cooldown_until.get(key, 0.0), until_ts)


def cooled_until(key: str, now_ts: Optional[float] = None) -> Optional[float]:
    """回傳仍在冷卻中的截止時間戳；已過期會順手清理並回傳 None。"""
    until = _cooldown_until.get(key)
    if until is None:
        return None
    if until <= (now_ts if now_ts is not None else datetime.now(timezone.utc).timestamp()):
        _cooldown_until.pop(key, None)
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


def snapshot() -> Dict[str, float]:
    """供診斷與工具查詢的當前冷卻表快照。"""
    now_ts = datetime.now(timezone.utc).timestamp()
    return {key: until for key, until in list(_cooldown_until.items()) if until > now_ts}
