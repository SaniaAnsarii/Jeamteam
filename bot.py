import os

import discord
from discord.ext import commands
from dotenv import load_dotenv

import database as db
from views.voting_view import FestivalPostView

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()

bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def setup_hook():
    db.init_db()

    # Re-register the persistent "Cast Your Vote" button view so it keeps
    # working after a bot restart (it has no timeout and a fixed custom_id).
    bot.add_view(FestivalPostView())

    await bot.load_extension("commands.festival")


async def sync_guild(guild: discord.Guild):
    """Copies the global command tree into one guild and syncs it there —
    this is what makes commands show up instantly (vs. up to an hour for a
    pure global sync)."""
    bot.tree.copy_global_to(guild=guild)
    synced = await bot.tree.sync(guild=guild)
    print(f"✅ Synced {len(synced)} command(s) to '{guild.name}' ({guild.id})")


@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")
    # bot.guilds is only reliably populated once the gateway connects, so
    # this is done here rather than in setup_hook.
    for guild in bot.guilds:
        await sync_guild(guild)
    print(f"✅ Bot is active in {len(bot.guilds)} server(s)")


@bot.event
async def on_guild_join(guild: discord.Guild):
    # Whenever someone invites the bot to a new server, register commands
    # there immediately instead of waiting for a restart.
    await sync_guild(guild)


bot.run(TOKEN)
