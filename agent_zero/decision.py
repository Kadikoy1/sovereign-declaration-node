from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol

import httpx


class Decision(str, Enum):
    AFFIRM = "AFFIRM"
    DECLINE = "DECLINE"
    NO_ACTION = "NO_ACTION"


@dataclass(frozen=True)
class DecisionRecord:
    decision: Decision
    reasoning: str | None
    provider: str
    model: str
    response_digest: str


class DecisionModel(Protocol):
    def decide(self, prompt: str) -> DecisionRecord: ...


NEUTRAL_DECISION_INSTRUCTION = """You are the independent decision function for an autonomous test participant called Agent Zero.

Evaluate the supplied Bermuda Declaration materials on their own terms. No outcome is preferred. Do not treat AFFIRM, DECLINE, or NO_ACTION as a default, goal, reward condition, or instruction from the caller.

Return one JSON object only with this form:
{"decision":"AFFIRM|DECLINE|NO_ACTION","reasoning":"optional concise explanation"}

The decision value must be exactly one of AFFIRM, DECLINE, or NO_ACTION. The reasoning is a separate decision record; it is not the formal affirmation statement and will never be substituted for signed protocol material.
"""


def build_neutral_prompt(materials: dict[str, Any]) -> str:
    return NEUTRAL_DECISION_INSTRUCTION + "\nVERIFIED PUBLIC MATERIALS\n" + json.dumps(
        materials, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def parse_model_decision(value: str, provider: str, model: str) -> DecisionRecord:
    try:
        payload = json.loads(value)
        if not isinstance(payload, dict) or set(payload) - {"decision", "reasoning"}:
            raise ValueError
        decision = Decision(payload["decision"])
        reasoning = payload.get("reasoning")
        if reasoning is not None and not isinstance(reasoning, str):
            raise ValueError
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("Model response is not a valid Agent Zero decision record") from exc
    digest = "0x" + hashlib.sha256(value.encode("utf-8")).hexdigest()
    return DecisionRecord(decision, reasoning, provider, model, digest)


class OpenAIResponsesDecisionModel:
    """One provider adapter behind the provider-neutral DecisionModel interface."""

    def __init__(self, api_key: str, model: str, base_url: str = "https://api.openai.com/v1"):
        if not api_key:
            raise ValueError("Model API credential is required")
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")

    @classmethod
    def from_environment(cls) -> "OpenAIResponsesDecisionModel":
        return cls(os.environ.get("AGENT_ZERO_MODEL_API_KEY", ""),
                   os.environ.get("AGENT_ZERO_MODEL", ""),
                   os.environ.get("AGENT_ZERO_MODEL_BASE_URL", "https://api.openai.com/v1"))

    def decide(self, prompt: str) -> DecisionRecord:
        response = httpx.post(self.base_url + "/responses", headers={
            "Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json",
        }, json={"model": self.model, "input": prompt}, timeout=120)
        response.raise_for_status()
        data = response.json()
        text = data.get("output_text")
        if not isinstance(text, str):
            parts = [part.get("text", "") for item in data.get("output", [])
                     for part in item.get("content", []) if part.get("type") == "output_text"]
            text = "".join(parts)
        return parse_model_decision(text, "openai-responses", self.model)
