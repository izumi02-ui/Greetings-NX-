"""
Discord Welcome Bot
===================

A friendly, configurable Discord bot that welcomes new members to your
server (and DMs them a goodbye when they leave).

Setup: read README.md. Short version:
  1. Create a bot at https://discord.com/developers/applications
     (enable the Server Members Intent) and copy its token.
  2. Copy `.env.example` to `.env` and set DISCORD_TOKEN.
  3. `pip install -r requirements.txt`
  4. `python bot.py`

Everything else can be configured live in Discord with `/welcome ...` commands.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any, Optional

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

try:
    from aiohttp import web  # ships with discord.py — no extra install needed
except ImportError:  # pragma: no cover
    web = None

load_dotenv()

# --------------------------------------------------------------------------- #
# Logging
# --------------------------------------------------------------------------- #
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
)
log = logging.getLogger("welcome-bot")

# --------------------------------------------------------------------------- #
# Environment-based configuration
# --------------------------------------------------------------------------- #
TOKEN = os.getenv("DISCORD_TOKEN", "").strip()


def env_int(name: str) -> Optional[int]:
    """Read an environment variable as an integer ID, or None."""
    raw = os.getenv(name, "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        log.warning("Env var %s is not a valid ID: %r (ignoring it)", name, raw)
        return None


def env_color(name: str, default: str) -> discord.Color:
    try:
        return discord.Color.from_str(os.getenv(name, default))
    except ValueError:
        log.warning(
            "Env var %s is not a valid hex color: %r (falling back to %s)",
            name, os.getenv(name), default,
        )
        return discord.Color.from_str(default)


WELCOME_COLOR = env_color("WELCOME_COLOR", "#5865F2")
GOODBYE_COLOR = env_color("GOODBYE_COLOR", "#EB459E")

# Defaults, applied to every guild. Anything can be overridden per-server
# at runtime with the /welcome commands (stored in settings.json).
DEFAULT_SETTINGS: dict[str, Any] = {
    "welcome_channel": env_int("WELCOME_CHANNEL_ID"),  # channel ID or None (falls back to the system channel)
    "auto_role": env_int("AUTO_ROLE_ID"),              # role ID or None
    "send_dm": True,                                   # DM new members a personal hello?
    "send_goodbye_dm": True,                           # DM members a farewell the moment they leave?
    "welcome_title": "Welcome to **THE NEXUS™**",
    "welcome_message": (
        "[New Entry Detected!]({avatar})\n\n"
        "**• Greetings, {mention} We're glad to have you here •**\n\n"
        "**• A new user has entered the void! Gear up and get ready for an epic experience.**\n\n"
        "• Make sure to check out **{rules}** to keep **The Community** safe.\n\n"
        "• Don't forget to pick **self & gaming roles** in **{roles1}** & **{roles2}**.\n\n"
        "**| • Let's build the ultimate community together • |**"
    ),
    "goodbye_message": "{name} just left **{server}**. We'll miss you! 👋",
    "dm_message": (
        "Hey {name}! 👋 Welcome to **{server}**! "
        "Take a moment to read the rules, then introduce yourself in general chat. Enjoy your stay!"
    ),
    "welcome_banner": os.getenv(
        "WELCOME_BANNER",
        "https://cdn.discordapp.com/attachments/1460251763881017459/"
        "1477366736113242192/GitHub_-_U7P4L-IN_Log-In__Set_Password_in_Tarmux_Tarminal_.gif"
        "?ex=6a97bd3e&is=6a966bbe&hm=0fa4bd07c7246f742b7160e1f86dc5545e897784cf13c0898d19138978311653&",
    ).strip(),  # large image shown at the BOTTOM of the welcome embed
    "welcome_footer_text": "| • A public void • ࿐",
    "welcome_footer_icon": (
        "https://media.discordapp.net/attachments/1413054941211267173/"
        "1477662809545511024/db86dee4d0ee23a59f05aca824d65447.jpg"
        "?ex=6a977f7b&is=6a962dfb&hm=77fb12621f69ce5439e9b4f67d4b8b69d446cea207ea46c3adee2ff55bdc1a85&"
    ),  # small image in the footer (bottom-left)
    "rules_channel": os.getenv("RULES_CHANNEL_ID", "1475330506005413929").strip(),
    "roles_channel1": os.getenv("ROLES_CHANNEL1_ID", "1475537402838782035").strip(),
    "roles_channel2": os.getenv("ROLES_CHANNEL2_ID", "1475570545885188308").strip(),
    "welcome_icon": os.getenv("WELCOME_ICON", "").strip() or None,  # custom icon (profile photo); None -> member avatar
}

SETTINGS_FILE = Path(__file__).resolve().parent / "settings.json"


# --------------------------------------------------------------------------- #
# Settings store — a small JSON file, one entry per guild
# --------------------------------------------------------------------------- #
class SettingsStore:
    """Persists per-guild settings to a JSON file next to the bot."""

    def __init__(self, path: Path = SETTINGS_FILE) -> None:
        self.path = path
        self._data: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            self._data = {}
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            self._data = raw if isinstance(raw, dict) else {}
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("Could not read %s (%s) — starting with empty settings.", self.path, exc)
            self._data = {}

    def _save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.path)

    def get(self, guild_id: int) -> dict[str, Any]:
        """Return the settings for a guild, merged over the defaults."""
        settings = dict(DEFAULT_SETTINGS)
        for key, value in self._data.get(str(guild_id), {}).items():
            if key in DEFAULT_SETTINGS and value is not None:
                settings[key] = value
        return settings

    def set(self, guild_id: int, **updates: Any) -> dict[str, Any]:
        """Update the settings for a guild and persist them."""
        settings = self.get(guild_id)
        for key, value in updates.items():
            if key in DEFAULT_SETTINGS:
                settings[key] = value
        self._data[str(guild_id)] = settings
        self._save()
        return settings


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def format_message(template: str, **placeholders: Any) -> str:
    """Fill {placeholders} in a template without touching any other braces."""
    for key, value in placeholders.items():
        template = template.replace("{" + key + "}", str(value))
    return template


async def find_welcome_channel(guild: discord.Guild, settings: dict[str, Any]) -> Optional[discord.TextChannel]:
    """Resolve where welcome messages go: configured channel, else the system channel."""
    channel_id = settings.get("welcome_channel")
    if channel_id is not None:
        channel = guild.get_channel(channel_id)
        if channel is None:
            try:
                channel = await guild.fetch_channel(channel_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                channel = None
        if isinstance(channel, discord.TextChannel):
            return channel
    return guild.system_channel if isinstance(guild.system_channel, discord.TextChannel) else None


def _channel_mention(guild: discord.Guild, channel_id: Any) -> str:
    """Turn a stored channel ID into a clickable #channel mention (or <#id>)."""
    if not channel_id:
        return ""
    try:
        channel = guild.get_channel(int(channel_id))
    except (TypeError, ValueError):
        channel = None
    if channel is not None:
        return channel.mention
    return f"<#{channel_id}>"


