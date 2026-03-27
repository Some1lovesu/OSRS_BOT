"""Async client for the Wise Old Man v2 API."""

import aiohttp
from typing import Optional

WOM_BASE = "https://api.wiseoldman.net/v2"

SKILL_ORDER = [
    "overall", "attack", "defence", "strength", "hitpoints", "ranged",
    "prayer", "magic", "cooking", "woodcutting", "fletching", "fishing",
    "firemaking", "crafting", "smithing", "mining", "herblore", "agility",
    "thieving", "slayer", "farming", "runecrafting", "hunter", "construction",
]

SKILL_EMOJIS = {
    "overall": "⚔️", "attack": "⚔️", "defence": "🛡️", "strength": "💪",
    "hitpoints": "❤️", "ranged": "🏹", "prayer": "🙏", "magic": "🔮",
    "cooking": "🍳", "woodcutting": "🪓", "fletching": "🏹", "fishing": "🎣",
    "firemaking": "🔥", "crafting": "🔨", "smithing": "⚒️", "mining": "⛏️",
    "herblore": "🌿", "agility": "🏃", "thieving": "🗡️", "slayer": "💀",
    "farming": "🌾", "runecrafting": "🌀", "hunter": "🦊", "construction": "🏠",
}


class WomClient:
    def __init__(self, api_key: Optional[str] = None):
        self._api_key = api_key
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            headers = {"User-Agent": "OSRS-Discord-Bot/1.0"}
            if self._api_key:
                headers["x-api-key"] = self._api_key
            self._session = aiohttp.ClientSession(headers=headers)
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    async def _get(self, path: str, params: Optional[dict] = None) -> dict | list | None:
        session = await self._get_session()
        url = f"{WOM_BASE}{path}"
        async with session.get(url, params=params) as resp:
            if resp.status == 404:
                return None
            resp.raise_for_status()
            return await resp.json()

    async def get_player(self, username: str) -> Optional[dict]:
        """Fetch full player details by RSN."""
        return await self._get(f"/players/{username}")

    async def get_player_gains(self, username: str, period: str = "day") -> Optional[dict]:
        """Fetch player gains for a given period (day, week, month, year)."""
        return await self._get(f"/players/{username}/gained", params={"period": period})

    async def update_player(self, username: str) -> Optional[dict]:
        """Trigger a player update on WOM (POST)."""
        session = await self._get_session()
        url = f"{WOM_BASE}/players/{username}"
        async with session.post(url) as resp:
            if resp.status == 404:
                return None
            resp.raise_for_status()
            return await resp.json()

    async def get_player_records(self, username: str, period: Optional[str] = None, metric: Optional[str] = None) -> Optional[list]:
        """Fetch a player's personal records."""
        params = {}
        if period:
            params["period"] = period
        if metric:
            params["metric"] = metric
        return await self._get(f"/players/{username}/records", params=params or None)

    async def get_player_achievements(self, username: str) -> Optional[list]:
        """Fetch a player's WOM achievements."""
        return await self._get(f"/players/{username}/achievements")

    async def get_leaderboard(self, metric: str, period: str = "week", player_type: Optional[str] = None) -> Optional[list]:
        """Fetch the global records leaderboard for a metric."""
        params: dict = {"metric": metric, "period": period}
        if player_type:
            params["playerType"] = player_type
        return await self._get("/records/leaderboard", params=params)

    async def get_player_names(self, username: str) -> Optional[list]:
        """Fetch name change history for a player."""
        return await self._get(f"/players/{username}/names")
