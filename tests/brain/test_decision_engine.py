from unittest.mock import AsyncMock, MagicMock, patch
from typing import Literal

import pytest
from pydantic import BaseModel, Field

from kyberos.brain.decision_engine import DecisionEngine
from kyberos.core.config import KyberosConfig


class HeartbeatDecision(BaseModel):
    actionable: bool = Field(description="Is any task actionable now?")


@pytest.fixture
def config():
    config = KyberosConfig()
    config.keys.typesafe = "test-key"
    return config


@pytest.mark.asyncio
@pytest.mark.parametrize("probability, expected", [(0.8, True), (0.2, False), (0.5, True)])
async def test_decide_sends_typed_question_and_returns_model(config, probability, expected):
    response = MagicMock()
    response.json = AsyncMock(return_value={
        "answers": {"actionable": {"type": "noul", "noul": probability}}
    })
    session = MagicMock()
    session.post.return_value.__aenter__ = AsyncMock(return_value=response)
    session.post.return_value.__aexit__ = AsyncMock(return_value=None)
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)

    with patch("kyberos.brain.decision_engine.aiohttp.ClientSession", return_value=session):
        result = await DecisionEngine(config).decide(
            HeartbeatDecision, {"heartbeat_content": "Check logs", "current_time": "2026-09-25T09:00:00-04:00"}
        )

    assert isinstance(result, HeartbeatDecision)
    assert result.actionable is expected
    args, kwargs = session.post.call_args
    assert args == (DecisionEngine.ENDPOINT,)
    assert kwargs["headers"] == {"Authorization": "Bearer test-key"}
    assert kwargs["json"] == {
        "state": {"heartbeat_content": "Check logs", "current_time": "2026-09-25T09:00:00-04:00"},
        "model": "jev-latest",
        "questions": {"actionable": {"type": "noul", "instructions": "Is any task actionable now?"}},
    }


@pytest.mark.asyncio
async def test_decide_rejects_missing_key(config):
    config.keys.typesafe = None
    with pytest.raises(ValueError, match="API key"):
        await DecisionEngine(config).decide(HeartbeatDecision, {})


@pytest.mark.asyncio
async def test_decide_rejects_unsupported_schema(config):
    class Unsupported(BaseModel):
        explanation: str = Field(description="Explain the answer")

    with pytest.raises(ValueError, match="bool or string Literal"):
        await DecisionEngine(config).decide(Unsupported, {})


@pytest.mark.asyncio
async def test_decide_choice_maps_literal_options(config):
    class LogCategory(BaseModel):
        category: Literal["memory", "noise"] = Field(
            description="Which category fits?",
            json_schema_extra={"criteria": {"memory": "Durable fact", "noise": "No lasting value"}},
        )

    response = MagicMock()
    response.json = AsyncMock(return_value={
        "answers": {"category": {"type": "choice", "choice": "memory"}}
    })
    session = MagicMock()
    session.post.return_value.__aenter__ = AsyncMock(return_value=response)
    session.post.return_value.__aexit__ = AsyncMock(return_value=None)
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)

    with patch("kyberos.brain.decision_engine.aiohttp.ClientSession", return_value=session):
        result = await DecisionEngine(config).decide(LogCategory, {"log_chunk": "User likes cats"})

    assert result.category == "memory"
    assert session.post.call_args.kwargs["json"]["questions"] == {
        "category": {
            "type": "choice",
            "instructions": "Which category fits?",
            "criteria": {"memory": "Durable fact", "noise": "No lasting value"},
        }
    }


@pytest.mark.asyncio
async def test_decide_choice_rejects_unknown_option(config):
    class LogCategory(BaseModel):
        category: Literal["memory", "noise"] = Field(description="Which category fits?")

    response = MagicMock()
    response.json = AsyncMock(return_value={
        "answers": {"category": {"type": "choice", "choice": "other"}}
    })
    session = MagicMock()
    session.post.return_value.__aenter__ = AsyncMock(return_value=response)
    session.post.return_value.__aexit__ = AsyncMock(return_value=None)
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)

    with patch("kyberos.brain.decision_engine.aiohttp.ClientSession", return_value=session):
        with pytest.raises(ValueError, match="Invalid choice"):
            await DecisionEngine(config).decide(LogCategory, {})


@pytest.mark.asyncio
async def test_decide_rejects_invalid_answer(config):
    response = MagicMock()
    response.json = AsyncMock(return_value={
        "answers": {"actionable": {"type": "noul", "noul": 1.5}}
    })
    session = MagicMock()
    session.post.return_value.__aenter__ = AsyncMock(return_value=response)
    session.post.return_value.__aexit__ = AsyncMock(return_value=None)
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)

    with patch("kyberos.brain.decision_engine.aiohttp.ClientSession", return_value=session):
        with pytest.raises(ValueError, match="Invalid probability"):
            await DecisionEngine(config).decide(HeartbeatDecision, {})


@pytest.mark.asyncio
async def test_decide_propagates_endpoint_failure(config):
    response = MagicMock()
    response.raise_for_status.side_effect = RuntimeError("unreachable")
    session = MagicMock()
    session.post.return_value.__aenter__ = AsyncMock(return_value=response)
    session.post.return_value.__aexit__ = AsyncMock(return_value=None)
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)

    with patch("kyberos.brain.decision_engine.aiohttp.ClientSession", return_value=session):
        with pytest.raises(RuntimeError, match="unreachable"):
            await DecisionEngine(config).decide(HeartbeatDecision, {})
