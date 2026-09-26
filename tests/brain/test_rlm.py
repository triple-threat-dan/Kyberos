import pytest
from unittest.mock import AsyncMock, Mock, patch, MagicMock
from datetime import datetime
from kyberos.brain.rlm import RLMEngine, RecursionGuard, RecursionLimitExceeded, CostLimitExceeded, RepetitiveStressError, TaskContext
from kyberos.core.config import KyberosConfig, AgentsConfig
from kyberos.brain.llm_gateway import LLMGateway
from kyberos.memory.librarian import ArchiveLibrarian
from kyberos.memory.thread_manager import ThreadManager
from kyberos.skills.tool_registry import ToolRegistry

@pytest.fixture
def mock_config():
    config = KyberosConfig()
    config.agents.max_recursion = 3
    config.agents.max_cost = 1.0
    config.agents.max_turns = 5
    return config

@pytest.fixture
def mock_gateway():
    gateway = Mock(spec=LLMGateway)
    gateway.audit_logger = AsyncMock()
    gateway.chat_completion = AsyncMock()
    return gateway

@pytest.fixture
def mock_librarian():
    librarian = Mock(spec=ArchiveLibrarian)
    librarian.search = Mock(return_value=[])
    return librarian

@pytest.fixture
def mock_thread_manager():
    return Mock(spec=ThreadManager)

@pytest.fixture
def mock_tool_registry():
    registry = Mock(spec=ToolRegistry)
    registry.get_tools_schema = Mock(return_value=[])
    registry.get_skills_context = Mock(return_value="")
    registry.get_internal_tools_context = Mock(return_value="")
    registry._internal_tools = {}
    registry._skills = {}
    # Make execute_tool an async mock
    registry.execute_tool = AsyncMock()
    return registry


class TestRecursionGuard:
    def test_check_within_limit(self):
        guard = RecursionGuard(max_depth=3)
        guard.check(current_depth=0)
        guard.check(current_depth=3)

    def test_check_exceeds_limit(self):
        guard = RecursionGuard(max_depth=3)
        with pytest.raises(RecursionLimitExceeded) as exc:
             guard.check(current_depth=4)
        assert "Maximum recursion depth (3) exceeded" in str(exc.value)

class TestRLMEngineInitialization:
    def test_init(self, mock_config, mock_gateway, mock_librarian, mock_thread_manager):
        with patch("kyberos.core.config.load_config", return_value=mock_config):
            engine = RLMEngine(
                config=mock_config,
                gateway=mock_gateway,
                librarian=mock_librarian,
                thread_manager=mock_thread_manager
            )
        assert engine.config == mock_config
        assert engine.gateway == mock_gateway
        assert engine.recursion_guard.max_depth == 3
        assert engine.session_cost == 0.0

class TestRLMEngineSafeguards:
    @pytest.mark.asyncio
    async def test_recursion_limit_in_think(self, mock_config, mock_gateway, mock_librarian, mock_thread_manager):
        with patch("kyberos.core.config.load_config", return_value=mock_config):
            engine = RLMEngine(
                config=mock_config,
                gateway=mock_gateway,
                librarian=mock_librarian,
                thread_manager=mock_thread_manager
            )
        # Should raise immediately if depth is too high
        with pytest.raises(RecursionLimitExceeded):
            await engine.think("test", depth=4)

    @pytest.mark.asyncio
    async def test_cost_limit_exceeded(self, mock_config, mock_gateway, mock_librarian, mock_thread_manager):
        with patch("kyberos.core.config.load_config", return_value=mock_config):
            engine = RLMEngine(
                config=mock_config,
                gateway=mock_gateway,
                librarian=mock_librarian,
                thread_manager=mock_thread_manager
            )
        engine.session_cost = 1.1  # Limit is 1.0
        with pytest.raises(CostLimitExceeded):
            await engine.think("test", depth=0)



