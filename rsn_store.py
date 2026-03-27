"""Persistent storage for tracked RSNs using a simple JSON file."""

import json
import os
from pathlib import Path

RSN_FILE = Path("rsns.json")


class RsnStore:
    def __init__(self, path: Path = RSN_FILE):
        self._path = path
        self._rsns: list[str] = self._load()

    def _load(self) -> list[str]:
        if self._path.exists():
            try:
                with open(self._path) as f:
                    data = json.load(f)
                    return [str(r) for r in data if r]
            except (json.JSONDecodeError, ValueError):
                return []
        return []

    def _save(self):
        with open(self._path, "w") as f:
            json.dump(self._rsns, f, indent=2)

    def get_all(self) -> list[str]:
        return list(self._rsns)

    def add(self, username: str) -> bool:
        """Returns True if added, False if already present."""
        normalized = username.strip().lower()
        if normalized in [r.lower() for r in self._rsns]:
            return False
        self._rsns.append(username.strip())
        self._save()
        return True

    def remove(self, username: str) -> bool:
        """Returns True if removed, False if not found."""
        normalized = username.strip().lower()
        for i, r in enumerate(self._rsns):
            if r.lower() == normalized:
                self._rsns.pop(i)
                self._save()
                return True
        return False
