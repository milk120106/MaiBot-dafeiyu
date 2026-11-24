"""額度冷卻與日用量持久化測試。"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from src.llm_models import quota_cooldown as quota


@pytest.fixture
def state_path(tmp_path, monkeypatch):
    path = tmp_path / "llm_quota.json"
    monkeypatch.setattr(quota, "_state_path", path)
    monkeypatch.setattr(quota, "_state_loaded", False)
    monkeypatch.setattr(quota, "_save_task", None)
    monkeypatch.setattr(quota, "_cooldown_until", {})
    monkeypatch.setattr(quota, "_quota_limits", {})
    monkeypatch.setattr(quota, "_daily_usage", {})
    return path


def _reload() -> None:
    quota._cooldown_until.clear()
    quota._quota_limits.clear()
    quota._daily_usage.clear()
    quota._state_loaded = False


def test_cooldown_survives_reload_without_raw_key(state_path):
    key = quota.make_key("Google AI Studio", "gemini-3.8-flash", "sk-secret-value")
    until = datetime.now(timezone.utc).timestamp() + 3600
    quota.mark_cooldown(key, until)

    payload = json.loads(state_path.read_text(encoding="utf-8"))
    assert "sk-secret-value" not in state_path.read_text(encoding="utf-8")
    assert payload["cooldowns"][key] == until

    _reload()
    assert quota.cooled_until(key) == pytest.approx(until)


def test_daily_usage_and_limit_survive_reload(state_path):
    key = quota.make_key("Groq", "model", "gsk-secret")
    now = datetime(2030, 1, 1, 0, 0, tzinfo=timezone.utc).timestamp()
    quota.set_daily_quota(key, 2)
    used, limit, cooled_until = quota.record_usage(key, now_ts=now)
    assert (used, limit, cooled_until) == (1, 2, None)
    used, limit, cooled_until = quota.record_usage(key, now_ts=now)
    assert (used, limit) == (2, 2)
    assert cooled_until is not None

    _reload()
    row = quota.usage_snapshot()[key]
    assert row["used"] == 2
    assert row["limit"] == 2
    assert row["cooled_until"] == pytest.approx(cooled_until)


def test_expired_records_are_dropped_on_reload(state_path):
    now = datetime.now(timezone.utc).timestamp()
    key = quota.make_key("Provider", "model", "key")
    state_path.write_text(json.dumps({
        "version": 1,
        "cooldowns": {key: now - 10},
        "daily_usage": {key: {"used": 99, "reset_at": now - 10}},
        "quota_limits": {key: 50},
    }), encoding="utf-8")

    quota._ensure_state_loaded()
    assert quota.snapshot() == {}
    assert quota.usage_snapshot()[key]["used"] == 0
    assert quota.get_daily_quota(key) == 50
