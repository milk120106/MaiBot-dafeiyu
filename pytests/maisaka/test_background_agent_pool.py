"""背景 Subagent 獨立模型池測試。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.config.model_configs import ModelTaskConfig
from src.maisaka.builtin_tool import subagent


def test_model_task_config_accepts_background_agent():
    config = ModelTaskConfig.model_validate({
        "background_agent": {
            "model_list": ["gemini-4-hydrogen", "nvidia/nemotron-3-ultra-550b-a55b", "google/gemma-4-31b-it"],
            "max_tokens": 16384,
            "temperature": 0.5,
            "selection_strategy": "balance",
            "hard_timeout": 600,
        }
    })
    assert config.background_agent.hard_timeout == 600
    assert config.background_agent.max_tokens == 16384
    assert config.background_agent.selection_strategy == "balance"


@pytest.mark.asyncio
async def test_subagent_uses_background_agent_pool(monkeypatch):
    run_sub_agent = AsyncMock(return_value=SimpleNamespace(content="完成", tool_calls=[], raw_messages=[]))
    runtime = SimpleNamespace(run_sub_agent=run_sub_agent, session_id="session", log_prefix="[test]", _tool_registry=SimpleNamespace())
    engine = SimpleNamespace(_build_tool_execution_context=lambda task: None)
    context = SimpleNamespace(runtime=runtime, engine=engine)
    monkeypatch.setattr(subagent, "emit_subagent_round", AsyncMock())
    monkeypatch.setattr(subagent, "load_prompt", lambda name: name)

    outcome = await subagent._run_sub_agent_rounds(
        context,
        task_id="subagent-test",
        task="執行背景研究",
        granted_specs=[],
        tool_usage={},
    )

    assert outcome.conclusion == "完成"
    assert run_sub_agent.await_args.kwargs["model_task_name"] == "background_agent"
