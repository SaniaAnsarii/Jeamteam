"""
database.py
Simple synchronous SQLite layer for the ZeamTeam design festival voting bot.

Schema:
    festivals(id, guild_id, channel_id, message_id, status, created_at)
        status: 'setup' -> 'voting' -> 'ended'
    designs(id, festival_id, number, name, submitter_id)
    votes(id, festival_id, user_id, first_design_id, second_design_id, third_design_id)
        UNIQUE(festival_id, user_id) -> enforces one ballot per user per festival
"""

import sqlite3
from contextlib import contextmanager

DB_PATH = "votes.db"


def init_db():
    with get_conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS festivals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                channel_id INTEGER,
                message_id INTEGER,
                status TEXT NOT NULL DEFAULT 'setup',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS designs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                festival_id INTEGER NOT NULL,
                number INTEGER NOT NULL,
                name TEXT NOT NULL,
                submitter_id INTEGER,
                FOREIGN KEY (festival_id) REFERENCES festivals (id)
            );

            CREATE TABLE IF NOT EXISTS votes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                festival_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                first_design_id INTEGER NOT NULL,
                second_design_id INTEGER NOT NULL,
                third_design_id INTEGER NOT NULL,
                UNIQUE (festival_id, user_id),
                FOREIGN KEY (festival_id) REFERENCES festivals (id)
            );

            CREATE TABLE IF NOT EXISTS settings (
                guild_id INTEGER PRIMARY KEY,
                admin_role_id INTEGER
            );
            """
        )


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Festivals
# ---------------------------------------------------------------------------

def create_festival(guild_id: int, channel_id: int) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO festivals (guild_id, channel_id, status) VALUES (?, ?, 'setup')",
            (guild_id, channel_id),
        )
        return cur.lastrowid


def get_active_festival(guild_id: int):
    """Returns the most recent festival for this guild that isn't ended, or None."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM festivals WHERE guild_id = ? AND status != 'ended' "
            "ORDER BY id DESC LIMIT 1",
            (guild_id,),
        ).fetchone()
        return dict(row) if row else None


def get_festival(festival_id: int):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM festivals WHERE id = ?", (festival_id,)).fetchone()
        return dict(row) if row else None


def get_latest_festival(guild_id: int):
    """Returns the most recent festival for this guild regardless of status
    (setup, voting, or ended). Use this for /results so it still works after
    voting has been closed. Use get_active_festival for anything that should
    only touch a festival that's still being set up or voted on."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM festivals WHERE guild_id = ? ORDER BY id DESC LIMIT 1",
            (guild_id,),
        ).fetchone()
        return dict(row) if row else None


def set_festival_message(festival_id: int, message_id: int):
    with get_conn() as conn:
        conn.execute(
            "UPDATE festivals SET message_id = ? WHERE id = ?", (message_id, festival_id)
        )


def set_festival_status(festival_id: int, status: str):
    with get_conn() as conn:
        conn.execute("UPDATE festivals SET status = ? WHERE id = ?", (status, festival_id))


# ---------------------------------------------------------------------------
# Designs
# ---------------------------------------------------------------------------

def add_design(festival_id: int, name: str, submitter_id: int | None) -> tuple[int, int]:
    """Adds a design, auto-numbering it. Returns (design_id, number)."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COALESCE(MAX(number), 0) + 1 AS next_num FROM designs WHERE festival_id = ?",
            (festival_id,),
        ).fetchone()
        number = row["next_num"]
        cur = conn.execute(
            "INSERT INTO designs (festival_id, number, name, submitter_id) VALUES (?, ?, ?, ?)",
            (festival_id, number, name, submitter_id),
        )
        return cur.lastrowid, number


def get_designs(festival_id: int):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM designs WHERE festival_id = ? ORDER BY number", (festival_id,)
        ).fetchall()
        return [dict(r) for r in rows]


