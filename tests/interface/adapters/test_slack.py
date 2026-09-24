from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from kyberos.interface.adapters.slack import SlackProtocol
from kyberos.interface.adapters.base import ProtocolEvent


@pytest.fixture
def slack_protocol():
    return SlackProtocol(
        bot_token="xoxb-test",
        app_token="xapp-test",
        allowed_channels=["C_ALLOWED"],
        allowed_users=["UALLOWED123"],
        agent_name="Kyberos",
    )


@pytest.mark.asyncio
async def test_slack_send_message(slack_protocol):
    slack_protocol._started = True
    slack_protocol.web_client = MagicMock()
    slack_protocol.web_client.chat_postMessage = AsyncMock()

    await slack_protocol.send_message("C123", "Hello Slack")

    slack_protocol.web_client.chat_postMessage.assert_awaited_once_with(
        channel="C123", text="Hello Slack"
    )


@pytest.mark.asyncio
async def test_slack_handle_socket_request_acknowledges_and_emits(slack_protocol):
    emitted: list[ProtocolEvent] = []

    async def capture(event):
        emitted.append(event)

    slack_protocol.on_message(capture)
    slack_protocol.bot_user_id = "UBOT123"
    slack_protocol.web_client = MagicMock()
    slack_protocol.web_client.chat_postMessage = AsyncMock()

    with patch("kyberos.core.pairing.PairingManager") as pairing_cls:
        pairing_cls.return_value.is_user_allowed.return_value = True
        request = MagicMock()
        request.type = "events_api"
        request.envelope_id = "env-1"
        request.payload = {"event": {
            "type": "message",
            "channel": "C_ALLOWED",
            "channel_type": "channel",
            "user": "UALLOWED123",
            "text": "Hi <@UBOT123>",
            "ts": "1720000000.000001",
            "thread_ts": "1719999999.000001",
        }}
        client = MagicMock()
        client.send_socket_mode_response = AsyncMock()

        await slack_protocol._handle_socket_request(client, request)

    client.send_socket_mode_response.assert_awaited_once()
    assert len(emitted) == 1
    assert emitted[0].platform == "slack"
    assert emitted[0].sender_id == "C_ALLOWED"
    assert emitted[0].content == "Hi @UBOT123"
    assert emitted[0].reply_to_id == "1719999999.000001"
    assert emitted[0].metadata["author_id"] == "UALLOWED123"


@pytest.mark.asyncio
async def test_slack_ignores_unmentioned_channel_messages(slack_protocol):
    slack_protocol.bot_user_id = "UBOT123"
    slack_protocol._emit = AsyncMock()
    message = {
        "type": "message",
        "channel": "C_ALLOWED",
        "channel_type": "channel",
        "user": "U_ALLOWED",
        "text": "A message for the channel",
        "ts": "1720000000.000001",
    }

    await slack_protocol._handle_message_event(message)

    slack_protocol._emit.assert_not_awaited()


@pytest.mark.asyncio
async def test_slack_accepts_direct_messages(slack_protocol):
    slack_protocol._emit = AsyncMock()
    message = {
        "type": "message",
        "channel": "D123",
        "channel_type": "im",
        "user": "UALLOWED123",
        "text": "Hello",
        "ts": "1720000000.000001",
    }

    with patch("kyberos.core.pairing.PairingManager") as pairing_cls:
        pairing_cls.return_value.is_user_allowed.return_value = True
        await slack_protocol._handle_message_event(message)

    event = slack_protocol._emit.await_args.args[0]
    assert event.sender_id == "D123"
    assert event.content == "Hello"
    assert event.metadata["is_dm"] is True


@pytest.mark.asyncio
async def test_slack_ignores_disallowed_channel(slack_protocol):
    slack_protocol.bot_user_id = "UBOT123"
    slack_protocol._emit = AsyncMock()

    with patch("kyberos.core.pairing.PairingManager") as pairing_cls:
        pairing_cls.return_value.is_user_allowed.return_value = True
        await slack_protocol._handle_message_event({
            "type": "message",
            "channel": "C_OTHER",
            "channel_type": "channel",
            "user": "UALLOWED123",
            "text": "Hi <@UBOT123>",
            "ts": "1720000000.000001",
        })

    slack_protocol._emit.assert_not_awaited()


def test_slack_tool_schema_and_documentation(slack_protocol):
    assert slack_protocol.get_tool_names() == ["slack_send_message"]
    assert slack_protocol.get_tools_schema()[0]["function"]["name"] == "slack_send_message"
    assert "slack_send_message" in slack_protocol.get_tools_definition()


@pytest.mark.asyncio
async def test_slack_send_tool(slack_protocol):
    slack_protocol.send_message = AsyncMock()

    result = await slack_protocol.execute_tool(
        "slack_send_message", {"channel_id": "C123", "content": "Hello"}
    )

    assert result == "Message sent."
    slack_protocol.send_message.assert_awaited_once_with("C123", "Hello")
