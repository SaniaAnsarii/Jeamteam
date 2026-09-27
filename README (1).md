# ZeamTeam — Design Festival Voting Bot
## Command Reference & How It Works

---

## 1. Overview

ZeamTeam runs a ranked-choice voting system for a "design festival" inside
any Discord server it's added to. Admins add design entries, members
privately rank their top 3, and the bot tallies weighted results
automatically:

```
1st choice = 5 points
2nd choice = 3 points
3rd choice = 1 point
```

The bot works in **every server it's invited to at once** — each server's
festivals, designs, and votes are kept completely separate (everything is
scoped by the server's Discord ID under the hood).

---

## 2. Who can do what

Two tiers of access:

| Tier | Can run | How they get it |
|---|---|---|
| **Real server admins** | Every command, always | Anyone with Discord's built-in **Manage Server** permission — this is a permanent override so you can never lock yourself out |
| **Festival organizers** | Everything except changing who's an organizer | Whichever single role is assigned via `/setadminrole` |
| **Everyone** | Voting only | No role needed — clicking **Cast Your Vote** and submitting a ballot works for any server member |

### `/setadminrole`
**Who can run it:** only someone with real **Manage Server** permission (not
the festival-organizer role itself — this is deliberate, so an organizer
can't grant themselves more power).

```
/setadminrole role:@Festival Organizer
```
Designates one role whose members can run every festival-management command
below. Run it once per server; re-run it any time to change which role is
trusted.

---

## 3. Running a festival, command by command

### `/setupvote`
Creates a new festival in **setup** mode for the current server. Only one
festival can be active (not yet ended) per server at a time — if you try to
run this while one already exists, it tells you its current status instead
of creating a duplicate.

### `/adddesign name:"..." submitter:@user`
Adds a single design entry. Both fields are **required** — `submitter` can
no longer be left blank. Designs are auto-numbered in the order you add them
(1, 2, 3, ...). Only works while the festival is in **setup**.

### `/adddesigns entries:"..."`
Bulk version — add many designs in one command. Paste one design per line:
```
Design A - @Sania
Design B - @Twan
Design C - @Jadie
```
Type `@` inside the field and pick the user from Discord's own suggestion
list so it becomes a real mention (plain typed names won't parse). The bot
reports how many were added and lists any lines it couldn't parse (missing
mention, or nothing left after removing the mention). Only works during
**setup**.

### `/editdesign design_number:3 name:"..." submitter:@user`
Edits an existing design by its **number** (not an internal ID — use the
number shown when it was added, or in the public festival post). Both
`name` and `submitter` are optional here — leave either blank to keep it
unchanged. Works during setup *or* after voting has opened (existing votes
still point to the right design, since votes are stored by internal ID —
but the already-posted public embed won't auto-update, so you'd need to
announce any change to voters yourself).

### `/deletedesign design_number:3`
Removes a design entirely. **Only works during setup** — blocked once
voting has started, since deleting a design with votes already cast for it
would silently drop those points from the final tally.

### `/startvote`
Posts the public festival embed (listing every design) with a **Cast Your
Vote** button, and flips the festival to **voting** status. Requires at
least 3 designs to be added first.

### `/results`
Computes and posts the current point totals, ranked highest to lowest.
Works **before, during, or after** voting closes — it always looks at the
most recent festival for the server regardless of its status (this was a
bug fix: it used to only find festivals that weren't ended yet, so
`/results` broke right after `/endvote`).

### `/ballots`
**Admin only.** Shows exactly who voted for what — every ballot, with the
voter's name and their 3 picks. This deliberately breaks the "anonymous"
framing shown to voters in the public post, so treat it as a
behind-the-scenes audit tool, not something to share publicly. If there are
too many ballots to fit in one message, it automatically sends a `.txt`
file attachment instead.

### `/endvote`
Closes voting for the current festival (status → **ended**). No more
ballots can be submitted after this. `/results` and `/ballots` both still
work afterward.

---

## 4. The voting flow (anyone, no role needed)

1. A member clicks **Cast Your Vote** on the public festival post.
2. They get a **private, ephemeral panel** — only they can see it — with
   three dropdowns: 🥇 First (5 pts), 🥈 Second (3 pts), 🥉 Third (1 pt).
3. **Their own submitted design(s) are automatically excluded** from all
   three dropdowns — you can't vote for yourself. (If excluding your own
   design(s) would leave fewer than 3 to choose from, you'll get a message
   instead of a broken panel.)
4. They pick one design per dropdown and hit **Submit Vote**. At that point
   the bot checks, in order:
   - All three ranks must be filled in.
   - The three picks must be three **different designs**.
   - None of the three picks can be a design **you** submitted (re-checked
     here too, in case `/editdesign` changed a design's submitter after the
     panel was opened).
   - The three picks can't be designs from the **same submitter** — even if
     one person has multiple entries (common now with `/adddesigns`), a
     single voter can only give that person one of their three ranks.
   - You haven't already voted in this festival (enforced both in code and
     by a database constraint, so it's safe even against a fast
     double-click).
5. On success, they see a private confirmation of exactly what they voted
   for, and the panel's controls disable themselves.

---

## 5. How it works across multiple servers

Slash commands can be registered two ways: **globally** (works everywhere,
but can take up to an hour to appear after a change) or **per-server**
(shows up instantly, but only for that one server unless you sync it to
each one).

The bot now does the per-server sync **automatically, for every server it's
in**:
- On startup, it loops through every server currently in `bot.guilds` and
  syncs commands to each one instantly.
- The moment it's invited to a **new** server (`on_guild_join`), it syncs
  that server immediately too — no restart needed.

This replaced the old setup, which only ever instantly-synced to one
hardcoded `GUILD_ID` from `.env`. That variable is no longer read anywhere
in the code — safe to delete from your environment variables.

All festival/design/vote data is already scoped by server ID in the
database, so running in multiple servers was always safe on the data side;
the only missing piece was command registration, which is fixed now.

To let other servers add the bot at all, share your bot's OAuth2 install
link from the Discord Developer Portal (Installation → Install Link) — that
grants any server owner the ability to add it themselves.
