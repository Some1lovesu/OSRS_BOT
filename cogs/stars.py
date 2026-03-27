"""Shooting Stars tracker — uses Star Miners API with a live-link fallback."""

import asyncio
import logging
import os
import time
from datetime import datetime, timezone

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands, tasks

log = logging.getLogger(__name__)

TRACKER_URL = "https://map.starminers.site/"

# Star Miners API — requires a Bearer JWT configured via STAR_MINERS_TOKEN env var.
# Default base URL can be overridden with STAR_MINERS_URL.
_DEFAULT_API_URL = "https://api.starminers.site"

# Location index → human-readable region name.
# Indices match the star-miners-server openapi schema (0-14).
STAR_LOCATIONS = {
    0:  "Asgarnia",
    1:  "Crandor / Karamja",
    2:  "Feldip Hills / Isle of Souls",
    3:  "Fremennik Lands / Lunar Isle",
    4:  "Great Kourend",
    5:  "Kandarin",
    6:  "Kebos Lowlands",
    7:  "Misthalin",
    8:  "Morytania",
    9:  "Piscatoris / Gnome Stronghold",
    10: "Tirannwn",
    11: "Wilderness",
    12: "Desert",
    13: "Fossil Island",
    14: "Mos Le'Harmless",
}

TIER_MINING_REQ = {i: i * 10 for i in range(1, 10)}  # tier → mining level required


def _fmt_time(unix_ts: int) -> str:
    """Format a unix timestamp as HH:MM UTC."""
    dt = datetime.fromtimestamp(unix_ts, tz=timezone.utc)
    return dt.strftime("%H:%M UTC")


def _mins_until(unix_ts: int) -> int:
    return max(0, int((unix_ts - time.time()) / 60))


def _build_stars_embed(stars: list[dict]) -> discord.Embed:
    embed = discord.Embed(
        title="Shooting Stars — Active Worlds",
        url=TRACKER_URL,
        color=0x5865F2,
        timestamp=datetime.now(timezone.utc),
    )
    embed.set_footer(text="Data via Star Miners community tracker")

    if not stars:
        embed.description = "No active stars reported right now. Check the [live map]({}) for updates.".format(TRACKER_URL)
        return embed

    # Sort by minTime so soonest landing appears first
    stars_sorted = sorted(stars, key=lambda s: s.get("minTime", 0))

    lines = []
    for star in stars_sorted[:20]:  # cap at 20 to avoid embed overflow
        world = star.get("world", "?")
        loc_idx = star.get("location", -1)
        location = STAR_LOCATIONS.get(loc_idx, f"Region {loc_idx}")
        tier = star.get("tier")
        min_t = star.get("minTime", 0)
        max_t = star.get("maxTime", 0)

        tier_str = f"T{tier} (lvl {TIER_MINING_REQ.get(tier, '?')}+)" if tier else "tier unknown"

        if min_t and max_t:
            now = time.time()
            if now < min_t:
                timing = f"lands {_fmt_time(min_t)}–{_fmt_time(max_t)} (~{_mins_until(min_t)}m)"
            elif now < max_t:
                timing = f"landed ✅ (gone by {_fmt_time(max_t)}, ~{_mins_until(max_t)}m left)"
            else:
                timing = "may have despawned"
        else:
            timing = "timing unknown"

        lines.append(f"**W{world}** · {location} · {tier_str} · {timing}")

    embed.description = "\n".join(lines)
    return embed


def _build_fallback_embed() -> discord.Embed:
    embed = discord.Embed(
        title="Shooting Stars Tracker",
        url=TRACKER_URL,
        description=(
            "Live star tracking requires a Star Miners API token (`STAR_MINERS_TOKEN`).\n\n"
            f"View current stars on the **[Star Miners live map]({TRACKER_URL})**.\n\n"
            "Stars land roughly every **90 minutes** (±15 min) on each world. "
            "You need a [RuneLite](https://runelite.net) client with the "
            "**Star Miners** plugin to contribute sightings."
        ),
        color=0xFEE75C,
    )
    embed.set_footer(text="Configure STAR_MINERS_TOKEN in .env for live data")
    return embed


