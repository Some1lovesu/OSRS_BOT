"""In-game timers — daily/weekly resets and farming patch reference."""

from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _next_daily() -> datetime:
    """Next daily reset = next midnight UTC."""
    now = _utcnow()
    tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return tomorrow


def _next_weekly() -> datetime:
    """Next weekly reset = next Wednesday 00:00 UTC."""
    now = _utcnow()
    days_until_wed = (2 - now.weekday()) % 7  # Wednesday = weekday 2
    if days_until_wed == 0 and now.hour == 0 and now.minute == 0:
        days_until_wed = 7
    elif days_until_wed == 0:
        days_until_wed = 7
    target = (now + timedelta(days=days_until_wed)).replace(hour=0, minute=0, second=0, microsecond=0)
    return target


def _countdown(target: datetime) -> str:
    """Return a human-readable countdown string to target (from now)."""
    delta = target - _utcnow()
    total_seconds = int(delta.total_seconds())
    if total_seconds <= 0:
        return "now"
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours >= 24:
        days = hours // 24
        hours = hours % 24
        return f"{days}d {hours}h {minutes}m"
    if hours > 0:
        return f"{hours}h {minutes}m {seconds}s"
    if minutes > 0:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"


# ── Patch growth reference data ────────────────────────────────────────────────
# Format: (patch_name, growth_time_minutes, notes)
PATCH_TIMES: list[tuple[str, int, str]] = [
    # Allotment / Herb / Flower
    ("Herb",            80,   "80 min · 4 stages × 20 min"),
    ("Allotment",       40,   "40 min · 4 stages × 10 min"),
    ("Flower",          20,   "20 min · 4 stages × 5 min"),
    ("Hops",            60,   "60 min · 4 stages × 15 min"),
    # Trees
    ("Oak tree",       200,   "3h 20m · 5 stages × 40 min"),
    ("Willow tree",    280,   "4h 40m · 7 stages × 40 min"),
    ("Maple tree",     480,   "8h · 8 stages × 60 min"),
    ("Yew tree",       960,   "16h · 8 stages × 120 min"),
    ("Magic tree",    1440,   "24h · 8 stages × 180 min"),
    # Fruit trees
    ("Apple tree",     960,   "16h · 8 stages × 120 min"),
    ("Banana tree",    960,   "16h · 8 stages × 120 min"),
    ("Papaya tree",   1200,   "20h · 8 stages × 150 min"),
    ("Palm tree",     1200,   "20h · 8 stages × 150 min"),
    ("Dragon fruit",  2880,   "48h · 8 stages × 360 min"),
    # Bush
    ("Redberry",       160,   "2h 40m · 4 stages × 40 min"),
    ("Cadavaberry",    240,   "4h · 4 stages × 60 min"),
    ("Dwellberry",     320,   "5h 20m · 4 stages × 80 min"),
    ("Jangerberry",    480,   "8h · 4 stages × 120 min"),
    ("Whiteberry",     640,   "10h 40m · 4 stages × 160 min"),
    ("Poison ivy",     640,   "10h 40m · 4 stages × 160 min"),
    # Special
    ("Birdhouse",       50,   "50 min"),
    ("Giant seaweed",  240,   "4h · 8 stages × 30 min"),
    ("Calquat",       2880,   "48h · 8 stages × 360 min"),
    ("Celastrus",      960,   "16h · 8 stages × 120 min"),
    ("Hardwood (Teak)",      3200,  "~53h · 8 stages × 400 min"),
    ("Hardwood (Mahogany)", 3200,  "~53h · 8 stages × 400 min"),
]


def _fmt_duration(minutes: int) -> str:
    if minutes < 60:
        return f"{minutes}m"
    hours = minutes // 60
    mins  = minutes % 60
    if mins:
        return f"{hours}h {mins}m"
    return f"{hours}h"


