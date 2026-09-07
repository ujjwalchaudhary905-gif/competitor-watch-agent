"""Load the user's business profile and competitor list from config/*.json."""

import json
from dataclasses import dataclass
from pathlib import Path

_CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"


@dataclass
class BusinessProfile:
    name: str
    site: str
    description: str
    region: str = ""  # e.g. "Canada", "United States", "Morocco", "Global" - blank if not specified


@dataclass
class Competitor:
    id: str
    name: str
    urls: list[str]


def load_business_profile() -> BusinessProfile:
    data = json.loads((_CONFIG_DIR / "business.json").read_text())
    return BusinessProfile(**data)


def load_competitors() -> list[Competitor]:
    data = json.loads((_CONFIG_DIR / "competitors.json").read_text())
    return [Competitor(**c) for c in data]


def save_business_profile(profile: BusinessProfile) -> None:
    path = _CONFIG_DIR / "business.json"
    path.write_text(json.dumps(profile.__dict__, indent=2) + "\n")


def save_competitors(competitors: list[Competitor]) -> None:
    path = _CONFIG_DIR / "competitors.json"
    path.write_text(json.dumps([c.__dict__ for c in competitors], indent=2) + "\n")
