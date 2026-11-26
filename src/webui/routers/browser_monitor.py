"""WebUI 無頭瀏覽器監看代理：轉發 toolbox 插件的本機 CDP screencast/控制 WebSocket。"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional

import aiohttp
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect

router = APIRouter(prefix="/browser-monitor", tags=["browser-monitor"])
_PLUGIN_ID = "maibot-toolbox"


async def _invoke_monitor_api(name: str, args: Optional[Dict[str, Any]] = None, timeout_ms: int = 30000) -> Dict[str, Any]:
    from src.plugin_runtime.integration import get_plugin_runtime_manager

    runtime = get_plugin_runtime_manager()
    for supervisor in runtime.supervisors:
        entry = supervisor.api_registry.get_api(_PLUGIN_ID, name, version="1")
        if entry is None or not entry.public:
            continue
        response = await supervisor.invoke_api(
            plugin_id=_PLUGIN_ID,
            component_name=entry.handler_name,
            args=args or {},
            timeout_ms=timeout_ms,
        )
        if response.error:
            raise RuntimeError(response.error)
        payload = response.payload
        if not isinstance(payload, dict) or not payload.get("success"):
            raise RuntimeError(f"瀏覽器監看 API 回應無效：{payload}")
        result = payload.get("result")
        if not isinstance(result, dict):
            raise RuntimeError(f"瀏覽器監看 API 結果無效：{payload}")
        return result
    raise RuntimeError("maibot-toolbox 尚未載入或不提供瀏覽器監看 API")


@router.post("/start")
async def start_browser_monitor() -> Dict[str, Any]:
    try:
        info = await _invoke_monitor_api("browser.monitor.start", timeout_ms=60000)
        return {"success": True, "running": bool(info.get("running"))}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/status")
async def browser_monitor_status() -> Dict[str, Any]:
    try:
        info = await _invoke_monitor_api("browser.monitor.status")
        return {
            "running": bool(info.get("running")),
            "controller": info.get("controller", "bot"),
            "clients": int(info.get("clients", 0)),
        }
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/stop")
async def stop_browser_monitor() -> Dict[str, Any]:
    try:
        await _invoke_monitor_api("browser.monitor.stop", timeout_ms=30000)
        return {"success": True}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.websocket("/ws")
async def browser_monitor_websocket(websocket: WebSocket) -> None:
    await websocket.accept()
    upstream: Optional[aiohttp.ClientWebSocketResponse] = None
    session: Optional[aiohttp.ClientSession] = None
    tasks: list[asyncio.Task] = []
    try:
        info = await _invoke_monitor_api("browser.monitor.status")
        if not info.get("running"):
            info = await _invoke_monitor_api("browser.monitor.start", timeout_ms=60000)
        base_url = str(info.get("base_url") or "")
        token = str(info.get("token") or "")
        if not base_url or not token:
            raise RuntimeError("瀏覽器監看 session 尚未就緒")
        session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=None, sock_read=None))
        upstream = await session.ws_connect(f"{base_url}/ws?token={token}", heartbeat=30)

        async def client_to_upstream() -> None:
            while True:
                message = await websocket.receive_json()
                await upstream.send_json(message)

        async def upstream_to_client() -> None:
            async for message in upstream:
                if message.type == aiohttp.WSMsgType.TEXT:
                    await websocket.send_text(message.data)
                elif message.type == aiohttp.WSMsgType.ERROR:
                    break

        tasks = [asyncio.create_task(client_to_upstream()), asyncio.create_task(upstream_to_client())]
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        for task in done:
            task.result()
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        try:
            await websocket.send_json({"type": "error", "error": str(exc)})
        except Exception:
            pass
    finally:
        for task in tasks:
            task.cancel()
        if upstream is not None:
            await upstream.close()
        if session is not None:
            await session.close()
        try:
            await websocket.close()
        except Exception:
            pass
