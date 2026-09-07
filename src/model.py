"""Shared Claude model factory (Anthropic API directly — no Bedrock)."""

import os

from dotenv import load_dotenv
from strands.models.anthropic import AnthropicModel

load_dotenv()

DEFAULT_MODEL_ID = "claude-sonnet-4-5-20250929"


def get_model(model_id: str = DEFAULT_MODEL_ID, max_tokens: int = 2048) -> AnthropicModel:
    """Build an AnthropicModel for use by any Strands Agent in this project."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError("Set ANTHROPIC_API_KEY in your environment or .env file")

    return AnthropicModel(model_id=model_id, max_tokens=max_tokens)