class TestRLMEngineLogic:
    def _create_mock_resp(self, content=None, tool_calls=None):
        msg = Mock(content=content)
        msg.tool_calls = tool_calls
        resp = Mock(choices=[Mock(message=msg)])
        resp._hidden_params = {"response_cost": 0.0}
        resp.usage = None
        return resp

    @staticmethod
    def _schema(name):
        return {"type": "function", "function": {"name": name, "description": name, "parameters": {"type": "object"}}}

    @pytest.mark.asyncio
    async def test_tool_categories_filter_schemas(self, mock_config, mock_gateway, mock_librarian, mock_thread_manager, mock_tool_registry):
        mock_config.keys.typesafe = "test-key"
        mock_tool_registry._skills = {"make_report": {}}
        mock_tool_registry.get_tools_schema.return_value = [
            self._schema(name) for name in (
                "memory_search", "read_file", "execute_powershell", "make_report"
            )
        ]
        protocol = Mock()
        protocol.get_tools_schema.return_value = [self._schema("discord_send_message")]
        engine = RLMEngine(mock_config, mock_gateway, mock_librarian, mock_thread_manager,
                           protocol_manager=protocol, tool_registry=mock_tool_registry)
        engine.decision_engine.decide = AsyncMock(return_value=Mock(
            memory=True, files=True, shell=False, skills=False, protocol=False, recursion=False
        ))
        mock_gateway.chat_completion.return_value = self._create_mock_resp(content="Done")

        assert await engine.think("Find a note and read it") == "Done"

        tools = mock_gateway.chat_completion.await_args.kwargs["tools"]
        assert [tool["function"]["name"] for tool in tools] == ["memory_search", "read_file"]
        schema, state = engine.decision_engine.decide.await_args.args
        assert set(schema.model_fields) == {"memory", "files", "shell", "skills", "protocol", "recursion"}
        assert state["request"] == "Find a note and read it"
        assert "make_report" not in mock_gateway.chat_completion.await_args.kwargs["messages"][0]["content"]

    @pytest.mark.asyncio
    async def test_tool_categories_refresh_after_tool_result(self, mock_config, mock_gateway, mock_librarian, mock_thread_manager, mock_tool_registry):
        mock_config.keys.typesafe = "test-key"
        mock_tool_registry._internal_tools = {"read_file": Mock(), "run_python": Mock()}
        mock_tool_registry.get_tools_schema.return_value = [self._schema("read_file"), self._schema("run_python")]
        mock_tool_registry.execute_tool.return_value = "numbers found"
        engine = RLMEngine(mock_config, mock_gateway, mock_librarian, mock_thread_manager,
                           tool_registry=mock_tool_registry)
        engine.decision_engine.decide = AsyncMock(side_effect=[
            Mock(memory=False, files=True, shell=False, skills=False, protocol=False, recursion=False),
            Mock(memory=False, files=False, shell=True, skills=False, protocol=False, recursion=False),
        ])
        tool_call = Mock(id="call_1")
        tool_call.function.name = "read_file"
        tool_call.function.arguments = '{"path": "data.txt"}'
        first_response = self._create_mock_resp(content=None, tool_calls=[tool_call])
        first_response.choices[0].message.model_dump.return_value = {
            "role": "assistant", "content": None,
            "tool_calls": [{"id": "call_1", "function": {"name": "read_file", "arguments": '{"path": "data.txt"}'}}],
        }
        mock_gateway.chat_completion.side_effect = [first_response, self._create_mock_resp(content="Done")]

        assert await engine.think("Read data, then calculate") == "Done"

        calls = mock_gateway.chat_completion.call_args_list
        assert [tool["function"]["name"] for tool in calls[0].kwargs["tools"]] == ["read_file"]
        assert [tool["function"]["name"] for tool in calls[1].kwargs["tools"]] == ["run_python"]
        assert "numbers found" in str(engine.decision_engine.decide.await_args.args[1]["recent_turns"])

    @pytest.mark.asyncio
    async def test_tool_category_failure_uses_all_schemas(self, mock_config, mock_gateway, mock_librarian, mock_thread_manager, mock_tool_registry):
        mock_config.keys.typesafe = "test-key"
        mock_tool_registry.get_tools_schema.return_value = [self._schema("read_file")]
        engine = RLMEngine(mock_config, mock_gateway, mock_librarian, mock_thread_manager,
                           tool_registry=mock_tool_registry)
        engine.decision_engine.decide = AsyncMock(side_effect=RuntimeError("unreachable"))
        mock_gateway.chat_completion.return_value = self._create_mock_resp(content="Done")

        assert await engine.think("Read a file") == "Done"

        names = [tool["function"]["name"] for tool in mock_gateway.chat_completion.await_args.kwargs["tools"]]
        assert names == ["read_file", "spawn_sub_agent"]

    @pytest.mark.asyncio
    async def test_think_loop_basic(self, mock_config, mock_gateway, mock_librarian, mock_thread_manager):
        with patch("kyberos.core.config.load_config", return_value=mock_config):
            engine = RLMEngine(mock_config, mock_gateway, mock_librarian, mock_thread_manager)
        
        # Mock LLM response
        mock_response = self._create_mock_resp(content="Hello world")
        mock_config.agents.max_turns = 1 # Force single turn
        
        mock_gateway.chat_completion.return_value = mock_response

        response = await engine.think("Hi")
        assert response == "Hello world"
        assert mock_gateway.chat_completion.called

    @pytest.mark.asyncio
    async def test_think_loop_with_tool(self, mock_config, mock_gateway, mock_librarian, mock_thread_manager, mock_tool_registry):
        with patch("kyberos.core.config.load_config", return_value=mock_config):
            engine = RLMEngine(mock_config, mock_gateway, mock_librarian, mock_thread_manager, tool_registry=mock_tool_registry)
        
        # Setup Tool Registry
        mock_tool_registry._internal_tools = {"test_tool": Mock()}
        mock_tool_registry.execute_tool.return_value = "Tool Result"

        # Mock LLM responses (Chain: Tool Call -> Final Answer)
        # Turn 1: Tool Call
        # function.name must be set explicitly as attribute, NOT as query param to Mock constructor
        tool_call = Mock(id="call_1")
        tool_call.function.name = "test_tool"
        tool_call.function.arguments = '{"arg": "val"}'
        
        resp1 = self._create_mock_resp(content=None, tool_calls=[tool_call])
        
        # Turn 2: Final Answer
        resp2 = self._create_mock_resp(content="Final Answer")

        mock_gateway.chat_completion.side_effect = [resp1, resp2]

        response = await engine.think("Use tool")
        
        assert response == "Final Answer"
        mock_tool_registry.execute_tool.assert_called_with("test_tool", {"arg": "val"})
        assert mock_gateway.chat_completion.call_count == 2

    @pytest.mark.asyncio
    async def test_think_recurse(self, mock_config, mock_gateway, mock_librarian, mock_thread_manager):
        with patch("kyberos.core.config.load_config", return_value=mock_config):
            engine = RLMEngine(mock_config, mock_gateway, mock_librarian, mock_thread_manager)
        
        # Turn 1: Spawn Sub Agent
        tool_call = Mock(id="call_1")
        tool_call.function.name = "spawn_sub_agent"
        tool_call.function.arguments = '{"instruction": "Sub task"}'
        
        resp1 = self._create_mock_resp(content=None, tool_calls=[tool_call])
        
        # Turn 2: Final Answer (after sub agent returns)
        resp2 = self._create_mock_resp(content="Task Done")

        # Sub-agent response (Recursive call)
        resp_sub = self._create_mock_resp(content="Sub Result")
        
        mock_gateway.chat_completion.side_effect = [resp1, resp_sub, resp2]

        response = await engine.think("Do recursive task")
        
        assert response == "Task Done"
        assert mock_gateway.chat_completion.call_count == 3 

    @pytest.mark.asyncio
    async def test_infinite_loop_detection(self, mock_config, mock_gateway, mock_librarian, mock_thread_manager, mock_tool_registry):
        with patch("kyberos.core.config.load_config", return_value=mock_config):
            engine = RLMEngine(mock_config, mock_gateway, mock_librarian, mock_thread_manager, tool_registry=mock_tool_registry)
        mock_tool_registry._internal_tools = {"repeat_tool": Mock()}
        mock_tool_registry.execute_tool.return_value = "Same result"

        # Mock repetitive tool calls
        tool_call = Mock(id="call_x")
        tool_call.function.name = "repeat_tool"
        tool_call.function.arguments = '{}'
        
        resp = self._create_mock_resp(content=None, tool_calls=[tool_call])

        mock_gateway.chat_completion.return_value = resp
        
        with pytest.raises(RepetitiveStressError):
             await engine.think("Loop me")

    @pytest.mark.asyncio
    async def test_unknown_tool(self, mock_config, mock_gateway, mock_librarian, mock_thread_manager):
        with patch("kyberos.core.config.load_config", return_value=mock_config):
            engine = RLMEngine(mock_config, mock_gateway, mock_librarian, mock_thread_manager)
        
        # Tool Call to unknown tool
        tool_call = Mock(id="call_1")
        tool_call.function.name = "unknown_tool"
        tool_call.function.arguments = '{}'
        
        resp1 = self._create_mock_resp(content=None, tool_calls=[tool_call])
        
        # Recovery
        resp2 = self._create_mock_resp(content="I made a mistake")

        mock_gateway.chat_completion.side_effect = [resp1, resp2]

        await engine.think("Try unknown")
        
        # Check that the error message was sent back
        # The messages list in the 2nd call should contain the tool error
        # Messages at start of call 2: [System, User, Assistant(ToolCall), Tool(Error)]
        call_args = mock_gateway.chat_completion.call_args_list[1]
        messages = call_args.kwargs['messages']
        
        tool_outputs = [m for m in messages if m.get("role") == "tool"]
        assert len(tool_outputs) > 0
        assert "ERROR: Tool 'unknown_tool' does not exist" in tool_outputs[0]["content"]

