"""VocaDB 日 V 資料與 osu 微調編輯測試。"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock

_PLUGIN_DIR = Path(__file__).resolve().parents[2] / "bots" / "e7a08768d11a43a68eee50474c353cbc" / "plugins" / "maibot-toolbox"


def _load(name: str):
    package_name = "_toolbox_vocadb_osu_test"
    package = types.ModuleType(package_name)
    package.__path__ = [str(_PLUGIN_DIR)]
    sys.modules[package_name] = package
    spec = importlib.util.spec_from_file_location(f"{package_name}.{name}", _PLUGIN_DIR / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_osu_edit_difficulty_and_offset():
    wiki = _load("wiki_engine")
    source = """[General]\nAudioFilename: a.mp3\n[Difficulty]\nHPDrainRate:4\nCircleSize:4\nOverallDifficulty:7\nApproachRate:8\n[TimingPoints]\n0,500,4,2,1,100,1,0\n1000,-50,4,2,1,100,0,0\n[HitObjects]\n64,192,2000,1,0,0:0:0:0:\n"""
    edited = wiki.edit_osu_map(source, ar=9, od=6, cs=3, hp=5, offset_ms=250)
    assert "ApproachRate:9" in edited and "OverallDifficulty:6" in edited
    assert "CircleSize:3" in edited and "HPDrainRate:5" in edited
    assert "250,500,4,2,1,100,1,0" in edited
    assert "64,192,2250,1,0,0:0:0:0:" in edited


def test_vocadb_lyrics_mapping(monkeypatch):
    import asyncio

    music = _load("music_engine")
    song = {
        "id": 1, "name": "千本桜", "artistString": "黒うさP", "lengthSeconds": 240,
        "names": [{"language": "Romaji", "value": "Senbonzakura"}],
        "artists": [
            {"artist": {"name": "黒うさP", "artistType": "Producer"}, "categories": "Producer", "roles": "Composer"},
            {"artist": {"name": "初音ミク", "artistType": "Vocaloid"}, "categories": "Vocalist", "roles": "Vocalist"},
        ],
        "lyrics": [
            {"translationType": "Original", "cultureCodes": ["ja"], "value": "歌詞"},
            {"translationType": "Romanization", "cultureCodes": ["ja"], "value": "kashi"},
        ],
    }
    monkeypatch.setattr(music, "search_vocadb", AsyncMock(return_value=[{"id": 1, "title": "千本桜", "title_romaji": "Senbonzakura", "producers": ["黒うさP"], "vocalists": ["初音ミク"], "url": "https://vocadb.net/S/1"}]))
    monkeypatch.setattr(music, "_get_json_with_session", AsyncMock(return_value=song))
    result = asyncio.run(music.fetch_vocadb_lyrics("千本桜", "黒うさP"))
    assert result["source"] == "vocadb"
    assert result["producers"] == ["黒うさP"]
    assert result["romanizations"][0]["text"] == "kashi"
