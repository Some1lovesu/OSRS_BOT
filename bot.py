"""OSRS Discord Bot — Wise Old Man integration."""

import asyncio
import logging
import os

import discord
from discord.ext import commands
from dotenv import load_dotenv

from wom_client import WomClient
from rsn_store import RsnStore
import cogs.player as player_cog
import cogs.roundup as roundup_cog
import cogs.stars as stars_cog
import cogs.prices as prices_cog
import cogs.timers as timers_cog

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


def _int_env(key: str, default: int = 0) -> int:
    val = os.getenv(key, str(default))
    try:
        return int(val)
    except ValueError:
        log.warning("Invalid value for %s='%s', using %d.", key, val, default)
        return default


class OsrsBot(commands.Bot):
    def __init__(
        self,
        wom: WomClient,
        store: RsnStore,
        roundup_channel_id: int,
        roundup_hour: int,
        roundup_minute: int,
        stars_token: str | None,
        stars_api_url: str,
        stars_channel_id: int,
    ):
        intents = discord.Intents.default()
        super().__init__(command_prefix="!", intents=intents)
        self.wom = wom
        self.store = store
        self.roundup_channel_id = roundup_channel_id
        self.roundup_hour = roundup_hour
        self.roundup_minute = roundup_minute
        self.stars_token = stars_token
        self.stars_api_url = stars_api_url
        self.stars_channel_id = stars_channel_id

    async def setup_hook(self):
        await player_cog.setup(self, self.wom)
        await roundup_cog.setup(
            self, self.wom, self.store,
            self.roundup_channel_id, self.roundup_hour, self.roundup_minute,
        )
        await stars_cog.setup(
            self,
            token=self.stars_token,
            api_url=self.stars_api_url,
            stars_channel_id=self.stars_channel_id,
        )
        await prices_cog.setup(self)
        await timers_cog.setup(self)

        # Hoist app_commands groups that live on cogs into the top-level tree
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

    wom_api_key        = os.getenv("WOM_API_KEY") or None
    roundup_channel_id = _int_env("ROUNDUP_CHANNEL_ID")
    roundup_time       = os.getenv("ROUNDUP_TIME", "08:00")
    stars_token        = os.getenv("STAR_MINERS_TOKEN") or None
    stars_api_url      = os.getenv("STAR_MINERS_URL", "https://api.starminers.site")
    stars_channel_id   = _int_env("STARS_CHANNEL_ID")

    roundup_hour, roundup_minute = _parse_time(roundup_time)

    wom   = WomClient(api_key=wom_api_key)
    store = RsnStore()

    bot = OsrsBot(
        wom=wom,
        store=store,
        roundup_channel_id=roundup_channel_id,
        roundup_hour=roundup_hour,
        roundup_minute=roundup_minute,
        stars_token=stars_token,
        stars_api_url=stars_api_url,
        stars_channel_id=stars_channel_id,
    )

    async with bot:
        await bot.start(token)


if __name__ == "__main__":
    asyncio.run(main())
