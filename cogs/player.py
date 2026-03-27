"""Player search commands."""

import asyncio

import discord
from discord import app_commands
from discord.ext import commands

from wom_client import WomClient, SKILL_ORDER, SKILL_EMOJIS


def _fmt_num(n: int) -> str:
    return f"{n:,}"


def _level_from_xp(xp: int) -> int:
    """Calculate OSRS level from XP."""
    for lvl in range(126, 0, -1):
        if xp >= _xp_for_level(lvl):
            return lvl
    return 1


def _xp_for_level(level: int) -> int:
    total = 0
    for i in range(1, level):
        total += int(i + 300 * (2 ** (i / 7)))
    return total // 4


def _build_player_embed(data: dict) -> discord.Embed:
    name = data.get("displayName", data.get("username", "Unknown"))
    player_type = data.get("type", "unknown").replace("_", " ").title()
    total_xp = data.get("exp", 0)

    embed = discord.Embed(
        title=f"{name}  —  {player_type}",
        url=f"https://wiseoldman.net/players/{name}",
        color=0x5865F2,
    )
    embed.set_thumbnail(url="https://oldschool.runescape.wiki/images/Hiscores_logo.png")
    embed.set_footer(text="Data via Wise Old Man")

    latest = data.get("latestSnapshot", {})
    if not latest:
        embed.description = "No snapshot data available. Try `/update` first."
        return embed

    skills_data = latest.get("data", {}).get("skills", {})
    bosses_data = latest.get("data", {}).get("bosses", {})

    # Skills section
    skill_lines = []
    for skill in SKILL_ORDER:
        entry = skills_data.get(skill)
        if not entry:
            continue
        xp = entry.get("experience", -1)
        level = entry.get("level", -1)
        if skill == "overall":
            skill_lines.insert(
                0,
                f"**Overall** — Level `{_fmt_num(level)}` | XP `{_fmt_num(xp)}`",
            )
        else:
            emoji = SKILL_EMOJIS.get(skill, "•")
            skill_lines.append(
                f"{emoji} **{skill.title()}** `{level}` — `{_fmt_num(xp)} xp`"
            )

    if skill_lines:
        # Overall first, then chunk the rest into two columns
        embed.add_field(name="📊 Skills", value=skill_lines[0], inline=False)
        chunk_size = 12
        rest = skill_lines[1:]
        for i in range(0, len(rest), chunk_size):
            embed.add_field(
                name="\u200b",
                value="\n".join(rest[i : i + chunk_size]),
                inline=True,
            )

    # Boss kills section — only show bosses with kills > 0
    boss_lines = []
    for boss, entry in bosses_data.items():
        kills = entry.get("kills", -1)
        if kills > 0:
            boss_name = boss.replace("_", " ").title()
            boss_lines.append(f"💀 **{boss_name}** — `{_fmt_num(kills)}` kc")

    if boss_lines:
        chunk_size = 15
        for i in range(0, len(boss_lines), chunk_size):
            embed.add_field(
                name="🏆 Boss Kills" if i == 0 else "\u200b",
                value="\n".join(boss_lines[i : i + chunk_size]),
                inline=True,
            )

    return embed


