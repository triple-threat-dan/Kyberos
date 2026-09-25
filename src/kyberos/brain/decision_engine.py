"""Typed, narrow decisions backed by TypeSafe AI's JEV endpoint."""

from typing import TypeVar

import aiohttp
from pydantic import BaseModel

from kyberos.core.config import KyberosConfig


Decision = TypeVar("Decision", bound=BaseModel)


class DecisionEngine:
    """Evaluate boolean Pydantic decision schemas against application state."""

    ENDPOINT = "https://api.typesafe.ai/v1/systemone"

    def __init__(self, config: KyberosConfig):
        self.config = config

    async def decide(self, schema: type[Decision], context: dict) -> Decision:
        """Return a validated decision; let failures reach the caller's fallback."""
        model = self.config.agents.models["decision_model"]
        if not model.enabled:
            raise ValueError("Decision model is disabled")
        if model.provider != "typesafe":
            raise ValueError("Decision model provider must be typesafe")

        api_key = self.config.keys.typesafe
        if not api_key:
            raise ValueError("TypeSafe API key is not configured")

        questions = {}
        for name, field in schema.model_fields.items():
            if field.annotation is not bool or not field.description:
                raise ValueError(f"Decision field '{name}' must be a described bool")
            questions[name] = {"type": "noul", "instructions": field.description}
        if not questions:
            raise ValueError("Decision schema must contain a boolean field")

        payload = {"state": context, "model": model.model, "questions": questions}
        timeout = aiohttp.ClientTimeout(total=5)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                self.ENDPOINT,
                json=payload,
                headers={"Authorization": f"Bearer {api_key}"},
            ) as response:
                response.raise_for_status()
                data = await response.json()

        answers = data["answers"]
        values = {}
        for name in questions:
            answer = answers[name]
            if answer["type"] != "noul":
                raise ValueError(f"Unexpected answer type for '{name}'")
            probability = answer["noul"]
            if isinstance(probability, bool) or not isinstance(probability, (int, float)) or not 0 <= probability <= 1:
                raise ValueError(f"Invalid probability for '{name}'")
            values[name] = probability >= 0.5
        return schema.model_validate(values)
