"""Typed, narrow decisions backed by TypeSafe AI's JEV endpoint."""

from typing import Literal, TypeVar, get_args, get_origin

import aiohttp
from pydantic import BaseModel

from kyberos.core.config import KyberosConfig


Decision = TypeVar("Decision", bound=BaseModel)


class DecisionEngine:
    """Evaluate boolean and literal-choice decision schemas against application state."""

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
            if not field.description:
                raise ValueError(f"Decision field '{name}' needs a description")
            if field.annotation is bool:
                questions[name] = {"type": "noul", "instructions": field.description}
            elif get_origin(field.annotation) is Literal and all(
                isinstance(option, str) for option in get_args(field.annotation)
            ):
                options = get_args(field.annotation)
                criteria = (field.json_schema_extra or {}).get("criteria", {})
                questions[name] = {
                    "type": "choice",
                    "instructions": field.description,
                    "criteria": {option: criteria.get(option) for option in options},
                }
            else:
                raise ValueError(f"Decision field '{name}' must be a bool or string Literal")
        if not questions:
            raise ValueError("Decision schema must contain a supported field")

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
        for name, question in questions.items():
            answer = answers[name]
            if answer["type"] != question["type"]:
                raise ValueError(f"Unexpected answer type for '{name}'")
            if question["type"] == "choice":
                choice = answer["choice"]
                if choice not in question["criteria"]:
                    raise ValueError(f"Invalid choice for '{name}'")
                values[name] = choice
            else:
                probability = answer["noul"]
                if isinstance(probability, bool) or not isinstance(probability, (int, float)) or not 0 <= probability <= 1:
                    raise ValueError(f"Invalid probability for '{name}'")
                values[name] = probability >= 0.5
        return schema.model_validate(values)