def _build_gains_embed(username: str, gains_data: dict, period: str) -> discord.Embed:
    period_label = {"day": "Last 24 Hours", "week": "Last 7 Days", "month": "Last 30 Days"}.get(
        period, period
    )

    embed = discord.Embed(
        title=f"{username}  —  Gains ({period_label})",
        url=f"https://wiseoldman.net/players/{username}",
        color=0x57F287,
    )
    embed.set_footer(text="Data via Wise Old Man")

    data = gains_data.get("data", {})
    skills = data.get("skills", {})
    bosses = data.get("bosses", {})

    # Skill gains — only show skills with xp gained
    skill_lines = []
    for skill in SKILL_ORDER:
        entry = skills.get(skill, {})
        xp_gained = entry.get("experience", {}).get("gained", 0)
        if xp_gained > 0:
            emoji = SKILL_EMOJIS.get(skill, "•")
            level_gained = entry.get("level", {}).get("gained", 0)
            level_str = f" (+{level_gained} lvl)" if level_gained > 0 else ""
            skill_lines.append(
                f"{emoji} **{skill.title()}**{level_str} — `+{_fmt_num(xp_gained)} xp`"
            )

    if skill_lines:
        chunk_size = 15
        for i in range(0, len(skill_lines), chunk_size):
            embed.add_field(
                name="📈 XP Gained" if i == 0 else "\u200b",
                value="\n".join(skill_lines[i : i + chunk_size]),
                inline=True,
            )
    else:
        embed.add_field(name="📈 XP Gained", value="No XP gains in this period.", inline=False)

    # Boss gains — only show bosses with kills gained
    boss_lines = []
    for boss, entry in bosses.items():
        kills_gained = entry.get("kills", {}).get("gained", 0)
        if kills_gained > 0:
            boss_name = boss.replace("_", " ").title()
            boss_lines.append(f"💀 **{boss_name}** — `+{_fmt_num(kills_gained)}` kc")

    if boss_lines:
        chunk_size = 15
        for i in range(0, len(boss_lines), chunk_size):
            embed.add_field(
                name="🏆 Boss Kills Gained" if i == 0 else "\u200b",
                value="\n".join(boss_lines[i : i + chunk_size]),
                inline=True,
            )

    starts_at = gains_data.get("startsAt", "")
    ends_at = gains_data.get("endsAt", "")
    if starts_at and ends_at:
        embed.description = f"`{starts_at[:10]}` → `{ends_at[:10]}`"

    return embed


class PlayerCog(commands.Cog):
    def __init__(self, bot: commands.Bot, wom: WomClient):
        self.bot = bot
        self.wom = wom

    @app_commands.command(name="player", description="Look up an OSRS player's stats from Wise Old Man.")
    @app_commands.describe(username="The player's RSN (RuneScape username)")
    async def player(self, interaction: discord.Interaction, username: str):
        await interaction.response.defer()
        data = await self.wom.get_player(username)
        if data is None:
            await interaction.followup.send(
                f"Player **{username}** not found on Wise Old Man. "
                "They may need to be tracked first.",
                ephemeral=True,
            )
            return
        embed = _build_player_embed(data)
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="gains", description="Show XP and boss kill gains for a player.")
    @app_commands.describe(
        username="The player's RSN",
        period="Time period: day (default), week, month",
    )
    @app_commands.choices(
        period=[
            app_commands.Choice(name="Last 24 hours", value="day"),
            app_commands.Choice(name="Last 7 days", value="week"),
            app_commands.Choice(name="Last 30 days", value="month"),
        ]
    )
    async def gains(
        self,
        interaction: discord.Interaction,
        username: str,
        period: app_commands.Choice[str] = None,
    ):
        await interaction.response.defer()
        period_val = period.value if period else "day"
        gains_data = await self.wom.get_player_gains(username, period=period_val)
        if gains_data is None:
            await interaction.followup.send(
                f"Player **{username}** not found on Wise Old Man.",
                ephemeral=True,
            )
            return
        embed = _build_gains_embed(username, gains_data, period_val)
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="update", description="Force-update a player's stats on Wise Old Man.")
    @app_commands.describe(username="The player's RSN to update")
    async def update(self, interaction: discord.Interaction, username: str):
        await interaction.response.defer(ephemeral=True)
        data = await self.wom.update_player(username)
        if data is None:
            await interaction.followup.send(
                f"Could not update **{username}**. They may not be tracked on WOM yet.",
                ephemeral=True,
            )
            return
        await interaction.followup.send(
            f"✅ **{username}** has been updated on Wise Old Man.",
            ephemeral=True,
        )

    # ── /compare ───────────────────────────────────────────────────────────────

    @app_commands.command(name="compare", description="Compare two players' stats side by side.")
    @app_commands.describe(player1="First player's RSN", player2="Second player's RSN")
    async def compare(self, interaction: discord.Interaction, player1: str, player2: str):
        await interaction.response.defer()
        p1_data, p2_data = await asyncio.gather(
            self.wom.get_player(player1),
            self.wom.get_player(player2),
        )
        if p1_data is None:
            await interaction.followup.send(f"Player **{player1}** not found on Wise Old Man.", ephemeral=True)
            return
        if p2_data is None:
            await interaction.followup.send(f"Player **{player2}** not found on Wise Old Man.", ephemeral=True)
            return

        embed = _build_compare_embed(p1_data, p2_data)
        await interaction.followup.send(embed=embed)

    # ── /records ───────────────────────────────────────────────────────────────

    @app_commands.command(name="records", description="Show a player's personal bests / WOM records.")
    @app_commands.describe(
        username="The player's RSN",
        period="Filter by period (optional)",
    )
    @app_commands.choices(period=[
        app_commands.Choice(name="Day",   value="day"),
        app_commands.Choice(name="Week",  value="week"),
        app_commands.Choice(name="Month", value="month"),
        app_commands.Choice(name="Year",  value="year"),
    ])
    async def records(
        self,
        interaction: discord.Interaction,
        username: str,
        period: app_commands.Choice[str] = None,
    ):
        await interaction.response.defer()
        period_val = period.value if period else None
        data = await self.wom.get_player_records(username, period=period_val)
        if data is None:
            await interaction.followup.send(f"Player **{username}** not found on Wise Old Man.", ephemeral=True)
            return
        embed = _build_records_embed(username, data, period_val)
        await interaction.followup.send(embed=embed)

    # ── /leaderboard ───────────────────────────────────────────────────────────

    @app_commands.command(name="leaderboard", description="Show the WOM global gains leaderboard for a skill or boss.")
    @app_commands.describe(
        metric="Skill or boss name (e.g. overall, zulrah, slayer)",
        period="Time period for gains",
    )
    @app_commands.choices(period=[
        app_commands.Choice(name="Day",   value="day"),
        app_commands.Choice(name="Week",  value="week"),
        app_commands.Choice(name="Month", value="month"),
        app_commands.Choice(name="Year",  value="year"),
    ])
    async def leaderboard(
        self,
        interaction: discord.Interaction,
        metric: str,
        period: app_commands.Choice[str] = None,
    ):
        await interaction.response.defer()
        period_val = period.value if period else "week"
        data = await self.wom.get_leaderboard(metric.lower().replace(" ", "_"), period=period_val)
        if data is None or not isinstance(data, list):
            await interaction.followup.send(
                f"No leaderboard data found for **{metric}**. Check the metric name and try again.",
                ephemeral=True,
            )
            return
        embed = _build_leaderboard_embed(metric, period_val, data)
        await interaction.followup.send(embed=embed)


