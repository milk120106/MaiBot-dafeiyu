"""固定記憶位測試。"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest

_PLUGIN_DIR = Path(__file__).resolve().parents[2] / "bots" / "e7a08768d11a43a68eee50474c353cbc" / "plugins" / "maibot-toolbox"


def _load():
    package_name = "_toolbox_pinned_test"
    package = types.ModuleType(package_name)
    package.__path__ = [str(_PLUGIN_DIR)]
    sys.modules[package_name] = package
    spec = importlib.util.spec_from_file_location(f"{package_name}.pinned_memory_engine", _PLUGIN_DIR / "pinned_memory_engine.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_pinned_memory_crud_and_prompt(tmp_path, monkeypatch):
    engine = _load()
    monkeypatch.setattr(engine, "_STATE_PATH", tmp_path / "pinned_memory.json")
    first = engine.add_entry("主人偏好繁體中文")
    second = engine.add_entry("重要約定")
    assert len(engine.list_entries()) == 2
    assert "主人偏好繁體中文" in engine.render_prompt()
    engine.update_entry(first["id"], "主人偏好繁體中文與簡潔回覆")
    assert "簡潔回覆" in engine.render_prompt()
    assert engine.delete_entry(second["id"])
    assert len(engine.list_entries()) == 1


def test_pinned_memory_limits(tmp_path, monkeypatch):
    engine = _load()
    monkeypatch.setattr(engine, "_STATE_PATH", tmp_path / "pinned_memory.json")
    with pytest.raises(ValueError):
        engine.add_entry("")
    with pytest.raises(ValueError):
        engine.add_entry("x" * 501)
    for index in range(20):
        engine.add_entry(f"記憶 {index}")
    with pytest.raises(ValueError):
        engine.add_entry("第二十一條")
