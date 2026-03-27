"""GE price lookup and item info via the OSRS Wiki APIs."""

import asyncio
import logging
from difflib import get_close_matches

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

log = logging.getLogger(__name__)

PRICES_BASE = "https://prices.runescape.wiki/api/v1/osrs"
WIKI_API    = "https://oldschool.runescape.wiki/api.php"
WIKI_BASE   = "https://oldschool.runescape.wiki/w"
UA          = "OSRS-Discord-Bot/1.0 (github.com/Some1lovesu/osrs_bot)"

# Precomputed high-alch values for common items aren't in the price API,
# but the mapping endpoint includes them under "highalch".
_item_map:  dict[str, dict] = {}   # name.lower() → {id, name, highalch, lowalch, members, limit}
_id_to_item: dict[int, dict] = {}  # id → same dict


async def _load_mapping(session: aiohttp.ClientSession):
    """Download item name→id mapping from the Wiki prices API."""
    global _item_map, _id_to_item
    try:
        async with session.get(f"{PRICES_BASE}/mapping") as resp:
            resp.raise_for_status()
            items: list[dict] = await resp.json()
        _item_map   = {i["name"].lower(): i for i in items}
        _id_to_item = {i["id"]: i for i in items}
        log.info("Loaded %d items from Wiki prices mapping.", len(_item_map))
    except Exception as exc:
        log.error("Failed to load item mapping: %s", exc)


def _find_item(query: str) -> dict | None:
    """Fuzzy-match a query string to an item in the mapping."""
    q = query.lower().strip()
    if q in _item_map:
        return _item_map[q]
    matches = get_close_matches(q, _item_map.keys(), n=1, cutoff=0.6)
    if matches:
        return _item_map[matches[0]]
    # Substring fallback
    for name, item in _item_map.items():
        if q in name:
            return item
    return None


def _fmt(n: int | None) -> str:
    if n is None or n < 0:
        return "N/A"
    return f"{n:,}"


def _gp(n: int | None) -> str:
    if n is None or n < 0:
        return "N/A"
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M gp"
    if n >= 1_000:
        return f"{n/1_000:.1f}k gp"
    return f"{n:,} gp"


def _build_price_embed(item: dict, price_data: dict) -> discord.Embed:
    name      = item.get("name", "Unknown")
    item_id   = item.get("id")
    highalch  = item.get("highalch")
    lowalch   = item.get("lowalch")
    members   = item.get("members", False)
    ge_limit  = item.get("limit")
    icon_url  = f"https://services.runescape.com/m=itemdb_oldschool/obj_big.gif?id={item_id}" if item_id else None

    high      = price_data.get("high")
    low       = price_data.get("low")
    high_time = price_data.get("highTime")
    low_time  = price_data.get("lowTime")

    margin    = (high - low) if (high and low) else None

    embed = discord.Embed(
        title=name,
        url=f"{WIKI_BASE}/{name.replace(' ', '_')}",
        color=0xF1C40F,
    )
    if icon_url:
        embed.set_thumbnail(url=icon_url)
    embed.set_footer(text="Prices via OSRS Wiki Real-Time API")

    embed.add_field(name="Insta-buy (high)", value=_gp(high),   inline=True)
    embed.add_field(name="Insta-sell (low)", value=_gp(low),    inline=True)
    embed.add_field(name="Margin",           value=_gp(margin), inline=True)

    embed.add_field(name="High Alch",  value=_gp(highalch), inline=True)
    embed.add_field(name="Low Alch",   value=_gp(lowalch),  inline=True)
    embed.add_field(name="GE Limit",   value=_fmt(ge_limit), inline=True)

    tags = []
    if members:
        tags.append("Members")
    if tags:
        embed.add_field(name="Tags", value=" • ".join(tags), inline=False)

    if high and highalch:
        alch_profit = highalch - high - 202  # subtract nature rune ~202gp
        colour = "🟢" if alch_profit > 0 else "🔴"
        embed.add_field(
            name="Alch Profit",
            value=f"{colour} {_gp(alch_profit)} (after nature rune)",
            inline=False,
        )

    return embed