class TestHeartbeatOptimization:
    @pytest.mark.asyncio
    async def test_heartbeat_empty_input(self, mock_config, mock_gateway, mock_librarian, mock_thread_manager):
        with patch("kyberos.core.config.load_config", return_value=mock_config):
            engine = RLMEngine(mock_config, mock_gateway, mock_librarian, mock_thread_manager)
        result = await engine.check_heartbeat_necessity("   ")
        assert result is False
        mock_gateway.chat_completion.assert_not_called()

    @pytest.mark.asyncio
    async def test_heartbeat_return_true(self, mock_config, mock_gateway, mock_librarian, mock_thread_manager):
        with patch("kyberos.core.config.load_config", return_value=mock_config):
            engine = RLMEngine(mock_config, mock_gateway, mock_librarian, mock_thread_manager)
        
        engine.decision_engine.decide = AsyncMock(return_value=Mock(actionable=True))
        
        result = await engine.check_heartbeat_necessity("Remind me to check logs")
        assert result is True
        
        schema, context = engine.decision_engine.decide.await_args.args
        assert schema.model_fields["actionable"].annotation is bool
        assert context["heartbeat_content"] == "Remind me to check logs"
        assert datetime.fromisoformat(context["current_time"]).tzinfo is not None
        mock_gateway.chat_completion.assert_not_called()

    @pytest.mark.asyncio
    async def test_heartbeat_return_false(self, mock_config, mock_gateway, mock_librarian, mock_thread_manager):
        with patch("kyberos.core.config.load_config", return_value=mock_config):
            engine = RLMEngine(mock_config, mock_gateway, mock_librarian, mock_thread_manager)
        
        engine.decision_engine.decide = AsyncMock(return_value=Mock(actionable=False))

        result = await engine.check_heartbeat_necessity("# Header")
        assert result is False

    @pytest.mark.asyncio
    async def test_heartbeat_future_task_no(self, mock_config, mock_gateway, mock_librarian, mock_thread_manager):
        """Test that a task scheduled for the future returns NO."""
        with patch("kyberos.core.config.load_config", return_value=mock_config):
            engine = RLMEngine(mock_config, mock_gateway, mock_librarian, mock_thread_manager)
        
        engine.decision_engine.decide = AsyncMock(return_value=Mock(actionable=False))

        result = await engine.check_heartbeat_necessity("Remind me this evening")
        assert result is False

    @pytest.mark.asyncio
    async def test_heartbeat_exception_default_true(self, mock_config, mock_gateway, mock_librarian, mock_thread_manager):
        with patch("kyberos.core.config.load_config", return_value=mock_config):
            engine = RLMEngine(mock_config, mock_gateway, mock_librarian, mock_thread_manager)
        engine.decision_engine.decide = AsyncMock(side_effect=Exception("API Error"))
        
        result = await engine.check_heartbeat_necessity("Fail Open")
        assert result is True
