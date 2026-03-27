"""Daily roundup — posts 24h gains for all tracked RSNs to a configured channel."""

import asyncio
import logging
from datetime import datetime, timezone

import discord
from discord.ext import commands, tasks

from wom_client import WomClient, SKILL_ORDER, SKILL_EMOJIS
from rsn_store import RsnStore

log = logging.getLogger(__name__)


def _fmt_num(n: int) -> str:
    return f"{n:,}"


def _build_roundup_embed(username: str, gains_data: dict) -> discord.Embed | None:
    """Build a gains embed for the daily roundup. Returns None if no activity."""
    data = gains_data.get("data", {})
    skills = data.get("skills", {})
    bosses = data.get("bosses", {})

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

    boss_lines = []
    for boss, entry in bosses.items():
        kills_gained = entry.get("kills", {}).get("gained", 0)
        if kills_gained > 0:
            boss_name = boss.replace("_", " ").title()
            boss_lines.append(f"💀 **{boss_name}** — `+{_fmt_num(kills_gained)}` kc")

    if not skill_lines and not boss_lines:
        return None  # No activity — skip this player

    embed = discord.Embed(
        title=f"{username}",
        url=f"https://wiseoldman.net/players/{username}",
        color=0xF1C40F,
    )

    if skill_lines:
        embed.add_field(
            name="📈 XP Gained",
            value="\n".join(skill_lines[:20]),
            inline=True,
        )
    if boss_lines:
        embed.add_field(
            name="🏆 Boss Kills",
            value="\n".join(boss_lines[:20]),
            inline=True,
        )

    return embed


class RoundupCog(commands.Cog):
    def __init__(
        self,
        bot: commands.Bot,
        wom: WomClient,
        store: RsnStore,
        channel_id: int,
        roundup_hour: int,
        roundup_minute: int,
    ):
        self.bot = bot
        self.wom = wom
        self.store = store
        self.channel_id = channel_id
        self.roundup_hour = roundup_hour
        self.roundup_minute = roundup_minute
        self._roundup_loop.change_interval(
            time=discord.utils.utcnow().replace(
                hour=roundup_hour,
                minute=roundup_minute,
                second=0,
                microsecond=0,
            )
        )

    async def cog_load(self):
        self._roundup_loop.start()

    async def cog_unload(self):
        self._roundup_loop.cancel()

    @tasks.loop(hours=24)
    async def _roundup_loop(self):
        await self._post_roundup()

    @_roundup_loop.before_loop
    async def _before_roundup(self):
        await self.bot.wait_until_ready()
        now = datetime.now(timezone.utc)
        target = now.replace(
            hour=self.roundup_hour,
            minute=self.roundup_minute,
            second=0,
            microsecond=0,
        )
        if target <= now:
            # Already passed today — schedule for tomorrow
            from datetime import timedelta
            target += timedelta(days=1)
        wait_seconds = (target - now).total_seconds()
        log.info("Daily roundup will fire in %.0f seconds.", wait_seconds)
        await asyncio.sleep(wait_seconds)

    async def _post_roundup(self):
        channel = self.bot.get_channel(self.channel_id)
        if channel is None:
            log.warning("Roundup channel %d not found.", self.channel_id)
            return

        rsns = self.store.get_all()
        if not rsns:
            await channel.send("📋 No RSNs are tracked yet. Use `/rsn add` to add players.")
            return

        header = discord.Embed(
            title="📅 Daily OSRS Roundup",
            description=f"Gains from the last 24 hours — {discord.utils.utcnow().strftime('%Y-%m-%d')}",
            color=0xEB459E,
        )
        await channel.send(embed=header)

        inactive = []
        for rsn in rsns:
            try:
                gains = await self.wom.get_player_gains(rsn, period="day")
                if gains is None:
                    inactive.append(rsn)
                    continue
                embed = _build_roundup_embed(rsn, gains)
                if embed is None:
                    inactive.append(rsn)
                else:
                    await channel.send(embed=embed)
                # Respect WOM rate limits
                await asyncio.sleep(1.5)
            except Exception as exc:
                log.error("Failed to fetch gains for %s: %s", rsn, exc)
                inactive.append(rsn)

        if inactive:
            await channel.send(
                f"😴 **No activity in the last 24h:** {', '.join(f'`{r}`' for r in inactive)}"
            )

    # ── Admin commands ─────────────────────────────────────────────────────────

    rsn_group = discord.app_commands.Group(
        name="rsn",
        description="Manage the list of RSNs tracked in the daily roundup.",
    )

    @rsn_group.command(name="add", description="Add a player RSN to the daily roundup.")
    @discord.app_commands.describe(username="The RSN to add")
    async def rsn_add(self, interaction: discord.Interaction, username: str):
        if self.store.add(username):
            await interaction.response.send_message(
                f"✅ Added **{username}** to the daily roundup.", ephemeral=True
            )
        else:
            await interaction.response.send_message(
                f"**{username}** is already being tracked.", ephemeral=True
            )

    @rsn_group.command(name="remove", description="Remove a player RSN from the daily roundup.")
    @discord.app_commands.describe(username="The RSN to remove")
    async def rsn_remove(self, interaction: discord.Interaction, username: str):
        if self.store.remove(username):
            await interaction.response.send_message(
                f"✅ Removed **{username}** from the daily roundup.", ephemeral=True
            )
        else:
            await interaction.response.send_message(
                f"**{username}** was not in the tracking list.", ephemeral=True
            )

    @rsn_group.command(name="list", description="List all RSNs tracked in the daily roundup.")
    async def rsn_list(self, interaction: discord.Interaction):
        rsns = self.store.get_all()
        if not rsns:
            await interaction.response.send_message(
                "No RSNs tracked yet. Use `/rsn add` to add players.", ephemeral=True
            )
            return
        lines = "\n".join(f"• `{r}`" for r in rsns)
        await interaction.response.send_message(
            f"**Tracked RSNs ({len(rsns)}):**\n{lines}", ephemeral=True
        )

    @rsn_group.command(name="roundup", description="Trigger the daily roundup immediately.")
    async def rsn_roundup(self, interaction: discord.Interaction):
        await interaction.response.send_message("🔄 Posting roundup now…", ephemeral=True)
        await self._post_roundup()


async def setup(bot: commands.Bot, wom: WomClient, store: RsnStore, channel_id: int, roundup_hour: int, roundup_minute: int):
    await bot.add_cog(
        RoundupCog(bot, wom, store, channel_id, roundup_hour, roundup_minute)
    )
