"""Stage 0 sanity-check tool — proves the Strands SDK can call a real Python tool on Claude."""

from strands import tool


@tool
def word_count(text: str) -> int:
    """Count the number of whitespace-separated words in a string.

    Args:
        text: The text to count words in.
    """
    return len(text.split())
