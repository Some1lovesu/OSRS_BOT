"""Player search commands."""

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


async def setup(bot: commands.Bot, wom: WomClient):
    await bot.add_cog(PlayerCog(bot, wom))
