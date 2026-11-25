"""任務 9：搜尋、天氣與 RSS 備援測試。"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

_PLUGIN_DIR = Path(__file__).resolve().parents[2] / "bots" / "e7a08768d11a43a68eee50474c353cbc" / "plugins" / "maibot-toolbox"


def _load(name: str):
    package_name = "_toolbox_task9_test"
    package = types.ModuleType(package_name)
    package.__path__ = [str(_PLUGIN_DIR)]
    sys.modules[package_name] = package
    spec = importlib.util.spec_from_file_location(f"{package_name}.{name}", _PLUGIN_DIR / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_rss2json_fallback_normalizes_items(monkeypatch):
    rss = _load("rss_engine")
    payload = {
        "status": "ok",
        "feed": {"title": "測試 Feed"},
        "items": [{
            "title": "標題",
            "link": "https://example.com/post",
            "pubDate": "Tue, 25 Nov 2026 12:00:00 +0000",
            "author": "作者",
            "content": "<p>摘要內容</p>",
        }],
    }

    async def fake_fetch(*args, **kwargs):
        return json.dumps(payload).encode("utf-8"), 200, ""

    monkeypatch.setattr(rss.netgateway, "fetch_bytes", fake_fetch)
    result = asyncio.run(rss._fetch_rss2json("https://example.com/feed", 10, 5))
    assert result["kind"] == "rss2json"
    assert result["items"][0]["title"] == "標題"
    assert result["items"][0]["published_unix"] > 0


def test_weatherapi_maps_forecast(monkeypatch):
    weather = _load("weather_engine")
    payload = {
        "location": {"name": "Taipei", "region": "Taipei", "country": "Taiwan", "tz_id": "Asia/Taipei"},
        "current": {"temp_c": 25, "feelslike_c": 27, "humidity": 80, "wind_kph": 10, "condition": {"text": "Partly cloudy"}, "air_quality": {"us-epa-index": 2, "pm2_5": 5}},
        "forecast": {"forecastday": [{"date": "2026-11-25", "day": {"maxtemp_c": 28, "mintemp_c": 22, "daily_chance_of_rain": 20, "condition": {"text": "Sunny"}}}]},
    }

    async def fake_fetch(*args, **kwargs):
        return payload, ""

    monkeypatch.setattr(weather, "_fetch_json", fake_fetch)
    result = asyncio.run(weather.fetch_weatherapi("Taipei", 3, "key"))
    assert result["provider"] == "weatherapi"
    assert result["current"]["temperature"] == 25
    assert result["forecast"][0]["rain_prob"] == 20


def test_open_meteo_failure_uses_weatherapi(monkeypatch):
    weather = _load("weather_engine")

    async def fake_fetch(*args, **kwargs):
        return None, "upstream unavailable"

    fallback = AsyncMock(return_value={"provider": "weatherapi", "location": "Taipei"})
    monkeypatch.setattr(weather, "_fetch_json", fake_fetch)
    monkeypatch.setattr(weather, "fetch_weatherapi", fallback)
    result = asyncio.run(weather.fetch_weather("Taipei", weatherapi_key="key"))
    assert result["provider"] == "weatherapi"
    fallback.assert_awaited_once()
