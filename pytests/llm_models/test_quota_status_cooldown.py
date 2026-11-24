"""HTTP 狀態重試耗盡後的短冷卻測試。"""

from src.llm_models import quota_cooldown as quota


def test_503_uses_two_minute_cooldown():
    assert quota.retry_exhausted_cooldown_seconds(503) == 120.0


def test_429_uses_five_minute_cooldown():
    assert quota.retry_exhausted_cooldown_seconds(429) == quota.MINUTE_COOLDOWN_SECONDS


def test_other_statuses_do_not_force_cooldown():
    assert quota.retry_exhausted_cooldown_seconds(500) is None
    assert quota.retry_exhausted_cooldown_seconds(502) is None
    assert quota.retry_exhausted_cooldown_seconds(504) is None