def get_design(design_id: int):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM designs WHERE id = ?", (design_id,)).fetchone()
        return dict(row) if row else None


def get_design_by_number(festival_id: int, number: int):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM designs WHERE festival_id = ? AND number = ?",
            (festival_id, number),
        ).fetchone()
        return dict(row) if row else None


def update_design(design_id: int, name: str | None = None, submitter_id: int | None = None):
    """Updates whichever fields are provided (None means 'leave unchanged')."""
    fields, values = [], []
    if name is not None:
        fields.append("name = ?")
        values.append(name)
    if submitter_id is not None:
        fields.append("submitter_id = ?")
        values.append(submitter_id)
    if not fields:
        return
    values.append(design_id)
    with get_conn() as conn:
        conn.execute(f"UPDATE designs SET {', '.join(fields)} WHERE id = ?", values)


def remove_design(design_id: int):
    with get_conn() as conn:
        conn.execute("DELETE FROM designs WHERE id = ?", (design_id,))


# ---------------------------------------------------------------------------
# Votes
# ---------------------------------------------------------------------------

def has_voted(festival_id: int, user_id: int) -> bool:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM votes WHERE festival_id = ? AND user_id = ?", (festival_id, user_id)
        ).fetchone()
        return row is not None


def record_vote(festival_id: int, user_id: int, first_id: int, second_id: int, third_id: int):
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO votes
               (festival_id, user_id, first_design_id, second_design_id, third_design_id)
               VALUES (?, ?, ?, ?, ?)""",
            (festival_id, user_id, first_id, second_id, third_id),
        )


def get_results(festival_id: int):
    """Returns designs sorted by total points, each with a points breakdown."""
    designs = get_designs(festival_id)
    points_by_design = {d["id"]: 0 for d in designs}

    with get_conn() as conn:
        votes = conn.execute(
            "SELECT * FROM votes WHERE festival_id = ?", (festival_id,)
        ).fetchall()

    for v in votes:
        points_by_design[v["first_design_id"]] = points_by_design.get(v["first_design_id"], 0) + 5
        points_by_design[v["second_design_id"]] = points_by_design.get(v["second_design_id"], 0) + 3
        points_by_design[v["third_design_id"]] = points_by_design.get(v["third_design_id"], 0) + 1

    results = [
        {"design": d, "points": points_by_design.get(d["id"], 0)} for d in designs
    ]
    results.sort(key=lambda r: r["points"], reverse=True)
    return results


def get_vote_count(festival_id: int) -> int:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM votes WHERE festival_id = ?", (festival_id,)
        ).fetchone()
        return row["c"]


def get_ballots(festival_id: int):
    """Returns every individual ballot for this festival, each with the voter's
    user_id and their three picks (design number + name for each rank).
    Admin-only use — this breaks per-vote anonymity by design."""
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT
                v.user_id,
                d1.number AS first_number,  d1.name AS first_name,
                d2.number AS second_number, d2.name AS second_name,
                d3.number AS third_number,  d3.name AS third_name
            FROM votes v
            JOIN designs d1 ON d1.id = v.first_design_id
            JOIN designs d2 ON d2.id = v.second_design_id
            JOIN designs d3 ON d3.id = v.third_design_id
            WHERE v.festival_id = ?
            ORDER BY v.id
            """,
            (festival_id,),
        ).fetchall()
        return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Settings (per-guild admin role for festival management)
# ---------------------------------------------------------------------------

def get_admin_role(guild_id: int) -> int | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT admin_role_id FROM settings WHERE guild_id = ?", (guild_id,)
        ).fetchone()
        return row["admin_role_id"] if row and row["admin_role_id"] else None


def set_admin_role(guild_id: int, role_id: int | None):
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO settings (guild_id, admin_role_id) VALUES (?, ?)
               ON CONFLICT(guild_id) DO UPDATE SET admin_role_id = excluded.admin_role_id""",
            (guild_id, role_id),
        )
