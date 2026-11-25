"""任務 11：創作、文件與安全壓縮測試。"""

from __future__ import annotations

import importlib.util
import io
import sys
import types
import zipfile
from pathlib import Path

_PLUGIN_DIR = Path(__file__).resolve().parents[2] / "bots" / "e7a08768d11a43a68eee50474c353cbc" / "plugins" / "maibot-toolbox"


def _load():
    package_name = "_toolbox_creative_test"
    package = types.ModuleType(package_name)
    package.__path__ = [str(_PLUGIN_DIR)]
    sys.modules[package_name] = package
    spec = importlib.util.spec_from_file_location(f"{package_name}.creative_engine", _PLUGIN_DIR / "creative_engine.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_zip_roundtrip_and_zip_slip_rejected():
    creative = _load()
    created = creative.create_zip({"folder/a.txt": b"hello"})
    assert created["extension"] == "zip"
    extracted = creative.extract_zip(created["data"])
    assert extracted["files"]["folder/a.txt"] == b"hello"

    seven = creative.create_7z({"a.txt": b"7z"})
    assert creative.extract_7z(seven["data"])["files"]["a.txt"] == b"7z"

    malicious = io.BytesIO()
    with zipfile.ZipFile(malicious, "w") as archive:
        archive.writestr("../evil.txt", "bad")
    try:
        creative.extract_zip(malicious.getvalue())
    except ValueError:
        return
    raise AssertionError("Zip Slip path was accepted")


def test_qr_and_office_generation():
    creative = _load()
    qr = creative.make_qr("https://example.com")
    assert qr["data"].startswith(b"\x89PNG")
    docx = creative.create_office("docx", "標題", "第一行\n第二行")
    assert docx["data"].startswith(b"PK")
    pdf = creative.create_office("pdf", "中文標題", "繁體中文內容")
    assert pdf["data"].startswith(b"%PDF")


def test_jar_inspection_without_extraction():
    creative = _load()
    jar = io.BytesIO()
    with zipfile.ZipFile(jar, "w") as archive:
        archive.writestr("fabric.mod.json", '{"id":"demo","version":"1.0"}')
        archive.writestr("assets/demo/lang/zh_tw.json", '{"item.demo":"測試"}')
        archive.writestr("data/demo/recipe/test.json", '{"type":"minecraft:crafting_shaped"}')
    result = creative.inspect_jar(jar.getvalue())
    assert result["fabric"]["id"] == "demo"
    assert result["languages"][0]["path"].endswith("zh_tw.json")
    assert result["recipes"][0]["data"]["type"] == "minecraft:crafting_shaped"