# ── Embed builders for new commands ───────────────────────────────────────────

def _snapshot_skills(data: dict) -> dict:
    return data.get("latestSnapshot", {}).get("data", {}).get("skills", {})


def _snapshot_bosses(data: dict) -> dict:
    return data.get("latestSnapshot", {}).get("data", {}).get("bosses", {})


def _build_compare_embed(p1: dict, p2: dict) -> discord.Embed:
    n1 = p1.get("displayName", p1.get("username", "Player 1"))
    n2 = p2.get("displayName", p2.get("username", "Player 2"))

    embed = discord.Embed(
        title=f"⚔️ {n1}  vs  {n2}",
        color=0xEB459E,
    )
    embed.set_footer(text="Data via Wise Old Man")

    s1 = _snapshot_skills(p1)
    s2 = _snapshot_skills(p2)
    b1 = _snapshot_bosses(p1)
    b2 = _snapshot_bosses(p2)

    # Skills comparison
    p1_lines, p2_lines = [], []
    for skill in SKILL_ORDER:
        e1 = s1.get(skill, {})
        e2 = s2.get(skill, {})
        lvl1 = e1.get("level", 0) or 0
        lvl2 = e2.get("level", 0) or 0
        emoji = SKILL_EMOJIS.get(skill, "•")
        label = "Overall" if skill == "overall" else skill.title()
        marker1 = " ▲" if lvl1 > lvl2 else (" ▼" if lvl1 < lvl2 else "")
        marker2 = " ▲" if lvl2 > lvl1 else (" ▼" if lvl2 < lvl1 else "")
        p1_lines.append(f"{emoji} **{label}** `{_fmt_num(lvl1)}`{marker1}")
        p2_lines.append(f"{emoji} **{label}** `{_fmt_num(lvl2)}`{marker2}")

    embed.add_field(name=f"📊 {n1}", value="\n".join(p1_lines[:12]), inline=True)
    embed.add_field(name=f"📊 {n2}", value="\n".join(p2_lines[:12]), inline=True)
    embed.add_field(name="\u200b", value="\u200b", inline=False)

    # Overall XP summary
    xp1 = s1.get("overall", {}).get("experience", 0) or 0
    xp2 = s2.get("overall", {}).get("experience", 0) or 0
    embed.add_field(
        name="Total XP",
        value=f"**{n1}:** `{_fmt_num(xp1)}`\n**{n2}:** `{_fmt_num(xp2)}`\nDiff: `{_fmt_num(abs(xp1 - xp2))}`",
        inline=True,
    )

    # EHP comparison
    ehp1 = p1.get("ehp", 0) or 0
    ehp2 = p2.get("ehp", 0) or 0
    embed.add_field(
        name="EHP",
        value=f"**{n1}:** `{ehp1:.1f}`\n**{n2}:** `{ehp2:.1f}`",
        inline=True,
    )

    # Boss kill totals
    total_kc1 = sum(e.get("kills", 0) or 0 for e in b1.values() if (e.get("kills") or 0) > 0)
    total_kc2 = sum(e.get("kills", 0) or 0 for e in b2.values() if (e.get("kills") or 0) > 0)
    embed.add_field(
        name="Total Boss KC",
        value=f"**{n1}:** `{_fmt_num(total_kc1)}`\n**{n2}:** `{_fmt_num(total_kc2)}`",
        inline=True,
    )

    return embed


