"""
views/voting_view.py
Discord UI components for the voting flow:
    FestivalPostView  -> the public embed's "Cast your vote" button
    VotingPanelView   -> the private ephemeral panel with 3 dropdowns + submit
"""

import discord

import database as db

PLACE_LABELS = {
    "first": ("🥇 First Choice", 5),
    "second": ("🥈 Second Choice", 3),
    "third": ("🥉 Third Choice", 1),
}


def _design_options(designs: list[dict]) -> list[discord.SelectOption]:
    options = []
    for d in designs:
        label = f"Design {d['number']} — {d['name']}"
        options.append(discord.SelectOption(label=label[:100], value=str(d["id"])))
    return options


class DesignSelect(discord.ui.Select):
    """One dropdown for one of the three ranked choices."""

    def __init__(self, place: str, designs: list[dict]):
        self.place = place
        label, points = PLACE_LABELS[place]
        super().__init__(
            placeholder=f"{label} — {points} points",
            min_values=1,
            max_values=1,
            options=_design_options(designs),
        )

    async def callback(self, interaction: discord.Interaction):
        # Store the selection on the parent view, then just acknowledge.
        view: "VotingPanelView" = self.view
        view.selections[self.place] = int(self.values[0])
        await interaction.response.defer()


class SubmitButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Submit Vote", style=discord.ButtonStyle.success, emoji="🗳️")

    async def callback(self, interaction: discord.Interaction):
        view: "VotingPanelView" = self.view
        await view.submit(interaction)


class VotingPanelView(discord.ui.View):
    """Ephemeral panel shown only to the voter."""

    def __init__(self, festival_id: int, designs: list[dict]):
        super().__init__(timeout=300)
        self.festival_id = festival_id
        self.designs = designs
        self.selections: dict[str, int] = {}

        self.add_item(DesignSelect("first", designs))
        self.add_item(DesignSelect("second", designs))
        self.add_item(DesignSelect("third", designs))
        self.add_item(SubmitButton())

    async def submit(self, interaction: discord.Interaction):
        if len(self.selections) < 3:
            await interaction.response.send_message(
                "⚠️ Please choose a design for all three ranks before submitting.",
                ephemeral=True,
            )
            return

        first_id = self.selections["first"]
        second_id = self.selections["second"]
        third_id = self.selections["third"]

        if len({first_id, second_id, third_id}) < 3:
            await interaction.response.send_message(
                "⚠️ You cannot select the same design more than once. "
                "Please choose three different designs.",
                ephemeral=True,
            )
            return

        # Safety-net check: the dropdowns already exclude the voter's own
        # design(s), but re-verify here in case a design's submitter was
        # changed (via /editdesign) after this panel was opened.
        picked_designs = []
        for design_id in (first_id, second_id, third_id):
            design = db.get_design(design_id)
            if design and design["submitter_id"] == interaction.user.id:
                await interaction.response.send_message(
                    "⚠️ You can't vote for your own design. Please reopen "
                    "**Cast Your Vote** and choose again.",
                    ephemeral=True,
                )
                return
            picked_designs.append(design)

        # A single submitter can have multiple designs entered (e.g. via
        # /adddesigns), but one voter can't give the same person more than
        # one of their three ranks.
        submitter_ids = [d["submitter_id"] for d in picked_designs if d and d["submitter_id"]]
        if len(submitter_ids) != len(set(submitter_ids)):
            await interaction.response.send_message(
                "⚠️ Two or more of your picks were submitted by the same person. "
                "Each of your three ranks must go to a different submitter.",
                ephemeral=True,
            )
            return

        if db.has_voted(self.festival_id, interaction.user.id):
            await interaction.response.send_message(
                "⚠️ You have already voted in this Design Festival. You cannot change your vote.",
                ephemeral=True,
            )
            return

        try:
            db.record_vote(self.festival_id, interaction.user.id, first_id, second_id, third_id)
        except Exception:
            await interaction.response.send_message(
                "⚠️ You have already voted in this Design Festival.", ephemeral=True
            )
            return

        first = db.get_design(first_id)
        second = db.get_design(second_id)
        third = db.get_design(third_id)

        for item in self.children:
            item.disabled = True

        embed = discord.Embed(title="✅ Your vote has been submitted!", color=discord.Color.green())
        embed.add_field(name="🥇 First (5 pts)", value=f"Design {first['number']} — {first['name']}", inline=False)
        embed.add_field(name="🥈 Second (3 pts)", value=f"Design {second['number']} — {second['name']}", inline=False)
        embed.add_field(name="🥉 Third (1 pt)", value=f"Design {third['number']} — {third['name']}", inline=False)
        embed.set_footer(text="Thank you for voting! 🏆")

        await interaction.response.edit_message(embed=embed, view=self)


class CastVoteButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            label="Cast Your Vote",
            style=discord.ButtonStyle.primary,
            emoji="🗳️",
            custom_id="zeamteam:cast_vote",
        )

    async def callback(self, interaction: discord.Interaction):
        festival = db.get_active_festival(interaction.guild_id)
        if not festival or festival["status"] != "voting":
            await interaction.response.send_message(
                "⚠️ Voting isn't open right now.", ephemeral=True
            )
            return

        if db.has_voted(festival["id"], interaction.user.id):
            await interaction.response.send_message(
                "⚠️ You have already voted in this Design Festival. You cannot change your vote.",
                ephemeral=True,
            )
            return

        designs = db.get_designs(festival["id"])
        eligible_designs = [d for d in designs if d["submitter_id"] != interaction.user.id]

        if len(eligible_designs) < 3:
            if len(eligible_designs) < len(designs):
                await interaction.response.send_message(
                    "⚠️ You can't vote — there aren't at least 3 designs left once your "
                    "own submission(s) are excluded.",
                    ephemeral=True,
                )
            else:
                await interaction.response.send_message(
                    "⚠️ Not enough designs have been added yet.", ephemeral=True
                )
            return

        panel = VotingPanelView(festival["id"], eligible_designs)
        embed = discord.Embed(
            title="🏆 DESIGN FESTIVAL — YOUR VOTE",
            description="Pick a different design for each rank, then press **Submit Vote**.\n"
            "-# Your own submitted design (if any) won't appear here.",
            color=discord.Color.blurple(),
        )
        await interaction.response.send_message(embed=embed, view=panel, ephemeral=True)


class FestivalPostView(discord.ui.View):
    """Persistent view attached to the public festival announcement message."""

    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(CastVoteButton())
