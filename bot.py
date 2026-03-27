"""OSRS Discord Bot — Wise Old Man integration."""

import asyncio
import logging
import os
from pathlib import Path

import discord
from discord.ext import commands
from dotenv import load_dotenv

from wom_client import WomClient
from rsn_store import RsnStore
import cogs.player as player_cog
import cogs.roundup as roundup_cog

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("bot")


def _parse_time(time_str: str) -> tuple[int, int]:
    """Parse 'HH:MM' into (hour, minute)."""
    try:
        h, m = time_str.split(":")
        return int(h), int(m)
    except (ValueError, AttributeError):
        log.warning("Invalid ROUNDUP_TIME '%s', defaulting to 08:00.", time_str)
        return 8, 0


class OsrsBot(commands.Bot):
    def __init__(self, wom: WomClient, store: RsnStore, channel_id: int, roundup_hour: int, roundup_minute: int):
        intents = discord.Intents.default()
        super().__init__(command_prefix="!", intents=intents)
        self.wom = wom
        self.store = store
        self.channel_id = channel_id
        self.roundup_hour = roundup_hour
        self.roundup_minute = roundup_minute

    async def setup_hook(self):
        await player_cog.setup(self, self.wom)
        await roundup_cog.setup(
            self, self.wom, self.store,
            self.channel_id, self.roundup_hour, self.roundup_minute,
        )
        # Add the RSN group from RoundupCog to the command tree
        roundup = self.cogs.get("RoundupCog")
        if roundup:
            self.tree.add_command(roundup.rsn_group)
        await self.tree.sync()
        log.info("Slash commands synced.")

    async def on_ready(self):
        log.info("Logged in as %s (ID: %s)", self.user, self.user.id)

    async def close(self):
        await self.wom.close()
        await super().close()


async def main():
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise RuntimeError("DISCORD_TOKEN environment variable is not set.")

    wom_api_key = os.getenv("WOM_API_KEY") or None
    channel_id_str = os.getenv("ROUNDUP_CHANNEL_ID", "0")
    roundup_time = os.getenv("ROUNDUP_TIME", "08:00")

    try:
        channel_id = int(channel_id_str)
    except ValueError:
        log.warning("Invalid ROUNDUP_CHANNEL_ID '%s', defaulting to 0.", channel_id_str)
        channel_id = 0

    roundup_hour, roundup_minute = _parse_time(roundup_time)

    wom = WomClient(api_key=wom_api_key)
    store = RsnStore()

    bot = OsrsBot(wom, store, channel_id, roundup_hour, roundup_minute)
    async with bot:
        await bot.start(token)


if __name__ == "__main__":
    asyncio.run(main())