def build_welcome_embed(member: discord.Member, settings: dict[str, Any]) -> discord.Embed:
    guild = member.guild
    description = format_message(
        settings.get("welcome_message", DEFAULT_SETTINGS["welcome_message"]),
        avatar=member.display_avatar.url,
        mention=member.mention,
        name=member.display_name,
        user=str(member),
        server=guild.name,
        count=guild.member_count or 0,
        rules=_channel_mention(guild, settings.get("rules_channel")),
        roles1=_channel_mention(guild, settings.get("roles_channel1")),
        roles2=_channel_mention(guild, settings.get("roles_channel2")),
    )
    embed = discord.Embed(
        title=settings.get("welcome_title", DEFAULT_SETTINGS["welcome_title"]),
        description=description,
        color=WELCOME_COLOR,
        timestamp=discord.utils.utcnow(),
    )
    # Small circle profile picture (top-right).
    icon_url = settings.get("welcome_icon") or member.display_avatar.url
    embed.set_thumbnail(url=icon_url)
    # Footer: bottom-left image + its caption.
    footer_text = settings.get("welcome_footer_text") or ""
    footer_icon = settings.get("welcome_footer_icon")
    embed.set_footer(text=footer_text, icon_url=footer_icon)
    # Banner: large image pinned to the bottom of the embed.
    banner = settings.get("welcome_banner")
    if banner:
        embed.set_image(url=banner)
    return embed


