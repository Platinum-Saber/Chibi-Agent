"""Clear what Raphael remembers and give her a fresh starting memory.

Backs up memory.db first (memory.db.bak-<date-time>), then deletes her facts and conversation
history (facts, conversations, messages and their vectors). Reminders, the mail and notification
labels for briefings, and settings stay. Then it loads the starting facts, one per line, from
profile.txt beside her data (ChibiAgent\\profile.txt, outside git; # lines are comments).

Quit Raphael first (she holds the database). Ollama must be running (the facts are embedded).
Run it from your own terminal, with the agent's venv:

    agent\\.venv\\Scripts\\python tools\\reset_memory.py [--db PATH] [--profile PATH]
"""
from __future__ import annotations

import argparse
import asyncio
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent"))

from chibi_shared import config, paths  # noqa: E402

PROFILE = ROOT.parent / "ChibiAgent" / "profile.txt"
CLEARED = ("facts", "vec_facts", "messages", "conversations", "vec_convs")


def agent_running() -> bool:
    import ctypes
    k32 = ctypes.windll.kernel32
    h = k32.OpenMutexW(0x00100000, False, r"Local\ChibiAgent.agent")  # SYNCHRONIZE
    if h:
        k32.CloseHandle(h)
    return bool(h)


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=paths.DATA / "memory.db")
    ap.add_argument("--profile", type=Path, default=PROFILE)
    args = ap.parse_args()
    if args.db == paths.DATA / "memory.db" and agent_running():
        sys.exit("Raphael is running: quit her from the tray first.")
    facts = [ln.strip() for ln in args.profile.read_text(encoding="utf-8").splitlines()
             if ln.strip() and not ln.lstrip().startswith("#")]

    from chibi_agent.memory import Memory
    from chibi_agent.memory.store import Store
    if args.db.exists():
        bak = args.db.with_name(f"{args.db.name}.bak-{time.strftime('%Y%m%d-%H%M%S')}")
        shutil.copy2(args.db, bak)
        print(f"backup: {bak}")
    store = Store(args.db)
    before = store.db.execute("SELECT count(*) FROM facts").fetchone()[0]
    convs = store.db.execute("SELECT count(*) FROM conversations").fetchone()[0]
    for table in CLEARED:
        store.db.execute(f"DELETE FROM {table}")
    store.db.commit()
    store.db.execute("VACUUM")
    print(f"cleared {before} facts and {convs} conversations")
    mem = Memory(config.load()["ollama"], store)
    for f in facts:
        await mem.remember(f, source="profile")
    print(f"loaded {len(store.all_facts())} starting facts from {args.profile}")
    await mem.embed.close()
    store.close()


if __name__ == "__main__":
    asyncio.run(main())
