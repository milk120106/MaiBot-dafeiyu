"""WebUI 瀏覽器監看代理與控制鎖測試。"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock

from src.webui.routers import browser_monitor as router

_PLUGIN_DIR = Path(__file__).resolve().parents[2] / "bots" / "e7a08768d11a43a68eee50474c353cbc" / "plugins" / "maibot-toolbox"


def test_monitor_rest_endpoints(monkeypatch):
    invoke = AsyncMock(return_value={"running": True, "controller": "user", "clients": 1, "base_url": "http://127.0.0.1:1", "token": "t"})
    monkeypatch.setattr(router, "_invoke_monitor_api", invoke)
    assert asyncio.run(router.start_browser_monitor()) == {"success": True, "running": True}
    status = asyncio.run(router.browser_monitor_status())
    assert status["controller"] == "user" and status["clients"] == 1
    assert asyncio.run(router.stop_browser_monitor()) == {"success": True}


def test_browser_tool_is_blocked_while_user_controls(monkeypatch):
    package_name = "_toolbox_monitor_lock_test"
    package = types.ModuleType(package_name)
    package.__path__ = [str(_PLUGIN_DIR)]
    sys.modules[package_name] = package
    spec = importlib.util.spec_from_file_location(f"{package_name}.browser_monitor", _PLUGIN_DIR / "browser_monitor.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    monitor = module.BrowserMonitor()
    monitor._context = object()
    monitor._page = object()
    monitor._controller = "user"
    monkeypatch.setattr(module, "_monitor", monitor)

    engine_spec = importlib.util.spec_from_file_location(f"{package_name}.browser_engine", _PLUGIN_DIR / "browser_engine.py")
    engine = importlib.util.module_from_spec(engine_spec)
    sys.modules[engine_spec.name] = engine
    engine_spec.loader.exec_module(engine)
    result = asyncio.run(engine.browse_page("https://example.com"))
    assert "目前控制權在主人手中" in result["error"]
