"""
commands/festival.py
Slash commands for the design festival voting system:
    /setadminrole (server admin) - choose which role can manage festivals
    /setupvote    (admin role)   - start a new festival in this channel
    /adddesign    (admin role)   - add one design to the festival being set up
    /adddesigns   (admin role)   - add multiple designs at once, one per line
    /editdesign   (admin role)   - edit a design's name/submitter
    /deletedesign (admin role)   - remove a design before voting opens
    /startvote    (admin role)   - post the public voting message and open voting
    /results      (admin role)   - compute and display results
    /ballots      (admin role)   - see exactly who voted for what (breaks anonymity)
    /endvote      (admin role)   - close voting

Permission model:
    - Real Discord "Manage Server" permission always works, for bootstrapping
      and as an owner override.
    - /setadminrole (Manage Server only) lets a real admin designate a role
      (e.g. "Festival Organizer") whose members can run every command below
      EXCEPT the voting flow itself — anyone in the server can click
      "Cast Your Vote" and vote, regardless of role.
"""

import io
import re

import discord
from discord import app_commands
from discord.ext import commands

import database as db
from views.voting_view import FestivalPostView


def is_admin():
    async def predicate(interaction: discord.Interaction) -> bool:
        if interaction.user.guild_permissions.manage_guild:
            return True
        admin_role_id = db.get_admin_role(interaction.guild_id)
        if admin_role_id is None:
            return False
        return any(role.id == admin_role_id for role in interaction.user.roles)

    return app_commands.check(predicate)


_MENTION_RE = re.compile(r"<@!?(\d+)>")


def _parse_bulk_entries(raw: str) -> tuple[list[tuple[str, int]], list[str]]:
    """Parses one design per line, formatted as:  Design Name - @submitter
    (order of name/mention doesn't matter, and '-' or '|' both work as the
    separator). Returns (parsed, problem_lines) where parsed is a list of
    (name, submitter_id) tuples ready for db.add_design, and problem_lines
    lists the raw lines that couldn't be parsed (no mention found, or the
    remaining text was empty after stripping the mention/separator)."""
    parsed: list[tuple[str, int]] = []
    problems: list[str] = []

    for raw_line in raw.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        match = _MENTION_RE.search(line)
        if not match:
            problems.append(raw_line)
            continue

        submitter_id = int(match.group(1))
        name = _MENTION_RE.sub("", line)
        # Strip a leading/trailing separator left over once the mention is gone.
        name = re.sub(r"^\s*[-|:]\s*|\s*[-|:]\s*$", "", name).strip()

        if not name:
            problems.append(raw_line)
            continue

        parsed.append((name, submitter_id))

    return parsed, problems


class FestivalCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # -- /setadminrole ----------------------------------------------------------
    @app_commands.command(
        name="setadminrole",
        description="Choose which role can manage festivals (Manage Server permission required)",
    )
    @app_commands.describe(role="The role that should be able to run festival admin commands")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def setadminrole(self, interaction: discord.Interaction, role: discord.Role):
        db.set_admin_role(interaction.guild_id, role.id)
        await interaction.response.send_message(
            f"✅ {role.mention} can now run every festival command except voting itself "
            f"(voting stays open to everyone).",
            ephemeral=True,
        )

    # -- /setupvote ---------------------------------------------------------
    @app_commands.command(name="setupvote", description="Start a new Design Festival (admin)")
    @is_admin()
    async def setupvote(self, interaction: discord.Interaction):
        existing = db.get_active_festival(interaction.guild_id)
        if existing:
            await interaction.response.send_message(
                f"⚠️ There's already an active festival (status: `{existing['status']}`). "
                f"Use `/endvote` to close it first, or `/adddesign` to keep adding designs.",
                ephemeral=True,
            )
            return

        festival_id = db.create_festival(interaction.guild_id, interaction.channel_id)
        await interaction.response.send_message(
            f"✅ Festival #{festival_id} created! Now add designs with `/adddesign`, "
            f"then run `/startvote` when you're ready to open voting.",
            ephemeral=True,
        )

    # -- /adddesign -----------------------------------------------------------
    @app_commands.command(name="adddesign", description="Add a design to the current festival (admin)")
    @app_commands.describe(name="Design name or title", submitter="Who submitted this design (required)")
    @is_admin()
    async def adddesign(
        self,
        interaction: discord.Interaction,
        name: str,
        submitter: discord.Member,
    ):
        festival = db.get_active_festival(interaction.guild_id)
        if not festival or festival["status"] != "setup":
            await interaction.response.send_message(
                "⚠️ No festival is currently being set up. Run `/setupvote` first.",
                ephemeral=True,
            )
            return

        design_id, number = db.add_design(festival["id"], name, submitter.id)

        await interaction.response.send_message(
            f"✅ Added **Design {number}: {name}** — {submitter.mention}", ephemeral=True
        )

    # -- /adddesigns (bulk) -----------------------------------------------------
    @app_commands.command(
        name="adddesigns",
        description="Add multiple designs at once, one per line (admin)",
    )
    @app_commands.describe(
        entries=(
            "One design per line, e.g.:  Design A - @Sania  (mention picker works "
            "inside this field — type @ and pick the user, one line per design)"
        )
    )
    @is_admin()
    async def adddesigns(self, interaction: discord.Interaction, entries: str):
        festival = db.get_active_festival(interaction.guild_id)
        if not festival or festival["status"] != "setup":
            await interaction.response.send_message(
                "⚠️ No festival is currently being set up. Run `/setupvote` first.",
                ephemeral=True,
            )
            return

        parsed, problems = _parse_bulk_entries(entries)

        if not parsed:
            await interaction.response.send_message(
                "⚠️ Couldn't parse any designs. Use one per line, e.g.:\n"
                "`Design A - @Sania`\n`Design B - @Twan`\n"
                "(type `@` inside the field and pick the user so it becomes a real mention).",
                ephemeral=True,
            )
            return

        added_lines = []
        for name, submitter_id in parsed:
            _, number = db.add_design(festival["id"], name, submitter_id)
            added_lines.append(f"Design {number}: {name} — <@{submitter_id}>")

        message = f"✅ Added {len(parsed)} design(s):\n" + "\n".join(added_lines)
        if problems:
            message += (
                f"\n\n⚠️ Skipped {len(problems)} line(s) — no valid `@mention` found:\n"
                + "\n".join(f"`{p}`" for p in problems)
            )

        await interaction.response.send_message(message[:2000], ephemeral=True)

    # -- /editdesign ----------------------------------------------------------
    @app_commands.command(name="editdesign", description="Edit a design's name and/or submitter (admin)")
    @app_commands.describe(
        design_number="The design number shown in /adddesign or the festival post (e.g. 3)",
        name="New name for the design (leave blank to keep the current name)",
        submitter="New submitter (leave blank to keep the current submitter)",
    )
    @is_admin()
    async def editdesign(
        self,
        interaction: discord.Interaction,
        design_number: int,
        name: str | None = None,
        submitter: discord.Member | None = None,
    ):
        festival = db.get_active_festival(interaction.guild_id)
        if not festival:
            await interaction.response.send_message(
                "⚠️ There's no active festival.", ephemeral=True
            )
            return

        design = db.get_design_by_number(festival["id"], design_number)
        if not design:
            await interaction.response.send_message(
                f"⚠️ No design numbered **{design_number}** found in the current festival.",
                ephemeral=True,
            )
            return

        if name is None and submitter is None:
            await interaction.response.send_message(
                "⚠️ Give at least a new `name` or a new `submitter` to update.",
                ephemeral=True,
            )
            return

        db.update_design(
            design["id"],
            name=name,
            submitter_id=submitter.id if submitter else None,
        )
        updated = db.get_design(design["id"])

        who = f" — <@{updated['submitter_id']}>" if updated["submitter_id"] else ""
        note = ""
        if festival["status"] == "voting":
            note = (
                "\n-# ⚠️ Voting is already open — the public post won't update automatically. "
                "Existing votes still point to this design correctly (they're stored by ID), "
                "but consider announcing the name change to voters."
            )
        await interaction.response.send_message(
            f"✅ Design **{updated['number']}** updated: **{updated['name']}**{who}{note}",
            ephemeral=True,
        )

    # -- /deletedesign --------------------------------------------------------
    @app_commands.command(name="deletedesign", description="Remove a design from the current festival (admin)")
    @app_commands.describe(design_number="The design number to remove (e.g. 3)")
    @is_admin()
    async def deletedesign(self, interaction: discord.Interaction, design_number: int):
        festival = db.get_active_festival(interaction.guild_id)
        if not festival:
            await interaction.response.send_message(
                "⚠️ There's no active festival.", ephemeral=True
            )
            return

        if festival["status"] != "setup":
            await interaction.response.send_message(
                "⚠️ Designs can only be deleted while the festival is still being set up "
                "(before `/startvote`). Deleting one after voting has started would corrupt "
                "any ballots already cast for it.",
                ephemeral=True,
            )
            return

        design = db.get_design_by_number(festival["id"], design_number)
        if not design:
            await interaction.response.send_message(
                f"⚠️ No design numbered **{design_number}** found in the current festival.",
                ephemeral=True,
            )
            return

        db.remove_design(design["id"])
        await interaction.response.send_message(
            f"🗑️ Removed Design **{design_number} — {design['name']}**. "
            f"Note: remaining design numbers were not renumbered.",
            ephemeral=True,
        )

    # -- /ballots -------------------------------------------------------------
    @app_commands.command(
        name="ballots",
        description="See exactly who voted for what — breaks anonymity, admin only",
    )
    @is_admin()
    async def ballots(self, interaction: discord.Interaction):
        festival = db.get_latest_festival(interaction.guild_id)
        if not festival:
            await interaction.response.send_message(
                "⚠️ There's no festival yet.", ephemeral=True
            )
            return

        ballots = db.get_ballots(festival["id"])
        if not ballots:
            await interaction.response.send_message(
                "No ballots have been cast yet.", ephemeral=True
            )
            return

        lines = []
        for b in ballots:
            lines.append(
                f"<@{b['user_id']}>: "
                f"🥇 Design {b['first_number']} ({b['first_name']}) — "
                f"🥈 Design {b['second_number']} ({b['second_name']}) — "
                f"🥉 Design {b['third_number']} ({b['third_name']})"
            )
        full_text = "\n".join(lines)

        header = f"🗳️ {len(ballots)} ballot(s) cast in festival #{festival['id']}\n\n"

        if len(header) + len(full_text) <= 4000:
            embed = discord.Embed(
                title="Ballots (admin only)",
                description=header + full_text,
                color=discord.Color.orange(),
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
        else:
            # Too many to fit in an embed — send as a text file instead.
            buffer = io.BytesIO((header + full_text).encode("utf-8"))
            file = discord.File(buffer, filename=f"ballots_festival_{festival['id']}.txt")
            await interaction.response.send_message(
                f"🗳️ {len(ballots)} ballot(s) — too many to show inline, see attached file.",
                file=file,
                ephemeral=True,
            )

    # -- /startvote -----------------------------------------------------------
    @app_commands.command(name="startvote", description="Post the festival and open voting (admin)")
    @is_admin()
    async def startvote(self, interaction: discord.Interaction):
        festival = db.get_active_festival(interaction.guild_id)
        if not festival or festival["status"] != "setup":
            await interaction.response.send_message(
                "⚠️ No festival is ready to start. Run `/setupvote` and `/adddesign` first.",
                ephemeral=True,
            )
            return

        designs = db.get_designs(festival["id"])
        if len(designs) < 3:
            await interaction.response.send_message(
                "⚠️ Add at least 3 designs with `/adddesign` before starting voting.",
                ephemeral=True,
            )
            return

        lines = []
        for d in designs:
            who = f" — <@{d['submitter_id']}>" if d["submitter_id"] else ""
            lines.append(f"🖼️ Design {d['number']} — {d['name']}{who}")

        embed = discord.Embed(
            title="🏆 DESIGN FESTIVAL",
            description=(
                "Choose your **top 3 designs**.\n\n"
                "🥇 First Choice — **5 points**\n"
                "🥈 Second Choice — **3 points**\n"
                "🥉 Third Choice — **1 point**\n\n"
                "Your votes are anonymous, and you get **one ballot**.\n\n"
                "**Designs**\n" + "\n".join(lines)
            ),
            color=discord.Color.gold(),
        )

        db.set_festival_status(festival["id"], "voting")
        await interaction.response.send_message(embed=embed, view=FestivalPostView())
        message = await interaction.original_response()
        db.set_festival_message(festival["id"], message.id)

    # -- /results ---------------------------------------------------------------
    @app_commands.command(name="results", description="Show current Design Festival results (admin)")
    @is_admin()
    async def results(self, interaction: discord.Interaction):
        # Uses get_latest_festival (not get_active_festival) so results still
        # work after /endvote has closed the festival.
        festival = db.get_latest_festival(interaction.guild_id)
        if not festival:
            await interaction.response.send_message(
                "⚠️ There's no festival yet — run `/setupvote` to create one.", ephemeral=True
            )
            return

        if festival["status"] == "setup":
            await interaction.response.send_message(
                "⚠️ Voting hasn't started yet for the current festival — run `/startvote` first.",
                ephemeral=True,
            )
            return

        results = db.get_results(festival["id"])
        if not results:
            await interaction.response.send_message(
                "No designs have been added yet.", ephemeral=True
            )
            return

        medals = ["🥇", "🥈", "🥉"]
        lines = []
        for i, r in enumerate(results):
            marker = medals[i] if i < 3 else f"{i + 1}️⃣"
            lines.append(f"{marker} Design {r['design']['number']} — {r['design']['name']} — {r['points']} pts")

        vote_count = db.get_vote_count(festival["id"])
        status_note = " (voting still open)" if festival["status"] == "voting" else ""
        embed = discord.Embed(
            title="🏆 DESIGN FESTIVAL RESULTS",
            description="\n".join(lines),
            color=discord.Color.gold(),
        )
        embed.set_footer(text=f"{vote_count} ballot(s) cast{status_note}")
        await interaction.response.send_message(embed=embed)

    # -- /endvote -----------------------------------------------------------
    @app_commands.command(name="endvote", description="Close voting for the current festival (admin)")
    @is_admin()
    async def endvote(self, interaction: discord.Interaction):
        festival = db.get_active_festival(interaction.guild_id)
        if not festival:
            await interaction.response.send_message(
                "⚠️ There's no active festival.", ephemeral=True
            )
            return

        db.set_festival_status(festival["id"], "ended")
        await interaction.response.send_message(
            f"🔒 Voting closed for festival #{festival['id']}. Run `/results` any time to see the tally.",
            ephemeral=True,
        )

    async def cog_app_command_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ):
        if isinstance(error, (app_commands.CheckFailure, app_commands.MissingPermissions)):
            await interaction.response.send_message(
                "⚠️ You don't have permission to use this command. Ask a server admin to run "
                "`/setadminrole` and assign you the festival admin role.",
                ephemeral=True,
            )
        else:
            raise error


async def setup(bot: commands.Bot):
    await bot.add_cog(FestivalCog(bot))

