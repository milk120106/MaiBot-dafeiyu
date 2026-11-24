"""月度預算帳本測試。"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from src.llm_models import monthly_budget


@pytest.fixture
def state_path(tmp_path, monkeypatch):
    path = tmp_path / "llm_monthly_budget.json"
    monkeypatch.setattr(monthly_budget, "_state_path", path)
    monkeypatch.setattr(monthly_budget, "_state_loaded", False)
    monkeypatch.setattr(monthly_budget, "_save_task", None)
    monkeypatch.setattr(monthly_budget, "_limits", {})
    monkeypatch.setattr(monthly_budget, "_usage", {})
    return path


def _reload() -> None:
    monthly_budget._limits.clear()
    monthly_budget._usage.clear()
    monthly_budget._state_loaded = False


def test_usage_and_limits_survive_reload(state_path):
    key = "provider|deadbeef|model"
    state = monthly_budget.record_usage(
        key,
        {"requests": 2, "tokens": 0, "budget_usd": 0, "budget_cny": 0},
        input_tokens=60,
        output_tokens=40,
        price_in=2.0,
        price_out=4.0,
    )
    assert state["requests"] == 1
    assert state["total_tokens"] == 100
    assert state["exceeded"] is False

    _reload()
    restored = monthly_budget.status(key)
    assert restored["requests"] == 1
    assert restored["total_tokens"] == 100
    assert restored["limits"]["requests"] == 2


def test_request_limit_marks_exceeded(state_path):
    key = "provider|deadbeef|model"
    state = monthly_budget.record_usage(key, {"requests": 1}, input_tokens=1, output_tokens=1)
    assert state["exceeded"] is True
    assert state["reasons"] == ["monthly_requests"]


def test_token_limit_marks_exceeded(state_path):
    key = "provider|deadbeef|model"
    state = monthly_budget.record_usage(key, {"tokens": 100}, input_tokens=60, output_tokens=50)
    assert state["exceeded"] is True
    assert state["reasons"] == ["monthly_tokens"]


def test_cached_input_cost_uses_cache_price(state_path):
    key = "provider|deadbeef|model"
    state = monthly_budget.record_usage(
        key,
        {},
        input_tokens=1000,
        output_tokens=100,
        cached_input_tokens=200,
        price_in=2.0,
        price_out=4.0,
        cache_price_in=0.5,
        usd_to_cny=7.0,
    )
    assert state["cost_cny"] == pytest.approx(0.0021)
    assert state["cost_usd"] == pytest.approx(0.0003)


def test_budget_limit_marks_exceeded(state_path):
    key = "provider|deadbeef|model"
    state = monthly_budget.record_usage(
        key,
        {"budget_cny": 0.001},
        input_tokens=1000,
        output_tokens=0,
        price_in=2.0,
    )
    assert state["exceeded"] is True
    assert state["reasons"] == ["monthly_budget_cny"]


def test_next_month_reset_is_taiwan_midnight():
    now = datetime(2026, 11, 30, 23, 59, tzinfo=timezone(timedelta(hours=8)))
    reset = datetime.fromtimestamp(monthly_budget.next_month_reset_ts(now.timestamp()), tz=timezone(timedelta(hours=8)))
    assert reset == datetime(2026, 12, 1, 0, 0, tzinfo=timezone(timedelta(hours=8)))
