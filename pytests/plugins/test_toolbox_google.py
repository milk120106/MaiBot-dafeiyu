"""Google Drive/Gmail 引擎測試（不呼叫真實 API）。"""

from __future__ import annotations

import base64
import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import Mock

_PLUGIN_DIR = Path(__file__).resolve().parents[2] / "bots" / "e7a08768d11a43a68eee50474c353cbc" / "plugins" / "maibot-toolbox"


def _load():
    package_name = "_toolbox_google_test"
    package = types.ModuleType(package_name)
    package.__path__ = [str(_PLUGIN_DIR)]
    sys.modules[package_name] = package
    spec = importlib.util.spec_from_file_location(f"{package_name}.google_engine", _PLUGIN_DIR / "google_engine.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_drive_list_uses_refresh_credentials(monkeypatch):
    engine = _load()
    service = Mock()
    service.files.return_value.list.return_value.execute.return_value = {"files": [{"id": "1", "name": "demo"}]}
    monkeypatch.setattr(engine, "_credentials", lambda *args: object())
    monkeypatch.setattr("googleapiclient.discovery.build", lambda *args, **kwargs: service)
    result = engine.drive_list("cid", "secret", "refresh", limit=5)
    assert result["files"][0]["id"] == "1"
    assert service.files.return_value.list.call_args.kwargs["pageSize"] == 5


def test_gmail_send_builds_raw_message(monkeypatch):
    engine = _load()
    service = Mock()
    service.users.return_value.messages.return_value.send.return_value.execute.return_value = {"id": "sent-1"}
    monkeypatch.setattr(engine, "_credentials", lambda *args: object())
    monkeypatch.setattr("googleapiclient.discovery.build", lambda *args, **kwargs: service)
    result = engine.gmail_send("cid", "secret", "refresh", "to@example.com", "主旨", "內文")
    from email import policy
    from email.parser import BytesParser

    raw = service.users.return_value.messages.return_value.send.call_args.kwargs["body"]["raw"]
    message = BytesParser(policy=policy.default).parsebytes(base64.urlsafe_b64decode(raw))
    assert str(message["Subject"]) == "主旨"
    assert str(message["To"]) == "to@example.com"
    assert result["id"] == "sent-1"
