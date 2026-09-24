from datetime import datetime

import pytest

from kyberos.interface.adapters.base import BaseProtocol, ProtocolEvent

def test_protocol_event_creation():
    """Test standard valid creation of ProtocolEvent."""
    event = ProtocolEvent(
        platform="discord",
        sender_id="123",
        content="hello"
    )
    assert event.platform == "discord"
    assert event.sender_id == "123"
    assert event.content == "hello"
    assert event.reply_to_id is None
    assert isinstance(event.timestamp, datetime)
    assert event.metadata == {}

def test_protocol_event_full_creation():
    """Test full valid creation of ProtocolEvent."""
    timestamp = datetime.now()
    event = ProtocolEvent(
        platform="telegram",
        sender_id="456",
        content="test",
        reply_to_id="789",
        timestamp=timestamp,
        metadata={"user_name": "bob"}
    )
    assert event.platform == "telegram"
    assert event.sender_id == "456"
    assert event.content == "test"
    assert event.reply_to_id == "789"
    assert event.timestamp == timestamp
    assert event.metadata == {"user_name": "bob"}

# --- Dummy Implementation for testing BaseProtocol ---

class DummyProtocol(BaseProtocol):
    """Concrete implementation of BaseProtocol for testing purposes."""
    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def send_message(self, target_id: str, content: str) -> None:
        pass

@pytest.fixture
def dummy_protocol():
    return DummyProtocol()

@pytest.mark.asyncio
async def test_base_protocol_abstract_methods(dummy_protocol):
    """Verify that calling implemented abstract methods works."""
    await dummy_protocol.start()
    await dummy_protocol.stop()
    await dummy_protocol.send_message("123", "hello")

@pytest.mark.asyncio
async def test_base_protocol_typing_indicators(dummy_protocol):
    """Test default typing indicator implementations (no-ops)."""
    await dummy_protocol.trigger_typing("123")
    await dummy_protocol.stop_typing("123")

def test_base_protocol_default_tool_methods(dummy_protocol):
    """Test default implementations of tool-related methods."""
    assert dummy_protocol.get_tools_definition() == ""
    assert dummy_protocol.get_tool_names() == []
    assert dummy_protocol.get_tools_schema() == []

@pytest.mark.asyncio
async def test_base_protocol_execute_tool_not_implemented(dummy_protocol):
    """Verify that execute_tool raises NotImplementedError by default."""
    with pytest.raises(NotImplementedError, match="Tool test_tool not implemented in DummyProtocol"):
        await dummy_protocol.execute_tool("test_tool", {"arg": "val"})

@pytest.mark.asyncio
async def test_base_protocol_message_handling(dummy_protocol):
    """Test registration and emission of message events."""
    received_event = None
    
    async def handler(event: ProtocolEvent):
        nonlocal received_event
        received_event = event

    dummy_protocol.on_message(handler)
    test_event = ProtocolEvent(platform="test", sender_id="111", content="hi")
    
    await dummy_protocol._emit(test_event)
    assert received_event == test_event

@pytest.mark.asyncio
async def test_base_protocol_emit_no_handler(dummy_protocol):
    """Verify that emitting without a registered handler does not raise errors."""
    test_event = ProtocolEvent(platform="test", sender_id="111", content="hi")
    await dummy_protocol._emit(test_event)