def build_goodbye_embed(member: discord.Member, settings: dict[str, Any]) -> discord.Embed:
    guild = member.guild
    description = format_message(
        settings.get("goodbye_message", DEFAULT_SETTINGS["goodbye_message"]),
        name=member.display_name,
        user=str(member),
        server=guild.name,
        count=guild.member_count or 0,
    )
    embed = discord.Embed(
        title=f"👋 Goodbye from {guild.name}!",
        description=description,
        color=GOODBYE_COLOR,
        timestamp=discord.utils.utcnow(),
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.set_footer(
        text=f"Member #{guild.member_count or 0}",
        icon_url=guild.icon.url if guild.icon else None,
    )
    return embed


async def assign_auto_role(member: discord.Member, settings: dict[str, Any]) -> None:
    role_id = settings.get("auto_role")
    if role_id is None:
        return
    role = member.guild.get_role(role_id)
    if role is None:
        log.warning("Auto-role %s no longer exists in %s", role_id, member.guild)
        return
    try:
        await member.add_roles(role, reason="Welcome bot: auto-role")
        log.info("Assigned auto-role %s to %s", role, member)
    except discord.Forbidden:
        log.warning(
            "Could not assign %s to %s — is the bot's role above it in Server Settings → Roles?",
            role, member,
        )
    except discord.HTTPException as exc:
        log.warning("Failed to assign auto-role to %s: %s", member, exc)


async def send_goodbye_dm(member: discord.Member, settings: dict[str, Any]) -> None:
    """DM the member a farewell the instant they leave the server."""
    if not settings.get("send_goodbye_dm", True):
        return
    try:
        await member.send(embed=build_goodbye_embed(member, settings))
        log.info("Sent goodbye DM to %s", member)
    except discord.Forbidden:
        log.info("Could not DM %s a goodbye (DMs are closed or no shared server).", member)
    except discord.HTTPException as exc:
        log.warning("Failed to DM %s a goodbye: %s", member, exc)


async def send_direct_message(member: discord.Member, settings: dict[str, Any]) -> None:
    if not settings.get("send_dm", True):
        return
    message = format_message(
        settings.get("dm_message", DEFAULT_SETTINGS["dm_message"]),
        name=member.display_name,
        user=str(member),
        server=member.guild.name,
    )
    try:
        await member.send(message)
        log.info("Sent welcome DM to %s", member)
    except discord.Forbidden:
        log.info("Could not DM %s (DMs are closed).", member)
    except discord.HTTPException as exc:
        log.warning("Failed to DM %s: %s", member, exc)


# --------------------------------------------------------------------------- #
# The bot
# --------------------------------------------------------------------------- #
class WelcomeBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.members = True        # required for member join/leave events
        intents.voice_states = True   # required for /join and /leave voice commands
        super().__init__(command_prefix=commands.when_mentioned, intents=intents)
        self.settings = SettingsStore()
        self.tree.add_command(WelcomeGroup(self))
        self.tree.add_command(join_voice)
        self.tree.add_command(leave_voice)
        self.tree.error(self.on_tree_error)

    # -- lifecycle -------------------------------------------------------- #

    async def on_ready(self) -> None:
        assert self.user is not None
        log.info("Logged in as %s (ID: %s) — connected to %d guild(s)", self.user, self.user.id, len(self.guilds))
        for g in self.guilds:
            log.info("GUILD: %s | ID: %s  <-- use this for SYNC_GUILD_ID", g.name, g.id)
        await self.change_presence(
            activity=discord.Activity(type=discord.ActivityType.watching, name="new members 👋")
        )
        await self.sync_commands()
        asyncio.create_task(self._heartbeat())  # keeps free web hosts happy

    async def sync_commands(self) -> None:
        """Register slash commands. Global sync can take ~1h to propagate;
        set SYNC_GUILD_ID for instant updates in one server."""
        sync_guild_id = os.getenv("SYNC_GUILD_ID", "").strip()
        try:
            if sync_guild_id:
                guild = self.get_guild(int(sync_guild_id))
                if guild is None:
                    guild = await self.fetch_guild(int(sync_guild_id))
                self.tree.copy_global_to(guild=guild)
await self.tree.sync(guild=guild)
                log.info("Slash commands synced instantly to guild %s", sync_guild_id)
            else:
                await self.tree.sync()
                log.info("Slash commands synced globally (can take up to an hour to appear)")
        except Exception as exc:  # noqa: BLE001
            log.error(
                "Guild sync to %s failed (%s) — falling back to a global sync.", sync_guild_id, exc
            )
            try:
                await self.tree.sync()
                log.info("Slash commands synced globally instead (may take up to an hour to appear).")
            except Exception as exc2:  # noqa: BLE001
                log.error("Global sync also failed: %s", exc2)

    async def _heartbeat(self) -> None:
        """Serve a tiny HTTP endpoint so free hosts (Render Web Service, etc.)
        see a live port. Discord bots normally open no ports, which makes
        Render fail the deploy with 'No open ports detected' — this fixes it.
        Render injects the PORT env var automatically."""
        if web is None:
            log.warning("aiohttp not available — heartbeat server disabled.")
            return
        port = int(os.getenv("PORT", "8000"))
        app = web.Application()

        async def health(_: web.Request) -> web.Response:
            return web.Response(text="ok")

        app.router.add_get("/", health)
        runner = web.AppRunner(app)
        await runner.setup()
        await web.TCPSite(runner, "0.0.0.0", port).start()
        log.info("Heartbeat HTTP server listening on 0.0.0.0:%d", port)

    # -- events ----------------------------------------------------------- #

    async def on_member_join(self, member: discord.Member) -> None:
        guild = member.guild
        settings = self.settings.get(guild.id)

        channel = await find_welcome_channel(guild, settings)
        if channel is not None:
            try:
                await channel.send(embed=build_welcome_embed(member, settings))
                log.info("Welcomed %s in %s", member, guild)
            except discord.HTTPException as exc:
                log.warning("Could not send welcome message to %s: %s", channel, exc)
        else:
            log.warning(
                "No welcome channel for %s — run /welcome channel to set one (or enable a system channel).",
                guild,
            )

        await assign_auto_role(member, settings)
        await send_direct_message(member, settings)

    async def on_member_remove(self, member: discord.Member) -> None:
        """Someone left — DM them a farewell instead of posting in any channel."""
        settings = self.settings.get(member.guild.id)
        await send_goodbye_dm(member, settings)

    # -- error handling --------------------------------------------------- #

    async def on_tree_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
        log.error("Command %r raised: %s", interaction.command, error)
        if isinstance(error, app_commands.CommandInvokeError):
            error = error.original  # unwrap to the real exception
        if isinstance(error, discord.Forbidden):
            message = "I don't have permission to do that — check the bot's roles and channel permissions."
        elif isinstance(error, app_commands.MissingPermissions):
            message = "You need the **Manage Server** permission to use this command."
        else:
            message = "Something went wrong while running that command. Check the bot's logs."
        try:
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)
        except discord.HTTPException:
            pass


