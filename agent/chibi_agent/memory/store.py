"""SQLite memory: facts about Kryo, conversation summaries, messages, reminders.

Vectors live in sqlite-vec tables keyed by the row id of their fact or
conversation (cosine distance; nomic-embed-text's 768 dims). One connection,
used from the agent's event loop only.
"""
from __future__ import annotations

import sqlite3
import struct
import time
from dataclasses import dataclass
from pathlib import Path

import sqlite_vec

DIM = 768
SCHEMA = f"""
CREATE TABLE IF NOT EXISTS facts (
    id INTEGER PRIMARY KEY, text TEXT NOT NULL, source TEXT NOT NULL,
    created REAL NOT NULL, last_used REAL);
CREATE VIRTUAL TABLE IF NOT EXISTS vec_facts USING vec0(embedding float[{DIM}] distance_metric=cosine);
CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY, started REAL NOT NULL, ended REAL, summary TEXT, extracted INTEGER DEFAULT 0);
CREATE VIRTUAL TABLE IF NOT EXISTS vec_convs USING vec0(embedding float[{DIM}] distance_metric=cosine);
CREATE TABLE IF NOT EXISTS messages (
    conv_id INTEGER NOT NULL REFERENCES conversations(id), role TEXT NOT NULL,
    content TEXT NOT NULL, ts REAL NOT NULL);
CREATE TABLE IF NOT EXISTS reminders (
    id INTEGER PRIMARY KEY, text TEXT NOT NULL, due REAL NOT NULL, created REAL NOT NULL,
    state TEXT NOT NULL DEFAULT 'pending');  -- pending | fired | cancelled
CREATE INDEX IF NOT EXISTS reminders_due ON reminders(state, due);
CREATE TABLE IF NOT EXISTS mail (  -- labels for the briefing; never bodies or snippets
    key TEXT PRIMARY KEY, account TEXT NOT NULL, sender TEXT NOT NULL, subject TEXT NOT NULL,
    received REAL NOT NULL, label TEXT NOT NULL, reason TEXT NOT NULL DEFAULT '',
    state TEXT NOT NULL DEFAULT 'new', seen REAL NOT NULL);  -- new | announced | briefed
CREATE INDEX IF NOT EXISTS mail_received ON mail(received);
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


def blob(vec: list[float]) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)


@dataclass
class Hit:
    id: int
    text: str
    similarity: float


@dataclass
class Reminder:
    id: int
    text: str
    due: float
    state: str


@dataclass
class MailRow:
    key: str       # "<account>:<message id>"
    account: str
    sender: str    # a name, never an address
    subject: str
    received: float
    label: str     # urgent | reply | bill | info | promo
    reason: str = ""
    state: str = "new"  # new | announced | briefed


class Store:
    def __init__(self, path: Path | str):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path))
        self.db.enable_load_extension(True)
        sqlite_vec.load(self.db)
        self.db.enable_load_extension(False)
        self.db.executescript(SCHEMA)
        self.db.commit()

    def close(self) -> None:
        self.db.close()

    # --- facts --------------------------------------------------------------------------
    def add_fact(self, text: str, vec: list[float], source: str) -> int:
        cur = self.db.execute("INSERT INTO facts(text, source, created) VALUES (?,?,?)",
                              (text, source, time.time()))
        self.db.execute("INSERT INTO vec_facts(rowid, embedding) VALUES (?,?)", (cur.lastrowid, blob(vec)))
        self.db.commit()
        return cur.lastrowid

    def replace_fact(self, fact_id: int, text: str, vec: list[float]) -> None:
        self.db.execute("UPDATE facts SET text=?, created=? WHERE id=?", (text, time.time(), fact_id))
        self.db.execute("DELETE FROM vec_facts WHERE rowid=?", (fact_id,))
        self.db.execute("INSERT INTO vec_facts(rowid, embedding) VALUES (?,?)", (fact_id, blob(vec)))
        self.db.commit()

    def delete_facts(self, ids: list[int]) -> None:
        for i in ids:
            self.db.execute("DELETE FROM facts WHERE id=?", (i,))
            self.db.execute("DELETE FROM vec_facts WHERE rowid=?", (i,))
        self.db.commit()

    def search_facts(self, vec: list[float], k: int = 5, min_sim: float = 0.0) -> list[Hit]:
        rows = self.db.execute(
            "SELECT f.id, f.text, v.distance FROM vec_facts v JOIN facts f ON f.id = v.rowid "
            "WHERE v.embedding MATCH ? AND k = ? ORDER BY v.distance", (blob(vec), k)).fetchall()
        hits = [Hit(i, t, 1 - d) for i, t, d in rows if 1 - d >= min_sim]
        if hits:
            now = time.time()
            self.db.executemany("UPDATE facts SET last_used=? WHERE id=?", [(now, h.id) for h in hits])
            self.db.commit()
        return hits

    def all_facts(self) -> list[tuple[int, str]]:
        return self.db.execute("SELECT id, text FROM facts ORDER BY created").fetchall()

    # --- conversations -----------------------------------------------------------------------
    def new_conversation(self) -> int:
        cur = self.db.execute("INSERT INTO conversations(started) VALUES (?)", (time.time(),))
        self.db.commit()
        return cur.lastrowid

    def log(self, conv_id: int, role: str, content: str) -> None:
        self.db.execute("INSERT INTO messages VALUES (?,?,?,?)", (conv_id, role, content, time.time()))
        self.db.execute("UPDATE conversations SET ended=? WHERE id=?", (time.time(), conv_id))
        self.db.commit()

    def messages(self, conv_id: int) -> list[tuple[str, str]]:
        return self.db.execute("SELECT role, content FROM messages WHERE conv_id=? ORDER BY ts",
                               (conv_id,)).fetchall()

    def unextracted(self, before: float) -> list[int]:
        """Conversations that ended before `before` and haven't been mined for facts yet."""
        return [r[0] for r in self.db.execute(
            "SELECT id FROM conversations WHERE extracted=0 AND ended IS NOT NULL AND ended < ?", (before,))]

    def set_summary(self, conv_id: int, summary: str, vec: list[float] | None) -> None:
        self.db.execute("UPDATE conversations SET summary=?, extracted=1 WHERE id=?", (summary, conv_id))
        if vec is not None:
            self.db.execute("DELETE FROM vec_convs WHERE rowid=?", (conv_id,))
            self.db.execute("INSERT INTO vec_convs(rowid, embedding) VALUES (?,?)", (conv_id, blob(vec)))
        self.db.commit()

    def search_summaries(self, vec: list[float], k: int = 2, min_sim: float = 0.0) -> list[Hit]:
        rows = self.db.execute(
            "SELECT c.id, c.summary, v.distance FROM vec_convs v JOIN conversations c ON c.id = v.rowid "
            "WHERE v.embedding MATCH ? AND k = ? ORDER BY v.distance", (blob(vec), k)).fetchall()
        return [Hit(i, t, 1 - d) for i, t, d in rows if t and 1 - d >= min_sim]

    # --- reminders -------------------------------------------------------------------------------
    def add_reminder(self, text: str, due: float) -> int:
        cur = self.db.execute("INSERT INTO reminders(text, due, created) VALUES (?,?,?)", (text, due, time.time()))
        self.db.commit()
        return cur.lastrowid

    def pending_reminders(self) -> list[Reminder]:
        return [Reminder(*r) for r in self.db.execute(
            "SELECT id, text, due, state FROM reminders WHERE state='pending' ORDER BY due")]

    def set_reminder_state(self, rid: int, state: str) -> None:
        self.db.execute("UPDATE reminders SET state=? WHERE id=?", (state, rid))
        self.db.commit()

    # --- mail labels (M5) --------------------------------------------------------------------------
    def known_mail_keys(self, keys: list[str]) -> set[str]:
        if not keys:
            return set()
        marks = ",".join("?" * len(keys))
        return {r[0] for r in self.db.execute(f"SELECT key FROM mail WHERE key IN ({marks})", keys)}

    def add_mail(self, m: MailRow) -> None:
        self.db.execute("INSERT OR IGNORE INTO mail(key, account, sender, subject, received, label, reason, "
                        "state, seen) VALUES (?,?,?,?,?,?,?,?,?)",
                        (m.key, m.account, m.sender, m.subject, m.received, m.label, m.reason, m.state,
                         time.time()))
        self.db.commit()

    def mail_since(self, since: float, labels: tuple[str, ...], states: tuple[str, ...]) -> list[MailRow]:
        q = (f"SELECT key, account, sender, subject, received, label, reason, state FROM mail "
             f"WHERE received >= ? AND label IN ({','.join('?' * len(labels))}) "
             f"AND state IN ({','.join('?' * len(states))}) ORDER BY received")
        return [MailRow(*r) for r in self.db.execute(q, (since, *labels, *states))]

    def set_mail_state(self, keys: list[str], state: str) -> None:
        self.db.executemany("UPDATE mail SET state=? WHERE key=?", [(state, k) for k in keys])
        self.db.commit()

    def prune_mail(self, before: float) -> None:
        self.db.execute("DELETE FROM mail WHERE received < ?", (before,))
        self.db.commit()

    # --- small settings ----------------------------------------------------------------------------
    def get_kv(self, key: str, default: str = "") -> str:
        row = self.db.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        return row[0] if row else default

    def set_kv(self, key: str, value: str) -> None:
        self.db.execute("INSERT INTO kv(key, value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                        (key, value))
        self.db.commit()