class StarsCog(commands.Cog):
    def __init__(
        self,
        bot: commands.Bot,
        token: str | None,
        api_url: str,
        stars_channel_id: int,
    ):
        self.bot = bot
        self._token = token
        self._api_url = api_url.rstrip("/")
        self._stars_channel_id = stars_channel_id
        self._session: aiohttp.ClientSession | None = None
        # Track the last set of worlds posted to avoid spam
        self._last_posted_worlds: set[int] = set()

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            headers = {"User-Agent": "OSRS-Discord-Bot/1.0"}
            if self._token:
                headers["Authorization"] = f"Bearer {self._token}"
            self._session = aiohttp.ClientSession(headers=headers)
        return self._session

    async def cog_load(self):
        if self._stars_channel_id and self._token:
            self._auto_post_loop.start()

    async def cog_unload(self):
        self._auto_post_loop.cancel()
        if self._session and not self._session.closed:
            await self._session.close()

    async def _fetch_stars(self) -> list[dict] | None:
        """Fetch star data from Star Miners API. Returns None if unavailable."""
        if not self._token:
            return None
        try:
            session = await self._get_session()
            async with session.get(
                f"{self._api_url}/stars",
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status == 401:
                    log.warning("Star Miners API: invalid token (401).")
                    return None
                if resp.status != 200:
                    log.warning("Star Miners API returned %d.", resp.status)
                    return None
                return await resp.json()
        except Exception as exc:
            log.error("Failed to fetch stars: %s", exc)
            return None

    # ── Slash command ──────────────────────────────────────────────────────────

    @app_commands.command(name="stars", description="Show current shooting star locations from the community tracker.")
    async def stars(self, interaction: discord.Interaction):
        await interaction.response.defer()
        data = await self._fetch_stars()
        if data is None:
            await interaction.followup.send(embed=_build_fallback_embed())
        else:
            await interaction.followup.send(embed=_build_stars_embed(data))

    # ── Auto-post loop ─────────────────────────────────────────────────────────

    @tasks.loop(minutes=5)
    async def _auto_post_loop(self):
        """Every 5 minutes, check for newly landed stars and post new ones."""
        await self._check_and_post_new_stars()

    @_auto_post_loop.before_loop
    async def _before_auto_post(self):
        await self.bot.wait_until_ready()

    async def _check_and_post_new_stars(self):
        channel = self.bot.get_channel(self._stars_channel_id)
        if channel is None:
            return

        data = await self._fetch_stars()
        if not data:
            return

        now = time.time()
        # Only care about stars that have already landed
        active = [s for s in data if s.get("minTime", now + 1) <= now]
        current_worlds = {s["world"] for s in active if "world" in s}
        new_worlds = current_worlds - self._last_posted_worlds

        for star in active:
            if star.get("world") not in new_worlds:
                continue
            world = star.get("world", "?")
            loc_idx = star.get("location", -1)
            location = STAR_LOCATIONS.get(loc_idx, f"Region {loc_idx}")
            tier = star.get("tier")
            max_t = star.get("maxTime", 0)
            tier_str = f"T{tier}" if tier else "unknown tier"
            despawn_str = f"gone by {_fmt_time(max_t)}" if max_t else ""

            embed = discord.Embed(
                title=f"Star Landed — W{world}",
                description=f"**Location:** {location}\n**Tier:** {tier_str} (lvl {TIER_MINING_REQ.get(tier, '?')}+)\n{despawn_str}",
                color=0x57F287,
                url=TRACKER_URL,
                timestamp=datetime.now(timezone.utc),
            )
            embed.set_footer(text="Star Miners community tracker")
            await channel.send(embed=embed)
            await asyncio.sleep(0.5)

        self._last_posted_worlds = current_worlds


async def setup(bot: commands.Bot, token: str | None, api_url: str, stars_channel_id: int):
    await bot.add_cog(StarsCog(bot, token, api_url, stars_channel_id))