# --------------------------------------------------------------------------- #
# Slash commands: /welcome ...  (server admins only)
# --------------------------------------------------------------------------- #
class WelcomeGroup(app_commands.Group):
    """Configure the welcome bot in-server — no code edits needed."""

    def __init__(self, bot: WelcomeBot) -> None:
        super().__init__(
            name="welcome",
            description="Welcome-bot configuration (Manage Server required).",
            guild_only=True,
            default_permissions=discord.Permissions(manage_guild=True),
        )
        self.bot = bot

    @staticmethod
    def _guild(interaction: discord.Interaction) -> discord.Guild:
        if interaction.guild is None:  # guarded by guild_only=True
            raise RuntimeError("Command used outside a guild")
        return interaction.guild

    @app_commands.command(name="channel", description="Set the channel where welcome messages are posted.")
    async def channel(
        self,
        interaction: discord.Interaction,
        channel: Optional[discord.TextChannel] = None,
        clear: bool = False,
    ) -> None:
        guild = self._guild(interaction)
        store = self.bot.settings
        if clear:
            store.set(guild.id, welcome_channel=None)
            await interaction.response.send_message(
                "✅ Welcome channel cleared — the server's system channel will be used instead.",
                ephemeral=True,
            )
            return
        if channel is not None:
            store.set(guild.id, welcome_channel=channel.id)
            await interaction.response.send_message(
                f"✅ Welcome messages will now be posted to {channel.mention}.",
                ephemeral=True,
            )
            return
        current_id = store.get(guild.id)["welcome_channel"]
        current = guild.get_channel(current_id) if current_id else None
        await interaction.response.send_message(
            f"Welcome channel is currently **{current.mention if current else 'the server system channel'}**.\n"
            "Use `/welcome channel <channel>` to change it, or `/welcome channel clear:True` to reset.",
            ephemeral=True,
        )

    @app_commands.command(name="role", description="Set a role that is auto-assigned to every new member.")
    async def role(
        self,
        interaction: discord.Interaction,
        role: Optional[discord.Role] = None,
        clear: bool = False,
    ) -> None:
        guild = self._guild(interaction)
        store = self.bot.settings
        if clear:
            store.set(guild.id, auto_role=None)
            await interaction.response.send_message("✅ Auto-role removed.", ephemeral=True)
            return
        if role is not None:
            if role >= guild.me.top_role:
                await interaction.response.send_message(
                    "❌ I can't assign that role — it must be **below** my highest role "
                    "in Server Settings → Roles.",
                    ephemeral=True,
                )
                return
            if not role.is_assignable():
                await interaction.response.send_message(
                    "❌ That role cannot be assigned to members (managed/integration roles can't be used).",
                    ephemeral=True,
                )
                return
            store.set(guild.id, auto_role=role.id)
            await interaction.response.send_message(
                f"✅ Every new member will automatically receive {role.mention}.",
                ephemeral=True,
            )
            return
        current_id = store.get(guild.id)["auto_role"]
        current = guild.get_role(current_id) if current_id else None
        await interaction.response.send_message(
            f"Auto-role is currently **{current.mention if current else 'disabled'}**.\n"
            "Use `/welcome role <role>` to set one, or `/welcome role clear:True` to remove it.",
            ephemeral=True,
        )

    @app_commands.command(name="message", description="Set the welcome message shown in the channel.")
    async def message(
        self,
        interaction: discord.Interaction,
        text: Optional[str] = None,
        reset: bool = False,
    ) -> None:
        guild = self._guild(interaction)
        store = self.bot.settings
        if reset:
            store.set(guild.id, welcome_message=DEFAULT_SETTINGS["welcome_message"])
            await interaction.response.send_message("✅ Welcome message reset to the default.", ephemeral=True)
            return
        if text is not None:
            store.set(guild.id, welcome_message=text.replace("\\n", "\n"))
            await interaction.response.send_message(
                "✅ Welcome message updated — run `/welcome preview` to see it.",
                ephemeral=True,
            )
            return
        current = store.get(guild.id)["welcome_message"]
        await interaction.response.send_message(
            f"**Current welcome message:**\n> {current}\n\n"
            "Placeholders: `{{mention}}` `{{name}}` `{{user}}` `{{server}}` `{{count}}`",
            ephemeral=True,
        )

    @app_commands.command(name="goodbye-dm", description="Toggle the farewell DM sent when a member leaves.")
    async def goodbye_dm(self, interaction: discord.Interaction, enabled: bool) -> None:
        guild = self._guild(interaction)
        self.bot.settings.set(guild.id, send_goodbye_dm=enabled)
        await interaction.response.send_message(
            f"✅ Goodbye DMs are now **{'on' if enabled else 'off'}**.",
            ephemeral=True,
        )

    @app_commands.command(name="goodbye", description="Set the farewell DM sent when someone leaves.")
    async def goodbye(
        self,
        interaction: discord.Interaction,
        text: Optional[str] = None,
        reset: bool = False,
    ) -> None:
        guild = self._guild(interaction)
        store = self.bot.settings
        if reset:
            store.set(guild.id, goodbye_message=DEFAULT_SETTINGS["goodbye_message"])
            await interaction.response.send_message("✅ Goodbye message reset to the default.", ephemeral=True)
            return
        if text is not None:
            store.set(guild.id, goodbye_message=text.replace("\\n", "\n"))
            await interaction.response.send_message(
                "✅ Goodbye message updated — run `/welcome preview` to see the welcome embed.",
                ephemeral=True,
            )
            return
        current = store.get(guild.id)["goodbye_message"]
        await interaction.response.send_message(
            f"**Current goodbye message:**\n> {current}",
            ephemeral=True,
        )

    @app_commands.command(name="dm", description="Toggle the private DM sent to each new member.")
    async def dm(self, interaction: discord.Interaction, enabled: bool) -> None:
        guild = self._guild(interaction)
        self.bot.settings.set(guild.id, send_dm=enabled)
        await interaction.response.send_message(
            f"✅ Private welcome DM is now **{'on' if enabled else 'off'}**.",
            ephemeral=True,
        )

    @app_commands.command(name="dm-message", description="Set the text of the private DM sent on join.")
    async def dm_message(
        self,
        interaction: discord.Interaction,
        text: Optional[str] = None,
        reset: bool = False,
    ) -> None:
        guild = self._guild(interaction)
        store = self.bot.settings
        if reset:
            store.set(guild.id, dm_message=DEFAULT_SETTINGS["dm_message"])
            await interaction.response.send_message("✅ DM message reset to the default.", ephemeral=True)
            return
        if text is not None:
            store.set(guild.id, dm_message=text.replace("\\n", "\n"))
            await interaction.response.send_message("✅ DM message updated.", ephemeral=True)
            return
        current = store.get(guild.id)["dm_message"]
        await interaction.response.send_message(f"**Current DM message:**\n> {current}", ephemeral=True)

    @app_commands.command(name="preview", description="Preview the embed new members will see.")
    async def preview(self, interaction: discord.Interaction) -> None:
        guild = self._guild(interaction)
        settings = self.bot.settings.get(guild.id)
        channel = await find_welcome_channel(guild, settings)
        location = channel.mention if channel else "no channel found (nothing will be posted)"
        embed = build_welcome_embed(interaction.user, settings)  # user is a Member here
        await interaction.response.send_message(
            f"👀 This is what new members will see in {location}:",
            embed=embed,
            ephemeral=True,
        )

    @app_commands.command(name="banner", description="Set the banner image shown at the bottom of the welcome embed.")
    async def banner(
        self,
        interaction: discord.Interaction,
        url: Optional[str] = None,
        reset: bool = False,
    ) -> None:
        guild = self._guild(interaction)
        store = self.bot.settings
        if reset:
            store.set(guild.id, welcome_banner=DEFAULT_SETTINGS["welcome_banner"])
            await interaction.response.send_message("✅ Welcome banner reset to the default.", ephemeral=True)
            return
        if url:
            store.set(guild.id, welcome_banner=url.strip())
            await interaction.response.send_message(
                "✅ Welcome banner updated — run `/welcome preview` to see it.", ephemeral=True
            )
            return
        current = store.get(guild.id)["welcome_banner"]
        await interaction.response.send_message(
            f"**Current banner:**\n{current}\n\nUse `/welcome banner <url>` to change it, "
            "or `/welcome banner reset:True` to restore the default.",
            ephemeral=True,
        )

    @app_commands.command(name="icon", description="Set the icon/profile photo shown on the welcome embed.")
    async def icon(
        self,
        interaction: discord.Interaction,
        url: Optional[str] = None,
        clear: bool = False,
    ) -> None:
        guild = self._guild(interaction)
        store = self.bot.settings
        if clear:
            store.set(guild.id, welcome_icon=None)
            await interaction.response.send_message(
                "✅ Icon cleared — each new member's own profile photo will be used.", ephemeral=True
            )
            return
        if url:
            store.set(guild.id, welcome_icon=url.strip())
            await interaction.response.send_message(
                "✅ Welcome icon updated — run `/welcome preview` to see it.", ephemeral=True
            )
            return
        current = store.get(guild.id)["welcome_icon"]
        icon_display = current if current else "each member's own profile photo"
        await interaction.response.send_message(
            f"**Current icon:** {icon_display}\n\n"
            "Use `/welcome icon <url>` to set your own profile photo, "
            "or `/welcome icon clear:True` to use each member's avatar.",
            ephemeral=True,
        )

    @app_commands.command(name="settings", description="Show the current welcome-bot configuration.")
    async def settings(self, interaction: discord.Interaction) -> None:
        guild = self._guild(interaction)
        settings = self.bot.settings.get(guild.id)
        channel = guild.get_channel(settings["welcome_channel"]) if settings["welcome_channel"] else None
        role = guild.get_role(settings["auto_role"]) if settings["auto_role"] else None

        embed = discord.Embed(title="⚙️ Welcome bot settings", color=WELCOME_COLOR)
        embed.add_field(
            name="📢 Welcome channel",
            value=channel.mention if channel else "System channel (fallback)",
            inline=True,
        )
        embed.add_field(
            name="💔 Goodbye DM",
            value="On" if settings.get("send_goodbye_dm", True) else "Off",
            inline=True,
        )
        embed.add_field(
            name="🎭 Auto role",
            value=role.mention if role else "Disabled",
            inline=True,
        )
        embed.add_field(
            name="📨 DM on join",
            value="On" if settings["send_dm"] else "Off",
            inline=True,
        )
        embed.add_field(
            name="👋 Welcome message",
            value=settings["welcome_message"][:120] or "*(default)*",
            inline=False,
        )
        embed.add_field(
            name="💔 Goodbye DM message",
            value=settings["goodbye_message"][:120] or "*(default)*",
            inline=False,
        )
        embed.add_field(
            name="📬 DM message",
            value=settings["dm_message"][:120] or "*(default)*",
            inline=False,
        )
        embed.add_field(
            name="🖼️ Banner (bottom)",
            value=settings["welcome_banner"][:120] or "*(none)*",
            inline=False,
        )
        embed.add_field(
            name="🪪 Icon",
            value=settings["welcome_icon"][:120] if settings["welcome_icon"] else "Member's profile photo",
            inline=False,
        )
        embed.add_field(
            name="🗒️ Footer",
            value=settings["welcome_footer_text"][:120] or "*(none)*",
            inline=False,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


# --------------------------------------------------------------------------- #
# Voice commands: /join and /leave
# --------------------------------------------------------------------------- #
@app_commands.command(name="join", description="Make the bot join a voice channel.")
@app_commands.describe(channel="Voice channel to join (defaults to the one you're in).")
@app_commands.guild_only()
async def join_voice(
    interaction: discord.Interaction,
    channel: Optional[discord.VoiceChannel] = None,
) -> None:
    guild = interaction.guild
    if guild is None:
        await interaction.response.send_message("This command only works in a server.", ephemeral=True)
        return

    # Fall back to whatever voice channel the caller is sitting in.
    if channel is None:
        author_voice = getattr(interaction.user, "voice", None)
        if author_voice is None or author_voice.channel is None:
            await interaction.response.send_message(
                "❌ You're not in a voice channel — join one first, or use `/join channel:<#voice>`.",
                ephemeral=True,
            )
            return
        channel = author_voice.channel

    perms = channel.permissions_for(guild.me)
    if not perms.connect:
        await interaction.response.send_message(
            f"❌ I don't have permission to connect to **{channel.name}**.", ephemeral=True
        )
        return
    if channel.user_limit and len(channel.members) >= channel.user_limit and not perms.move_members:
        await interaction.response.send_message(
            f"❌ **{channel.name}** is full.", ephemeral=True
        )
        return

    await interaction.response.defer(ephemeral=True)
    voice = guild.voice_client
    try:
        if voice is not None and voice.is_connected():
            if voice.channel.id == channel.id:
                await interaction.followup.send(f"✅ Already connected to {channel.mention}.", ephemeral=True)
                return
            await voice.move_to(channel)
            await interaction.followup.send(f"✅ Moved to {channel.mention}.", ephemeral=True)
        else:
            await channel.connect(self_deaf=True)
            await interaction.followup.send(f"✅ Joined {channel.mention}.", ephemeral=True)
        log.info("Joined voice channel %s in %s", channel, guild)
    except asyncio.TimeoutError:
        await interaction.followup.send("❌ Timed out while connecting to the voice channel.", ephemeral=True)
    except discord.ClientException as exc:
        await interaction.followup.send(f"❌ Could not connect: {exc}", ephemeral=True)
    except RuntimeError as exc:  # PyNaCl missing, etc.
        log.error("Voice connect failed: %s", exc)
        await interaction.followup.send(
            "❌ Voice support is not installed on the host. Run `pip install -U \"discord.py[voice]\"`.",
            ephemeral=True,
        )


@app_commands.command(name="leave", description="Disconnect the bot from the voice channel.")
@app_commands.guild_only()
async def leave_voice(interaction: discord.Interaction) -> None:
    guild = interaction.guild
    if guild is None:
        await interaction.response.send_message("This command only works in a server.", ephemeral=True)
        return

    voice = guild.voice_client
    if voice is None or not voice.is_connected():
        await interaction.response.send_message("❌ I'm not in a voice channel.", ephemeral=True)
        return

    name = voice.channel.mention if voice.channel else "the voice channel"
    await voice.disconnect(force=False)
    log.info("Left voice channel in %s", guild)
    await interaction.response.send_message(f"👋 Left {name}.", ephemeral=True)


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
bot = WelcomeBot()


async def main() -> None:
    if not TOKEN:
        log.error("No bot token found. Copy `.env.example` to `.env` and set DISCORD_TOKEN.")
        raise SystemExit(1)
    try:
        await bot.start(TOKEN)
    except KeyboardInterrupt:
        await bot.close()


if __name__ == "__main__":
    asyncio.run(main())
