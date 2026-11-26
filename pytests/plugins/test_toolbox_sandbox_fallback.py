"""toolbox 沙盒備援鏈測試（不呼叫真實雲端 API）。"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
from pathlib import Path

import pytest

_PLUGIN_DIR = Path(__file__).resolve().parents[2] / "bots" / "e7a08768d11a43a68eee50474c353cbc" / "plugins" / "maibot-toolbox"


@pytest.fixture
def sandbox_engine():
    package_name = "_toolbox_sandbox_test"
    package = types.ModuleType(package_name)
    package.__path__ = [str(_PLUGIN_DIR)]
    sys.modules[package_name] = package
    spec = importlib.util.spec_from_file_location(f"{package_name}.sandbox_engine", _PLUGIN_DIR / "sandbox_engine.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def disable_network_fallbacks(sandbox_engine, monkeypatch):
    async def unavailable(*args, **kwargs):
        return {"error": "disabled in unit test"}

    monkeypatch.setattr(sandbox_engine, "_execute_judge0", unavailable)
    monkeypatch.setattr(sandbox_engine, "_execute_onlinecompiler", unavailable)


def test_wandbox_success_stops_fallback(sandbox_engine, monkeypatch):
    async def fake_execute(*args, **kwargs):
        return {"provider": "wandbox", "stdout": "ok", "exit_code": 0}

    monkeypatch.setattr(sandbox_engine, "execute_in_sandbox", fake_execute)
    result = asyncio.run(sandbox_engine.execute_with_fallback("python", "print(1)", e2b_api_keys=["e2b"]))
    assert result["provider"] == "wandbox"


def test_wandbox_failure_uses_e2b(sandbox_engine, monkeypatch):
    async def fake_execute(*args, **kwargs):
        return {"error": "wandbox unavailable"}

    monkeypatch.setattr(sandbox_engine, "execute_in_sandbox", fake_execute)
    monkeypatch.setattr(sandbox_engine, "_execute_e2b", lambda *args: {"provider": "e2b", "stdout": "ok", "exit_code": 0})
    result = asyncio.run(sandbox_engine.execute_with_fallback("python", "print(1)", e2b_api_keys=["e2b"]))
    assert result["provider"] == "e2b"


def test_e2b_failure_uses_modal(sandbox_engine, monkeypatch):
    async def fake_execute(*args, **kwargs):
        return {"error": "wandbox unavailable"}

    def fake_e2b(*args):
        raise RuntimeError("e2b unavailable")

    async def fake_modal(*args):
        return {"provider": "modal", "stdout": "ok", "exit_code": 0}

    monkeypatch.setattr(sandbox_engine, "execute_in_sandbox", fake_execute)
    monkeypatch.setattr(sandbox_engine, "_execute_e2b", fake_e2b)
    monkeypatch.setattr(sandbox_engine, "_execute_modal", fake_modal)
    result = asyncio.run(sandbox_engine.execute_with_fallback(
        "python", "print(1)", e2b_api_keys=["e2b"], modal_token_ids=["id"], modal_token_secrets=["secret"]
    ))
    assert result["provider"] == "modal"


def test_non_python_does_not_call_python_only_fallbacks(sandbox_engine, monkeypatch):
    async def fake_execute(*args, **kwargs):
        return {"error": "wandbox unavailable"}

    def forbidden(*args):
        raise AssertionError("non-python must not call E2B")

    monkeypatch.setattr(sandbox_engine, "execute_in_sandbox", fake_execute)
    monkeypatch.setattr(sandbox_engine, "_execute_e2b", forbidden)
    result = asyncio.run(sandbox_engine.execute_with_fallback("javascript", "console.log(1)", e2b_api_keys=["e2b"]))
    assert "error" in result
    assert len(result["attempts"]) == 2
