import os

import discord
from discord.ext import commands
from dotenv import load_dotenv

import database as db
from views.voting_view import FestivalPostView

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID_RAW = os.getenv("GUILD_ID")  # set this in .env for instant (guild-scoped) command sync

intents = discord.Intents.default()

bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def setup_hook():
    db.init_db()

    # Re-register the persistent "Cast Your Vote" button view so it keeps
    # working after a bot restart (it has no timeout and a fixed custom_id).
    bot.add_view(FestivalPostView())

    await bot.load_extension("commands.festival")

    if GUILD_ID_RAW:
        guild = discord.Object(id=int(GUILD_ID_RAW))
        bot.tree.copy_global_to(guild=guild)
        synced = await bot.tree.sync(guild=guild)
        print(f"✅ Synced {len(synced)} command(s) to guild {GUILD_ID_RAW}")
    else:
        synced = await bot.tree.sync()
        print(f"✅ Synced {len(synced)} command(s) globally (can take up to 1 hour to appear)")


@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")


bot.run(TOKEN)