def _build_records_embed(username: str, records: list, period: str | None) -> discord.Embed:
    period_label = {"day": "Day", "week": "Week", "month": "Month", "year": "Year"}.get(period or "", "All time")
    embed = discord.Embed(
        title=f"{username}  —  Records ({period_label})",
        url=f"https://wiseoldman.net/players/{username}",
        color=0xF1C40F,
    )
    embed.set_footer(text="Data via Wise Old Man")

    if not records:
        embed.description = "No records found for this period."
        return embed

    skill_lines, boss_lines = [], []
    for rec in records:
        metric = rec.get("metric", "")
        rec_type = rec.get("type", "")  # "experience" or "kills"
        value = rec.get("value", 0)
        period_str = rec.get("period", "")

        label = metric.replace("_", " ").title()
        val_str = _fmt_num(int(value)) if value else "0"

        if rec_type == "kills":
            boss_lines.append(f"💀 **{label}** — `{val_str}` kc ({period_str})")
        else:
            skill_lines.append(f"📈 **{label}** — `{val_str}` xp ({period_str})")

    if skill_lines:
        embed.add_field(name="Skill Records", value="\n".join(skill_lines[:15]), inline=True)
    if boss_lines:
        embed.add_field(name="Boss Records",  value="\n".join(boss_lines[:15]),  inline=True)

    return embed


def _build_leaderboard_embed(metric: str, period: str, entries: list) -> discord.Embed:
    period_label = {"day": "Day", "week": "Week", "month": "Month", "year": "Year"}.get(period, period.title())
    metric_label = metric.replace("_", " ").title()

    embed = discord.Embed(
        title=f"🏆 {metric_label} Leaderboard — {period_label}",
        url="https://wiseoldman.net/leaderboards/records",
        color=0xF1C40F,
    )
    embed.set_footer(text="Data via Wise Old Man")

    if not entries:
        embed.description = "No leaderboard data available."
        return embed

    lines = []
    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    for i, entry in enumerate(entries[:15], start=1):
        player = entry.get("player", {})
        name = player.get("displayName", player.get("username", "Unknown"))
        value = entry.get("value", 0)
        val_str = _fmt_num(int(value)) if value else "0"
        medal = medals.get(i, f"`{i}.`")
        lines.append(f"{medal} **{name}** — `{val_str}`")

    embed.description = "\n".join(lines)
    return embed


async def setup(bot: commands.Bot, wom: WomClient):
    await bot.add_cog(PlayerCog(bot, wom))
