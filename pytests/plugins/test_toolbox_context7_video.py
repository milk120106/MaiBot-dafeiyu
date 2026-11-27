"""Context7 文件查詢與 MP4 抽幀工具測試。"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock

_PLUGIN_DIR = Path(__file__).resolve().parents[2] / "bots" / "e7a08768d11a43a68eee50474c353cbc" / "plugins" / "maibot-toolbox"


def _load(name: str):
    package_name = "_toolbox_ctx7_video_test"
    package = types.ModuleType(package_name)
    package.__path__ = [str(_PLUGIN_DIR)]
    sys.modules[package_name] = package
    spec = importlib.util.spec_from_file_location(f"{package_name}.{name}", _PLUGIN_DIR / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_context7_search_then_docs(monkeypatch):
    ctx = _load("context7_engine")
    search_payload = {"results": [{"id": "/reactjs/react.dev", "title": "React", "description": "docs", "trustScore": 9.7, "totalSnippets": 5000, "versions": []}]}
    monkeypatch.setattr(ctx.netgateway, "fetch_json", AsyncMock(return_value=(search_payload, 200, "")))
    monkeypatch.setattr(ctx.netgateway, "fetch_bytes", AsyncMock(return_value=(b"### useState example\nimport { useState }", 200, "")))
    result = asyncio.run(ctx.query_context7("react", topic="useState", tokens=800))
    assert result["library_id"] == "/reactjs/react.dev"
    assert "useState" in result["docs"]
    assert result["candidates"][0]["title"] == "React"


def test_context7_empty_query():
    ctx = _load("context7_engine")
    result = asyncio.run(ctx.query_context7("  "))
    assert result.get("error")


def test_video_frames_orchestration(monkeypatch, tmp_path):
    ve = _load("video_engine")
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"\x00\x00\x00\x18ftypmp42")

    async def fake_run(args, timeout=40):
        out_path = Path(args[-1])
        out_path.write_bytes(b"\xff\xd8\xff\xe0fakejpeg")
        return 0, b"", b""

    monkeypatch.setattr(ve, "_probe_duration", AsyncMock(return_value=6.0))
    monkeypatch.setattr(ve, "_run", fake_run)
    monkeypatch.setattr(ve, "_resolve_bin", lambda name, configured="": f"/usr/bin/{name}")
    result = asyncio.run(ve.extract_video_frames(str(source), frames=3))
    assert not result.get("error"), result
    assert result["duration"] == 6.0
    assert len(result["frames"]) == 3
    assert all(Path(f["path"]).is_file() for f in result["frames"])
    import shutil
    shutil.rmtree(result["temp_dir"], ignore_errors=True)


def test_video_missing_source():
    ve = _load("video_engine")
    result = asyncio.run(ve.extract_video_frames(""))
    assert result.get("error")