def _build_timers_embed() -> discord.Embed:
    now = _utcnow()
    daily  = _next_daily()
    weekly = _next_weekly()

    embed = discord.Embed(
        title="⏱️ OSRS Timers",
        color=0x5865F2,
        timestamp=now,
    )
    embed.set_footer(text="All times UTC")

    embed.add_field(
        name="🕐 Current Game Time",
        value=f"`{now.strftime('%H:%M:%S UTC')}`",
        inline=False,
    )

    embed.add_field(
        name="🌅 Daily Reset",
        value=(
            f"In **{_countdown(daily)}**\n"
            f"at `{daily.strftime('%Y-%m-%d 00:00 UTC')}`\n"
            "Resets: kingdom, daily challenges, Tears of Guthix,\n"
            "herb/allotment patches, shooting star cycle"
        ),
        inline=True,
    )

    embed.add_field(
        name="📅 Weekly Reset",
        value=(
            f"In **{_countdown(weekly)}**\n"
            f"at `{weekly.strftime('%Y-%m-%d 00:00 UTC')}`  (Wednesday)\n"
            "Resets: Leagues tasks, BA points cap,\n"
            "clan wars, some minigame rewards"
        ),
        inline=True,
    )

    embed.add_field(name="\u200b", value="\u200b", inline=False)

    # Shooting star spawn window (approximate)
    embed.add_field(
        name="🌠 Shooting Stars",
        value=(
            "Spawn **every ~90 min** (±15 min) per world\n"
            "Use `/stars` for live tracked locations\n"
            "Mining req: T1=1, T2=10, …, T9=90"
        ),
        inline=False,
    )

    return embed


def _build_patches_embed() -> discord.Embed:
    embed = discord.Embed(
        title="🌿 Farming Patch Growth Times",
        description="Time from planting to harvest-ready. Growth happens in ticks every 5 minutes.",
        color=0x57F287,
    )
    embed.set_footer(text="Times are approximate; disease can pause growth")

    # Split into categories for readability
    categories = {
        "Herbs / Allotments": ["Herb", "Allotment", "Flower", "Hops"],
        "Trees": ["Oak tree", "Willow tree", "Maple tree", "Yew tree", "Magic tree"],
        "Fruit Trees": ["Apple tree", "Banana tree", "Papaya tree", "Palm tree", "Dragon fruit", "Calquat", "Celastrus"],
        "Bushes": ["Redberry", "Cadavaberry", "Dwellberry", "Jangerberry", "Whiteberry", "Poison ivy"],
        "Special": ["Birdhouse", "Giant seaweed", "Hardwood (Teak)", "Hardwood (Mahogany)"],
    }
    patch_lookup = {p[0]: p for p in PATCH_TIMES}

    for cat, names in categories.items():
        lines = []
        for name in names:
            entry = patch_lookup.get(name)
            if entry:
                _, mins, detail = entry
                lines.append(f"**{name}** — `{_fmt_duration(mins)}` · {detail}")
        if lines:
            embed.add_field(name=cat, value="\n".join(lines), inline=False)

    return embed


class TimersCog(commands.Cog):

    @app_commands.command(name="timers", description="Show OSRS daily/weekly reset countdowns and game time.")
    async def timers(self, interaction: discord.Interaction):
        await interaction.response.send_message(embed=_build_timers_embed())

    @app_commands.command(name="daily", description="How long until the next OSRS daily reset (midnight UTC).")
    async def daily(self, interaction: discord.Interaction):
        target = _next_daily()
        embed = discord.Embed(
            title="🌅 Daily Reset",
            description=(
                f"**{_countdown(target)}** until daily reset\n"
                f"Resets at `{target.strftime('%Y-%m-%d 00:00 UTC')}`\n\n"
                "**What resets daily:**\n"
                "• Kingdom of Miscellania (collect resources)\n"
                "• Daily challenges\n"
                "• Tears of Guthix\n"
                "• Herb/allotment/flower patches (some)\n"
                "• Brimhaven Agility Arena ticket cap\n"
                "• Shooting star cycle resets"
            ),
            color=0xFEE75C,
            timestamp=_utcnow(),
        )
        embed.set_footer(text="UTC")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="patches", description="Farming patch growth time reference.")
    async def patches(self, interaction: discord.Interaction):
        await interaction.response.send_message(embed=_build_patches_embed())


async def setup(bot: commands.Bot):
    await bot.add_cog(TimersCog())
