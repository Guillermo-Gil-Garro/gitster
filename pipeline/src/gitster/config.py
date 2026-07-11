from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class OwnerPlaylist:
    owner_id: str
    owner_name: str
    playlist: str


@dataclass
class DeckConfig:
    expansion_size: int = 60
    expansion_size_overrides: dict[str, int] = field(default_factory=dict)
    artist_cap_per_expansion: int = 3
    album_cap_per_expansion: int = 2

    def size_for(self, owner_id: str) -> int:
        return self.expansion_size_overrides.get(owner_id, self.expansion_size)


@dataclass
class RunConfig:
    owners: list[OwnerPlaylist]
    deck: DeckConfig


def extract_playlist_id(value: str) -> str:
    value = value.strip()

    if "open.spotify.com/playlist/" in value:
        tail = value.split("open.spotify.com/playlist/", 1)[1]
        return tail.split("?", 1)[0].split("/", 1)[0]

    return value


def load_run_config(path: str | Path) -> RunConfig:
    config_path = Path(path)
    data = json.loads(config_path.read_text(encoding="utf-8"))

    owners = [
        OwnerPlaylist(
            owner_id=item["owner_id"],
            owner_name=item["owner_name"],
            playlist=item["playlist"],
        )
        for item in data["owners"]
    ]
    if not owners:
        raise ValueError(f"{config_path}: 'owners' must contain at least one entry")

    owner_ids = [owner.owner_id for owner in owners]
    if len(set(owner_ids)) != len(owner_ids):
        raise ValueError(f"{config_path}: duplicate owner_id entries in 'owners'")

    deck_data = data.get("deck", {})
    deck = DeckConfig(
        expansion_size=int(deck_data.get("expansion_size", 60)),
        expansion_size_overrides={
            str(key): int(value)
            for key, value in deck_data.get("expansion_size_overrides", {}).items()
        },
        artist_cap_per_expansion=int(deck_data.get("artist_cap_per_expansion", 3)),
        album_cap_per_expansion=int(deck_data.get("album_cap_per_expansion", 2)),
    )

    unknown_overrides = set(deck.expansion_size_overrides) - set(owner_ids)
    if unknown_overrides:
        raise ValueError(
            f"{config_path}: expansion_size_overrides references unknown owner_ids: {sorted(unknown_overrides)}"
        )

    return RunConfig(owners=owners, deck=deck)
