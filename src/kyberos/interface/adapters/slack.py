"""Slack Socket Mode adapter for the Kyberos protocol system."""

import logging
import re
from datetime import datetime, timezone
from typing import Any

from slack_sdk.socket_mode.aiohttp import SocketModeClient
from slack_sdk.socket_mode.request import SocketModeRequest
from slack_sdk.socket_mode.response import SocketModeResponse
from slack_sdk.web.async_client import AsyncWebClient

from kyberos.interface.adapters.base import BaseProtocol, ProtocolEvent

logger = logging.getLogger("kyberos.protocol.slack")


class SlackProtocol(BaseProtocol):
    """Receive Slack messages through Socket Mode and send them via Web API."""

    def __init__(
        self,
        bot_token: str,
        app_token: str,
        allowed_channels: list[str] | None = None,
        allowed_users: list[str] | None = None,
        agent_name: str = "Kyberos",
    ):
        super().__init__()
        self.bot_token = bot_token
        self.app_token = app_token
        self.allowed_channels = allowed_channels or []
        self.allowed_users = allowed_users or []
        self.agent_name = agent_name
        self.web_client: AsyncWebClient | None = None
        self.client: SocketModeClient | None = None
        self.bot_user_id: str | None = None
        self._started = False

    async def start(self) -> None:
        if self._started:
            return

        self.web_client = AsyncWebClient(token=self.bot_token)
        self.client = SocketModeClient(
            app_token=self.app_token,
            web_client=self.web_client,
        )
        self.client.socket_mode_request_listeners.append(self._handle_socket_request)
        try:
            auth = await self.web_client.auth_test()
            self.bot_user_id = auth.get("user_id")
            await self.client.connect()
            self._started = True
            logger.info("Slack Protocol started.")
        except Exception:
            await self._close_web_client()
            self.client = None
            self.web_client = None
            raise

    async def stop(self) -> None:
        if self.client:
            await self.client.disconnect()
        await self._close_web_client()
        self.client = None
        self.web_client = None
        self._started = False
        logger.info("Slack Protocol stopped.")

    async def _close_web_client(self) -> None:
        """Close the aiohttp session created lazily by the Slack SDK."""
        session = self.web_client.session if self.web_client else None
        if session and not session.closed:
            await session.close()

    async def send_message(self, target_id: str, content: str) -> None:
        """Send a message to a Slack channel or direct-message conversation."""
        if not self._started or not self.web_client:
            logger.error("Cannot send message: Slack Protocol not started.")
            return
        try:
            await self.web_client.chat_postMessage(channel=target_id, text=content)
        except Exception as exc:
            logger.error("Failed to send Slack message to %s: %s", target_id, exc)

    async def _handle_socket_request(
        self, client: SocketModeClient, request: SocketModeRequest
    ) -> None:
        """Acknowledge Socket Mode envelopes, then process message events."""
        if request.type != "events_api":
            return

        await client.send_socket_mode_response(
            SocketModeResponse(envelope_id=request.envelope_id)
        )
        event = request.payload.get("event", {})
        if event.get("type") == "message":
            await self._handle_message_event(event)

    async def _handle_message_event(self, message: dict[str, Any]) -> None:
        # Ignore edits, bot messages, and other message subtypes to prevent loops.
        if message.get("subtype") or message.get("bot_id"):
            return
        user_id = message.get("user")
        channel_id = message.get("channel")
        content = message.get("text", "")
        if not user_id or not channel_id or not content.strip():
            return

        is_dm = message.get("channel_type") == "im"
        mention_pattern = rf"<@{re.escape(self.bot_user_id or '')}(?:\|[^>]*)?>" if self.bot_user_id else r"(?!)"
        named_trigger = re.match(
            rf"^{re.escape(self.agent_name)}\b\s*[, :]?\s*", content, re.IGNORECASE
        ) is not None
        should_respond = is_dm or named_trigger or re.search(mention_pattern, content) is not None
        if not should_respond:
            return

        from kyberos.core.pairing import PairingManager

        pairing = PairingManager()
        if not pairing.is_user_allowed("slack", user_id, self.allowed_users):
            code = pairing.create_request("slack", user_id, message.get("username", user_id))
            if self.web_client:
                try:
                    await self.web_client.chat_postMessage(
                        channel=channel_id,
                        text=f"You are not authorized to interact with me. Ask the administrator to approve pairing code `{code}`.",
                    )
                except Exception as exc:
                    logger.error("Failed to send Slack pairing notice: %s", exc)
            return

        if self.allowed_channels and channel_id not in self.allowed_channels and not is_dm:
            return

        # Slack uses <@USERID> mention tokens. Replace them with readable names.
        clean_content = re.sub(r"<@([A-Z0-9]+)(?:\|([^>]+))?>", lambda match: f"@{match.group(2) or match.group(1)}", content)
        try:
            timestamp = datetime.fromtimestamp(float(message["ts"]), tz=timezone.utc)
        except (KeyError, TypeError, ValueError, OSError):
            timestamp = datetime.now(timezone.utc)

        event = ProtocolEvent(
            platform="slack",
            sender_id=channel_id,
            content=clean_content.strip(),
            timestamp=timestamp,
            reply_to_id=message.get("thread_ts"),
            metadata={
                "channel_id": channel_id,
                "channel_name": message.get("channel_name"),
                "author_id": user_id,
                "author_name": message.get("username"),
                "is_dm": is_dm,
                "thread_ts": message.get("thread_ts"),
                "message_ts": message.get("ts"),
            },
        )
        await self._emit(event)

    def get_tools_definition(self) -> str:
        from pathlib import Path

        tools_path = Path(__file__).parent / "slack_tools.md"
        return tools_path.read_text(encoding="utf-8") if tools_path.exists() else ""

    def get_tool_names(self) -> list[str]:
        return ["slack_send_message"]

    def get_tools_schema(self) -> list[dict[str, Any]]:
        return [{
            "type": "function",
            "function": {
                "name": "slack_send_message",
                "description": "Send a message to a Slack channel or direct-message conversation.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "channel_id": {"type": "string", "description": "Slack channel or conversation ID."},
                        "content": {"type": "string", "description": "Message text."},
                    },
                    "required": ["channel_id", "content"],
                },
            },
        }]

    async def execute_tool(self, tool_name: str, args: dict[str, Any]) -> Any:
        if tool_name != "slack_send_message":
            raise NotImplementedError(f"Tool {tool_name} not found in SlackProtocol")
        await self.send_message(args.get("channel_id"), args.get("content"))
        return "Message sent."