def _build_item_embed(item: dict, wiki_extract: str | None) -> discord.Embed:
    name     = item.get("name", "Unknown")
    item_id  = item.get("id")
    icon_url = f"https://services.runescape.com/m=itemdb_oldschool/obj_big.gif?id={item_id}" if item_id else None

    embed = discord.Embed(
        title=name,
        url=f"{WIKI_BASE}/{name.replace(' ', '_')}",
        color=0x3498DB,
    )
    if icon_url:
        embed.set_thumbnail(url=icon_url)
    embed.set_footer(text="OSRS Wiki")

    if wiki_extract:
        # Strip HTML tags and truncate
        import re
        clean = re.sub(r"<[^>]+>", "", wiki_extract).strip()
        if len(clean) > 500:
            clean = clean[:497] + "…"
        embed.description = clean

    embed.add_field(name="Item ID",   value=str(item_id),                  inline=True)
    embed.add_field(name="Members",   value="Yes" if item.get("members") else "No", inline=True)
    embed.add_field(name="High Alch", value=_gp(item.get("highalch")),     inline=True)
    embed.add_field(name="Low Alch",  value=_gp(item.get("lowalch")),      inline=True)
    embed.add_field(name="GE Limit",  value=_fmt(item.get("limit")),       inline=True)

    return embed


class PricesCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._session: aiohttp.ClientSession | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers={"User-Agent": UA}
            )
        return self._session

    async def cog_load(self):
        session = await self._get_session()
        await _load_mapping(session)

    async def cog_unload(self):
        if self._session and not self._session.closed:
            await self._session.close()

    async def _fetch_price(self, item_id: int) -> dict | None:
        session = await self._get_session()
        try:
            async with session.get(
                f"{PRICES_BASE}/latest",
                params={"id": item_id},
            ) as resp:
                resp.raise_for_status()
                data = await resp.json()
                return data.get("data", {}).get(str(item_id))
        except Exception as exc:
            log.error("Price fetch failed for id %d: %s", item_id, exc)
            return None

    async def _fetch_wiki_extract(self, page_name: str) -> str | None:
        session = await self._get_session()
        try:
            params = {
                "action": "query",
                "format": "json",
                "prop": "extracts",
                "exintro": "1",
                "explaintext": "1",
                "redirects": "1",
                "titles": page_name,
            }
            async with session.get(WIKI_API, params=params) as resp:
                resp.raise_for_status()
                data = await resp.json()
            pages = data.get("query", {}).get("pages", {})
            for page in pages.values():
                extract = page.get("extract", "")
                if extract:
                    return extract
        except Exception as exc:
            log.error("Wiki extract failed for '%s': %s", page_name, exc)
        return None

    # ── /price ─────────────────────────────────────────────────────────────────

    @app_commands.command(name="price", description="Look up the current GE price of an item.")
    @app_commands.describe(item="Item name (e.g. Abyssal whip, Dragon bones)")
    async def price(self, interaction: discord.Interaction, item: str):
        await interaction.response.defer()

        if not _item_map:
            await interaction.followup.send("Item mapping not loaded yet, try again in a moment.", ephemeral=True)
            return

        found = _find_item(item)
        if not found:
            await interaction.followup.send(
                f"Couldn't find an item matching **{item}**. Check the spelling and try again.",
                ephemeral=True,
            )
            return

        price_data = await self._fetch_price(found["id"])
        if not price_data:
            await interaction.followup.send(
                f"Found **{found['name']}** but couldn't fetch its current price.",
                ephemeral=True,
            )
            return

        embed = _build_price_embed(found, price_data)
        await interaction.followup.send(embed=embed)

    # ── /item ──────────────────────────────────────────────────────────────────

    @app_commands.command(name="item", description="Get info about an OSRS item from the Wiki.")
    @app_commands.describe(item="Item name to look up")
    async def item_info(self, interaction: discord.Interaction, item: str):
        await interaction.response.defer()

        if not _item_map:
            await interaction.followup.send("Item mapping not loaded yet, try again in a moment.", ephemeral=True)
            return

        found = _find_item(item)
        if not found:
            await interaction.followup.send(
                f"Couldn't find an item matching **{item}**.",
                ephemeral=True,
            )
            return

        extract = await self._fetch_wiki_extract(found["name"])
        embed = _build_item_embed(found, extract)
        await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(PricesCog(bot))
