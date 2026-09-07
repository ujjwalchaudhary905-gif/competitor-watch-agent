"""Stage 0 — minimal Strands agent on Claude (no Bedrock) with one dummy tool."""

import os

from dotenv import load_dotenv
from strands import Agent
from strands.models.anthropic import AnthropicModel

from src.tools.dummy_tool import word_count

load_dotenv()

if not os.environ.get("ANTHROPIC_API_KEY"):
    raise RuntimeError("Set ANTHROPIC_API_KEY in your environment or .env file")

model = AnthropicModel(
    model_id="claude-sonnet-4-5-20250929",
    max_tokens=1024,
)

agent = Agent(model=model, tools=[word_count])


def main() -> None:
    response = agent("How many words are in the sentence: 'Strands agents are working on Claude.'? Use the word_count tool.")
    print("\n--- FINAL RESPONSE ---")
    print(response)


if __name__ == "__main__":
    main()
