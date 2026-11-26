"""輕量音訊分析、混音與 UTAU 拼接測試。"""

from __future__ import annotations

import importlib.util
import io
import sys
import types
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

_PLUGIN_DIR = Path(__file__).resolve().parents[2] / "bots" / "e7a08768d11a43a68eee50474c353cbc" / "plugins" / "maibot-toolbox"


def _load(name: str):
    package_name = "_toolbox_audio_test"
    package = types.ModuleType(package_name)
    package.__path__ = [str(_PLUGIN_DIR)]
    sys.modules[package_name] = package
    spec = importlib.util.spec_from_file_location(f"{package_name}.{name}", _PLUGIN_DIR / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _wav(seconds: float = 1.0, frequency: float = 440.0) -> bytes:
    sr = 22050
    t = np.arange(int(sr * seconds)) / sr
    data = (0.2 * np.sin(2 * np.pi * frequency * t)).astype(np.float32)
    output = io.BytesIO()
    sf.write(output, data, sr, format="WAV")
    return output.getvalue()


def test_audio_analyze_and_mix():
    audio = _load("audio_engine")
    import asyncio

    click_sr = 22050
    click = np.zeros(click_sr * 3, dtype=np.float32)
    for start in range(0, len(click), click_sr // 2):
        click[start:start + 400] += 0.4 * np.sin(2 * np.pi * 880 * np.arange(400) / click_sr)
    click_output = io.BytesIO()
    sf.write(click_output, click, click_sr, format="WAV")
    result = asyncio.run(audio.analyze_audio(click_output.getvalue(), "clicks.wav"))
    assert result["duration_sec"] == 3.0
    assert result["bpm"] > 0
    assert result["key"] and result["spectral_energy"]
    assert isinstance(result["chords"], list) and isinstance(result["chord_progression"], list)

    mixed = asyncio.run(audio.mix_audio([
        {"name": "a.wav", "data": _wav(1.0, 440), "volume": 0.5},
        {"name": "b.wav", "data": _wav(1.0, 880), "volume": 0.3, "fade_in_ms": 100},
    ], output_format="wav"))
    assert mixed["data"].startswith(b"RIFF")
    assert mixed["tracks"] == 2


def test_ust_parse_and_pinyin_concat(tmp_path):
    utau = _load("utau_engine")
    import asyncio

    ust = "[#VERSION]\n1.0\n[#SETTING]\nTempo=120\n[#0000]\nLyric=你\nNote=C4\nDuration=500\n[#0001]\nLyric=好\nNote=D4\nDuration=500\n"
    parsed = utau.parse_ust(ust.encode("utf-16"))
    assert parsed["duration_sec"] == 1.0
    assert len(parsed["notes"]) == 2

    bank = tmp_path / "demo"
    (bank / "CV").mkdir(parents=True)
    (bank / "CV" / "ni.wav").write_bytes(_wav(0.2))
    (bank / "CV" / "hao.wav").write_bytes(_wav(0.2))
    result = asyncio.run(utau.concat_pinyin("你好", str(tmp_path), "demo"))
    assert result["syllables"] == 2
    assert result["data"].startswith(b"RIFF")
